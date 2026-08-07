"""LLM-assisted inline material splitting for source-backed composition rows."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List

from loguru import logger
from pydantic import BaseModel, Field

from ..requirements_common import _compact_text
from .llm_runner import _call_dimension_llm


class InlineMaterialChildren(BaseModel):
    row_index: int = Field(description="1-based row index from the input list")
    children: List[str] = Field(default_factory=list, description="Child material names explicitly present in the quote")


class InlineMaterialSplitResult(BaseModel):
    items: List[InlineMaterialChildren] = Field(default_factory=list)


def _needs_inline_material_llm(row: Dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    if row.get("parent_name"):
        return False
    if str(row.get("source_kind") or "") == "index_table":
        return False
    quote = str(row.get("quote") or row.get("name") or "").strip()
    name = str(row.get("name") or "").strip()
    compact = _compact_text(quote)
    if len(compact) < 18:
        return False
    if len(compact) > 360:
        return False
    if any(term in compact for term in ("应包括但不限于以下内容", "包括但不限于以下内容", "参见本采购文件提供的格式")):
        return False
    split_markers = ("、", "/", "及", "和", "分别提供", "如下", "下列", "包括")
    material_terms = (
        "营业执照",
        "登记证书",
        "资格证明",
        "资质证明",
        "许可证",
        "截图",
        "证明文件",
        "证书",
        "报价函",
        "应答函",
        "承诺函",
        "声明",
        "业绩",
        "人员资质",
        "荣誉",
        "认证",
        "清单",
    )
    if not any(marker in compact for marker in split_markers):
        return False
    if not any(term in compact or term in _compact_text(name) for term in material_terms):
        return False
    return True


def _child_supported_by_quote(child: str, quote: str) -> bool:
    child_key = _compact_text(child)
    quote_key = _compact_text(quote)
    if not child_key or len(child_key) < 2:
        return False
    if child_key in quote_key:
        return True
    child_core = re.sub(r"(?:复印件|原件|截图|扫描件|证明文件|证明材料|材料|文件)$", "", child_key)
    if len(child_core) >= 4 and child_core in quote_key:
        return True
    if child_key.endswith("截图"):
        base = child_key[:-2]
        return len(base) >= 4 and base in quote_key and any(term in quote_key for term in ("截图", "页面", "PDF"))
    return False


def _append_children_after_parent(rows: List[Dict[str, Any]], children_by_index: Dict[int, List[str]]) -> List[Dict[str, Any]]:
    refined: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        refined.append(row)
        child_names = children_by_index.get(idx) or []
        if not child_names:
            continue
        try:
            parent_level = int(row.get("outline_level") or 1)
        except Exception:
            parent_level = 1
        parent_name = str(row.get("name") or "").strip()
        seen = {_compact_text(parent_name)}
        for child_name in child_names:
            clean_child = str(child_name or "").strip(" ：:，,。；;、")
            child_key = _compact_text(clean_child)
            if not clean_child or child_key in seen:
                continue
            seen.add(child_key)
            child = {
                "name": clean_child,
                "required": True,
                "order": len(refined) + 1,
                "quote": row.get("quote") or clean_child,
                "template_ref": None,
                "has_template": False,
                "section_id": row.get("section_id"),
                "section_title": row.get("section_title"),
                "source_backed_composition": True,
                "source_backed_authoritative": True,
                "source_kind": row.get("source_kind"),
                "outline_level": parent_level + 1,
                "parent_name": parent_name,
                "llm_inline_material_child": True,
            }
            refined.append(child)
    return refined


def _row_quote(row: Dict[str, Any]) -> str:
    requirement = row.get("requirement") if isinstance(row.get("requirement"), dict) else {}
    return str(requirement.get("quote") or row.get("quote") or row.get("name") or "")


def _row_anchor(row: Dict[str, Any]) -> Dict[str, Any] | None:
    requirement = row.get("requirement") if isinstance(row.get("requirement"), dict) else {}
    anchor = requirement.get("anchor") if isinstance(requirement.get("anchor"), dict) else None
    if anchor:
        return anchor
    if row.get("section_id") or row.get("section_title"):
        return {
            "section_id": row.get("section_id"),
            "section_title": row.get("section_title"),
        }
    return None


def _as_final_file_composition_child(source_child: Dict[str, Any], order: int) -> Dict[str, Any]:
    name = str(source_child.get("name") or "").strip()
    quote = _row_quote(source_child)
    anchor = _row_anchor(source_child)
    return {
        "name": name,
        "required": bool(source_child.get("required", True)),
        "order": order,
        "template_ref": source_child.get("template_ref"),
        "requirement": {
            "value": name,
            "quote": quote,
            "anchor": anchor,
            "severity": "P2",
        },
        "source_backed_composition": True,
        "source_kind": source_child.get("source_kind"),
        "outline_level": source_child.get("outline_level"),
        "parent_name": source_child.get("parent_name"),
        "outline_group": False,
    }


def merge_source_backed_inline_children_into_final_rows(
    final_rows: List[Dict[str, Any]],
    source_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge source-supported inline children when the final file_composition came from LLM rows.

    The narrow splitter runs on source-backed rows before final payload merge. If full
    LLM file_composition rows win later, those validated children would otherwise be
    lost. This reconciler only inserts child rows whose parent already exists in the
    final outline and whose child name is still missing under that parent.
    """
    if not final_rows or not source_rows:
        return final_rows

    parent_names = {_compact_text(str(row.get("name") or "")) for row in final_rows if isinstance(row, dict)}
    if not parent_names:
        return final_rows

    children_by_parent: Dict[str, List[Dict[str, Any]]] = {}
    for row in source_rows:
        if not isinstance(row, dict) or not row.get("llm_inline_material_child"):
            continue
        parent_name = str(row.get("parent_name") or "").strip()
        parent_key = _compact_text(parent_name)
        child_name = str(row.get("name") or "").strip()
        if not parent_key or parent_key not in parent_names or not child_name:
            continue
        quote = _row_quote(row)
        if not _child_supported_by_quote(child_name, quote):
            continue
        children_by_parent.setdefault(parent_key, []).append(row)

    if not children_by_parent:
        return final_rows

    merged: List[Dict[str, Any]] = []
    inserted = 0
    for row in final_rows:
        merged.append(row)
        if not isinstance(row, dict):
            continue
        parent_key = _compact_text(str(row.get("name") or ""))
        source_children = children_by_parent.get(parent_key) or []
        if not source_children:
            continue
        existing_child_keys = {
            _compact_text(str(item.get("name") or ""))
            for item in final_rows
            if isinstance(item, dict)
            and _compact_text(str(item.get("parent_name") or "")) == parent_key
        }
        for child in source_children:
            child_key = _compact_text(str(child.get("name") or ""))
            if not child_key or child_key in existing_child_keys or child_key == parent_key:
                continue
            existing_child_keys.add(child_key)
            order = len(merged) + 1
            merged.append(_as_final_file_composition_child(child, order))
            inserted += 1

    if inserted:
        logger.info(
            "[requirements] merged {} source-backed inline child rows into final file_composition",
            inserted,
        )
    return merged


