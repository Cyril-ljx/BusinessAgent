"""Batching and prompt helpers for requirement extraction."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from loguru import logger

from ..requirements_common import _compact_text
from .configs import MAX_DIMENSION_BATCH_CHARS
from .schemas import DimensionConfig
from .selectors import (
    _DIMENSION_PRIORITY_HINTS,
    _looks_like_file_format_chapter,
    _section_depth,
)


DIMENSION_EXTRACTION_PROMPT = """你是招标文件需求抽取专家。请只抽取【{dimension_name}】维度。

【强制原则】
1. 只抽取原文明确出现的要求，禁止推断、补全、编造。
2. 每条要求必须带 quote，quote 必须是连续复制的原文短摘录，尽量不超过 25 字；不得改写、概括或省略 URL/数字/关键标点。
3. 每条要求必须尽量带 anchor，anchor 必须来自输入片段的 section_id/title/anchor_start/anchor_end/anchor_blocks。
4. anchor_blocks 只保留最相关锚点，text 不要超过 30 字。
5. 抽不到则返回空对象或空列表，不要用模板填充。
6. 必须穷尽该维度所有条款，不要只抽代表性样例；一句话里多个证件/条件/材料要拆成多条。
7. 只返回该维度 schema 允许的字段，不要返回其他维度。

【维度说明】
{dimension_instruction}

【定位片段 JSON】
{sections_json}

