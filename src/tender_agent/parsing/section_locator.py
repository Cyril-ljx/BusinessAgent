"""
关键章节定位(智能版 + 内容空回退)。

★ V10.1 关键修复:
   有些招标书在开头有一个"总目录"页,只列章节标题不含内容。
   LLM 定位时容易定到这个目录页,导致取不到内容。

   修复:取章节内容时,如果当前位置内容为空,
        自动在文档后面找同名(或包含同名)的章节作为真正内容。
"""
import os
import re
from typing import Any, List

from loguru import logger
from pydantic import BaseModel, Field

from .docx_parser import ParsedDoc, Section
from tender_agent.understanding.index_table_composition import looks_like_index_table_composition


class LocatedSection(BaseModel):
    section_id: str = Field(description="章节编号,如 '1', '2.3', '附件三'")
    section_title: str = Field(description="章节标题")
    relevance: str = Field(description="该章节与投标书目录信息的相关性")


class LocateResult(BaseModel):
    document_type: str = Field(
        description="文件类型,如 '招标文件 / 磋商文件 / 比选文件 / 询价文件'"
    )
    located_sections: list[LocatedSection] = Field(
        description="所有相关章节"
    )


_GENERIC_TIMELINE_DEADLINE_RE = re.compile(
    r"(?:提交|递交)?(?:投标|响应|报价|应答)?文件?(?:提交|递交)?截止时间|(?:投标|响应|报价|应答)(?:截止|文件截止)|提交截止时间"
)


LOCATOR_PROMPT = """你是资深招投标专家。下面是一份招标类文件的章节目录,请找出所有与"**投标方需要在响应文件中提交什么内容**"相关的章节。

【背景】
这份文件可能是:招标书 / 磋商文件 / 比选文件 / 询价文件 / 谈判文件 等任意类型。
不同类型用词不同,但都需要投标/磋商/比选方提供"响应文件"。

【任务】
请找出所有**可能描述以下信息**的章节(可以是多个,也可能只有一个):
1. 响应文件应该包含哪些大类内容(如"投标文件构成"、"响应文件组成"、"比选申请书格式")
2. 投标方需要具备的资质门槛 → 通常对应一份份具体证明文件(如"供应商资格要求"、"投标人资质")
3. 评审 / 评分细则 → 反推哪些方案/材料需要在响应文件里写(如"评审办法"、"评分标准")
4. 提供的表单范本 / 附件参考(如"响应文件格式"、"附件参考"、"附件一/二/三")

【⚠️ 重要避坑】
- 文档开头通常有一个"总目录索引"页(只列章节名,没有实际内容),不要定位到那里
- 应该定位到**真正的章节实体**(在目录索引之后的位置)
- 如果同一个章节标题在文档里出现多次,优先选**靠后**的那个(那个是真正的内容)

【其他规则】
- 不要用关键词死板匹配,根据章节标题语义判断
- 同一份招标书可能有 1 个、3 个、5 个相关章节,数量不固定
- 也可能某些方面没有专门章节(如简单询价单可能没有"评分细则"),不要硬找
- 一定要返回**章节的实际编号**(如 "6"、"附件三")和原始标题

【目录】
{toc}

请按 JSON 格式返回结果。
"""


def locate_route_sections_llm(parsed: ParsedDoc, llm_caller) -> list[LocatedSection]:
    """用 LLM 定位投标书目录相关章节。"""
    toc_lines = []
    for sec in parsed.flat_sections:
        # Level-3 headings often contain concrete attachment/form items.
        # Hiding them makes the locator miss "response file format" details.
        if sec.level > _locator_toc_level_limit():
            continue
        indent = "  " * (sec.level - 1)
        toc_lines.append(f"{indent}{sec.id}  {sec.title}")

    toc_text = "\n".join(toc_lines)

    if len(toc_lines) < 5:
        logger.warning(f"[locator] 目录只有 {len(toc_lines)} 个章节,可能解析不完整")

    logger.info(f"[locator] 目录长度 {len(toc_text)} 字,共 {len(toc_lines)} 个章节标题")

    prompt = LOCATOR_PROMPT.format(toc=toc_text)

    timeout_seconds = _locator_llm_timeout_seconds()
    max_tokens = _locator_max_tokens_override()
    logger.info(
        f"[locator] LLM timeout={timeout_seconds}s, max_tokens={max_tokens}"
    )

    try:
        call_kwargs: dict[str, Any] = {
            "timeout": timeout_seconds,
            "network_max_retries": _locator_network_max_retries(),
        }
        if max_tokens is not None:
            call_kwargs["max_tokens"] = max_tokens
        result: LocateResult = llm_caller(prompt, LocateResult, **call_kwargs)
        logger.info(
            f"[locator] ✓ 文件类型:{result.document_type},"
            f"定位到 {len(result.located_sections)} 个相关章节"
        )
        for sec in result.located_sections:
            logger.info(f"  - {sec.section_id} {sec.section_title} ({sec.relevance})")
        return _augment_located_sections(parsed, result.located_sections)
    except Exception as e:
        logger.error(f"[locator] ✗ LLM 定位失败: {e}")
        return []


