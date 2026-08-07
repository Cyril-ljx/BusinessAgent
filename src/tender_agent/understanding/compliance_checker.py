from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from ..rules.engine import enrich_issue, load_rules, summarize_categories
from .composer import _normalize_outline_similarity_text


_RESPONSE_KEYWORD_GROUPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("社保", ("社保", "社会保障", "劳务合同")),
    ("纳税", ("纳税", "缴税", "税收", "完税")),
    ("业绩", ("业绩", "同类项目", "合同证明")),
    ("财务", ("财务", "审计", "资信")),
    ("信用", ("信用", "失信", "违法", "黑名单")),
    ("资质", ("资质", "证照", "营业执照", "许可证", "许可", "三证合一")),
    ("报价", ("报价", "价格", "限价", "报价表", "报价文件")),
    ("保证金", ("保证金", "投标保证金", "履约保证金")),
    ("授权", ("授权", "法定代表人", "法人", "身份证", "委托代理")),
    ("签章", ("签字", "签章", "盖章", "公章")),
    ("密封", ("密封", "封装", "封套")),
    ("偏离", ("偏离", "商务技术条款")),
    ("承诺", ("承诺", "声明", "投标函")),
    ("安全", ("安全", "安全生产")),
    ("保密", ("保密", "商业机密")),
    ("银行账户", ("银行账户", "开户行", "账号")),
    ("目录封面", ("封面", "目录")),
)

_STOPWORDS = {
    "未",
    "无",
    "不",
    "未按",
    "提供",
    "提交",
    "要求",
    "规定",
    "文件",
    "资料",
    "材料",
    "投标",
    "投标人",
    "报价人",
    "响应",
    "有效",
    "无效",
    "废标",
    "否决",
    "视为",
    "情况",
    "下列",
    "之一",
}

_CHINESE_ORDINAL = "一二三四五六七八九十百千万零〇两"
_RESIDUAL_ORDINAL_PREFIX_PAT = re.compile(
    rf"^\s*(?:[{_CHINESE_ORDINAL}]+[、.．]|[（(][{_CHINESE_ORDINAL}\d]+[）)])"
)
_OUTLINE_PREFIX_PATTERNS = (
    re.compile(r"^\s*格式\s*\d+(?:\.\d+)*(?:[、.．:：\-－—\s]*)"),
    re.compile(r"^\s*\d+(?:\.\d+)*(?:[、.．:：\-－—\s]*)"),
    re.compile(rf"^\s*[{_CHINESE_ORDINAL}]+[、.．\s]*"),
    re.compile(rf"^\s*[（(][{_CHINESE_ORDINAL}\d]+[）)]\s*"),
)
_PLACEHOLDER_TOKENS = (
    "[此处需人工填写",
    "此处需人工填写",
    "[待补充",
    "待补充",
    "未能定位原文范本",
    "请人工补充",
    "请基于上述素材完善",
    "TODO",
    "TBD",
)


def _build_node_name_map(outline: List[Dict[str, Any]]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}

    def walk(nodes: List[Dict[str, Any]]) -> None:
        for node in nodes:
            node_id = str(node.get("id", ""))
            node_name = str(node.get("name", ""))
            if node_id:
                mapping[node_id] = node_name
            children = node.get("children") or []
            if children:
                walk(children)

    walk(outline)
    return mapping


