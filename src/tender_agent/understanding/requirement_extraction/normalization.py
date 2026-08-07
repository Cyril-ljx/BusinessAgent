"""Normalization and merge helpers for requirement extraction payloads."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

from ..requirements import (
    FileCompositionItem,
    FormatRequirement,
    InvalidationClause,
    MaterialItem,
    QualificationRequirement,
    ScoringCriterion,
    ScoringGroup,
    ScoringOverview,
    TechnicalRequirement,
    TenderRequirements,
    TimelineRequirement,
    RequirementAtom,
    SourceAnchor,
)
from ..requirements_common import _compact_text
from .anchors import _simple_anchor

_DEPOSIT_AMOUNT_RE = re.compile(
    r"(?:人民币|￥)?\s*\d+(?:\.\d+)?\s*(?:万元|元|%)?",
    re.IGNORECASE,
)


def _extract_datetime_phrase(text: Any) -> str:
    value = str(text or "")
    match = re.search(
        r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日(?:\s*\d{1,2}\s*[:：]\s*\d{1,2})?",
        value,
    )
    return match.group(0) if match else ""


def _extract_scoring_score(text: Any) -> Any:
    value = str(text or "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*分", value)
    if not match:
        return None
    number = match.group(1)
    return float(number) if "." in number else int(number)


def _infer_scoring_type(
    category: str = "",
    item: str = "",
    quote: str = "",
    section_title: str = "",
) -> str:
    """Classify a scoring row using the complete evidence already supplied by callers."""
    haystack = _compact_text(
        " ".join(str(part or "") for part in (category, item, quote, section_title))
    )
    if any(term in haystack for term in ("最低价法", "综合评审法", "评审办法", "评审步骤", "定标方式")):
        return "评审方法"
    if any(term in haystack for term in ("符合性评审", "符合性审查", "资格性审查")):
        return "符合性评审"
    if any(
        term in haystack
        for term in (
            "价格标",
            "报价标",
            "价格评分",
            "价格评审",
            "报价评分",
            "报价得分",
            "评审基准价",
            "价格分",
            "报价分",
        )
    ):
        return "价格评分"
    if any(term in haystack for term in ("技术标", "技术评分", "技术评审")):
        return "技术评分"
    if any(term in haystack for term in ("商务标", "商务评分", "商务评审")):
        return "商务评分"
    if any(
        term in haystack
        for term in (
            "业绩",
            "资质",
            "资信",
            "证书",
            "认证",
            "许可证",
            "营业执照",
            "信用",
            "纳税",
            "社保",
            "财务",
            "授权",
            "分签",
            "注册资本",
            "项目负责人",
            "合同经验",
        )
    ):
        return "商务评分"
    if any(
        term in haystack
        for term in (
            "方案",
            "服务",
            "技术",
            "应急",
            "响应",
            "管理制度",
            "培训",
            "招聘",
            "保障",
            "现场",
            "履约",
            "食品安全",
            "运营",
        )
    ):
        return "技术评分"
    return "评分标准"

def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict, str)) and not value:
        return True
    return False


def _dedupe_key(item: Any) -> str:
    if not isinstance(item, dict):
        return json.dumps(item, ensure_ascii=False, sort_keys=True)
    if item.get("source_backed_composition"):
        return "source_composition:{}:{}:{}".format(
            item.get("section_id") or "",
            item.get("order") or "",
            re.sub(r"\s+", "", str(item.get("quote") or item.get("name") or "")),
        )
    if item.get("quote") and item.get("condition"):
        return "invalidation:" + re.sub(r"\s+", "", str(item.get("quote") or ""))
    requirement = item.get("requirement") if isinstance(item.get("requirement"), dict) else {}
    material_text = f"{item.get('name') or ''}{requirement.get('quote') or ''}{item.get('quote') or ''}"
    if any(
        word in material_text
        for word in (
            "证",
            "证明",
            "许可证",
            "执照",
            "截图",
            "报告",
            "报表",
            "账户",
            "保证金",
            "承诺书",
            "协议",
            "授权书",
            "报价表",
            "报价单",
            "业绩",
            "社保",
            "劳务合同",
        )
    ):
        return "material:" + _material_semantic_key(
            str(item.get("name") or ""),
            str(requirement.get("quote") or item.get("quote") or ""),
        )
    parts = [
        item.get("name"),
        item.get("condition"),
        item.get("item"),
        item.get("category"),
        item.get("quote"),
    ]
    requirement = item.get("requirement")
    if isinstance(requirement, dict):
        parts.append(requirement.get("quote"))
        parts.append(str(requirement.get("value")))
    required_value = item.get("required_value")
    if isinstance(required_value, dict):
        parts.append(required_value.get("quote"))
        parts.append(str(required_value.get("value")))
    return "|".join(str(part or "") for part in parts)


def _source_backed_material_semantic(item: Any) -> str | None:
    if not isinstance(item, dict) or not item.get("source_backed_composition"):
        return None
    requirement = item.get("requirement") if isinstance(item.get("requirement"), dict) else {}
    return _material_semantic_key(
        str(item.get("name") or ""),
        str(requirement.get("quote") or item.get("quote") or ""),
    )


def _merge_lists(left: List[Any], right: List[Any]) -> List[Any]:
    merged = list(left or [])
    seen = {_dedupe_key(item) for item in merged}
    source_semantics = {
        key for key in (_source_backed_material_semantic(item) for item in merged) if key
    }
    for item in right or []:
        if isinstance(item, dict) and not item.get("source_backed_composition"):
            requirement = item.get("requirement") if isinstance(item.get("requirement"), dict) else {}
            semantic = _material_semantic_key(
                str(item.get("name") or ""),
                str(requirement.get("quote") or item.get("quote") or ""),
            )
            if semantic in source_semantics:
                continue
        key = _dedupe_key(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
        source_key = _source_backed_material_semantic(item)
        if source_key:
            source_semantics.add(source_key)
    return merged


def _merge_objects(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(left or {})
    for key, value in (right or {}).items():
        if _is_empty_value(value):
            continue
        existing = merged.get(key)
        if isinstance(existing, list) and isinstance(value, list):
            merged[key] = _merge_lists(existing, value)
        elif isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _merge_objects(existing, value)
        elif _is_empty_value(existing):
            merged[key] = value
    return merged


def _as_requirement_atom(value: Any) -> Any:
    if value is None or value == "":
        return value
    if isinstance(value, dict):
        return value
    return {"value": value, "quote": str(value)}


def _as_requirement_atom_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_as_requirement_atom(item) for item in value if item not in (None, "")]
    if value == "":
        return []
    return [_as_requirement_atom(value)]


def _normalize_document_type(value: Any) -> str:
    allowed = tuple(TenderRequirements.model_fields["document_type"].annotation.__args__)
    text = str(value or "").strip()
    if text in allowed:
        return text
    for item in allowed:
        if item and (text.startswith(item) or item in text):
            return item
    return allowed[-1]


def _normalize_severity(value: Any, default: str = "P2") -> str:
    text = str(value or "").strip().upper()
    if text in {"P0", "P1", "P2", "P3"}:
        return text
    if any(word in text for word in ("致命", "废标", "无效", "HIGH", "高")):
        return "P0"
    if any(word in text for word in ("重要", "较高", "MEDIUM", "中")):
        return "P1"
    if any(word in text for word in ("参考", "LOW", "低")):
        return "P3"
    return default


def _coerce_atom_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize common LLM scalar shortcuts before final TenderRequirements validation."""
    if not isinstance(payload, dict):
        return payload

    payload["document_type"] = _normalize_document_type(payload.get("document_type"))

    base_info = payload.get("base_info")
    if isinstance(base_info, dict):
        for key in (
            "project_name",
            "tender_no",
            "purchaser",
            "agency",
            "submission_deadline",
            "bid_open_time",
            "bid_validity_period",
            "document_title",
        ):
            if key in base_info:
                base_info[key] = _as_requirement_atom(base_info.get(key))

    deposit = payload.get("deposit")
    if isinstance(deposit, dict):
        for key in ("required", "amount", "currency", "payment_method", "payment_deadline"):
            if key in deposit:
                deposit[key] = _as_requirement_atom(deposit.get(key))
        for key in ("refund_conditions", "forfeiture_conditions"):
            deposit[key] = _as_requirement_atom_list(deposit.get(key))

    pricing = payload.get("pricing")
    if isinstance(pricing, dict):
        for key in ("highest_limit", "quotation_method"):
            if key in pricing:
                pricing[key] = _as_requirement_atom(pricing.get(key))
        for key in ("price_components", "tax_rules", "abnormal_price_rules"):
            pricing[key] = _as_requirement_atom_list(pricing.get(key))

    contract = payload.get("contract")
    if isinstance(contract, dict):
        for key in ("service_period", "performance_bond"):
            if key in contract:
                contract[key] = _as_requirement_atom(contract.get(key))
        for key in ("payment_terms", "acceptance_rules", "penalty_clauses", "other_risks"):
            contract[key] = _as_requirement_atom_list(contract.get(key))

    for item in payload.get("timeline") or []:
        if isinstance(item, dict) and "time" in item:
            item["time"] = _as_requirement_atom(item.get("time"))

    for item in payload.get("technical_requirements") or []:
        if not isinstance(item, dict):
            continue
        if "required_value" in item:
            item["required_value"] = _as_requirement_atom(item.get("required_value"))
        if "quantity" in item:
            item["quantity"] = _as_requirement_atom(item.get("quantity"))

    for list_name, atom_key in (
        ("file_composition", "requirement"),
        ("format_requirements", "requirement"),
        ("qualifications", "requirement"),
        ("scoring", "criteria"),
        ("material_checklist", "requirement"),
        ("bidder_special_requirements", "requirement"),
    ):
        for item in payload.get(list_name) or []:
            if isinstance(item, dict) and atom_key in item:
                item[atom_key] = _as_requirement_atom(item.get(atom_key))

    return payload