请严格返回合法 JSON。
"""

def _dimension_item_size(item: Dict[str, Any]) -> int:
    return len(json.dumps(item, ensure_ascii=False))


def _dimension_item_priority(item: Dict[str, Any], config_name: str) -> float:
    title = _compact_text(str(item.get("title") or ""))
    relevance = _compact_text(str(item.get("relevance") or ""))
    content = _compact_text(str(item.get("content") or ""))
    head = f"{title}{relevance}"
    hints = _DIMENSION_PRIORITY_HINTS.get(config_name, ())
    score = float(_section_depth(item.get("section_id")) * 8)
    if item.get("protected_list"):
        score += 1000.0
    if config_name == "file_composition" and _looks_like_file_format_chapter(item):
        score += 260.0
    if title and any(token in title for token in hints):
        score += 40.0
    score += sum(12.0 for token in hints if token in head)
    score += sum(3.0 for token in hints[:6] if token in content[:2400])
    if "autoaugment" not in head and "auto-augment" not in relevance.lower():
        score += 6.0
    size_penalty = min(20.0, _dimension_item_size(item) / 2500.0)
    return score - size_penalty


def _truncate_middle(text: str, max_chars: int) -> str:
    raw = str(text or "")
    if max_chars <= 0 or len(raw) <= max_chars:
        return raw
    marker = "\n...[中间内容已压缩]...\n"
    if max_chars <= len(marker) + 20:
        return raw[:max_chars]
    head = int(max_chars * 0.7)
    tail = max_chars - head - len(marker)
    if tail < 20:
        tail = 20
        head = max(20, max_chars - tail - len(marker))
    return f"{raw[:head]}{marker}{raw[-tail:]}"


def _technical_scoring_content_limit(item: Dict[str, Any]) -> int | None:
    title = _compact_text(str(item.get("title") or ""))
    relevance = _compact_text(str(item.get("relevance") or ""))
    head = f"{title}{relevance}"
    if any(token in head for token in ("评分", "评审", "综合评分", "技术评分", "商务评分", "价格评分")):
        return 5000
    if any(token in head for token in ("采购需求", "服务要求", "技术要求", "项目需求", "用户需求")):
        return 3500
    return 4000


def _risk_contract_content_limit(item: Dict[str, Any]) -> int | None:
    title = _compact_text(str(item.get("title") or ""))
    relevance = _compact_text(str(item.get("relevance") or ""))
    head = f"{title}{relevance}"
    if str(item.get("section_id") or "") == "head_text":
        return 900
    if any(token in head for token in ("保证金", "履约保证金", "投标保证金", "付款", "违约", "赔偿", "合同", "报价要求", "最高限价")):
        return 2800
    if any(token in head for token in ("无效", "废标", "否决", "不予受理", "响应文件组成")):
        return 2200
    if any(token in head for token in ("资格", "符合性", "须知", "邀请")):
        return 1800
    return 2000


def _compact_dimension_item(item: Dict[str, Any], config: DimensionConfig) -> Dict[str, Any]:
    if config.name not in {"technical_scoring", "risk_contract"}:
        return item
    limit = (
        _technical_scoring_content_limit(item)
        if config.name == "technical_scoring"
        else _risk_contract_content_limit(item)
    )
    if not limit:
        return item
    content = str(item.get("content") or "")
    if len(content) <= limit:
        return item
    next_item = dict(item)
    next_item["content"] = _truncate_middle(content, limit)
    return next_item


def _compact_dimension_sections(
    selected: List[Dict[str, Any]],
    config: DimensionConfig,
) -> List[Dict[str, Any]]:
    compacted = [_compact_dimension_item(item, config) for item in selected]
    if config.name in {"technical_scoring", "risk_contract"}:
        before_chars = sum(len(str(item.get("content") or "")) for item in selected)
        after_chars = sum(len(str(item.get("content") or "")) for item in compacted)
        if after_chars < before_chars:
            logger.info(
                "[requirements] dimension {} compacted content chars {} -> {}",
                config.name,
                before_chars,
                after_chars,
            )
    return compacted


def _trim_dimension_sections(
    selected: List[Dict[str, Any]],
    config: DimensionConfig,
) -> List[Dict[str, Any]]:
    max_total_chars = config.max_total_chars
    if not max_total_chars or len(selected) <= 1:
        return selected

    total_chars = sum(_dimension_item_size(item) for item in selected)
    if total_chars <= max_total_chars:
        return selected

    ranked: List[Tuple[float, int, int, Dict[str, Any]]] = []
    forced_indexes: set[int] = set()
    for idx, item in enumerate(selected):
        if config.include_head and str(item.get("section_id") or "") == "head_text":
            forced_indexes.add(idx)
        ranked.append(
            (
                _dimension_item_priority(item, config.name),
                _section_depth(item.get("section_id")),
                -_dimension_item_size(item),
                item,
            )
        )

    kept_indexes = set(forced_indexes)
    kept_chars = sum(_dimension_item_size(selected[idx]) for idx in kept_indexes)
    index_by_identity = {id(item): idx for idx, item in enumerate(selected)}

    for _score, _depth, _neg_size, item in sorted(ranked, key=lambda row: (row[0], row[1], row[2]), reverse=True):
        idx = index_by_identity[id(item)]
        if idx in kept_indexes:
            continue
        item_chars = _dimension_item_size(item)
        if kept_indexes and kept_chars + item_chars > max_total_chars:
            continue
        kept_indexes.add(idx)
        kept_chars += item_chars

    if not kept_indexes:
        return selected[:1]

    trimmed = [item for idx, item in enumerate(selected) if idx in kept_indexes]
    if not trimmed:
        return selected[:1]

    logger.info(
        "[requirements] dimension {} trimmed sections {} -> {}, chars {} -> {}",
        config.name,
        len(selected),
        len(trimmed),
        total_chars,
        kept_chars,
    )
    return trimmed


def _split_oversized_item(item: Dict[str, Any], max_chars: int = MAX_DIMENSION_BATCH_CHARS) -> List[Dict[str, Any]]:
    item_chars = len(json.dumps(item, ensure_ascii=False))
    if item_chars <= max_chars or item.get("protected_list"):
        return [item]

    content = str(item.get("content") or "")
    lines = [line for line in content.splitlines() if line.strip()]
    if len(lines) <= 1:
        midpoint = max(1, len(content) // 2)
        pieces = [content[:midpoint], content[midpoint:]]
    else:
        half = sum(len(line) for line in lines) / 2
        running = 0
        split_at = 1
        for idx, line in enumerate(lines, start=1):
            running += len(line)
            if running >= half:
                split_at = idx
                break
        if split_at >= len(lines):
            split_at = max(1, len(lines) // 2)
        pieces = ["\n".join(lines[:split_at]), "\n".join(lines[split_at:])]

    split_items: List[Dict[str, Any]] = []
    for idx, piece in enumerate(pieces, start=1):
        if not piece.strip():
            continue
        next_item = dict(item)
        next_item["content"] = piece
        parent_id = item.get("chunk_id") or item.get("section_id")
        next_item["chunk_id"] = f"{parent_id}#part{idx}"
        next_item["title"] = f"{item.get('title') or ''}（片段{idx}/{len(pieces)}）"
        if len(json.dumps(next_item, ensure_ascii=False)) > max_chars and len(piece) < len(content):
            split_items.extend(_split_oversized_item(next_item, max_chars=max_chars))
        else:
            split_items.append(next_item)
    return split_items or [item]


def _build_dimension_batches(
    items: List[Dict[str, Any]],
    max_chars: int = MAX_DIMENSION_BATCH_CHARS,
) -> List[List[Dict[str, Any]]]:
    batches: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    current_chars = 0
    expanded_items: List[Dict[str, Any]] = []
    for item in items:
        expanded_items.extend(_split_oversized_item(item, max_chars=max_chars))

    for item in expanded_items:
        item_chars = len(json.dumps(item, ensure_ascii=False))
        if current and current_chars + item_chars > max_chars:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(item)
        current_chars += item_chars
    if current:
        batches.append(current)
    return batches


def _build_dimension_prompt(config: DimensionConfig, batch: List[Dict[str, Any]]) -> str:
    return DIMENSION_EXTRACTION_PROMPT.format(
        dimension_name=config.name,
        dimension_instruction=config.instruction,
        sections_json=json.dumps(batch, ensure_ascii=False, indent=2),
    )
