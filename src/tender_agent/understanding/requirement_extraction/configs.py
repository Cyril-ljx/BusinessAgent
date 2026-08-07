"""Dimension configuration for requirement extraction."""

from __future__ import annotations

from typing import List

from .schemas import (
    BaseTimelineExtraction,
    DimensionConfig,
    FileCompositionExtraction,
    FormatTemplateExtraction,
    QualificationReviewExtraction,
    RiskContractExtraction,
    SubmissionChecklistExtraction,
    TechnicalScoringExtraction,
)


MAX_DIMENSION_BATCH_CHARS = 12000
PER_DIMENSION_TIMEOUT_SECONDS = 300
DEFAULT_DIMENSION_MAX_TOKENS = 3500
HIGH_RECALL_MAX_TOKENS = 8000


GROUP_CONFIGS: List[DimensionConfig] = [
    DimensionConfig(
        name="base_timeline",
        output_model=BaseTimelineExtraction,
        include_head=True,
        max_tokens=3500,
        batch_chars=18000,
        max_total_chars=36000,
        instruction="抽取基础项目信息与所有时间节点。包括项目名称、项目编号、采购人/招标人、代理机构、投标截止、开标、报名、递交、投标有效期等。",
    ),
    DimensionConfig(
        name="file_composition",
        output_model=FileCompositionExtraction,
        max_tokens=4500,
        batch_chars=16000,
        instruction=(
            "只抽取投标/响应/报价文件组成清单，尤其是投标文件格式/响应文件格式/报价文件格式章节中的完整层级目录，"
            "输出到 file_composition。即使原文没有'投标文件组成/应包括'导语，只要格式章节列出封面、报价表、资格证明材料、商务文件格式、技术响应文件格式、其他资料等格式/范本标题，也要抽取。"
            "必须按原文编号和缩进标注 outline_level 与 parent_name：中文序号'一、二、三、'开头的是 outline_level=1；"
            "括号中文'（一）（二）'开头的是 outline_level=2，parent_name 写最近的中文序号父项；"
            "括号数字'（1）（2）'开头的条目永远不能是 outline_level=1：若上文存在'（一）（二）'父项，则为 outline_level=3 且 parent_name 写该括号中文父项；否则为 outline_level=2 且 parent_name 写最近的中文序号父项；"
            "'格式X.Y'或'X.Y'点分编号按点分层级和原文缩进定级。outline_level 必须与原文编号/缩进一致，不要把子项拍平成一级，所有子项都必须填写直接 parent_name。"
            "只抽目录条目，不要把'按/按照/根据/依据/参照/对/投标人应/响应人须/见第X章'等开头的正文说明句当目录条目。"
            "如果某个目录条目本身是父项且原文在同一句中明确列出多个子材料，例如'报价函及应答函'、'资格证明文件：营业执照/登记证书/一般纳税人资格证明'、'信用记录：信用中国截图/企业信用信息公示系统截图'，必须同时输出父项和子项；子项 outline_level=父项+1，parent_name 写父项名称。"
            "如果目录条目明确引用附件/附表/附录，而对应附件正文列出了投标文件需要编写或提供的多个主题，必须保留该目录父项，并将这些主题输出为其子项。"
            "source_kind=attachment_body 的 reference_mentions 是同一附件编号在前文的引用证据；应结合这些证据判断其目录父项，父项名称保留原文，子项 parent_name 必须与输出的父项名称完全一致。"
            "附件中的表单字段、空格填写项、签字盖章栏、日期栏和普通正文段落不是子目录，不要拆分。"
            "对于'项目实施方案书应包括但不限于以下内容'后面的编号条目，应作为'项目实施方案书'的子项，不要把导语本身作为目录项。"
            "不要抽资格审查解释、评分标准、合同风险、技术服务正文。按原文格式章节清单逐项保留原名和顺序。"
        ),
    ),
    DimensionConfig(
        name="format_template",
        output_model=FormatTemplateExtraction,
        max_tokens=2500,
        batch_chars=12000,
        max_total_chars=18000,
        instruction="只抽取附件/格式/范本/表格/函件模板、签字盖章、密封装订、正副本份数等格式要求。输出 format_requirements。不要输出资格门槛、评分标准或合同条款。",
    ),
    DimensionConfig(
        name="qualification_review",
        output_model=QualificationReviewExtraction,
        max_tokens=3000,
        batch_chars=12000,
        max_total_chars=22000,
        instruction="抽取投标人资格/资质/财务/信用/业绩/人员等资格审查要求，输出 qualifications。它主要用于前端资格审查 Tab；除非原文明确说需提交某材料，否则不要输出材料清单。",
    ),
    DimensionConfig(
        name="submission_checklist",
        output_model=SubmissionChecklistExtraction,
        max_tokens=3000,
        batch_chars=8000,
        max_total_chars=12000,
        instruction="抽取招标书明确要求提交/提供/填写的材料清单，输出 material_checklist；同时抽取投标人特殊提交/承诺要求，输出 bidder_special_requirements。不要把项目服务地点、岗位人数、KPI、作业安排等技术服务正文抽成材料。",
    ),
    DimensionConfig(
        name="technical_scoring",
        output_model=TechnicalScoringExtraction,
        max_tokens=HIGH_RECALL_MAX_TOKENS,
        batch_chars=10000,
        max_total_chars=18000,
        instruction="抽取技术评分组: 1) technical_requirements 抽取技术/服务/采购需求、服务标准、人员配置、岗位、招聘、培训、考勤、工资社保、KPI/到岗率、作业安排、数量、时限、强制或推荐要求；2) scoring 抽取评分/评审标准、评分项、分值、评价条件、证明材料提示。",
    ),
    DimensionConfig(
        name="risk_contract",
        output_model=RiskContractExtraction,
        include_head=True,
        max_tokens=HIGH_RECALL_MAX_TOKENS,
        batch_chars=12000,
        max_total_chars=26000,
        instruction="抽取风险条款组: 1) 无效投标、废标、否决、不予受理、取消资格、逾期、超限价等条款; 2) 报价方式、最高限价、价格组成、税费、异常报价规则; 3) 投标/履约保证金金额和缴退/没收条件; 4) 合同、服务期、付款、验收、违约、赔偿、履约义务。",
    ),
]

# Backward-compatible name used by the Phase 2 validation script.
DIMENSION_CONFIGS = GROUP_CONFIGS
