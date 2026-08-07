"""Text cleanup helpers for source-backed file composition."""

from __future__ import annotations

import re

from .requirements_common import _compact_text


def _clean_composition_line(line: str) -> str:
    value = str(line or "").strip()
    value = re.sub(r"^\s*#{1,6}\s*", "", value)
    value = re.sub(r"^\s*[★☆*□☑√✓\[\]【】]+\s*", "", value)
    value = re.sub(r"^\s*\d+(?:\.\d+){1,4}\s*", "", value)
    value = re.sub(r"^\s*[（(]\s*[\d一二三四五六七八九十]+\s*[）)][、.)）．]?\s*", "", value)
    value = re.sub(r"^\s*[\d一二三四五六七八九十]+[、.)．]\s*", "", value)
    value = re.sub(r"^\s*[-–—●•]\s*", "", value)
    value = re.sub(r"\s+[-–—]?\s*\d+\s*[-–—]?\s*$", "", value)
    return value.strip()


def _is_unselected_submission_option(line: str) -> bool:
    # PDF/DOCX parsers may expose checklist rows as Markdown headings, e.g.
    # ``## 三、[X]联合体协议书``. Strip structural prefixes before reading the
    # selected/unselected marker so excluded rows never enter the outline.
    compact = _compact_text(_clean_composition_line(line)).upper()
    return bool(re.match(r"^(?:\[[X×]\]|【[X×]】|[（(][X×][）)]|[X×][、.．])", compact))


def _clean_source_backed_option_name(line: str) -> str:
    value = str(line or "").strip()
    value = re.sub(r"^\s*(?:\[[√✓]\]|【[√✓]】|[（(][√✓][）)]|☑)\s*", "", value)
    value = re.sub(r"^\s*\[?\s*[√✓]\s*\]?\s*", "", value)
    value = re.sub(r"[（(]适用于[^）)]{1,40}情况[）)]", "", value)
    return value.strip()


def _composition_shape_text(text: str) -> str:
    """Drop URL/domain noise before judging whether a line is a short material row."""
    value = str(text or "")
    value = re.sub(r"https?://[^\s）)；;，,]+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"(?:www\.)?[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:/[^\s）)；;，,]*)?", "", value)
    return value
