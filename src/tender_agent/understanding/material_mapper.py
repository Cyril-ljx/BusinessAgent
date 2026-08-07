"""Map outline leaves to source templates and company knowledge-base materials.

Deterministic certificate/template matches are resolved first. Only unresolved
nodes are sent to the bounded LLM mapper for technical-section selection.
"""

import asyncio
from difflib import SequenceMatcher
import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..config.settings import settings
from ..core.db import engine, get_db_session
from ..llm.gateway import llm_gateway

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from data.knowledge.models import Certificate, TemplateSection
from tender_agent.knowledge.certificate_filters import usable_certificate_filters

TENDER_TEMPLATE_MISSING_NOTE = "未能定位原文范本，请按招标文件格式章节人工补充"

_INDEX_CACHE: Dict[str, Dict[str, Any]] = {}
_INDEX_CACHE_LOCK = threading.RLock()
_INDEX_CACHE_MAX_COMPANIES = 64


def _company_cache_key(company_id: str) -> str:
    return str(company_id or "").strip() or "__shared__"


def _store_material_index_cache(
    company_id: str,
    certs_index: Dict[str, int],
    tech_index: List[Dict[str, Any]],
    cert_items: List[Dict[str, Any]],
) -> None:
    key = _company_cache_key(company_id)
    with _INDEX_CACHE_LOCK:
        _INDEX_CACHE[key] = {
            "certs_index": dict(certs_index),
            "tech_index": list(tech_index),
            "cert_items": list(cert_items),
            "updated_at": time.time(),
        }
        if len(_INDEX_CACHE) > _INDEX_CACHE_MAX_COMPANIES:
            oldest_key = min(
                _INDEX_CACHE,
                key=lambda item: float(_INDEX_CACHE[item].get("updated_at") or 0.0),
            )
            _INDEX_CACHE.pop(oldest_key, None)


def _read_material_index_cache(company_id: str) -> Dict[str, Any]:
    key = _company_cache_key(company_id)
    with _INDEX_CACHE_LOCK:
        cached = _INDEX_CACHE.get(key) or {}
        return {
            "certs_index": dict(cached.get("certs_index") or {}),
            "tech_index": list(cached.get("tech_index") or []),
            "cert_items": list(cached.get("cert_items") or []),
        }

class Material(BaseModel):
    source: Literal["certificate", "tech_section", "tech_section_range", "tender_template", "manual"]
    id: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    file_path: Optional[str] = None
    file_type: Optional[str] = None
    chapter_id: Optional[str] = None
    section_id: Optional[str] = None
    chapter_start: Optional[str] = None
    chapter_end: Optional[str] = None
    copy_full_section: bool = False
    max_count: Optional[int] = None
    name: Optional[str] = None
    note: Optional[str] = None
    source_section_id: Optional[str] = None
    source_anchor: Optional[str] = None
    anchor_start: Optional[str] = None
    anchor_end: Optional[str] = None
    content_preview: Optional[str] = None
    copy_method: Optional[str] = None


class Assignment(BaseModel):
    node_id: str
    node_name: str
    materials: List[Material] = Field(default_factory=list)


class MappingResult(BaseModel):
    assignments: List[Assignment]


PROMPT_TEMPLATE = """你是投标书素材匹配专家。请从每个叶子章节附带的候选中选择知识库素材。

【投标书目录及候选素材】
{outline_flat}

【素材类型】
1. certificate: 从证书库按 category 复制材料图片/文件。
示例: {{"source": "certificate", "category": "营业执照", "max_count": 1}}

2. tech_section: 从技术方案/流程母版按 chapter_id 复制章节内容。
示例: {{"source": "tech_section", "chapter_id": "1.5"}}
只有目录明确要求整体、完整方案且候选本身是完整父章节时，才设置 copy_full_section=true。

3. manual: 本项目特定内容，需要人工填写。
示例: {{"source": "manual", "note": "请填写本次报价金额"}}

4. tender_template: 招标文件原文提供的函/表/声明/承诺/授权/索引目录表等范本。
示例: {{"source": "tender_template", "name": "首次报价一览表", "source_section_id": "31", "source_anchor": "首次报价一览表"}}

【关键规则】
1. 只给叶子章节分配素材，非叶子章节不要分配。
2. 证书/执照/许可证/审计报告/信用/社保/业绩/纳税/开户 等证明类章节，优先匹配 certificate。
3. 技术方案/服务方案/流程/培训/招聘/人员管理/应急预案/质量保障 等方案类章节，优先匹配 tech_section。
4. 招标文件已提供范本时，该叶子章节只保留 tender_template，不要在同一 materials 中追加证书或技术材料；原文明示的附加材料应由对应子章节独立匹配。
5. 找不到对应知识库素材时才用 manual。
6. category 必须来自当前目录项的 certificate_candidates，chapter_id 必须来自当前目录项的 tech_candidates。
7. 根据目录 path、技术章节 full_path 和 span 判断语义；不要只因为共享“方案、实施、服务、项目”等泛词就匹配。

【输出】
严格返回 JSON，不要 markdown:
{{
  "assignments": [
    {{"node_id": "1.1", "node_name": "营业执照复印件", "materials": [{{"source": "certificate", "category": "营业执照", "max_count": 1}}]}}
  ]
}}
"""