def locate_explicit_composition_sections(parsed: ParsedDoc) -> list[LocatedSection]:
    """Locate authoritative composition evidence without an LLM call.

    This path only reuses existing high-confidence structural detectors:
    explicit directory blocks, index tables, submission checklists, and body
    composition parts. The existing augmentation step then adds broader
    qualification, scoring, and timeline evidence for requirement extraction.
    """
    located: list[LocatedSection] = []
    seen_ids: set[str] = set()

    def add(sec: Section, relevance: str) -> None:
        section_id = str(sec.id or "")
        if not section_id or section_id in seen_ids:
            return
        seen_ids.add(section_id)
        located.append(
            LocatedSection(
                section_id=section_id,
                section_title=sec.title,
                relevance=relevance,
            )
        )

    for sec in _find_plain_file_directory_sections(parsed):
        add(sec, "structured-source: explicit file directory")

    for sec in parsed.flat_sections or []:
        if looks_like_index_table_composition(
            {"title": sec.title or "", "content": sec.content or ""}
        ):
            add(sec, "structured-source: file index table")

    for sec in _find_authoritative_checklist_sections(parsed):
        add(sec, "structured-source: submission checklist")

    for sec in _find_body_composition_part_sections(parsed):
        add(sec, "structured-source: body composition part")

    if not located:
        return []

    logger.info(
        "[locator] structured composition source found; skipping locator LLM, "
        f"sources={len(located)}"
    )
    augmented = _augment_located_sections(parsed, located)
    ordered: list[LocatedSection] = []
    ordered_ids: set[str] = set()
    for item in [*located, *augmented]:
        if item.section_id in ordered_ids:
            continue
        ordered_ids.add(item.section_id)
        ordered.append(item)
    return ordered


def locate_route_sections_fallback(parsed: ParsedDoc, max_items: int = 8) -> list[LocatedSection]:
    """LLM 定位失败时的关键词兜底，避免整单中断。"""
    keywords = (
        "投标文件", "响应文件", "文件格式", "附件", "评审", "评分",
        "资格", "资质", "申请书", "比选", "磋商",
    )
    picked: list[LocatedSection] = []
    seen: set[str] = set()

    for sec in parsed.flat_sections:
        if sec.level > _locator_toc_level_limit():
            continue
        title = (sec.title or "").strip()
        if not title:
            continue
        normalized = _normalize_title(title)
        if normalized in seen:
            continue
        if any(k in title for k in keywords):
            seen.add(normalized)
            picked.append(
                LocatedSection(
                    section_id=sec.id,
                    section_title=sec.title,
                    relevance="fallback: 标题关键词匹配",
                )
            )
        if len(picked) >= max_items:
            break

    if picked:
        logger.warning(f"[locator:fallback] 启用关键词兜底，命中 {len(picked)} 个章节")
        for sec in picked:
            logger.warning(f"  - {sec.section_id} {sec.section_title}")
    else:
        logger.warning("[locator:fallback] 未命中任何关键词章节")
    return _augment_located_sections(parsed, picked)


def _add_located_section(
    additions: list[LocatedSection],
    seen: set[str],
    seen_ids: set[str],
    sec: Section,
    relevance: str,
) -> bool:
    normalized_key = _normalize_title(sec.id + sec.title)
    if normalized_key in seen or sec.id in seen_ids:
        return False
    seen.add(normalized_key)
    seen_ids.add(sec.id)
    additions.append(
        LocatedSection(
            section_id=sec.id,
            section_title=sec.title,
            relevance=relevance,
        )
    )
    return True


def _compact_locator_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _looks_like_plain_file_directory_heading_text(text: str) -> bool:
    compact = _compact_locator_text(text)
    if not compact or len(compact) > 36:
        return False
    if any(term in compact for term in ("评分", "评审", "索引", "页码", "总目录", "目录索引")):
        return False
    return compact in {
        "投标文件目录",
        "响应文件目录",
        "报价文件目录",
        "应答文件目录",
        "投标目录",
        "响应目录",
        "报价目录",
    }


def _plain_directory_item_key(text: str) -> str:
    value = re.sub(r"^\s*\d+[、.．)]\s*", "", str(text or "").strip())
    value = re.sub(r"[（(]\s*(?:必填|选填|可选|必须|非必须)\s*[）)]", "", value)
    value = re.sub(r"\s+", "", value)
    return value.strip("：:；;。,.，、")


def _looks_like_plain_file_directory_row_text(text: str) -> bool:
    value = str(text or "").strip()
    compact = _compact_locator_text(value)
    if not compact or len(compact) > 110:
        return False
    if _looks_like_plain_file_directory_heading_text(value):
        return False
    if compact.startswith(("致：", "致:", "根据贵方", "我方", "本公司", "投标人名称", "法人或授权代表签字")):
        return False
    if any(term in compact for term in ("应包括但不限于", "包括但不限于", "应包括下列内容", "包括下列内容")):
        return False
    if len(compact) > 55 and any(mark in value for mark in ("，", "；", "。", "：")):
        return False
    return True


def _find_plain_file_directory_sections(parsed: ParsedDoc) -> list[Section]:
    """Promote explicit front matter file-directory blocks to source sections."""
    blocks = list(parsed.block_index or [])
    found: list[Section] = []
    existing_ids = {str(sec.id or "") for sec in parsed.flat_sections or []}
    for idx, block in enumerate(blocks):
        heading = str(block.get("text") or "").strip()
        if not _looks_like_plain_file_directory_heading_text(heading):
            continue
        start_anchor = str(block.get("anchor") or f"p{idx}")
        try:
            start_idx = int(start_anchor[1:]) if start_anchor.startswith("p") else idx
        except ValueError:
            start_idx = idx
        candidate: list[tuple[int, dict, str]] = []
        seen_keys: set[str] = set()
        for next_pos, next_block in enumerate(blocks[idx + 1 :], start=idx + 1):
            text = str(next_block.get("text") or "").strip()
            compact = _compact_locator_text(text)
            if not compact:
                continue
            if candidate and _looks_like_plain_file_directory_heading_text(text):
                break
            key = _plain_directory_item_key(text)
            if candidate and key in seen_keys and not any(mark in compact for mark in ("必填", "选填", "可选")):
                break
            if candidate and compact in {"投标函", "响应函", "报价函", "投标文件", "响应文件", "报价文件"}:
                break
            if not _looks_like_plain_file_directory_row_text(text):
                if candidate:
                    break
                if len(compact) > 60:
                    break
                continue
            if key in seen_keys:
                continue
            seen_keys.add(key)
            candidate.append((next_pos, next_block, text))
        if len(candidate) < 5:
            continue
        end_pos = candidate[-1][0]
        section_id = f"__plain_file_directory__p{start_idx}"
        if section_id in existing_ids:
            continue
        content = "\n".join([heading] + [item[2] for item in candidate])
        sec = Section(
            id=section_id,
            title=heading,
            level=2,
            content=content,
            start_item_idx=start_idx,
            end_item_idx=end_pos,
        )
        parsed.flat_sections.append(sec)
        existing_ids.add(section_id)
        found.append(sec)
    return found


