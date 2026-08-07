"""Structured LLM schemas used by requirement extraction."""

from __future__ import annotations

from typing import List, Type

from pydantic import BaseModel, Field

from ..requirements import BidderSpecialRequirement


class SimpleFileCompositionItem(BaseModel):
    name: str = ""
    required: bool = True
    order: int | None = None
    template_ref: str | None = None
    outline_level: int | None = None
    parent_name: str | None = None
    quote: str = ""
    section_id: str | None = None
    section_title: str | None = None


class SimpleFormatRequirement(BaseModel):
    name: str = ""
    quote: str = ""
    template_ref: str | None = None
    section_id: str | None = None
    section_title: str | None = None
    severity: str = "P2"


class SimpleQualificationRequirement(BaseModel):
    name: str = ""
    quote: str = ""
    mandatory: bool = True
    evidence_hint: str | None = None
    section_id: str | None = None
    section_title: str | None = None
    severity: str = "P1"


class SimpleMaterialItem(BaseModel):
    name: str = ""
    quote: str = ""
    original: bool | None = None
    copy_sealed: bool | None = None
    count: int | None = None
    required: bool = True
    section_id: str | None = None
    section_title: str | None = None
    severity: str = "P1"


class SimpleBaseInfoItem(BaseModel):
    field: str = ""
    value: str = ""
    quote: str = ""
    section_id: str | None = None
    section_title: str | None = None
    severity: str = "P1"


class SimpleTimelineItem(BaseModel):
    name: str = ""
    time: str = ""
    action: str | None = None
    fatal_if_missed: bool = False
    quote: str = ""
    section_id: str | None = None
    section_title: str | None = None
    severity: str = "P1"


class SimpleTechnicalRequirement(BaseModel):
    name: str = ""
    param_name: str | None = None
    required_value: str = ""
    quantity: str | None = None
    mandatory: bool = True
    category: str | None = None
    response_hint: str | None = None
    quote: str = ""
    section_id: str | None = None
    section_title: str | None = None
    severity: str = "P1"


class SimpleScoringCriterion(BaseModel):
    category: str = ""
    score_type: str | None = None
    item: str = ""
    score: float | None = None
    criteria: str = ""
    evidence_hint: str | None = None
    quote: str = ""
    section_id: str | None = None
    section_title: str | None = None
    severity: str = "P2"


class SimpleInvalidationClause(BaseModel):
    condition: str = ""
    quote: str = ""
    level: str = "P0"
    category: str | None = None
    section_id: str | None = None
    section_title: str | None = None


class SimpleNamedRequirement(BaseModel):
    name: str = ""
    value: str = ""
    quote: str = ""
    section_id: str | None = None
    section_title: str | None = None
    severity: str = "P1"


class BaseTimelineExtraction(BaseModel):
    document_type: str = Field(default="其他")
    base_info_items: List[SimpleBaseInfoItem] = Field(default_factory=list)
    timeline: List[SimpleTimelineItem] = Field(default_factory=list)


class FileCompositionExtraction(BaseModel):
    file_composition: List[SimpleFileCompositionItem] = Field(default_factory=list)


class FormatTemplateExtraction(BaseModel):
    format_requirements: List[SimpleFormatRequirement] = Field(default_factory=list)


class QualificationReviewExtraction(BaseModel):
    qualifications: List[SimpleQualificationRequirement] = Field(default_factory=list)


class SubmissionChecklistExtraction(BaseModel):
    material_checklist: List[SimpleMaterialItem] = Field(default_factory=list)
    bidder_special_requirements: List[BidderSpecialRequirement] = Field(default_factory=list)


class TechnicalScoringExtraction(BaseModel):
    technical_requirements: List[SimpleTechnicalRequirement] = Field(default_factory=list)
    scoring: List[SimpleScoringCriterion] = Field(default_factory=list)


class RiskContractExtraction(BaseModel):
    invalidation: List[SimpleInvalidationClause] = Field(default_factory=list)
    pricing_requirements: List[SimpleNamedRequirement] = Field(default_factory=list)
    deposit_requirements: List[SimpleNamedRequirement] = Field(default_factory=list)
    contract_requirements: List[SimpleNamedRequirement] = Field(default_factory=list)


class DimensionConfig(BaseModel):
    name: str
    output_model: Type[BaseModel]
    instruction: str
    include_head: bool = False
    max_tokens: int = 3500
    batch_chars: int = 12000
    max_total_chars: int | None = None