async def refine_inline_material_children_with_llm(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Use LLM only to split long source-backed rows that explicitly contain child materials."""
    if os.getenv("DISABLE_INLINE_MATERIAL_LLM", "").lower() in {"1", "true", "yes", "on"}:
        return rows
    candidates = [row for row in rows or [] if _needs_inline_material_llm(row)]
    if not candidates:
        return rows
    max_rows = max(1, int(os.getenv("INLINE_MATERIAL_SPLIT_MAX_ROWS", "8")))
    candidates = candidates[:max_rows]
    row_index_by_id = {id(row): idx for idx, row in enumerate(rows or [], start=1)}
    children_by_index: Dict[int, List[str]] = {}
    llm_candidates: List[Dict[str, Any]] = list(candidates)
    input_rows = [
        {
            "row_index": row_index_by_id[id(row)],
            "parent_name": row.get("name") or "",
            "quote": row.get("quote") or row.get("name") or "",
        }
        for row in llm_candidates
    ]
    prompt = (
        "你是招标文件目录材料拆解助手。只处理输入 quote 中明确列出的子材料。\n"
        "任务：对每个 row 判断 parent_name 是否需要拆成子目录；只输出原文 quote 连续出现或可直接对应的材料名。\n"
        "禁止推断、禁止补全、禁止把要求说明改写成新材料。找不到子材料就返回空 children。\n"
        "常见可拆：'报价函及应答函' -> ['报价函','应答函']；包含多个证照/截图/证明时逐项列出。\n"
        "不要输出父节点本身，不要输出泛化词如'相关证明文件'，除非原文只写了这个。\n"
        f"输入 rows：{input_rows}\n"
    )
    quote_by_index = {item["row_index"]: item["quote"] for item in input_rows}
    try:
        result = await _call_dimension_llm(
            prompt,
            InlineMaterialSplitResult,
            max_tokens=int(os.getenv("INLINE_MATERIAL_SPLIT_MAX_TOKENS", "900")),
            timeout_override_seconds=int(os.getenv("INLINE_MATERIAL_SPLIT_TIMEOUT_SECONDS", "18")),
        )
    except Exception as exc:
        logger.warning("[requirements] inline material LLM split skipped: {}", str(exc)[:160])
        return rows

    for item in result.items or []:
        row_index = int(item.row_index or 0)
        quote = quote_by_index.get(row_index, "")
        if not quote:
            continue
        supported = []
        for child in item.children or []:
            if _child_supported_by_quote(child, quote):
                supported.append(child)
        if supported:
            children_by_index[row_index] = list(dict.fromkeys(supported))
    if not children_by_index:
        return rows
    logger.info(
        "[requirements] inline material LLM split added {} child rows from {} parent rows",
        sum(len(v) for v in children_by_index.values()),
        len(children_by_index),
    )
    return _append_children_after_parent(rows, children_by_index)
