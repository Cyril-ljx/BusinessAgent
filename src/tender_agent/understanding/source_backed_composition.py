"""Source-backed authoritative file-composition detection."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from .requirements_common import SELF_CHECK_TABLE_HEADER_TOKENS, _compact_text
from .composition_text import (
    _clean_composition_line,
    _is_unselected_submission_option,
    _clean_source_backed_option_name,
    _composition_shape_text,
)
from .index_table_composition import _index_table_composition_rows


def _is_broad_template_section(item: Dict[str, Any]) -> bool:
    title = _compact_text(item.get("title") or "")
    content_len = len(str(item.get("content") or ""))
    if content_len < 2500:
        return False
    return any(
        marker in title
        for marker in (
            "投标文件格式",
            "响应文件格式",
            "报价文件格式",
            "文件格式",
            "格式文件",
            "附件格式",
        )
    )


_FILE_COMPOSITION_ANCHORS = ("投标文件", "响应文件", "报价文件", "报价书")
_FILE_COMPOSITION_TRIGGERS = (
    "组成",
    "构成",
    "应包括",
    "包括但不限于",
    "包括下列",
    "由下述文件构成",
    "由以下文件构成",
    "按下列内容和顺序编写",
    "按下列内容",
    "提交要求",
    "编写要求",
    "下列内容",
)


def _has_file_composition_anchor(text: str) -> bool:
    compact = _compact_text(text)
    return any(anchor in compact for anchor in _FILE_COMPOSITION_ANCHORS)


def _has_file_composition_trigger(text: str) -> bool:
    compact = _compact_text(text)
    return any(trigger in compact for trigger in _FILE_COMPOSITION_TRIGGERS)


def _looks_like_composition_intro(line: str) -> bool:
    return _has_file_composition_anchor(line) and _has_file_composition_trigger(line)




def _looks_like_file_directory_heading(line: str) -> bool:
    compact = _compact_text(line)
    if not compact or len(compact) > 36:
        return False
    if any(term in compact for term in ("评分", "评审", "索引", "页码", "总目录", "目录索引")):
        return False
    return compact in {
        "投标文件目录",
        "响应文件目录",
        "报价文件目录",
        "应答文件目录",
        "投标目录",
        "响应目录",
        "报价目录",
    }


def _directory_item_key(line: str) -> str:
    value = _clean_composition_line(line)
    value = re.sub(r"[（(]\s*(?:必填|选填|可选|必须|非必须)\s*[）)]", "", value)
    value = re.sub(r"\s+", "", value)
    return value.strip("：:；;。,.，、")


def _looks_like_plain_directory_row(line: str) -> bool:
    """Return True for a row inside an explicit file-directory block.

    Once a tender says "投标文件目录"/"响应文件目录", the following short
    rows are already an authoritative directory. Do not require each row to
    contain material nouns such as "函" or "证明"; only reject obvious body text.
    """
    text = str(line or "").strip()
    compact = _compact_text(_composition_shape_text(text))
    if not compact or len(compact) > 110:
        return False
    if _looks_like_file_directory_heading(text):
        return False
    if _looks_like_composition_intro(text) or _looks_like_composition_part_header(text):
        return False
    if _is_source_backed_composition_noise(text):
        return False
    if _looks_like_template_body_boundary(text):
        return False
    if any(term in compact for term in ("应包括但不限于", "包括但不限于", "应包括下列内容", "包括下列内容")):
        return False
    # Form body/instruction sentences should terminate the directory block, not
    # become weak directory items. Keep punctuation-heavy rows only if they are
    # still short names, e.g. "商务、技术（或服务）偏离表".
    if len(compact) > 55 and any(mark in text for mark in ("，", "；", "。", "：")):
        return False
    return True


def _directory_composition_lines_from_anchor(lines: List[str]) -> List[str]:
    """Extract paragraph file-directory rows after a directory heading."""
    best: List[str] = []
    for anchor_idx, line in enumerate(lines):
        if not _looks_like_file_directory_heading(line):
            continue
        candidate: List[str] = []
        seen_keys: set[str] = set()
        skipped = 0
        for row in lines[anchor_idx + 1 :]:
            compact = _compact_text(row)
            if not compact:
                continue
            if candidate and _looks_like_file_directory_heading(row):
                break
            if candidate and _looks_like_template_body_boundary(row):
                break
            if not _looks_like_plain_directory_row(row):
                skipped += 1
                if candidate or skipped > 4 or len(compact) > 60:
                    break
                continue
            key = _directory_item_key(row)
            if candidate and key in seen_keys and not any(mark in compact for mark in ("必填", "选填", "可选")):
                break
            if key in seen_keys:
                continue
            seen_keys.add(key)
            candidate.append(row)
        if _composition_item_threshold_met(candidate) and len(candidate) > len(best):
            best = candidate
    return best

def _looks_like_structural_composition_section(item: Dict[str, Any]) -> bool:
    title = _compact_text(item.get("title") or "")
    if not title:
        return False
    if any(term in title for term in ("格式", "范本", "样例", "参考", "评分", "评审", "采购需求", "服务需求")):
        return False
    exact_titles = {
        "报价文件",
        "投标文件",
        "响应文件",
        "报价书",
        "磋商文件",
        "应提交材料",
        "提交材料",
        "提交清单",
        "材料清单",
        "文件清单",
    }
    if title in exact_titles:
        return True
    return any(
        term in title
        for term in (
            "报价文件提交",
            "报价书提交",
            "投标文件提交",
            "响应文件提交",
            "应提交的材料",
            "应提交文件",
            "须提交材料",
            "提交资料清单",
        )
    )


def _looks_like_unified_composition_section(item: Dict[str, Any]) -> bool:
    title = _compact_text(item.get("title") or "")
    if not title:
        return False
    if _looks_like_structural_composition_section(item):
        return True
    has_composition_title = _has_file_composition_anchor(title) and any(term in title for term in ("组成", "构成"))
    if any(
        term in title
        for term in (
            "初审",
            "符合性",
            "资格性",
            "保证金",
            "投标函",
            "响应函",
            "报价函",
            "格式",
            "范本",
            "模板",
            "封面",
            "目录表",
            "制作",
            "提交",
            "递交",
            "解密",
            "样品",
            "磋商小组",
            "澄清",
            "有效性",
            "无效",
            "否决",
            "评分",
            "评审",
            "前附表",
        )
    ) and not has_composition_title:
        return False
    if not _has_file_composition_anchor(title):
        return False
    if any(term in title for term in ("签署", "密封", "递交", "解密", "撤回", "修改", "评分", "评审")):
        return False
    return _has_file_composition_trigger(title)


def _looks_like_submission_instruction_clause(line: str) -> bool:
    """Reject body instructions that reference submission files but are not file names.

    Source-backed composition sections often list real items first, then continue
    with clauses about signing, negotiation, guarantee handling, or exclusions.
    Those clauses can contain words like "响应文件"/"保证金" and otherwise look
    material-like, so keep this guard focused on long instruction sentences.
    """
    text = str(line or "").strip()
    compact = _compact_text(_composition_shape_text(text))
    if not compact:
        return False
    hard_markers = (
        "响应文件不包括",
        "投标文件不包括",
        "报价文件不包括",
        "应答文件不包括",
        "不包括第",
        "所指的授权委托书",
        "所指的响应保证金",
        "所指的投标保证金",
        "谈判和评审过程中",
        "评审过程中作出的",
        "符合采购文件要求的承诺",
        "符合磋商文件要求的承诺",
        "法定代表人亲自签署响应文件",
        "法定代表人亲自签署投标文件",
        "授权代表签署响应文件",
        "授权代表签署投标文件",
        "可以参加谈判",
        "可以参加磋商",
        "可参加谈判",
        "可参加磋商",
    )
    if any(marker in compact for marker in hard_markers):
        return True
    if any(doc in compact for doc in ("响应文件", "投标文件", "报价文件", "应答文件")) and "不包括" in compact:
        return True
    if any(stage in compact for stage in ("谈判", "磋商", "评审")) and any(term in compact for term in ("承诺", "说明", "补正", "澄清")):
        return True
    if len(compact) <= 34:
        return False
    actors = ("供应商", "投标人", "响应人", "报价人", "谈判供应商", "磋商供应商")
    actions = ("签署", "参加谈判", "参加磋商", "作出", "承诺", "说明", "补正", "不包括", "视为", "不得")
    if any(actor in compact for actor in actors) and any(action in compact for action in actions):
        # Keep genuine material names such as "供应商认为需要提供的其他资料".
        safe_material_phrases = ("认为有必要提供", "需要提供的其他", "应提交", "须提交", "提供下列")
        if not any(phrase in compact for phrase in safe_material_phrases):
            return True
    if re.search(r"\d+(?:\.\d+){1,4}", compact) and any(term in compact for term in ("不包括", "所指", "签署", "参加谈判", "参加磋商")):
        return True
    return False


def _looks_like_structural_composition_item(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return False
    compact = _compact_text(_composition_shape_text(_clean_composition_line(text)))
    if compact in {"投标文件", "响应文件", "报价文件", "报价书", "政府采购投标文件"}:
        return False
    if _looks_like_submission_instruction_clause(text):
        return False
    if compact.startswith("报价书分") and "经济报价书" in compact and "技术报价书" in compact:
        return False
    if any(term in compact for term in ("投标文件格式", "响应文件格式", "报价文件格式", "投标文件的组成", "响应文件的组成")):
        return False
    if any(term in compact for term in ("应包括但不限于以下内容", "包括但不限于以下内容", "应包括以下内容", "包括以下内容", "应包括下列内容", "包括下列内容")):
        return False
    if len(compact) > 90:
        return False
    if _is_dirty_source_backed_line(text) or _is_source_backed_composition_noise(text):
        return False
    non_submit_terms = (
        "工资",
        "补贴",
        "加班费",
        "餐费",
        "社会劳动保险",
        "住房公积金",
        "税费",
        "违约",
        "合同义务",
        "保密",
        "风险全包",
        "用工成本",
        "服务开始前",
        "持续具有",
        "项目服务",
        "服务期间",
        "考核",
        "扣分",
        "扣款",
        "应当对采购文件",
        "构成投标文件的组成部分",
        "不撤销投标文件",
        "签订合同",
        "刑事犯罪行为",
    )
    if any(term in compact for term in non_submit_terms):
        material_contract_terms = ("保密协议", "反商业贿赂协议", "安全生产管理协议", "项目服务方案")
        if not any(term in compact for term in material_contract_terms):
            return False
    material_terms = (
        "表",
        "函",
        "证明书",
        "证明",
        "许可证",
        "营业执照",
        "承诺函",
        "承诺书",
        "声明函",
        "声明书",
        "截图",
        "说明",
        "报告",
        "委托书",
        "授权书",
        "方案",
        "情况介绍",
        "信息",
        "协议",
        "承诺",
        "文件",
        "材料",
        "资料",
        "复印件",
        "证书",
        "凭证",
        "凭据",
        "保证金",
        "报价书",
        "计划",
        "分析",
        "意见",
    )
    if not any(term in compact for term in material_terms):
        return False
    sentence_marks = ("。", "，", "；")
    if len(compact) > 55 and any(mark in text for mark in sentence_marks):
        # Short list rows often end with semicolons; long sentences are usually
        # service/contract clauses, not submission-material names.
        if not any(term in compact for term in ("规定格式见附件", "需提供原件", "加盖公章")):
            return False
    return True


def _looks_like_numbered_file_composition_clause(line: str) -> bool:
    """Accept explicit numbered rows inside an authoritative composition section.

    In these sections long rows are still submission requirements, e.g.
    "6.3.3 需要提供近三年业绩案例...证明文件". The generic prose filter is
    intentionally stricter elsewhere, so keep this scoped to dotted numbering.
    """
    text = str(line or "").strip()
    if not re.match(
        r"^(?:\d+(?:\.\d+){1,4}|[（(]\d{1,3}[）)]|\d{1,3}[、.．)])\s*\S+",
        text,
    ):
        return False
    if _looks_like_submission_instruction_clause(text):
        return False
    cleaned = _clean_composition_line(text)
    compact = _compact_text(_composition_shape_text(cleaned))
    if not compact or len(compact) > 260:
        return False
    if _looks_like_composition_intro(cleaned):
        return False
    if compact.startswith("报价书分") and "经济报价书" in compact and "技术报价书" in compact:
        return False
    if any(term in compact for term in ("应包括但不限于以下内容", "包括但不限于以下内容", "应包括以下内容", "包括以下内容")):
        return False
    if "参见本采购文件提供的格式" in compact or "参考本采购文件提供的格式" in compact:
        return False
    material_terms = (
        "函",
        "委托书",
        "证明",
        "许可证",
        "营业执照",
        "声明",
        "截图",
        "文件",
        "材料",
        "资料",
        "方案",
        "清单",
        "业绩",
        "资质",
        "资格",
        "人员",
        "团队",
        "资源",
        "荣誉",
        "认证",
        "响应",
        "报价",
        "意见",
        "条款",
    )
    return any(term in compact for term in material_terms)


def _has_composition_attachment_marker(line: str) -> bool:
    compact = _compact_text(line)
    return bool(
        re.search(r"附件[一二三四五六七八九十\d]+", compact)
        or "规定格式见附件" in compact
        or "格式见附件" in compact
        or "需提供原件" in compact
    )


def _looks_like_composition_part_header(line: str) -> bool:
    compact = _compact_text(line)
    if not compact or len(compact) > 32:
        return False
    if _looks_like_structural_composition_item(line):
        return False
    return any(
        term in compact
        for term in (
            "价格及商务部分",
            "价格商务部分",
            "商务部分",
            "技术部分",
            "经济部分",
            "经济报价书",
            "技术报价书",
            "初审文件",
            "其他文件",
        )
    )


def _is_explicit_attachment_material_line(line: str) -> bool:
    compact = _compact_text(line)
    if not re.match(r"^附件[一二三四五六七八九十\d]+(?:[-－—]\d+)*", compact):
        return False
    return any(
        term in compact
        for term in (
            "表",
            "函",
            "证明",
            "许可证",
            "营业执照",
            "声明",
            "报告",
            "材料",
            "复印件",
            "协议",
            "方案",
        )
    )


def _is_parenthesized_composition_group(line: str) -> bool:
    compact = _compact_text(re.sub(r"^#{1,6}\s*", "", str(line or "")))
    if not re.match(r"^[（(][一二三四五六七八九十\d]+[）)]", compact):
        return False
    return any(term in compact for term in ("供应商", "投标人", "证明材料", "提供下列材料", "资格条件", "联合体"))


def _composition_outline_level(line: str, current_parent_level: int = 2) -> int:
    compact = _compact_text(line)
    if _looks_like_composition_part_header(line):
        return 1
    if re.match(r"^[一二三四五六七八九十]+[、.．]", compact):
        return 2
    if _is_parenthesized_composition_group(line):
        return max(current_parent_level + 1, 3)
    if re.match(r"^附件[一二三四五六七八九十\d]+[-－—]\d+[-－—]\d+", compact):
        return max(current_parent_level + 1, 4)
    if re.match(r"^附件[一二三四五六七八九十\d]+[-－—]\d+", compact):
        return max(current_parent_level + 1, 3)
    if compact.startswith("附件"):
        return max(current_parent_level + 1, 3)
    return current_parent_level


def _composition_outline_level_from_raw(raw: str, line: str, current_parent_level: int = 2) -> int:
    raw_text = str(raw or "").strip()
    compact_raw = _compact_text(raw_text)
    compact = _compact_text(line)
    if _looks_like_composition_part_header(line):
        return 1
    if compact_raw.startswith("###"):
        return max(current_parent_level + 1, 3)
    if compact_raw.startswith("##"):
        if re.match(r"^##\s*附件[一二三四五六七八九十\d]+[-－—]\d+[-－—]\d+", raw_text):
            return max(current_parent_level + 1, 4)
        if re.match(r"^##\s*附件", raw_text):
            return max(current_parent_level + 1, 3)
        return 2
    if re.match(r"^[一二三四五六七八九十]+[、.．]", compact_raw):
        return 2
    if _is_parenthesized_composition_group(raw) or _is_parenthesized_composition_group(line):
        return 3
    if compact.startswith("附件"):
        return _composition_outline_level(line, current_parent_level)
    return max(current_parent_level + 1, 2)


def _part_header_name(line: str) -> str:
    value = _clean_composition_line(line)
    value = re.sub(r"^第[一二三四五六七八九十\d]+部分", "", value).strip()
    value = value.strip("()（） 　")
    return value or _clean_composition_line(line)


def _looks_like_body_composition_row(line: str) -> bool:
    if _looks_like_structural_composition_item(line):
        return True
    if _is_parenthesized_composition_group(line):
        return True
    if _is_explicit_attachment_material_line(line):
        return True
    return False


def _part_section_composition_rows(section: Dict[str, Any]) -> List[Dict[str, Any]]:
    title = _clean_composition_line(str(section.get("title") or ""))
    if not _looks_like_composition_part_header(title):
        return []

    rows: List[Dict[str, Any]] = [
        {
            "name": _part_header_name(title),
            "quote": title,
            "outline_level": 1,
            "outline_group": True,
        }
    ]
    current_parent_level = 1
    for raw in str(section.get("content") or "").splitlines():
        line = _clean_composition_line(raw)
        if not line:
            continue
        compact = _compact_text(line)
        if _looks_like_heading_composition_wrapper(line) and len(rows) > 1:
            break
        if _looks_like_composition_part_header(line):
            rows.append(
                {
                    "name": _part_header_name(line),
                    "quote": line,
                    "outline_level": 1,
                    "outline_group": True,
                }
            )
            current_parent_level = 1
            continue
        if _is_source_backed_composition_noise(line) and not _is_explicit_attachment_material_line(line):
            continue
        if not _looks_like_body_composition_row(line):
            if len(rows) > 1 and len(compact) > 80:
                break
            continue
        level = _composition_outline_level_from_raw(raw, line, current_parent_level)
        is_group = _is_parenthesized_composition_group(raw) or _is_parenthesized_composition_group(line)
        rows.append(
            {
                "name": line,
                "quote": line,
                "outline_level": level,
                "outline_group": is_group,
            }
        )
        if level <= 2 or is_group:
            current_parent_level = level

    material_count = sum(1 for row in rows if not row.get("outline_group"))
    if material_count < 3:
        return []
    return rows


def _composition_item_threshold_met(lines: List[str]) -> bool:
    if len(lines) >= 5:
        return True
    return len(lines) >= 3 and any(_has_composition_attachment_marker(line) for line in lines)


def _lookahead_has_composition_item(lines: List[str], start: int, window: int = 4) -> bool:
    for ahead in lines[start : start + window]:
        if _looks_like_structural_composition_item(ahead):
            return True
        if _looks_like_composition_part_header(ahead) or _looks_like_composition_intro(ahead):
            continue
        if len(_compact_text(ahead)) > 80:
            return False
    return False


def _composition_anchor_indices(item: Dict[str, Any], lines: List[str]) -> List[int]:
    indices: List[int] = []
    if _looks_like_unified_composition_section(item):
        indices.append(0)
    for idx, line in enumerate(lines):
        compact = _compact_text(line)
        if not _has_file_composition_anchor(compact):
            continue
        if any(term in compact for term in ("签署", "密封", "递交", "解密", "撤回", "修改")) and not _has_file_composition_trigger(compact):
            continue
        if _has_file_composition_trigger(compact):
            indices.append(idx)
    return sorted(set(indices))



def _composition_intro_parent_name(line: str) -> str:
    text = _clean_composition_line(str(line or "").strip())
    text = re.sub(r"^\d+(?:\.\d+){1,4}\s*", "", text).strip()
    text = re.sub(
        r"(?:应包括但不限于以下内容|包括但不限于以下内容|应包括以下内容|包括以下内容|应包括下列内容|包括下列内容)[:：。；;]*$",
        "",
        text,
    ).strip()
    return text.strip(" ：:，,。；;、")


def _append_nested_composition_child_rows(
    base_rows: List[Any],
    all_lines: List[str],
) -> List[Any]:
    """Attach numbered child rows after a listed parent says it includes subitems."""
    if not base_rows or not all_lines:
        return base_rows

    parent_by_key: Dict[str, str] = {}
    for row in base_rows:
        if isinstance(row, dict):
            name = str(row.get("name") or row.get("quote") or "").strip()
        else:
            name = _source_backed_composition_name(str(row or ""))
        if name:
            parent_by_key[_compact_text(name)] = name

    additions_by_parent: Dict[str, List[Dict[str, Any]]] = {}
    for idx, line in enumerate(all_lines):
        compact = _compact_text(line)
        if not any(term in compact for term in ("应包括但不限于以下内容", "包括但不限于以下内容", "应包括以下内容", "包括以下内容", "应包括下列内容", "包括下列内容")):
            continue
        parent_name = _composition_intro_parent_name(line)
        parent_key = _compact_text(parent_name)
        matched_parent = parent_by_key.get(parent_key)
        if not matched_parent:
            for key, value in parent_by_key.items():
                if parent_key and (parent_key in key or key in parent_key):
                    matched_parent = value
                    break
        if not matched_parent:
            continue

        number_match = re.match(r"^(\d+(?:\.\d+){1,3})\s*", str(line or "").strip())
        prefix = number_match.group(1) if number_match else ""
        children: List[Dict[str, Any]] = []
        for child_idx, child_line in enumerate(all_lines[idx + 1 :], start=idx + 1):
            child_text = str(child_line or "").strip()
            if not child_text:
                continue
            child_number = re.match(r"^(\d+(?:\.\d+){1,4})\s*", child_text)
            if prefix and child_number and not child_number.group(1).startswith(prefix + "."):
                break
            if prefix and not child_number:
                if children:
                    break
                continue
            structural_child = bool(
                prefix
                and child_number
                and child_number.group(1).startswith(prefix + ".")
                and child_number.group(1).count(".") == prefix.count(".") + 1
            )
            if not structural_child and not _looks_like_numbered_file_composition_clause(child_text):
                if children and _lookahead_has_composition_item(all_lines, child_idx + 1):
                    continue
                if children:
                    break
                continue
            children.append(
                {
                    "name": _source_backed_composition_name(child_text),
                    "quote": child_text,
                    "outline_level": 2,
                    "parent_name": matched_parent,
                }
            )
        if children:
            additions_by_parent.setdefault(_compact_text(matched_parent), []).extend(children)

    if not additions_by_parent:
        return base_rows

    result: List[Any] = []
    inserted_keys: set[str] = set()
    for row in base_rows:
        result.append(row)
        row_name = str(row.get("name") or row.get("quote") or "").strip() if isinstance(row, dict) else _source_backed_composition_name(str(row or ""))
        row_key = _compact_text(row_name)
        for child in additions_by_parent.get(row_key, []):
            child_key = f"{row_key}|{_compact_text(str(child.get('name') or ''))}"
            if child_key in inserted_keys:
                continue
            inserted_keys.add(child_key)
            result.append(child)
    return result


def _unified_composition_lines_from_anchor(item: Dict[str, Any], lines: List[str]) -> List[str]:
    lines = _scope_composition_lines_at_stop_headings(lines)
    best: List[str] = []
    stop_markers = (
        "投标文件的签署",
        "响应文件的签署",
        "报价文件的签署",
        "报价书的签署",
        "投标文件的密封",
        "响应文件的密封",
        "报价文件的密封",
        "投标有效期",
        "投标报价",
        "投标保证金",
    )
    for anchor_idx in _composition_anchor_indices(item, lines):
        candidate: List[str] = []
        skipped_after_anchor = 0
        for idx in range(anchor_idx, len(lines)):
            line = lines[idx]
            compact = _compact_text(line)
            if candidate and _is_composition_stop_line(line, stop_markers):
                break
            if idx == anchor_idx and _has_file_composition_anchor(line):
                continue
            if _looks_like_composition_intro(line) or _looks_like_composition_part_header(line):
                continue
            if _looks_like_numbered_file_composition_clause(line):
                candidate.append(line)
                skipped_after_anchor = 0
                continue
            if _is_source_backed_composition_noise(line):
                if candidate:
                    if not _lookahead_has_composition_item(lines, idx + 1):
                        break
                continue
            if candidate and _looks_like_template_body_boundary(line):
                break
            if _looks_like_structural_composition_item(line):
                candidate.append(line)
                skipped_after_anchor = 0
                continue
            if candidate and candidate[-1].rstrip().endswith(("，", "、", ",")) and len(compact) <= 80:
                candidate[-1] = candidate[-1].rstrip() + line
                skipped_after_anchor = 0
                continue
            if not candidate:
                skipped_after_anchor += 1
                if skipped_after_anchor <= 8 and len(compact) <= 90:
                    continue
                if _looks_like_template_body_boundary(line):
                    break
                continue
            if _lookahead_has_composition_item(lines, idx + 1):
                continue
            break
        if len(candidate) > len(best):
            best = candidate
    if not _composition_item_threshold_met(best):
        return []
    candidate_count = sum(
        1
        for line in best
        if _looks_like_structural_composition_item(line)
        or _looks_like_numbered_file_composition_clause(line)
    )
    if candidate_count / max(len(best), 1) < 0.7:
        return []
    return best


def _heading_composition_lines_from_sections(sections_payload: List[Dict[str, Any]], start_index: int) -> List[str]:
    anchor_section = sections_payload[start_index]
    if not _looks_like_unified_composition_section(anchor_section):
        if _looks_like_template_form_section(anchor_section):
            return []
        if not _can_cross_section_collect_heading_items(anchor_section):
            return []
        anchor_lines = [str(anchor_section.get("title") or "")]
        anchor_lines.extend(str(anchor_section.get("content") or "").splitlines())
        if not any(_looks_like_composition_intro(line) for line in anchor_lines):
            return []
    lines: List[str] = []
    started = False
    for section in sections_payload[start_index + 1 :]:
        title = _clean_composition_line(str(section.get("title") or ""))
        compact = _compact_text(title)
        if not title:
            continue
        if _looks_like_unified_composition_section(section) and started:
            break
        if started and _is_heading_composition_stop_title(title):
            break
        if started and _looks_like_heading_attachment_detail(title):
            continue
        if _looks_like_composition_part_header(title):
            continue
        if _looks_like_heading_composition_wrapper(title):
            if started and "政府采购投标文件" in compact and len(lines) >= 10:
                break
            if started:
                continue
            if len(compact) <= 32:
                continue
            break
        if started and "联合体协议" in compact:
            continue
        if _looks_like_structural_composition_item(title):
            lines.append(title)
            started = True
            continue
        if not started:
            if len(compact) <= 28:
                continue
            break
        break
    if not _composition_item_threshold_met(lines):
        return []
    return lines


def _can_cross_section_collect_heading_items(item: Dict[str, Any]) -> bool:
    """Allow cross-section checklist recovery only from explicit composition anchors.

    This prevents broad announcement/instruction chapters that mention
    "投标文件应包括…" once from sweeping in unrelated following headings and
    turning them into a fake submission checklist.
    """
    title = _compact_text(item.get("title") or "")
    content = _compact_text(item.get("content") or "")
    relevance = _compact_text(item.get("relevance") or "")
    if not title and not content:
        return False
    if any(
        term in title
        for term in (
            "公告",
            "邀请",
            "须知前附表",
            "前附表",
            "评标",
            "评审",
            "评分",
            "合同",
            "否决",
            "废标",
            "保证金",
            "开标",
        )
    ):
        return False
    if any(term in relevance for term in ("权威提交清单章节", "正文投标文件组成分部")):
        return True
    if any(term in title for term in ("组成", "构成", "编写要求")):
        return True
    intro_window = content[:800]
    if len(content) <= 1800 and any(
        marker in intro_window
        for marker in (
            "应由下述文件构成",
            "应由下列文件构成",
            "包括下列文件",
            "包括以下文件",
            "应包括下列内容",
            "应包括以下内容",
            "按下列内容和顺序编写",
            "报价书的编写要求",
        )
    ):
        return True
    return False


def _looks_like_template_form_section(item: Dict[str, Any]) -> bool:
    title = _compact_text(item.get("title") or "")
    if not title:
        return False
    if _has_file_composition_anchor(title) and any(term in title for term in ("组成", "构成")):
        return False
    return any(
        term in title
        for term in (
            "投标函",
            "响应函",
            "报价函",
            "承诺函",
            "声明函",
            "证明书",
            "授权委托书",
            "投标报价表",
            "报价表",
            "封面",
            "目录",
            "附录",
        )
    )


def _looks_like_heading_attachment_detail(title: str) -> bool:
    compact = _compact_text(title)
    if not compact:
        return False
    return bool(re.match(r"^附件\d+[-－—]\d+", compact))


def _looks_like_heading_composition_wrapper(title: str) -> bool:
    compact = _compact_text(title)
    if not compact or len(compact) > 36:
        return False
    return any(
        term in compact
        for term in (
            "政府采购投标文件",
            "投标文件",
            "响应文件",
            "报价文件",
            "商务部分",
            "技术部分",
            "价格部分",
            "经济部分",
        )
    ) and not _looks_like_structural_composition_item(title)


def _is_heading_composition_stop_title(title: str) -> bool:
    compact = _compact_text(title)
    if not compact:
        return False
    if any(
        term in compact
        for term in (
            "投标文件格式",
            "响应文件格式",
            "报价文件格式",
            "文件格式",
            "格式文件",
            "评标",
            "评审",
            "评分",
            "澄清",
            "有效性",
            "无效",
            "否决",
            "采购需求",
            "用户需求",
            "合同",
        )
    ):
        return True
    return bool(re.match(r"^第[一二三四五六七八九十]+章", compact)) and not any(
        term in compact for term in ("投标文件组成", "响应文件组成", "报价文件组成")
    )


def _structural_composition_lines_from_section(item: Dict[str, Any], lines: List[str]) -> List[str]:
    return _unified_composition_lines_from_anchor(item, lines)


def _looks_like_guarantee_material_text(text: str) -> bool:
    compact = _compact_text(text)
    if "保证金" not in compact:
        return False
    return any(
        marker in compact
        for marker in (
            "保证金登记表",
            "保证金进账凭证",
            "保证金缴纳凭证",
            "保证金凭证",
            "保证金证明",
            "保证金保函",
            "银行保函",
            "汇款凭证",
            "转账凭证",
            "银行回单",
            "收据",
        )
    )


def _is_source_backed_risk_clause_section(item: Dict[str, Any]) -> bool:
    """Reject risk/invalidity clauses as authoritative submission checklists.

    Guarantee proof rows such as "投标保证金进账凭证" are valid materials and
    remain eligible; this only rejects clause contexts like forfeiture/refusal.
    """
    title = _compact_text(item.get("title") or "")
    relevance = _compact_text(item.get("relevance") or "")
    content = _compact_text(str(item.get("content") or "")[:1800])
    text = title + relevance + content

    if _looks_like_guarantee_material_text(title):
        return False

    if any(term in title or term in relevance for term in ("无效报价", "无效响应", "否决", "废标", "有效性认定", "资格的取消")):
        return True

    title_relevance = title + relevance
    if "保证金" in title_relevance:
        if _looks_like_guarantee_material_text(text) and not any(
            risk in text for risk in ("不予退还", "没收", "否决其投标", "撤销投标文件", "视为放弃")
        ):
            return False
        return any(
            risk in text
            for risk in (
                "不予退还",
                "没收",
                "否决其投标",
                "撤销投标文件",
                "视为放弃",
                "放弃中标",
                "退还保证金",
                "转为合同履约保证金",
                "保证金将",
            )
        )

    return False


def _self_check_table_header_hits(text: str) -> int:
    compact = _compact_text(text)
    return sum(1 for token in SELF_CHECK_TABLE_HEADER_TOKENS if token in compact)


def _is_self_check_or_review_table_section(section: Dict[str, Any]) -> bool:
    content = str(section.get("content") or "")
    title = str(section.get("title") or "")
    lines = content.splitlines()[:80]
    sample = "\n".join(lines)
    if _self_check_table_header_hits(sample) < 2:
        return False
    first_header_idx = next(
        (idx for idx, line in enumerate(lines) if _self_check_table_header_hits(line) >= 2),
        None,
    )
    first_intro_idx = next(
        (idx for idx, line in enumerate(lines) if _looks_like_composition_intro(line)),
        None,
    )
    if first_intro_idx is not None and first_header_idx is not None and first_intro_idx < first_header_idx:
        return False
    return "|" in sample or "表" in title or "表" in sample[:300]


def _looks_like_file_format_stop_heading(line: str) -> bool:
    text = str(line or "").strip()
    compact = _compact_text(text)
    if not compact or len(compact) > 42:
        return False
    if "合同书格式范本" in compact or "合同格式范本" in compact:
        return False
    stop_markers = (
        "初步评审",
        "详细评审",
        "资格评审",
        "评分办法",
        "评标办法",
        "综合评分",
        "评审标准",
        "合同条款",
        "合同主要条款",
        "合同书格式",
        "否决投标条款",
        "废标条款",
    )
    if not any(marker in compact for marker in stop_markers):
        return False
    heading_prefix = bool(
        re.match(
            r"^(?:第[一二三四五六七八九十\d]+[章节部分]|[一二三四五六七八九十\d]+[、.．)]|[（(][一二三四五六七八九十\d]+[）)])",
            compact,
        )
    )
    heading_suffix = compact.endswith(("表", "办法", "标准", "条款", "格式"))
    exact_heading = any(compact == marker for marker in stop_markers)
    return heading_prefix or heading_suffix or exact_heading


def _scope_composition_lines_at_stop_headings(lines: List[str]) -> List[str]:
    scoped: List[str] = []
    for line in lines:
        if scoped and _looks_like_file_format_stop_heading(line) and not _looks_like_numbered_file_composition_clause(line):
            break
        scoped.append(line)
    return scoped


def _is_dirty_source_backed_line(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return True
    compact = _compact_text(text)
    strong_material_terms = (
        "企业信用报告",
        "信用中国",
        "中国政府采购网",
        "政府采购网查询截图",
        "股权穿透图",
        "查询截图",
        "失信被执行人",
        "重大税收违法",
        "政府采购严重违法",
        "审计报告",
        "财务报表",
        "安全生产管理协议",
        "反商业贿赂协议",
        "保密协议",
        "中标承诺书",
        "偏离表",
        "银行账户信息",
        "资格申明函",
        "资格声明函",
        "项目实施方案",
        "详细的项目实施方案",
    )
    if len(compact) <= 90 and any(term in compact for term in strong_material_terms):
        return False
    if _is_explicit_attachment_material_line(text):
        return False
    dirty_terms = (
        "签字",
        "签章",
        "年月日",
        "年月",
        "粘贴处",
        "特此声明",
        "特此证明",
        "本表",
        "此表",
        "投标文件其他部分",
        "与招标文件要求不一致",
        "正偏离",
        "负偏离",
        "如无差异",
        "为响应你方",
        "我方声明",
        "我方保证",
        "本公司违反",
        "被授权委托人无转委托权",
        "法定代表人姓名",
        "投标人名称",
        "招标编号",
        "甲方工作人员",
        "保密信息",
        "本协议",
        "本协议书",
        "不得以任何理由",
        "应当对采购文件",
        "构成投标文件的组成部分",
        "不撤销投标文件",
        "收到中标通知书后",
        "如我方中标",
        "一旦我方中标",
        "如果我方中标",
        "我方承诺",
        "近三年内无刑事犯罪",
        "参见本采购文件提供的格式",
        "应包括但不限于以下内容",
    )
    if any(term in compact for term in dirty_terms):
        return True
    if _looks_like_submission_instruction_clause(text):
        return True
    if re.match(r"^[（(]?\d+[）)]", text) and len(compact) > 28:
        return True
    sentence_marks = ("，", "。", "；", "：", "如果", "则", "应当", "不得", "保证", "确认后")
    if len(compact) > 55 and any(mark in text for mark in sentence_marks):
        return True
    return False


def _is_authoritative_source_backed_rows(items: List[Dict[str, Any]]) -> bool:
    if not items:
        return False
    if not all(item.get("source_backed_authoritative") for item in items):
        return False
    source_kinds = {str(item.get("source_kind") or "") for item in items}
    if "index_table" in source_kinds:
        return len(items) >= 5
    if any(
        _is_dirty_source_backed_line(str(item.get("quote") or item.get("name") or ""))
        and not _looks_like_numbered_file_composition_clause(str(item.get("quote") or ""))
        and not (
            str(item.get("source_kind") or "") == "composition_list"
            and re.match(r"^\d+(?:\.\d+){1,4}\s*\S+", str(item.get("quote") or ""))
        )
        for item in items
    ):
        return False
    if len(items) >= 5:
        return len(items) <= 60
    return len(items) >= 3 and any(
        _has_composition_attachment_marker(str(item.get("quote") or item.get("name") or ""))
        for item in items
    )


def _numbered_composition_lines_from_intro(lines: List[str]) -> List[str]:
    """Keep direct dotted children under an explicit file-composition intro."""
    for index, line in enumerate(lines or []):
        if not _looks_like_composition_intro(line):
            continue
        parent_match = re.match(r"^(\d+(?:\.\d+){1,3})\s*", str(line or "").strip())
        if not parent_match:
            continue
        parent_number = parent_match.group(1)
        children: List[str] = []
        for candidate in lines[index + 1 :]:
            child_match = re.match(r"^(\d+(?:\.\d+){1,4})\s*", str(candidate or "").strip())
            if not child_match:
                if children:
                    break
                continue
            child_number = child_match.group(1)
            if not child_number.startswith(parent_number + "."):
                if children:
                    break
                continue
            if child_number.count(".") != parent_number.count(".") + 1:
                continue
            children.append(str(candidate or "").strip())
        if len(children) >= 3:
            return [str(line or "").strip(), *children]
    return []


def _extract_file_composition_list_item(item: Dict[str, Any]) -> Dict[str, Any] | None:
    """Protect continuous response-file composition lists from generic chunking.

    These lists are source-backed structures, not inferred rules. They are
    often the only place where required certificates/materials are enumerated,
    so splitting them across batches can make the LLM miss fatal materials.
    """
    if _is_source_backed_risk_clause_section(item):
        return None
    if _is_self_check_or_review_table_section(item):
        return None
    if _is_broad_template_section(item):
        return None

    content = str(item.get("content") or "")
    lines = [str(line or "").strip() for line in content.splitlines()]
    lines = [line for line in lines if line]
    lines = _scope_composition_lines_at_stop_headings(lines)
    if not lines:
        return None

    numbered_lines = _numbered_composition_lines_from_intro(lines)
    if numbered_lines:
        protected_item = dict(item)
        protected_item["content"] = "\n".join(numbered_lines)
        protected_item["chunk_id"] = f"{item.get('section_id')}#numbered_file_composition_list"
        protected_item["title"] = f"{item.get('title') or ''}（点分编号提交清单）"
        protected_item["relevance"] = f"{item.get('relevance') or ''}; source-backed numbered file composition"
        protected_item["requirement_tags"] = list(
            dict.fromkeys(list(item.get("requirement_tags") or []) + ["file_composition", "submission_checklist"])
        )
        protected_item["protected_list"] = "file_composition"
        return protected_item

    directory_lines = _directory_composition_lines_from_anchor(lines)
    if directory_lines:
        protected_item = dict(item)
        protected_item["content"] = "\n".join(directory_lines)
        protected_item["chunk_id"] = f"{item.get('section_id')}#directory_file_composition_list"
        protected_item["title"] = f"{item.get('title') or ''}（文件目录清单）"
        protected_item["relevance"] = f"{item.get('relevance') or ''}; source-backed file directory composition"
        protected_item["requirement_tags"] = list(
            dict.fromkeys(list(item.get("requirement_tags") or []) + ["file_composition", "submission_checklist"])
        )
        protected_item["protected_list"] = "file_composition"
        return protected_item

    unified_lines = _unified_composition_lines_from_anchor(item, lines)
    if unified_lines:
        protected_item = dict(item)
        protected_item["content"] = "\n".join(unified_lines)
        protected_item["chunk_id"] = f"{item.get('section_id')}#unified_file_composition_list"
        protected_item["title"] = f"{item.get('title') or ''}（权威提交清单）"
        protected_item["relevance"] = f"{item.get('relevance') or ''}; source-backed unified file composition"
        protected_item["requirement_tags"] = list(
            dict.fromkeys(list(item.get("requirement_tags") or []) + ["file_composition", "submission_checklist"])
        )
        protected_item["protected_list"] = "file_composition"
        return protected_item

    start_idx: int | None = None
    for idx, line in enumerate(lines):
        if _looks_like_composition_intro(line):
            start_idx = idx
            break
    if start_idx is None:
        for idx, line in enumerate(lines):
            if "应包括但不限于下列内容" in line or "包括但不限于下列内容" in line:
                start_idx = idx
                break
    if start_idx is None:
        structural_lines = _structural_composition_lines_from_section(item, lines)
        if not structural_lines:
            return None
        protected_item = dict(item)
        protected_item["content"] = "\n".join(structural_lines)
        protected_item["chunk_id"] = f"{item.get('section_id')}#structural_file_composition_list"
        protected_item["title"] = f"{item.get('title') or ''}（结构化提交清单）"
        protected_item["relevance"] = f"{item.get('relevance') or ''}; source-backed structural file composition"
        protected_item["requirement_tags"] = list(
            dict.fromkeys(list(item.get("requirement_tags") or []) + ["file_composition", "submission_checklist"])
        )
        protected_item["protected_list"] = "file_composition"
        return protected_item

    protected: List[str] = []
    numbered_items: List[str] = []
    stop_markers = (
        "投标文件的签署",
        "响应文件的签署",
        "报价文件的签署",
        "投标文件的密封",
        "响应文件的密封",
        "投标有效期",
        "投标报价",
        "投标保证金",
    )
    for line in lines[start_idx:]:
        if protected and _is_composition_stop_line(line, stop_markers):
            break
        compact = _compact_text(line)
        if "组成" in compact or "包括" in compact or "下列内容" in compact:
            if not protected:
                protected.append(line)
            continue
        if _is_source_backed_composition_noise(line):
            continue
        if protected and _looks_like_template_body_boundary(line):
            break
        if not _looks_like_numbered_composition_item(line):
            if protected and _looks_like_template_body_boundary(line):
                break
            continue
        numbered_items.append(line)

    # Source-backed extraction is only safe for explicit, continuous numbered
    # file-composition lists. Otherwise large "supplier instruction" sections
    # can be mistaken for material rows and pollute both file_composition and
    # material_checklist.
    if len(numbered_items) < 5:
        return None
    protected.extend(numbered_items)

    protected_item = dict(item)
    protected_item["content"] = "\n".join(protected)
    protected_item["chunk_id"] = f"{item.get('section_id')}#file_composition_list"
    protected_item["title"] = f"{item.get('title') or ''}（投标文件组成清单）"
    protected_item["relevance"] = f"{item.get('relevance') or ''}; source-backed file composition list"
    protected_item["protected_list"] = "file_composition"
    return protected_item


def _is_composition_stop_line(line: str, stop_markers: Tuple[str, ...]) -> bool:
    text = str(line or "").strip()
    if not text:
        return False
    for marker in stop_markers:
        if text == marker:
            return True
        if text.startswith(marker) and len(text) <= len(marker) + 6:
            # Avoid stopping on list items such as "投标报价表" or "投标保证金登记表".
            if any(word in text for word in ("表", "函", "证明", "登记", "复印件")):
                return False
            return True
    return False


def _looks_like_template_body_boundary(line: str) -> bool:
    compact = _compact_text(line)
    if not compact:
        return False
    if any(marker in compact for marker in ("第五部分投标文件格式", "附件格式", "格式文件")):
        return True
    if any(
        marker in compact
        for marker in (
            "如我方中标",
            "一旦我方中标",
            "如果我方中标",
            "我方承诺",
            "我方声明",
            "我方保证",
            "特此声明",
            "特此证明",
            "投标人名称",
            "法定代表人或其委托代理人",
        )
    ):
        return True
    if "格式" in compact and len(compact) <= 20 and not _looks_like_numbered_composition_item(line):
        return True
    return False


def _composition_lines_from_protected_item(item: Dict[str, Any]) -> List[str]:
    lines = [str(line or "").strip() for line in str(item.get("content") or "").splitlines()]
    lines = _scope_composition_lines_at_stop_headings(lines)
    result: List[str] = []
    explicit_numbered_list = "#numbered_file_composition_list" in str(item.get("chunk_id") or "")
    for line in lines:
        if not line:
            continue
        if explicit_numbered_list and re.match(r"^\d+(?:\.\d+){1,4}\s*\S+", line):
            if not _looks_like_composition_intro(line):
                result.append(line)
            continue
        numbered_clause = _looks_like_numbered_file_composition_clause(line)
        if _is_dirty_source_backed_line(line) and not numbered_clause:
            continue
        if _is_source_backed_composition_noise(line) and not numbered_clause:
            continue
        if _looks_like_structural_composition_item(line):
            result.append(line)
            continue
        if not _looks_like_numbered_composition_item(line):
            if numbered_clause:
                result.append(line)
                continue
            compact_for_header = re.sub(r"\s+", "", line)
            if not (
                ("投标文件" in compact_for_header or "响应文件" in compact_for_header or "报价文件" in compact_for_header)
                and ("组成" in compact_for_header or "包括" in compact_for_header)
            ):
                continue
        compact = re.sub(r"\s+", "", line)
        if (
            ("投标文件" in compact or "响应文件" in compact or "报价文件" in compact)
            and ("组成" in compact or "包括" in compact)
        ):
            continue
        if "包括但不限于下列内容" in compact or "应包括但不限于" in compact:
            continue
        result.append(line)
    return result


def _looks_like_numbered_composition_item(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return False
    if _is_dirty_source_backed_line(text):
        return _looks_like_numbered_file_composition_clause(text)
    compact = _compact_text(text)
    if len(compact) > 80 and not _looks_like_numbered_file_composition_clause(text):
        return False
    if _looks_like_numbered_file_composition_clause(text):
        return True
    if re.match(r"^(?:\d{1,3}[、.．)]|[（(]\d{1,3}[）)]|[一二三四五六七八九十]{1,3}[、.．])\s*\S+", text):
        return len(compact) <= 80
    # Lines are cleaned before source-backed parsing, so the numeric prefix may
    # already be stripped. Accept only material/form-like nouns after cleaning;
    # process instructions and table rows are filtered separately.
    material_terms = (
        "文件",
        "封面",
        "目录",
        "表",
        "书",
        "证明",
        "承诺",
        "声明",
        "授权",
        "证书",
        "复印件",
        "许可证",
        "报告",
        "说明",
        "截图",
        "清单",
        "执照",
        "方案",
        "投标函",
        "报价函",
        "承诺函",
        "声明函",
        "申明函",
        "情况介绍",
        "银行账户信息",
        "协议",
        "计划",
    )
    if "函件" in text:
        return False
    return any(term in compact for term in material_terms)


def _is_source_backed_composition_noise(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return True
    compact = re.sub(r"\s+", "", text)
    if "有限公司" in compact and compact.endswith(("报价指引文件", "招标文件", "采购文件", "磋商文件")):
        return True
    if text.startswith("##"):
        heading = re.sub(r"^\s*#{1,6}\s*", "", text)
        # A format chapter often stores its authoritative checklist as heading
        # rows. Keep numbered material headings while still rejecting ordinary
        # template/body headings from source-backed composition candidates.
        if not re.match(
            r"^(?:[（(]?\d{1,3}[）)、.．]|[一二三四五六七八九十]{1,3}[、.．])\s*\S+",
            re.sub(r"^\s*[★☆*□☑√✓]+\s*", "", heading),
        ):
            return True
    if text.startswith("|") or "|---" in compact or "---|" in compact:
        return True
    if re.fullmatch(r"\[.*?(章节末尾|section end|end).*?\]", text, flags=re.IGNORECASE):
        return True
    if compact in {"[章节末尾]", "章节末尾"}:
        return True
    if _is_dirty_source_backed_line(text):
        return True
    process_terms = (
        "编制",
        "编写",
        "修改",
        "撤回",
        "装订",
        "密封",
        "递交",
        "送达",
        "截止",
        "澄清",
        "补充",
        "签署",
        "打印",
        "盖写",
    )
    if (
        "响应文件" in compact
        or "投标文件" in compact
        or "报价文件" in compact
        or "磋商文件" in compact
    ) and any(
        term in compact for term in process_terms
    ):
        material_terms = (
            "投标函",
            "报价函",
            "承诺函",
            "声明函",
            "授权书",
            "证明书",
            "证书",
            "许可证",
            "营业执照",
            "复印件",
            "清单",
            "保证金",
        )
        if not any(term in compact for term in material_terms):
            return True
    return False


def _source_backed_composition_name(line: str) -> str:
    text = _clean_composition_line(str(line or "").strip())
    compact = _compact_text(text)
    if "及其他必要文件" in compact:
        return text
    if compact.startswith("承诺函"):
        return "承诺函"
    if re.match(r"^报价函[，,:：]", text):
        return "报价函"
    if any(term in compact for term in ("资格证明文件", "经营资格证明文件", "经营资格证明材料")):
        return "资格证明文件"
    if "无重大违法记录" in compact and "信用记录" in compact:
        return "报价人无重大违法记录声明及信用记录"
    if "专业资质" in compact and any(term in compact for term in ("必须具备", "需具备", "应具备", "具备")):
        return "专业资质证明"
    if "实质性内容" in compact and "完全响应" in compact:
        return "实质性内容响应"
    if "理解" in compact and "内容清单" in compact:
        return "项目理解及服务/货物清单"
    if "近三年" in compact and "业绩" in compact and "人员资质" in compact:
        return "业绩证明及人员资质证明材料"
    if "服务" in compact and "团队" in compact and any(term in compact for term in ("模式", "进度", "介绍")):
        return "服务模式及团队介绍"
    if any(term in compact for term in ("资质", "认证", "荣誉证书")) and "获得" in compact:
        return "资质认证或荣誉证书"
    if "、" in text and len(compact) <= 90:
        return text
    aliases = [
        ("法定代表人身份证明", ("法定代表人身份证明",)),
        ("法定代表人授权书", ("法定代表人授权书",)),
        ("企业法人营业执照", ("企业法人营业执照",)),
        ("营业执照", ("营业执照", "三证合一")),
        ("劳务派遣经营许可证", ("劳务派遣经营许可证",)),
        ("人力资源服务许可证", ("人力资源服务许可证",)),
        ("开户许可证", ("开户许可证", "银行开户许可证")),
        ("企业信用报告", ("企业信用报告", "国家企业信用信息公示")),
        ("失信被执行人截图", ("失信被执行人",)),
        ("重大税收违法失信主体截图", ("重大税收违法",)),
        ("政府采购严重违法失信记录截图", ("政府采购严重违法",)),
        ("团队社保证明或劳务合同证明", ("社保证明", "劳务合同证明")),
        ("天眼查股权穿透图截图", ("天眼查", "股权穿透图")),
        ("信用中国及中国政府采购网查询截图", ("信用中国", "中国政府采购网")),
        ("信用中国及中国政府采购网查询截图", ("信用中国", "政府采购网")),
    ]
    for name, keys in aliases:
        if any(key in compact for key in keys):
            return name
    return re.sub(r"[；。]$", "", text)[:80]


def _is_source_backed_qualification_parent(name: str, quote: str) -> bool:
    compact = _compact_text(f"{name}{quote}")
    if not any(term in compact for term in ("投标人资质证明文件", "企业资质证明文件", "资格证明文件", "资质证明材料", "资格证明材料")):
        return False
    return any(term in compact for term in ("以下", "下列", "复印件需", "须提供", "需提供", "包括"))


def _is_source_backed_qualification_child(name: str, quote: str) -> bool:
    compact = _compact_text(f"{name}{quote}")
    child_terms = (
        "营业执照",
        "许可证",
        "企业信用报告",
        "信用信息公示",
        "信用中国",
        "中国政府采购网",
        "失信被执行人",
        "重大税收违法",
        "政府采购严重违法",
        "审计报告",
        "财务报表",
        "财务状况报告",
        "资信证明",
        "法定代表人身份证明",
        "法定代表人授权书",
        "法人授权代表身份证",
        "资质证书",
        "资格证书",
        "授权代理证书",
        "其它资质",
        "其他资质",
    )
    return any(term in compact for term in child_terms)


def _is_source_backed_qualification_child_stop(name: str, quote: str) -> bool:
    compact = _compact_text(f"{name}{quote}")
    stop_terms = (
        "投标保证金",
        "报价保证金",
        "投标人银行账户",
        "银行账户信息",
        "中标承诺书",
        "反商业贿赂协议",
        "保密协议",
        "安全生产管理协议",
        "其他响应文件",
        "商务技术条款偏离表",
        "商务、技术条款偏离表",
        "投标人服务方案",
        "项目方案",
        "服务方案",
    )
    return any(term in compact for term in stop_terms)


def _extract_source_backed_file_composition(sections_payload: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Parse explicit response-file composition lists into file_composition.

    This copies list rows from the tender text; it does not invent requirements.
    It protects fatal certificate rows from LLM omission or skipped batches.
    """
    candidates: List[Tuple[int, int, List[Dict[str, Any]]]] = []

    def build_items(
        rows: List[Dict[str, Any]] | List[str],
        section: Dict[str, Any],
        *,
        source_kind: str,
    ) -> List[Dict[str, Any]]:
        group: List[Dict[str, Any]] = []
        seen: set[str] = set()
        active_qualification_parent_key = ""
        for order, row in enumerate(rows, start=1):
            if isinstance(row, dict):
                quote = str(row.get("quote") or row.get("name") or "").strip()
                name = str(row.get("name") or "").strip()
                outline_level = row.get("outline_level")
                outline_group = bool(row.get("outline_group"))
                row_parent_name = str(row.get("parent_name") or "").strip()
                row_template_ref = str(row.get("template_ref") or "").strip()
            else:
                quote = str(row or "").strip()
                outline_level = None
                outline_group = False
                row_parent_name = ""
                row_template_ref = ""
                if _is_unselected_submission_option(quote):
                    continue
                quote = _clean_source_backed_option_name(quote)
                name = _source_backed_composition_name(quote)
            if _is_unselected_submission_option(quote) or _is_unselected_submission_option(name):
                continue
            quote = _clean_source_backed_option_name(quote)
            name = _clean_source_backed_option_name(name)
            clean_name = str(name or "").strip()
            clean_quote = str(quote or clean_name).strip()
            if not clean_name:
                continue
            numbered_clause = _looks_like_numbered_file_composition_clause(clean_quote)
            explicit_numbered_row = bool(
                source_kind == "composition_list"
                and re.match(r"^\d+(?:\.\d+){1,4}\s*\S+", clean_quote)
            )
            if source_kind != "index_table" and not outline_group and not numbered_clause and not explicit_numbered_row and (
                _is_dirty_source_backed_line(clean_quote) or _is_dirty_source_backed_line(clean_name)
            ):
                continue
            if source_kind != "index_table" and not explicit_numbered_row and (
                _is_source_backed_format_explanation(clean_name) or _is_source_backed_format_explanation(clean_quote)
            ):
                continue
            if source_kind != "index_table":
                if _is_source_backed_qualification_parent(clean_name, clean_quote):
                    outline_level = int(outline_level or 1)
                    active_qualification_parent_key = re.sub(r"\s+", "", clean_name)
                elif active_qualification_parent_key:
                    if _is_source_backed_qualification_child_stop(clean_name, clean_quote):
                        active_qualification_parent_key = ""
                    elif _is_source_backed_qualification_child(clean_name, clean_quote):
                        outline_level = int(outline_level or 2)
                    else:
                        active_qualification_parent_key = ""
            key = re.sub(r"\s+", "", clean_name)
            dedupe_scope = active_qualification_parent_key if outline_level and int(outline_level) > 1 else "__root__"
            dedupe_key = f"{dedupe_scope}|{key}"
            root_dedupe_key = f"__root__|{key}"
            if dedupe_scope != "__root__" and root_dedupe_key not in seen:
                # A qualification child may add evidence details to a material
                # already listed at root level (for example "...书、...复印件").
                # Prefer the authoritative parent-child placement without
                # requiring title-specific aliases.
                root_alias = next(
                    (
                        seen_key
                        for seen_key in seen
                        if seen_key.startswith("__root__|")
                        and key.startswith(seen_key.split("|", 1)[1])
                    ),
                    "",
                )
                if root_alias:
                    root_name_key = root_alias.split("|", 1)[1]
                    group = [
                        item
                        for item in group
                        if re.sub(r"\s+", "", str(item.get("name") or "")) != root_name_key
                        or int(item.get("outline_level") or 1) > 1
                    ]
                    seen.discard(root_alias)
            if dedupe_scope != "__root__" and root_dedupe_key in seen:
                # If a later authoritative qualification parent repeats a
                # root-level item, keep the structured parent-child placement.
                group = [
                    item
                    for item in group
                    if re.sub(r"\s+", "", str(item.get("name") or "")) != key
                    or int(item.get("outline_level") or 1) > 1
                ]
                seen.discard(root_dedupe_key)
            if dedupe_key in seen:
                if key == "报价指引文件要求的其他内容":
                    clean_name = "技术报价书要求的其他内容"
                    key = re.sub(r"\s+", "", clean_name)
                    dedupe_key = f"{dedupe_scope}|{key}"
                    if dedupe_key in seen:
                        continue
                else:
                    continue
            seen.add(dedupe_key)
            template_ref = row_template_ref or _source_backed_template_ref(clean_quote)
            group.append(
                {
                    "name": clean_name,
                    "required": True,
                    "order": len(group) + 1,
                    "quote": clean_quote,
                    "template_ref": template_ref,
                    "has_template": bool(template_ref),
                    "section_id": section.get("section_id"),
                    "section_title": section.get("title"),
                    "source_backed_composition": True,
                    "source_backed_authoritative": True,
                    "source_kind": source_kind,
                }
            )
            parent_level = int(outline_level or 1)
            if outline_level:
                group[-1]["outline_level"] = parent_level
            if outline_group:
                group[-1]["outline_group"] = True
            if row_parent_name:
                group[-1]["parent_name"] = row_parent_name
        return group

    for section_index, section in enumerate(sections_payload):
        if _is_self_check_or_review_table_section(section):
            continue
        index_rows = _index_table_composition_rows(section)
        index_items = build_items(index_rows, section, source_kind="index_table")
        if _is_authoritative_source_backed_rows(index_items):
            candidates.append((_index_table_candidate_score(section), section_index, index_items))

    grouped_part_rows: List[Dict[str, Any]] = []
    first_part_index: int | None = None
    for section_index, section in enumerate(sections_payload):
        if _is_source_backed_risk_clause_section(section):
            continue
        if _is_self_check_or_review_table_section(section):
            continue
        part_rows = _part_section_composition_rows(section)
        if not part_rows:
            continue
        if first_part_index is None:
            first_part_index = section_index
        grouped_part_rows.extend(part_rows)
    if grouped_part_rows:
        grouped_items = build_items(grouped_part_rows, sections_payload[first_part_index or 0], source_kind="body_part_composition")
        if _is_authoritative_source_backed_rows(grouped_items):
            candidates.append((_body_part_candidate_score(grouped_items), first_part_index or 0, grouped_items))

    for section_index, section in enumerate(sections_payload):
        if _is_source_backed_risk_clause_section(section):
            continue
        if _is_self_check_or_review_table_section(section):
            continue
        heading_lines = _heading_composition_lines_from_sections(sections_payload, section_index)
        heading_items = build_items(heading_lines, section, source_kind="composition_list")
        if _is_authoritative_source_backed_rows(heading_items):
            candidates.append(
                (
                    _source_backed_candidate_score(section, heading_lines, source_kind="heading_composition"),
                    section_index,
                    heading_items,
                )
            )

    for section_index, section in enumerate(sections_payload):
        if _is_source_backed_risk_clause_section(section):
            continue
        if _is_self_check_or_review_table_section(section):
            continue
        section_lines = [str(line or "").strip() for line in str(section.get("content") or "").splitlines()]
        section_lines = [line for line in section_lines if line]
        section_lines = _scope_composition_lines_at_stop_headings(section_lines)
        protected_lines = _unified_composition_lines_from_anchor(section, section_lines)
        protected = _extract_file_composition_list_item(section)
        if protected:
            protected_candidate_lines = _composition_lines_from_protected_item(protected)
            protected_chunk_id = str(protected.get("chunk_id") or "")
            directory_boundary_trimmed = (
                "#directory_file_composition_list" in protected_chunk_id
                and 0 <= len(protected_lines) - len(protected_candidate_lines) <= 1
            )
            if len(protected_candidate_lines) > len(protected_lines) or directory_boundary_trimmed:
                protected_lines = protected_candidate_lines
        protected_lines = _append_nested_composition_child_rows(protected_lines, section_lines)
        if not protected_lines:
            continue
        protected_items = build_items(protected_lines, section, source_kind="composition_list")
        if _is_authoritative_source_backed_rows(protected_items):
            candidates.append(
                (
                    _source_backed_candidate_score(section, protected_lines, source_kind="composition_list"),
                    section_index,
                    protected_items,
                )
            )

    if not candidates:
        return []
    candidates.sort(key=lambda candidate: (-candidate[0], -len(candidate[2]), candidate[1]))
    return candidates[0][2]


