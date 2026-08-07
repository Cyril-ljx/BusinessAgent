import asyncio
import json
import os
import re
from typing import Any, Dict, List, Tuple

from loguru import logger
from pydantic import BaseModel, Field

from ..config.settings import settings
from ..llm.gateway import llm_gateway
from .truthfulness import TRUTHFULNESS_RULES


class SectionDraft(BaseModel):
    content: str = Field(default="")


class BatchSectionDraftItem(BaseModel):
    node_id: str
    content: str = Field(default="")


class BatchSectionDraft(BaseModel):
    sections: List[BatchSectionDraftItem] = Field(default_factory=list)


def _format_exception(exc: Exception, timeout_sec: int | None = None) -> str:
    """Give user-facing warnings a useful reason; TimeoutError has an empty str()."""
    if isinstance(exc, asyncio.TimeoutError):
        return f"LLM调用超时{f'({timeout_sec}s)' if timeout_sec else ''}"
    message = str(exc).strip()
    if message:
        return message[:160]
    return type(exc).__name__


async def _with_optional_timeout(coro, timeout_sec: int | None):
    """timeout_sec <= 0 means wait without an application-level timeout."""
    if timeout_sec is None or timeout_sec <= 0:
        return await coro
    return await asyncio.wait_for(coro, timeout=timeout_sec)


def _chapter_type(name: str) -> str:
    n = name or ""
    if any(k in n for k in ["资质", "证书", "执照", "许可"]):
        return "qualification"
    if any(k in n for k in ["报价", "价格", "费用", "工期"]):
        return "quotation"
    if any(k in n for k in ["承诺", "声明", "保证", "函"]):
        return "commitment"
    return "technical"


def _norm_name(name: str) -> str:
    return "".join((name or "").split())


def _is_front_chapter(name: str) -> bool:
    n = _norm_name(name)
    return n in {"封面", "投标文件封面", "响应文件封面", "目录", "投标文件目录", "响应文件目录"}


