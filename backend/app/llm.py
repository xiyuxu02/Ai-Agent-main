"""LLM 配置与实例管理。"""

import math
import os
import re
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


load_dotenv()


def _non_empty_string(value: object, setting_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{setting_name} must be a non-empty string.")
    return value.strip()


def _parse_temperature(value: object) -> float:
    """Strictly parse a finite model temperature in the OpenAI-compatible range."""
    if isinstance(value, bool):
        raise ValueError("TEMPERATURE must be a number between 0 and 2.")
    try:
        temperature = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("TEMPERATURE must be a number between 0 and 2.") from exc
    if not math.isfinite(temperature) or not 0 <= temperature <= 2:
        raise ValueError("TEMPERATURE must be a finite number between 0 and 2.")
    return temperature


def _parse_max_tokens(value: object) -> int:
    """Strictly parse a positive integer without accepting floats or booleans."""
    if isinstance(value, bool):
        raise ValueError("MAX_TOKENS must be a positive integer.")
    if isinstance(value, int):
        max_tokens = value
    elif isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value.strip()):
        max_tokens = int(value.strip())
    else:
        raise ValueError("MAX_TOKENS must be a positive integer.")
    if max_tokens <= 0:
        raise ValueError("MAX_TOKENS must be a positive integer.")
    return max_tokens


@dataclass(frozen=True)
class LLMSettings:
    """Validated settings used to construct the OpenAI-compatible client."""

    model: str
    temperature: float
    api_key: str = field(repr=False)
    max_tokens: int
    base_url: str

    @classmethod
    def from_env(
        cls,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        api_key: Optional[str] = None,
        max_tokens: Optional[int] = None,
        base_url: Optional[str] = None,
    ) -> "LLMSettings":
        """Resolve explicit overrides first, then strictly validate environment values."""
        resolved_model = _non_empty_string(
            model if model is not None else os.getenv("OPENAI_MODEL", "deepseek-chat"),
            "OPENAI_MODEL",
        )
        resolved_temperature = _parse_temperature(
            temperature if temperature is not None else os.getenv("TEMPERATURE", "0.7")
        )
        resolved_api_key = _non_empty_string(
            api_key if api_key is not None else os.getenv("OPENAI_API_KEY"),
            "OPENAI_API_KEY",
        )
        resolved_max_tokens = _parse_max_tokens(
            max_tokens if max_tokens is not None else os.getenv("MAX_TOKENS", "2000")
        )
        resolved_base_url = _non_empty_string(
            base_url
            if base_url is not None
            else os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
            "OPENAI_BASE_URL",
        )
        return cls(
            model=resolved_model,
            temperature=resolved_temperature,
            api_key=resolved_api_key,
            max_tokens=resolved_max_tokens,
            base_url=resolved_base_url,
        )


class LLMManager:
    """LLM 管理器，负责模型配置和初始化。"""

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        api_key: Optional[str] = None,
        max_tokens: Optional[int] = None,
        base_url: Optional[str] = None,
        streaming: bool = True,
    ):
        self.settings = LLMSettings.from_env(
            model=model,
            temperature=temperature,
            api_key=api_key,
            max_tokens=max_tokens,
            base_url=base_url,
        )
        self.model = self.settings.model
        self.temperature = self.settings.temperature
        self.api_key = self.settings.api_key
        self.max_tokens = self.settings.max_tokens
        self.base_url = self.settings.base_url
        self.streaming = streaming
        self.llm = self._create_llm()

    def _create_llm(self) -> ChatOpenAI:
        return ChatOpenAI(
            model=self.model,
            temperature=self.temperature,
            api_key=self.api_key,
            base_url=self.base_url,
            max_tokens=self.max_tokens,
            streaming=self.streaming,
            callbacks=[],
        )

    def get_llm(self) -> ChatOpenAI:
        return self.llm


_llm_manager: Optional[LLMManager] = None
_llm_manager_lock = Lock()


def get_llm_manager() -> LLMManager:
    """线程安全地获取全局 LLM 管理器实例。"""
    global _llm_manager
    if _llm_manager is None:
        with _llm_manager_lock:
            if _llm_manager is None:
                _llm_manager = LLMManager()
    return _llm_manager


def get_llm() -> ChatOpenAI:
    """获取全局 LLM 实例。"""
    return get_llm_manager().get_llm()
