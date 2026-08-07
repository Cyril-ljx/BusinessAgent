"""Import certificate images from a heading-structured DOCX bundle.

This module is the single implementation used by the API and maintenance
scripts. It is append-only by design: importing a bundle never deletes existing
certificate rows.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

DEFAULT_COMPANY_ID = "demo-company"


def _company_knowledge_dir(company_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(company_id or DEFAULT_COMPANY_ID)).strip("_")
    return Path("data/knowledge/companies") / (safe_id or DEFAULT_COMPANY_ID)


def detect_heading_level(para: Paragraph) -> int:
    """Detect Word/WPS heading level from style, outline level, or short numeric title."""
    style_name = (para.style.name or "").strip().lower()
    if style_name.startswith("heading "):
        try:
            return int(style_name.split(" ")[1])
        except (IndexError, ValueError):
            return 0
    if "标题 1" in style_name:
        return 1
    if "标题 2" in style_name:
        return 2
    if "标题 3" in style_name:
        return 3
    if "标题 4" in style_name:
        return 4

    try:
        p_pr = para._element.pPr
        if p_pr is not None:
            outline_lvl = p_pr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}outlineLvl")
            if outline_lvl is not None:
                val = outline_lvl.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val")
                if val is not None and str(val).isdigit():
                    return int(val) + 1
    except Exception:
        pass

    text = str(para.text or "").strip()
    if re.match(r"^\d+(?:\.\d+)*[.、\s]+", text) and len(text) <= 80:
        first = text.split()[0] if text.split() else text
        return min(first.count(".") + 1, 4)
    return 0


def clean_heading_text(text: str) -> str:
    """Strip leading chapter numbering while preserving years such as 2025."""
    value = str(text or "").strip()
    patterns = (
        r"^\d+(?:\.\d+)+\.?\s+(.+)$",
        r"^\d+\.\s+([^\d\s].*)$",
        r"^\d+(?:\.\d+)*\.\s*([^\d\s].*)$",
        r"^\d+、\s*(.+)$",
    )
    for pattern in patterns:
        match = re.match(pattern, value)
        if match:
            return match.group(1).strip() or "未命名证书"
    return value or "未命名证书"


def iter_docx_paragraphs_in_order(doc: Document) -> Iterator[Paragraph]:
    """Yield paragraphs from body and tables in visual order."""
    for child in doc.element.body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, doc)
        elif child.tag.endswith("}tbl"):
            table = Table(child, doc)
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        yield para


def image_extension_from_blob(blob: bytes, content_type: str = "") -> str:
    if blob.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if blob.startswith(b"GIF8"):
        return "gif"
    if blob.startswith(b"RIFF") and b"WEBP" in blob[:16]:
        return "webp"
    value = str(content_type or "").split("/")[-1].lower()
    if value in {"jpeg", "jpg"}:
        return "jpg"
    if value in {"png", "gif", "webp"}:
        return value
    return "png"


def import_certificate_images_from_docx(
    file_path: Path | str,
    company_id: str = DEFAULT_COMPANY_ID,
    scope: str = "company",
) -> Dict[str, Any]:
    """Append certificate image rows extracted from a DOCX heading structure."""
    from data.knowledge.models import Certificate
    from tender_agent.core.db import get_db_session

    source_path = Path(file_path)
    doc = Document(str(source_path))
    normalized_scope = "shared" if scope == "shared" else "company"

    image_rels: Dict[str, Dict[str, Any]] = {}
    for rel_id, rel in doc.part.rels.items():
        if "image" in str(rel.target_ref).lower():
            image_rels[rel_id] = {
                "blob": rel.target_part.blob,
                "content_type": rel.target_part.content_type,
            }

    heading_stack: Dict[int, str] = {}
    pending: list[Dict[str, Any]] = []
    heading_count = 0

    for para in iter_docx_paragraphs_in_order(doc):
        text = str(para.text or "").strip()
        level = detect_heading_level(para)
        if level > 0 and text:
            heading_stack[level] = clean_heading_text(text)
            for key in list(heading_stack.keys()):
                if key > level:
                    del heading_stack[key]
            heading_count += 1
            continue

        for blip in para._element.findall(".//" + qn("a:blip")):
            rid = blip.get(qn("r:embed"))
            if not rid or rid not in image_rels:
                continue
            deepest_level = max(heading_stack.keys()) if heading_stack else 0
            category = heading_stack.get(1) or "未分类"
            nearest = heading_stack.get(deepest_level) if deepest_level else None
            subcategory = heading_stack.get(2) if deepest_level >= 3 else None
            pending.append(
                {
                    "category": category,
                    "subcategory": subcategory,
                    "name": nearest or category,
                    "rel_id": rid,
                    "path": "/".join(heading_stack[key] for key in sorted(heading_stack)),
                }
            )

    cert_dir = (
        Path("data/knowledge/shared/certs")
        if normalized_scope == "shared"
        else _company_knowledge_dir(company_id) / "certs"
    )
    cert_dir.mkdir(parents=True, exist_ok=True)

    db = next(get_db_session())
    try:
        name_counter: Dict[str, int] = {}
        category_counter: Counter[str] = Counter()
        saved = 0
        for item in pending:
            rel_info = image_rels.get(item["rel_id"])
            if not rel_info:
                continue
            blob = rel_info["blob"]
            ext = image_extension_from_blob(blob, rel_info.get("content_type", ""))
            base_name = str(item["name"] or "未命名证书").strip() or "未命名证书"
            name_counter[base_name] = name_counter.get(base_name, 0) + 1
            display_name = base_name if name_counter[base_name] == 1 else f"{base_name}_{name_counter[base_name]}"
            save_path = cert_dir / f"{uuid.uuid4().hex}.{ext}"
            save_path.write_bytes(blob)

            row = Certificate(
                company_id=company_id if normalized_scope != "shared" else None,
                scope=normalized_scope,
                category=str(item["category"] or "未分类"),
                subcategory=item.get("subcategory") or None,
                name=display_name,
                file_path=str(save_path),
                file_type=ext,
                file_size=len(blob),
                is_current=True,
                metadata_info={
                    "source_import_docx": str(source_path),
                    "source_heading_path": item.get("path") or "",
                    "imported_at": datetime.now().isoformat(),
                },
            )
            db.add(row)
            saved += 1
            category_counter[row.category] += 1
        db.commit()
        return {
            "ok": True,
            "image_count": len(image_rels),
            "heading_count": heading_count,
            "imported_count": saved,
            "categories": [{"name": name, "count": count} for name, count in category_counter.most_common()],
        }
    finally:
        db.close()
