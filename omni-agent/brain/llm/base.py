"""ModelClient ABC — 統一所有 LLM provider 的介面。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    # 工具結果回填：role=tool 的訊息攜帶某個 tool_call 的執行結果
    TOOL = "tool"


@dataclass
class ToolSpec:
    """提供給模型的工具描述（provider-native function calling 用）。

    `parameters` 為 JSON schema dict（type/properties/required…）；各 client
    再轉成自家 SDK 的 tool 格式（OpenAI tools / Anthropic tools / Gemini
    function declarations），形狀已收斂，差異只在外層包裝。
    """
    name: str
    description: str
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})


@dataclass
class ToolCall:
    """模型要求呼叫某工具：正規化後的統一格式（跨 provider 一致）。"""
    id: str
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass
class Message:
    role: Role
    content: str
    # assistant 回合要求呼叫工具時攜帶（role=assistant）
    tool_calls: list[ToolCall] | None = None
    # 工具結果回合（role=tool）：對應的 tool_call id 與工具名
    tool_call_id: str | None = None
    name: str | None = None
    # 未來擴充 multimodal 時可加 images: list[bytes] 等欄位


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    usage: dict = field(default_factory=dict)
    # usage 範例: {"input_tokens": 100, "output_tokens": 50, "cache_read_tokens": 80}
    cached: bool = False
    # "length"=被 max_tokens 硬截；"tool_calls"=模型要求呼叫工具（迴圈據此續跑）
    finish_reason: str = ""
    # provider-native tool calling 正規化結果；無工具呼叫時為空 list
    tool_calls: list[ToolCall] = field(default_factory=list)


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
        tools: list[ToolSpec] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        """發送對話請求，回傳 LLM 回應。

        傳入 `tools` 時啟用 provider-native function calling；模型可能回
        `tool_calls`（見 LLMResponse），此時 `finish_reason="tool_calls"`。
        不傳 `tools` 時行為與既有一致（向後相容）。
        """
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
