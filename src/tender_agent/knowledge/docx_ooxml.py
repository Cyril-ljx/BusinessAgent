"""Low-level DOCX OOXML helpers shared by renderers and copiers."""

from __future__ import annotations

from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def remove_element(element) -> None:
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def append_body_block(target_doc, block) -> None:
    body = target_doc.element.body
    sect_pr = body.sectPr
    if sect_pr is not None:
        body.insert(body.index(sect_pr), block)
    else:
        body.append(block)


def block_has_page_break(block) -> bool:
    return any(page_break.get(qn("w:type")) == "page" for page_break in block.findall(".//" + qn("w:br")))


def block_text(block) -> str:
    return "".join(node.text or "" for node in block.iter() if node.text)


def strip_page_break_marks(block) -> None:
    for page_break in list(block.findall(".//" + qn("w:br"))):
        if page_break.get(qn("w:type")) == "page":
            remove_element(page_break)
    for tag in ("w:lastRenderedPageBreak", "w:pageBreakBefore"):
        for element in list(block.findall(".//" + qn(tag))):
            remove_element(element)


def strip_section_properties(block) -> None:
    for sect_pr in block.findall(".//" + qn("w:sectPr")):
        remove_element(sect_pr)


def paragraph_visible_text(paragraph) -> str:
    return "".join(node.text or "" for node in paragraph_body_text_nodes(paragraph)).strip()


def paragraph_body_text_nodes(paragraph) -> list:
    return [node for node in paragraph.iter() if node.tag.endswith("}t") and not is_inside_non_body_text(node)]


def is_inside_non_body_text(node) -> bool:
    parent = node.getparent()
    blocked_suffixes = (
        "}drawing",
        "}pict",
        "}txbxContent",
        "}textbox",
        "}shape",
    )
    while parent is not None:
        if str(parent.tag).endswith(blocked_suffixes):
            return True
        parent = parent.getparent()
    return False


def inline_floating_drawings(block) -> None:
    """Convert floating drawings to inline so copied objects do not cover text."""
    for anchor in list(block.findall(".//" + qn("wp:anchor"))):
        for tag in (
            "wp:simplePos",
            "wp:positionH",
            "wp:positionV",
            "wp:wrapNone",
            "wp:wrapSquare",
            "wp:wrapTight",
            "wp:wrapThrough",
            "wp:wrapTopAndBottom",
        ):
            for child in list(anchor.findall(qn(tag))):
                anchor.remove(child)
        for attr in ("simplePos", "relativeHeight", "behindDoc", "locked", "layoutInCell", "allowOverlap"):
            anchor.attrib.pop(attr, None)
        anchor.tag = qn("wp:inline")


def fit_copied_tender_template_tables_to_page(block, target_doc) -> None:
    """Preserve copied form proportions, shrinking only tables wider than the page body."""
    available_width = target_content_width_twips(target_doc)
    if available_width <= 0:
        return

    tables = []
    if block.tag == qn("w:tbl"):
        tables.append(block)
    tables.extend(block.findall(".//" + qn("w:tbl")))

    for tbl in tables:
        measured_width = copied_table_width_twips(tbl)
        if measured_width <= 0:
            fit_unknown_width_table_to_page(tbl)
            continue
        indent = max(0, table_indent_twips(tbl))
        total_width = measured_width + indent
        if total_width <= available_width:
            continue
        ratio = min(1.0, available_width / float(total_width))
        clear_table_indent(tbl)
        scale_copied_table_widths(tbl, ratio)


def target_content_width_twips(target_doc) -> int:
    try:
        section = target_doc.sections[-1]
        width_emu = int(section.page_width) - int(section.left_margin) - int(section.right_margin)
        return max(0, int(width_emu / 635))
    except Exception:
        return 0


def copied_table_width_twips(tbl) -> int:
    widths = [table_declared_width_twips(tbl), table_grid_width_twips(tbl), table_max_row_width_twips(tbl)]
    return max(widths)


def table_declared_width_twips(tbl) -> int:
    tbl_pr = tbl.find(qn("w:tblPr"))
    if tbl_pr is None:
        return 0
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None or tbl_w.get(qn("w:type")) != "dxa":
        return 0
    return safe_int(tbl_w.get(qn("w:w")))


def table_grid_width_twips(tbl) -> int:
    tbl_grid = tbl.find(qn("w:tblGrid"))
    if tbl_grid is None:
        return 0
    return sum(safe_int(col.get(qn("w:w"))) for col in tbl_grid.findall(qn("w:gridCol")))


def table_max_row_width_twips(tbl) -> int:
    max_width = 0
    for row in tbl.findall(".//" + qn("w:tr")):
        row_width = 0
        for cell in row.findall(qn("w:tc")):
            tc_pr = cell.find(qn("w:tcPr"))
            if tc_pr is None:
                continue
            tc_w = tc_pr.find(qn("w:tcW"))
            if tc_w is None or tc_w.get(qn("w:type")) != "dxa":
                continue
            row_width += safe_int(tc_w.get(qn("w:w")))
        max_width = max(max_width, row_width)
    return max_width


def table_indent_twips(tbl) -> int:
    tbl_pr = tbl.find(qn("w:tblPr"))
    if tbl_pr is None:
        return 0
    tbl_ind = tbl_pr.find(qn("w:tblInd"))
    if tbl_ind is None or tbl_ind.get(qn("w:type")) != "dxa":
        return 0
    return safe_int(tbl_ind.get(qn("w:w")))


def clear_table_indent(tbl) -> None:
    tbl_pr = tbl.find(qn("w:tblPr"))
    if tbl_pr is None:
        return
    for tbl_ind in list(tbl_pr.findall(qn("w:tblInd"))):
        tbl_pr.remove(tbl_ind)


def scale_copied_table_widths(tbl, ratio: float) -> None:
    for element in tbl.findall(".//" + qn("w:tblW")):
        if element.get(qn("w:type")) == "dxa":
            scale_width_attr(element, ratio)
    for element in tbl.findall(".//" + qn("w:gridCol")):
        scale_width_attr(element, ratio)
    for element in tbl.findall(".//" + qn("w:tcW")):
        if element.get(qn("w:type")) == "dxa":
            scale_width_attr(element, ratio)


def fit_unknown_width_table_to_page(tbl) -> None:
    tbl_pr = tbl.find(qn("w:tblPr"))
    if tbl_pr is None:
        tbl_pr = OxmlElement("w:tblPr")
        tbl.insert(0, tbl_pr)
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.insert(0, tbl_w)
    if tbl_w.get(qn("w:type")) not in {"dxa", "pct"}:
        tbl_w.set(qn("w:type"), "pct")
        tbl_w.set(qn("w:w"), "5000")


def scale_width_attr(element, ratio: float) -> None:
    width = safe_int(element.get(qn("w:w")))
    if width <= 0:
        return
    element.set(qn("w:w"), str(max(1, int(width * ratio))))


def safe_int(value) -> int:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return 0