def _augment_located_sections(
    parsed: ParsedDoc,
    located: list[LocatedSection],
    max_extra: int = 12,
) -> list[LocatedSection]:
    """扩展定位上下文，避免只把附件表单交给 composer。

    这里不直接生成投标目录，只把“组成、资格、需求、评分、无效响应”等原文段落
    作为上下文补给 composer，由 composer 再按原文抽取目录。
    """
    seen = {_normalize_title(item.section_id + item.section_title) for item in located}
    seen_ids = {str(item.section_id or "") for item in located}
    additions: list[LocatedSection] = []

    # Explicit front-matter file directories are authoritative outline sources.
    # They may sit between parsed headings, so promote their block range before
    # broader checklist/template sections can win by accident.
    for sec in _find_plain_file_directory_sections(parsed):
        _add_located_section(additions, seen, seen_ids, sec, "auto-augment: 投标文件目录原文块")

    # Authoritative checklist sections should be seen before risk/scoring
    # context. This only adds high-confidence checklist sources and leaves the
    # existing broad context rules below untouched.
    for sec in _find_authoritative_checklist_sections(parsed):
        _add_located_section(additions, seen, seen_ids, sec, "auto-augment: 权威提交清单章节")

    # Basic announcement / instructions / schedule sections often carry
    # purchaser, agency, deadline, opening time, and validity-period data.
    # Keep them available for requirement extraction even when the LLM locator
    # focused on composition/scoring chapters.
    for sec in _find_base_timeline_sections(parsed):
        _add_located_section(additions, seen, seen_ids, sec, "auto-augment: 基础信息与时间章节")

    # Some tenders place validity-period or explicit schedule clauses inside
    # short attachment/form subsections such as "应答"/"承诺函". Those sections
    # are easy for the generic locator to miss, but requirement extraction
    # still needs them for base_timeline.
    for sec in _find_timeline_evidence_sections(parsed):
        _add_located_section(additions, seen, seen_ids, sec, "auto-augment: 时限/有效期证据章节")

    # The bid-file index table is an authoritative outline source. Keep it in
    # located_sections deterministically so composer can copy it without an LLM.
    for sec in parsed.flat_sections:
        if not _looks_like_bid_index_table_section(sec):
            continue
        if _add_located_section(additions, seen, seen_ids, sec, "auto-augment: 响应文件索引目录表"):
            break

    # Some tenders have a front TOC entry such as "第五章 投标文件组成 31"
    # and the real body immediately later as "第一部分 商务部分 / 第二部分 技术部分".
    # Add those real body parts so source-backed extraction sees the full list,
    # not just the shallow TOC rows.
    for sec in _find_body_composition_part_sections(parsed):
        _add_located_section(additions, seen, seen_ids, sec, "auto-augment: 正文投标文件组成分部")

    rules: list[tuple[tuple[str, ...], tuple[str, ...], str]] = [
        (("报价文件", "响应文件", "投标文件"), ("截止", "提交方式", "密封", "保密", "有效性", "无效", "废标"), "响应文件组成要求"),
        (("供应商资格", "报价人资格", "投标人资格", "资格要求"), tuple(), "资格审查要求"),
        (("项目服务内容", "项目服务要求", "采购需求", "服务内容"), tuple(), "项目服务要求"),
        (("项目报价", "预算金额", "最高限价", "报价及模式"), tuple(), "报价与预算要求"),
        (("履约保证金", "保证金"), tuple(), "履约资金要求"),
        (("有效性认定", "无效报价", "废标", "否决"), tuple(), "废标/无效响应风险"),
        (("综合评分", "评分标准", "评审办法"), tuple(), "评分标准"),
    ]

    for include_words, exclude_words, relevance in rules:
        for sec in parsed.flat_sections:
            title = (sec.title or "").strip()
            if not title:
                continue
            if sec.id in seen_ids:
                continue
            if not any(word in title for word in include_words):
                continue
            if exclude_words and any(word in title for word in exclude_words):
                continue
            # 优先补真正有正文或有子项的章节，避免只补目录页空壳。
            if not (sec.content.strip() or sec.children):
                continue
            _add_located_section(additions, seen, seen_ids, sec, f"auto-augment: {relevance}")
            break
        if len(additions) >= max_extra:
            break

    for sec in parsed.flat_sections:
        if len(additions) >= max_extra:
            break
        title = (sec.title or "").strip()
        if not _looks_like_material_requirement_title(title):
            continue
        _add_located_section(additions, seen, seen_ids, sec, "auto-augment: 明确素材要求")

    if additions:
        logger.info(f"[locator] 扩展定位上下文 {len(additions)} 个")
        for sec in additions:
            logger.info(f"  + {sec.section_id} {sec.section_title} ({sec.relevance})")

    # 把补充章节放前面，让 composer 先看到正文要求，再看附件格式。
    return additions + located


def _looks_like_material_requirement_title(title: str) -> bool:
    title = re.sub(r"\s+", "", title or "")
    if not title or len(title) > 60:
        return False
    include = (
        "营业执照", "许可证", "审计报告", "财务报表", "纳税", "社保",
        "业绩", "同类项目", "信用", "资质证书", "体系认证", "ISO",
    )
    exclude = ("附件", "授权委托", "法定代表人", "负责人证明", "报价函", "承诺函")
    return any(k in title for k in include) and not any(k in title for k in exclude)


