"""Structured tender requirements models.

This module defines the contract for the upcoming "requirements layer".
It is intentionally not wired into graph/composer/content yet.
"""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


DocumentType = Literal["招标", "磋商", "询价", "谈判", "比选", "竞价", "其他"]


class Severity(str, Enum):
    """Unified severity levels for extraction, generation and compliance."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class AnchorBlock(BaseModel):
    """One source block anchor from ParsedDoc.block_index / located_sections."""

    anchor: str = Field(default="", description="块锚点，如 p123")
    kind: Optional[str] = Field(default=None, description="段落/表格等块类型")
    text: Optional[str] = Field(default=None, description="该块文本摘录")


class SourceAnchor(BaseModel):
    """Trace pointer compatible with current located_sections output."""

    section_id: Optional[str] = Field(default=None, description="located_sections.section_id")
    section_title: Optional[str] = Field(default=None, description="located_sections.title")
    anchor_start: Optional[str] = Field(default=None, description="章节起始块锚点，如 p10")
    anchor_end: Optional[str] = Field(default=None, description="章节结束块锚点，如 p28")
    anchor_blocks: List[AnchorBlock] = Field(default_factory=list, description="更细的段落/表格块锚点")


class RequirementAtom(BaseModel):
    """Smallest traceable requirement unit extracted from the tender document."""

    value: Any = Field(default=None, description="结构化取值，保持原文含义，不得编造")
    quote: str = Field(default="", description="原文摘录")
    anchor: Optional[SourceAnchor] = Field(default=None, description="原文定位信息，兼容 located_sections 锚点")
    severity: Severity = Field(default=Severity.P2, description="P0 致命，P1 重要，P2 普通，P3 参考")


class BaseInfoRequirements(BaseModel):
    """A-BASE: project and tender metadata."""

    project_name: Optional[RequirementAtom] = None
    tender_no: Optional[RequirementAtom] = None
    purchaser: Optional[RequirementAtom] = None
    agency: Optional[RequirementAtom] = None
    submission_deadline: Optional[RequirementAtom] = None
    bid_open_time: Optional[RequirementAtom] = None
    bid_validity_period: Optional[RequirementAtom] = None
    document_title: Optional[RequirementAtom] = None


class DepositRequirements(BaseModel):
    """A-DEPOSIT: bid bond/deposit requirements."""

    required: Optional[RequirementAtom] = None
    amount: Optional[RequirementAtom] = None
    currency: Optional[RequirementAtom] = None
    payment_method: Optional[RequirementAtom] = None
    payment_deadline: Optional[RequirementAtom] = None
    refund_conditions: List[RequirementAtom] = Field(default_factory=list)
    forfeiture_conditions: List[RequirementAtom] = Field(default_factory=list)


class FileCompositionItem(BaseModel):
    """A-FORMAT: required response/bid file component."""

    name: str = Field(default="", description="文件组成项名称")
    required: bool = Field(default=True)
    order: Optional[int] = Field(default=None)
    template_ref: Optional[str] = Field(default=None, description="附件/格式范本编号")
    requirement: RequirementAtom = Field(default_factory=RequirementAtom)
    source_backed_composition: bool = Field(default=False)
    source_kind: Optional[str] = None
    outline_level: Optional[int] = None
    parent_name: Optional[str] = None
    outline_group: bool = Field(default=False)


class FormatRequirement(BaseModel):
    """A-FORMAT: formatting, signing, sealing, binding, copy count, template rules."""

    name: str = Field(default="")
    requirement: RequirementAtom = Field(default_factory=RequirementAtom)
    template_ref: Optional[str] = None


class QualificationRequirement(BaseModel):
    """A-QUALIFY: qualification threshold or proof requirement."""

    name: str = Field(default="")
    requirement: RequirementAtom = Field(default_factory=RequirementAtom)
    mandatory: bool = Field(default=True)
    evidence_hint: Optional[str] = Field(default=None, description="建议响应材料，如营业执照/许可证/社保")


class ScoringCriterion(BaseModel):
    """A-SCORE: scoring item or review criterion."""

    category: str = Field(default="", description="商务/技术/价格/综合等")
    score_type: Optional[str] = Field(default=None, description="技术评分/商务评分/价格评分/评审方法等顶层评分类型")
    item: str = Field(default="")
    score: Optional[float] = Field(default=None)
    criteria: RequirementAtom = Field(default_factory=RequirementAtom)
    evidence_hint: Optional[str] = Field(default=None)


class ScoringGroup(BaseModel):
    """Grouped scoring items for UI and downstream planning."""

    score_type: str = Field(default="", description="技术评分/商务评分/价格评分/评审方法等")
    total_score: Optional[float] = Field(default=None, description="该评分组已识别到的分值合计")
    items: List[ScoringCriterion] = Field(default_factory=list)


class ScoringOverview(BaseModel):
    """Structured view of scoring rules grouped by score type."""

    total_score: Optional[float] = Field(default=None, description="所有可计分评分组的合计分值")
    groups: List[ScoringGroup] = Field(default_factory=list)


class TechnicalRequirement(BaseModel):
    """B-TECH_REQ: technical requirement, purchase list item, service requirement."""

    name: str = Field(default="")
    param_name: Optional[str] = Field(default=None, description="技术参数/服务指标名称")
    required_value: RequirementAtom = Field(default_factory=RequirementAtom, description="要求值/指标值/服务标准")
    quantity: Optional[RequirementAtom] = Field(default=None, description="数量/规模/频次")
    mandatory: bool = Field(default=True, description="强制要求为 true，推荐/加分项为 false")
    category: Optional[str] = Field(default=None, description="采购清单/服务要求/技术参数/人员要求等")
    response_hint: Optional[str] = Field(default=None, description="建议在技术方案中如何响应")


class InvalidationClause(BaseModel):
    """A-INVALID: invalid bid / rejection / disqualification clause."""

    condition: str = Field(default="", description="触发废标/无效/否决的条件")
    quote: str = Field(default="", description="原文摘录")
    anchor: Optional[SourceAnchor] = Field(default=None)
    level: Severity = Field(default=Severity.P0, description="通常为 P0/P1")
    category: Optional[str] = Field(default=None, description="资格/报价/格式/递交/平台操作等")


class PricingRequirement(BaseModel):
    """B-PRICE: pricing, quotation and price composition rules."""

    highest_limit: Optional[RequirementAtom] = None
    quotation_method: Optional[RequirementAtom] = None
    price_components: List[RequirementAtom] = Field(default_factory=list)
    tax_rules: List[RequirementAtom] = Field(default_factory=list)
    abnormal_price_rules: List[RequirementAtom] = Field(default_factory=list)


class ContractRequirement(BaseModel):
    """A-CONTRACT: contract, performance, payment, penalty and service obligations."""

    service_period: Optional[RequirementAtom] = None
    performance_bond: Optional[RequirementAtom] = None
    payment_terms: List[RequirementAtom] = Field(default_factory=list)
    acceptance_rules: List[RequirementAtom] = Field(default_factory=list)
    penalty_clauses: List[RequirementAtom] = Field(default_factory=list)
    other_risks: List[RequirementAtom] = Field(default_factory=list)


class TimelineRequirement(BaseModel):
    """A-TIMELINE: submission, clarification, opening, delivery and other deadlines."""

    name: str = Field(default="")
    time: RequirementAtom = Field(default_factory=RequirementAtom)
    action: Optional[str] = Field(default=None)
    fatal_if_missed: bool = Field(default=False)


class MaterialItem(BaseModel):
    """A-MATERIAL: required material checklist item."""

    name: str = Field(default="")
    original: Optional[bool] = Field(default=None, description="是否要求原件")
    copy_sealed: Optional[bool] = Field(default=None, description="复印件是否要求加盖公章")
    count: Optional[int] = Field(default=None, description="要求份数")
    required: bool = Field(default=True)
    requirement: RequirementAtom = Field(default_factory=RequirementAtom)


class BidderSpecialRequirement(BaseModel):
    """B-BIDDER: bidder-specific special condition not covered by common fields."""

    name: str = Field(default="")
    requirement: RequirementAtom = Field(default_factory=RequirementAtom)


class TenderRequirements(BaseModel):
    """Top-level structured requirements extracted from a tender document."""

    document_type: DocumentType = Field(default="其他", description="招标/磋商/询价/谈判/比选等")

    @model_validator(mode="before")
    @classmethod
    def _coerce_empty_top_level_fields(cls, data: Any) -> Any:
        """LLMs sometimes use null for an empty object/list; normalize it."""
        if not isinstance(data, dict):
            return data

        object_fields = ("base_info", "deposit", "contract", "pricing", "method_specific")
        object_fields += ("scoring_overview",)
        list_fields = (
            "file_composition",
            "format_requirements",
            "qualifications",
            "scoring",
            "invalidation",
            "material_checklist",
            "timeline",
            "technical_requirements",
            "bidder_special_requirements",
        )
        for field_name in object_fields:
            if data.get(field_name) is None:
                data[field_name] = {}
        for field_name in list_fields:
            if data.get(field_name) is None:
                data[field_name] = []
        return data

    # A layer: common bid-critical requirements.
    base_info: BaseInfoRequirements = Field(default_factory=BaseInfoRequirements)
    deposit: DepositRequirements = Field(default_factory=DepositRequirements)
    file_composition: List[FileCompositionItem] = Field(default_factory=list)
    format_requirements: List[FormatRequirement] = Field(default_factory=list)
    qualifications: List[QualificationRequirement] = Field(default_factory=list)
    scoring: List[ScoringCriterion] = Field(default_factory=list)
    scoring_overview: ScoringOverview = Field(default_factory=ScoringOverview)
    invalidation: List[InvalidationClause] = Field(default_factory=list)
    material_checklist: List[MaterialItem] = Field(default_factory=list)
    contract: ContractRequirement = Field(default_factory=ContractRequirement)
    timeline: List[TimelineRequirement] = Field(default_factory=list)

    # B layer: supplemental requirements currently weak/missing in the pipeline.
    pricing: PricingRequirement = Field(default_factory=PricingRequirement)
    technical_requirements: List[TechnicalRequirement] = Field(default_factory=list)
    bidder_special_requirements: List[BidderSpecialRequirement] = Field(default_factory=list)

    # C layer: procurement-method-specific extension point.
    method_specific: Dict[str, Any] = Field(
        default_factory=dict,
        description="采购方式差异化字段，如磋商轮次、询价报价方式、谈判响应规则等",
    )
