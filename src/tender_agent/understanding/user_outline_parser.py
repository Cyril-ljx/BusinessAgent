"""Parse user-confirmed bid outlines.

This module is intentionally small: when a business user pastes the intended
bid-document directory, we should trust that text as the outline source instead
of running it through the automatic tender-source heuristics.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from ..llm.gateway import llm_gateway


class UserOutlineNode(BaseModel):
    name: str = Field(description="Short directory item title.")
    required: bool = True
    has_template: bool = False
    source_text: str | None = Field(default=None, description="Original pasted line or cell text.")
    children: list["UserOutlineNode"] = Field(default_factory=list)


UserOutlineNode.model_rebuild()


class UserOutlineParseResult(BaseModel):
    outline: list[UserOutlineNode] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


USER_OUTLINE_PROMPT = """You are a bid-document outline parser.

The user pasted a directory/table/range that they want to use as the bid
document outline. Convert only the pasted text into a clean outline tree.

Rules:
1. Use only the pasted text. Do not infer missing chapters from experience.
2. Preserve the original order.
3. Infer hierarchy from numbering, indentation, bullets, table rows, and repeated
   parent-child patterns.
4. Keep parenthetical explanations inside the parent item name or source_text;
   do not split them into child chapters.
5. Remove pure page numbers, dotted leaders, headers/footers, and table columns
   such as page/no/remark/status when they are not directory items.
6. If the text is a flat list, return a flat outline.
7. If a row clearly mentions a form/template/attachment/format, set
   has_template=true. Otherwise leave it false.
8. Titles should be short, but do not change their business meaning.

Return strict JSON only:
{
  "outline": [
    {
      "name": "chapter title",
      "required": true,
      "has_template": false,
      "source_text": "original pasted text for this item",
      "children": []
    }
  ],
  "notes": []
}

[Pasted outline text]
{outline_text}
"""


def _clean_outline_name(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"^\s*(?:\d+(?:[\.．]\d+)*|[一二三四五六七八九十百千]+)[、\.．)]?\s+", "", text)
    text = re.sub(r"^\s*\(?[一二三四五六七八九十百千\d]+\)?[、\.．)]\s*", "", text)
    text = re.sub(r"\s*[.·•…-]{2,}\s*\d+\s*$", "", text)
    text = re.sub(r"\s+\d+\s*$", "", text)
    return text.strip()


def _node_to_dict(node: UserOutlineNode) -> dict[str, Any]:
    name = _clean_outline_name(node.name)
    if not name:
        source_text = _clean_outline_name(node.source_text)
        name = source_text
    return {
        "id": "",
        "name": name,
        "level": 1,
        "required": bool(node.required),
        "has_template": bool(node.has_template),
        "source": "user_provided_outline",
        "source_kind": "user_provided_outline",
        "source_text": str(node.source_text or node.name or "").strip(),
        "children": [
            child
            for child in (_node_to_dict(item) for item in (node.children or []))
            if child.get("name")
        ],
    }


_NUMBERED_OUTLINE_LINE = re.compile(
    r"^\s*(?P<number>\d+(?:[.．]\d+)*)\s*(?:[、.．):：]\s*)?(?P<name>\S.*)$"
)


def _parse_numbered_outline(raw_text: str) -> list[dict[str, Any]]:
    """Parse explicit decimal numbering without involving the LLM."""
    parsed_rows: list[tuple[tuple[int, ...], str, str]] = []
    nonempty_lines = 0
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        nonempty_lines += 1
        match = _NUMBERED_OUTLINE_LINE.match(line)
        if not match:
            continue
        number_text = match.group("number").replace("．", ".")
        name = match.group("name").strip().rstrip(":：").strip()
        if not name:
            continue
        parsed_rows.append(
            (tuple(int(part) for part in number_text.split(".")), name, line)
        )

    # Mixed prose should still go through the semantic parser. A real numbered
    # directory normally has at least two entries and mostly numbered lines.
    if len(parsed_rows) < 2 or len(parsed_rows) / max(1, nonempty_lines) < 0.6:
        return []

    roots: list[dict[str, Any]] = []
    nodes_by_number: dict[tuple[int, ...], dict[str, Any]] = {}
    for number, name, source_text in parsed_rows:
        node = {
            "id": "",
            "name": name,
            "level": len(number),
            "required": True,
            "has_template": False,
            "source": "user_provided_outline",
            "source_kind": "user_provided_outline",
            "source_text": source_text,
            "children": [],
        }
        parent = nodes_by_number.get(number[:-1]) if len(number) > 1 else None
        if parent is None:
            roots.append(node)
        else:
            parent["children"].append(node)
        nodes_by_number[number] = node

    return renumber_user_outline(roots)


def renumber_user_outline(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Renumber user-provided outline without applying auto-detection cleanup."""
    cleaned: list[dict[str, Any]] = []
    for raw in nodes or []:
        if not isinstance(raw, dict):
            continue
        name = _clean_outline_name(raw.get("name"))
        if not name:
            continue
        item = dict(raw)
        item["name"] = name
        item["required"] = bool(item.get("required", True))
        item["has_template"] = bool(item.get("has_template", False))
        item["source"] = "user_provided_outline"
        item["source_kind"] = "user_provided_outline"
        item["children"] = renumber_user_outline(item.get("children") or [])
        cleaned.append(item)

    def walk(items: list[dict[str, Any]], prefix: str = "") -> None:
        for index, item in enumerate(items, 1):
            node_id = f"{prefix}.{index}" if prefix else str(index)
            item["id"] = node_id
            item["level"] = node_id.count(".") + 1
            walk(item.get("children") or [], node_id)

    walk(cleaned)
    return cleaned


def outline_has_user_source(nodes: list[dict[str, Any]]) -> bool:
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        if str(node.get("source_kind") or node.get("source") or "") == "user_provided_outline":
            return True
        if outline_has_user_source(node.get("children") or []):
            return True
    return False


async def parse_user_outline_text(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    raw_text = str(text or "").strip()
    if len(raw_text) < 8:
        raise ValueError("Outline text is too short")

    numbered_outline = _parse_numbered_outline(raw_text)
    if numbered_outline:
        return numbered_outline, []

    prompt = USER_OUTLINE_PROMPT.replace("{outline_text}", raw_text[:30000])
    parsed: UserOutlineParseResult = await llm_gateway.async_call_structured(
        prompt,
        UserOutlineParseResult,
        max_tokens=5000,
    )
    nodes = [_node_to_dict(item) for item in parsed.outline or []]
    outline = renumber_user_outline([item for item in nodes if item.get("name")])
    if not outline:
        raise ValueError("No outline items were parsed")
    return outline, [str(item).strip() for item in (parsed.notes or []) if str(item).strip()]
