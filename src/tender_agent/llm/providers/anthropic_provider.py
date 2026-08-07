"""
Anthropic Claude Provider(可选,本期不强依赖)。

用裸 anthropic SDK,prompt 引导 JSON,与 volcengine 保持一致风格。
"""
import json
import re
from typing import Type

from pydantic import BaseModel

from ...config.settings import settings
from .base import BaseLLMProvider

# 软依赖:没装 anthropic 包也不影响其他 provider
try:
    from anthropic import Anthropic, AsyncAnthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False


_JSON_INSTRUCTION = """你必须严格按照以下 JSON Schema 输出,不要输出任何其他内容。
不要使用 Markdown 代码块包裹,直接输出纯 JSON 对象。

JSON Schema:
{schema}

记住:输出必须是合法的 JSON,字段名和层级必须完全匹配 Schema。"""


class AnthropicProvider(BaseLLMProvider):
    def __init__(self, model_name: str = None):
        super().__init__()
        if not _ANTHROPIC_AVAILABLE:
            raise RuntimeError("未安装 anthropic 包,执行 pip install anthropic")
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError("未配置 ANTHROPIC_API_KEY")
        self.client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.async_client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = model_name or settings.DEFAULT_MODEL_NAME

    def generate_structured(
        self, prompt: str, schema: Type[BaseModel], **kwargs
    ) -> BaseModel:
        self._last_retries = 0
        schema_json = json.dumps(
            schema.model_json_schema(), ensure_ascii=False, indent=2
        )
        call_kwargs = {
            "model": self.model,
            "max_tokens": kwargs.get("max_tokens", 8192),
            "temperature": kwargs.get("temperature", 0.1),
            "system": _JSON_INSTRUCTION.format(schema=schema_json),
            "messages": [{"role": "user", "content": prompt}],
        }
        if kwargs.get("timeout") is not None:
            call_kwargs["timeout"] = kwargs["timeout"]
        response = self.client.messages.create(**call_kwargs)

        raw = response.content[0].text.strip()
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        self._last_usage = {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": (input_tokens or 0) + (output_tokens or 0) if (input_tokens is not None or output_tokens is not None) else None,
        }
        cleaned = self._clean_json(raw)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM 输出不是合法 JSON:{e}\n原始输出:{raw[:500]}")

        return schema.model_validate(data)

    async def async_generate_structured(
        self, prompt: str, schema: Type[BaseModel], **kwargs
    ) -> BaseModel:
        self._last_retries = 0
        schema_json = json.dumps(
            schema.model_json_schema(), ensure_ascii=False, indent=2
        )
        call_kwargs = {
            "model": self.model,
            "max_tokens": kwargs.get("max_tokens", 8192),
            "temperature": kwargs.get("temperature", 0.1),
            "system": _JSON_INSTRUCTION.format(schema=schema_json),
            "messages": [{"role": "user", "content": prompt}],
        }
        if kwargs.get("timeout") is not None:
            call_kwargs["timeout"] = kwargs["timeout"]
        response = await self.async_client.messages.create(**call_kwargs)

        raw = response.content[0].text.strip()
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        self._last_usage = {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": (input_tokens or 0) + (output_tokens or 0) if (input_tokens is not None or output_tokens is not None) else None,
        }
        cleaned = self._clean_json(raw)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM 输出不是合法 JSON:{e}\n原始输出:{raw[:500]}")

        return schema.model_validate(data)

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
