"""LLM Provider 抽象基类。"""
from abc import ABC, abstractmethod
from contextvars import ContextVar
from typing import Type
from pydantic import BaseModel


class BaseLLMProvider(ABC):
    def __init__(self):
        self.__last_usage_context: ContextVar[dict] = ContextVar(
            f"provider_last_usage_{id(self)}",
            default={},
        )
        self.__last_retries_context: ContextVar[int] = ContextVar(
            f"provider_last_retries_{id(self)}",
            default=0,
        )

    @property
    def _last_usage(self) -> dict:
        return self.__last_usage_context.get()

    @_last_usage.setter
    def _last_usage(self, value: dict) -> None:
        self.__last_usage_context.set(dict(value or {}))

    @property
    def _last_retries(self) -> int:
        return self.__last_retries_context.get()

    @_last_retries.setter
    def _last_retries(self, value: int) -> None:
        self.__last_retries_context.set(int(value or 0))

    def get_last_usage(self) -> dict:
        return dict(self._last_usage or {})

    def get_last_retries(self) -> int:
        return int(self._last_retries or 0)

    @abstractmethod
    def generate_structured(
        self, prompt: str, schema: Type[BaseModel], **kwargs
    ) -> BaseModel:
        """同步接口。"""
        ...

    @abstractmethod
    async def async_generate_structured(
        self, prompt: str, schema: Type[BaseModel], **kwargs
    ) -> BaseModel:
        """异步接口:并行调用时使用。"""
        ...
