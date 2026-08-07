"""Section selection helpers for requirement extraction dimensions."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from loguru import logger

from ..requirements_common import _compact_text, _head_text_payload
from ..source_backed_composition import (
    _composition_lines_from_protected_item,
    _drop_broad_umbrella_sections,
    _extract_file_composition_list_item,
)
from .schemas import DimensionConfig
from .source_selection import _source_backed_rows_need_llm_file_composition


_DIMENSION_PRIORITY_HINTS: Dict[str, Tuple[str, ...]] = {
    "base_timeline": ("公告", "须知", "前附表", "项目概况", "基本情况", "截止", "开标", "有效期"),
    "file_composition": ("组成", "目录", "清单", "索引", "应包括", "由以下"),
    "format_template": ("格式", "模板", "范本", "附件", "附表", "密封", "盖章", "正本", "副本"),
    "qualification_review": ("资格", "资质", "资格审查", "资格性", "符合性", "营业执照", "许可证", "财务", "信用", "业绩"),
    "submission_checklist": ("提交", "提供", "材料", "资料", "证明", "授权书", "报价表", "承诺函"),
    "technical_scoring": ("评分", "评审", "技术", "商务", "价格", "综合评分", "采购需求", "服务要求"),
    "risk_contract": ("无效", "废标", "否决", "保证金", "报价要求", "最高限价", "合同", "付款", "违约"),
}


def _section_depth(section_id: Any) -> int:
    text = str(section_id or "").strip()
    if not text or text == "head_text":
        return 0
    return len([part for part in text.split(".") if part])


def _looks_like_file_format_chapter(item: Dict[str, Any]) -> bool:
    title = _compact_text(str(item.get("title") or item.get("section_title") or ""))
    relevance = _compact_text(str(item.get("relevance") or ""))
    content_head = _compact_text(str(item.get("content") or "")[:1200])
    head = f"{title}{relevance}"
    format_titles = ("投标文件格式", "响应文件格式", "报价文件格式", "应答文件格式", "竞投文件格式")
    if any(token in head for token in format_titles):
        return True
    if any(token in title for token in ("投标文件", "响应文件", "报价文件", "应答文件", "竞投文件")) and "格式" in title:
        return True
    return any(token in content_head[:240] for token in format_titles)


_QUALIFICATION_BROAD_CONTEXT_HEADS = ("总则", "定义", "项目概况", "基本情况")


def _qualification_review_head_has_signal(item: Dict[str, Any]) -> bool:
    title = _compact_text(str(item.get("title") or item.get("section_title") or ""))
    relevance = _compact_text(str(item.get("relevance") or ""))
    head = f"{title}{relevance}"
    return any(token in head for token in _DIMENSION_PRIORITY_HINTS["qualification_review"])


def _qualification_review_context_terms() -> Tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            list(_DIMENSION_PRIORITY_HINTS["qualification_review"])
            + [
                "营业执照",
                "许可证",
                "审计报告",
                "财务报表",
                "信用中国",
                "失信被执行人",
                "同类业绩",
                "类似业绩",
                "社保",
                "纳税",
                "商业信誉",
                "违法记录",
                "履行合同能力",
                "独立承担民事责任",
                "项目负责人",
                "人员证书",
            ]
        )
    )


def _compact_broad_qualification_review_item(item: Dict[str, Any]) -> Dict[str, Any] | None:
    """Keep broad base/timeline sections out of qualification LLM unless they carry evidence."""
    if _qualification_review_head_has_signal(item):
        return item

    tags = set(item.get("requirement_tags") or [])
    title = _compact_text(str(item.get("title") or item.get("section_title") or ""))
    relevance = _compact_text(str(item.get("relevance") or ""))
    is_broad_context = (
        "base_timeline" in tags
        or any(token in title for token in _QUALIFICATION_BROAD_CONTEXT_HEADS)
        or "基础信息与时间" in relevance
    )
    if not is_broad_context:
        return item

    content = str(item.get("content") or "")
    lines = content.splitlines()
    if not lines:
        return None

    terms = _qualification_review_context_terms()
    selected_indexes: set[int] = set()
    for idx, line in enumerate(lines):
        compact = _compact_text(line)
        if not compact or not any(term in compact for term in terms):
            continue
        start = max(0, idx - 1)
        end = min(len(lines), idx + 2)
        selected_indexes.update(range(start, end))

    if not selected_indexes:
        logger.info(
            "[requirements] qualification_review dropped broad base section: {} {}",
            item.get("section_id") or item.get("source_section_id") or "",
            item.get("title") or item.get("section_title") or "",
        )
        return None

    next_item = dict(item)
    next_item["content"] = "\n".join(lines[idx] for idx in sorted(selected_indexes))
    next_item["qualification_review_compacted"] = True
    return next_item


def _compact_broad_qualification_review_sections(
    selected: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    compacted: List[Dict[str, Any]] = []
    before_chars = sum(len(str(item.get("content") or "")) for item in selected)
    for item in selected:
        next_item = _compact_broad_qualification_review_item(item)
        if next_item is not None:
            compacted.append(next_item)
    after_chars = sum(len(str(item.get("content") or "")) for item in compacted)
    if len(compacted) != len(selected) or after_chars < before_chars:
        logger.info(
            "[requirements] qualification_review compacted broad sections {} -> {}, chars {} -> {}",
            len(selected),
            len(compacted),
            before_chars,
            after_chars,
        )
    return compacted


def select_dimension_candidate_sections(
    sections_payload: List[Dict[str, Any]],
    head_text: str,
    config: DimensionConfig,
) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    if config.include_head and head_text.strip():
        selected.append(_head_text_payload(head_text))

    tagged_selected = [
        item
        for item in sections_payload
        if config.name in set(item.get("requirement_tags") or [])
    ]
    selected.extend(tagged_selected)
    selected = _drop_broad_umbrella_sections(selected, config.name)
    if config.name == "qualification_review":
        selected = _compact_broad_qualification_review_sections(selected)

    protected_source_ids: set[str] = set()
    for item in sections_payload:
        if config.name != "file_composition":
            continue
        protected = _extract_file_composition_list_item(item)
        if not protected:
            continue
        protected_rows = _composition_lines_from_protected_item(protected)
        protected_items = [
            {"name": row, "quote": row}
            for row in protected_rows
        ]
        if _source_backed_rows_need_llm_file_composition(protected_items):
            selected.append(item)
            continue
        protected["requirement_tags"] = list(
            dict.fromkeys(list(protected.get("requirement_tags") or []) + ["file_composition"])
        )
        protected_source_ids.add(str(item.get("section_id") or item.get("source_section_id") or ""))
        selected.append(protected)

    if config.name == "file_composition":
        selected_keys = {
            str(item.get("chunk_id") or item.get("section_id") or id(item))
            for item in selected
        }
        format_source_keys: set[str] = set()
        for item in sections_payload:
            if not _looks_like_file_format_chapter(item):
                continue
            key = str(item.get("chunk_id") or item.get("section_id") or id(item))
            format_source_keys.add(key)
            if key in selected_keys:
                continue
            selected_keys.add(key)
            selected.append(item)
        if format_source_keys:
            attachment_body_items = [
                item
                for item in selected
                if str(item.get("source_kind") or "") == "attachment_body"
            ]
            format_items = [
                item
                for item in selected
                if str(item.get("chunk_id") or item.get("section_id") or id(item)) in format_source_keys
            ]
            if format_items:
                substantive_format_items = [
                    item
                    for item in format_items
                    if len(str(item.get("content") or "")) >= 800
                ]
                if substantive_format_items:
                    format_items = substantive_format_items
                min_depth = min(_section_depth(item.get("section_id")) for item in format_items)
                selected = [
                    item
                    for item in format_items
                    if _section_depth(item.get("section_id")) == min_depth
                ]
                selected.extend(attachment_body_items)
            protected_source_ids.clear()
        if protected_source_ids:
            selected = [
                item
                for item in selected
                if item.get("protected_list") == "file_composition"
                or str(item.get("section_id") or item.get("source_section_id") or "") not in protected_source_ids
            ]
        deduped: List[Dict[str, Any]] = []
        seen_keys: set[str] = set()
        for item in selected:
            key = str(item.get("chunk_id") or item.get("section_id") or id(item))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(item)
        selected = deduped

    if config.name == "submission_checklist":
        # A source-backed file-composition list is also the strongest checklist
        # signal. Feed only the protected list rows, not the whole surrounding
        # supplier-instruction chapter.
        seen_keys = {
            str(item.get("chunk_id") or item.get("section_id") or id(item))
            for item in selected
        }
        for item in sections_payload:
            protected = _extract_file_composition_list_item(item)
            if not protected:
                continue
            protected["requirement_tags"] = list(
                dict.fromkeys(list(protected.get("requirement_tags") or []) + ["submission_checklist"])
            )
            key = str(protected.get("chunk_id") or protected.get("section_id") or id(protected))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            selected.append(protected)

    return selected
