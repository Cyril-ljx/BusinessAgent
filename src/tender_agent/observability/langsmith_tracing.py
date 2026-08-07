"""Small LangSmith tracing helpers used by API and graph stages.

The business pipeline already has LangGraph node traces, but LangGraph's callback
context is not always visible to our own LLM gateway calls.  These helpers keep a
project-local parent RunTree so gateway-created LLM spans can be attached to the
logical stage that issued the model call.
"""
from __future__ import annotations

import contextlib
import contextvars
import functools
import inspect
import os
from typing import Any, Callable, Iterator, TypeVar

try:  # LangSmith is optional in local/offline runs.
    from langsmith import traceable as _langsmith_traceable
    from langsmith.run_helpers import get_current_run_tree as _get_current_run_tree
    from langsmith.run_helpers import tracing_context as _tracing_context
except ImportError:  # pragma: no cover
    _langsmith_traceable = None
    _get_current_run_tree = None
    _tracing_context = None

F = TypeVar("F", bound=Callable[..., Any])

_current_stage_parent: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "tender_agent_langsmith_stage_parent",
    default=None,
)


def langsmith_tracing_enabled() -> bool:
    return any(
        os.getenv(name, "").lower() in {"1", "true", "yes", "on"}
        for name in ("LANGSMITH_TRACING", "LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING_V2")
    )


def _summarize_value(value: Any) -> Any:
    if isinstance(value, dict):
        summary: dict[str, Any] = {"keys": list(value.keys())[:20]}
        if "located_sections" in value:
            summary["located_sections"] = len(value.get("located_sections") or [])
        if "outline" in value:
            summary["outline_nodes"] = len(value.get("outline") or [])
        if "final_outline" in value:
            summary["final_outline_nodes"] = len(value.get("final_outline") or [])
        if "material_assignments" in value:
            summary["material_assignments"] = len(value.get("material_assignments") or [])
        return summary
    if isinstance(value, (list, tuple, set)):
        return {"type": type(value).__name__, "count": len(value)}
    return {"type": type(value).__name__}


def _stage_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    summarized: dict[str, Any] = {}
    for key, value in inputs.items():
        if key == "kwargs" and isinstance(value, dict):
            summarized[key] = {k: _summarize_value(v) for k, v in value.items()}
        elif key == "args" and isinstance(value, tuple):
            summarized[key] = [_summarize_value(v) for v in value[:3]]
        else:
            summarized[key] = _summarize_value(value)
    return summarized


def _stage_outputs(output: Any) -> dict[str, Any]:
    if isinstance(output, dict):
        result: dict[str, Any] = {"keys": list(output.keys())[:20]}
        if "located_sections" in output:
            result["located_sections"] = len(output.get("located_sections") or [])
        if "final_outline" in output:
            result["final_outline_nodes"] = len(output.get("final_outline") or [])
        if "material_assignments" in output:
            result["material_assignments"] = len(output.get("material_assignments") or [])
        if "generated_sections" in output:
            result["generated_sections"] = len(output.get("generated_sections") or {})
        return result
    if isinstance(output, (list, tuple, set)):
        return {"type": type(output).__name__, "count": len(output)}
    return {"type": type(output).__name__}


def _set_current_stage_parent() -> contextvars.Token | None:
    if _get_current_run_tree is None:
        return None
    parent = _get_current_run_tree()
    if parent is None:
        return None
    return _current_stage_parent.set(parent)


def trace_stage(name: str, *, run_type: str = "chain") -> Callable[[F], F]:
    """Trace a logical pipeline stage and expose it as parent for nested LLM calls."""

    def _decorate(fn: F) -> F:
        if _langsmith_traceable is None:
            return fn

        if inspect.iscoroutinefunction(fn):

            @_langsmith_traceable(
                name=name,
                run_type=run_type,
                process_inputs=_stage_inputs,
                process_outputs=_stage_outputs,
                enabled=langsmith_tracing_enabled(),
            )
            @functools.wraps(fn)
            async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
                token = _set_current_stage_parent()
                try:
                    return await fn(*args, **kwargs)
                finally:
                    if token is not None:
                        _current_stage_parent.reset(token)

            return _async_wrapper  # type: ignore[return-value]

        @_langsmith_traceable(
            name=name,
            run_type=run_type,
            process_inputs=_stage_inputs,
            process_outputs=_stage_outputs,
            enabled=langsmith_tracing_enabled(),
        )
        @functools.wraps(fn)
        def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            token = _set_current_stage_parent()
            try:
                return fn(*args, **kwargs)
            finally:
                if token is not None:
                    _current_stage_parent.reset(token)

        return _sync_wrapper  # type: ignore[return-value]

    return _decorate


@contextlib.contextmanager
def use_current_stage_parent() -> Iterator[None]:
    """Attach a nested traceable run to the current logical stage when available."""
    parent = _current_stage_parent.get()
    if parent is None or _tracing_context is None:
        yield
        return
    with _tracing_context(parent=parent, enabled=langsmith_tracing_enabled()):
        yield