def _assignment_map(assignments: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    mapping: Dict[str, List[Dict[str, Any]]] = {}
    for item in assignments or []:
        node_id = str(item.get("node_id", "") or item.get("outline_node_id", "")).strip()
        if not node_id:
            continue
        materials = item.get("materials") or []
        if isinstance(materials, list):
            mapping[node_id] = [m for m in materials if isinstance(m, dict)]
    return mapping


def _has_structured_material(materials: List[Dict[str, Any]]) -> bool:
    for material in materials or []:
        source = str(material.get("source") or "")
        if source == "knowledge_certificate":
            source = "certificate"
        elif source == "knowledge_tech_section":
            source = "tech_section"
        if source == "certificate":
            return True
        if source == "tech_section" and (
            "." in str(material.get("chapter_id") or "") or bool(material.get("copy_full_section"))
        ):
            return True
        if source == "tech_section_range":
            return True
        if source == "tender_template":
            return True
    return False


def _first_template_material(materials: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    for material in materials or []:
        if str(material.get("source") or "") == "tender_template":
            return material
    return None


def _template_tokens(text: str) -> set[str]:
    compact = _norm_name(text)
    if not compact:
        return set()
    compact = re.sub(r"[（(].*?[）)]", "", compact)
    compact = re.sub(r"附件[一二三四五六七八九十\d]+(?:[-－—]\d+)?", "", compact)
    parts = re.split(r"[、，,；;：:/和与及]", compact)
    tokens = {part.strip() for part in parts if 2 <= len(part.strip()) <= 24}
    if 2 <= len(compact) <= 24:
        tokens.add(compact)
    return {token for token in tokens if token}


def _requirement_anchor(item: Dict[str, Any]) -> Dict[str, Any]:
    anchor = item.get("anchor")
    if isinstance(anchor, dict):
        return anchor
    requirement = item.get("requirement")
    if isinstance(requirement, dict):
        requirement_anchor = requirement.get("anchor")
        if isinstance(requirement_anchor, dict):
            return requirement_anchor
    return {}


def _template_requirement_items(tender_requirements: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    rows: List[Tuple[str, Dict[str, Any]]] = []
    for field in ("file_composition", "format_requirements", "material_checklist"):
        for item in tender_requirements.get(field) or []:
            if isinstance(item, dict):
                rows.append((field, item))
    return rows


def _template_requirement_text(item: Dict[str, Any]) -> str:
    parts = [
        str(item.get("name") or ""),
        str(item.get("quote") or ""),
        str(item.get("template_ref") or ""),
        str(item.get("section_title") or ""),
    ]
    requirement = item.get("requirement")
    if isinstance(requirement, dict):
        parts.extend([str(requirement.get("value") or ""), str(requirement.get("quote") or "")])
    anchor = _requirement_anchor(item)
    if anchor:
        parts.extend([str(anchor.get("section_title") or ""), str(anchor.get("section_id") or "")])
    return " ".join(part for part in parts if part)


def _template_requirement_score(node_name: str, field: str, item: Dict[str, Any]) -> int:
    node_norm = _norm_name(node_name)
    text = _template_requirement_text(item)
    text_norm = _norm_name(text)
    if not node_norm or not text_norm:
        return 0
    score = 0
    name_norm = _norm_name(str(item.get("name") or ""))
    quote_norm = _norm_name(str(item.get("quote") or ""))
    if name_norm and node_norm == name_norm:
        score += 20
    if node_norm in text_norm:
        score += 12
    if name_norm and name_norm in node_norm:
        score += 8
    if quote_norm and quote_norm in node_norm:
        score += 6
    overlap = _template_tokens(node_name) & _template_tokens(text)
    score += len(overlap) * 4
    if item.get("template_ref"):
        score += 3
    if field == "format_requirements":
        score += 2
    if any(term in text for term in ("范本", "格式", "附件", "模板")):
        score += 2
    return score


def _best_template_requirement(
    node_name: str,
    tender_requirements: Dict[str, Any],
) -> Dict[str, Any] | None:
    best_item: Dict[str, Any] | None = None
    best_score = 0
    for field, item in _template_requirement_items(tender_requirements):
        score = _template_requirement_score(node_name, field, item)
        if score > best_score:
            best_score = score
            best_item = item
    if best_score < 6:
        return None
    return best_item


def _find_located_section_for_template(
    item: Dict[str, Any],
    located_sections: List[Dict[str, Any]],
) -> Dict[str, Any] | None:
    anchor = _requirement_anchor(item)
    section_id = str(item.get("section_id") or anchor.get("section_id") or "").strip()
    section_title = str(item.get("section_title") or anchor.get("section_title") or "").strip()
    if section_id:
        for section in located_sections:
            if str(section.get("section_id") or "").strip() == section_id:
                return section
    title_norm = _norm_name(section_title)
    if title_norm:
        for section in located_sections:
            candidate_title = _norm_name(str(section.get("title") or section.get("section_title") or ""))
            if candidate_title == title_norm or (title_norm and title_norm in candidate_title):
                return section
    return None


def _find_template_line_index(lines: List[str], search_terms: List[str]) -> int | None:
    best_idx: int | None = None
    best_score = 0
    normalized_terms = [_norm_name(term) for term in search_terms if _norm_name(term)]
    for idx, line in enumerate(lines):
        normalized_line = _norm_name(line)
        if not normalized_line:
            continue
        score = 0
        for term in normalized_terms:
            if normalized_line == term:
                score += 8
            elif term in normalized_line:
                score += 5
            elif normalized_line in term:
                score += 2
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx


def _looks_like_template_boundary(line: str, search_terms: List[str]) -> bool:
    text = str(line or "").strip()
    if not text:
        return False
    normalized = _norm_name(text)
    search_norms = {_norm_name(term) for term in search_terms if _norm_name(term)}
    if normalized in search_norms:
        return False
    if re.match(r"^第[一二三四五六七八九十\d]+[章节部分]", text):
        return True
    if re.match(r"^附件[一二三四五六七八九十\d]+", text):
        return True
    if re.match(r"^[（(]?[一二三四五六七八九十\d]+[）).、．]\s*", text) and len(text) <= 28:
        return True
    if len(text) <= 24 and re.search(r"(函|书|表|单|声明|承诺|证明|协议|附录)$", text):
        return True
    return False


def _extract_template_excerpt(
    node_name: str,
    requirement_item: Dict[str, Any] | None,
    located_section: Dict[str, Any] | None,
) -> str:
    quote = ""
    template_ref = ""
    if requirement_item:
        quote = str(
            requirement_item.get("quote")
            or _atom_value(requirement_item.get("requirement"), "quote")
            or ""
        ).strip()
        template_ref = str(requirement_item.get("template_ref") or "").strip()
    if not located_section:
        return quote

    content = str(located_section.get("content") or "").strip()
    if not content:
        return quote

    lines = [re.sub(r"\s+", " ", raw).strip() for raw in content.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return quote

    search_terms = [node_name, quote, template_ref]
    if requirement_item:
        search_terms.extend(
            [
                str(requirement_item.get("name") or ""),
                str(requirement_item.get("section_title") or ""),
            ]
        )
    start_idx = _find_template_line_index(lines, search_terms)
    if start_idx is None:
        return quote

    if start_idx > 0 and re.match(r"^附件[一二三四五六七八九十\d]+", lines[start_idx - 1]):
        start_idx -= 1

    excerpt_lines: List[str] = []
    non_empty_count = 0
    for idx in range(start_idx, len(lines)):
        line = lines[idx]
        if idx > start_idx + 1 and _looks_like_template_boundary(line, search_terms):
            break
        excerpt_lines.append(line)
        non_empty_count += 1
        if non_empty_count >= 18:
            break

    excerpt = "\n".join(excerpt_lines).strip()
    if quote and quote not in excerpt and len(quote) > len(excerpt):
        return quote
    return excerpt or quote


def _template_material_anchor_item(material: Dict[str, Any]) -> Dict[str, Any]:
    source_anchor = str(material.get("source_anchor") or "").strip()
    source_section_id = str(material.get("source_section_id") or "").strip()
    if not source_anchor and not source_section_id:
        return {}
    anchor = {}
    if source_section_id:
        anchor["section_id"] = source_section_id
    return {
        "name": material.get("name") or source_anchor,
        "quote": source_anchor or str(material.get("name") or ""),
        "section_id": source_section_id,
        "anchor": anchor,
    }


def _build_template_generated_sections(
    leaves: List[Tuple[str, str]],
    assignments: Dict[str, List[Dict[str, Any]]],
    tender_requirements: Dict[str, Any],
    located_sections: List[Dict[str, Any]],
) -> Tuple[Dict[str, str], List[str]]:
    generated: Dict[str, str] = {}
    warnings: List[str] = []
    for node_id, node_name in leaves:
        template_material = _first_template_material(assignments.get(node_id, []))
        if not template_material:
            continue
        material_item = _template_material_anchor_item(template_material)
        requirement_item = material_item or _best_template_requirement(node_name, tender_requirements)
        located_section = _find_located_section_for_template(requirement_item or {}, located_sections)
        excerpt = _extract_template_excerpt(node_name, requirement_item, located_section)
        if not excerpt and material_item:
            requirement_item = _best_template_requirement(node_name, tender_requirements)
            located_section = _find_located_section_for_template(requirement_item or {}, located_sections)
            excerpt = _extract_template_excerpt(node_name, requirement_item, located_section)
        if excerpt:
            generated[node_id] = _sanitize_generated_text(excerpt)
            continue
        note = str(template_material.get("note") or "未能定位原文范本，请人工补充本章节").strip()
        generated[node_id] = f"[{note}]"
        warnings.append(f"[content] {node_id} 未定位到原文范本，已回退为明确占位提示")
    return generated, warnings


def _style_instruction(chapter_type: str) -> str:
    mapping = {
        "qualification": "以清单式写法，逐条引用素材事实（名称/编号/有效期）。",
        "quotation": "以结构化写法，说明口径与边界，不得虚构数字。",
        "commitment": "以正式法律文风写作，措辞严谨、边界清晰。",
        "technical": "以方案文风写作，先目标后方法，再落地措施。",
    }
    return mapping.get(chapter_type, mapping["technical"])


def _facts_text(material_facts: List[Dict[str, Any]]) -> str:
    if not material_facts:
        return "[]"
    return json.dumps(material_facts, ensure_ascii=False, indent=2)


def _requirements_text(requirements_context: Dict[str, Any]) -> str:
    if not requirements_context:
        return "无明确结构化要求。"
    lines = []
    for field, value in requirements_context.items():
        summary = _summarize_requirement_value(value, limit=8)
        if summary:
            lines.append(f"- {_requirement_field_label(field)}: {summary}")
    return "\n".join(lines) if lines else "无明确结构化要求。"


def _match_requirements_for_chapter(
    node_name: str,
    tender_requirements: Dict[str, Any],
    limit: int = 12,
) -> Dict[str, Any]:
    if not tender_requirements:
        return {}
    name = _norm_name(node_name)
    fields = _chapter_requirement_fields(name)
    matched: Dict[str, Any] = {}
    for field in fields:
        value = tender_requirements.get(field)
        if not value:
            continue
        if isinstance(value, list):
            items = _filter_requirement_items_by_chapter(name, field, value, limit)
            if items:
                matched[field] = items
        elif isinstance(value, dict):
            compact = _compact_requirement_object(value)
            if compact:
                matched[field] = compact
    return matched


def _atom_fact_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value if value not in (None, "") else None
    atom_value = value.get("value")
    if atom_value not in (None, "", [], {}):
        return atom_value
    quote = str(value.get("quote") or "").strip()
    return quote or None


def _build_locked_project_facts(state: Dict[str, Any], tender_requirements: Dict[str, Any]) -> Dict[str, Any]:
    base_info = tender_requirements.get("base_info") or {}
    facts: Dict[str, Any] = {}
    for key in (
        "project_name",
        "tender_no",
        "purchaser",
        "agency",
        "submission_deadline",
        "bid_open_time",
        "bid_validity_period",
    ):
        value = _atom_fact_value(base_info.get(key))
        if value not in (None, "", [], {}):
            facts[key] = value

    title_info = state.get("title_info") or {}
    if not facts.get("project_name") and title_info.get("project_name"):
        facts["project_name"] = title_info["project_name"]
    if state.get("company_name"):
        facts["bidder_company"] = state["company_name"]
    return facts


def _chapter_requirement_fields(name: str) -> List[str]:
    fields: List[str] = []
    if any(
        k in name
        for k in (
            "技术",
            "服务方案",
            "服务保障",
            "24小时服务",
            "项目专员",
            "人员配置",
            "人员补充",
            "业务指令",
            "作业方案",
            "质量控制",
            "安全生产",
            "KPI",
            "风险管控",
            "应急",
            "抗风险",
        )
    ):
        fields.extend(["technical_requirements", "scoring", "contract"])
    if any(k in name for k in ("评分", "评审", "商务技术")):
        fields.extend(["scoring", "technical_requirements"])
    if any(k in name for k in ("资格", "资质", "证照", "证明", "执照", "许可", "信用", "失信", "社保", "纳税", "业绩", "审计", "财务")):
        fields.extend(["qualifications", "material_checklist", "file_composition", "format_requirements"])
    if any(k in name for k in ("银行账户", "账户信息")):
        fields.extend(["material_checklist", "file_composition"])
    if any(k in name for k in ("报价", "价格", "费用")):
        fields.extend(["pricing", "invalidation", "file_composition"])
    if "保证金" in name:
        fields.extend(["deposit", "invalidation"])
    if any(k in name for k in ("承诺", "声明", "协议", "授权", "函")):
        fields.extend(["file_composition", "format_requirements", "material_checklist", "invalidation"])
    if any(k in name for k in ("密封", "编制", "递交", "目录", "封面", "签字", "盖章", "装订", "正副本")):
        fields.extend(["format_requirements", "timeline", "invalidation"])
    if "偏离" in name:
        fields.extend(["format_requirements", "technical_requirements", "scoring"])
    if "其他响应" in name:
        fields.extend(["file_composition", "material_checklist"])
    deduped: List[str] = []
    for field in fields:
        if field not in deduped:
            deduped.append(field)
    return deduped


def _filter_requirement_items_by_chapter(
    chapter_name: str,
    field: str,
    items: List[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    scored: List[Tuple[int, Dict[str, Any]]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        text = _requirement_item_search_text(item)
        score = _requirement_match_score(chapter_name, text, field, item)
        if score <= 0:
            continue
        scored.append((score, _compact_requirement_item(item)))
    scored.sort(key=lambda row: row[0], reverse=True)
    return [item for _, item in scored[:limit]]


def _requirement_match_score(chapter_name: str, text: str, field: str, item: Dict[str, Any]) -> int:
    score = 0
    if _norm_name(chapter_name) and _norm_name(chapter_name) in _norm_name(text):
        score += 8
    keyword_groups = (
        ("社保", ("社保", "社会保障", "劳务合同")),
        ("业绩", ("业绩", "合同证明")),
        ("财务", ("财务", "审计", "资信")),
        ("信用", ("信用", "失信", "违法")),
        ("资质", ("资质", "许可证", "营业执照", "证照")),
        ("报价", ("报价", "价格", "限价", "预算")),
        ("保证金", ("保证金",)),
        ("服务", ("服务", "技术", "作业", "人员", "质量", "安全")),
        ("偏离", ("偏离",)),
        ("授权", ("授权", "法定代表人", "身份证")),
    )
    for chapter_key, req_keys in keyword_groups:
        if chapter_key in chapter_name and any(req_key in text for req_key in req_keys):
            score += 5
    severity = str(item.get("level") or _atom_value(item.get("requirement"), "severity") or _atom_value(item.get("required_value"), "severity") or "")
    if severity in {"P0", "P1"}:
        score += 2
    if field in {"technical_requirements", "scoring"} and any(k in chapter_name for k in ("技术", "服务", "方案")):
        score += 3
    if field in {"material_checklist", "qualifications"} and any(k in chapter_name for k in ("资格", "资质", "证明", "材料")):
        score += 3
    return score


def _requirement_item_search_text(item: Dict[str, Any]) -> str:
    parts = []
    for key in ("name", "condition", "item", "category", "evidence_hint", "response_hint", "quote"):
        if item.get(key):
            parts.append(str(item.get(key)))
    for key in ("requirement", "required_value", "criteria", "time"):
        value = item.get(key)
        if isinstance(value, dict):
            parts.append(str(value.get("value") or ""))
            parts.append(str(value.get("quote") or ""))
    return " ".join(parts)


def _atom_value(atom: Any, key: str) -> Any:
    if isinstance(atom, dict):
        return atom.get(key)
    return None


def _compact_requirement_object(value: Dict[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {}
    for key, item in (value or {}).items():
        if item in (None, "", [], {}):
            continue
        if isinstance(item, list):
            compact[key] = [_compact_requirement_item(v) for v in item[:8] if isinstance(v, dict)]
        elif isinstance(item, dict):
            compact[key] = _compact_requirement_item(item)
        else:
            compact[key] = item
    return compact


def _compact_requirement_item(item: Dict[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {}
    for key in ("name", "condition", "item", "category", "mandatory", "required", "level", "evidence_hint", "response_hint"):
        if item.get(key) not in (None, "", [], {}):
            compact[key] = item.get(key)
    for atom_key in ("requirement", "required_value", "criteria", "time"):
        atom = item.get(atom_key)
        if isinstance(atom, dict):
            compact[atom_key] = {
                k: atom.get(k)
                for k in ("value", "quote", "severity")
                if atom.get(k) not in (None, "")
            }
    if item.get("quote"):
        compact["quote"] = item.get("quote")
    return compact


_BASE_PROMPT = """你是投标文件写作助手。

{truthfulness}

章节名称: {chapter_name}
章节编号: {chapter_id}
章节类型: {chapter_type}
写作风格: {style_instruction}
全项目锁定事实(所有章节必须保持一致，不得改写数值):
{project_facts}
可写入正文的素材事实(必须优先使用):
{material_facts}
招标结构化要求(必须逐条响应):
{requirements_context}

要求:
1. 必须优先使用“素材事实”中的具体内容写作。
2. 对每条关键事实加“(依据:素材名称)”标识。
3. 禁止编造任何编号/日期/金额/资质。
4. 缺失信息写成 [此处需人工填写: xxx]。
5. 技术方案类章节必须逐条回应“技术服务要求”；评分相关章节必须对齐“评分要求”的评分点组织证据。
6. 若招标结构化要求与素材事实冲突，以素材事实为准，并用 [此处需人工核对: 与招标要求核对] 标记缺口。
7. 正文中禁止出现 tech_candidates、material_facts、requirements_context、cert_candidates、technical_requirements、scoring、manual、source、chapter_id 等内部字段名。
8. 输出正文，不要输出解释。
"""

_REWRITE_PROMPT = """你是标书文稿质检助手。请对下列草稿做二次重写:
1) 压缩冗余表达
2) 统一术语和语气
3) 保持数据与事实不变
4) 保留 [待补充] 标记

草稿:
{draft}
"""

_BATCH_PROMPT = """你是投标文件写作助手，请一次性生成多个章节正文。

{truthfulness}

全项目锁定事实(所有章节必须保持一致，不得改写数值):
{project_facts}

章节上下文(JSON):
{chapters}

要求:
1. 对每个章节单独生成正文，返回 node_id 与 content。
2. 必须优先使用“素材事实”中的具体内容写作。
3. 对每条关键事实加“(依据:素材名称)”标识。
4. 禁止编造任何编号/日期/金额/资质。
5. 缺失信息写成 [此处需人工填写: xxx]。
6. 必须结合招标结构化要求逐条响应，技术方案对齐“技术服务要求”，评分章节对齐“评分要求”。
7. 若招标结构化要求与素材事实冲突，以素材事实为准，并标记 [此处需人工核对: 与招标要求核对]。
8. 正文中禁止出现 tech_candidates、material_facts、requirements_context、cert_candidates、technical_requirements、scoring、manual、source、chapter_id 等内部字段名。
9. 输出正文，不要输出解释。
"""


def _fallback(
    node_name: str,
    material_facts: List[Dict[str, Any]],
    requirements_context: Dict[str, Any] | None = None,
) -> str:
    lines = ["本章节按招标要求编制。"]
    if requirements_context:
        lines.append("需响应的招标要求如下:")
        for field, value in list(requirements_context.items())[:4]:
            summary = _summarize_requirement_value(value)
            if summary:
                lines.append(f"- {_requirement_field_label(field)}: {summary}")
    if material_facts:
        lines.append("可用素材如下:")
        for f in material_facts[:8]:
            if f.get("source") == "certificate":
                lines.append(
                    f"- {f.get('name','未命名证书')}"
                    f"（编号:{f.get('cert_number') or '[待补充]'}，有效期至:{f.get('expire_date') or '[待补充]'}）"
                )
            elif f.get("source") == "tech_section":
                content = str(f.get("content") or f.get("content_preview") or "").strip()
                if content:
                    lines.append(content)
                else:
                    lines.append(f"- 技术母版章节：{f.get('title') or f.get('chapter_id') or '已匹配'}")
            else:
                lines.append(f"- [此处需人工填写: {f.get('note','请人工补充')}]" )
    else:
        lines.extend([
            "- [此处需人工填写: 结合本项目实际参数补充]",
            "- [此处需人工填写: 引用对应资质/业绩证明材料]",
        ])
    return _sanitize_generated_text("\n".join(lines))


def _sanitize_generated_text(text: str) -> str:
    cleaned = text or ""
    replacements = {
        "tech_candidates": "技术母版素材",
        "material_facts": "素材事实",
        "requirements_context": "招标要求",
        "cert_candidates": "证书素材",
        "technical_requirements": "技术服务要求",
        "file_composition": "响应文件组成要求",
        "format_requirements": "格式签署要求",
        "material_checklist": "材料清单要求",
        "qualifications": "资格要求",
        "scoring": "评分要求",
        "invalidation": "废标条款",
        "pricing": "报价要求",
        "source": "来源",
        "manual素材": "人工补充事项",
        "manual": "人工补充事项",
        "chapter_id": "章节编号",
    }
    for source, target in replacements.items():
        cleaned = cleaned.replace(source, target)
    cleaned = re.sub(r"依据[:：]\s*技术母版素材\s*([0-9.]+)", r"依据:技术母版章节 \1", cleaned)
    cleaned = re.sub(r"依据[:：]\s*人工补充事项素材", "依据:人工补充事项", cleaned)
    cleaned = cleaned.replace("[待补充:", "[此处需人工填写:")
    cleaned = _remove_json_leakage(cleaned)
    return cleaned.strip()


def _summarize_requirement_value(value: Any, limit: int = 5) -> str:
    if isinstance(value, list):
        parts = []
        for item in value[:limit]:
            text = _natural_requirement_text(item)
            if text:
                parts.append(text)
        text = "；".join(part for part in parts if part)
        if len(value) > limit:
            text += f"；等{len(value)}项"
    elif isinstance(value, dict):
        parts = []
        for key, item in list(value.items())[:limit]:
            if item in (None, "", [], {}):
                continue
            text = _natural_requirement_text(item)
            if not text and isinstance(item, (str, int, float, bool)):
                text = str(item)
            if text:
                parts.append(text)
        text = "；".join(part for part in parts if part)
    else:
        text = str(value or "")
    text = _remove_json_leakage(text)
    return text[:260] + ("..." if len(text) > 260 else "")


def _natural_requirement_text(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, (str, int, float, bool)):
        text = str(value).strip()
        return "" if _looks_like_json_text(text) else text
    if isinstance(value, list):
        parts = [_natural_requirement_text(item) for item in value[:5]]
        return "；".join(part for part in parts if part)
    if not isinstance(value, dict):
        return ""

    direct_keys = (
        "name",
        "condition",
        "item",
        "category",
        "evidence_hint",
        "response_hint",
        "quote",
        "value",
    )
    for key in direct_keys:
        text = str(value.get(key) or "").strip()
        if text and not _looks_like_json_text(text):
            return text

    for atom_key in ("requirement", "required_value", "criteria", "time"):
        atom = value.get(atom_key)
        if isinstance(atom, dict):
            for key in ("value", "quote"):
                text = str(atom.get(key) or "").strip()
                if text and not _looks_like_json_text(text):
                    return text

    parts = []
    for item in value.values():
        text = _natural_requirement_text(item)
        if text:
            parts.append(text)
        if len(parts) >= 3:
            break
    return "；".join(parts)


def _looks_like_json_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.startswith(("{", "[")) and any(marker in stripped for marker in ('"', ":", "requirement", "quote")):
        return True
    return any(marker in stripped for marker in ('"requirement"', '"quote"', '"condition"', '"severity"', '"level"'))


def _remove_json_leakage(text: str) -> str:
    cleaned = text or ""
    if not _looks_like_json_text(cleaned) and not any(token in cleaned for token in ("[{", '{"', '"quote"', '"severity"', '"level"')):
        return cleaned
    cleaned = re.sub(r"\[\s*\{.*?\}\s*\]", "详见招标文件对应要求", cleaned)
    cleaned = re.sub(r"\{\s*\"(?:requirement|quote|condition|severity|level|value|name)\".*?\}", "详见招标文件对应要求", cleaned)
    cleaned = re.sub(r"\{[^{}]*(?:\"quote\"|\"severity\"|\"level\"|\"condition\"|\"requirement\")[^{}]*\}", "详见招标文件对应要求", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _requirement_field_label(field: str) -> str:
    return {
        "file_composition": "响应文件组成要求",
        "format_requirements": "格式签署要求",
        "material_checklist": "材料清单要求",
        "qualifications": "资格要求",
        "technical_requirements": "技术服务要求",
        "scoring": "评分要求",
        "invalidation": "废标条款",
        "pricing": "报价要求",
        "deposit": "保证金要求",
        "contract": "合同履约要求",
        "timeline": "时间节点要求",
    }.get(field, field)


def _leaf_nodes(outline: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    leaves: List[Tuple[str, str]] = []

    def walk(nodes: List[Dict[str, Any]]) -> None:
        for node in nodes:
            children = node.get("children") or []
            if children:
                walk(children)
            else:
                leaves.append((str(node.get("id", "")), str(node.get("name", ""))))

    walk(outline)
    return leaves


def _leaf_node_meta_map(outline: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    leaves: Dict[str, Dict[str, Any]] = {}

    def walk(nodes: List[Dict[str, Any]]) -> None:
        for node in nodes:
            children = node.get("children") or []
            if children:
                walk(children)
            else:
                leaves[str(node.get("id", ""))] = node

    walk(outline)
    return leaves


def _should_skip_authoritative_content_generation(
    node: Dict[str, Any],
    assigned_materials: List[Dict[str, Any]],
) -> bool:
    """权威提交清单节点无结构化素材时，跳过 LLM 生成，用范本复制/占位代替。

    调用者已过滤掉有结构化素材的节点，此处无需重复检查。
    """
    source = str(node.get("source") or "")
    return source in {"submission_requirement", "required_item_from_tender_requirements", "index_table"}


async def _generate_one(
    sem: asyncio.Semaphore,
    node_id: str,
    node_name: str,
    ctx: Dict[str, Any],
    requirements_context: Dict[str, Any],
    project_facts: Dict[str, Any],
    timeout_sec: int,
    max_tokens: int,
) -> Tuple[str, str, str]:
    async with sem:
        ctype = _chapter_type(node_name)
        material_facts = ctx.get("material_facts", []) or []
        use_llm = os.getenv("ENABLE_CONTENT_LLM", "true").lower() in {"1", "true", "yes", "on"}
        if not use_llm:
            return node_id, _fallback(node_name, material_facts, requirements_context), ""

        prompt = _BASE_PROMPT.format(
            truthfulness=TRUTHFULNESS_RULES,
            chapter_name=node_name,
            chapter_id=node_id,
            chapter_type=ctype,
            style_instruction=_style_instruction(ctype),
            project_facts=json.dumps(project_facts, ensure_ascii=False, indent=2),
            materials=ctx.get("materials", []),
            material_facts=_facts_text(material_facts),
            requirements_context=_requirements_text(requirements_context),
            cert_candidates=ctx.get("cert_candidates", []),
            tech_candidates=ctx.get("tech_candidates", []),
        )
        try:
            first: SectionDraft = await _with_optional_timeout(
                llm_gateway.async_call_structured(prompt, SectionDraft, max_tokens=max_tokens),
                timeout_sec,
            )
            draft = _sanitize_generated_text(
                (first.content or "").strip() or _fallback(node_name, material_facts, requirements_context)
            )

            if settings.ENABLE_CONTENT_REWRITE:
                rewrite: SectionDraft = await _with_optional_timeout(
                    llm_gateway.async_call_structured(
                        _REWRITE_PROMPT.format(draft=draft),
                        SectionDraft,
                        max_tokens=max_tokens,
                    ),
                    timeout_sec,
                )
                return node_id, _sanitize_generated_text((rewrite.content or "").strip() or draft), ""

            return node_id, _sanitize_generated_text(draft), ""
        except Exception as exc:
            reason = _format_exception(exc, timeout_sec)
            logger.warning(f"[content] {node_id} generate failed: {reason}")
            return node_id, _fallback(node_name, material_facts, requirements_context), f"[content] {node_id} 生成失败: {reason}"


def _chunked(items: List[Tuple[str, str]], size: int) -> List[List[Tuple[str, str]]]:
    return [items[i : i + size] for i in range(0, len(items), max(1, size))]


async def _generate_batch(
    sem: asyncio.Semaphore,
    batch: List[Tuple[str, str]],
    rag_contexts: Dict[str, Any],
    requirements_by_node: Dict[str, Dict[str, Any]],
    project_facts: Dict[str, Any],
    timeout_sec: int,
    max_tokens: int,
    batch_max_tokens: int,
) -> List[Tuple[str, str, str]]:
    async with sem:
        use_llm = os.getenv("ENABLE_CONTENT_LLM", "true").lower() in {"1", "true", "yes", "on"}
        if not use_llm:
            return [
                (
                    node_id,
                    _fallback(
                        node_name,
                        (rag_contexts.get(node_id, {}) or {}).get("material_facts", []) or [],
                        requirements_by_node.get(node_id, {}),
                    ),
                    "",
                )
                for node_id, node_name in batch
            ]

        chapters = []
        for node_id, node_name in batch:
            ctx = rag_contexts.get(node_id, {}) or {}
            ctype = _chapter_type(node_name)
            chapters.append(
                {
                    "node_id": node_id,
                    "chapter_name": node_name,
                    "chapter_type": ctype,
                    "style_instruction": _style_instruction(ctype),
                    "facts": ctx.get("material_facts", []) or [],
                    "requirements": _requirements_text(requirements_by_node.get(node_id, {})),
                }
            )

        prompt = _BATCH_PROMPT.format(
            truthfulness=TRUTHFULNESS_RULES,
            project_facts=json.dumps(project_facts, ensure_ascii=False, indent=2),
            chapters=json.dumps(chapters, ensure_ascii=False, indent=2),
        )
        try:
            result: BatchSectionDraft = await _with_optional_timeout(
                llm_gateway.async_call_structured(
                    prompt,
                    BatchSectionDraft,
                    max_tokens=max(max_tokens, batch_max_tokens),
                ),
                timeout_sec,
            )
            by_id = {str(item.node_id): _sanitize_generated_text(item.content or "") for item in result.sections}
            rows: List[Tuple[str, str, str]] = []
            for node_id, node_name in batch:
                content = by_id.get(node_id)
                if not content:
                    material_facts = (rag_contexts.get(node_id, {}) or {}).get("material_facts", []) or []
                    rows.append((node_id, _fallback(node_name, material_facts, requirements_by_node.get(node_id, {})), f"[content] {node_id} 批量生成缺失，已降级"))
                else:
                    rows.append((node_id, content, ""))
            return rows
        except Exception as exc:
            reason = _format_exception(exc, timeout_sec)
            logger.warning(
                "[content] batch generate failed for nodes={}: {}",
                [node_id for node_id, _ in batch],
                reason,
            )
            rows = []
            for node_id, node_name in batch:
                material_facts = (rag_contexts.get(node_id, {}) or {}).get("material_facts", []) or []
                rows.append((node_id, _fallback(node_name, material_facts, requirements_by_node.get(node_id, {})), f"[content] {node_id} 批量生成失败: {reason}"))
            return rows


async def generate_content(state: Dict[str, Any]) -> Dict[str, Any]:
    outline = state.get("final_outline") or state.get("outline") or []
    rag_contexts = state.get("rag_contexts") or {}
    located_sections = state.get("located_sections") or []
    tender_requirements = state.get("tender_requirements") or {}
    project_facts = _build_locked_project_facts(state, tender_requirements)
    assignments = _assignment_map(state.get("material_assignments") or [])
    if not outline:
        return {"generated_sections": {}, "warnings": ["[content] empty outline"]}

    all_leaves = _leaf_nodes(outline)
    leaf_meta = _leaf_node_meta_map(outline)
    generated, warnings = _build_template_generated_sections(
        all_leaves,
        assignments,
        tender_requirements,
        located_sections,
    )
    leaves = [
        (node_id, node_name)
        for node_id, node_name in all_leaves
        if node_id not in generated
        and not _is_front_chapter(node_name)
        and not _has_structured_material(assignments.get(node_id, []))
        and not _should_skip_authoritative_content_generation(leaf_meta.get(node_id, {}), assignments.get(node_id, []))
    ]
    if not leaves:
        payload: Dict[str, Any] = {
            "generated_sections": generated,
            "project_facts": project_facts,
        }
        if warnings:
            payload["warnings"] = warnings
        return payload

    timeout_sec = int(os.getenv("CONTENT_CALL_TIMEOUT_SEC", "150"))
    max_concurrency = int(os.getenv("CONTENT_MAX_CONCURRENCY", str(settings.CONTENT_MAX_CONCURRENCY)))
    max_tokens = int(os.getenv("CONTENT_MAX_TOKENS", str(settings.CONTENT_MAX_TOKENS)))
    batch_size = int(os.getenv("CONTENT_BATCH_SIZE", str(settings.CONTENT_BATCH_SIZE)))
    batch_max_tokens = int(os.getenv("CONTENT_BATCH_MAX_TOKENS", str(max_tokens * max(1, min(batch_size, 3)))))
    sem = asyncio.Semaphore(max(1, max_concurrency))
    requirements_by_node = {
        node_id: _match_requirements_for_chapter(node_name, tender_requirements)
        for node_id, node_name in leaves
    }
    requirement_hits = sum(1 for ctx in requirements_by_node.values() if ctx)

    logger.info(
        f"[content] start, leaves={len(leaves)}/{len(all_leaves)}, requirement_hits={requirement_hits}, concurrency={max_concurrency}, batch_size={batch_size}, timeout={'none' if timeout_sec <= 0 else f'{timeout_sec}s'}, max_tokens={max_tokens}"
    )

    if batch_size <= 1:
        tasks = [
            _generate_one(
                sem,
                node_id,
                node_name,
                rag_contexts.get(node_id, {}) or {},
                requirements_by_node.get(node_id, {}),
                project_facts,
                timeout_sec,
                max_tokens,
            )
            for node_id, node_name in leaves
        ]
        results = await asyncio.gather(*tasks)
    else:
        batch_tasks = [
            _generate_batch(
                sem,
                batch,
                rag_contexts,
                requirements_by_node,
                project_facts,
                timeout_sec,
                max_tokens,
                batch_max_tokens,
            )
            for batch in _chunked(leaves, batch_size)
        ]
        batch_results = await asyncio.gather(*batch_tasks)
        results = [row for batch in batch_results for row in batch]

    for node_id, content, warning in results:
        generated[node_id] = content
        if warning:
            warnings.append(warning)

    logger.info(f"[content] done, generated={len(generated)}, warnings={len(warnings)}")
    payload: Dict[str, Any] = {
        "generated_sections": generated,
        "project_facts": project_facts,
    }
    if warnings:
        payload["warnings"] = warnings
    return payload
