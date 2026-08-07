"""Plan an outline tree from structured file-composition rows.

Planner consumes already structured rows only. It does not inspect tender source
text and does not know about rendering/material mapping.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from .outline_cleaner import (
    clean_source_name,
    expand_source_names,
    is_composition_wrapper_name,
    is_explicit_composition_row,
    looks_like_template_name,
    normalize_outline_key,
)


def build_outline_from_file_composition_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    index_tree = _build_index_table_outline_from_rows(rows)
    if index_tree:
        return index_tree

    entries = _source_row_entries(rows)
    records: List[Dict[str, Any]] = []
    node_by_key: Dict[str, Dict[str, Any]] = {}

    for entry in entries:
        name = entry["name"]
        key = normalize_outline_key(name)
        if not key or key in node_by_key:
            continue
        level = max(1, int(entry.get("level") or 1))
        node = {
            "id": "",
            "name": name,
            "required": True,
            "children": [],
            "source": "submission_requirement",
        }
        if entry.get("source_kind"):
            node["source_kind"] = entry["source_kind"]
        if entry.get("template_ref"):
            node["template_ref"] = entry["template_ref"]
        node["has_template"] = bool(entry.get("has_template") or entry.get("template_ref")) or looks_like_template_name(name)

        node_by_key[key] = node
        records.append({"entry": entry, "key": key, "level": level, "node": node})

    # Resolve explicit parent_name links only after every node is known. LLM
    # batches may return attachment children before their referenced parent.
    nodes: List[Dict[str, Any]] = []
    stack_by_level: Dict[int, Dict[str, Any]] = {}
    for record in records:
        entry = record["entry"]
        key = record["key"]
        level = record["level"]
        node = record["node"]
        parent = _find_parent(entry, level, stack_by_level, node_by_key, current_key=key)
        if parent is None:
            nodes.append(node)
            level = 1
        else:
            parent.setdefault("children", []).append(node)
        stack_by_level[level] = node
        for old_level in [item for item in stack_by_level if item > level]:
            stack_by_level.pop(old_level, None)

    _renumber_outline(nodes)
    return nodes


def _build_index_table_outline_from_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    group_order: List[str] = []

    for row in rows or []:
        if not isinstance(row, dict) or str(row.get("source_kind") or "") != "index_table":
            continue
        group = _index_table_group_from_row(row)
        name = clean_source_name(str(row.get("name") or row.get("requirement") or row.get("quote") or ""))
        if not group or not name or _is_index_table_header_token(name):
            continue
        group_key = normalize_outline_key(group)
        if not group_key:
            continue
        if group_key not in grouped:
            grouped[group_key] = []
            group_order.append(group_key)
        name_key = normalize_outline_key(name)
        if not name_key or any(normalize_outline_key(item["name"]) == name_key for item in grouped[group_key]):
            continue
        child = {
            "name": name,
            "required": True,
            "has_template": bool(row.get("has_template") or row.get("template_ref")),
            "source": "index_table",
            "source_kind": "index_table",
            "children": [],
        }
        if row.get("template_ref"):
            child["template_ref"] = row["template_ref"]
        grouped[group_key].append(child)

    if len(group_order) < 2:
        return []

    outline: List[Dict[str, Any]] = []
    for group_key in group_order:
        children = grouped.get(group_key) or []
        if not children:
            continue
        outline.append(
            {
                "id": "",
                "name": _display_group_name_from_key(group_key),
                "required": True,
                "has_template": False,
                "source": "index_table",
                "source_kind": "index_table",
                "children": children,
            }
        )
    _renumber_outline(outline)
    return outline


def _index_table_group_from_row(row: Dict[str, Any]) -> str:
    structured_group = _clean_index_table_group(str(row.get("parent_name") or ""))
    if structured_group and not _is_index_table_header_token(structured_group):
        return structured_group

    quote = str(row.get("quote") or "")
    requirement = row.get("requirement")
    if isinstance(requirement, dict) and not quote:
        quote = str(requirement.get("quote") or "")
    if "|" not in quote:
        return ""
    cells = [cell.strip() for cell in quote.strip().strip("|").split("|")]
    if len(cells) < 3:
        return ""
    group = _clean_index_table_group(cells[0])
    if _is_numeric_index_token(group) and len(cells) >= 4:
        group = _clean_index_table_group(cells[1])
    if _is_numeric_index_token(group):
        return ""
    return "" if _is_index_table_header_token(group) else group


def _clean_index_table_group(text: str) -> str:
    value = re.sub(r"\s+", "", str(text or ""))
    value = re.sub(r"[（(][^）)]{0,40}[）)]", "", value)
    value = re.sub(r"^供应商应提交的", "", value)
    return value.strip("：:，,。；;、")


def _display_group_name_from_key(key: str) -> str:
    return key or "提交材料"


def _is_index_table_header_token(text: str) -> bool:
    key = normalize_outline_key(text)
    return key in {
        "文件类型", "类型", "文件分类", "文件名称", "证明材料", "材料名称",
        "响应文件", "序号", "装订顺序", "序码", "提交情况", "页码范围",
        "页码", "备注", "有", "无", "格式", "文件名", "名称",
    }


def _is_numeric_index_token(text: str) -> bool:
    value = re.sub(r"\s+", "", str(text or ""))
    return bool(re.fullmatch(r"\d{1,3}", value))


def _source_row_entries(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        raw_name = str(row.get("name") or row.get("requirement") or row.get("quote") or "").strip()
        if not raw_name:
            continue
        names = [name for name in expand_source_names(raw_name) if name]
        if not names:
            continue
        parent_name = clean_source_name(str(row.get("parent_name") or ""))
        try:
            level = int(row.get("outline_level") or 1)
        except Exception:
            level = 1
        for name in names:
            source_kind = str(row.get("source_kind") or "")
            if (
                source_kind != "index_table"
                and is_composition_wrapper_name(name)
                and not is_explicit_composition_row(row)
            ):
                continue
            entries.append(
                {
                    "name": name,
                    "level": level,
                    "parent_name": parent_name,
                    "source_kind": source_kind,
                    "has_template": row.get("has_template"),
                    "template_ref": row.get("template_ref"),
                }
            )
    return entries


def _find_parent(
    entry: Dict[str, Any],
    level: int,
    stack_by_level: Dict[int, Dict[str, Any]],
    node_by_key: Dict[str, Dict[str, Any]],
    *,
    current_key: str = "",
) -> Dict[str, Any] | None:
    parent_name = str(entry.get("parent_name") or "").strip()
    parent_key = normalize_outline_key(parent_name)
    if parent_key and parent_key != current_key and parent_key in node_by_key:
        return node_by_key[parent_key]
    if level <= 1:
        return None
    for candidate_level in range(level - 1, 0, -1):
        parent = stack_by_level.get(candidate_level)
        if parent is not None:
            return parent
    return None


def _renumber_outline(nodes: List[Dict[str, Any]], prefix: str = "") -> None:
    for index, node in enumerate(nodes, 1):
        node_id = f"{prefix}.{index}" if prefix else str(index)
        node["id"] = node_id
        _renumber_outline(node.get("children") or [], node_id)
