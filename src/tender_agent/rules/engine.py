from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

RULES_DIR = Path(__file__).resolve().parent

def _normalize_text(issue: Dict[str, Any]) -> str:
    return " ".join([str(issue.get("type", "")), str(issue.get("message", "")), str(issue.get("node_name", ""))]).lower()

def load_rules(version: str = "v1") -> Dict[str, Any]:
    path = RULES_DIR / f"risk_rules_{version}.json"
    if not path.exists():
        path = RULES_DIR / "risk_rules_v1.json"
    return json.loads(path.read_text(encoding="utf-8-sig"))

def match_rule(issue: Dict[str, Any], ruleset: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    text = _normalize_text(issue)
    issue_type = str(issue.get("type", ""))
    for rule in ruleset.get("rules", []):
        types = set(rule.get("match_types", []))
        if types and issue_type in types:
            return rule
        kws = [str(k).lower() for k in rule.get("match_keywords", [])]
        if kws and any(k in text for k in kws):
            return rule
    return None

def enrich_issue(issue: Dict[str, Any], ruleset: Dict[str, Any]) -> Dict[str, Any]:
    rule = match_rule(issue, ruleset)
    enriched = dict(issue)
    if not rule:
        enriched.setdefault("category", "format")
        enriched.setdefault("severity", "P2")
        enriched.setdefault("fatal", False)
        enriched.setdefault("owner", "商务")
        enriched.setdefault("suggestion", "按招标要求补齐内容并复检。")
        return enriched
    enriched["rule_id"] = rule.get("id")
    enriched["rule_name"] = rule.get("name")
    enriched["category"] = rule.get("category", "format")
    enriched["severity"] = rule.get("severity", "P2")
    enriched["fatal"] = bool(rule.get("fatal", False))
    enriched["owner"] = rule.get("owner", "商务")
    enriched["suggestion"] = rule.get("suggestion", "")
    return enriched

def summarize_categories(issues: List[Dict[str, Any]]) -> Dict[str, int]:
    stats: Dict[str, int] = {}
    for i in issues:
        c = str(i.get("category", "format"))
        stats[c] = stats.get(c, 0) + 1
    return stats
