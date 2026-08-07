"""Source-selection gates for extracted requirement rows.

This module decides whether deterministic source-backed file-composition rows
are trustworthy enough to keep, or should yield to LLM extraction.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..requirements_common import _compact_text


def _source_backed_rows_need_llm_file_composition(rows: List[Dict[str, Any]]) -> bool:
    names = [
        str(item.get("name") or item.get("quote") or "").strip()
        for item in rows or []
        if isinstance(item, dict)
    ]
    names = [name for name in names if name]
    if not names:
        return False
    if any(_looks_like_instruction_file_component(name) for name in names):
        return True
    if _looks_like_authoritative_explicit_file_list(rows):
        return False
    if _source_backed_rows_have_unexpanded_groups(rows):
        return True
    if any(_looks_like_prose_file_component(name) for name in names):
        return True
    return len(names) < 3


_FILE_LIST_SECTION_TITLE_MARKERS = (
    "投标文件",
    "响应文件",
    "报价文件",
    "应答文件",
    "竞投文件",
    "报价书",
)

_FILE_LIST_ROW_MARKERS = (
    "附件",
    "原件",
    "复印件",
    "营业执照",
    "承诺函",
    "授权",
    "证明书",
    "证明",
    "截图",
    "查询",
    "报价函",
    "报价表",
    "自查表",
)

_SOURCE_BACKED_FILE_COMPOSITION_KINDS = {
    "composition_list",
    "index_table",
    "body_part_composition",
}


def _looks_like_authoritative_explicit_file_list(rows: List[Dict[str, Any]]) -> bool:
    """Keep explicit file lists from being mistaken for prose.

    A real submission list can contain long rows with semicolons and attachment
    notes, and one noisy row should not disqualify the whole list.
    """
    items = [item for item in rows or [] if isinstance(item, dict)]
    if len(items) < 3:
        return False

    auth_count = sum(1 for item in items if item.get("source_backed_authoritative"))
    if auth_count / max(len(items), 1) < 0.8:
        return False

    kind_values = [str(item.get("source_kind") or "") for item in items]
    known_kind_count = sum(1 for kind in kind_values if kind in _SOURCE_BACKED_FILE_COMPOSITION_KINDS)
    if known_kind_count / max(len(items), 1) < 0.8:
        return False
    if any(kind and kind not in _SOURCE_BACKED_FILE_COMPOSITION_KINDS for kind in kind_values):
        return False

    section_titles = [_compact_text(str(item.get("section_title") or "")) for item in items]
    has_file_list_section = any(
        any(marker in title for marker in _FILE_LIST_SECTION_TITLE_MARKERS)
        for title in section_titles
    )
    if not has_file_list_section and "index_table" not in kind_values:
        return False

    if has_file_list_section and len(items) >= 5:
        short_rows = 0
        for item in items:
            compact = _compact_text(str(item.get("name") or item.get("quote") or ""))
            if compact and len(compact) <= 90:
                short_rows += 1
        if short_rows / max(len(items), 1) >= 0.8:
            return True

    marked_rows = 0
    for item in items:
        compact = _compact_text(str(item.get("name") or item.get("quote") or ""))
        if any(marker in compact for marker in _FILE_LIST_ROW_MARKERS):
            marked_rows += 1
    return marked_rows >= 2 or marked_rows >= max(1, len(items) // 3)


def _source_backed_rows_have_unexpanded_groups(rows: List[Dict[str, Any]]) -> bool:
    items = [item for item in rows or [] if isinstance(item, dict)]
    if not items:
        return False
    if any(item.get("outline_level") and int(item.get("outline_level") or 0) > 1 for item in items):
        return False
    return any(
        _looks_like_unexpanded_group_file_component(
            str(item.get("name") or item.get("quote") or "")
        )
        for item in items
    )


def _looks_like_unexpanded_group_file_component(name: str) -> bool:
    compact = _compact_text(name)
    if not compact or len(compact) > 32:
        return False
    group_terms = (
        "资格审查资料",
        "资格证明材料",
        "资格证明文件",
        "资质证明材料",
        "资质证明文件",
        "经营资格证明文件",
        "证明材料",
        "其他资料",
        "其他材料",
        "商务文件格式",
        "技术响应文件格式",
        "响应文件格式",
    )
    return any(term in compact for term in group_terms)


def _looks_like_prose_file_component(name: str) -> bool:
    text = str(name or chr(34) + chr(34)).strip()
    stripped_text = text.rstrip("；。;.")
    compact = _compact_text(stripped_text)
    if not compact:
        return False
    sentence_marks = (chr(65292), chr(65307), chr(12290))
    if len(compact) >= 24 and any(mark in stripped_text for mark in sentence_marks):
        return True
    return False


def _looks_like_instruction_file_component(name: str) -> bool:
    text = _compact_text(name)
    if not text:
        return False
    instruction_prefixes = ("按", "按照", "根据", "依据", "参照", "对")
    instruction_refs = ("投标人须知", "招标文件", "采购文件", "磋商文件", "第三章", "第四章", "第五章", "规定")
    if text.startswith(instruction_prefixes) and any(ref in text for ref in instruction_refs):
        return True
    actor_prefixes = ("投标人应", "响应人应", "报价人应", "供应商应", "投标人须", "响应人须", "报价人须", "供应商须")
    return text.startswith(actor_prefixes) and any(ref in text for ref in instruction_refs)
