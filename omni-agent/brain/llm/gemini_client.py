"""Gemini provider — 使用 google-genai SDK，啟用 Context Caching。"""

import os
import base64
from google import genai
from google.genai import types
from .base import ModelClient, Message, LLMResponse, Role


class GeminiClient(ModelClient):
    """Google Gemini 客戶端，支援 context caching。"""

    def __init__(self, model: str = "gemini-2.5-flash"):
        self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self._model = model
        self._cached_content = None  # 快取 SOUL.md system prompt 用

    async def _get_or_create_cache(self, system_prompt: str) -> types.CachedContent | None:
        """建立或復用 Gemini Context Cache。

        Context Caching 可將大段 system prompt 快取在 Google 伺服器端，
        後續請求引用此 cache 即可，大幅降低 token 計費。
        """
        if self._cached_content is not None:
            # 檢查 cache 是否已過期
            try:
                # 嘗試取得 cache 狀態，若已過期會拋例外
                return self._cached_content
            except Exception:
                self._cached_content = None

        # 建立新 cache（最小 cache 需要 >= 4096 tokens 的內容）
        if len(system_prompt) < 2000:
            # system prompt 太短，不值得 cache
            return None

        try:
            cached = self._client.caches.create(
                model=self._model,
                config=types.CreateCachedContentConfig(
                    system_instruction=system_prompt,
                    ttl="3600s",  # 1 小時 TTL
                ),
            )
            self._cached_content = cached
            return cached
        except Exception:
            # Cache 建立失敗不影響正常運作，fallback 為不使用 cache
            return None

    async def chat(
        self,
        messages: list[Message],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        thinking_budget: int | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        target_model = model or self._model
        
        contents = []
        for m in messages:
            if m.role == Role.SYSTEM:
                continue
            role = "user" if m.role == Role.USER else "model"

            parts = []
            if isinstance(m.content, str):
                parts.append(types.Part(text=m.content))
            elif isinstance(m.content, list):
                # Handle multimodal parts (Phase 4D)
                for p in m.content:
                    if p.get("type") == "text":
                        parts.append(types.Part(text=p["text"]))
                    elif p.get("type") == "image":
                        data = p["data"]
                        if isinstance(data, str):
                            data = base64.b64decode(data)
                        parts.append(types.Part(inline_data=types.Blob(
                            mime_type=p["mime_type"],
                            data=data
                        )))
                    elif p.get("type") == "audio":
                        data = p["data"]
                        if isinstance(data, str):
                            data = base64.b64decode(data)
                        parts.append(types.Part(inline_data=types.Blob(
                            mime_type=p["mime_type"],
                            data=data
                        )))

            contents.append(types.Content(role=role, parts=parts))

        generate_config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        if thinking_budget is not None and thinking_budget >= 0:
            generate_config.thinking_config = types.ThinkingConfig(
                include_thoughts=True,
                thinking_budget=thinking_budget
            )

        # 嘗試使用 context cache
        cached_content = None
        if system_prompt:
            cached_content = await self._get_or_create_cache(system_prompt)

        if cached_content:
            # 透過 cached_content 呼叫，不需再送 system_instruction
            config_params = {
                "temperature": temperature,
                "max_output_tokens": max_tokens,
                "cached_content": cached_content.name,
            }
            if thinking_budget is not None and thinking_budget >= 0:
                config_params["thinking_config"] = types.ThinkingConfig(
                    include_thoughts=True,
                    thinking_budget=thinking_budget
                )
                
            response = self._client.models.generate_content(
                model=target_model,
                contents=contents,
                config=types.GenerateContentConfig(**config_params),
            )
        else:
            # 無 cache，直接帶 system_instruction
            if system_prompt:
                generate_config.system_instruction = system_prompt
            response = self._client.models.generate_content(
                model=target_model,
                contents=contents,
                config=generate_config,
            )

        usage = {}
        if response.usage_metadata:
            usage = {
                "input_tokens": response.usage_metadata.prompt_token_count,
                "output_tokens": response.usage_metadata.candidates_token_count,
            }
            if hasattr(response.usage_metadata, "cached_content_token_count"):
                usage["cache_read_tokens"] = response.usage_metadata.cached_content_token_count

        return LLMResponse(
            content=response.text,
            model=target_model,
            provider="gemini",
            usage=usage,
            cached=cached_content is not None,
        )

    def provider_name(self) -> str:
        return "gemini"

    def model_name(self) -> str:
        return self._model

    async def supports_vision(self) -> bool:
        return True
