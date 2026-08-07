"""
LLM Gateway。整个系统访问 LLM 的统一入口。
"""
import asyncio
import os
import random
import time
from contextvars import ContextVar
from typing import Any, Callable, Type

from pydantic import BaseModel

from ..config.settings import settings
from ..observability.langsmith_tracing import use_current_stage_parent
from .providers.base import BaseLLMProvider

try:
    from langsmith import traceable as _langsmith_traceable
except ImportError:  # pragma: no cover - LangSmith is optional at runtime.
    _langsmith_traceable = None


def _langsmith_tracing_enabled() -> bool:
    return any(
        os.getenv(name, "").lower() in {"1", "true", "yes", "on"}
        for name in ("LANGSMITH_TRACING", "LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING_V2")
    )


def _trace_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    prompt = str(inputs.get("prompt_preview") or "")
    return {
        "provider": inputs.get("provider_name"),
        "schema": inputs.get("schema_name"),
        "prompt": prompt[:1200],
    }


def _truncate_trace_value(
    value: Any,
    *,
    max_depth: int = 4,
    max_items: int = 8,
    max_chars: int = 500,
) -> Any:
    if max_depth <= 0:
        return f"<{type(value).__name__}>"
    if isinstance(value, str):
        if len(value) <= max_chars:
            return value
        return value[:max_chars] + f"... <truncated {len(value) - max_chars} chars>"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, BaseModel):
        return _truncate_trace_value(
            value.model_dump(),
            max_depth=max_depth - 1,
            max_items=max_items,
            max_chars=max_chars,
        )
    if isinstance(value, dict):
        items = list(value.items())
        result = {
            str(key): _truncate_trace_value(
                item,
                max_depth=max_depth - 1,
                max_items=max_items,
                max_chars=max_chars,
            )
            for key, item in items[:max_items]
        }
        if len(items) > max_items:
            result["_truncated_keys"] = len(items) - max_items
        return result
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        result = [
            _truncate_trace_value(
                item,
                max_depth=max_depth - 1,
                max_items=max_items,
                max_chars=max_chars,
            )
            for item in items[:max_items]
        ]
        if len(items) > max_items:
            result.append(f"... <truncated {len(items) - max_items} items>")
        return result
    return str(value)


def _trace_outputs(output: Any) -> dict[str, Any]:
    if isinstance(output, BaseModel):
        return {
            "schema": output.__class__.__name__,
            "fields": _truncate_trace_value(output.model_dump()),
        }
    return {
        "type": type(output).__name__,
        "value": _truncate_trace_value(output),
    }


def _trace_llm_sync(
    fn: Callable[[], BaseModel],
    *,
    run_name: str,
    prompt: str,
    schema: Type[BaseModel],
    provider_name: str,
) -> BaseModel:
    if _langsmith_traceable is None or not _langsmith_tracing_enabled():
        return fn()

    @_langsmith_traceable(
        name=run_name,
        run_type="llm",
        process_inputs=_trace_inputs,
        process_outputs=_trace_outputs,
        enabled=True,
    )
    def _traced_llm_call(prompt_preview: str, schema_name: str, provider_name: str) -> BaseModel:
        return fn()

    with use_current_stage_parent():
        return _traced_llm_call(prompt, schema.__name__, provider_name)


async def _trace_llm_async(
    fn: Callable[[], Any],
    *,
    run_name: str,
    prompt: str,
    schema: Type[BaseModel],
    provider_name: str,
) -> BaseModel:
    if _langsmith_traceable is None or not _langsmith_tracing_enabled():
        return await fn()

    @_langsmith_traceable(
        name=run_name,
        run_type="llm",
        process_inputs=_trace_inputs,
        process_outputs=_trace_outputs,
        enabled=True,
    )
    async def _traced_llm_call(prompt_preview: str, schema_name: str, provider_name: str) -> BaseModel:
        return await fn()

    with use_current_stage_parent():
        return await _traced_llm_call(prompt, schema.__name__, provider_name)


