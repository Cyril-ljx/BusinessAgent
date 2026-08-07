"""LangGraph state definition."""
import operator
from typing import Annotated, Any, Dict, List, TypedDict


def _last_writer_wins(_left: Any, right: Any) -> Any:
    return right


class TenderState(TypedDict, total=False):
    project_id: str
    file_name: str
    source_file_path: str
    company_id: str
    company_name: str

    # Input
    head_text: str
    located_sections: List[Dict[str, Any]]
    requirement_source_sections: List[Dict[str, Any]]
    block_index: List[Dict[str, Any]]

    # Outputs from early stages
    title_info: Annotated[Dict[str, Any], _last_writer_wins]
    merged_outline: List[Dict[str, Any]]
    final_outline: List[Dict[str, Any]]
    outline: List[Dict[str, Any]]
    tender_requirements: Annotated[Dict[str, Any], _last_writer_wins]
    tender_requirements_stats: Annotated[Dict[str, Any], _last_writer_wins]
    material_assignments: List[Dict[str, Any]]

    # New pipeline outputs
    rag_contexts: Dict[str, Dict[str, Any]]
    retrieval_summary: Dict[str, Any]
    generated_sections: Dict[str, str]
    project_facts: Dict[str, Any]
    compliance_report: Dict[str, Any]
    consistency_report: Dict[str, Any]

    warnings: Annotated[List[str], operator.add]
