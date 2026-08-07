"""Render planning for bid DOCX output.

The render layer consumes an already-confirmed outline plus material assignments.
It must not infer bid requirements from title keywords. Template copying is only
triggered by explicit template metadata or a `tender_template` material chosen by
material mapping/LLM.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, List


def prepare_render_outline(outline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    nodes = clone_renderable(outline or [])
    _renumber(nodes)
    return nodes


def clone_renderable(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cloned: List[Dict[str, Any]] = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        item = deepcopy(node)
        item["children"] = clone_renderable(item.get("children") or [])
        cloned.append(item)
    return cloned


def _renumber(nodes: List[Dict[str, Any]], prefix: str = "") -> None:
    for index, node in enumerate(nodes or [], start=1):
        node_id = f"{prefix}.{index}" if prefix else str(index)
        original_id = str(node.get("_source_id") or node.get("id") or "")
        node["_source_id"] = original_id or node_id
        node["id"] = node_id
        node["level"] = node_id.count(".") + 1
        _renumber(node.get("children") or [], node_id)


def is_authoritative_outline_source(node: Dict[str, Any]) -> bool:
    return bool(str(node.get("source") or node.get("source_kind") or "").strip())


def build_render_plan(
    outline: List[Dict[str, Any]],
    material_assignments: List[Dict[str, Any]],
    generated_sections: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    return {
        "outline": outline or [],
        "assignments_by_id": build_assignment_map(material_assignments or []),
        "generated_sections": generated_sections or {},
    }


def build_assignment_map(assignments: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    by_id: Dict[str, List[Dict[str, Any]]] = {}
    for assignment in assignments or []:
        if not isinstance(assignment, dict):
            continue
        node_id = str(assignment.get("node_id") or assignment.get("outline_node_id") or "").strip()
        if not node_id:
            continue
        by_id.setdefault(node_id, []).append(assignment)
    return by_id


def resolve_node_assignments(render_plan: Dict[str, Any], node: Dict[str, Any]) -> List[Dict[str, Any]]:
    by_id = render_plan.get("assignments_by_id") or {}
    node_id = str(node.get("id") or "")
    source_id = str(node.get("_source_id") or "")
    return list(by_id.get(node_id) or by_id.get(source_id) or [])


def resolve_node_generated_text(render_plan: Dict[str, Any], node: Dict[str, Any]) -> str:
    generated = render_plan.get("generated_sections") or {}
    node_id = str(node.get("id") or "")
    source_id = str(node.get("_source_id") or "")
    return str(generated.get(node_id) or generated.get(source_id) or "").strip()


def resolve_node_render_decision(render_plan: Dict[str, Any], node: Dict[str, Any]) -> Dict[str, Any]:
    assignments = resolve_node_assignments(render_plan, node)
    generated = resolve_node_generated_text(render_plan, node)
    materials = flatten_materials(assignments)
    if generated and _looks_like_material_stub_generated_text(generated, materials):
        generated = ""
    has_template_material = has_tender_template_material(assignments)
    should_template = should_try_tender_template(node, assignments)
    decision: Dict[str, Any] = {
        "assignments": assignments,
        "generated": generated,
        "has_tender_template_material": has_template_material,
        "should_try_tender_template": should_template,
        "should_copy_template_package": False,
        "prefers_template_over_materials": should_template,
        "append_supporting_materials_after_template": bool(materials),
        "template_package_step": "",
        "template_package_supporting_assignments": assignments,
        "compact_heading": should_template,
        "template_fallback_steps": template_fallback_steps(node, should_template),
        "copy_generated_after_template": bool(generated and should_template),
        "template_required_placeholder": template_required_placeholder(),
        "structured_material_phase": structured_material_phase(assignments, generated, should_template),
        "manual_placeholders": manual_placeholder_lines(node, assignments),
        "material_summary_lines": material_summary_lines(assignments),
        "material_summary_placeholder": material_summary_placeholder(),
        "empty_placeholder": empty_section_placeholder(node),
        "is_manual_only_assignment": is_manual_only_assignment(assignments),
        "is_evidence_node": False,
    }
    decision["strategy"] = classify_render_strategy(node, decision)
    return decision


def classify_render_strategy(node: Dict[str, Any], decision: Dict[str, Any]) -> str:
    if node.get("children"):
        return "container"
    if decision.get("should_try_tender_template"):
        return "tender_template"
    if decision.get("generated"):
        return "generated"
    if flatten_materials(decision.get("assignments") or []):
        return "materials"
    return "empty"


def structured_material_phase(assignments: List[Dict[str, Any]], generated: str, should_template: bool = False) -> str:
    materials = [m for m in flatten_materials(assignments) if material_source(m) != "tender_template"]
    if not materials:
        return ""
    if should_template:
        return "after_template"
    return "after_generated" if str(generated or "").strip() else "fallback"


def template_fallback_steps(node: Dict[str, Any], should_template: bool | Dict[str, Any] = False) -> List[str]:
    if isinstance(should_template, dict):
        enabled = bool(should_template.get("should_try_tender_template"))
    else:
        enabled = bool(should_template)
    if node.get("children") or not enabled:
        return []
    return ["official_template", "pdf_template", "docx_template"]


def pdf_template_fallback_allowed(node_name: str) -> bool:
    return bool(template_search_tokens(node_name))


def docx_template_fallback_allowed(node_name: str) -> bool:
    return bool(template_search_tokens(node_name))


def pdf_table_fallback_allowed(node_name: str) -> bool:
    return bool(template_search_tokens(node_name))


def pdf_text_template_fallback_allowed(node_name: str) -> bool:
    return bool(template_search_tokens(node_name))


def template_search_tokens(name: str) -> List[str]:
    text = _norm_text(name)
    if not text:
        return []
    tokens = [text]
    for part in re.split(r"[、/／()（）\[\]【】,，;；:：\s]+", text):
        part = part.strip()
        if len(part) >= 3 and part not in tokens:
            tokens.append(part)
    return tokens[:6]


def template_required_placeholder() -> str:
    return "[待补充：请按招标文件原文范本填写本章节]"


def template_fill_placeholder() -> str:
    return "[待补充：请按招标文件格式填写]"


def material_summary_placeholder() -> str:
    return "[待补充：请根据以上素材完善本章节]"


def empty_section_placeholder(node: Dict[str, Any]) -> str:
    return f"[待补充：请人工补充：{str(node.get('name') or '本章节')}（当前知识库无对应素材）]"


def manual_placeholder_lines(node: Dict[str, Any], assignments: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    for material in flatten_materials(assignments):
        if str(material.get("source") or "") == "manual":
            note = str(material.get("note") or "").strip()
            if note:
                lines.append(f"[待补充：{note}]")
    return lines or [empty_section_placeholder(node)]


def manual_section_placeholder(node: Dict[str, Any], note: str) -> str:
    return f"[待补充：{note or str(node.get('name') or '本章节')}]"


def material_summary_lines(assignments: List[Dict[str, Any]], limit: int = 10) -> List[str]:
    lines: List[str] = []
    for material in flatten_materials(assignments)[:limit]:
        source = material_source(material)
        if source == "certificate":
            lines.append(f"- 证书/资料：{material.get('category') or material.get('name') or ''}")
        elif source == "tech_section":
            lines.append(f"- 技术章节：{material.get('chapter_id') or ''}")
        elif source == "tech_section_range":
            lines.append(f"- 技术章节：{material.get('chapter_start') or ''} - {material.get('chapter_end') or ''}")
        elif source == "tender_template":
            lines.append(f"- 招标文件范本：{material.get('name') or ''}")
        elif source == "manual":
            lines.append(f"- 待补充：{material.get('note') or ''}")
    return [line for line in lines if line.strip("- ：")]


def build_todo_items(render_plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    todos: List[Dict[str, Any]] = []
    for node in _walk_nodes(render_plan.get("outline") or []):
        decision = resolve_node_render_decision(render_plan, node)
        if decision.get("strategy") in {"empty", "materials"} and decision.get("is_manual_only_assignment"):
            todos.append({"node_id": node.get("id"), "node_name": node.get("name"), "reason": "manual_required"})
    return todos


def build_render_decision_report(
    outline: List[Dict[str, Any]],
    material_assignments: List[Dict[str, Any]],
    generated_sections: Dict[str, str] | None = None,
) -> List[Dict[str, Any]]:
    render_outline = prepare_render_outline(outline or [])
    plan = build_render_plan(render_outline, material_assignments or [], generated_sections or {})
    report: List[Dict[str, Any]] = []
    for node in _walk_nodes(render_outline):
        decision = resolve_node_render_decision(plan, node)
        materials = flatten_materials(decision.get("assignments") or [])
        report.append(
            {
                "node_id": str(node.get("id") or ""),
                "source_id": str(node.get("_source_id") or node.get("id") or ""),
                "node_name": str(node.get("name") or ""),
                "has_template": bool(node.get("has_template")),
                "assignment_count": len(decision.get("assignments") or []),
                "material_count": len(materials),
                "material_sources": sorted({material_source(m) for m in materials if material_source(m)}),
                "has_generated": bool(str(decision.get("generated") or "").strip()),
                "strategy": str(decision.get("strategy") or ""),
                "compact_heading": bool(decision.get("compact_heading")),
                "copy_generated_after_template": bool(decision.get("copy_generated_after_template")),
                "template_fallback_steps": list(decision.get("template_fallback_steps") or []),
                "template_package_step": str(decision.get("template_package_step") or ""),
                "structured_material_phase": str(decision.get("structured_material_phase") or ""),
                "prefers_template_over_materials": bool(decision.get("prefers_template_over_materials")),
                "append_supporting_materials_after_template": bool(decision.get("append_supporting_materials_after_template")),
                "should_try_tender_template": bool(decision.get("should_try_tender_template")),
                "should_copy_template_package": bool(decision.get("should_copy_template_package")),
                "has_tender_template_material": bool(decision.get("has_tender_template_material")),
                "is_evidence_node": bool(decision.get("is_evidence_node")),
                "is_manual_only_assignment": bool(decision.get("is_manual_only_assignment")),
            }
        )
    return report


def flatten_materials(assignments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    flat_materials: List[Dict[str, Any]] = []
    for assignment in assignments or []:
        if not isinstance(assignment, dict):
            continue
        mats = assignment.get("materials")
        if isinstance(mats, list):
            flat_materials.extend([m for m in mats if isinstance(m, dict)])
        else:
            flat_materials.append(assignment)
    return flat_materials


def material_source(material: Dict[str, Any]) -> str:
    source = str(material.get("source") or "").strip()
    if source == "knowledge_certificate":
        return "certificate"
    if source == "knowledge_tech_section":
        return "tech_section"
    return source


def _looks_like_material_stub_generated_text(generated: str, materials: List[Dict[str, Any]]) -> bool:
    """Ignore editor drafts created by the old material-insert shortcut.

    Those drafts only contain a material title/path and should not suppress the
    structured renderer that copies the actual certificate image or master DOCX.
    """
    if not generated or not materials:
        return False
    normalized = _norm_text(re.sub(r"<[^>]+>", "", generated))
    if not normalized or len(normalized) > 260:
        return False
    structured_sources = {material_source(material) for material in materials}
    if structured_sources.intersection({"certificate", "tech_section", "tech_section_range"}) and (
        "知识库无对应素材" in normalized
        or ("此处需人工填写" in normalized and "请人工补充" in normalized)
    ):
        return True
    for material in materials:
        source = material_source(material)
        file_path = str(material.get("file_path") or "").strip()
        if file_path and _norm_text(file_path) in normalized:
            return True
        if source == "certificate" and any(token in normalized for token in ("知识库证书", "证书图片", "素材文件")):
            return True
        if source == "certificate" and "证书资料" in normalized:
            material_name = _norm_text(str(material.get("category") or material.get("name") or ""))
            if not material_name or material_name in normalized:
                return True
    return False


def normalize_lookup_name(text: str) -> str:
    return _norm_text(text)


def should_try_tender_template(node: Dict[str, Any], assignments: List[Dict[str, Any]] | None = None) -> bool:
    materials = flatten_materials(assignments or [])
    if any(material_source(material) == "tender_template" for material in materials):
        return True
    if any(material_source(material) in {"certificate", "tech_section", "tech_section_range"} for material in materials):
        return False
    if node.get("template_ref") or node.get("source_anchor") or node.get("source_section_id"):
        return True
    return bool(node.get("has_template"))


def prefers_tender_template_over_materials(node: Dict[str, Any]) -> bool:
    return should_try_tender_template(node, [])


def append_supporting_materials_after_template(
    node: Dict[str, Any],
    assignments: List[Dict[str, Any]],
    prefers_template: bool | None = None,
) -> bool:
    materials = [m for m in flatten_materials(assignments) if material_source(m) != "tender_template"]
    return bool(materials)


def should_copy_template_package_as_whole(node: Dict[str, Any], assignments: List[Dict[str, Any]]) -> bool:
    return False


def template_package_supporting_assignments(node: Dict[str, Any], assignments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return assignments


def without_blocked_tech_materials(node: Dict[str, Any], assignments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return assignments


def has_tech_section_material(assignments: List[Dict[str, Any]]) -> bool:
    return any(material_source(material) in {"tech_section", "tech_section_range"} for material in flatten_materials(assignments))


def has_tender_template_material(assignments: List[Dict[str, Any]]) -> bool:
    return any(material_source(material) == "tender_template" for material in flatten_materials(assignments))


def is_manual_only_assignment(assignments: List[Dict[str, Any]]) -> bool:
    materials = flatten_materials(assignments)
    return bool(materials) and all(material_source(material) == "manual" for material in materials)


def is_evidence_node(node: Dict[str, Any]) -> bool:
    return False


def _walk_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        result.append(node)
        result.extend(_walk_nodes(node.get("children") or []))
    return result


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip("：:")