def flatten_outline_for_prompt(
    nodes: List[Dict[str, Any]],
    result: Optional[List[Dict[str, Any]]] = None,
    parents: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    if result is None:
        result = []
    parents = list(parents or [])
    for node in nodes:
        name = str(node.get("name", ""))
        path = parents + ([name] if name else [])
        result.append(
            {
                "id": str(node.get("id", "")),
                "name": name,
                "path": " / ".join(path),
                "level": int(node.get("level", 1)),
                "is_leaf": not bool(node.get("children")),
                "has_template": bool(node.get("has_template")),
                "source": node.get("source"),
                "source_kind": node.get("source_kind"),
                "source_anchor": node.get("source_anchor"),
                "template_ref": node.get("template_ref"),
            }
        )
        if node.get("children"):
            flatten_outline_for_prompt(node.get("children") or [], result, path)
    return result


def _normalized_evidence_title(value: Any) -> str:
    text = re.sub(r"<[^>]+>", "", str(value or "")).lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def _best_located_section(
    node_name: str,
    located_sections: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    target = _normalized_evidence_title(node_name)
    if len(target) < 3:
        return None

    best: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for section in located_sections or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or section.get("section_title") or "").strip()
        candidate = _normalized_evidence_title(title)
        if len(candidate) < 3:
            continue
        if candidate == target:
            score = 100.0
        elif min(len(target), len(candidate)) >= 4 and (target in candidate or candidate in target):
            score = 86.0 - min(abs(len(target) - len(candidate)), 12)
        else:
            ratio = SequenceMatcher(None, target, candidate).ratio()
            score = ratio * 80.0 if ratio >= 0.9 else 0.0

        section_id = str(section.get("id") or section.get("section_id") or "")
        if section_id.startswith("__plain_file_directory__"):
            score -= 30.0
        if score > best_score:
            best = section
            best_score = score

    return best if best_score >= 82.0 else None


def _located_section_preview(
    section: Dict[str, Any],
    block_index: List[Dict[str, Any]],
    max_chars: int = 12000,
) -> str:
    start_anchor = str(section.get("anchor_start") or "").strip()
    end_anchor = str(section.get("anchor_end") or start_anchor).strip()
    if not start_anchor or not block_index:
        return ""

    positions = {
        str(block.get("anchor") or ""): index
        for index, block in enumerate(block_index)
        if isinstance(block, dict) and block.get("anchor")
    }
    start = positions.get(start_anchor)
    end = positions.get(end_anchor)
    if start is None:
        return ""
    if end is None or end < start:
        end = start

    parts: List[str] = []
    size = 0
    for block in block_index[start : end + 1]:
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        remaining = max_chars - size
        if remaining <= 0:
            break
        parts.append(text[:remaining])
        size += min(len(text), remaining) + 2
    return "\n\n".join(parts).strip()


def _anchor_number(value: Any) -> Optional[int]:
    match = re.fullmatch(r"p(\d+)", str(value or "").strip())
    return int(match.group(1)) if match else None


def _attach_located_template_evidence(
    flat: List[Dict[str, Any]],
    located_sections: List[Dict[str, Any]],
    block_index: List[Dict[str, Any]],
) -> None:
    matched: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for item in flat:
        if not item.get("is_leaf"):
            continue
        match = _best_located_section(str(item.get("name") or ""), located_sections)
        if not match:
            continue
        matched.append((item, dict(match)))

    matched_starts = sorted(
        value
        for _, match in matched
        for value in [_anchor_number(match.get("anchor_start"))]
        if value is not None
    )
    for item, match in matched:
        start_number = _anchor_number(match.get("anchor_start"))
        end_number = _anchor_number(match.get("anchor_end"))
        if start_number is not None and (end_number is None or end_number - start_number < 3):
            next_start = next((value for value in matched_starts if start_number < value <= start_number + 80), None)
            if next_start is not None:
                match["anchor_end"] = f"p{next_start - 1}"
        section_id = str(match.get("id") or match.get("section_id") or "").strip()
        title = str(match.get("title") or match.get("section_title") or item.get("name") or "").strip()
        if section_id:
            item["source_section_id"] = section_id
        if title:
            item["source_anchor"] = title
        for key in ("anchor_start", "anchor_end"):
            value = str(match.get(key) or "").strip()
            if value:
                item[key] = value
        preview = _located_section_preview(match, block_index)
        if preview:
            item["content_preview"] = preview
        item["copy_method"] = "located_section"


def _attach_source_document_template_evidence(
    flat: List[Dict[str, Any]],
    source_file_path: str,
    block_index: List[Dict[str, Any]],
) -> None:
    """Recover template spans omitted by the requirement-section locator."""
    if not source_file_path or not block_index:
        return

    leaves = [
        item
        for item in flat
        if item.get("is_leaf") and not (item.get("anchor_start") and item.get("anchor_end"))
    ]
    _attach_format_block_template_evidence(leaves, block_index)
    leaves = [
        item
        for item in leaves
        if not (item.get("anchor_start") and item.get("anchor_end"))
    ]
    if not leaves or Path(source_file_path).suffix.lower() != ".docx":
        return

    from tender_agent.knowledge.tender_template_copier import resolve_tender_template_spans_by_nodes
    from tender_agent.parsing.docx_parser import parse_document

    parsed = parse_document(Path(source_file_path))
    parsed_sections = getattr(parsed, "flat_sections", []) or []
    full_sections: List[Dict[str, Any]] = []
    for section in parsed_sections:
        start = getattr(section, "start_item_idx", None)
        end = getattr(section, "end_item_idx", None)
        if start is None:
            continue
        full_sections.append(
            {
                "id": str(getattr(section, "id", "") or ""),
                "title": str(getattr(section, "title", "") or ""),
                "anchor_start": f"p{start}",
                "anchor_end": f"p{end if end is not None else start}",
            }
        )

    positions = {
        str(block.get("anchor") or ""): index
        for index, block in enumerate(block_index)
        if isinstance(block, dict) and block.get("anchor")
    }

    def substantive_span(span: Dict[str, Any]) -> bool:
        start = positions.get(str(span.get("anchor_start") or ""))
        end = positions.get(str(span.get("anchor_end") or ""))
        if start is None or end is None or end < start:
            return False
        blocks = block_index[start : end + 1]
        preview = _located_section_preview(span, block_index)
        has_table = any(str(block.get("kind") or "") == "table" for block in blocks)
        return has_table or len(re.sub(r"\s+", "", preview)) >= 60

    spans: Dict[str, Dict[str, str]] = {}
    unmatched: List[Dict[str, Any]] = []
    for item in leaves:
        match = _best_located_section(str(item.get("name") or ""), full_sections)
        if match:
            parsed_span = {
                "anchor_start": str(match.get("anchor_start") or ""),
                "anchor_end": str(match.get("anchor_end") or ""),
                "source_anchor": str(match.get("title") or item.get("name") or ""),
                "copy_method": "parsed_section",
                "source_section_id": str(match.get("id") or ""),
            }
            if substantive_span(parsed_span):
                spans[str(item.get("id") or "")] = parsed_span
                continue
        if str(item.get("id") or "") not in spans:
            unmatched.append(item)
    spans.update(resolve_tender_template_spans_by_nodes(unmatched, source_file_path))
    for item in leaves:
        span = spans.get(str(item.get("id") or ""))
        if not span:
            continue
        start = positions.get(str(span.get("anchor_start") or ""))
        end = positions.get(str(span.get("anchor_end") or ""))
        if start is None or end is None or end < start:
            continue
        preview = _located_section_preview(span, block_index)
        # A bare instruction line is not a reusable template; tables and substantive
        # form bodies are. This keeps service-plan placeholders mapped to the KB.
        if not substantive_span(span):
            continue
        item["has_template"] = True
        source_section_id = str(span.get("source_section_id") or "")
        if source_section_id:
            item["source_section_id"] = source_section_id
        item["source_anchor"] = str(span.get("source_anchor") or item.get("name") or "")
        item["anchor_start"] = str(span.get("anchor_start") or "")
        item["anchor_end"] = str(span.get("anchor_end") or "")
        item["copy_method"] = str(span.get("copy_method") or "renderer_title_match")
        if preview:
            item["content_preview"] = preview


_FORMAT_MARKER_RE = re.compile(
    r"^格式\s*([〇零一二三四五六七八九十百两0-9]+)"
    r"(?:\s*[-－—]\s*([〇零一二三四五六七八九十百两0-9]+))?\s*[：:]?$"
)
_DIRECTORY_NUMBER_RE = re.compile(r"^([〇零一二三四五六七八九十百两0-9]+)\s*[、.．]\s*(.+)$")
_SELF_DRAFT_TEMPLATE_RE = re.compile(r"(?:内容和)?格式自拟|自行(?:编写|编制|拟定)")
_FORMAT_SECTION_BOUNDARY_RE = re.compile(
    r"^附件\s*[：:]?\s*[〇零一二三四五六七八九十百两0-9]+(?:[.．、：:]|\s|$)"
)


def _format_marker_key(value: Any) -> str:
    compact = re.sub(r"\s+", "", str(value or "")).strip()
    match = _FORMAT_MARKER_RE.fullmatch(compact)
    if not match:
        return ""
    suffix = f"-{match.group(2)}" if match.group(2) else ""
    return f"格式{match.group(1)}{suffix}"


def _format_marker_base(marker_key: str) -> str:
    return str(marker_key or "").split("-", 1)[0]


def _is_following_format_boundary(block: Dict[str, Any]) -> bool:
    if str(block.get("kind") or "") == "table":
        return False
    text = re.sub(r"\s+", "", str(block.get("text") or "")).strip()
    return bool(text and len(text) <= 80 and _FORMAT_SECTION_BOUNDARY_RE.match(text))


def _template_directory_number(value: Any, node_name: str) -> str:
    text = re.sub(r"\s+", "", str(value or "")).strip()
    match = _DIRECTORY_NUMBER_RE.match(text)
    if not match:
        return ""
    target = _normalized_evidence_title(node_name)
    candidate = _normalized_evidence_title(match.group(2))
    if not target or not candidate:
        return ""
    if target == candidate or target in candidate or candidate in target:
        return match.group(1)
    return ""


def _attach_format_block_template_evidence(
    leaves: List[Dict[str, Any]],
    block_index: List[Dict[str, Any]],
) -> None:
    """Resolve PDF/plain-text templates from `格式N` blocks and their boundaries."""
    blocks = [block for block in block_index or [] if isinstance(block, dict)]
    markers: List[Tuple[int, str]] = []
    for index, block in enumerate(blocks):
        key = _format_marker_key(block.get("text"))
        if key:
            markers.append((index, key))
    if not markers:
        return

    first_marker_index = markers[0][0]
    positions = {
        str(block.get("anchor") or ""): index
        for index, block in enumerate(blocks)
        if block.get("anchor")
    }

    for item in leaves:
        node_name = str(item.get("name") or "").strip()
        marker_key = _format_marker_key(item.get("template_ref"))
        if not marker_key and str(item.get("source") or item.get("source_kind") or "") == "index_table":
            item["has_template"] = False
            continue
        if not marker_key:
            for block in reversed(blocks[:first_marker_index]):
                number = _template_directory_number(block.get("text"), node_name)
                if number:
                    marker_key = f"格式{number}"
                    break
        exact_starts = [index for index, key in markers if key == marker_key]
        start = exact_starts[0] if exact_starts else None
        marker_base = _format_marker_base(marker_key)
        grouped_reference = bool(marker_key and "-" not in marker_key)
        if start is None and grouped_reference:
            start = next(
                (index for index, key in markers if _format_marker_base(key) == marker_base),
                None,
            )
        if start is None:
            continue
        next_start = next(
            (
                index
                for index, key in markers
                if index > start
                and (
                    not grouped_reference
                    or _format_marker_base(key) != marker_base
                )
            ),
            len(blocks),
        )
        next_boundary = next(
            (
                index
                for index in range(start + 1, next_start)
                if _is_following_format_boundary(blocks[index])
            ),
            next_start,
        )
        next_start = min(next_start, next_boundary)
        span_start = start
        marker_page = blocks[start].get("page_no")
        while (
            marker_page is not None
            and span_start > 0
            and str(blocks[span_start - 1].get("kind") or "") == "table"
            and blocks[span_start - 1].get("page_no") == marker_page
        ):
            span_start -= 1

        next_content_start = next_start
        if next_start < len(blocks):
            next_marker_page = blocks[next_start].get("page_no")
            while (
                next_content_start > span_start
                and str(blocks[next_content_start - 1].get("kind") or "") == "table"
                and blocks[next_content_start - 1].get("page_no") == next_marker_page
            ):
                next_content_start -= 1
        end = next_content_start - 1
        span_blocks = blocks[span_start : end + 1]
        span_text = "\n".join(str(block.get("text") or "") for block in span_blocks).strip()
        has_table = any(str(block.get("kind") or "") == "table" for block in span_blocks)
        compact_span = re.sub(r"\s+", "", span_text)

        # A one-line "format self-drafted" instruction is not an original form.
        if _SELF_DRAFT_TEMPLATE_RE.search(compact_span) and not has_table:
            item["has_template"] = False
            continue
        if not has_table and len(compact_span) < 60:
            item["has_template"] = False
            continue

        start_anchor = str(blocks[span_start].get("anchor") or "")
        end_anchor = str(blocks[end].get("anchor") or "")
        if not start_anchor or not end_anchor:
            continue
        if start_anchor not in positions or end_anchor not in positions:
            continue

        source_anchor = node_name
        target = _normalized_evidence_title(node_name)
        for block in blocks[start + 1 : min(end + 1, start + 8)]:
            title = str(block.get("text") or "").strip()
            candidate = _normalized_evidence_title(title)
            if target and candidate and (target == candidate or target in candidate or candidate in target):
                source_anchor = title
                break

        span = {
            "anchor_start": start_anchor,
            "anchor_end": end_anchor,
            "source_anchor": source_anchor,
        }
        item["has_template"] = True
        item["anchor_start"] = start_anchor
        item["anchor_end"] = end_anchor
        item["source_anchor"] = source_anchor
        item["copy_method"] = "format_block"
        preview = _located_section_preview(span, block_index)
        if preview:
            item["content_preview"] = preview


def _attach_existing_template_evidence(
    flat: List[Dict[str, Any]],
    assignments: List[Dict[str, Any]],
) -> None:
    """Preserve template spans already confirmed by a previous render/remap."""
    materials_by_node = {
        str(assignment.get("node_id") or ""): assignment.get("materials") or []
        for assignment in assignments or []
        if isinstance(assignment, dict)
    }
    for item in flat:
        node_id = str(item.get("id") or "")
        template = next(
            (
                material
                for material in materials_by_node.get(node_id, [])
                if isinstance(material, dict) and str(material.get("source") or "") == "tender_template"
            ),
            None,
        )
        if template is None:
            continue
        has_resolved_span = bool(template.get("anchor_start") and template.get("anchor_end"))
        if not has_resolved_span and not template.get("source_section_id"):
            continue
        item["has_template"] = True
        for key in (
            "source_section_id",
            "source_anchor",
            "anchor_start",
            "anchor_end",
            "content_preview",
            "copy_method",
        ):
            value = template.get(key)
            if value and not item.get(key):
                item[key] = value


def _company_scope_filter(model: Any, company_id: str):
    company_id = str(company_id or "").strip()
    if not company_id:
        return model.scope == "shared"
    return or_(model.company_id == company_id, model.scope == "shared")


def build_certs_index(db: Session, company_id: str = "") -> Dict[str, int]:
    rows = (
        db.query(Certificate.category, func.count(Certificate.id))
        .filter(
            *usable_certificate_filters(Certificate),
            _company_scope_filter(Certificate, company_id),
        )
        .group_by(Certificate.category)
        .all()
    )
    return {category: count for category, count in rows if category}


def build_cert_items(db: Session, company_id: str = "") -> List[Dict[str, Any]]:
    rows = (
        db.query(Certificate)
        .filter(
            *usable_certificate_filters(Certificate),
            _company_scope_filter(Certificate, company_id),
        )
        .order_by(Certificate.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(row.id),
            "category": row.category,
            "subcategory": row.subcategory,
            "name": row.name,
            "file_path": row.file_path,
            "file_type": row.file_type,
        }
        for row in rows
        if row.category and row.name and row.file_path
    ]


def build_tech_index(db: Session, company_id: str = "") -> List[Dict[str, Any]]:
    rows = (
        db.query(TemplateSection)
        .filter(
            TemplateSection.is_current.is_(True),
            TemplateSection.deleted_at.is_(None),
            TemplateSection.level <= 4,
            _company_scope_filter(TemplateSection, company_id),
        )
        .order_by(TemplateSection.start_block_idx)
        .all()
    )
    return [
        {
            "section_id": str(row.id),
            "chapter_id": row.chapter_id,
            "title": row.title,
            "full_path": row.full_path or row.title,
            "level": row.level,
            "span": (row.end_block_idx or 0) - (row.start_block_idx or 0),
        }
        for row in rows
    ]


def _load_material_indexes(
    db: Session,
    company_id: str = "",
) -> Tuple[Dict[str, int], List[Dict[str, Any]], List[Dict[str, Any]]]:
    certs_index = build_certs_index(db, company_id=company_id)
    tech_index = build_tech_index(db, company_id=company_id)
    cert_items = build_cert_items(db, company_id=company_id)
    _store_material_index_cache(company_id, certs_index, tech_index, cert_items)
    return certs_index, tech_index, cert_items


def _cached_material_indexes(company_id: str = "") -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
    cached = _read_material_index_cache(company_id)
    return cached["certs_index"], cached["tech_index"]


def _cached_cert_items(company_id: str = "") -> List[Dict[str, Any]]:
    return _read_material_index_cache(company_id)["cert_items"]


def _dispose_db_pool_after_error() -> None:
    try:
        engine.dispose()
    except Exception:
        pass


def _leaf_ids(flat: List[Dict[str, Any]]) -> set[str]:
    return {str(item.get("id", "")) for item in flat if item.get("is_leaf")}


def _template_source_fields(
    node_name: str,
    node_meta: Optional[Dict[str, Any]] = None,
    material: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    meta = node_meta or {}
    incoming = material or {}
    source_section_id = str(
        incoming.get("source_section_id")
        or incoming.get("section_id")
        or meta.get("source_section_id")
        or meta.get("section_id")
        or ""
    ).strip()
    source_anchor = str(
        incoming.get("source_anchor")
        or incoming.get("quote")
        or incoming.get("template_ref")
        or meta.get("source_anchor")
        or meta.get("quote")
        or meta.get("template_ref")
        or meta.get("anchor_start")
        or node_name
        or ""
    ).strip()

    fields: Dict[str, Any] = {}
    if source_section_id:
        fields["source_section_id"] = source_section_id
    if source_anchor:
        fields["source_anchor"] = source_anchor
    for key in ("anchor_start", "anchor_end", "content_preview", "copy_method"):
        value = incoming.get(key) or meta.get(key)
        if value:
            fields[key] = value
    has_anchor_span = bool(fields.get("anchor_start") and fields.get("anchor_end"))
    if not source_anchor or (not source_section_id and not has_anchor_span):
        fields["note"] = TENDER_TEMPLATE_MISSING_NOTE
    return fields


def _tender_template_material(
    node_name: str,
    node_meta: Optional[Dict[str, Any]] = None,
    material: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result = {
        "source": "tender_template",
        "name": node_name,
    }
    result.update(_template_source_fields(node_name, node_meta, material))
    return result


def _certificate_material(category: str, max_count: int) -> Dict[str, Any]:
    return {"source": "certificate", "category": category, "max_count": max_count}


def _specific_certificate_materials(
    node_name: str,
    category: str,
    cert_items: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Return concrete files when a node names one certificate inside a broad category."""
    node_key = _norm_material_name(node_name)
    category_key = _norm_material_name(category)
    if not node_key or node_key == category_key:
        return []

    matches: List[Dict[str, Any]] = []
    for item in cert_items or []:
        if str(item.get("category") or "").strip() != category:
            continue
        item_key = _norm_material_name(item.get("name") or "")
        base_key = re.sub(r"[_-]\d+$", "", item_key)
        if not base_key or base_key == category_key:
            continue
        if node_key != base_key and base_key not in node_key and node_key not in base_key:
            continue
        matches.append(
            {
                "source": "certificate",
                "id": item.get("id"),
                "category": category,
                "subcategory": item.get("subcategory"),
                "name": item.get("name"),
                "file_path": item.get("file_path"),
                "file_type": item.get("file_type"),
                "max_count": 1,
            }
        )
    return matches[:10]


def _norm_material_name(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip("：:，,。；;、（）()[]【】")


_CERTIFICATE_CATEGORY_ALIASES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("营业执照", ("营业执照", "三证合一")),
    ("劳务派遣经营许可证", ("劳务派遣经营许可证", "劳务派遣许可证")),
    ("人力资源服务许可证", ("人力资源服务许可证", "人力资源许可证")),
    ("基本存款账户信息", ("开户许可证", "基本存款账户信息", "银行账户信息")),
    ("审计报告", ("审计报告", "财务报表", "财务状况报告")),
    ("一般纳税人认定证明", ("一般纳税人",)),
    ("ISO认证体系证书", ("ISO认证", "ISO证书", "质量管理体系认证", "职业健康安全管理体系认证")),
    ("项目人员证书", ("人员证书", "项目人员证书")),
    ("合作业绩", ("业绩证明", "类似业绩合同", "同类业绩合同", "合作业绩")),
    ("企业荣誉", ("企业荣誉", "荣誉证书", "获奖证书", "表彰")),
    ("项目奖项", ("项目荣誉", "项目奖项", "获奖项目")),
)

_TEMPLATE_SUPPORT_RULES: Tuple[Tuple[Tuple[str, ...], str, int], ...] = (
    (
        (
            "业绩表",
            "业绩一览表",
            "业绩汇总表",
            "业绩情况表",
            "同类项目业绩",
            "类似项目业绩",
            "合作业绩",
        ),
        "合作业绩",
        10,
    ),
    (
        ("服务团队情况", "团队情况", "服务团队成员一览表", "拟任本项目服务团队情况"),
        "项目人员证书",
        5,
    ),
)


def _best_certificate_category(
    node_name: str,
    certs_index: Dict[str, int],
    cert_items: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    node_key = _norm_material_name(node_name)
    if not node_key:
        return None

    best_category = ""
    best_score = 0
    for category, count in (certs_index or {}).items():
        category_key = _norm_material_name(category)
        if not category_key or int(count or 0) <= 0:
            continue
        score = 0
        if node_key == category_key:
            score = 100
        elif category_key in node_key:
            score = 80
        elif len(node_key) >= 3 and node_key in category_key:
            score = 60
        if score > best_score:
            best_category = str(category)
            best_score = score

    for item in cert_items or []:
        category = str(item.get("category") or "").strip()
        if category not in (certs_index or {}):
            continue
        haystack = _norm_material_name(f"{item.get('name') or ''}{category}")
        if not haystack:
            continue
        score = 0
        if node_key == _norm_material_name(item.get("name") or ""):
            score = 95
        elif node_key in haystack:
            score = 75
        elif _norm_material_name(category) in node_key:
            score = 70
        if score > best_score:
            best_category = category
            best_score = score

    if best_score < 60:
        for category, aliases in _CERTIFICATE_CATEGORY_ALIASES:
            if category in (certs_index or {}) and any(alias in node_key for alias in aliases):
                return category

    return best_category if best_score >= 60 else None


def _supporting_certificate_materials(
    node_name: str,
    certs_index: Dict[str, int],
) -> List[Dict[str, Any]]:
    """Attach reusable evidence to forms that are intended to be filled with KB data."""
    compact = _norm_material_name(node_name)
    for markers, category, max_count in _TEMPLATE_SUPPORT_RULES:
        if category in certs_index and any(marker in compact for marker in markers):
            return [
                _certificate_material(
                    category,
                    min(certs_index.get(category, 1), max_count),
                )
            ]
    return []


def _is_fillable_template_node(node_name: str) -> bool:
    compact = _norm_material_name(node_name)
    return compact.endswith(("表", "清单", "目录")) or any(
        term in compact for term in ("一览表", "情况表", "汇总表", "明细表", "登记表")
    )


def _static_materials(
    node_name: str,
    certs_index: Dict[str, int],
    node_meta: Optional[Dict[str, Any]] = None,
    cert_items: Optional[List[Dict[str, Any]]] = None,
    incoming_template: Optional[Dict[str, Any]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Resolve deterministic certificate/template materials before using LLM output."""
    cert_category = _best_certificate_category(node_name, certs_index, cert_items)
    has_template = _is_tender_template_node(node_name, node_meta) or incoming_template is not None
    if cert_category and (not has_template or not _is_fillable_template_node(node_name)):
        specific_materials = _specific_certificate_materials(node_name, cert_category, cert_items)
        if specific_materials:
            return specific_materials
        return [_certificate_material(cert_category, min(certs_index.get(cert_category, 1), 10))]
    supporting = _supporting_certificate_materials(node_name, certs_index)
    if has_template:
        template_name = str((incoming_template or {}).get("name") or node_name)
        return [
            _tender_template_material(template_name, node_meta, incoming_template),
            *supporting,
        ]
    if supporting:
        return supporting
    return None


def _default_materials(
    node_name: str,
    certs_index: Dict[str, int],
    node_meta: Optional[Dict[str, Any]] = None,
    cert_items: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    return _static_materials(node_name, certs_index, node_meta, cert_items) or [
        _manual_material(node_name)
    ]

def _manual_material(node_name: str) -> Dict[str, Any]:
    name = str(node_name or "").strip() or "本章节"
    return {"source": "manual", "note": f"请人工补充：{name}（当前知识库无对应素材）"}


def _is_manual_materials(materials: List[Dict[str, Any]]) -> bool:
    return not materials or all(item.get("source") == "manual" for item in materials)


def _is_tender_template_node(node_name: str, node_meta: Optional[Dict[str, Any]] = None) -> bool:
    meta = node_meta or {}
    if meta.get("source_anchor") or meta.get("source_section_id"):
        return True
    if meta.get("anchor_start") and meta.get("anchor_end"):
        return True
    return str(meta.get("source") or "") == "tender_template" or str(meta.get("source_kind") or "") == "tender_template"

def _safe_tech_chapter_id(chapter_id: str, node_name: str, tech_index: List[Dict[str, Any]]) -> str:
    """Avoid copying huge parent sections; prefer the most relevant child section."""
    current = next((item for item in tech_index if str(item.get("chapter_id")) == chapter_id), None)
    if not current:
        return chapter_id
    if int(current.get("span") or 0) <= 180:
        return chapter_id

    child = _best_child_tech_section(chapter_id, node_name, tech_index)
    return str(child.get("chapter_id") or "") if child else ""


def _best_child_tech_section(
    chapter_id: str,
    node_name: str,
    tech_index: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    children = [
        item
        for item in tech_index
        if str(item.get("chapter_id") or "").startswith(f"{chapter_id}.")
        and 0 < int(item.get("span") or 0) <= 180
    ]
    if not children:
        return None

    preferred = _preferred_tech_title(node_name)
    best: Optional[Dict[str, Any]] = None
    best_score = -10_000
    for item in children:
        text = f"{item.get('title', '')} {item.get('full_path', '')}"
        score = sum(1 for token in _tokens(node_name) if token and token in text)
        if preferred and preferred in text:
            score += 100
        if str(item.get("level") or "") in {"3", "4"}:
            score += 1
        score -= max(int(item.get("span") or 0) - 80, 0) // 20
        if score > best_score:
            best = item
            best_score = score
    return best


def _preferred_tech_title(node_name: str) -> str:
    rules = [
        ("运营管理", "企业项目管理体系"),
        ("管理梯队", "企业项目管理体系"),
        ("人员履历", "员工管理准则"),
        ("招聘", "人员招聘方案"),
        ("高峰", "服务质量保证"),
        ("保障", "项目保障体系"),
        ("应急", "突发事件应急预案"),
        ("风险", "风险管控制度"),
        ("项目实施方案", "项目整体规划"),
        ("实施方案书", "项目整体规划"),
        ("实质性内容响应", "项目整体规划"),
        ("项目理解", "项目整体规划"),
        ("服务/货物清单", "项目整体规划"),
        ("服务模式", "项目整体规划"),
        ("团队介绍", "项目整体规划"),
        ("服务方案", "项目整体规划"),
        ("技术方案", "项目整体规划"),
        ("整体方案", "项目整体规划"),
    ]
    for keyword, title in rules:
        if keyword in node_name:
            return title
    return ""


def _tokens(text: str) -> List[str]:
    tokens = []
    cleaned = "".join(ch if "\u4e00" <= ch <= "\u9fff" else " " for ch in text)
    for part in cleaned.split():
        tokens.append(part)
        for size in (2, 3, 4):
            for idx in range(0, max(len(part) - size + 1, 0)):
                tokens.append(part[idx : idx + size])
    return list(dict.fromkeys(tokens))


def postprocess_assignments(
    assignments: List[Dict[str, Any]],
    flat: List[Dict[str, Any]],
    certs_index: Dict[str, int],
    tech_index: List[Dict[str, Any]],
    cert_items: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    valid_leaf_ids = _leaf_ids(flat)
    valid_categories = set(certs_index.keys())
    tech_by_chapter_id = {
        str(item.get("chapter_id")): item
        for item in tech_index
        if item.get("chapter_id")
    }
    valid_chapter_ids = set(tech_by_chapter_id)
    node_name_map = {str(item.get("id", "")): str(item.get("name", "")) for item in flat}
    node_meta_map = {str(item.get("id", "")): item for item in flat}

    cleaned_by_id: Dict[str, Dict[str, Any]] = {}
    for assignment in assignments:
        node_id = str(assignment.get("node_id", "")).strip()
        if node_id not in valid_leaf_ids:
            continue
        node_name = str(assignment.get("node_name") or node_name_map.get(node_id) or "")
        node_meta = node_meta_map.get(node_id)
        incoming_template: Optional[Dict[str, Any]] = None
        materials = []
        for material in assignment.get("materials", []) or []:
            if not isinstance(material, dict):
                continue
            source = material.get("source")
            if source == "certificate":
                category = str(material.get("category", "")).strip()
                if category in valid_categories:
                    materials.append(
                        _certificate_material(
                            category,
                            min(certs_index.get(category, 1), 10),
                        )
                    )
            elif source == "tech_section":
                chapter_id = str(material.get("chapter_id", "")).strip()
                copy_full_section = bool(material.get("copy_full_section"))
                if chapter_id in valid_chapter_ids and ("." in chapter_id or copy_full_section):
                    safe_chapter_id = chapter_id if copy_full_section else _safe_tech_chapter_id(chapter_id, node_name, tech_index)
                    if safe_chapter_id:
                        section = tech_by_chapter_id.get(safe_chapter_id) or {}
                        materials.append(
                            {
                                "source": "tech_section",
                                "chapter_id": safe_chapter_id,
                                "section_id": section.get("section_id"),
                                "chapter_title": section.get("title"),
                                "full_path": section.get("full_path"),
                                "copy_full_section": copy_full_section,
                            }
                        )
            elif source == "tech_section_range":
                chapter_start = str(material.get("chapter_start") or "").strip()
                chapter_end = str(material.get("chapter_end") or "").strip()
                if chapter_start in valid_chapter_ids and chapter_end in valid_chapter_ids:
                    materials.append(
                        {
                            "source": "tech_section_range",
                            "chapter_start": chapter_start,
                            "chapter_end": chapter_end,
                        }
                    )
            elif source == "tender_template":
                incoming_template = material
            elif source == "manual":
                materials.append({"source": "manual", "note": str(material.get("note") or "请人工补充")})

        static_materials = _static_materials(
            node_name,
            certs_index,
            node_meta,
            cert_items,
            incoming_template,
        )
        if static_materials is not None:
            materials = static_materials
        elif not materials:
            materials = [_manual_material(node_name)]
        cleaned_by_id[node_id] = {"node_id": node_id, "node_name": node_name, "materials": materials}

    for item in flat:
        node_id = str(item.get("id", ""))
        if node_id not in valid_leaf_ids or node_id in cleaned_by_id:
            continue
        node_name = str(item.get("name", ""))
        cleaned_by_id[node_id] = {
            "node_id": node_id,
            "node_name": node_name,
            "materials": _default_materials(node_name, certs_index, item, cert_items),
        }

    return list(cleaned_by_id.values())


def _candidate_score(query: str, candidate: str) -> float:
    query_norm = _norm_material_name(query)
    candidate_norm = _norm_material_name(candidate)
    if not query_norm or not candidate_norm:
        return 0.0
    query_tokens = set(_tokens(query))
    candidate_tokens = set(_tokens(candidate))
    overlap = len(query_tokens & candidate_tokens) / max(len(query_tokens), 1)
    ratio = SequenceMatcher(None, query_norm, candidate_norm).ratio()
    containment = 0.25 if query_norm in candidate_norm or candidate_norm in query_norm else 0.0
    return overlap * 0.55 + ratio * 0.20 + containment


def _material_identity(material: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    source = str(material.get("source") or "")
    if source == "certificate":
        value = str(
            material.get("id")
            or material.get("file_path")
            or (
                f"{material.get('category') or ''}:{material.get('name') or ''}"
                if material.get("name")
                else material.get("category")
            )
            or ""
        ).strip()
    elif source == "tech_section":
        value = str(material.get("section_id") or material.get("chapter_id") or "").strip()
    elif source == "tech_section_range":
        value = f"{material.get('chapter_start') or ''}:{material.get('chapter_end') or ''}".strip(":")
    else:
        return None
    return (source, value) if value else None


def _dedupe_materials_across_assignments(
    assignments: List[Dict[str, Any]],
    flat: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Keep a reusable KB item on the single best-matching outline node."""
    meta_by_id = {str(item.get("id") or ""): item for item in flat}
    occurrences: Dict[Tuple[str, str], List[Tuple[int, Dict[str, Any]]]] = {}
    for assignment_index, assignment in enumerate(assignments or []):
        local_seen: set[Tuple[str, str]] = set()
        unique_materials: List[Dict[str, Any]] = []
        for material in assignment.get("materials") or []:
            identity = _material_identity(material)
            if identity and identity in local_seen:
                continue
            if identity:
                local_seen.add(identity)
                occurrences.setdefault(identity, []).append((assignment_index, material))
            unique_materials.append(material)
        assignment["materials"] = unique_materials

    keep: Dict[Tuple[str, str], int] = {}
    for identity, rows in occurrences.items():
        if len(rows) == 1:
            keep[identity] = rows[0][0]
            continue
        source, value = identity
        best_index = rows[0][0]
        best_score = -1.0
        for assignment_index, material in rows:
            assignment = assignments[assignment_index]
            node_id = str(assignment.get("node_id") or "")
            meta = meta_by_id.get(node_id) or {}
            query = str(meta.get("path") or assignment.get("node_name") or "")
            descriptor = str(
                material.get("full_path")
                or material.get("chapter_title")
                or material.get("category")
                or value
            )
            score = _candidate_score(query, descriptor)
            if score > best_score:
                best_score = score
                best_index = assignment_index
        keep[(source, value)] = best_index

    for assignment_index, assignment in enumerate(assignments or []):
        materials = [
            material
            for material in assignment.get("materials") or []
            if (identity := _material_identity(material)) is None
            or keep.get(identity) == assignment_index
        ]
        if not materials:
            materials = [_manual_material(str(assignment.get("node_name") or ""))]
        assignment["materials"] = materials
    return assignments


def _node_candidate_view(
    node: Dict[str, Any],
    certs_index: Dict[str, int],
    tech_index: List[Dict[str, Any]],
) -> Dict[str, Any]:
    query = str(node.get("path") or node.get("name") or "")
    cert_candidates = sorted(
        certs_index.items(),
        key=lambda item: _candidate_score(query, str(item[0])),
        reverse=True,
    )[:3]
    tech_candidates = sorted(
        tech_index,
        key=lambda item: _candidate_score(
            query,
            f"{item.get('title') or ''} {item.get('full_path') or ''}",
        ),
        reverse=True,
    )[:5]
    return {
        "id": node.get("id"),
        "name": node.get("name"),
        "path": node.get("path"),
        "has_template": bool(
            node.get("has_template")
            or node.get("template_ref")
            or node.get("source_anchor")
            or node.get("source_section_id")
        ),
        "certificate_candidates": [
            {"category": category, "count": count}
            for category, count in cert_candidates
        ],
        "tech_candidates": [
            {
                "section_id": item.get("section_id"),
                "chapter_id": item.get("chapter_id"),
                "title": item.get("title"),
                "full_path": item.get("full_path"),
                "span": item.get("span"),
            }
            for item in tech_candidates
        ],
    }


def _build_slim_llm_prompt(
    nodes: List[Dict[str, Any]],
    certs_index: Dict[str, int],
    tech_index: List[Dict[str, Any]],
) -> str:
    node_views = [
        _node_candidate_view(node, certs_index, tech_index)
        for node in nodes
    ]
    prompt = PROMPT_TEMPLATE.format(
        outline_flat=json.dumps(node_views, ensure_ascii=False, separators=(",", ":")),
    )
    return prompt + "\n\n请只输出 JSON 对象，不要 markdown 代码块，不要任何解释文字。"


def _merge_default_and_llm_assignments(
    flat: List[Dict[str, Any]],
    default_by_id: Dict[str, Dict[str, Any]],
    llm_assignments: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    llm_by_id = {str(item.get("node_id") or ""): item for item in llm_assignments}
    merged: List[Dict[str, Any]] = []
    for item in flat:
        if not item.get("is_leaf"):
            continue
        node_id = str(item.get("id") or "")
        merged.append(llm_by_id.get(node_id) or default_by_id.get(node_id))
    return merged


async def map_materials(state: dict) -> dict:
    outline = state.get("final_outline") or state.get("outline") or []
    if not outline:
        return {"material_assignments": [], "warnings": ["[material_mapper] empty outline"]}
    company_id = str(state.get("company_id") or "").strip()
    flat = flatten_outline_for_prompt(outline)
    located_sections = state.get("located_sections") or (state.get("stats") or {}).get("located_sections") or []
    block_index = state.get("block_index") or []
    _attach_located_template_evidence(flat, located_sections, block_index)
    _attach_source_document_template_evidence(
        flat,
        str(state.get("source_file_path") or ""),
        block_index,
    )
    _attach_existing_template_evidence(flat, state.get("existing_material_assignments") or [])

    db = None
    certs_index: Dict[str, int] = {}
    tech_index: List[Dict[str, Any]] = []
    cert_items: List[Dict[str, Any]] = []
    try:
        db = next(get_db_session())
        certs_index, tech_index, cert_items = _load_material_indexes(db, company_id=company_id)
        leaf_nodes = [item for item in flat if item.get("is_leaf")]

        default_by_id: Dict[str, Dict[str, Any]] = {}
        llm_nodes: List[Dict[str, Any]] = []
        locked_count = 0
        for item in leaf_nodes:
            node_id = str(item.get("id") or "")
            node_name = str(item.get("name") or "")
            materials = _default_materials(node_name, certs_index, item, cert_items)
            assignment = {"node_id": node_id, "node_name": node_name, "materials": materials}
            default_by_id[node_id] = assignment
            if _is_manual_materials(materials):
                llm_nodes.append(item)
            else:
                locked_count += 1

        if not settings.MATERIAL_MAPPER_USE_LLM:
            logger.info("[material_mapper] LLM disabled, metadata/manual mapping")
            assignments = _merge_default_and_llm_assignments(flat, default_by_id, [])
            return {"material_assignments": _dedupe_materials_across_assignments(assignments, flat)}

        if not llm_nodes:
            logger.info(
                "[material_mapper] metadata split covered all leaf nodes, skip LLM: leaves={}, locked={}",
                len(leaf_nodes),
                locked_count,
            )
            assignments = _merge_default_and_llm_assignments(flat, default_by_id, [])
            return {"material_assignments": _dedupe_materials_across_assignments(assignments, flat)}

        batch_size = max(1, int(settings.MATERIAL_MAPPER_BATCH_SIZE))
        batches = [llm_nodes[index : index + batch_size] for index in range(0, len(llm_nodes), batch_size)]
        prompt_lengths = [len(_build_slim_llm_prompt(batch, certs_index, tech_index)) for batch in batches]
        logger.info(
            "[material_mapper] llm split mapping start, batches={}, prompt_max={}, leaves={}, locked={}, llm_nodes={}, cert_categories={}, tech={}",
            len(batches),
            max(prompt_lengths, default=0),
            len(leaf_nodes),
            locked_count,
            len(llm_nodes),
            len(certs_index),
            len(tech_index),
        )
        start = time.time()
        try:
            semaphore = asyncio.Semaphore(max(1, int(settings.MATERIAL_MAPPER_CONCURRENCY)))

            async def map_batch(batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
                prompt = _build_slim_llm_prompt(batch, certs_index, tech_index)
                async with semaphore:
                    result: MappingResult = await asyncio.wait_for(
                        llm_gateway.async_call_structured(
                            prompt,
                            MappingResult,
                            max_tokens=max(1200, len(batch) * 260),
                            disable_json_mode=True,
                        ),
                        timeout=float(settings.MATERIAL_MAPPER_LLM_TIMEOUT_SECONDS),
                    )
                return [item.model_dump() for item in result.assignments]

            batch_results = await asyncio.gather(*(map_batch(batch) for batch in batches))
            raw_assignments = [item for batch_result in batch_results for item in batch_result]
            llm_assignments = postprocess_assignments(
                raw_assignments,
                llm_nodes,
                certs_index,
                tech_index,
                cert_items,
            )
            for assignment in llm_assignments:
                if _is_manual_materials(assignment.get("materials", []) or []):
                    node_id = str(assignment.get("node_id") or "")
                    if node_id in default_by_id:
                        assignment["materials"] = default_by_id[node_id]["materials"]
            assignments = _merge_default_and_llm_assignments(flat, default_by_id, llm_assignments)
            assignments = _dedupe_materials_across_assignments(assignments, flat)
            logger.info(
                "[material_mapper] done {:.1f}s, assignments={}, llm_assignments={}",
                time.time() - start,
                len(assignments),
                len(llm_assignments),
            )
            return {"material_assignments": assignments}
        except Exception as llm_exc:
            logger.warning(
                "[material_mapper] LLM failed after metadata split, manual fallback applied: {}",
                str(llm_exc)[:200],
            )
            assignments = _merge_default_and_llm_assignments(flat, default_by_id, [])
            return {
                "material_assignments": _dedupe_materials_across_assignments(assignments, flat),
                "warnings": [f"[material_mapper] LLM failed after metadata split, manual fallback applied: {str(llm_exc)[:200]}"],
            }
    except Exception as exc:
        logger.error(f"[material_mapper] failed: {str(exc)[:200]}")
        _dispose_db_pool_after_error()
        if not certs_index and not tech_index:
            certs_index, tech_index = _cached_material_indexes(company_id)
        if not cert_items:
            cert_items = _cached_cert_items(company_id)
        cache_note = ""
        if certs_index or tech_index:
            cache_note = f"，使用缓存索引 cert_categories={len(certs_index)}, tech={len(tech_index)}"
        assignments = postprocess_assignments([], flat, certs_index, tech_index, cert_items)
        return {
            "material_assignments": _dedupe_materials_across_assignments(assignments, flat),
            "warnings": [f"[material_mapper] failed, manual fallback applied{cache_note}: {str(exc)[:200]}"],
        }
    finally:
        if db is not None:
            db.close()