def _normalize_file_composition(items: List[Any]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("requirement"), dict):
            normalized.append(item)
            continue

        anchor = None
        if item.get("section_id") or item.get("section_title"):
            anchor = SourceAnchor(
                section_id=item.get("section_id"),
                section_title=item.get("section_title"),
            )
        requirement = RequirementAtom(
            value=item.get("name") or item.get("quote") or "",
            quote=item.get("quote") or "",
            anchor=anchor,
        )
        payload = FileCompositionItem(
            name=item.get("name") or "",
            required=bool(item.get("required", True)),
            order=item.get("order"),
            template_ref=item.get("template_ref"),
            requirement=requirement,
        ).model_dump(mode="json")
        if item.get("source_backed_composition"):
            payload["source_backed_composition"] = True
        for extra_key in ("source_kind", "outline_level", "outline_group", "parent_name"):
            if item.get(extra_key) is not None:
                payload[extra_key] = item.get(extra_key)
        normalized.append(payload)
    return normalized


def _file_composition_final_source_stats(rows: List[Any]) -> Dict[str, Any]:
    total = sum(1 for item in rows or [] if isinstance(item, dict))
    if total <= 0:
        return {
            "file_composition_final_source": "empty",
            "file_composition_final_count": 0,
            "file_composition_final_source_counts": {
                "source_backed": 0,
                "llm": 0,
                "unknown": 0,
            },
        }

    source_backed_count = 0
    llm_count = 0
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        if item.get("source_backed_composition") is True:
            source_backed_count += 1
        elif item.get("outline_level") is not None or not item.get("source_kind"):
            llm_count += 1
    unknown_count = max(0, total - source_backed_count - llm_count)
    if source_backed_count == total:
        final_source = "source_backed"
    elif llm_count == total:
        final_source = "llm"
    else:
        final_source = "mixed"
    return {
        "file_composition_final_source": final_source,
        "file_composition_final_count": total,
        "file_composition_final_source_counts": {
            "source_backed": source_backed_count,
            "llm": llm_count,
            "unknown": unknown_count,
        },
    }