def _source_backed_template_ref(text: str) -> str | None:
    compact = _compact_text(text)
    match = re.search(r"附件[一二三四五六七八九十\d]+(?:[-－—]\d+)?", compact)
    if match:
        return match.group(0)
    if "规定格式见附件" in compact or "格式见附件" in compact:
        return "附件"
    return None


def _is_source_backed_format_explanation(text: str) -> bool:
    compact = _compact_text(text)
    return any(term in compact for term in ("格式要求", "附件格式要求", "自查表格式要求"))


def _source_backed_candidate_score(section: Dict[str, Any], lines: List[str], *, source_kind: str) -> int:
    title = _compact_text(section.get("title") or "")
    relevance = _compact_text(section.get("relevance") or "")
    has_explicit_composition_title = _has_file_composition_anchor(title) and any(
        term in title for term in ("组成", "构成")
    )
    score = 700
    if source_kind == "index_table":
        score = 1000
    elif _looks_like_structural_composition_section(section):
        score = 880
    elif has_explicit_composition_title:
        score = 860
    elif any(_looks_like_composition_intro(line) for line in str(section.get("content") or "").splitlines()):
        score = 820
    synthetic_directory = str(section.get("section_id") or "").startswith("__plain_file_directory__")
    if not synthetic_directory:
        if "投标文件目录原文块" in relevance or "响应文件目录原文块" in relevance or "报价文件目录原文块" in relevance:
            score += 420
        if title in {"投标文件目录", "响应文件目录", "报价文件目录", "应答文件目录", "投标目录", "响应目录", "报价目录"}:
            score += 360
    if "权威提交清单章节" in relevance:
        score += 260
    if "响应文件索引目录表" in relevance:
        score += 240
    # Richer explicit checklists should beat shallow wrapper chapters when both
    # are otherwise plausible candidates.
    score += min(len(lines or []), 12) * 20
    if has_explicit_composition_title:
        score += 120
        if len(lines or []) >= 7:
            score += 80
    if (
        any(term in title for term in ("格式", "范本", "模板"))
        and not any(term in relevance for term in ("权威提交清单章节", "响应文件索引目录表"))
    ):
        score -= 500
    if any(term in title for term in ("有效性", "无效", "否决", "评分", "评审", "澄清", "保证金", "前附表")):
        score -= 500
    if lines:
        marker_count = sum(1 for line in lines if _has_composition_attachment_marker(line))
        if len(lines) > 15 and marker_count / max(len(lines), 1) > 0.45:
            score -= 80
    return score


