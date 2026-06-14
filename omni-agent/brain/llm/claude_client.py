"""Claude provider — 使用 anthropic 官方 SDK，啟用 Prompt Caching。"""

import os
import anthropic
from .base import ModelClient, Message, LLMResponse, Role, ToolCall, ToolSpec


def _to_anthropic_messages(messages: list[Message]) -> list[dict]:
    """內部 Message → Anthropic messages。

    Anthropic 沒有 tool role：工具結果以 `tool_result` block 放進 **user** 訊息，
    且同一輪的多個 tool_result 必須**合併進同一則 user 訊息**（緊跟在帶 tool_use
    的 assistant 訊息之後）。assistant 的 tool_calls → tool_use block。
    """
    out: list[dict] = []
    pending_results: list[dict] = []

    def flush_results():
        if pending_results:
            out.append({"role": "user", "content": list(pending_results)})
            pending_results.clear()

    for m in messages:
        if m.role == Role.SYSTEM:
            continue
        if m.role == Role.TOOL:
            pending_results.append({
                "type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content or ""})
            continue
        flush_results()
        if m.role == Role.ASSISTANT and m.tool_calls:
            blocks: list[dict] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            for tc in m.tool_calls:
                blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append({"role": m.role.value, "content": m.content})
    flush_results()
    return out


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
        tools: list[ToolSpec] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        kwargs: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": _to_anthropic_messages(messages),
        }

        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]
            kwargs["tool_choice"] = {"type": tool_choice}  # "auto" | "any"

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

        # 解析 content blocks：text 串接為 content，tool_use 正規化為 tool_calls
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input or {}))

        finish_reason = "tool_calls" if response.stop_reason == "tool_use" else (response.stop_reason or "")

        return LLMResponse(
            content="".join(text_parts),
            model=self._model,
            provider="claude",
            usage=usage,
            cached=cached,
            finish_reason=finish_reason,
            tool_calls=tool_calls,
        )

    def provider_name(self) -> str:
        return "claude"

    def model_name(self) -> str:
        return self._model

    async def supports_vision(self) -> bool:
        # 模型本身支援 vision，但本 client 尚未實作內部 image block →
        # Anthropic source 格式的轉換，原樣轉送會 400 — 在轉換完成前回報 False，
        # 讓 router 能力閘門跳過，避免 image payload 白打一次 API。
        return False
