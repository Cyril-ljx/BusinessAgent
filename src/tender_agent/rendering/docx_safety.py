"""Safety guards for generated DOCX documents."""

from __future__ import annotations

import re

from docx.oxml.ns import qn

RAW_OOXML_TEXT_PATTERN = re.compile(r"(?:<|&lt;)/?(?:w|wp|a|r|mc|v|o):[A-Za-z]")


def remove_raw_ooxml_text_paragraphs(doc) -> int:
    """Remove visible paragraphs that contain raw Word/OpenXML markup text.

    This is a final safety guard for bad source material. It does not touch real
    DOCX XML structure; it only removes text that was accidentally pasted as
    visible body content, such as ``<w:p ...>``.
    """
    removed = 0
    for paragraph in list(doc.element.body.findall(".//" + qn("w:p"))):
        text = "".join(node.text or "" for node in paragraph.findall(".//" + qn("w:t")))
        if not text or not RAW_OOXML_TEXT_PATTERN.search(text):
            continue
        parent = paragraph.getparent()
        if parent is None:
            continue
        if str(parent.tag).endswith("}tc"):
            for node in paragraph.findall(".//" + qn("w:t")):
                node.text = ""
        else:
            parent.remove(paragraph)
        removed += 1
    return removed
