"""Route tender sections to requirement extraction dimensions.

The navigator is intentionally separate from the extractors. It classifies
located tender sections once, then each extractor consumes only the tagged
sections it owns. This keeps extraction closer to a routing DAG and avoids
letting every extractor independently scan the whole tender.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


TAG_BASE_TIMELINE = "base_timeline"
TAG_FILE_COMPOSITION = "file_composition"
TAG_FORMAT_TEMPLATE = "format_template"
TAG_QUALIFICATION_REVIEW = "qualification_review"
TAG_SUBMISSION_CHECKLIST = "submission_checklist"
TAG_TECHNICAL_SCORING = "technical_scoring"
TAG_RISK_CONTRACT = "risk_contract"

_GENERIC_TIMELINE_DEADLINE_RE = re.compile(
    r"(?:提交|递交)?(?:投标|响应|报价|应答)?文件?(?:提交|递交)?截止时间|(?:投标|响应|报价|应答)(?:截止|文件截止)|提交截止时间"
)


def tag_requirement_sections(sections_payload: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return copies of sections with requirement_tags attached."""
    tagged: List[Dict[str, Any]] = []
    for item in sections_payload:
        next_item = dict(item)
        next_item["requirement_tags"] = route_section_for_requirements(item)
        tagged.append(next_item)
    return tagged


