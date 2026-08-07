"""LLM call and batch execution helpers for requirement extraction."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, List, Tuple, Type

from loguru import logger
from pydantic import BaseModel

from ...llm.gateway import llm_gateway
from .batching import _build_dimension_prompt
from .configs import PER_DIMENSION_TIMEOUT_SECONDS
from .schemas import DimensionConfig

_LLM_CALL_SEMAPHORE: asyncio.Semaphore | None = None
_LLM_CALL_SEMAPHORE_LIMIT: int | None = None
_LLM_CALL_SEMAPHORE_LOOP: asyncio.AbstractEventLoop | None = None

# 需求抽取输出较长，默认限制为 3 路，避免并发请求争抢同一账号的生成吞吐。

def _usage_delta(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("prompt_tokens", "completion_tokens", "total_tokens", "calls", "retries", "cost_usd")
    delta: Dict[str, Any] = {}
    for key in keys:
        left = before.get(key) or 0
        right = after.get(key) or 0
        value = right - left
        delta[key] = round(value, 6) if isinstance(value, float) else value
    return delta


def _format_exc(exc: Exception) -> str:
    text = str(exc).strip()
    return text or exc.__class__.__name__


def _is_timeout_error(text: str) -> bool:
    lowered = (text or "").lower()
    return "timeouterror" in lowered or "timed out" in lowered or "timeout" in lowered


async def _call_dimension_llm(
    prompt: str,
    output_model: Type[BaseModel],
    max_tokens: int,
    timeout_override_seconds: int | None = None,
) -> BaseModel:
    global _LLM_CALL_SEMAPHORE, _LLM_CALL_SEMAPHORE_LIMIT, _LLM_CALL_SEMAPHORE_LOOP
    timeout_seconds = (
        timeout_override_seconds
        if timeout_override_seconds is not None
        else int(os.getenv("REQUIREMENTS_CALL_TIMEOUT_SECONDS", str(PER_DIMENSION_TIMEOUT_SECONDS)))
    )
    llm_concurrency = max(1, int(os.getenv("REQUIREMENTS_LLM_CONCURRENCY", "3")))
    current_loop = asyncio.get_running_loop()
    if (
        _LLM_CALL_SEMAPHORE is None
        or _LLM_CALL_SEMAPHORE_LIMIT != llm_concurrency
        or _LLM_CALL_SEMAPHORE_LOOP is not current_loop
    ):
        _LLM_CALL_SEMAPHORE = asyncio.Semaphore(llm_concurrency)
        _LLM_CALL_SEMAPHORE_LIMIT = llm_concurrency
        _LLM_CALL_SEMAPHORE_LOOP = current_loop
    async with _LLM_CALL_SEMAPHORE:
        call = llm_gateway.async_call_structured(
            prompt,
            output_model,
            max_tokens=max_tokens,
            network_max_retries=0,
        )
        if timeout_seconds <= 0:
            return await call
        return await asyncio.wait_for(call, timeout=timeout_seconds)


def _latest_usage() -> Dict[str, Any]:
    usage = llm_gateway.get_usage()
    return {
        "calls": usage.get("calls"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }


def _usage_snapshot() -> Dict[str, Any]:
    return llm_gateway.get_usage()


def _write_requirement_trace(event: Dict[str, Any]) -> None:
    trace_path = os.getenv("REQUIREMENTS_TRACE_PATH")
    if not trace_path:
        return
    try:
        record = {"ts": round(time.time(), 3), **event}
        with open(trace_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        logger.debug("[requirements] failed to write trace event", exc_info=True)


async def _extract_dimension_batch(
    config: DimensionConfig,
    batch: List[Dict[str, Any]],
    label: str,
    warnings: List[str],
    trace: Dict[str, Any] | None = None,
    split_depth: int = 0,
) -> List[Dict[str, Any]]:
    if trace is None:
        trace = {"retry_count": 0, "split_count": 0, "errors": []}
    prompt = _build_dimension_prompt(config, batch)
    try:
        call_timeout = None
        if split_depth > 0:
            call_timeout = max(1, int(os.getenv("REQUIREMENTS_SPLIT_CALL_TIMEOUT_SECONDS", "90")))
        elif config.name == "file_composition":
            call_timeout = max(
                1,
                int(os.getenv("REQUIREMENTS_FILE_COMPOSITION_TIMEOUT_SECONDS", "600")),
            )
        result = await _call_dimension_llm(
            prompt,
            config.output_model,
            config.max_tokens,
            timeout_override_seconds=call_timeout,
        )
        return [result.model_dump(mode="json")]
    except Exception as first_exc:
        trace["retry_count"] = int(trace.get("retry_count") or 0) + 1
        trace.setdefault("errors", []).append(_format_exc(first_exc))
        first_error_text = _format_exc(first_exc)
        logger.warning(
            "[requirements] {} failed once: {}; max_tokens={}, usage={}",
            label,
            first_error_text[:180],
            config.max_tokens,
            _latest_usage(),
        )
        if "throttling" in first_error_text or "429" in first_error_text:
            await asyncio.sleep(float(os.getenv("REQUIREMENTS_THROTTLE_RETRY_DELAY_SECONDS", "8")))
        max_split_depth = max(0, int(os.getenv("REQUIREMENTS_TIMEOUT_SPLIT_RETRY_DEPTH", "1")))
        if _is_timeout_error(first_error_text) and len(batch) > 1 and split_depth < max_split_depth:
            trace["split_count"] = int(trace.get("split_count") or 0) + 1
            mid = max(1, len(batch) // 2)
            logger.warning(
                "[requirements] {} timeout, retrying as split batches: {} + {} sections",
                label,
                len(batch[:mid]),
                len(batch[mid:]),
            )
            left, right = await asyncio.gather(
                _extract_dimension_batch(
                    config,
                    batch[:mid],
                    f"{label} split-a",
                    warnings,
                    trace,
                    split_depth + 1,
                ),
                _extract_dimension_batch(
                    config,
                    batch[mid:],
                    f"{label} split-b",
                    warnings,
                    trace,
                    split_depth + 1,
                ),
            )
            recovered = left + right
            if recovered:
                return recovered
        action = "skipped after timeout" if _is_timeout_error(first_error_text) else "failed"
        message = f"[requirements] {label} {action}: {first_error_text[:200]}"
        warnings.append(message)
        logger.error("{}; max_tokens={}, usage={}", message, config.max_tokens, _latest_usage())
        return []


async def _run_dimension_batch(
    config: DimensionConfig,
    batch: List[Dict[str, Any]],
    idx: int,
    total_batches: int,
    phase: str = "initial",
) -> Tuple[int, List[Dict[str, Any]], Dict[str, Any], int, List[str]]:
    prompt = _build_dimension_prompt(config, batch)
    prompt_chars = len(prompt)
    batch_ids = [str(item.get("section_id") or "") for item in batch]
    label = f"{config.name} batch {idx}/{total_batches}"
    if phase != "initial":
        label = f"{label} {phase}"
    logger.info(
        "[requirements] {}, sections={}, prompt_chars={}, max_tokens={}",
        label,
        ",".join(batch_ids),
        prompt_chars,
        config.max_tokens,
    )
    batch_started = time.time()
    trace: Dict[str, Any] = {"retry_count": 0, "split_count": 0, "errors": []}
    _write_requirement_trace(
        {
            "event": "batch_start",
            "dimension": config.name,
            "batch_index": idx,
            "batch_total": total_batches,
            "sections": batch_ids,
            "prompt_chars": prompt_chars,
            "max_tokens": config.max_tokens,
        }
    )
    warnings: List[str] = []
    payloads = await _extract_dimension_batch(config, batch, label, warnings, trace)
    batch_success = bool(payloads)
    batch_elapsed = time.time() - batch_started
    retry_count = int(trace.get("retry_count") or 0)
    errors = [str(item) for item in (trace.get("errors") or []) if item]
    if batch_success and retry_count:
        status = "retry"
    elif batch_success:
        status = "success"
    elif any(_is_timeout_error(error) for error in errors):
        status = "timeout"
    else:
        status = "failed"
    batch_stats = {
        "index": idx,
        "sections": batch_ids,
        "prompt_chars": prompt_chars,
        "elapsed_sec": round(batch_elapsed, 3),
        "status": status,
        "retry_count": retry_count,
        "split_count": int(trace.get("split_count") or 0),
        "error": errors[-1] if not batch_success and errors else None,
        "errors": errors,
        "phase": phase,
    }
    _write_requirement_trace(
        {
            "event": "batch_end",
            "dimension": config.name,
            "batch_index": idx,
            "batch_total": total_batches,
            "sections": batch_ids,
            "prompt_chars": prompt_chars,
            "elapsed_sec": round(batch_elapsed, 3),
            "status": status,
            "retry_count": retry_count,
            "split_count": int(trace.get("split_count") or 0),
            "error": errors[-1] if not batch_success and errors else None,
            "errors": errors,
            "phase": phase,
        }
    )
    return idx, payloads, batch_stats, prompt_chars, warnings
