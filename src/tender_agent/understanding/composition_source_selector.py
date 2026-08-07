"""Select the authoritative source used to build the bid outline.

This module is source-shape based. It decides where the outline should come
from, but never decides which business material should be pasted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from .index_table_composition import _index_table_composition_rows
from .outline_cleaner import clean_source_name
from .outline_planner import build_outline_from_file_composition_rows


@dataclass
class CompositionSource:
    kind: str
    outline: List[Dict[str, Any]]
    reason: str


def select_structured_composition_source(
    *,
    located_sections: List[Dict[str, Any]],
    block_index: List[Dict[str, Any]],
    tender_requirements: Dict[str, Any],
) -> CompositionSource | None:
    """Return a structured outline source, or None when user review is needed."""
    index_outline = _index_table_outline(located_sections, block_index)
    if index_outline:
        return CompositionSource("index_table", index_outline, "explicit index/table directory")

    file_rows = _effective_file_composition_rows(tender_requirements)
    if file_rows:
        outline = build_outline_from_file_composition_rows(file_rows)
        if outline:
            return CompositionSource("file_composition", outline, "structured file_composition rows")

    return None


def _index_table_outline(
    located_sections: List[Dict[str, Any]],
    block_index: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    for sec in located_sections or []:
        rows = _index_table_rows_from_text(str(sec.get("content") or ""), str(sec.get("title") or ""))
        outline = build_outline_from_file_composition_rows(rows)
        if outline:
            return outline

    for block in block_index or []:
        if not isinstance(block, dict):
            continue
        text = str(block.get("text") or "")
        if "|" not in text:
            continue
        rows = _index_table_rows_from_text(text, "索引目录表")
        outline = build_outline_from_file_composition_rows(rows)
        if outline:
            return outline
    return []


def _index_table_rows_from_text(content: str, title: str) -> List[Dict[str, Any]]:
    rows = _index_table_composition_rows({"title": title or "索引目录表", "content": content or ""})
    result: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = clean_source_name(str(row.get("name") or ""))
        if not name:
            continue
        item = dict(row)
        item["name"] = name
        item["source"] = "index_table"
        item["source_kind"] = "index_table"
        item["source_backed_composition"] = True
        item["required"] = True
        item["has_template"] = bool(item.get("has_template"))
        result.append(item)
    return result


def _effective_file_composition_rows(tender_requirements: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = tender_requirements.get("file_composition") if isinstance(tender_requirements, dict) else []
    result: List[Dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = clean_source_name(str(row.get("name") or row.get("requirement") or row.get("quote") or ""))
        if not name:
            continue
        item = dict(row)
        item["name"] = name
        item["source"] = item.get("source") or "file_composition"
        item["source_kind"] = item.get("source_kind") or "file_composition"
        item["required"] = True
        item["has_template"] = bool(item.get("has_template"))
        result.append(item)
    return result
