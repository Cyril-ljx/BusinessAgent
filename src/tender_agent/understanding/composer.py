"""Bid outline composer.

This module deliberately keeps only the orchestration boundary for outline
review. It does not infer business materials, does not expand scoring items, and
does not patch tender-specific wording. Directory extraction is delegated to the
source selector and planner; if no explicit directory structure is found, the
workflow stops for user review/paste.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from loguru import logger

from .composition_source_selector import select_structured_composition_source


def _normalize_outline_similarity_text(value: str) -> str:
    """Normalize text for loose equality checks used outside composer."""
    text = re.sub(r"\s+", "", str(value or ""))
    text = re.sub(r"^第[一二三四五六七八九十\d]+[章节部分篇条]?", "", text)
    text = re.sub(r"^\d+(?:\.\d+)*[、.．)]?", "", text)
    return text.strip("：:，,。；;、（）()[]【】")


def normalize_outline_numbering(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Renumber outline nodes without semantic filtering or keyword patches."""

    def is_number_only_title(value: Any) -> bool:
        text = re.sub(r"\s+", "", str(value or ""))
        return bool(re.fullmatch(r"\d{1,3}", text))

    def collapse_number_wrappers(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        collapsed: List[Dict[str, Any]] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            node = dict(item)
            children = collapse_number_wrappers(node.get("children") or [])
            node["children"] = children
            if is_number_only_title(node.get("name")) and len(children) == 1:
                child = dict(children[0])
                child.setdefault("source", node.get("source"))
                child.setdefault("source_kind", node.get("source_kind"))
                collapsed.append(child)
                continue
            collapsed.append(node)
        return collapsed

    def clone_walk(items: List[Dict[str, Any]], prefix: str = "") -> List[Dict[str, Any]]:
        cloned: List[Dict[str, Any]] = []
        for index, item in enumerate(items or [], start=1):
            if not isinstance(item, dict):
                continue
            new_id = f"{prefix}.{index}" if prefix else str(index)
            node = dict(item)
            node["id"] = new_id
            node["level"] = new_id.count(".") + 1
            node["children"] = clone_walk(node.get("children") or [], new_id)
            cloned.append(node)
        return cloned

    return clone_walk(collapse_number_wrappers(nodes or []))


async def compose_outline(state: dict) -> dict:
    """Build outline only from explicit directory structure.

    Accepted sources are selected by shape, not by tender-specific keyword
    patches: explicit index/table rows and structured file-composition rows.
    If neither exists, return an empty draft and let the user paste/edit the
    outline before material mapping.
    """
    located_sections = state.get("located_sections") or []
    existing_outline = state.get("final_outline") or state.get("outline") or []

    if not located_sections:
        if existing_outline:
            outline = normalize_outline_numbering(existing_outline)
            return {"final_outline": outline, "outline": outline}
        return {
            "final_outline": [],
            "outline": [],
            "warnings": ["[composer] 未定位到目录性章节，请粘贴目录重建或手动编辑"],
        }

    if not any(str(sec.get("content") or "").strip() for sec in located_sections):
        if existing_outline:
            outline = normalize_outline_numbering(existing_outline)
            logger.warning("[composer] located_sections has no content; reusing existing outline")
            return {
                "final_outline": outline,
                "outline": outline,
                "warnings": ["[composer] located_sections has no content; reused existing outline"],
            }
        logger.warning("[composer] located_sections has no content; waiting for user outline review")
        return {
            "final_outline": [],
            "outline": [],
            "warnings": ["[composer] located_sections has no content; please paste or edit outline"],
        }

    selected_source = select_structured_composition_source(
        located_sections=located_sections,
        block_index=state.get("block_index") or [],
        tender_requirements=state.get("tender_requirements") or {},
    )
    if selected_source and selected_source.outline:
        outline = normalize_outline_numbering(selected_source.outline)
        logger.info(
            "[composer] structured source selected: kind={}, reason={}, top_nodes={}",
            selected_source.kind,
            selected_source.reason,
            len(outline),
        )
        return {"final_outline": outline, "outline": outline}

    logger.warning("[composer] no explicit bid-file directory source selected; waiting for user review")
    return {
        "final_outline": [],
        "outline": [],
        "warnings": ["[composer] 未识别到明确的投标/响应文件目录结构，请粘贴目录重建或手动编辑后再匹配素材"],
    }
