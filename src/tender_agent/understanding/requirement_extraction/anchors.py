"""Anchor hydration helpers for requirement extraction outputs."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from ..requirements import SourceAnchor
from ..requirements_common import _compact_text, _trim_anchor_blocks


def _simple_anchor(item: Dict[str, Any]) -> SourceAnchor | None:
    if item.get("section_id") or item.get("section_title"):
        return SourceAnchor(
            section_id=item.get("section_id"),
            section_title=item.get("section_title"),
            anchor_start=item.get("anchor_start"),
            anchor_end=item.get("anchor_end"),
            anchor_blocks=item.get("anchor_blocks") or [],
        )
    return None


def _build_section_anchor_lookup(sections_payload: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for section in sections_payload or []:
        section_id = str(section.get("section_id") or "").strip()
        if not section_id:
            continue
        lookup[section_id] = {
            "section_id": section.get("section_id"),
            "section_title": section.get("title") or section.get("section_title"),
            "anchor_start": section.get("anchor_start"),
            "anchor_end": section.get("anchor_end"),
            "anchor_blocks": section.get("anchor_blocks") or [],
        }
    return lookup


def _attach_anchor_details(target: Dict[str, Any], lookup: Dict[str, Dict[str, Any]]) -> None:
    section_id = str(target.get("section_id") or "").strip()
    if not section_id:
        return
    source = lookup.get(section_id)
    if not source:
        return
    if not target.get("section_title"):
        target["section_title"] = source.get("section_title")
    if not target.get("anchor_start"):
        target["anchor_start"] = source.get("anchor_start")
    if not target.get("anchor_end"):
        target["anchor_end"] = source.get("anchor_end")
    if not target.get("anchor_blocks"):
        target["anchor_blocks"] = source.get("anchor_blocks") or []


def _anchor_quote_candidates(value: Any) -> List[str]:
    candidates: List[str] = []

    def push(raw: Any) -> None:
        if raw is None:
            return
        if isinstance(raw, dict):
            for key in ("quote", "value", "name", "item", "condition", "field", "time"):
                push(raw.get(key))
            return
        if isinstance(raw, list):
            for item in raw:
                push(item)
            return
        text = str(raw or "").strip()
        compact = _compact_text(text)
        if len(compact) < 4:
            return
        candidates.append(text)

    for key in ("quote", "value", "name", "item", "condition", "field", "time", "required_value", "requirement", "criteria"):
        push(value.get(key) if isinstance(value, dict) else None)

    deduped: List[str] = []
    seen: set[str] = set()
    for item in candidates:
        compact = _compact_text(item)
        if compact in seen:
            continue
        seen.add(compact)
        deduped.append(item)
    return deduped


def _quote_fragments(text: str) -> List[str]:
    raw = str(text or "").strip()
    compact = _compact_text(raw)
    fragments: List[str] = []
    if len(compact) >= 6:
        fragments.extend([compact, compact[:120], compact[:80], compact[:50], compact[:30]])
    for token in re.split(r"[\n\r\|，,。；;：:、/\s]+", raw):
        piece = _compact_text(token)
        if len(piece) >= 6:
            fragments.append(piece[:80])
    deduped: List[str] = []
    seen: set[str] = set()
    for item in sorted((frag for frag in fragments if frag), key=len, reverse=True):
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _select_precise_anchor_block(target: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any] | None:
    blocks = source.get("anchor_blocks") or []
    if not blocks:
        return None

    candidates = _anchor_quote_candidates(target)
    if not candidates:
        return None

    best_block: Dict[str, Any] | None = None
    best_score = 0
    for block in blocks:
        block_text = str(block.get("text") or "").strip()
        block_compact = _compact_text(block_text)
        if len(block_compact) < 4:
            continue
        score = 0
        for candidate in candidates:
            for fragment in _quote_fragments(candidate):
                if fragment and fragment in block_compact:
                    score = max(score, 1000 + min(len(fragment), 200))
                    break
            if score >= 1000:
                break
        if score > best_score:
            best_score = score
            best_block = block

    if best_block is None or best_score < 1006:
        return None
    return best_block


def _refine_anchor_details(target: Dict[str, Any], lookup: Dict[str, Dict[str, Any]]) -> None:
    section_id = str(target.get("section_id") or "").strip()
    if not section_id:
        return
    source = lookup.get(section_id) or {}
    precise = _select_precise_anchor_block(target, source)
    if not precise:
        return
    target["anchor_start"] = precise.get("anchor")
    target["anchor_end"] = precise.get("anchor")
    target["anchor_blocks"] = _trim_anchor_blocks([precise], limit=1)


def _hydrate_nested_atom_anchor(container: Dict[str, Any], atom_key: str, lookup: Dict[str, Dict[str, Any]]) -> None:
    atom = container.get(atom_key)
    if not isinstance(atom, dict):
        return

    anchor = atom.get("anchor") if isinstance(atom.get("anchor"), dict) else {}
    section_id = str(
        anchor.get("section_id")
        or atom.get("section_id")
        or container.get("section_id")
        or ""
    ).strip()
    if not section_id:
        return

    source = lookup.get(section_id)
    if not source:
        return

    hydrated_anchor = dict(anchor)
    hydrated_anchor.setdefault("section_id", section_id)
    hydrated_anchor.setdefault("section_title", atom.get("section_title") or container.get("section_title") or source.get("section_title"))
    _attach_anchor_details(hydrated_anchor, lookup)

    probe = {
        "section_id": section_id,
        "quote": atom.get("quote") or container.get("quote") or "",
        "value": atom.get("value") or container.get("value") or atom.get("name") or container.get("name") or "",
        "name": atom.get("name") or container.get("name") or "",
        "item": atom.get("item") or container.get("item") or "",
        "condition": atom.get("condition") or container.get("condition") or "",
        "field": atom.get("field") or container.get("field") or "",
        "time": atom.get("time") or container.get("time") or "",
    }
    _refine_anchor_details(probe, lookup)
    if probe.get("anchor_start"):
        hydrated_anchor["anchor_start"] = probe.get("anchor_start")
        hydrated_anchor["anchor_end"] = probe.get("anchor_end")
        hydrated_anchor["anchor_blocks"] = probe.get("anchor_blocks") or []

    atom["anchor"] = hydrated_anchor


def _hydrate_payload_anchors(value: Any, lookup: Dict[str, Dict[str, Any]]) -> Any:
    """Fill precise block anchors for LLM outputs that only returned section_id."""
    if isinstance(value, list):
        for item in value:
            _hydrate_payload_anchors(item, lookup)
        return value
    if not isinstance(value, dict):
        return value

    _attach_anchor_details(value, lookup)
    _refine_anchor_details(value, lookup)
    for atom_key in ("requirement", "required_value", "criteria", "time"):
        _hydrate_nested_atom_anchor(value, atom_key, lookup)
    anchor = value.get("anchor")
    if isinstance(anchor, dict):
        _attach_anchor_details(anchor, lookup)
    for child in value.values():
        _hydrate_payload_anchors(child, lookup)
    return value
