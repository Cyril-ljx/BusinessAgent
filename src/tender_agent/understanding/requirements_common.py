"""Shared helpers for requirement extraction modules."""

from __future__ import annotations

import re
from typing import Any, Dict, List


SELF_CHECK_TABLE_HEADER_TOKENS = ("自查结论", "证明资料位置", "评审内容", "是否符合")


def _trim_text(text: str, max_chars: int) -> str:
    value = (text or "").strip()
    if len(value) <= max_chars:
        return value
    head = max_chars * 3 // 5
    tail = max_chars - head - 80
    return f"{value[:head]}\n...[中间内容已压缩]...\n{value[-tail:]}"


def _trim_anchor_blocks(blocks: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
    trimmed: List[Dict[str, Any]] = []
    for block in (blocks or [])[:limit]:
        trimmed.append(
            {
                "anchor": block.get("anchor"),
                "kind": block.get("kind"),
                "text": _trim_text(str(block.get("text") or ""), 60),
            }
        )
    return trimmed


def _make_section_item(sec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "section_id": sec.get("section_id"),
        "source_section_id": sec.get("section_id"),
        "title": sec.get("title"),
        "relevance": sec.get("relevance"),
        "anchor_start": sec.get("anchor_start"),
        "anchor_end": sec.get("anchor_end"),
        "anchor_blocks": _trim_anchor_blocks(sec.get("anchor_blocks") or []),
        "content": str(sec.get("content", "") or ""),
    }


def _head_text_payload(head_text: str) -> Dict[str, Any]:
    return {
        "section_id": "head_text",
        "title": "文档开头信息",
        "relevance": "source: head_text",
        "anchor_start": "head_text",
        "anchor_end": "head_text",
        "anchor_blocks": [
            {"anchor": "head_text", "kind": "head_text", "text": _trim_text(head_text, 220)}
        ],
        "content": _trim_text(head_text, 700),
    }


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))
