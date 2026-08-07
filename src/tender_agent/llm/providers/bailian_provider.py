"""阿里云百炼 / DashScope OpenAI 兼容 Provider。"""
import json
import re
from typing import Type

from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel

from ...config.settings import settings
from .base import BaseLLMProvider


_JSON_INSTRUCTION = """你必须严格按照以下 JSON Schema 输出,不要输出任何其他内容。
不要使用 Markdown 代码块包裹,直接输出纯 JSON 对象。

JSON Schema:
{schema}

记住:输出必须是合法的 JSON,字段名和层级必须完全匹配 Schema。"""


class BailianProvider(BaseLLMProvider):
    """百炼 OpenAI 兼容接口 Provider。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        provider_label: str = "BAILIAN",
    ):
        super().__init__()
        resolved_api_key = api_key if api_key is not None else settings.BAILIAN_API_KEY
        resolved_base_url = base_url if base_url is not None else settings.BAILIAN_BASE_URL
        resolved_model = model_name if model_name is not None else settings.BAILIAN_MODEL_NAME
        if not resolved_api_key:
            raise RuntimeError(f"未配置 {provider_label}_API_KEY,请检查 .env")

        self.client = OpenAI(
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )
        self.async_client = AsyncOpenAI(
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )
        self.model = resolved_model or "qwen3.6-plus"

    def _build_messages(self, prompt: str, schema: Type[BaseModel]) -> list[dict]:
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)
        system_msg = _JSON_INSTRUCTION.format(schema=schema_json)
        return [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ]

    def _build_call_kwargs(self, kwargs: dict) -> dict:
        call_kwargs = {
            "model": self.model,
            "temperature": kwargs.get("temperature", 0),
            # ★ V12: qwen3.6-plus 支持更长输出,从4096提升到8192
            "max_tokens": kwargs.get("max_tokens", 8192),
            # ★ V13: 开启百炼原生 JSON mode。
            # 不开时模型自由生成 JSON 文本再 parse,长输出极易格式崩(Expecting
            # property name)且生成极慢(逐字符硬生成,易撞超时)。开启后由服务端
            # 约束输出为合法 JSON,既快又稳。注意:json_object 要求 prompt 中出现
            # "JSON" 字样,本 provider 的 system 指令已满足。
            "response_format": {"type": "json_object"},
        }
        if kwargs.get("timeout") is not None:
            call_kwargs["timeout"] = kwargs["timeout"]
        # 允许调用方显式关闭(极少数非结构化场景),默认开启。
        if kwargs.get("disable_json_mode"):
            call_kwargs.pop("response_format", None)
        return call_kwargs

    def _parse_response(self, raw: str, schema: Type[BaseModel]) -> BaseModel:
        cleaned = self._clean_json(raw)
        try:
            data = json.loads(cleaned)
            if isinstance(data, list):
                data = {}
            return schema.model_validate(data)
        except json.JSONDecodeError:
            repaired = self._repair_json(cleaned)
            try:
                data = json.loads(repaired)
            except json.JSONDecodeError:
                data = json.loads(self._close_truncated_json(repaired))
            if isinstance(data, list):
                data = {}
            return schema.model_validate(data)

    def generate_structured(
        self, prompt: str, schema: Type[BaseModel], **kwargs
    ) -> BaseModel:
        self._last_retries = 0
        response = self.client.chat.completions.create(
            messages=self._build_messages(prompt, schema),
            **self._build_call_kwargs(kwargs),
        )
        raw = (response.choices[0].message.content or "").strip()
        finish_reason = getattr(response.choices[0], "finish_reason", None)
        usage = getattr(response, "usage", None)
        self._last_usage = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
            "finish_reason": finish_reason,
            "model": self.model,
            "max_tokens": kwargs.get("max_tokens", 8192),
        }
        if not raw:
            self._last_retries += 1
            retry_kwargs = dict(self._build_call_kwargs(kwargs))
            retry_kwargs.pop("seed", None)
            retry_kwargs["temperature"] = kwargs.get("retry_temperature", 0.2)
            response = self.client.chat.completions.create(
                messages=self._build_messages(prompt, schema),
                **retry_kwargs,
            )
            raw = (response.choices[0].message.content or "").strip()
            if not raw:
                raise ValueError("Bailian 返回空内容（两次重试后仍为空）")
        try:
            return self._parse_response(raw, schema)
        except Exception as exc:
            preview = raw[:220].replace("\n", "\\n")
            if isinstance(exc, json.JSONDecodeError):
                pos = max(exc.pos - 80, 0)
                around = raw[pos: exc.pos + 80].replace("\n", "\\n")
                raise ValueError(
                    f"Bailian 结构化解析失败: {exc}; around={around}; raw_preview={preview}"
                ) from exc
            raise ValueError(f"Bailian 结构化解析失败: {exc}; raw_preview={preview}") from exc

    async def async_generate_structured(
        self, prompt: str, schema: Type[BaseModel], **kwargs
    ) -> BaseModel:
        self._last_retries = 0
        response = await self.async_client.chat.completions.create(
            messages=self._build_messages(prompt, schema),
            **self._build_call_kwargs(kwargs),
        )
        raw = (response.choices[0].message.content or "").strip()
        finish_reason = getattr(response.choices[0], "finish_reason", None)
        usage = getattr(response, "usage", None)
        self._last_usage = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
            "finish_reason": finish_reason,
            "model": self.model,
            "max_tokens": kwargs.get("max_tokens", 8192),
        }
        if not raw:
            self._last_retries += 1
            retry_kwargs = dict(self._build_call_kwargs(kwargs))
            retry_kwargs.pop("seed", None)
            retry_kwargs["temperature"] = kwargs.get("retry_temperature", 0.2)
            response = await self.async_client.chat.completions.create(
                messages=self._build_messages(prompt, schema),
                **retry_kwargs,
            )
            raw = (response.choices[0].message.content or "").strip()
            if not raw:
                raise ValueError("Bailian 返回空内容（两次重试后仍为空）")
        try:
            return self._parse_response(raw, schema)
        except Exception as exc:
            preview = raw[:220].replace("\n", "\\n")
            if isinstance(exc, json.JSONDecodeError):
                pos = max(exc.pos - 80, 0)
                around = raw[pos: exc.pos + 80].replace("\n", "\\n")
                raise ValueError(
                    f"Bailian 结构化解析失败: {exc}; around={around}; raw_preview={preview}"
                ) from exc
            raise ValueError(f"Bailian 结构化解析失败: {exc}; raw_preview={preview}") from exc

    @staticmethod
    def _clean_json(raw: str) -> str:
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        if not cleaned.lstrip().startswith(("{", "[")):
            match = re.search(r"[\{\[]", cleaned)
            if match:
                cleaned = cleaned[match.start():]
                last_close = max(cleaned.rfind("}"), cleaned.rfind("]"))
                if last_close > 0:
                    cleaned = cleaned[: last_close + 1]
        return cleaned.strip()

    @staticmethod
    def _repair_json(text: str) -> str:
        """容错修复常见 LLM JSON 噪声：注释、尾逗号、BOM、分号。"""
        fixed = text.strip().lstrip("\ufeff")
        fixed = re.sub(r"//.*?$", "", fixed, flags=re.MULTILINE)
        fixed = re.sub(r"/\*.*?\*/", "", fixed, flags=re.DOTALL)
        # 有些模型在 JSON 字段值后误输出分号，例如:
        #   "severity": "P2";
        # 如果后面接对象/数组结束符，直接移除；如果后面接下一个字段，改成逗号。
        fixed = re.sub(r";\s*([}\]])", r"\1", fixed)
        fixed = re.sub(r";\s*(\"[^\"]+\"\s*:)", r", \1", fixed)
        # JavaScript 风格尾部分号，例如数组/对象后写成 ]; 或 };
        fixed = re.sub(r"([}\]])\s*;", r"\1", fixed)
        fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
        return fixed

    @staticmethod
    def _close_truncated_json(text: str) -> str:
        """Best-effort repair for JSON cut off near the end of generation."""
        fixed = text.strip().rstrip(",")
        if re.search(r":\s*$", fixed):
            fixed += " null"

        stack: list[str] = []
        in_string = False
        escaped = False
        for ch in fixed:
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == "\"":
                    in_string = False
                continue
            if ch == "\"":
                in_string = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]":
                if stack and stack[-1] == ch:
                    stack.pop()

        if in_string:
            fixed += "\""
        while stack:
            fixed = fixed.rstrip(",")
            fixed += stack.pop()
        return fixed
