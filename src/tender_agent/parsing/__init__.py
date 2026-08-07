from .docx_parser import parse_docx, parse_pdf, parse_document, ParsedDoc, Section
from .section_locator import (
    locate_route_sections_llm,  # ★ 新接口
    locate_explicit_composition_sections,
    locate_route_sections_fallback,
    assemble_section_content,
    LocatedSection,
    LocateResult,
)

__all__ = [
    "parse_docx",
    "parse_pdf",
    "parse_document",
    "ParsedDoc",
    "Section",
    "locate_route_sections_llm",
    "locate_explicit_composition_sections",
    "locate_route_sections_fallback",
    "assemble_section_content",
    "LocatedSection",
    "LocateResult",
]
