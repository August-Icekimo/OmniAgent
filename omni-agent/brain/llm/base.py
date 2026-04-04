"""ModelClient ABC — 統一所有 LLM provider 的介面。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Message:
    role: Role
    content: str
    # 未來擴充 multimodal 時可加 images: list[bytes] 等欄位


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    usage: dict = field(default_factory=dict)
    # usage 範例: {"input_tokens": 100, "output_tokens": 50, "cache_read_tokens": 80}
    cached: bool = False


class ModelClient(ABC):
    """所有 LLM provider 的抽象基底類別。"""

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """發送對話請求，回傳 LLM 回應。"""
        ...

    @abstractmethod
    def provider_name(self) -> str:
        """回傳 provider 名稱，如 'claude', 'gemini', 'local'。"""
        ...

    @abstractmethod
    def model_name(self) -> str:
        """回傳目前使用的模型名稱。"""
        ...

    @abstractmethod
    async def supports_vision(self) -> bool:
        """此 provider 是否支援圖片輸入。"""
        ...