def _looks_like_bid_index_table_section(sec: Section) -> bool:
    title = re.sub(r"\s+", "", sec.title or "")
    if not title:
        return False
    if not any(k in title for k in ("详细评审索引目录表", "索引目录表", "响应文件索引", "投标文件索引", "投标文件所需资料")):
        return False
    content = re.sub(r"\s+", "", sec.content or "")
    if not content:
        return False
    if "文件类型" not in content or "文件名称" not in content:
        return False
    if not any(k in content for k in ("供应商应提交", "资格性及符合性资料", "商务文件", "技术文件", "价格部分", "初审文件", "其他文件")):
        return False
    return True


def _find_authoritative_checklist_sections(parsed: ParsedDoc) -> list[Section]:
    """Find high-confidence source sections that enumerate submission files.

    This is deliberately narrow: it promotes explicit checklist/form-composition
    sections ahead of risk/scoring context, but does not replace the existing
    locator context collection.
    """
    scored: list[tuple[int, int, Section]] = []
    for idx, sec in enumerate(parsed.flat_sections or []):
        score = _authoritative_checklist_section_score(sec)
        if score <= 0:
            continue
        scored.append((score, idx, sec))
    scored.sort(key=lambda item: (-item[0], -int(item[2].start_item_idx or 0), item[1]))
    selected: list[Section] = []
    seen_titles: set[str] = set()
    for _score, _idx, sec in scored:
        title_key = _checklist_title_family(sec.title)
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        selected.append(sec)
        if len(selected) >= 3:
            break
    return selected


def _find_base_timeline_sections(parsed: ParsedDoc) -> list[Section]:
    """Find announcement/instruction sections that carry base info and timeline."""
    scored: list[tuple[int, int, Section]] = []
    for idx, sec in enumerate(parsed.flat_sections or []):
        score = _base_timeline_section_score(sec)
        if score <= 0:
            continue
        scored.append((score, idx, sec))
    scored.sort(key=lambda item: (-item[0], -int(item[2].start_item_idx or 0), item[1]))
    selected: list[Section] = []
    seen_titles: set[str] = set()
    for _score, _idx, sec in scored:
        title_key = _base_timeline_title_family(sec.title)
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        selected.append(sec)
        if len(selected) >= 4:
            break
    return selected


def _find_timeline_evidence_sections(parsed: ParsedDoc) -> list[Section]:
    """Find compact body sections that explicitly carry dates or validity phrases."""
    scored: list[tuple[int, int, Section]] = []
    for idx, sec in enumerate(parsed.flat_sections or []):
        score = _timeline_evidence_section_score(sec)
        if score <= 0:
            continue
        scored.append((score, idx, sec))
    scored.sort(key=lambda item: (-item[0], -int(item[2].start_item_idx or 0), item[1]))
    selected: list[Section] = []
    seen_titles: set[str] = set()
    for _score, _idx, sec in scored:
        title_key = _normalize_title(sec.title)
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        selected.append(sec)
        if len(selected) >= 4:
            break
    return selected


def _base_timeline_section_score(sec: Section) -> int:
    title = re.sub(r"\s+", "", sec.title or "")
    if not title:
        return 0
    if any(term in title for term in ("评审", "评分", "废标", "否决", "合同", "投标文件格式", "响应文件格式", "报价文件格式")):
        return 0

    content = _collect_content(sec, max_chars=12000)
    compact_content = re.sub(r"\s+", "", content)
    text = title + compact_content[:5000]
    signal_terms = (
        "采购人",
        "招标人",
        "代理机构",
        "采购代理机构",
        "项目编号",
        "招标编号",
        "采购编号",
        "投标截止",
        "截止时间",
        "开标时间",
        "开启时间",
        "递交",
        "提交响应文件",
        "投标有效期",
        "报价有效期",
        "获取采购文件",
        "报名时间",
        "开标地点",
    )
    signal_count = sum(1 for term in signal_terms if term in text)
    if _GENERIC_TIMELINE_DEADLINE_RE.search(text):
        signal_count += 2

    score = 0
    if any(term in title for term in ("投标人须知前附表", "供应商须知前附表", "采购须知前附表")):
        score = 135
    elif any(term in title for term in ("招标公告", "采购公告", "投标邀请", "磋商邀请", "比选公告", "邀请书")):
        score = 125
    elif any(term in title for term in ("投标人须知", "供应商须知", "采购须知")):
        score = 118
    elif "前附表" in title:
        score = 108
    elif any(term in title for term in ("项目概况", "基本情况")):
        score = 85
    elif "总则" in title:
        score = 60
    elif _GENERIC_TIMELINE_DEADLINE_RE.search(title):
        score = 104
    else:
        return 0

    if score <= 60 and signal_count == 0:
        return 0
    if score < 100 and signal_count == 0:
        return 0
    return score + min(signal_count, 6) * 10


def _timeline_evidence_section_score(sec: Section) -> int:
    title = re.sub(r"\s+", "", sec.title or "")
    content = _collect_content(sec, max_chars=5000)
    compact = re.sub(r"\s+", "", content)
    combined = title + compact
    if not combined:
        return 0
    if any(term in title for term in ("评审", "评分", "废标", "否决", "合同", "目录", "索引")):
        return 0

    score = 0
    validity_terms = ("投标有效期", "投标报价有效期", "报价有效期", "响应有效期", "90天内有效", "90天（含90天）", "90天")
    deadline_terms = ("提交投标文件截止时间", "投标文件截止时间", "投标截止", "递交截止", "提交响应文件截止", "报价截止时间")
    open_terms = ("开标时间", "开启时间", "响应文件开启", "报价开启")
    if any(term in combined for term in validity_terms):
        score += 120
    if any(term in combined for term in deadline_terms):
        score += 80
    if any(term in combined for term in open_terms):
        score += 80
    if _GENERIC_TIMELINE_DEADLINE_RE.search(combined):
        score += 110
    if any(term in title for term in ("应答", "应答函", "报价函", "承诺函", "响应文件递交", "递交", "时间")):
        score += 25
    if len(compact) > 3000:
        score -= 30
    return score if score >= 100 else 0


