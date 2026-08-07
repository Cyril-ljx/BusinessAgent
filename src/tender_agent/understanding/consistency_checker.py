import re
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, List

_NUM_PAT = re.compile(
    r"(报价|工期|人数|人员数量|服务期限|合同期限)\s*[:：]?\s*(\d+(?:\.\d+)?)"
    r"\s*(?:万元|元|天|月|年|人)?"
)
COMPANY_PAT = re.compile(r"(有限公司|股份有限公司|集团)")
PROJECT_NO_PAT = re.compile(r"([A-Z]{2,}-?[A-Z0-9-]{4,})")
DATE_PAT = re.compile(r"(20\d{2})[年\-/](\d{1,2})[月\-/](\d{1,2})")
PERSON_PAT = re.compile(r"(项目经理|技术负责人|法定代表人)[:：]\s*([\u4e00-\u9fa5]{2,4})")
DATE_LABELS = {
    "submission_deadline": ("投标截止", "响应截止", "报价截止", "递交截止", "提交截止"),
    "bid_open_time": ("开标时间", "开标", "响应开启", "开启时间"),
    "award_time": ("中标通知", "中选通知", "成交通知", "定标"),
    "service_start": ("服务开始", "履约开始", "合同开始", "进场时间", "进场日期"),
}


def _collect_text(generated: Dict[str, str]) -> str:
    return "\n".join([v or "" for v in generated.values()])


def _parse_date_match(match: re.Match[str]) -> date | None:
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3))).date()
    except ValueError:
        return None


def _dates_from_value(value: Any) -> List[date]:
    text = str(value or "")
    return [parsed for match in DATE_PAT.finditer(text) if (parsed := _parse_date_match(match))]


def _labeled_date_occurrences(
    generated: Dict[str, str],
    node_name_map: Dict[str, str],
) -> Dict[str, List[Dict[str, Any]]]:
    result: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for node_id, text in generated.items():
        node_text = str(text or "")
        for match in DATE_PAT.finditer(node_text):
            parsed = _parse_date_match(match)
            if parsed is None:
                continue
            context_start = max(0, match.start() - 32)
            context_end = min(len(node_text), match.end() + 16)
            context = node_text[context_start:context_end]
            before_date = node_text[context_start:match.start()]
            label_positions = {
                field: max((before_date.rfind(label) for label in labels), default=-1)
                for field, labels in DATE_LABELS.items()
            }
            field = max(label_positions, key=label_positions.get)
            if label_positions[field] < 0:
                continue
            result[field].append(
                {
                    "node_id": str(node_id),
                    "node_name": node_name_map.get(str(node_id), str(node_id)),
                    "value": parsed,
                    "snippet": context,
                }
            )
    return result


def _date_relation_conflicts(
    generated: Dict[str, str],
    project_facts: Dict[str, Any],
    node_name_map: Dict[str, str],
) -> List[Dict[str, Any]]:
    conflicts: List[Dict[str, Any]] = []
    occurrences = _labeled_date_occurrences(generated, node_name_map)

    for field in ("submission_deadline", "bid_open_time"):
        locked_dates = _dates_from_value(project_facts.get(field))
        if not locked_dates:
            continue
        locked = locked_dates[0]
        mismatches = [row for row in occurrences.get(field, []) if row["value"] != locked]
        if mismatches:
            conflicts.append(
                {
                    "fact": f"项目日期不一致:{field}",
                    "values": [locked.isoformat()] + sorted({row["value"].isoformat() for row in mismatches}),
                    "occurrences": [
                        {**row, "value": row["value"].isoformat()} for row in mismatches[:8]
                    ],
                }
            )

    def first_date(field: str) -> date | None:
        locked = _dates_from_value(project_facts.get(field))
        if locked:
            return locked[0]
        rows = occurrences.get(field) or []
        return rows[0]["value"] if rows else None

    submission = first_date("submission_deadline")
    opening = first_date("bid_open_time")
    if submission and opening and opening < submission:
        conflicts.append(
            {
                "fact": "日期顺序:开标早于投标截止",
                "values": [submission.isoformat(), opening.isoformat()],
                "occurrences": [],
            }
        )

    award = first_date("award_time")
    service_start = first_date("service_start")
    if award and service_start and service_start < award:
        conflicts.append(
            {
                "fact": "日期顺序:服务开始早于中标",
                "values": [award.isoformat(), service_start.isoformat()],
                "occurrences": [],
            }
        )
    return conflicts


def check_consistency(state: Dict[str, Any]) -> Dict[str, Any]:
    generated = state.get("generated_sections") or {}
    compliance_report = state.get("compliance_report") or {}
    node_name_map = compliance_report.get("node_name_map") or {}

    facts: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for node_id, text in generated.items():
        node_text = text or ""
        for m in _NUM_PAT.finditer(node_text):
            key = m.group(1)
            val = m.group(2)
            facts[key].append(
                {
                    "node_id": node_id,
                    "node_name": node_name_map.get(str(node_id), str(node_id)),
                    "value": val,
                    "snippet": node_text[max(m.start() - 20, 0) : min(m.end() + 40, len(node_text))],
                }
            )

    conflicts = []
    for key, rows in facts.items():
        uniq = sorted({r["value"] for r in rows})
        if len(uniq) > 1:
            conflicts.append({"fact": key, "values": uniq, "occurrences": rows[:8]})

    full_text = _collect_text(generated)

    # 公司名称一致性（简化：按“有限公司/集团”所在句抽样）
    company_lines = [ln.strip() for ln in full_text.splitlines() if COMPANY_PAT.search(ln)]
    company_uniq = sorted(set(company_lines[:20]))
    if len(company_uniq) > 1:
        conflicts.append({"fact": "公司名称", "values": company_uniq[:5], "occurrences": []})

    # 项目编号一致性
    proj_nos = PROJECT_NO_PAT.findall(full_text)
    proj_uniq = sorted(set(proj_nos))
    if len(proj_uniq) > 1:
        conflicts.append({"fact": "项目编号", "values": proj_uniq[:8], "occurrences": []})

    # Future tender dates are normal. Only report contradictions against locked
    # project facts or impossible event ordering.
    conflicts.extend(
        _date_relation_conflicts(
            generated,
            state.get("project_facts") or {},
            node_name_map,
        )
    )

    # 人员重复冲突（同角色多姓名）
    role_map: Dict[str, set[str]] = defaultdict(set)
    for role, name in PERSON_PAT.findall(full_text):
        role_map[role].add(name)
    for role, names in role_map.items():
        if len(names) > 1:
            conflicts.append({"fact": f"人员角色冲突:{role}", "values": sorted(names), "occurrences": []})

    report = {
        "passed": len(conflicts) == 0,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
    }
    return {"consistency_report": report}