def _normalize_format_requirements(items: List[Any]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("requirement"), dict):
            normalized.append(item)
            continue

        anchor = None
        if item.get("section_id") or item.get("section_title"):
            anchor = SourceAnchor(
                section_id=item.get("section_id"),
                section_title=item.get("section_title"),
            )
        requirement = RequirementAtom(
            value=item.get("quote") or item.get("name") or "",
            quote=item.get("quote") or "",
            anchor=anchor,
            severity=item.get("severity") or "P2",
        )
        normalized.append(
            FormatRequirement(
                name=item.get("name") or "",
                requirement=requirement,
                template_ref=item.get("template_ref"),
            ).model_dump(mode="json")
        )
    return normalized


def _make_atom_from_simple_item(item: Dict[str, Any], default_severity: str = "P2") -> RequirementAtom:
    anchor = _simple_anchor(item)
    return RequirementAtom(
        value=item.get("quote") or item.get("name") or "",
        quote=item.get("quote") or "",
        anchor=anchor,
        severity=_normalize_severity(item.get("severity"), default_severity),
    )


def _simple_atom(
    item: Dict[str, Any],
    value_key: str = "value",
    default_severity: str = "P2",
) -> RequirementAtom:
    value = item.get(value_key) or item.get("quote") or item.get("name") or ""
    return RequirementAtom(
        value=value,
        quote=item.get("quote") or str(value or ""),
        anchor=_simple_anchor(item),
        severity=_normalize_severity(item.get("severity"), default_severity),
    )


