"""LangGraph 节点：标题提取。"""
import asyncio
import re
import time
from typing import Any, Dict

from loguru import logger

from ..config.settings import settings
from ..core.models import TitleInfo
from ..core.state import TenderState
from ..llm.gateway import llm_gateway
from .prompts import TITLE_EXTRACTION_PROMPT


async def extract_title(state: TenderState) -> Dict[str, Any]:
    """从招标书开头提取标题信息。"""
    head_content = state.get("head_text", "")
    if not head_content:
        return {"title_info": _fallback_title_info(state, ""), "warnings": ["[title] 无开头内容,使用文件名兜底"]}

    t0 = time.time()
    trimmed_head = _trim_title_context(head_content)
    logger.info(f"[title] 开始,输入 {len(trimmed_head)}/{len(head_content)} 字")

    prompt = TITLE_EXTRACTION_PROMPT.format(content=trimmed_head)
    timeout_seconds = max(5.0, float(settings.TITLE_LLM_TIMEOUT_SECONDS))
    try:
        info: TitleInfo = await asyncio.wait_for(
            llm_gateway.async_call_structured(prompt, TitleInfo, max_tokens=700),
            timeout=timeout_seconds,
        )
        logger.info(f"[title] ✓ 完成,耗时 {time.time() - t0:.1f}s")
        result = info.model_dump()
        # 通用过滤：排除资格要求条款被误提取为采购方
        if result.get("purchaser") and _is_invalid_purchaser(result["purchaser"]):
            result["purchaser"] = ""
        return {"title_info": result}
    except asyncio.TimeoutError:
        elapsed = time.time() - t0
        logger.warning(f"[title] 超时 {elapsed:.1f}s,使用规则兜底")
        return {
            "title_info": _fallback_title_info(state, trimmed_head),
            "warnings": [f"[title] LLM 超时 {elapsed:.1f}s,已使用规则兜底"],
        }
    except Exception as e:
        logger.error(f"[title] ✗ 失败:{str(e)[:200]}")
        return {
            "title_info": _fallback_title_info(state, trimmed_head),
            "warnings": [f"[title] 标题提取失败,已使用规则兜底: {str(e)[:200]}"],
        }


def _trim_title_context(text: str, max_chars: int = 3500) -> str:
    """标题信息通常在首页/前几段,不需要把长上下文交给模型。"""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return text[:max_chars]

    picked = []
    for line in lines[:120]:
        if len("\n".join(picked)) >= max_chars:
            break
        picked.append(line)
    return "\n".join(picked)[:max_chars]


def _is_invalid_purchaser(text: str) -> bool:
    """通用过滤：排除资格要求、评审条款等非采购方名称的内容。"""
    t = re.sub(r"\s+", "", text or "")
    if re.search(r"[。！？；]", t):
        return True
    # 资格要求/评审条款 markers — 这些出现在招标文件的资格条件部分，不是采购方名称
    invalid_markers = (
        "投标将被拒绝",
        "不得参与本项目",
        "不得同时参加投标",
        "不接受联合体投标",
        "不得转包",
        "不得分包",
        "资格声明函原件",
        "投标人必须具备的资格",
        "合格投标人资格",
        "合同纠纷",
        "被索赔",
        "被政府",
        "不合格供应商",
        "被司法部门处罚",
    )
    return any(marker in t for marker in invalid_markers)


def _fallback_title_info(state: TenderState, text: str) -> Dict[str, str]:
    file_name = str(state.get("file_name") or "").strip()
    file_stem = re.sub(r"\.(docx?|pdf)$", "", file_name, flags=re.IGNORECASE).strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    tender_no = ""
    purchaser = ""
    project_name = ""

    for line in lines[:80]:
        if not tender_no:
            m = re.search(r"(?:项目编号|招标编号|采购编号|比选编号|磋商编号)[:：\s]*([A-Za-z0-9_\-./（）()]+)", line)
            if m:
                tender_no = m.group(1).strip()
        if not purchaser:
            m = re.search(r"(?:采购人|招标人|比选人|发包人)(?:\s*[:：]\s*|\s{2,})(.+)", line)
            if m:
                candidate = m.group(1).strip()[:80]
                if candidate and not _is_invalid_purchaser(candidate):
                    purchaser = candidate
        if not project_name:
            m = re.search(r"(?:项目名称|采购项目名称|招标项目名称)[:：\s]*(.+)", line)
            if m:
                project_name = m.group(1).strip()

    if not project_name:
        for line in lines[:30]:
            cleaned = re.sub(r"\s+", "", line)
            if 4 <= len(cleaned) <= 80 and any(k in cleaned for k in ("项目", "服务", "采购", "招标", "外包")):
                project_name = cleaned
                break

    if not project_name:
        project_name = file_stem or "投标项目"

    title = project_name
    if not any(k in title for k in ("投标文件", "响应文件", "比选申请书")):
        title = f"{title}投标文件"

    return {
        "title": title,
        "project_name": project_name,
        "tender_no": tender_no,
        "purchaser": purchaser,
    }