def _base_timeline_title_family(title: str) -> str:
    compact = re.sub(r"\s+", "", title or "")
    compact = re.sub(r"\d+$", "", compact)
    compact = compact.replace("\t", "")
    for marker in (
        "投标人须知前附表",
        "供应商须知前附表",
        "采购须知前附表",
        "招标公告",
        "采购公告",
        "投标邀请",
        "磋商邀请",
        "比选公告",
        "邀请书",
        "投标人须知",
        "供应商须知",
        "采购须知",
        "前附表",
        "项目概况",
        "基本情况",
        "总则",
    ):
        if marker in compact:
            return marker
    return compact


def _normalize_checklist_title(title: str) -> str:
    compact = re.sub(r"\s+", "", title or "")
    return re.sub(r"(投标|响应|报价)文件的(组成|格式)", r"\1文件\2", compact)


def _authoritative_checklist_section_score(sec: Section) -> int:
    title = _normalize_checklist_title(sec.title)
    if not title:
        return 0
    if any(term in title for term in ("保证金", "废标", "否决", "无效", "评分", "评审", "澄清", "合同")):
        return 0

    content = _collect_content(sec, max_chars=14000)
    compact_content = re.sub(r"\s+", "", content)
    text = title + compact_content[:4000]
    has_title_anchor = any(
        term in title
        for term in (
            "投标文件格式",
            "响应文件格式",
            "报价文件格式",
            "投标文件组成",
            "响应文件组成",
            "报价文件组成",
            "报价文件",
            "报价书",
        )
    )
    has_body_anchor = "报价书的编写要求" in text or "按下列内容和顺序编写" in text
    if not (has_title_anchor or has_body_anchor):
        return 0

    score = 0
    if any(term in title for term in ("投标文件格式", "响应文件格式", "报价文件格式")):
        score += 120
    if any(term in title for term in ("投标文件组成", "响应文件组成", "报价文件组成", "报价文件", "报价书")):
        score += 110
    if "报价书的编写要求" in text:
        score += 180
    if "按下列内容和顺序编写" in text:
        score += 120
    if "目录" in compact_content[:500]:
        score += 80

    material_score = _material_heading_sequence_score(content)
    score += material_score * 35

    if _looks_like_front_toc_shell(sec, content):
        score -= 140
    if any(term in compact_content[:1200] for term in ("电子招投标系统", "工具软件下载", "电子投标文件编制系统")):
        score -= 80

    if score < 220:
        return 0
    if material_score < 4 and "按下列内容和顺序编写" not in text:
        return 0
    return score


def _material_heading_sequence_score(content: str) -> int:
    score = 0
    seen_ordinals: set[str] = set()
    material_terms = (
        "投标函",
        "响应函",
        "报价函",
        "证明",
        "授权",
        "委托书",
        "协议",
        "保证金",
        "资格审查",
        "偏差表",
        "报价表",
        "服务方案",
        "其他资料",
        "承诺书",
        "财务报表",
        "银行账户",
        "技术响应",
        "项目实施方案",
        "组织架构",
        "资质",
        "信用记录",
        "合同主要条款",
    )
    for raw in str(content or "").splitlines()[:80]:
        line = raw.strip()
        if not line:
            continue
        compact = re.sub(r"\s+", "", line)
        if len(compact) > 120:
            continue
        ordinal = re.match(r"^#{0,3}\s*([一二三四五六七八九十]+)[、.．]", line)
        parenthesized = re.match(r"^#{0,3}\s*[（(]\s*(\d{1,2})\s*[）)]", line)
        dotted = re.match(r"^#{0,3}\s*(\d+(?:\.\d+){1,4})\s*", line)
        if not (ordinal or parenthesized or dotted):
            continue
        if not any(term in compact for term in material_terms):
            continue
        key = ordinal.group(1) if ordinal else parenthesized.group(1) if parenthesized else dotted.group(1)
        if key in seen_ordinals:
            continue
        seen_ordinals.add(key)
        score += 1
    return score


def _looks_like_front_toc_shell(sec: Section, content: str) -> bool:
    title = sec.title or ""
    own_content = re.sub(r"\s+", "", sec.content or "")
    compact = re.sub(r"\s+", "", content[:1600])
    if re.search(r"\s+\d+\s*$", title) or re.search(r"\t\d+\s*$", title):
        if own_content in {"目录", "目录87"} or "电子招投标系统" in compact:
            return True
    return False


def _checklist_title_family(title: str) -> str:
    compact = _normalize_checklist_title(title)
    compact = re.sub(r"\d+$", "", compact)
    compact = compact.replace("\t", "")
    if "报价书的编写要求" in compact:
        return "报价书的编写要求"
    for marker in ("投标文件格式", "响应文件格式", "报价文件格式", "投标文件组成", "响应文件组成", "报价文件组成"):
        if marker in compact:
            return marker
    return compact


