"""Tender requirement extractor.

Phase 2 implementation: serial, dimension-based extraction. Each LLM call uses
one small schema, then partial results are merged into TenderRequirements. The
result is persisted for review; downstream nodes do not consume it yet.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, List, Tuple

from loguru import logger

from tender_agent.parsing.attachment_refs import attachment_body_sections

from .requirement_extraction.configs import (
    DIMENSION_CONFIGS,
)
from .requirement_extraction.schemas import DimensionConfig
from .requirement_extraction.batching import (
    _build_dimension_batches,
    _compact_dimension_sections,
    _trim_dimension_sections,
)
from .requirement_extraction.anchors import (
    _build_section_anchor_lookup,
    _hydrate_payload_anchors,
)
from .requirement_extraction.normalization import (
    _file_composition_final_source_stats,
    _merge_requirement_payloads,
)
from .requirement_extraction.llm_runner import (
    _run_dimension_batch,
    _usage_delta,
    _usage_snapshot,
    _write_requirement_trace,
)
from .requirement_extraction.source_selection import (
    _source_backed_rows_need_llm_file_composition,
)
from .requirement_extraction.inline_material_splitter import (
    merge_source_backed_inline_children_into_final_rows,
    refine_inline_material_children_with_llm,
)
from .requirement_extraction.selectors import (
    select_dimension_candidate_sections,
)
from .section_navigator import tag_requirement_sections
from .requirements_common import (
    _head_text_payload,
    _make_section_item,
)
from .source_backed_composition import (
    _is_authoritative_source_backed_rows,
    _extract_source_backed_file_composition,
)
from .requirements import TenderRequirements


def _section_group(section_id: Any) -> str:
    return str(section_id or "").split(".", 1)[0]


def _expand_technical_source_sections(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Recover nearby sibling evidence when malformed Word headings flatten a chapter."""
    if not items:
        return items
    technical_indexes = [
        index
        for index, item in enumerate(items)
        if "technical_scoring" in (item.get("requirement_tags") or [])
    ]
    if not technical_indexes:
        return items

    included = set(technical_indexes)
    for left, right in zip(technical_indexes, technical_indexes[1:]):
        if right - left <= 3 and _section_group(items[left].get("section_id")) == _section_group(
            items[right].get("section_id")
        ):
            included.update(range(left, right + 1))

    for anchor in technical_indexes:
        group = _section_group(items[anchor].get("section_id"))
        added = 0
        for index in range(anchor + 1, min(len(items), anchor + 4)):
            item = items[index]
            if _section_group(item.get("section_id")) != group:
                break
            tags = set(item.get("requirement_tags") or [])
            included.add(index)
            if "technical_scoring" not in tags:
                added += 1
                if added >= 2:
                    break

    expanded: List[Dict[str, Any]] = []
    for index, item in enumerate(items):
        if index in included and "technical_scoring" not in (item.get("requirement_tags") or []):
            next_item = dict(item)
            next_item["requirement_tags"] = list(item.get("requirement_tags") or []) + ["technical_scoring"]
            next_item["technical_context_expanded"] = True
            expanded.append(next_item)
        else:
            expanded.append(item)
    return expanded


def _select_dimension_sections(
    sections_payload: List[Dict[str, Any]],
    head_text: str,
    config: DimensionConfig,
) -> List[Dict[str, Any]]:
    selected = select_dimension_candidate_sections(sections_payload, head_text, config)
    selected = _trim_dimension_sections(selected, config)
    selected = _compact_dimension_sections(selected, config)
    return selected