class LLMGateway:
    """统一模型路由层,支持运行时切换 Provider。"""

    def __init__(self):
        self._providers: dict[str, BaseLLMProvider] = {}
        self._usage_context: ContextVar[dict[str, float] | None] = ContextVar(
            "llm_usage_context",
            default=None,
        )

    @staticmethod
    def _empty_usage() -> dict[str, float]:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
            "retries": 0,
            "cost_usd": 0,
        }

    def reset_usage(self) -> None:
        # Context variables are inherited by child asyncio tasks, while separate
        # project tasks receive independent counters.
        self._usage_context.set(self._empty_usage())

    def _usage_totals(self) -> dict[str, float]:
        totals = self._usage_context.get()
        if totals is None:
            totals = self._empty_usage()
            self._usage_context.set(totals)
        return totals

    def get_usage(self) -> dict:
        return dict(self._usage_totals())

    def _provider_rates(self, provider_name: str) -> tuple[float, float]:
        if provider_name == "volcengine":
            return settings.COST_VOLCENGINE_INPUT_PER_M, settings.COST_VOLCENGINE_OUTPUT_PER_M
        if provider_name == "anthropic":
            return settings.COST_ANTHROPIC_INPUT_PER_M, settings.COST_ANTHROPIC_OUTPUT_PER_M
        return settings.COST_BAILIAN_INPUT_PER_M, settings.COST_BAILIAN_OUTPUT_PER_M

    def _accumulate_usage(self, provider: BaseLLMProvider, provider_name: str) -> None:
        totals = self._usage_totals()
        usage = provider.get_last_usage() or {}
        retries = provider.get_last_retries() if hasattr(provider, "get_last_retries") else 0
        totals["calls"] += 1
        totals["retries"] += retries
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
            v = usage.get(k)
            if isinstance(v, (int, float)):
                totals[k] += v
        in_tokens = usage.get("prompt_tokens") or 0
        out_tokens = usage.get("completion_tokens") or 0
        in_rate, out_rate = self._provider_rates(provider_name)
        totals["cost_usd"] += (in_tokens / 1_000_000) * in_rate + (out_tokens / 1_000_000) * out_rate

    def _record_gateway_retry(self) -> None:
        self._usage_totals()["retries"] += 1

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code in {408, 409, 425, 429, 500, 502, 503, 504}:
            return True
        text = f"{exc.__class__.__name__}: {exc}".lower()
        return any(
            marker in text
            for marker in (
                "timeout",
                "timed out",
                "connection",
                "temporarily unavailable",
                "rate limit",
                "throttl",
                "too many requests",
                "429",
                "502",
                "503",
                "504",
            )
        )

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        base = max(0.1, float(os.getenv("LLM_RETRY_BASE_SECONDS", "1")))
        maximum = max(base, float(os.getenv("LLM_RETRY_MAX_SECONDS", "12")))
        return min(maximum, base * (2 ** attempt)) + random.uniform(0, base * 0.25)

    @staticmethod
    def _max_network_retries() -> int:
        return max(0, int(os.getenv("LLM_NETWORK_MAX_RETRIES", "2")))

    def get_provider(self, provider_name: str = None) -> BaseLLMProvider:
        provider_name = provider_name or settings.DEFAULT_LLM_PROVIDER

        if provider_name in self._providers:
            return self._providers[provider_name]

        if provider_name == "volcengine":
            from .providers.volcengine_provider import VolcEngineProvider
            self._providers[provider_name] = VolcEngineProvider()
        elif provider_name == "bailian":
            from .providers.bailian_provider import BailianProvider
            self._providers[provider_name] = BailianProvider()
        elif provider_name == "token_plan":
            from .providers.token_plan_provider import TokenPlanProvider
            self._providers[provider_name] = TokenPlanProvider()
        elif provider_name == "anthropic":
            from .providers.anthropic_provider import AnthropicProvider
            self._providers[provider_name] = AnthropicProvider()
        else:
            raise ValueError(f"未知的 Provider: {provider_name}")

        return self._providers[provider_name]

    def call_structured(
        self,
        prompt: str,
        schema: Type[BaseModel],
        provider: str = None,
        **kwargs,
    ) -> BaseModel:
        """同步调用。"""
        provider_name = provider or settings.DEFAULT_LLM_PROVIDER
        call_kwargs = dict(kwargs)
        max_retries = max(
            0,
            int(call_kwargs.pop("network_max_retries", self._max_network_retries())),
        )

        def _impl():
            llm = self.get_provider(provider_name)
            for attempt in range(max_retries + 1):
                try:
                    result = llm.generate_structured(prompt, schema, **call_kwargs)
                except Exception as exc:
                    self._accumulate_usage(llm, provider_name)
                    if attempt >= max_retries or not self._is_retryable_error(exc):
                        raise
                    self._record_gateway_retry()
                    time.sleep(self._retry_delay(attempt))
                    continue
                self._accumulate_usage(llm, provider_name)
                return result
            raise RuntimeError("LLM retry loop exhausted")

        return _trace_llm_sync(
            _impl,
            run_name=f"llm:{schema.__name__}",
            prompt=prompt,
            schema=schema,
            provider_name=provider_name,
        )

    async def async_call_structured(
        self,
        prompt: str,
        schema: Type[BaseModel],
        provider: str = None,
        **kwargs,
    ) -> BaseModel:
        """异步调用:并行提取时使用。"""
        provider_name = provider or settings.DEFAULT_LLM_PROVIDER
        call_kwargs = dict(kwargs)
        max_retries = max(
            0,
            int(call_kwargs.pop("network_max_retries", self._max_network_retries())),
        )

        async def _impl():
            llm = self.get_provider(provider_name)
            for attempt in range(max_retries + 1):
                try:
                    result = await llm.async_generate_structured(prompt, schema, **call_kwargs)
                except Exception as exc:
                    self._accumulate_usage(llm, provider_name)
                    if attempt >= max_retries or not self._is_retryable_error(exc):
                        raise
                    self._record_gateway_retry()
                    await asyncio.sleep(self._retry_delay(attempt))
                    continue
                self._accumulate_usage(llm, provider_name)
                return result
            raise RuntimeError("LLM retry loop exhausted")

        return await _trace_llm_async(
            _impl,
            run_name=f"llm:{schema.__name__}",
            prompt=prompt,
            schema=schema,
            provider_name=provider_name,
        )


# 全局单例
llm_gateway = LLMGateway()
