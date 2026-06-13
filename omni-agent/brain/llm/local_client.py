"""Local MLX provider — 使用 openai SDK 連接 chrysoberyl Rapid-MLX server。

chrysoberyl (MacBook Pro M4) 跑 gemma-4-26b (4-bit)，benchmarked:
  - 34.5 tok/s, TTFT ~120 ms (no-think), ~2.2 s (think, 18× slower)
thinking_budget > 0 才啟用 enable_thinking；預設關閉。

2026-06-12 起 server 以 --mllm --no-thinking 運行，支援圖片輸入
（audio/video block Rapid-MLX 會靜默丟棄，本端直接拒收讓 router fallback）。
"""

import base64
import json
import logging
import os
import re

from openai import AsyncOpenAI
from .base import ModelClient, Message, LLMResponse, Role, ToolCall, ToolSpec

logger = logging.getLogger("brain.llm.local")

# Gemma 4 在 MLLM 模式下 per-request enable_thinking 失效，模型會在答案後
# 漏出 thought 標記接續碎念（google-deepmind/gemma#622），以 stop 截斷。
# 代價：合法英文回應中的 "thought" 一詞也會被截斷 — 家庭中文場景可接受。
_STOP_SEQUENCES = ["thought"]

# thought 截斷點前偶見殘留的外文殘 token（實測出現過泰文 'ต์'）。
# 這些文字在 Cindy 的家庭場景不可能合法出現，直接視為碎屑修剪。
_FOREIGN_TAIL = re.compile(
    r"[̀-ͯ֐-׿؀-ۿऀ-෿฀-๿]+$"
)
# 「有意義內容」：CJK、日韓、拉丁數字、emoji 與常用符號。
_MEANINGFUL = re.compile(
    r"[一-鿿㐀-䶿぀-ヿ가-힯"
    r"A-Za-z0-9"
    r"\U0001F000-\U0001FAFF☀-➿←-⇿⬀-⯿]"
)


def _to_openai_content(content):
    """內部 multimodal block list → OpenAI chat content；純字串原樣回傳。

    內部格式與 gemini_utils.build_gemini_parts 同源：
    {"type": "text"|"image"|"audio"|"video", "mime_type": ..., "data": b64|bytes}
    """
    if isinstance(content, str):
        return content
    parts = []
    for p in content:
        ptype = p.get("type")
        if ptype == "text":
            parts.append({"type": "text", "text": p["text"]})
        elif ptype == "image":
            data = p["data"]
            if isinstance(data, bytes):
                data = base64.b64encode(data).decode("utf-8")
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{p['mime_type']};base64,{data}"},
            })
        else:
            # Rapid-MLX 0.6.82 對 audio/video block 是靜默丟棄而非報錯，
            # 模型會在沒拿到內容的情況下一本正經回覆 — 必須在本端擋下。
            raise ValueError(f"LocalClient unsupported content block type: {ptype}")
    return parts


def _clean_output(text: str) -> str:
    """清理 Gemma 4 MLLM 模式的輸出殘留（thought 漏標記、外文殘 token、孤立碎屑行）。"""
    cleaned = text
    # stop 序列理應已在 server 端截斷；此處為防禦（如 server 端 stop 失效）。
    idx = cleaned.find("thought")
    if idx != -1:
        cleaned = cleaned[:idx]
    cleaned = cleaned.rstrip()
    cleaned = _FOREIGN_TAIL.sub("", cleaned).rstrip()
    # 尾端孤立碎屑行：整行不含任何有意義字元（CJK/拉丁/數字/emoji）才修剪
    if "\n" in cleaned:
        head, _, tail = cleaned.rpartition("\n")
        if tail.strip() and not _MEANINGFUL.search(tail):
            cleaned = head.rstrip()
    return cleaned


def _tools_to_openai(tools: list[ToolSpec] | None):
    """內部 ToolSpec → OpenAI tools 格式。"""
    if not tools:
        return None
    return [
        {"type": "function", "function": {
            "name": t.name, "description": t.description, "parameters": t.parameters}}
        for t in tools
    ]


def _oai_message(m: Message) -> dict:
    """內部 Message → OpenAI chat message，含 tool_calls / tool-result 回合。"""
    if m.role == Role.TOOL:
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content or ""}
    msg: dict = {"role": m.role.value, "content": _to_openai_content(m.content)}
    if m.tool_calls:
        msg["tool_calls"] = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)}}
            for tc in m.tool_calls
        ]
    return msg


def _parse_tool_calls(message) -> list[ToolCall]:
    """OpenAI 回傳的 tool_calls → 統一 ToolCall（arguments 解析成 dict，容錯）。"""
    out = []
    for tc in (getattr(message, "tool_calls", None) or []):
        raw = tc.function.arguments or "{}"
        try:
            args = json.loads(raw)
        except (ValueError, TypeError):
            logger.warning("tool_call arguments 非合法 JSON: %r", raw)
            args = {}
        out.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
    return out


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
        tools: list[ToolSpec] | None = None,
        tool_choice: str = "auto",
        model: str | None = None,
    ) -> LLMResponse:
        oai_messages = []
        if system_prompt:
            oai_messages.append({"role": "system", "content": system_prompt})
        for m in messages:
            oai_messages.append(_oai_message(m))

        effective_budget = thinking_budget if thinking_budget is not None else self._thinking_budget
        # Always send enable_thinking explicitly — Gemma 4 defaults to thinking=on via chat template,
        # which causes message.content to be empty (mlx-lm issue #1352).
        extra = {"enable_thinking": effective_budget > 0}

        kwargs = dict(
            model=model or self._model,
            messages=oai_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra,
        )
        oai_tools = _tools_to_openai(tools)
        if oai_tools:
            kwargs["tools"] = oai_tools
            kwargs["tool_choice"] = tool_choice
        else:
            # stop 序列只在純文字生成時套用；tool calling 模式不需要、避免干擾
            kwargs["stop"] = _STOP_SEQUENCES

        response = await self._client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        usage = {}
        if response.usage:
            usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }

        tool_calls = _parse_tool_calls(choice.message)
        raw_content = choice.message.content or ""
        # 有 tool_calls 時 content 通常為空，且不需 thought 清理
        content = raw_content if tool_calls else _clean_output(raw_content)
        if not tool_calls and content != raw_content:
            logger.info(
                "Local output cleaned: %d -> %d chars (finish_reason=%s)",
                len(raw_content), len(content), choice.finish_reason,
            )

        return LLMResponse(
            content=content,
            model=self._model,
            provider="local",
            usage=usage,
            cached=False,  # 本地模型無 cache 機制
            finish_reason=choice.finish_reason or "",
            tool_calls=tool_calls,
        )

    def provider_name(self) -> str:
        return "local"

    def model_name(self) -> str:
        return self._model

    async def supports_vision(self) -> bool:
        return True  # Rapid-MLX --mllm 模式，gemma-4-26b 含 vision tower