async def _extract_dimension_group(
    config: DimensionConfig,
    sections_payload: List[Dict[str, Any]],
    head_text: str,
    sem: asyncio.Semaphore,
) -> Tuple[str, List[Dict[str, Any]], List[str], Dict[str, Any], int, int, int]:
    """Extract one independent dimension group.

    Dimension groups run concurrently. Batches inside each group can also run
    with a small concurrency, while _call_dimension_llm keeps the real provider
    concurrency under REQUIREMENTS_LLM_CONCURRENCY.
    """
    async with sem:
        group_started = time.time()
        if config.name in {"file_composition", "submission_checklist"}:
            source_backed = _extract_source_backed_file_composition(sections_payload)
            if config.name == "file_composition":
                source_backed = await refine_inline_material_children_with_llm(source_backed)
            source_backed_needs_llm = (
                config.name == "file_composition"
                and _source_backed_rows_need_llm_file_composition(source_backed)
            )
            can_skip_with_source = bool(source_backed) and not source_backed_needs_llm and (
                config.name == "file_composition"
                or _is_authoritative_source_backed_rows(source_backed)
            )
            if can_skip_with_source:
                payload_key = "file_composition" if config.name == "file_composition" else "material_checklist"
                stats = {
                    "section_count": 0,
                    "batch_count": 0,
                    "selected_content_chars": 0,
                    "prompt_chars": [],
                    "batches": [],
                    "batch_concurrency": 0,
                    "source_backed_skip_llm": True,
                    "source_backed_count": len(source_backed),
                    "source_backed_authoritative": _is_authoritative_source_backed_rows(source_backed),
                    "elapsed_sec": round(time.time() - group_started, 3),
                }
                logger.info(
                    "[requirements] dimension {} skipped LLM; source-backed rows={}",
                    config.name,
                    len(source_backed),
                )
                return (
                    config.name,
                    [{payload_key: source_backed}],
                    [],
                    stats,
                    0,
                    0,
                    0,
                )
            if config.name == "file_composition" and source_backed_needs_llm:
                logger.info(
                    "[requirements] dimension file_composition keeps LLM; source-backed rows look like instruction prose: rows={}",
                    len(source_backed),
                )
            if config.name == "submission_checklist" and source_backed:
                logger.info(
                    "[requirements] dimension submission_checklist keeps LLM; source-backed rows not authoritative/clean enough: rows={}",
                    len(source_backed),
                )

        selected = _select_dimension_sections(sections_payload, head_text, config)
        batches = _build_dimension_batches(selected, max_chars=config.batch_chars)
        stats: Dict[str, Any] = {
            "section_count": len(selected),
            "batch_count": len(batches),
            "selected_content_chars": sum(len(str(item.get("content") or "")) for item in selected),
            "prompt_chars": [],
            "batches": [],
        }
        payloads: List[Dict[str, Any]] = []
        warnings: List[str] = []
        prompt_chars_total = 0
        successful_batches = 0

        logger.info(
            "[requirements] dimension {}, sections={}, batches={}",
            config.name,
            len(selected),
            len(batches),
        )
        batch_results: List[Tuple[int, List[Dict[str, Any]], Dict[str, Any], int, List[str]]] = []
        if config.name in {
            "file_composition",
            "format_template",
            "qualification_review",
            "submission_checklist",
        }:
            batch_concurrency = max(
                1,
                int(
                    os.getenv(
                        "REQUIREMENTS_MATERIAL_BATCH_CONCURRENCY",
                        os.getenv("REQUIREMENTS_QUALIFICATION_BATCH_CONCURRENCY", "2"),
                    )
                ),
            )
        else:
            batch_concurrency = max(1, int(os.getenv("REQUIREMENTS_BATCH_CONCURRENCY", "2")))
        stats["batch_concurrency"] = batch_concurrency
        batch_sem = asyncio.Semaphore(batch_concurrency)

        async def run_limited(
            item: Tuple[int, List[Dict[str, Any]]]
        ) -> Tuple[int, List[Dict[str, Any]], Dict[str, Any], int, List[str]]:
            idx, batch = item
            async with batch_sem:
                return await _run_dimension_batch(config, batch, idx, len(batches))

        batch_results = await asyncio.gather(
            *[run_limited((idx, batch)) for idx, batch in enumerate(batches, start=1)]
        )
        batch_results.sort(key=lambda item: item[0])

        recovered_batches = 0
        final_batch_results = batch_results

        for _idx, batch_payloads, batch_stats, prompt_chars, batch_warnings in final_batch_results:
            prompt_chars_total += prompt_chars
            stats["prompt_chars"].append(prompt_chars)
            stats["batches"].append(batch_stats)
            payloads.extend(batch_payloads)
            warnings.extend(batch_warnings)
            if batch_payloads:
                successful_batches += 1

        stats["recovered_batches"] = recovered_batches
        stats["elapsed_sec"] = round(time.time() - group_started, 3)
        _write_requirement_trace(
            {
                "event": "dimension_end",
                "dimension": config.name,
                "elapsed_sec": stats["elapsed_sec"],
                "batch_count": len(batches),
                "successful_batches": successful_batches,
                "warning_count": len(warnings),
            }
        )

        return (
            config.name,
            payloads,
            warnings,
            stats,
            prompt_chars_total,
            len(batches),
            successful_batches,
        )


