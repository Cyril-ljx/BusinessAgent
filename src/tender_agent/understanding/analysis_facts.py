"""Build one traceable analysis view from extracted tender requirements.

This module intentionally only normalizes existing extraction output.  It does
not infer new tender requirements, so the analysis layer cannot change the
directory, material mapping, or rendering plan.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List


ANALYSIS_GROUP_KEYS = (
    "basic_info",
    "file_composition",
    "material_checklist",
    "qualifications",
    "scoring",
    "technical_requirements",
    "business_terms",
    "format_requirements",
    "invalidation",
)

_BASE_INFO_LABELS = {
    "project_name": "项目名称",
    "tender_no": "项目编号",
    "purchaser": "采购人",
    "agency": "代理机构",
    "submission_deadline": "递交截止时间",
    "bid_open_time": "开标时间",
    "bid_validity_period": "投标有效期",
    "document_title": "文件名称",
}

_BUSINESS_LABELS = {
    "highest_limit": "最高限价",
    "quotation_method": "报价方式",
    "price_components": "报价组成",
    "tax_rules": "税费规则",
    "abnormal_price_rules": "异常报价规则",
    "required": "保证金要求",
    "amount": "保证金金额",
    "currency": "币种",
    "payment_method": "缴纳方式",
    "payment_deadline": "缴纳截止时间",
    "refund_conditions": "退还条件",
    "forfeiture_conditions": "没收条件",
    "service_period": "服务期限",
    "performance_bond": "履约保证金",
    "payment_terms": "付款条款",
    "acceptance_rules": "验收规则",
    "penalty_clauses": "违约条款",
    "other_risks": "其他合同风险",
}


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    if isinstance(value, dict):
        for key in ("value", "criteria", "required_value", "quote", "name", "condition", "time"):
            text = _text(value.get(key))
            if text:
                return text
    return ""


def _anchor(item: Dict[str, Any]) -> Dict[str, Any] | None:
    nested = (
        _as_dict(item.get("requirement"))
        or _as_dict(item.get("criteria"))
        or _as_dict(item.get("required_value"))
    )
    anchor = nested.get("anchor") or item.get("anchor")
    return _as_dict(anchor) or None


def _quote(item: Dict[str, Any]) -> str:
    nested = (
        _as_dict(item.get("requirement"))
        or _as_dict(item.get("criteria"))
        or _as_dict(item.get("required_value"))
    )
    return _text(item.get("quote")) or _text(nested.get("quote"))


def _severity(item: Dict[str, Any], default: str = "P2") -> str:
    nested = (
        _as_dict(item.get("requirement"))
        or _as_dict(item.get("criteria"))
        or _as_dict(item.get("required_value"))
    )
    return _text(item.get("severity")) or _text(nested.get("severity")) or default


def _fact(
    group: str,
    source_field: str,
    index: int,
    title: str,
    item: Dict[str, Any],
    *,
    detail: str = "",
    value: str = "",
    severity: str | None = None,
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    fact = {
        "id": f"{group}:{source_field}:{index}",
        "group": group,
        "source_field": source_field,
        "title": title.strip() or source_field,
        "value": value.strip(),
        "detail": detail.strip(),
        "quote": _quote(item),
        "anchor": _anchor(item),
        "severity": severity or _severity(item),
    }
    if extra:
        fact.update({key: value for key, value in extra.items() if value not in (None, "", [], {})})
    return fact


def _append_if_meaningful(items: List[Dict[str, Any]], fact: Dict[str, Any]) -> None:
    if any(str(fact.get(key) or "").strip() for key in ("title", "value", "detail", "quote")):
        items.append(fact)


def _facts_for_named_items(
    group: str,
    source_field: str,
    items: Iterable[Any],
    *,
    title_key: str = "name",
    value_key: str = "value",
    detail_key: str = "",
    default_severity: str = "P2",
) -> List[Dict[str, Any]]:
    facts: List[Dict[str, Any]] = []
    for index, raw in enumerate(items, start=1):
        item = _as_dict(raw)
        if not item:
            continue
        title = _text(item.get(title_key)) or source_field
        detail = _text(item.get(detail_key)) if detail_key else ""
        value = _text(item.get(value_key))
        _append_if_meaningful(
            facts,
            _fact(
                group,
                source_field,
                index,
                title,
                item,
                detail=detail,
                value=value,
                severity=_severity(item, default_severity),
            ),
        )
    return facts


def build_tender_analysis_facts(requirements: Any) -> Dict[str, Any]:
    """Return a stable, source-traceable fact table from ``tender_requirements``."""
    source = _as_dict(requirements)
    groups: Dict[str, List[Dict[str, Any]]] = {key: [] for key in ANALYSIS_GROUP_KEYS}

    base_info = _as_dict(source.get("base_info"))
    for index, (field, label) in enumerate(_BASE_INFO_LABELS.items(), start=1):
        item = _as_dict(base_info.get(field))
        if item:
            _append_if_meaningful(
                groups["basic_info"],
                _fact("basic_info", field, index, label, item, value=_text(item.get("value")), severity=_severity(item, "P1")),
            )
    groups["basic_info"].extend(
        _facts_for_named_items("basic_info", "timeline", _as_list(source.get("timeline")), title_key="name", value_key="time", default_severity="P1")
    )

    groups["file_composition"].extend(
        _facts_for_named_items("file_composition", "file_composition", _as_list(source.get("file_composition")), value_key="", detail_key="template_ref", default_severity="P1")
    )
    groups["material_checklist"].extend(
        _facts_for_named_items("material_checklist", "material_checklist", _as_list(source.get("material_checklist")), value_key="", default_severity="P1")
    )
    groups["qualifications"].extend(
        _facts_for_named_items("qualifications", "qualifications", _as_list(source.get("qualifications")), value_key="evidence_hint", default_severity="P1")
    )

    for index, raw in enumerate(_as_list(source.get("scoring")), start=1):
        item = _as_dict(raw)
        if not item:
            continue
        score = item.get("score")
        score_text = f"{score} 分" if score is not None and str(score) != "" else ""
        _append_if_meaningful(
            groups["scoring"],
            _fact(
                "scoring",
                "scoring",
                index,
                _text(item.get("item")),
                item,
                value=score_text,
                detail=_text(item.get("criteria")),
                severity=_severity(item, "P1"),
                extra={"category": item.get("category"), "score_type": item.get("score_type"), "score": score},
            ),
        )

    for index, raw in enumerate(_as_list(source.get("technical_requirements")), start=1):
        item = _as_dict(raw)
        if not item:
            continue
        _append_if_meaningful(
            groups["technical_requirements"],
            _fact(
                "technical_requirements",
                "technical_requirements",
                index,
                _text(item.get("name")),
                item,
                value=_text(item.get("required_value")),
                detail=_text(item.get("response_hint")),
                severity=_severity(item, "P1"),
                extra={"category": item.get("category"), "quantity": _text(item.get("quantity")), "mandatory": item.get("mandatory")},
            ),
        )

    business_index = 0
    for source_field, container_name in (("pricing", "pricing"), ("deposit", "deposit"), ("contract", "contract")):
        container = _as_dict(source.get(container_name))
        for field, label in _BUSINESS_LABELS.items():
            if field not in container:
                continue
            values = _as_list(container.get(field)) or [container.get(field)]
            for raw in values:
                item = _as_dict(raw)
                if not item:
                    continue
                business_index += 1
                _append_if_meaningful(
                    groups["business_terms"],
                    _fact(
                        "business_terms",
                        f"{source_field}.{field}",
                        business_index,
                        label,
                        item,
                        value=_text(item.get("value")),
                        severity=_severity(item, "P1"),
                    ),
                )

    groups["format_requirements"].extend(
        _facts_for_named_items("format_requirements", "format_requirements", _as_list(source.get("format_requirements")), value_key="template_ref", default_severity="P1")
    )
    for index, raw in enumerate(_as_list(source.get("invalidation")), start=1):
        item = _as_dict(raw)
        if not item:
            continue
        _append_if_meaningful(
            groups["invalidation"],
            _fact(
                "invalidation",
                "invalidation",
                index,
                _text(item.get("condition")),
                item,
                detail=_text(item.get("category")),
                severity=_severity(item, "P0"),
            ),
        )

    return {
        "groups": groups,
        "summary": {key: len(value) for key, value in groups.items()},
    }


def strategy_prompt(facts: Dict[str, Any]) -> str:
    groups = _as_dict(facts.get("groups"))
    scoring = _as_list(groups.get("scoring"))[:50]
    risks = _as_list(groups.get("invalidation"))[:50]
    payload = {"scoring": scoring, "risks": risks}
    return (
        "你是投标分析助手。只能依据以下带有 id 和原文依据的事实生成建议，不能补造招标要求、"
        "资质、分值或承诺。\n"
        "对 scoring 事实：给出 2-4 条可执行的争分动作；对 invalidation 事实：给出 2-4 条核验/规避动作。\n"
        "每条建议必须对应一个现有 fact_id；没有可靠依据的事实不要输出。建议简洁、可执行，不要复述原文。\n"
        f"事实 JSON：{json.dumps(payload, ensure_ascii=False)}"
    )
