"""Claude provider — 使用 anthropic 官方 SDK，啟用 Prompt Caching。"""

import os
import anthropic
from .base import ModelClient, Message, LLMResponse, Role


class ClaudeClient(ModelClient):
    """Anthropic Claude 客戶端，支援 prompt caching。"""

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self._client = anthropic.AsyncAnthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
        )
        self._model = model

    async def chat(
        self,
        messages: list[Message],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        kwargs: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": m.role.value, "content": m.content}
                for m in messages
                if m.role != Role.SYSTEM
            ],
        }

        # Prompt Caching：將 system prompt 標記為可快取
        # 這會讓 Anthropic 在伺服器端快取此段 prompt，後續請求直接命中
        # 對於每次都注入的 SOUL.md 來說，cache hit rate 會非常高
        if system_prompt:
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        response = await self._client.messages.create(**kwargs)

        usage = {}
        if response.usage:
            usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
            # cache 相關 usage 欄位（如果有的話）
            if hasattr(response.usage, "cache_creation_input_tokens"):
                usage["cache_creation_tokens"] = response.usage.cache_creation_input_tokens
            if hasattr(response.usage, "cache_read_input_tokens"):
                usage["cache_read_tokens"] = response.usage.cache_read_input_tokens

        cached = usage.get("cache_read_tokens", 0) > 0

        return LLMResponse(
            content=response.content[0].text,
            model=self._model,
            provider="claude",
            usage=usage,
            cached=cached,
        )

    def provider_name(self) -> str:
        return "claude"

    def model_name(self) -> str:
        return self._model

    async def supports_vision(self) -> bool:
        return True
