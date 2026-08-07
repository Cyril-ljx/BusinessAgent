"""LangGraph workflow for tender generation."""
from langgraph.graph import END, START, StateGraph

from ..core.state import TenderState
from ..observability.langsmith_tracing import trace_stage
from .compliance_checker import run_compliance_checks
from .composer import compose_outline
from .consistency_checker import check_consistency
from .content_generator import generate_content
from .material_mapper import map_materials
from .nodes import extract_title
from .rag_retriever import build_rag_contexts
from .requirement_extractor import extract_tender_requirements


def build_understanding_graph() -> StateGraph:
    workflow = StateGraph(TenderState)

    workflow.add_node("title", trace_stage("title")(extract_title))
    workflow.add_node("composer", trace_stage("composer")(compose_outline))
    workflow.add_node("requirement_extractor", trace_stage("requirement_extractor")(extract_tender_requirements))
    workflow.add_node("material_mapper", trace_stage("material_mapper")(map_materials))
    workflow.add_node("rag_retriever", trace_stage("rag_retriever")(build_rag_contexts))
    workflow.add_node("content_generator", trace_stage("content_generator")(generate_content))
    workflow.add_node("compliance", trace_stage("compliance")(run_compliance_checks))
    workflow.add_node("consistency", trace_stage("consistency")(check_consistency))

    workflow.add_edge(START, "title")
    workflow.add_edge("title", "requirement_extractor")
    workflow.add_edge("requirement_extractor", "composer")
    workflow.add_edge("composer", "material_mapper")
    workflow.add_edge("material_mapper", "rag_retriever")
    workflow.add_edge("rag_retriever", "content_generator")
    workflow.add_edge("content_generator", "compliance")
    workflow.add_edge("compliance", "consistency")
    workflow.add_edge("consistency", END)

    return workflow.compile()


def build_outline_review_graph() -> StateGraph:
    """Build only the source-understanding stages needed before user review."""
    workflow = StateGraph(TenderState)

    workflow.add_node("title", trace_stage("title")(extract_title))
    workflow.add_node("requirement_extractor", trace_stage("requirement_extractor")(extract_tender_requirements))
    workflow.add_node("composer", trace_stage("composer")(compose_outline))

    workflow.add_edge(START, "title")
    workflow.add_edge("title", "requirement_extractor")
    workflow.add_edge("requirement_extractor", "composer")
    workflow.add_edge("composer", END)

    return workflow.compile()


tender_graph = build_understanding_graph()
outline_review_graph = build_outline_review_graph()
