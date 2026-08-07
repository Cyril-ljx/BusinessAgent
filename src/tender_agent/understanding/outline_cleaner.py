"""Clean and audit structured outline rows.

This module intentionally does not parse tender text and does not build a tree.
It only normalizes row names, removes shell nodes, merges duplicates, and exposes
the same cleaned source sequence used by planner diagnostics.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List


def normalize_outline_key(text: str) -> str:
    value = str(text or "")
    for token in ("（必填）", "(必填)", "（必须）", "(必须)", "（选填）", "(选填)"):
        value = value.replace(token, "")
    return "".join(value.split()).strip("：:，,。；;、")


def clean_source_name(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if is_shell_format_code(value):
        return ""
    # Only remove structural noise from copied catalogue rows. Do not rewrite
    # business semantics here; uncertain interpretation belongs to LLM/user review.
    value = re.sub(r"\s*[.·•…]{2,}\s*\d+\s*$", "", value).strip()
    value = re.sub(r"^格式\s*\d+(?:\.\d+)*\s*", "", value).strip()
    value = re.sub(r"^[一二三四五六七八九十]+[、.．]\s*", "", value)
    value = re.sub(r"^\d+(?:\.\d+)*[、.．)]?\s*", "", value)
    value = re.sub(r"^[（(][一二三四五六七八九十\d]+[）)]\s*", "", value)
    value = re.sub(r"^[-—•·●◆▶]\s*", "", value)
    value = value.strip("：:，,。；;、")
    return value


def is_shell_format_code(text: str) -> bool:
    value = "".join(str(text or "").split()).strip("：:，,。；;、")
    return bool(re.fullmatch(r"格式\d+(?:\.\d+)*", value))


def expand_source_names(text: str) -> List[str]:
    value = clean_source_name(text)
    return [value] if value else []




def looks_like_template_name(name: str) -> bool:
    """Template detection is no longer inferred from title keywords."""
    return False


def is_composition_wrapper_name(name: str) -> bool:
    key = normalize_outline_key(name)
    return key in {
        "投标文件",
        "响应文件",
        "报价文件",
        "投标文件组成",
        "响应文件组成",
        "报价文件组成",
    }


def is_explicit_composition_row(row: Dict[str, Any]) -> bool:
    quote = str(row.get("quote") or "").strip()
    return bool(
        re.match(
            r"^(?:\d+(?:\.\d+)*[、.．)]?|[（(][\d一二三四五六七八九十]+[）)]|[一二三四五六七八九十]+[、.．])\s*\S+",
            quote,
        )
    )


def source_rows_audit(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    names: List[str] = []
    ignored_items: List[Dict[str, str]] = []
    normalization_items: List[Dict[str, Any]] = []
    seen: set[str] = set()
    raw_count = 0

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        raw_name = str(row.get("name") or row.get("requirement") or row.get("quote") or "").strip()
        if not raw_name:
            continue
        raw_count += 1
        expanded = [name.strip() for name in expand_source_names(raw_name) if name.strip()]
        if not expanded:
            ignored_items.append(
                {
                    "raw_name": raw_name,
                    "reason": "shell_format_code" if is_shell_format_code(raw_name) else "empty_after_normalization",
                }
            )
            continue

        accepted_for_row: List[str] = []
        for name in expanded:
            if is_composition_wrapper_name(name) and not is_explicit_composition_row(row):
                ignored_items.append({"raw_name": raw_name, "normalized_name": name, "reason": "wrapper"})
                continue
            key = normalize_outline_key(name)
            if not key:
                ignored_items.append({"raw_name": raw_name, "normalized_name": name, "reason": "empty_key"})
                continue
            if key in seen:
                ignored_items.append({"raw_name": raw_name, "normalized_name": name, "reason": "duplicate"})
                continue
            seen.add(key)
            names.append(name)
            accepted_for_row.append(name)
        if accepted_for_row and (len(accepted_for_row) != 1 or accepted_for_row[0] != raw_name):
            normalization_items.append({"raw_name": raw_name, "normalized_names": accepted_for_row})

    return {
        "raw_count": raw_count,
        "effective_names": names,
        "ignored_items": ignored_items,
        "normalization_items": normalization_items,
    }