def _norm_text(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _strip_outline_prefixes(name: str) -> str:
    text = str(name or "").strip()
    previous = None
    while text and previous != text:
        previous = text
        for pattern in _OUTLINE_PREFIX_PATTERNS:
            text = pattern.sub("", text, count=1).strip()
    return text


def _effective_chinese_char_count(name: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", _strip_outline_prefixes(name)))


def _is_placeholder_text(text: Any) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    return any(token in value for token in _PLACEHOLDER_TOKENS)


def _node_issue(
    issue_type: str,
    node: Dict[str, Any],
    message: str,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "node_id": str(node.get("id", "")),
        "node_name": str(node.get("name", "")),
        "type": issue_type,
        "message": message,
        "evidence": evidence or {},
    }


def _declared_level(node: Dict[str, Any], fallback: int) -> int:
    try:
        return int(node.get("level") or fallback)
    except (TypeError, ValueError):
        return fallback


def _walk_outline_nodes(
    outline: List[Dict[str, Any]],
    parent: Optional[Dict[str, Any]] = None,
    depth: int = 1,
) -> List[Tuple[Dict[str, Any], Optional[Dict[str, Any]], int]]:
    rows: List[Tuple[Dict[str, Any], Optional[Dict[str, Any]], int]] = []
    for node in outline or []:
        if not isinstance(node, dict):
            continue
        rows.append((node, parent, depth))
        children = node.get("children") or []
        if isinstance(children, list) and children:
            rows.extend(_walk_outline_nodes(children, node, depth + 1))
    return rows


def _prefix_group_key(name: str) -> str:
    ordinal_match = re.match(rf"^\s*([{_CHINESE_ORDINAL}]+)[、.．]", str(name or ""))
    if ordinal_match:
        return f"ordinal:{ordinal_match.group(1)}"
    text = _normalize_outline_similarity_text(_strip_outline_prefixes(name))
    if not text:
        text = _normalize_outline_similarity_text(name)
    text = re.sub(r"\d+", "#", text)
    return text[:6] if len(text) >= 6 else ""


def _check_outline_shape(outline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for node, parent, depth in _walk_outline_nodes(outline):
        name = str(node.get("name", "")).strip()
        node_level = _declared_level(node, depth or 1)

        if name and _effective_chinese_char_count(name) < 2:
            issues.append(
                _node_issue(
                    "shell_numbered_node",
                    node,
                    "目录节点疑似仅保留编号或格式号，缺少实义名称",
                    {"raw_name": name, "stripped_name": _strip_outline_prefixes(name)},
                )
            )

        if depth > 1 and _RESIDUAL_ORDINAL_PREFIX_PAT.search(name):
            issues.append(
                _node_issue(
                    "residual_ordinal_prefix",
                    node,
                    "子级目录名称仍残留原文序号前缀",
                    {
                        "raw_name": name,
                        "parent_id": str((parent or {}).get("id", "")),
                        "parent_name": str((parent or {}).get("name", "")),
                    },
                )
            )

        if parent is None and node_level > 1:
            issues.append(
                _node_issue(
                    "orphan_outline_node",
                    node,
                    "目录节点层级大于 1，但在树结构中没有父节点",
                    {"declared_level": node_level, "tree_depth": depth},
                )
            )

        if depth >= 4 or node_level >= 4:
            issues.append(
                _node_issue(
                    "outline_depth_anomaly",
                    node,
                    "目录层级过深，建议人工确认是否错挂或过度拆分",
                    {"declared_level": node_level, "tree_depth": depth},
                )
            )

    def check_siblings(nodes: List[Dict[str, Any]], parent: Optional[Dict[str, Any]] = None) -> None:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for child in nodes or []:
            if not isinstance(child, dict):
                continue
            key = _prefix_group_key(str(child.get("name", "")))
            if key:
                groups.setdefault(key, []).append(child)
            children = child.get("children") or []
            if isinstance(children, list) and children:
                check_siblings(children, child)
        for key, siblings in groups.items():
            if len(siblings) < 2:
                continue
            names = [str(item.get("name", "")) for item in siblings[:8]]
            for item in siblings:
                issues.append(
                    _node_issue(
                        "suspicious_sibling_prefix",
                        item,
                        "同一父节点下存在多个共享相同前缀的目录项，可能被截断或错挂",
                        {
                            "prefix": key,
                            "sibling_names": names,
                            "parent_id": str((parent or {}).get("id", "")),
                            "parent_name": str((parent or {}).get("name", "")),
                        },
                    )
                )

    check_siblings(outline)
    return issues


def _flatten_assignment_materials(materials: Any) -> List[Dict[str, Any]]:
    flat: List[Dict[str, Any]] = []
    if not isinstance(materials, list):
        return flat
    for item in materials:
        if not isinstance(item, dict):
            continue
        nested = item.get("materials")
        if isinstance(nested, list):
            flat.extend(material for material in nested if isinstance(material, dict))
        else:
            flat.append(item)
    return flat


def _materials_cover_non_text_content(materials: List[Dict[str, Any]]) -> bool:
    flat = _flatten_assignment_materials(materials)
    if not flat:
        return False
    for material in flat:
        source = str(material.get("source") or "")
        if source in {"certificate", "tech_section", "tech_section_range", "uploaded_file", "file_attachment"}:
            return True
        if source == "tender_template" and str(material.get("render_status") or "") == "copied":
            return True
    return False


def _template_material_was_rendered(materials: List[Dict[str, Any]]) -> bool:
    return any(
        str(material.get("source") or "") == "tender_template"
        and str(material.get("render_status") or "") == "copied"
        for material in _flatten_assignment_materials(materials)
    )


def _check_template_backfill(
    assignments: List[Dict[str, Any]],
    generated: Dict[str, str],
    node_name_map: Dict[str, str],
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for assignment in assignments or []:
        if not isinstance(assignment, dict):
            continue
        node_id = str(assignment.get("node_id", "") or assignment.get("outline_node_id", "")).strip()
        if not node_id:
            continue
        materials = assignment.get("materials") or []
        template_materials = [
            material
            for material in materials
            if isinstance(material, dict) and str(material.get("source") or "") == "tender_template"
        ]
        if not template_materials:
            continue
        content = str(generated.get(node_id, "") or "").strip()
        if not _is_placeholder_text(content):
            continue
        issues.append(
            {
                "node_id": node_id,
                "node_name": str(assignment.get("node_name") or node_name_map.get(node_id) or node_id),
                "type": "template_backfill_missing",
                "message": "范本章节未能从招标原文回填有效正文",
                "evidence": {
                    "draft_preview": content[:160],
                    "template_materials": template_materials[:3],
                },
            }
        )
    return issues


def _check_placeholder_residue(
    generated: Dict[str, str],
    node_name_map: Dict[str, str],
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for node_id, content in (generated or {}).items():
        text = str(content or "")
        matched = [token for token in _PLACEHOLDER_TOKENS if token in text]
        if not matched:
            continue
        node_key = str(node_id)
        issues.append(
            {
                "node_id": node_key,
                "node_name": node_name_map.get(node_key, node_key),
                "type": "placeholder_residue",
                "message": "生成正文中残留待补充或人工填写占位符",
                "evidence": {
                    "placeholder_tokens": matched,
                    "draft_preview": text[:180],
                },
            }
        )
    return issues


def _atom(item: Dict[str, Any], key: str = "requirement") -> Dict[str, Any]:
    value = item.get(key)
    return value if isinstance(value, dict) else {}


def _severity(item: Dict[str, Any], atom_key: str = "requirement") -> str:
    return str(item.get("level") or _atom(item, atom_key).get("severity") or "").upper()


def _quote(item: Dict[str, Any], atom_key: str = "requirement") -> str:
    return str(item.get("quote") or _atom(item, atom_key).get("quote") or "")


def _anchor(item: Dict[str, Any], atom_key: str = "requirement") -> Dict[str, Any]:
    anchor = item.get("anchor") or _atom(item, atom_key).get("anchor")
    return anchor if isinstance(anchor, dict) else {}


def _requirement_label(item: Dict[str, Any]) -> str:
    for key in ("name", "condition", "item", "category"):
        if item.get(key):
            return str(item.get(key))
    return str(_atom(item).get("value") or _quote(item))


def _build_response_corpus(
    outline: List[Dict[str, Any]],
    generated: Dict[str, str],
    assignments: List[Dict[str, Any]],
) -> Tuple[str, List[Dict[str, str]]]:
    rows: List[Dict[str, str]] = []
    assignment_map = {str(a.get("node_id", "")): a.get("materials", []) or [] for a in assignments}

    def walk(nodes: List[Dict[str, Any]]) -> None:
        for node in nodes or []:
            node_id = str(node.get("id", ""))
            node_name = str(node.get("name", ""))
            material_names = " ".join(
                str(m.get("name") or m.get("title") or m.get("chapter_title") or "")
                for m in assignment_map.get(node_id, [])
                if isinstance(m, dict)
            )
            text = " ".join([node_id, node_name, str(generated.get(node_id, "")), material_names])
            if node_id or node_name:
                rows.append({"node_id": node_id, "node_name": node_name, "text": text})
            children = node.get("children") or []
            if children:
                walk(children)

    walk(outline)
    return _norm_text("\n".join(row["text"] for row in rows)), rows


def _extract_response_tokens(text: str) -> Set[str]:
    normalized = _norm_text(text)
    tokens: Set[str] = set()
    for canonical, aliases in _RESPONSE_KEYWORD_GROUPS:
        if any(_norm_text(alias) in normalized for alias in aliases):
            tokens.add(canonical)

    for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", str(text or "")):
        if token in _STOPWORDS:
            continue
        if any(stop in token and len(token) <= len(stop) + 1 for stop in _STOPWORDS):
            continue
        tokens.add(token)
    return tokens


def _is_requirement_covered(label: str, quote: str, corpus: str) -> bool:
    text = " ".join([label, quote])
    normalized_text = _norm_text(text)

    for phrase in (label, quote):
        phrase_norm = _norm_text(phrase)
        if phrase_norm and len(phrase_norm) >= 4 and phrase_norm in corpus:
            return True

    canonical_tokens = {
        canonical
        for canonical, aliases in _RESPONSE_KEYWORD_GROUPS
        if any(_norm_text(alias) in normalized_text for alias in aliases)
    }
    if canonical_tokens:
        return all(
            any(_norm_text(alias) in corpus for alias in aliases)
            for canonical, aliases in _RESPONSE_KEYWORD_GROUPS
            if canonical in canonical_tokens
        )

    meaningful = sorted(
        (token for token in _extract_response_tokens(text) if len(_norm_text(token)) >= 3),
        key=len,
        reverse=True,
    )[:3]
    if not meaningful:
        return False
    return any(_norm_text(token) in corpus for token in meaningful)


def _related_nodes(label: str, quote: str, response_rows: List[Dict[str, str]], limit: int = 5) -> List[Dict[str, str]]:
    tokens = _extract_response_tokens(" ".join([label, quote]))
    scored: List[Tuple[int, Dict[str, str]]] = []
    for row in response_rows:
        row_text = _norm_text(row.get("text", ""))
        score = sum(1 for token in tokens if _norm_text(token) and _norm_text(token) in row_text)
        if score:
            scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "node_id": row.get("node_id", ""),
            "node_name": row.get("node_name", ""),
        }
        for _, row in scored[:limit]
    ]


def _requirement_issue(
    issue_type: str,
    label: str,
    message: str,
    item: Dict[str, Any],
    severity: str,
    category: str,
    response_rows: List[Dict[str, str]],
    fatal: bool = True,
    atom_key: str = "requirement",
) -> Dict[str, Any]:
    quote = _quote(item, atom_key=atom_key)
    return {
        "node_id": "",
        "node_name": label,
        "type": issue_type,
        "message": message,
        "category": category,
        "severity": severity or "P0",
        "fatal": fatal,
        "owner": "商务" if category in {"qualification", "format", "pricing"} else "法务",
        "suggestion": "补充对应章节、正文响应或材料映射，并复核是否满足招标原文要求。",
        "evidence": {
            "requirement_name": label,
            "quote": quote,
            "anchor": _anchor(item, atom_key=atom_key),
            "matched_nodes": _related_nodes(label, quote, response_rows),
        },
    }


def _check_structured_requirements(
    tender_requirements: Dict[str, Any],
    outline: List[Dict[str, Any]],
    generated: Dict[str, str],
    assignments: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not isinstance(tender_requirements, dict) or not tender_requirements:
        return []

    corpus, response_rows = _build_response_corpus(outline, generated, assignments)
    issues: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    def add_once(issue: Dict[str, Any]) -> None:
        key = "|".join(
            [
                str(issue.get("type", "")),
                str(issue.get("node_name", "")),
                str((issue.get("evidence") or {}).get("quote", ""))[:80],
            ]
        )
        if key in seen:
            return
        seen.add(key)
        issues.append(issue)

    for item in tender_requirements.get("qualifications") or []:
        if not isinstance(item, dict) or not item.get("mandatory", True):
            continue
        label = _requirement_label(item)
        quote = _quote(item)
        item_severity = _severity(item) or "P1"
        if item_severity in {"P0", "P1"} and not _is_requirement_covered(label, quote, corpus):
            add_once(
                _requirement_issue(
                    "missing_p0_requirement_response" if item_severity == "P0" else "missing_qualification_response",
                    label,
                    f"资格门槛未在目录/正文/素材中发现明确响应: {label}",
                    item,
                    "P0" if item_severity == "P0" else "P1",
                    "qualification",
                    response_rows,
                    fatal=True,
                )
            )

    for item in tender_requirements.get("material_checklist") or []:
        if not isinstance(item, dict) or not item.get("required", True):
            continue
        label = _requirement_label(item)
        quote = _quote(item)
        item_severity = _severity(item) or "P1"
        if item_severity in {"P0", "P1"} and not _is_requirement_covered(label, quote, corpus):
            add_once(
                _requirement_issue(
                    "missing_required_material_response",
                    label,
                    f"必备材料未在目录/正文/素材中发现明确响应: {label}",
                    item,
                    "P0" if item_severity == "P0" else "P1",
                    "qualification",
                    response_rows,
                    fatal=item_severity == "P0",
                )
            )

    for item in tender_requirements.get("invalidation") or []:
        if not isinstance(item, dict):
            continue
        level = str(item.get("level") or "P0").upper()
        if level != "P0":
            continue
        label = _requirement_label(item)
        quote = _quote(item, atom_key="")
        if not _is_requirement_covered(label, quote, corpus):
            add_once(
                _requirement_issue(
                    "uncovered_invalidation_clause",
                    label,
                    f"废标/无效条款未找到对应响应章节: {label}",
                    item,
                    "P0",
                    "invalid",
                    response_rows,
                    fatal=True,
                    atom_key="",
                )
            )

    return issues


def run_compliance_checks(state: Dict[str, Any], rule_version: str = "v1") -> Dict[str, Any]:
    outline = state.get("final_outline") or state.get("outline") or []
    assignments = state.get("material_assignments") or []
    generated = state.get("generated_sections") or {}
    rag_contexts = state.get("rag_contexts") or {}
    located_sections = state.get("located_sections") or []
    tender_requirements = state.get("tender_requirements") or {}

    assignment_map = {str(a.get("node_id", "")): a.get("materials", []) or [] for a in assignments}

    leaf_nodes: List[Dict[str, Any]] = []

    def walk(nodes):
        for n in nodes:
            children = n.get("children") or []
            if children:
                walk(children)
            else:
                leaf_nodes.append(n)

    walk(outline)

    issues: List[Dict[str, Any]] = []
    seen_issue_keys: Set[str] = set()
    ruleset = load_rules(rule_version)
    node_name_map = _build_node_name_map(outline)

    def add_issue(issue: Dict[str, Any], preserve_deterministic_fields: bool = False) -> None:
        evidence = issue.get("evidence") if isinstance(issue.get("evidence"), dict) else {}
        key = "|".join(
            [
                str(issue.get("node_id", "")),
                str(issue.get("type", "")),
                str(issue.get("node_name", "")),
                str(evidence.get("quote") or evidence.get("draft_preview") or evidence.get("raw_name") or "")[:80],
            ]
        )
        if key in seen_issue_keys:
            return
        seen_issue_keys.add(key)
        enriched = enrich_issue(issue, ruleset)
        if preserve_deterministic_fields:
            enriched.update(
                {
                    k: v
                    for k, v in issue.items()
                    if k in {"severity", "fatal", "owner", "suggestion", "category"}
                }
            )
        issues.append(enriched)

    for n in leaf_nodes:
        nid = str(n.get("id", ""))
        nname = str(n.get("name", ""))
        required = bool(n.get("required", True))
        mats = assignment_map.get(nid, [])
        content = (generated.get(nid) or "").strip()

        if required and not mats:
            issue = {
                "node_id": nid,
                "node_name": nname,
                "type": "missing_material",
                "message": "必填章节无素材映射",
                "evidence": {
                    "materials": mats,
                    "rag_candidates": rag_contexts.get(nid, {}),
                },
            }
            add_issue(issue)

        if required and ("待补充" in content or (not content and not _materials_cover_non_text_content(mats))):
            issue_evidence_sections = []
            for sec in located_sections:
                sec_title = str(sec.get("title", ""))
                if any(token in sec_title for token in (nname[:6], "评分", "资格", "响应", "要求")):
                    issue_evidence_sections.append(
                        {
                            "section_id": sec.get("section_id", ""),
                            "section_title": sec_title,
                            "anchor_start": sec.get("anchor_start"),
                            "anchor_end": sec.get("anchor_end"),
                            "snippet": str(sec.get("content", ""))[:120],
                            "anchor_blocks": sec.get("anchor_blocks", [])[:3],
                        }
                    )
                if len(issue_evidence_sections) >= 3:
                    break

            issue = {
                "node_id": nid,
                "node_name": nname,
                "type": "incomplete_content",
                "message": "必填章节存在待补充内容",
                "evidence": {
                    "draft_preview": content[:120],
                    "related_sections": issue_evidence_sections,
                },
            }
            add_issue(issue)

    deterministic_issues: List[Dict[str, Any]] = []
    deterministic_issues.extend(_check_outline_shape(outline))
    deterministic_issues.extend(_check_template_backfill(assignments, generated, node_name_map))
    deterministic_issues.extend(_check_placeholder_residue(generated, node_name_map))
    for issue in deterministic_issues:
        add_issue(issue)

    structured_issues = _check_structured_requirements(
        tender_requirements=tender_requirements,
        outline=outline,
        generated=generated,
        assignments=assignments,
    )
    for issue in structured_issues:
        add_issue(issue, preserve_deterministic_fields=True)

    fatal = sum(1 for i in issues if i.get("fatal"))

    report = {
        "passed": fatal == 0,
        "fatal_count": fatal,
        "issue_count": len(issues),
        "issues": issues,
        "node_name_map": node_name_map,
        "rule_version": ruleset.get("version", rule_version),
        "category_stats": summarize_categories(issues),
        "structured_requirement_issue_count": len(structured_issues),
        "deterministic_issue_count": len(deterministic_issues),
    }
    return {"compliance_report": report}