def _trim_authoritative_checklist_content(content: str, title: str = "") -> str:
    text = str(content or "")
    if not text.strip():
        return text

    quote_idx = text.find("报价书的编写要求")
    if quote_idx >= 0:
        start = text.rfind("\n", 0, quote_idx)
        start = 0 if start < 0 else start + 1
        end_candidates = [
            pos
            for marker in ("\n第五条", "\n第六条")
            for pos in [text.find(marker, quote_idx)]
            if pos > quote_idx
        ]
        end = min(end_candidates) if end_candidates else len(text)
        return text[start:end].strip()

    lines = text.splitlines()
    toc_index = None
    for idx, raw in enumerate(lines[:30]):
        compact = re.sub(r"\s+", "", raw or "")
        if compact in {"目录", "##目录"} or compact.endswith("目录"):
            toc_index = idx
            break
    if toc_index is None:
        return text

    picked: list[str] = []
    seen_ordinals: set[str] = set()
    item_count = 0
    for raw in lines[toc_index + 1 :]:
        line = str(raw or "").strip()
        if not line:
            continue
        compact = re.sub(r"\s+", "", line)
        ordinal = re.match(r"^#{0,3}\s*([一二三四五六七八九十百零\d]+[一二三四五六七八九十]*)[、.．]", line)
        if not ordinal:
            ordinal = re.match(r"^#{0,3}\s*([一二三四五六七八九十百零\d]+[一二三四五六七八九十]*)、", line)
        if ordinal:
            key = ordinal.group(1)
            if key in seen_ordinals and item_count >= 5:
                break
            seen_ordinals.add(key)
            if "其他资料" in compact and ("：" in line or ":" in line):
                line = re.split(r"[:：]", line, maxsplit=1)[0]
            picked.append(line)
            item_count += 1
            continue
        if item_count >= 5 and line.startswith("##"):
            break
        if item_count >= 5 and len(compact) > 80:
            break
    if item_count < 5:
        return text

    title_compact = re.sub(r"\s+", "", title or "")
    anchor = "响应文件" if "响应文件" in title_compact else "报价文件" if "报价文件" in title_compact else "投标文件"
    return f"{anchor}包括下列内容：\n" + "\n".join(picked)


def _find_body_composition_part_sections(parsed: ParsedDoc) -> list[Section]:
    """Find body business/technical parts after a file-composition chapter."""
    parts: list[Section] = []
    flat = list(parsed.flat_sections or [])
    for idx, wrapper in enumerate(flat):
        title = re.sub(r"\s+", "", wrapper.title or "")
        if not any(k in title for k in ("投标文件组成", "响应文件组成", "报价文件组成", "报价书组成")):
            continue
        if wrapper.start_item_idx is None:
            continue
        current_parts: list[Section] = []
        for sec in flat[idx + 1 :]:
            if sec.start_item_idx is None or sec.start_item_idx <= wrapper.start_item_idx:
                continue
            sec_title = re.sub(r"\s+", "", sec.title or "")
            if not sec_title:
                continue
            if sec.level <= wrapper.level and _looks_like_next_major_chapter(sec_title):
                break
            if sec.level > wrapper.level:
                continue
            if _looks_like_composition_body_part(sec) and (sec.content.strip() or sec.children):
                current_parts.append(sec)
                continue
            if current_parts and sec.level <= wrapper.level:
                break
        if len(current_parts) >= 2 or (
            current_parts and any("技术" in (s.title or "") or "商务" in (s.title or "") for s in current_parts)
        ):
            parts = current_parts
    return parts


def _looks_like_composition_body_part(sec: Section) -> bool:
    title = re.sub(r"\s+", "", sec.title or "")
    if not title:
        return False
    if re.search(r"[-–—]?\d+[-–—]?$", title):
        return False
    return any(k in title for k in ("商务部分", "技术部分", "价格部分", "报价部分", "经济部分"))


def _looks_like_next_major_chapter(title: str) -> bool:
    if not title:
        return False
    if any(k in title for k in ("投标文件组成", "响应文件组成", "报价文件组成", "报价书组成")):
        return False
    return bool(re.match(r"^第[一二三四五六七八九十\d]+章", title))


def assemble_section_content(
    parsed: ParsedDoc, located: list[LocatedSection], max_chars: int | None = None
) -> list[dict]:
    """把每个定位到的章节,从 parsed 里取出实际内容。

    ★ V10.1 关键修复:
       取到的章节内容为空时(说明定位到了目录索引页),
       自动找文档后面同名/相似名的章节作为真正内容。
    """
    by_id = {sec.id: sec for sec in parsed.flat_sections}
    _ordered = sorted(
        [s for s in parsed.flat_sections if s.start_item_idx is not None],
        key=lambda s: s.start_item_idx,
    )

    def _next_section_start(sec: Section) -> int | None:
        for s in _ordered:
            if s.start_item_idx > (sec.start_item_idx or -1):
                return s.start_item_idx
        return None

    def _collect_content_by_block_range(sec: Section) -> str:
        if sec.start_item_idx is None:
            return ""
        end = _next_section_start(sec)
        parts = []
        for b in (parsed.block_index or []):
            anchor = str(b.get("anchor") or "")
            if not anchor.startswith("p"):
                continue
            try:
                idx = int(anchor[1:])
            except ValueError:
                continue
            if idx < sec.start_item_idx:
                continue
            if end is not None and idx >= end:
                break
            if idx == sec.start_item_idx:
                continue
            text = str(b.get("text") or "")
            if text:
                parts.append(text)
        return "\n".join(parts)

    results = []
    for loc in located:
        # 1. 优先按 id 匹配
        sec = by_id.get(loc.section_id)

        # 2. id 找不到 → 按标题模糊匹配,找所有候选
        candidates = _find_all_matching_sections(parsed, loc.section_title)

        if sec is None:
            if not candidates:
                logger.warning(
                    f"[locator] LLM 返回的章节 '{loc.section_id} {loc.section_title}' "
                    f"在文档里找不到对应,跳过"
                )
                continue
            sec = candidates[0]

        # 3. ★ 关键修复:如果 sec 内容为空,试着用候选里有内容的那个替换
        section_max_chars = max_chars or _section_max_chars(sec.title, loc.relevance)
        content = _collect_content(sec, max_chars=section_max_chars)
        if not content.strip() and candidates:
            # 找到第一个有内容的候选
            for cand in candidates:
                cand_content = _collect_content(cand, max_chars=max_chars or _section_max_chars(cand.title, loc.relevance))
                if cand_content.strip():
                    logger.info(
                        f"[locator] 章节 '{loc.section_title}' 在 id={sec.id} 处内容为空,"
                        f"改用 id={cand.id} 处的内容"
                    )
                    sec = cand
                    content = cand_content
                    break

        if not content.strip():
            range_content = _collect_content_by_block_range(sec)
            if range_content.strip():
                logger.info(f"[locator] 章节 {sec.id} content 为空，按 block 区间补取 {len(range_content)} 字")
                content = range_content

        if not content.strip() and _looks_like_material_requirement_title(sec.title):
            content = sec.title

        content = _append_following_empty_attachment_checklist(parsed, sec, content)

        if "权威提交清单章节" in (loc.relevance or ""):
            content = _trim_authoritative_checklist_content(content, sec.title)

        if not content.strip():
            logger.warning(
                f"[locator] 章节 '{loc.section_id} {loc.section_title}' "
                f"内容为空(可能是目录索引页或文档结构问题),跳过"
            )
            continue

        results.append({
            "section_id": sec.id,
            "title": sec.title,
            "relevance": loc.relevance,
            "content": content,
            "anchor_start": f"p{sec.start_item_idx}" if sec.start_item_idx is not None else None,
            "anchor_end": f"p{sec.end_item_idx}" if sec.end_item_idx is not None else None,
            "anchor_blocks": [
                b
                for b in (parsed.block_index or [])
                if sec.start_item_idx is not None
                and sec.end_item_idx is not None
                and b.get("anchor", "").startswith("p")
                and sec.start_item_idx <= int(str(b.get("anchor", "p0"))[1:]) <= sec.end_item_idx
            ][: _anchor_block_limit()],
        })
        logger.info(
            f"[locator] 章节 {sec.id} '{sec.title}' 已定位,内容 {len(content)} 字"
        )

    return results


