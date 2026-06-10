"""Local MLX provider — 使用 openai SDK 連接 chrysoberyl Rapid-MLX server。

chrysoberyl (MacBook Pro M4) 跑 gemma-4-26b (4-bit)，benchmarked:
  - 34.5 tok/s, TTFT ~120 ms (no-think), ~2.2 s (think, 18× slower)
thinking_budget > 0 才啟用 enable_thinking；預設關閉。
"""

import os
from openai import AsyncOpenAI
from .base import ModelClient, Message, LLMResponse


class LocalClient(ModelClient):
    """本地 MLX 客戶端，透過 OpenAI-compatible API 連接 chrysoberyl。"""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        thinking_budget: int = -1,
    ):
        self._base_url = base_url or os.environ.get(
            "MLX_BASE_URL", "http://100.88.136.117:8000/v1"
        )
        self._model = model or os.environ.get("MLX_MODEL", "gemma-4-26b")
        self._thinking_budget = thinking_budget
        self._client = AsyncOpenAI(
            base_url=self._base_url,
            api_key="not-needed",
            timeout=120.0,
        )

    async def chat(
        self,
        messages: list[Message],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
        thinking_budget: int | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        oai_messages = []
        if system_prompt:
            oai_messages.append({"role": "system", "content": system_prompt})
        for m in messages:
            oai_messages.append({"role": m.role.value, "content": m.content})

        effective_budget = thinking_budget if thinking_budget is not None else self._thinking_budget
        # Always send enable_thinking explicitly — Gemma 4 defaults to thinking=on via chat template,
        # which causes message.content to be empty (mlx-lm issue #1352).
        extra = {"enable_thinking": effective_budget > 0}

        response = await self._client.chat.completions.create(
            model=model or self._model,
            messages=oai_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra,
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