async def extract_tender_requirements(state: Dict[str, Any]) -> Dict[str, Any]:
    """Extract TenderRequirements from located sections without feeding downstream."""
    located_sections = state.get("located_sections") or []
    requirement_source_sections = state.get("requirement_source_sections") or []
    head_text = str(state.get("head_text") or "")
    if not located_sections:
        return {
            "tender_requirements": TenderRequirements().model_dump(mode="json"),
            "tender_requirements_stats": {
                "elapsed_sec": 0,
                "prompt_chars": 0,
                "section_count": 0,
                "usage_delta": {},
            },
            "warnings": ["[requirements] empty located_sections"],
        }

    usage_before = _usage_snapshot()
    started = time.time()
    sections_payload = tag_requirement_sections([_make_section_item(sec) for sec in located_sections])
    attachment_sections_payload = attachment_body_sections(state.get("block_index") or [])
    composition_sections_payload = [*sections_payload, *attachment_sections_payload]
    technical_sections_payload = (
        _expand_technical_source_sections(
            tag_requirement_sections([_make_section_item(sec) for sec in requirement_source_sections])
        )
        if requirement_source_sections
        else sections_payload
    )
    tag_counts: Dict[str, int] = {}
    untagged_sections = 0
    for item in sections_payload:
        tags = list(item.get("requirement_tags") or [])
        if not tags:
            untagged_sections += 1
        for tag in tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    if technical_sections_payload is not sections_payload:
        tag_counts["technical_scoring"] = sum(
            1
            for item in technical_sections_payload
            if "technical_scoring" in (item.get("requirement_tags") or [])
        )
    partial_payloads: List[Dict[str, Any]] = []
    warnings: List[str] = []
    dimension_stats: Dict[str, Any] = {}
    prompt_chars_total = 0
    batch_count = 0
    successful_batches = 0

    logger.info(
        "[requirements] start dimension extraction, sections={}, dimensions={}, tags={}, untagged={}",
        len(sections_payload) + (1 if head_text.strip() else 0),
        len(DIMENSION_CONFIGS),
        tag_counts,
        untagged_sections,
    )

    parallel_enabled = os.getenv("REQUIREMENTS_PARALLEL", "true").lower() in {"1", "true", "yes", "on"}
    dimension_concurrency = max(
        1,
        int(os.getenv("REQUIREMENTS_DIMENSION_CONCURRENCY", "3")),
    )
    if not parallel_enabled:
        dimension_concurrency = 1
    sem = asyncio.Semaphore(dimension_concurrency)

    def source_sections_for(config: DimensionConfig) -> List[Dict[str, Any]]:
        if config.name == "technical_scoring":
            return technical_sections_payload
        if config.name == "file_composition":
            return composition_sections_payload
        return sections_payload

    if parallel_enabled:
        logger.info(
            "[requirements] dimension parallel enabled, concurrency={}",
            dimension_concurrency,
        )
        group_results = await asyncio.gather(
            *[
                _extract_dimension_group(config, source_sections_for(config), head_text, sem)
                for config in DIMENSION_CONFIGS
            ]
        )
    else:
        logger.info("[requirements] dimension parallel disabled, running serial")
        group_results = []
        for config in DIMENSION_CONFIGS:
            group_results.append(
                await _extract_dimension_group(config, source_sections_for(config), head_text, sem)
            )

    for (
        dimension_name,
        dimension_payloads,
        dimension_warnings,
        stats_for_dimension,
        prompt_chars_for_dimension,
        batch_count_for_dimension,
        successful_batches_for_dimension,
    ) in group_results:
        dimension_stats[dimension_name] = stats_for_dimension
        partial_payloads.extend(dimension_payloads)
        warnings.extend(dimension_warnings)
        prompt_chars_total += prompt_chars_for_dimension
        batch_count += batch_count_for_dimension
        successful_batches += successful_batches_for_dimension

    source_backed_file_composition = _extract_source_backed_file_composition(sections_payload)
    source_backed_file_composition = await refine_inline_material_children_with_llm(source_backed_file_composition)
    has_file_composition_payload = any(
        isinstance(payload, dict) and payload.get("file_composition")
        for payload in partial_payloads
    )
    source_backed_needs_llm = _source_backed_rows_need_llm_file_composition(source_backed_file_composition)
    if source_backed_file_composition and not has_file_composition_payload:
        fallback_rows = list(source_backed_file_composition)
        partial_payloads.insert(
            0,
            {
                "file_composition": fallback_rows,
                "material_checklist": fallback_rows,
            },
        )
        if source_backed_needs_llm:
            warnings.append(
                "[requirements] file_composition LLM 未产出，已保留原文目录候选，请在目录确认页复核"
            )
            logger.warning(
                "[requirements] source-backed file composition kept for review after LLM failure: rows={}",
                len(fallback_rows),
            )
        else:
            logger.info(
                "[requirements] source-backed file composition added {} rows",
                len(fallback_rows),
            )
    elif source_backed_file_composition:
        logger.info(
            "[requirements] source-backed file composition already supplied {} rows",
            len(source_backed_file_composition),
        )

    anchor_sources = list(located_sections)
    if head_text.strip():
        anchor_sources.append(_head_text_payload(head_text))
    anchor_lookup = _build_section_anchor_lookup(anchor_sources)
    for partial_payload in partial_payloads:
        _hydrate_payload_anchors(partial_payload, anchor_lookup)

    elapsed = time.time() - started
    usage_after = _usage_snapshot()
    payload = _merge_requirement_payloads(partial_payloads)
    payload["file_composition"] = merge_source_backed_inline_children_into_final_rows(
        payload.get("file_composition") or [],
        source_backed_file_composition,
    )
    file_composition_source_stats = _file_composition_final_source_stats(payload.get("file_composition") or [])
    dimension_elapsed_values = [
        float(item.get("elapsed_sec") or 0)
        for item in dimension_stats.values()
        if isinstance(item, dict)
    ]
    max_dimension_elapsed = max(dimension_elapsed_values) if dimension_elapsed_values else 0
    stats = {
        "elapsed_sec": round(elapsed, 3),
        "max_dimension_elapsed_sec": round(max_dimension_elapsed, 3),
        "parallel_overhead_sec": round(elapsed - max_dimension_elapsed, 3),
        "prompt_chars": prompt_chars_total,
        "section_count": len(sections_payload) + (1 if head_text.strip() else 0),
        "requirement_source_section_count": len(technical_sections_payload),
        "attachment_body_section_count": len(attachment_sections_payload),
        "dimension_count": len(DIMENSION_CONFIGS),
        "section_tag_counts": tag_counts,
        "untagged_sections": untagged_sections,
        "parallel_enabled": parallel_enabled,
        "dimension_concurrency": dimension_concurrency,
        "batch_count": batch_count,
        "successful_batches": successful_batches,
        "failed_batches": len(warnings),
        "source_backed_file_composition": len(source_backed_file_composition),
        **file_composition_source_stats,
        "dimension_stats": dimension_stats,
        "usage_delta": _usage_delta(usage_before, usage_after),
    }
    logger.info(
        "[requirements] done, elapsed={:.1f}s, batches={}/{}, tech={}, invalid={}, materials={}",
        elapsed,
        successful_batches,
        batch_count,
        len(payload.get("technical_requirements") or []),
        len(payload.get("invalidation") or []),
        len(payload.get("material_checklist") or []),
    )
    result_payload = {"tender_requirements": payload, "tender_requirements_stats": stats}
    if warnings:
        result_payload["warnings"] = warnings
    return result_payload