def _body_part_candidate_score(items: List[Dict[str, Any]]) -> int:
    score = 960
    score += min(len(items or []), 20) * 14
    compact_names = {_compact_text(str(item.get("name") or "")) for item in items}
    if "商务部分" in compact_names and "技术部分" in compact_names:
        score += 80
    return score


def _index_table_candidate_score(section: Dict[str, Any]) -> int:
    title = _compact_text(section.get("title") or "")
    relevance = _compact_text(section.get("relevance") or "")
    score = 1200
    if any(marker in title for marker in ("详细评审索引目录表", "索引目录表", "响应文件索引", "投标文件索引", "投标文件所需资料")):
        score += 120
    if "响应文件索引目录表" in relevance:
        score += 160
    if _is_broad_format_umbrella_section(section):
        score -= 260
    return score


def _is_broad_format_umbrella_section(item: Dict[str, Any]) -> bool:
    title = re.sub(r"\s+", "", str(item.get("title") or ""))
    content_len = len(str(item.get("content") or ""))
    if content_len < 6000:
        return False
    return any(
        token in title
        for token in (
            "响应文件格式",
            "投标文件格式",
            "报价文件格式",
            "第五章响应文件格式",
            "第五章投标文件格式",
        )
    )


def _drop_broad_umbrella_sections(
    selected: List[Dict[str, Any]],
    config_name: str,
) -> List[Dict[str, Any]]:
    if config_name not in {
        "format_template",
        "qualification_review",
        "submission_checklist",
        "technical_scoring",
        "risk_contract",
    }:
        return selected
    specific = [item for item in selected if not _is_broad_format_umbrella_section(item)]
    if not specific:
        return selected
    return specific


# Public aliases for future modules; legacy private names are kept above for compatibility.
extract_source_backed_file_composition = _extract_source_backed_file_composition
is_authoritative_source_backed_rows = _is_authoritative_source_backed_rows
drop_broad_umbrella_sections = _drop_broad_umbrella_sections
extract_file_composition_list_item = _extract_file_composition_list_item
