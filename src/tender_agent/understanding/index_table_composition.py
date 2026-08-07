"""Index-table extraction for source-backed file composition."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from .requirements_common import _compact_text


_INDEX_CATEGORY_HEADERS = {"文件类型", "类型", "文件分类"}
_INDEX_MATERIAL_HEADERS = {"文件名称", "证明材料", "材料名称", "响应文件"}
_INDEX_ORDER_HEADERS = {"序号", "装订顺序", "序码"}
_INDEX_FORMAT_HEADERS = {"格式", "格式要求", "文件格式"}
_INDEX_HEADER_TOKENS = (
    _INDEX_CATEGORY_HEADERS
    | _INDEX_MATERIAL_HEADERS
    | _INDEX_ORDER_HEADERS
    | _INDEX_FORMAT_HEADERS
    | {"提交情况", "页码范围", "页码", "备注", "有", "无"}
)
_EXPLICIT_FORMAT_RE = re.compile(
    r"格式\s*([〇零一二三四五六七八九十百两0-9]+)"
    r"(?:\s*[-－—]\s*([〇零一二三四五六七八九十百两0-9]+))?"
)


def _clean_index_table_cell_subject(cell: str, *, category: bool = False) -> str:
    value = str(cell or "").strip()
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"\r\n?", "\n", value)
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) > 1:
        first = re.sub(r"\s+", "", lines[0])
        if first and len(first) <= 48:
            value = first
    compact = re.sub(r"\s+", "", value)
    if not compact:
        return ""
    explanation_markers = (
        "有一项不符合要求",
        "不能进入下一阶段评审",
        "截至递交",
        "截至响应",
        "截至投标",
        "截至报价",
        "经信用中国",
        "报价内容需",
        "内容需严格",
        "需严格涵盖",
        "如出现",
        "将被视作",
        "将被视为",
    )
    cut_at = min((compact.find(marker) for marker in explanation_markers if marker in compact), default=-1)
    if cut_at > 0:
        compact = compact[:cut_at]
        compact = compact.strip("；;。,.，、：:")
    if category:
        compact = re.sub(r"[（(][^）)]{0,40}[）)]", "", compact)
        compact = re.sub(r"^供应商应提交的", "", compact)
    return compact


def _index_table_columns(
    cells: List[str],
) -> Tuple[int | None, int, int | None, int | None] | None:
    normalized = [_compact_text(cell) for cell in cells]

    def find(headers: set[str]) -> int | None:
        for idx, cell in enumerate(normalized):
            if cell in headers:
                return idx
        return None

    category_col = find(_INDEX_CATEGORY_HEADERS)
    material_col = find(_INDEX_MATERIAL_HEADERS)
    order_col = find(_INDEX_ORDER_HEADERS)
    format_col = find(_INDEX_FORMAT_HEADERS)
    if material_col is None:
        return None
    if category_col is None and order_col is None:
        return None
    return category_col, material_col, order_col, format_col


def _explicit_format_reference(cell: str) -> str:
    compact = re.sub(r"\s+", "", str(cell or ""))
    if not compact or any(marker in compact for marker in ("自拟", "自行编写", "自行编制")):
        return ""
    match = _EXPLICIT_FORMAT_RE.search(compact)
    if not match:
        return ""
    suffix = f"-{match.group(2)}" if match.group(2) else ""
    return f"格式{match.group(1)}{suffix}"


def _index_table_composition_rows(section: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract bid-file rows from authoritative index tables.

    Some tenders provide an index table instead of a "response file shall
    include" paragraph. The table is still a source-backed file composition and
    should not be re-inferred by LLM.
    """
    title = str(section.get("title") or "")
    content = str(section.get("content") or "")
    compact_title = _compact_text(title)
    compact_content = _compact_text(content[:500])
    if not any(
        marker in compact_title or marker in compact_content
        for marker in ("索引目录", "投标文件目录表", "响应文件目录表", "报价文件目录表")
        + ("响应文件内容一览表", "投标文件内容一览表", "内容一览表", "投标文件所需资料")
    ):
        return []

    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    header: List[str] = []
    category_col: int | None = None
    file_name_col: int | None = None
    format_col: int | None = None
    current_category = ""
    table_started = False
    for raw in content.splitlines():
        line = raw.strip()
        if not line or "|" not in line:
            if table_started:
                break
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 3:
            if table_started:
                break
            continue
        compact = re.sub(r"\s+", "", "".join(cells))
        if not compact or set(compact) <= {"-", ":"}:
            continue
        if not table_started:
            columns = _index_table_columns(cells)
            if not columns:
                continue
            category_col, file_name_col, _order_col, format_col = columns
            header = cells
            table_started = True
            continue

        if file_name_col is None or file_name_col >= len(cells):
            break
        normalized_cells = [_compact_text(cell) for cell in cells]
        if any(cell in _INDEX_HEADER_TOKENS for cell in normalized_cells):
            continue
        name = _clean_index_table_cell_subject(cells[file_name_col])
        if not name or name in _INDEX_HEADER_TOKENS or name in {"文件名", "名称"}:
            continue
        if category_col is not None and category_col < len(cells):
            category = _clean_index_table_cell_subject(cells[category_col], category=True)
            if category and category not in _INDEX_HEADER_TOKENS:
                current_category = category
        key = re.sub(r"\s+", "", name)
        if key in seen:
            continue
        seen.add(key)
        row = {
            "name": name,
            "quote": line,
            "header": header,
            "column": file_name_col + 1,
        }
        if format_col is not None and format_col < len(cells):
            template_ref = _explicit_format_reference(cells[format_col])
            if template_ref:
                row["template_ref"] = template_ref
                row["has_template"] = True
        if current_category:
            row.update(
                {
                    "parent_name": current_category,
                    "outline_level": 2,
                }
            )
        rows.append(row)
    return rows


def looks_like_index_table_composition(section: Dict[str, Any]) -> bool:
    """Use the real table parser as the single detector for index-style outlines."""
    return len(_index_table_composition_rows(section)) >= 3
