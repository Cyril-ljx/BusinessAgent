"""Rendering policy for certificate-like materials."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict


DEFAULT_POLICY = {
    "certificate_category_caps": {
        "营业执照": 1,
        "劳务派遣经营许可证": 1,
        "人力资源服务许可证": 1,
        "基本存款账户信息": 1,
        "审计报告": 12,
        "ISO认证体系证书": 1,
        "企业荣誉": 2,
        "企业纳税等级": 1,
        "一般纳税人认定证明": 1,
        "项目人员证书": 3,
        "合作业绩": 3,
        "项目奖项": 2,
    },
    "default_certificate_cap": 3,
    "no_item_heading_categories": ["审计报告", "合作业绩"],
    "open_collection_markers": ["其他", "其它", "等", "资质", "资格", "荣誉", "证书"],
    "supporting_headings": {
        "项目人员证书": "项目人员资质证明材料",
    },
    "performance_heading": {
        "markers": ["同类", "近3年", "近三年"],
        "matched": "同类业绩证明材料",
        "default": "业绩证明材料",
    },
}


@lru_cache(maxsize=1)
def load_certificate_rendering_policy() -> Dict[str, Any]:
    policy = _deep_copy_policy(DEFAULT_POLICY)
    path = Path(__file__).resolve().parents[1] / "rules" / "rendering_policy_v1.json"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return policy
    if isinstance(loaded, dict):
        _merge_policy(policy, loaded)
    return policy


def cap_certificate_count(category: str, requested: int) -> int:
    policy = load_certificate_rendering_policy()
    caps = _dict_value(policy, "certificate_category_caps")
    default_cap = _positive_int(policy.get("default_certificate_cap"), 3)
    cap = _positive_int(caps.get(category), default_cap)
    return max(1, min(requested, cap))


def supporting_certificate_heading(node_name: str, category: str) -> str:
    policy = load_certificate_rendering_policy()
    compact = re.sub(r"\s+", "", str(node_name or ""))
    if category == "合作业绩":
        config = _dict_value(policy, "performance_heading")
        markers = _list_value(config, "markers")
        matched = str(config.get("matched") or "同类业绩证明材料")
        default = str(config.get("default") or "业绩证明材料")
        return matched if any(marker in compact for marker in markers) else default
    configured = _dict_value(policy, "supporting_headings").get(category)
    return str(configured or category)


def certificate_item_heading_level(node: Dict[str, Any], category: str, max_count: int, level: int) -> int:
    policy = load_certificate_rendering_policy()
    if category in set(_list_value(policy, "no_item_heading_categories")):
        return 0
    node_name = re.sub(r"\s+", "", str(node.get("name") or ""))
    category_name = re.sub(r"\s+", "", str(category or ""))
    if not node_name or not category_name:
        return 0

    markers = _list_value(policy, "open_collection_markers")
    open_collection = any(marker in node_name for marker in markers)
    exact_single = category_name in node_name and len(node_name) <= len(category_name) + 4 and max_count <= 1
    if exact_single and not open_collection:
        return 0
    if open_collection or max_count > 1 or category_name not in node_name:
        return min(level + 1, 3)
    return 0


def _merge_policy(base: Dict[str, Any], incoming: Dict[str, Any]) -> None:
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key].update(value)
        elif value is not None:
            base[key] = value


def _deep_copy_policy(policy: Dict[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(policy, ensure_ascii=False))


def _dict_value(data: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _list_value(data: Dict[str, Any], key: str) -> list[str]:
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else fallback
    except (TypeError, ValueError):
        return fallback
