"""Local MLX provider — 使用 openai SDK 連接 Mac Mini mlx-lm server。"""

import os
from openai import AsyncOpenAI
from .base import ModelClient, Message, LLMResponse


class LocalClient(ModelClient):
    """本地 MLX 客戶端，透過 OpenAI-compatible API 連接 Mac Mini。"""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
    ):
        self._base_url = base_url or os.environ.get(
            "MLX_BASE_URL", "http://mac-mini.local:8080/v1"
        )
        self._model = model or os.environ.get("MLX_MODEL", "mlx-community/Meta-Llama-3.1-8B-Instruct-4bit")
        self._client = AsyncOpenAI(
            base_url=self._base_url,
            api_key="not-needed",  # mlx-lm 不需要 API key
        )

    async def chat(
        self,
        messages: list[Message],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        oai_messages = []
        if system_prompt:
            oai_messages.append({"role": "system", "content": system_prompt})
        for m in messages:
            oai_messages.append({"role": m.role.value, "content": m.content})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=oai_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        choice = response.choices[0]
        usage = {}
        if response.usage:
            usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }

        return LLMResponse(
            content=choice.message.content or "",
            model=self._model,
            provider="local",
            usage=usage,
            cached=False,  # 本地模型無 cache 機制
        )

    def provider_name(self) -> str:
        return "local"

    def model_name(self) -> str:
        return self._model

    async def supports_vision(self) -> bool:
        return False  # mlx-lm 目前不支援 vision
