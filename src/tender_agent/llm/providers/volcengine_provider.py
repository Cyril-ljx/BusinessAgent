"""
火山引擎 Provider - V10.7。

★ V10.7 改动:
   1. temperature 默认值 0.1 → 0(降低输出随机性,提高同一招标书每次结果的一致性)
   2. 加 seed 参数(火山引擎支持 seed,固定 seed 进一步稳定输出)
   3. 去掉 wrap_openai(避免每个 LLM 调用变成独立 trace,让 LangGraph 统一管理)

【关于 temperature=0】
- temperature=0:LLM 选概率最高的 token,几乎确定性输出
- temperature=0.1:仍有少量随机
- temperature=0.7+:有创造性,适合写作场景
- 我们这是"映射"任务,需要确定性,所以 0 最合适

【关于 seed】
- 即使 temperature=0,如果不设 seed,模型实现内部仍可能因为浮点精度等原因有微小变化
- 设固定 seed 后,同样输入 → 同样输出(理论上)
- 火山引擎 GLM-5.1 支持 seed 参数
"""
import json
import re
from typing import Type

from openai import OpenAI, AsyncOpenAI
from pydantic import BaseModel

from ...config.settings import settings
from .base import BaseLLMProvider


_JSON_INSTRUCTION = """你必须严格按照以下 JSON Schema 输出,不要输出任何其他内容。
不要使用 Markdown 代码块包裹,直接输出纯 JSON 对象。

JSON Schema:
{schema}

记住:输出必须是合法的 JSON,字段名和层级必须完全匹配 Schema。"""


# ★ 固定 seed,提高输出稳定性
DEFAULT_SEED = 42


class VolcEngineProvider(BaseLLMProvider):
    """火山引擎 / 兼容 OpenAI 协议的 Provider。"""

    def __init__(self):
        super().__init__()
        if not settings.VOLCENGINE_API_KEY:
            raise RuntimeError("未配置 VOLCENGINE_API_KEY,请检查 .env")

        # 直接创建客户端（LangGraph 会自动管理 trace 层级）
        self.client = OpenAI(
            api_key=settings.VOLCENGINE_API_KEY,
            base_url=settings.VOLCENGINE_BASE_URL,
            timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
        )

        self.async_client = AsyncOpenAI(
            api_key=settings.VOLCENGINE_API_KEY,
            base_url=settings.VOLCENGINE_BASE_URL,
            timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
        )

        self.model = settings.VOLCENGINE_MODEL_NAME

    def _build_messages(self, prompt: str, schema: Type[BaseModel]) -> list[dict]:
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)
        system_msg = _JSON_INSTRUCTION.format(schema=schema_json)
        return [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ]

    def _parse_response(self, raw: str, schema: Type[BaseModel]) -> BaseModel:
        cleaned = self._clean_json(raw)
        try:
            data = json.loads(cleaned)
            return schema.model_validate(data)
        except json.JSONDecodeError:
            repaired = self._repair_json(cleaned)
            data = json.loads(repaired)
            return schema.model_validate(data)

    def _build_call_kwargs(self, kwargs: dict) -> dict:
        """统一组装 chat.completions.create 的参数。"""
        call_kwargs = {
            "model": self.model,
            # ★ 默认 temperature=0,确定性输出
            "temperature": kwargs.get("temperature", 0),
            "max_tokens": kwargs.get("max_tokens", 4096),
            # ★ 固定 seed
            "seed": kwargs.get("seed", DEFAULT_SEED),
        }
        if kwargs.get("timeout") is not None:
            call_kwargs["timeout"] = kwargs["timeout"]
        return call_kwargs

    def generate_structured(
        self, prompt: str, schema: Type[BaseModel], **kwargs
    ) -> BaseModel:
        self._last_retries = 0
        messages = self._build_messages(prompt, schema)
        call_kwargs = self._build_call_kwargs(kwargs)
        try:
            response = self.client.chat.completions.create(
                messages=messages,
                **call_kwargs,
            )
        except Exception as e:
            # 某些模型可能不支持 seed 参数,降级重试
            if "seed" in str(e).lower():
                self._last_retries += 1
                call_kwargs.pop("seed", None)
                response = self.client.chat.completions.create(
                    messages=messages,
                    **call_kwargs,
                )
            else:
                raise
        raw = (response.choices[0].message.content or "").strip()
        usage = getattr(response, "usage", None)
        self._last_usage = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
        return self._parse_response(raw, schema)

    async def async_generate_structured(
        self, prompt: str, schema: Type[BaseModel], **kwargs
    ) -> BaseModel:
        self._last_retries = 0
        messages = self._build_messages(prompt, schema)
        call_kwargs = self._build_call_kwargs(kwargs)
        try:
            response = await self.async_client.chat.completions.create(
                messages=messages,
                **call_kwargs,
            )
        except Exception as e:
            if "seed" in str(e).lower():
                self._last_retries += 1
                call_kwargs.pop("seed", None)
                response = await self.async_client.chat.completions.create(
                    messages=messages,
                    **call_kwargs,
                )
            else:
                raise
        raw = (response.choices[0].message.content or "").strip()
        usage = getattr(response, "usage", None)
        self._last_usage = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
        if not raw:
            # 方舟偶发返回空 content，降级重试一次（去 seed + 给一点随机性）
            self._last_retries += 1
            retry_kwargs = dict(call_kwargs)
            retry_kwargs.pop("seed", None)
            retry_kwargs["temperature"] = kwargs.get("retry_temperature", 0.2)
            response = await self.async_client.chat.completions.create(
                messages=messages,
                **retry_kwargs,
            )
            raw = (response.choices[0].message.content or "").strip()
            if not raw:
                raise ValueError("VolcEngine 返回空内容（两次重试后仍为空）")
        try:
            return self._parse_response(raw, schema)
        except Exception as exc:
            preview = raw[:220].replace("\n", "\\n")
            if isinstance(exc, json.JSONDecodeError):
                pos = max(exc.pos - 80, 0)
                around = raw[pos: exc.pos + 80].replace("\n", "\\n")
                raise ValueError(
                    f"VolcEngine 结构化解析失败: {exc}; around={around}; raw_preview={preview}"
                ) from exc
            raise ValueError(f"VolcEngine 结构化解析失败: {exc}; raw_preview={preview}") from exc

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
        """容错修复常见 LLM JSON 噪声：注释、尾逗号、BOM。"""
        fixed = text.strip().lstrip("\ufeff")
        # 去掉 // 行注释与 /* */ 块注释
        fixed = re.sub(r"//.*?$", "", fixed, flags=re.MULTILINE)
        fixed = re.sub(r"/\*.*?\*/", "", fixed, flags=re.DOTALL)
        # 去掉对象/数组末尾多余逗号
        fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
        return fixed