def _append_following_empty_attachment_checklist(parsed: ParsedDoc, sec: Section, content: str) -> str:
    """Recover checklist rows split into empty attachment-title sections.

    Some Word files style "附件一：投标函" rows as headings immediately after a
    "投标文件的组成/应由下述文件构成" intro. Keep parser heading behavior intact,
    but stitch those consecutive empty headings back into the located section
    content so source-backed extraction can treat them as list rows.
    """
    if sec.start_item_idx is None:
        return content
    seed = f"{sec.title or ''}\n{content or ''}"
    compact_seed = re.sub(r"\s+", "", seed)
    if not any(anchor in compact_seed for anchor in ("投标文件", "响应文件", "报价文件", "报价书")):
        return content
    if not any(trigger in compact_seed for trigger in ("组成", "构成", "应包括", "包括但不限于", "下述文件构成", "以下文件构成")):
        return content

    ordered = sorted(
        [item for item in parsed.flat_sections if item.start_item_idx is not None],
        key=lambda item: int(item.start_item_idx or 0),
    )
    following = [item for item in ordered if int(item.start_item_idx or 0) > int(sec.start_item_idx or 0)]
    recovered: list[str] = []
    stop_section: Section | None = None
    for candidate in following:
        title = str(candidate.title or "").strip()
        if not title:
            continue
        if not _looks_like_empty_attachment_checklist_section(candidate):
            stop_section = candidate
            break
        name = _attachment_checklist_item_name(title)
        if not name:
            stop_section = candidate
            break
        recovered.append(name)

    if len(recovered) < 3:
        return content
    recovered.extend(_following_qualification_checklist_items(stop_section))

    deduped: list[str] = []
    seen: set[str] = set()
    for item in recovered:
        key = re.sub(r"\s+", "", item)
        if "授权委托书" in key:
            key = "授权委托书"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    base = str(content or "").rstrip()
    suffix = "\n".join(deduped)
    return f"{base}\n{suffix}".strip() if base else suffix


def _looks_like_empty_attachment_checklist_section(sec: Section) -> bool:
    title = re.sub(r"\s+", "", sec.title or "")
    if not re.match(r"^附件[一二三四五六七八九十\d]+[：:]", title):
        return False
    if str(sec.content or "").strip():
        return False
    return bool(_attachment_checklist_item_name(sec.title or ""))


def _attachment_checklist_item_name(title: str) -> str:
    value = re.sub(r"\s+", "", str(title or "").strip())
    value = re.sub(r"^附件[一二三四五六七八九十\d]+[：:]\s*", "", value)
    value = re.sub(r"[（(]\s*(?:需单独密封|投标人自行编写)[^）)]*[）)]", "", value)
    if not value:
        return ""
    if len(value) > 60:
        return ""
    if any(term in value for term in ("评分", "评审", "保证金不予退还", "废标", "否决")):
        return ""
    return value


def _following_qualification_checklist_items(sec: Section | None) -> list[str]:
    if sec is None:
        return []
    title = re.sub(r"\s+", "", sec.title or "")
    content = str(sec.content or "")
    compact_content = re.sub(r"\s+", "", content)
    if "资格审查" not in title:
        return []
    if not any(marker in compact_content for marker in ("具体包括如下内容", "包括如下内容", "包括以下内容")):
        return []

    rows: list[str] = []
    for raw in content.splitlines():
        line = str(raw or "").strip()
        compact = re.sub(r"\s+", "", line)
        if not compact:
            continue
        if not re.match(r"^\d+[、.．]", compact):
            continue
        name = _qualification_checklist_item_name(compact)
        if name:
            rows.append(name)
    return rows if len(rows) >= 3 else []


