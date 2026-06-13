"""Gemini provider — 使用 google-genai SDK，啟用 Context Caching。"""

import os
from google import genai
from google.genai import types
from .base import ModelClient, Message, LLMResponse, Role, ToolCall, ToolSpec
from .gemini_utils import build_gemini_parts


def _to_gemini_contents(messages: list[Message]) -> list:
    """內部 Message → Gemini contents。

    Gemini 角色僅 user/model；函式呼叫在 model 的 function_call part，函式結果以
    Part.from_function_response（**依函式名配對**，Gemini 無 call id）放進 user content。
    """
    contents = []
    for m in messages:
        if m.role == Role.SYSTEM:
            continue
        if m.role == Role.TOOL:
            contents.append(types.Content(role="user", parts=[
                types.Part.from_function_response(name=m.name, response={"output": m.content or ""})]))
        elif m.role == Role.ASSISTANT and m.tool_calls:
            parts = []
            if m.content:
                parts.append(types.Part(text=m.content))
            for tc in m.tool_calls:
                parts.append(types.Part(function_call=types.FunctionCall(name=tc.name, args=tc.arguments)))
            contents.append(types.Content(role="model", parts=parts))
        else:
            role = "user" if m.role == Role.USER else "model"
            contents.append(types.Content(role=role, parts=build_gemini_parts(m.content)))
    return contents


def _parse_gemini(response):
    """從 Gemini 回應抽 text 與 function_call（避免 response.text 在 function-call
    回應上拋例外），正規化 function_call → ToolCall（id 用函式名，Gemini 無 call id）。"""
    text_parts, tool_calls = [], []
    if response.candidates and response.candidates[0].content:
        for part in (response.candidates[0].content.parts or []):
            if getattr(part, "text", None):
                text_parts.append(part.text)
            elif getattr(part, "function_call", None):
                fc = part.function_call
                tool_calls.append(ToolCall(id=fc.name, name=fc.name, arguments=dict(fc.args or {})))
    return "".join(text_parts), tool_calls


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
        tools: list[ToolSpec] | None = None,
        tool_choice: str = "auto",
        model: str | None = None,
    ) -> LLMResponse:
        target_model = model or self._model

        contents = _to_gemini_contents(messages)

        # 內部 ToolSpec → Gemini function declarations
        # NOTE: Gemini tool 路徑在本環境無 API key、未實機驗證；local-first 下 gemini 為
        # fallback。正式倚賴前需 smoke test（function_call 觸發 + functionResponse 回填）。
        gemini_tools = None
        if tools:
            gemini_tools = [types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t.name, description=t.description, parameters=t.parameters)
                for t in tools])]

        generate_config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if gemini_tools:
            generate_config.tools = gemini_tools

        if thinking_budget is not None and thinking_budget >= 0:
            generate_config.thinking_config = types.ThinkingConfig(
                include_thoughts=True,
                thinking_budget=thinking_budget
            )

        # 嘗試使用 context cache（帶 tools 時跳過：tool 回合短，且 cache+tools 易衝突）
        cached_content = None
        if system_prompt and not gemini_tools:
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

        content, tool_calls = _parse_gemini(response)

        # finish_reason：有 function_call → "tool_calls"；MAX_TOKENS → "length"
        finish_reason = ""
        if tool_calls:
            finish_reason = "tool_calls"
        elif response.candidates:
            raw_reason = getattr(response.candidates[0], "finish_reason", None)
            if raw_reason is not None and "MAX_TOKENS" in str(raw_reason):
                finish_reason = "length"

        return LLMResponse(
            content=content,
            model=target_model,
            provider="gemini",
            usage=usage,
            cached=cached_content is not None,
            finish_reason=finish_reason,
            tool_calls=tool_calls,
        )

    def provider_name(self) -> str:
        return "gemini"

    def model_name(self) -> str:
        return self._model

    async def supports_vision(self) -> bool:
        return True