def route_section_for_requirements(item: Dict[str, Any]) -> List[str]:
    """Classify a located tender section into extraction dimensions.

    This is a deterministic navigator, not the final extractor. It uses strong
    section-level signals: title, relevance labels, composition-list phrases,
    format headings, scoring headings, and risk/contract headings.
    """
    title, relevance, content = _section_route_text(item)
    head = title + relevance
    body_head = content[:2500]
    whole = head + body_head
    tags: List[str] = []

    def add(tag: str) -> None:
        if tag not in tags:
            tags.append(tag)

    if _has_base_timeline_signal(head, whole):
        add(TAG_BASE_TIMELINE)

    if _has_file_composition_signal(whole, title):
        add(TAG_FILE_COMPOSITION)
        add(TAG_SUBMISSION_CHECKLIST)

    if _has_format_template_signal(head, whole):
        add(TAG_FORMAT_TEMPLATE)

    if _has_qualification_signal(head):
        add(TAG_QUALIFICATION_REVIEW)

    if _has_qualification_material_signal(whole):
        add(TAG_QUALIFICATION_REVIEW)
        add(TAG_SUBMISSION_CHECKLIST)

    if _has_submission_material_signal(whole):
        add(TAG_SUBMISSION_CHECKLIST)

    if _has_technical_or_scoring_signal(head, whole):
        add(TAG_TECHNICAL_SCORING)

    if _has_risk_contract_signal(head, whole):
        add(TAG_RISK_CONTRACT)

    return tags


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _contains_any(text: str, needles: Tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _section_route_text(item: Dict[str, Any]) -> Tuple[str, str, str]:
    title = _compact(str(item.get("title") or ""))
    relevance = _compact(str(item.get("relevance") or ""))
    content = _compact(str(item.get("content") or ""))
    return title, relevance, content


def _has_base_timeline_signal(head: str, whole: str = "") -> bool:
    if _contains_any(
        head,
        (
            "招标公告",
            "采购公告",
            "投标邀请",
            "磋商邀请",
            "比选公告",
            "邀请书",
            "供应商须知前附表",
            "投标人须知前附表",
            "采购须知前附表",
            "供应商须知",
            "投标人须知",
            "采购须知",
            "前附表",
            "总则",
            "项目概况",
            "基本情况",
        ),
    ):
        return True
    return _contains_any(
        whole,
        (
            "采购代理机构",
            "招标代理机构",
            "代理机构",
            "投标有效期",
            "投标报价有效期",
            "报价有效期",
            "响应有效期",
            "90天内有效",
            "90天（含90天）",
            "提交投标文件截止时间",
            "投标文件截止时间",
            "投标截止",
            "递交截止",
            "开标时间",
            "开启时间",
            "报名时间",
            "获取采购文件时间",
        ),
    ) or bool(_GENERIC_TIMELINE_DEADLINE_RE.search(_compact(whole)))


def _has_file_composition_signal(text: str, title: str = "") -> bool:
    composition_signals = (
        "投标文件组成",
        "响应文件组成",
        "报价文件组成",
        "投标文件由以下组成",
        "响应文件由以下组成",
        "报价文件由以下组成",
        "投标文件由以下部分组成",
        "响应文件由以下部分组成",
        "报价文件由以下部分组成",
        "投标文件应包括",
        "响应文件应包括",
        "报价文件应包括",
        "投标文件应包括下列",
        "响应文件应包括下列",
        "报价文件应包括下列",
        "文件组成清单",
        "索引目录表",
        "投标文件目录",
        "响应文件目录",
        "包括但不限于下列内容",
    )
    if not _contains_any(text, composition_signals):
        return False

    # A commitment/statement form may mention "响应文件应包括..." in its body,
    # but it is a single material, not the tender's file-composition checklist.
    title_text = _compact(title)
    single_material_heads = (
        "承诺函",
        "承 诺 函",
        "声明函",
        "声 明 函",
        "协议",
        "偏离表",
    )
    checklist_title_terms = (
        "文件组成",
        "组成清单",
        "索引目录",
        "投标文件目录",
        "响应文件目录",
        "报价文件目录",
        "应包括",
        "由以下",
        "下列内容",
    )
    if _contains_any(title_text, single_material_heads) and not _contains_any(title_text, checklist_title_terms):
        return False

    return True


def _has_format_template_signal(head: str, whole: str) -> bool:
    if _contains_any(
        head,
        (
            "投标文件格式",
            "响应文件格式",
            "报价文件格式",
            "投标文件模板",
            "响应文件模板",
            "附件格式",
            "格式文件",
            "格式要求",
            "范本",
        ),
    ):
        return True
    if _contains_any(head, ("附件", "附表", "表格")) and _contains_any(
        whole, ("格式", "填写", "模板", "按附件")
    ):
        return True
    return _contains_any(
        whole,
        (
            "正本",
            "副本",
            "电子版",
            "密封",
            "封装",
            "装订",
            "逐页盖章",
            "骑缝章",
        ),
    ) and _contains_any(whole, ("投标文件", "响应文件", "报价文件"))


def _has_qualification_signal(head: str) -> bool:
    return _contains_any(
        head,
        (
            "资格要求",
            "资格条件",
            "供应商资格",
            "投标人资格",
            "申请人资格",
            "资格审查",
            "符合性审查",
            "资格性审查",
        ),
    )


def _has_submission_material_signal(text: str) -> bool:
    submit_terms = (
        "提交",
        "提供",
        "须附",
        "需附",
        "应附",
        "须提供",
        "需提供",
        "应提供",
        "应提交",
        "须提交",
        "需提交",
        "加盖公章",
        "复印件",
        "原件",
    )
    material_terms = (
        "材料",
        "资料",
        "证明",
        "证书",
        "许可证",
        "执照",
        "报告",
        "承诺函",
        "声明函",
        "授权",
        "报价函",
        "报价表",
        "偏离表",
        "业绩",
        "截图",
        "保证金",
        "账户",
        "中小企业",
    )
    return _contains_any(text, submit_terms) and _contains_any(text, material_terms)


def _has_qualification_material_signal(text: str) -> bool:
    qualification_terms = (
        "营业执照",
        "许可证",
        "审计报告",
        "财务报表",
        "社保",
        "信用中国",
        "失信被执行人",
        "同类业绩",
        "类似业绩",
    )
    return _contains_any(text, qualification_terms) and _has_submission_material_signal(text)


def _has_technical_or_scoring_signal(head: str, whole: str) -> bool:
    if _contains_any(
        head,
        (
            "技术要求",
            "服务要求",
            "用户需求",
            "采购需求",
            "技术规格",
            "服务内容",
            "服务标准",
            "人员配置",
            "岗位要求",
            "评标办法",
            "评审办法",
            "评分标准",
            "综合评分",
            "技术评分",
            "商务评分",
            "价格评分",
        ),
    ):
        return True
    return _contains_any(
        whole,
        (
            "评分标准",
            "评分办法",
            "分值",
            "得分",
            "评审因素",
            "评审标准",
        ),
    ) and _contains_any(whole, ("技术", "商务", "价格", "业绩", "方案"))


def _has_risk_contract_signal(head: str, whole: str) -> bool:
    if _contains_any(
        head,
        (
            "无效投标",
            "废标",
            "否决投标",
            "不予受理",
            "投标保证金",
            "履约保证金",
            "报价要求",
            "最高限价",
            "合同条款",
            "合同格式",
            "付款方式",
            "违约责任",
            "履约义务",
            "服务期",
        ),
    ):
        return True
    return _contains_any(
        whole,
        (
            "无效",
            "废标",
            "否决",
            "不予受理",
            "逾期送达",
            "高于最高限价",
            "保证金",
            "付款",
            "违约",
            "赔偿",
        ),
    ) and _contains_any(whole, ("投标", "响应", "报价", "合同", "供应商"))