def _qualification_checklist_item_name(line: str) -> str:
    value = re.sub(r"^\d+[、.．]\s*", "", line)
    value = value.rstrip("；;。")
    if "营业执照" in value:
        return "营业执照"
    if "财务审计报告" in value or "财务报表" in value:
        return "财务审计报告或财务报表"
    if "缴税" in value and "社保" in value:
        return "企业缴税凭证及社保缴纳凭据"
    if "授权委托书" in value:
        return "法人授权委托书"
    if "投标保证金" in value:
        return "投标保证金进账凭证复印件"
    if len(value) <= 60:
        return value
    return ""


def _find_all_matching_sections(parsed: ParsedDoc, target_title: str) -> List[Section]:
    """找出所有匹配某标题的章节(同名 / 相似名),按出现顺序返回。"""
    target = target_title.strip()
    matches = []

    # 第 1 轮:精确匹配
    for sec in parsed.flat_sections:
        if sec.title.strip() == target:
            matches.append(sec)
    if matches:
        return matches

    # 第 2 轮:子串匹配
    target_simplified = _normalize_title(target)
    for sec in parsed.flat_sections:
        sec_simplified = _normalize_title(sec.title)
        if not sec_simplified or not target_simplified:
            continue
        # 双向子串
        if target_simplified in sec_simplified or sec_simplified in target_simplified:
            matches.append(sec)
    return matches


def _normalize_title(title: str) -> str:
    """规范化标题用于模糊匹配:去空格、去标点。"""
    import re
    # 去掉所有空格、全角空格、标点
    return re.sub(r'[\s\u3000\.\,\,\.、:: ]+', '', title.strip())


def _locator_toc_level_limit() -> int:
    """Allow deeper TOC items so attachment/form titles are visible to locator."""
    try:
        return max(2, int(os.getenv("LOCATOR_TOC_LEVEL_LIMIT", "4")))
    except Exception:
        return 4


def _locator_llm_timeout_seconds() -> float:
    """Keep the pre-graph locator from blocking the workflow on slow LLM calls."""
    try:
        return max(10.0, float(os.getenv("LOCATOR_LLM_TIMEOUT_SECONDS", "90")))
    except Exception:
        return 90.0


def _locator_max_tokens_override() -> int | None:
    """Keep the small locator schema from inheriting a large provider budget."""
    raw = os.getenv("LOCATOR_MAX_TOKENS", "1200")
    try:
        return max(512, int(raw))
    except Exception:
        return 1200


def _locator_network_max_retries() -> int:
    """A locator miss is recoverable, so avoid several minutes of retries."""
    try:
        return max(0, min(1, int(os.getenv("LOCATOR_NETWORK_MAX_RETRIES", "1"))))
    except Exception:
        return 1


def _anchor_block_limit() -> int:
    try:
        return max(3, int(os.getenv("LOCATOR_ANCHOR_BLOCK_LIMIT", "12")))
    except Exception:
        return 12


def _section_max_chars(title: str, relevance: str = "") -> int:
    text = f"{title or ''} {relevance or ''}"
    if any(k in text for k in ("评分", "评审", "评标", "综合评分", "评审办法")):
        return int(os.getenv("LOCATOR_SCORING_MAX_CHARS", "24000"))
    if any(k in text for k in ("采购需求", "服务需求", "技术要求", "技术规格", "服务内容", "项目服务")):
        return int(os.getenv("LOCATOR_TECH_MAX_CHARS", "20000"))
    if any(k in text for k in ("资格", "资质", "证明材料", "响应文件组成", "投标文件组成", "附件", "格式")):
        return int(os.getenv("LOCATOR_QUALIFICATION_MAX_CHARS", "16000"))
    if any(k in text for k in ("废标", "无效", "否决", "合同", "付款", "履约", "保证金", "时限", "截止", "递交")):
        return int(os.getenv("LOCATOR_RISK_MAX_CHARS", "16000"))
    return int(os.getenv("LOCATOR_DEFAULT_MAX_CHARS", "10000"))

def _collect_content(section: Section, max_chars: int = 10000) -> str:
    """递归收集章节及子章节的内容。"""
    parts = []
    if section.content:
        parts.append(section.content)
    for child in section.children:
        if child.title:
            parts.append(f"\n## {child.title}")
        if child.content:
            parts.append(child.content)
        for gc in child.children:
            if gc.title:
                parts.append(f"\n### {gc.title}")
            if gc.content:
                parts.append(gc.content)

    text = "\n".join(parts)
    if len(text) > max_chars:
        text = _trim_long_section_content(text, max_chars)
    return text


def _trim_long_section_content(text: str, max_chars: int) -> str:
    """Trim long sections while preserving high-value tender clauses."""
    if len(text) <= max_chars:
        return text

    high_value_keywords = (
        "评分", "评审", "评标", "分值", "得分", "综合评分",
        "材料", "证明", "附件", "格式", "响应文件", "投标文件",
        "资格", "资质", "原件", "复印件", "加盖公章", "份数",
        "废标", "无效", "否决", "不予受理", "截止", "保证金",
        "合同", "履约", "付款", "服务期限", "技术要求", "服务要求",
    )
    head_budget = max(1600, int(max_chars * 0.45))
    tail_budget = max(1000, int(max_chars * 0.15))
    middle_budget = max_chars - head_budget - tail_budget - 220
    if middle_budget <= 0:
        return text[:max_chars] + f"\n[内容已截断, 完整 {len(text)} 字]"

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    picked: list[str] = []
    used = 0
    for line in lines:
        if not any(keyword in line for keyword in high_value_keywords):
            continue
        if line in picked:
            continue
        if used + len(line) + 1 > middle_budget:
            break
        picked.append(line)
        used += len(line) + 1

    middle = "\n".join(picked)
    return (
        text[:head_budget]
        + f"\n[中间内容已压缩, 完整 {len(text)} 字, 保留关键条款如下]\n"
        + middle
        + "\n[章节末尾]\n"
        + text[-tail_budget:]
    )[: max_chars + 120]