def _normalize_base_info_items(items: List[Any]) -> Dict[str, Any]:
    field_aliases = {
        "项目名称": "project_name",
        "项目编号": "tender_no",
        "招标编号": "tender_no",
        "采购编号": "tender_no",
        "招标人": "purchaser",
        "采购人": "purchaser",
        "代理机构": "agency",
        "投标截止": "submission_deadline",
        "递交截止": "submission_deadline",
        "开标时间": "bid_open_time",
        "投标有效期": "bid_validity_period",
        "投标报价有效期": "bid_validity_period",
        "报价有效期": "bid_validity_period",
        "响应有效期": "bid_validity_period",
        "文件标题": "document_title",
        "文档标题": "document_title",
    }
    normalized: Dict[str, Any] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        raw_field = str(item.get("field") or item.get("name") or "")
        target = None
        for keyword, field_name in field_aliases.items():
            if keyword in raw_field:
                target = field_name
                break
        if not target or normalized.get(target):
            continue
        normalized[target] = _simple_atom(item, "value", "P1").model_dump(mode="json")
    return normalized


def _normalize_timeline(items: List[Any]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        normalized.append(
            TimelineRequirement(
                name=item.get("name") or item.get("action") or "",
                time=_simple_atom(item, "time", "P1"),
                action=item.get("action"),
                fatal_if_missed=bool(item.get("fatal_if_missed", False)),
            ).model_dump(mode="json")
        )
    return normalized


def _normalize_qualifications(items: List[Any]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("requirement"), dict):
            normalized.append(item)
            continue
        normalized.append(
            QualificationRequirement(
                name=item.get("name") or "",
                requirement=_make_atom_from_simple_item(item, "P1"),
                mandatory=bool(item.get("mandatory", True)),
                evidence_hint=item.get("evidence_hint"),
            ).model_dump(mode="json")
        )
    return normalized


def _normalize_technical_requirements(items: List[Any]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("required_value"), dict):
            normalized.append(item)
            continue
        quantity = None
        if item.get("quantity") not in (None, ""):
            quantity = _simple_atom(item, "quantity", "P2")
        normalized.append(
            TechnicalRequirement(
                name=item.get("name") or item.get("param_name") or "",
                param_name=item.get("param_name"),
                required_value=_simple_atom(item, "required_value", "P1"),
                quantity=quantity,
                mandatory=bool(item.get("mandatory", True)),
                category=item.get("category"),
                response_hint=item.get("response_hint"),
            ).model_dump(mode="json")
        )
    return normalized


def _normalize_scoring(items: List[Any]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        category = item.get("category") or ""
        scoring_item = item.get("item") or item.get("name") or ""
        criteria_value = item.get("criteria")
        score_value = item.get("score")
        if score_value in ("", None) and isinstance(criteria_value, dict):
            score_value = _extract_scoring_score(criteria_value.get("quote") or criteria_value.get("value") or "")
        elif score_value in ("", None):
            score_value = _extract_scoring_score(criteria_value or "")
        score_type = item.get("score_type") or _infer_scoring_type(
            category=category,
            item=scoring_item,
            quote=(criteria_value.get("quote") or criteria_value.get("value") or "") if isinstance(criteria_value, dict) else str(criteria_value or ""),
            section_title=item.get("section_title") or "",
        )
        if isinstance(criteria_value, dict):
            normalized.append(
                ScoringCriterion(
                    category=category,
                    score_type=score_type,
                    item=scoring_item,
                    score=score_value,
                    criteria=_as_requirement_atom(criteria_value),
                    evidence_hint=item.get("evidence_hint"),
                ).model_dump(mode="json")
            )
            continue
        normalized.append(
            ScoringCriterion(
                category=category,
                score_type=score_type,
                item=scoring_item,
                score=score_value,
                criteria=_simple_atom(item, "criteria", "P2"),
                evidence_hint=item.get("evidence_hint"),
            ).model_dump(mode="json")
        )
    return normalized


def _canonical_scoring_group_name(score_type: str) -> str:
    compact = _compact_text(score_type)
    if not compact:
        return "其他评分"
    if "评审方法" in compact or any(term in compact for term in ("综合评审法", "最低价法", "定标方式", "评审步骤")):
        return "评审方法"
    if any(term in compact for term in ("符合性评审", "符合性审查", "资格性审查")):
        return "符合性评审"
    if any(term in compact for term in ("技术评分", "技术评审")):
        return "技术评分"
    if any(term in compact for term in ("商务评分", "商务评审")):
        return "商务评分"
    if any(term in compact for term in ("价格评分", "价格评审", "报价评分", "报价得分", "价格分", "报价分")):
        return "价格评分"
    if "技术" in compact:
        return "技术评分"
    if any(term in compact for term in ("商务", "资信", "资质", "业绩")):
        return "商务评分"
    if any(term in compact for term in ("价格", "报价")):
        return "价格评分"
    return "其他评分"


def _looks_like_group_total_row(item: Dict[str, Any], group_name: str) -> bool:
    label = _compact_text(
        " ".join(
            str(part or "")
            for part in (
                item.get("score_type"),
                item.get("category"),
                item.get("item"),
                ((item.get("criteria") or {}) if isinstance(item.get("criteria"), dict) else {}).get("quote", ""),
            )
        )
    )
    if not label:
        return False
    if any(term in label for term in ("总分", "满分", "分值构成")):
        return True
    if label in {_compact_text(group_name), _compact_text(f"{group_name}总分")}:
        return True
    return False


def _build_scoring_overview(items: List[Any]) -> Dict[str, Any]:
    normalized_items = _normalize_scoring([item for item in items or [] if isinstance(item, dict)])
    deduped_items: List[Dict[str, Any]] = []
    seen_items: set[tuple[str, str, str, str]] = set()
    for item in normalized_items:
        key = (
            _compact_text(str(item.get("score_type") or "")),
            _compact_text(str(item.get("category") or "")),
            _compact_text(str(item.get("item") or "")),
            str(item.get("score") or ""),
        )
        if key in seen_items:
            continue
        seen_items.add(key)
        deduped_items.append(item)
    normalized_items = deduped_items
    if not normalized_items:
        return ScoringOverview().model_dump(mode="json")

    group_order = ("评审方法", "符合性评审", "技术评分", "商务评分", "价格评分", "其他评分")
    grouped: Dict[str, List[Dict[str, Any]]] = {name: [] for name in group_order}
    for item in normalized_items:
        criteria = item.get("criteria") if isinstance(item.get("criteria"), dict) else {}
        group_hint = " ".join(
            str(part or "")
            for part in (
                item.get("score_type"),
                item.get("category"),
                item.get("item"),
                criteria.get("quote") or criteria.get("value"),
            )
        )
        group_name = _canonical_scoring_group_name(group_hint)
        grouped.setdefault(group_name, []).append(item)

    groups: List[Dict[str, Any]] = []
    grand_total = 0.0
    has_grand_total = False
    for group_name in group_order:
        rows = grouped.get(group_name) or []
        if not rows:
            continue
        subtotal = 0.0
        has_subtotal = False
        for row in rows:
            score_value = row.get("score")
            if score_value in (None, "") or _looks_like_group_total_row(row, group_name):
                continue
            try:
                subtotal += float(score_value)
                has_subtotal = True
            except (TypeError, ValueError):
                continue
        group_payload = ScoringGroup(
            score_type=group_name,
            total_score=round(subtotal, 3) if has_subtotal else None,
            items=[ScoringCriterion.model_validate(row) for row in rows],
        ).model_dump(mode="json")
        groups.append(group_payload)
        if has_subtotal and group_name in {"技术评分", "商务评分", "价格评分", "其他评分"}:
            grand_total += subtotal
            has_grand_total = True

    overview = ScoringOverview(
        total_score=round(grand_total, 3) if has_grand_total else None,
        groups=[ScoringGroup.model_validate(group) for group in groups],
    )
    return overview.model_dump(mode="json")


def _normalize_invalidation(items: List[Any]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("anchor"), dict):
            normalized.append(item)
            continue
        normalized.append(
            InvalidationClause(
                condition=item.get("condition") or item.get("quote") or "",
                quote=item.get("quote") or item.get("condition") or "",
                anchor=_simple_anchor(item),
                level=_normalize_severity(item.get("level"), "P0"),
                category=item.get("category"),
            ).model_dump(mode="json")
        )
    return normalized


def _merge_simple_pricing(target: Dict[str, Any], items: List[Any]) -> Dict[str, Any]:
    merged = dict(target or {})
    for item in items or []:
        if not isinstance(item, dict):
            continue
        haystack = f"{item.get('name') or ''} {item.get('value') or ''} {item.get('quote') or ''}"
        atom = _simple_atom(item, "value", item.get("severity") or "P1").model_dump(mode="json")
        if any(word in haystack for word in ("最高限价", "预算", "控制价")) and not merged.get("highest_limit"):
            merged["highest_limit"] = atom
        elif any(word in haystack for word in ("报价方式", "报价要求", "报价形式")) and not merged.get("quotation_method"):
            merged["quotation_method"] = atom
        elif "税" in haystack:
            merged["tax_rules"] = _merge_lists(merged.get("tax_rules", []), [atom])
        elif any(word in haystack for word in ("异常报价", "低于", "高于", "0元")):
            merged["abnormal_price_rules"] = _merge_lists(merged.get("abnormal_price_rules", []), [atom])
        else:
            merged["price_components"] = _merge_lists(merged.get("price_components", []), [atom])
    return merged


def _merge_simple_deposit(target: Dict[str, Any], items: List[Any]) -> Dict[str, Any]:
    merged = dict(target or {})
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        value = str(item.get("value") or "")
        quote = str(item.get("quote") or "")
        haystack = f"{name} {value} {quote}"
        compact_name = _compact_text(name)
        compact_haystack = _compact_text(haystack)
        amount_match = _DEPOSIT_AMOUNT_RE.search(value) or _DEPOSIT_AMOUNT_RE.search(quote)
        atom = _simple_atom(item, "value", item.get("severity") or "P1").model_dump(mode="json")
        if any(word in compact_haystack for word in ("不予退还", "将被没收", "保证金没收", "没收保证金", "扣除保证金", "扣除")):
            merged["forfeiture_conditions"] = _merge_lists(merged.get("forfeiture_conditions", []), [atom])
        elif any(word in compact_haystack for word in ("退还", "返还")):
            merged["refund_conditions"] = _merge_lists(merged.get("refund_conditions", []), [atom])
        elif (
            any(word in compact_name for word in ("金额", "保证金金额"))
            or amount_match is not None
        ) and not merged.get("amount"):
            if amount_match is None:
                continue
            matched_amount = amount_match.group(0).strip()
            amount_item = dict(item)
            amount_item["value"] = matched_amount
            if not amount_item.get("quote"):
                amount_item["quote"] = quote or value or matched_amount
            merged["amount"] = _simple_atom(amount_item, "value", item.get("severity") or "P1").model_dump(mode="json")
        elif (
            any(word in compact_name for word in ("截止", "期限"))
            or (
                _extract_datetime_phrase(quote or value)
                and any(word in compact_haystack for word in ("保证金", "到账", "到帐", "递交", "提交", "缴纳", "截止"))
            )
        ) and not merged.get("payment_deadline"):
            merged["payment_deadline"] = atom
        elif any(word in compact_haystack for word in ("缴纳", "支付", "账户", "方式", "转账", "电汇", "汇款", "保函", "支票", "本票")) and not merged.get("payment_method"):
            merged["payment_method"] = atom
        else:
            merged.setdefault("required", atom)
    return merged


def _merge_simple_contract(target: Dict[str, Any], items: List[Any]) -> Dict[str, Any]:
    merged = dict(target or {})
    for item in items or []:
        if not isinstance(item, dict):
            continue
        haystack = f"{item.get('name') or ''} {item.get('value') or ''} {item.get('quote') or ''}"
        atom = _simple_atom(item, "value", item.get("severity") or "P1").model_dump(mode="json")
        if any(word in haystack for word in ("服务期", "服务期限", "合同期")) and not merged.get("service_period"):
            merged["service_period"] = atom
        elif "履约保证金" in haystack and not merged.get("performance_bond"):
            merged["performance_bond"] = atom
        elif "付款" in haystack:
            merged["payment_terms"] = _merge_lists(merged.get("payment_terms", []), [atom])
        elif "验收" in haystack:
            merged["acceptance_rules"] = _merge_lists(merged.get("acceptance_rules", []), [atom])
        elif any(word in haystack for word in ("违约", "赔偿", "扣罚", "处罚")):
            merged["penalty_clauses"] = _merge_lists(merged.get("penalty_clauses", []), [atom])
        else:
            merged["other_risks"] = _merge_lists(merged.get("other_risks", []), [atom])
    return merged


def _normalize_material_checklist(items: List[Any]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("requirement"), dict):
            normalized.append(item)
            continue
        payload = MaterialItem(
            name=item.get("name") or "",
            original=item.get("original"),
            copy_sealed=item.get("copy_sealed"),
            count=item.get("count"),
            required=bool(item.get("required", True)),
            requirement=_make_atom_from_simple_item(item, "P1"),
        ).model_dump(mode="json")
        if item.get("source_backed_composition"):
            payload["source_backed_composition"] = True
        normalized.append(payload)
    return normalized


def _material_semantic_key(name: str, quote: str = "") -> str:
    text = f"{name or ''}{quote or ''}"
    groups = [
        ("营业执照", ("营业执照", "三证合一")),
        ("劳务派遣经营许可证", ("劳务派遣经营许可证",)),
        ("人力资源服务许可证", ("人力资源服务许可证",)),
        ("开户许可证", ("开户许可证",)),
        ("企业信用报告", ("企业信用报告", "国家企业信用信息公示")),
        ("失信被执行人截图", ("失信被执行人",)),
        ("重大税收违法截图", ("重大税收违法",)),
        ("政府采购违法截图", ("政府采购严重违法",)),
        ("审计财务", ("审计报告", "财务报表")),
        ("授权书", ("授权书", "授权委托书")),
        ("身份证明", ("身份证明", "身份证")),
        ("业绩", ("业绩", "合同首尾页", "合同关键信息")),
        ("团队社保证明或劳务合同证明", ("同类服务专业团队", "专业团队", "劳务合同证明")),
        ("社保缴纳材料", ("社保", "社会保障")),
        ("资质证明", ("资质证明", "资质证书", "资格证书", "企业资质")),
        ("保证金登记", ("保证金登记表",)),
        ("银行账户", ("银行账户",)),
        ("中标承诺书", ("中标承诺书",)),
        ("反商业贿赂协议", ("反商业贿赂",)),
        ("保密协议", ("保密协议",)),
        ("安全生产协议", ("安全生产",)),
        ("投标报价", ("投标报价", "报价表", "报价单")),
        ("资格声明函", ("资格声明函", "资格申明函")),
        ("纳税证明", ("纳税", "缴税", "税收")),
    ]
    for key, aliases in groups:
        if any(alias in text for alias in aliases):
            return key
    return re.sub(r"\s+", "", text)[:32]


def _is_material_like_file_component(item: Dict[str, Any]) -> bool:
    requirement = item.get("requirement") if isinstance(item.get("requirement"), dict) else {}
    text = f"{item.get('name') or ''} {requirement.get('value') or ''} {requirement.get('quote') or ''}"
    if any(word in text for word in ("封面", "目录", "投标函", "基本情况介绍", "服务方案", "偏离表", "其他响应文件")):
        return False
    return any(
        word in text
        for word in (
            "证",
            "证明",
            "复印件",
            "截图",
            "报告",
            "报表",
            "许可证",
            "执照",
            "账户",
            "保证金",
            "承诺书",
            "协议",
            "声明函",
            "申明函",
            "授权书",
            "报价表",
            "报价单",
            "业绩",
            "社保",
            "劳务合同",
        )
    )


def _ensure_materials_from_file_composition(merged: Dict[str, Any]) -> None:
    materials = list(merged.get("material_checklist") or [])
    seen = {
        _material_semantic_key(
            str(item.get("name") or ""),
            str(((item.get("requirement") or {}) if isinstance(item, dict) else {}).get("quote") or ""),
        )
        for item in materials
        if isinstance(item, dict)
    }
    for item in merged.get("file_composition") or []:
        if not isinstance(item, dict) or not _is_material_like_file_component(item):
            continue
        requirement = item.get("requirement") if isinstance(item.get("requirement"), dict) else {}
        key = _material_semantic_key(str(item.get("name") or ""), str(requirement.get("quote") or ""))
        if key in seen:
            continue
        seen.add(key)
        materials.append(
            MaterialItem(
                name=item.get("name") or str(requirement.get("value") or ""),
                required=bool(item.get("required", True)),
                requirement=RequirementAtom.model_validate(requirement or {}),
            ).model_dump(mode="json")
        )
    merged["material_checklist"] = materials


def _ensure_base_info_from_timeline(merged: Dict[str, Any]) -> None:
    base_info = merged.get("base_info")
    timeline = merged.get("timeline")
    if not isinstance(base_info, dict) or not isinstance(timeline, list):
        return

    def normalize_time_atom(value: Any) -> Any:
        if isinstance(value, dict) and "value" in value:
            inner_value = value.get("value")
            if isinstance(inner_value, dict) and "value" in inner_value:
                value = inner_value
            return {
                "value": value.get("value"),
                "quote": value.get("quote") or str(value.get("value") or ""),
                "anchor": value.get("anchor"),
                "severity": value.get("severity") or "P1",
            }
        return value

    def pick_time(name_keywords: Tuple[str, ...], exclude_keywords: Tuple[str, ...] = ()) -> Any:
        # Later timeline rows are often anchored to the precise section, while
        # earlier rows may come from head_text hints. Prefer the precise row.
        for item in reversed(timeline):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("action") or "")
            if not all(keyword in name for keyword in name_keywords):
                continue
            if exclude_keywords and any(keyword in name for keyword in exclude_keywords):
                continue
            value = item.get("time")
            if not _is_empty_value(value):
                return normalize_time_atom(value)
        return None

    if _is_empty_value(base_info.get("submission_deadline")):
        # base_info feeds the frontend summary, while timeline often captures
        # the same deadline more reliably. Keep the two views in sync.
        deadline = (
            pick_time(("递交", "截止"))
            or pick_time(("提交", "截止"))
            or pick_time(("响应文件", "递交"))
        )
        if not _is_empty_value(deadline):
            base_info["submission_deadline"] = deadline

    if _is_empty_value(base_info.get("bid_open_time")):
        bid_open = pick_time(("开标",), exclude_keywords=("提交", "递交"))
        if not _is_empty_value(bid_open):
            base_info["bid_open_time"] = bid_open


def _merge_requirement_payloads(payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
    merged = TenderRequirements().model_dump(mode="json")
    list_fields = {
        "file_composition",
        "format_requirements",
        "qualifications",
        "scoring",
        "invalidation",
        "material_checklist",
        "timeline",
        "technical_requirements",
        "bidder_special_requirements",
    }

    for payload in payloads:
        if not payload:
            continue
        if payload.get("document_type") and merged.get("document_type") == "其他":
            merged["document_type"] = payload["document_type"]
        for key, value in payload.items():
            if key == "document_type" or _is_empty_value(value):
                continue
            if key == "base_info_items":
                merged["base_info"] = _merge_objects(
                    merged.get("base_info", {}),
                    _normalize_base_info_items(value or []),
                )
                continue
            if key == "file_composition":
                value = _normalize_file_composition(value or [])
            if key == "format_requirements":
                value = _normalize_format_requirements(value or [])
            if key == "qualifications":
                value = _normalize_qualifications(value or [])
            if key == "material_checklist":
                value = _normalize_material_checklist(value or [])
            if key == "technical_requirements":
                value = _normalize_technical_requirements(value or [])
            if key == "scoring":
                value = _normalize_scoring(value or [])
            if key == "invalidation":
                value = _normalize_invalidation(value or [])
            if key == "timeline":
                value = _normalize_timeline(value or [])
            if key == "pricing_requirements":
                merged["pricing"] = _merge_simple_pricing(merged.get("pricing", {}), value or [])
                continue
            if key == "deposit_requirements":
                merged["deposit"] = _merge_simple_deposit(merged.get("deposit", {}), value or [])
                continue
            if key == "contract_requirements":
                merged["contract"] = _merge_simple_contract(merged.get("contract", {}), value or [])
                continue
            if key in list_fields:
                merged[key] = _merge_lists(merged.get(key, []), value or [])
            elif isinstance(value, dict):
                merged[key] = _merge_objects(merged.get(key, {}), value)
            else:
                if _is_empty_value(merged.get(key)):
                    merged[key] = value
    _ensure_materials_from_file_composition(merged)
    _ensure_base_info_from_timeline(merged)
    merged["scoring_overview"] = _build_scoring_overview(merged.get("scoring") or [])
    return TenderRequirements.model_validate(_coerce_atom_fields(merged)).model_dump(mode="json")
