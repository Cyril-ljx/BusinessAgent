"""Structural attachment references shared by parsing and template copying."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple


AttachmentReference = Tuple[str, str]

_ATTACHMENT_REFERENCE_RE = re.compile(
    r"附(件|表|录)\s*([一二三四五六七八九十百零\d]+(?:\s*[-－—]\s*\d+)*)"
)
_BARE_ATTACHMENT_LABEL_RE = re.compile(
    r"附(?:件|表|录)[一二三四五六七八九十百零\d]+(?:[-－—]\d+)*[:：]?"
)
_LEADING_ATTACHMENT_LABEL_RE = re.compile(
    r"^附(?:件|表|录)[一二三四五六七八九十百零\d]+(?:[-－—]\d+)*[:：\s、.-]*"
)


def _anchor_order(value: Any) -> int:
    match = re.fullmatch(r"p(\d+)", str(value or "").strip())
    return int(match.group(1)) if match else 10**9


def attachment_reference(text: str) -> Optional[AttachmentReference]:
    """Return a canonical reference such as ``("表", "1")``."""
    match = _ATTACHMENT_REFERENCE_RE.search(str(text or ""))
    if not match:
        return None
    number = re.sub(r"\s+", "", match.group(2)).replace("－", "-").replace("—", "-")
    if number.isdigit():
        number = str(int(number))
    return match.group(1), number


def is_bare_attachment_label(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    return bool(compact and _BARE_ATTACHMENT_LABEL_RE.fullmatch(compact))


def strip_leading_attachment_label(text: str) -> str:
    return _LEADING_ATTACHMENT_LABEL_RE.sub("", str(text or "").strip())


def _reference_mentions(
    blocks: List[Dict[str, Any]],
    reference: AttachmentReference,
    *,
    before_index: int,
    limit: int = 8,
) -> List[Dict[str, str]]:
    mentions: List[Dict[str, str]] = []
    for block in blocks[:before_index]:
        text = str(block.get("text") or "").strip()
        if not text or is_bare_attachment_label(text) or attachment_reference(text) != reference:
            continue
        mentions.append(
            {
                "anchor": str(block.get("anchor") or ""),
                "text": text[:240],
            }
        )
    return mentions[-limit:]


def attachment_body_sections(
    block_index: Iterable[Dict[str, Any]],
    *,
    max_chars_per_section: int = 3200,
    max_total_chars: int = 16000,
) -> List[Dict[str, Any]]:
    """Build source-evidence sections bounded by explicit attachment labels.

    The function only establishes structural spans. It does not decide whether
    the body is a fillable form or a nested response checklist; that decision is
    intentionally left to the existing file-composition LLM.
    """
    blocks = [dict(item) for item in block_index or [] if isinstance(item, dict)]
    starts = [
        index
        for index, block in enumerate(blocks)
        if is_bare_attachment_label(str(block.get("text") or ""))
    ]
    if not starts:
        return []

    best_by_reference: Dict[AttachmentReference, Tuple[int, Dict[str, Any]]] = {}
    for position, start in enumerate(starts):
        label = str(blocks[start].get("text") or "").strip()
        reference = attachment_reference(label)
        if reference is None:
            continue
        end = starts[position + 1] if position + 1 < len(starts) else len(blocks)
        body = [block for block in blocks[start + 1 : end] if str(block.get("text") or "").strip()]
        if not body:
            continue

        body_texts = [str(block.get("text") or "").strip() for block in body]
        full_content = "\n".join([label, *body_texts])
        content = full_content[:max_chars_per_section]
        reference_mentions = _reference_mentions(blocks, reference, before_index=start)
        has_table = any(str(block.get("kind") or "") == "table" for block in body)
        score = min(len(full_content), max_chars_per_section) + (2000 if has_table else 0) + start
        section = {
            "section_id": f"attachment_body:{reference[0]}:{reference[1]}",
            "chunk_id": f"attachment_body:{reference[0]}:{reference[1]}",
            "title": f"{label} {body_texts[0]}".strip(),
            "content": content,
            "relevance": "投标文件组成条目引用的附件正文",
            "requirement_tags": ["file_composition"],
            "source_kind": "attachment_body",
            "attachment_reference": {"kind": reference[0], "number": reference[1]},
            "reference_mentions": reference_mentions,
            "anchor_start": str(blocks[start].get("anchor") or ""),
            "anchor_end": str(body[-1].get("anchor") or blocks[start].get("anchor") or ""),
            "anchor_blocks": [
                {
                    "anchor": str(block.get("anchor") or ""),
                    "text": str(block.get("text") or "")[:120],
                    "kind": str(block.get("kind") or ""),
                }
                for block in body[:16]
            ],
        }
        previous = best_by_reference.get(reference)
        if previous is None or score > previous[0]:
            best_by_reference[reference] = (score, section)

    result: List[Dict[str, Any]] = []
    total_chars = 0
    for _, section in sorted(
        best_by_reference.values(),
        key=lambda item: _anchor_order(item[1].get("anchor_start")),
    ):
        content = str(section.get("content") or "")
        if result and total_chars + len(content) > max_total_chars:
            break
        result.append(section)
        total_chars += len(content)
    return result
