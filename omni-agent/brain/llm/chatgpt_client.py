"""ChatGPT provider — 以 admin 的 ChatGPT Plus 額度呼叫 OpenAI Responses API（Sign in with ChatGPT）。

憑證由 scripts/siwc_login.py 在主機登入後產生，以目錄 volume 掛進容器（SIWC_CREDENTIALS 指向檔案）。
官方 preview 限制（developers.openai.com/siwc，2026-10-26 實測）：
- 必須 store=false、stream=true；歷史每次完整放進 input，不用 previous_response_id
- 不支援 temperature / max_output_tokens 等欄位（HTTP 400 "Unsupported parameter"）
- system prompt 走 instructions；function tools 以 namespace 分組，結果以 function_call_output 回填
- store=false 時 response.completed 的 output 為空，output items 只在 response.output_item.done 事件出現
- access token 1h、refresh token 30 天且每次輪替 → refresh 序列化並原子寫回
"""

import asyncio
import base64
import json
import logging
import os
import tempfile
import time
from datetime import datetime

import httpx
import openai
from openai import AsyncOpenAI

from .base import (
    CHECK_MODEL_TIMEOUT, ModelClient, ModelIdMismatch, Message, LLMResponse, Role, ToolCall, ToolSpec,
)

logger = logging.getLogger("brain.llm.chatgpt")

API_BASE = "https://api.openai.com/v1"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
# 工具統一放在單一 namespace（官方要求 function tools 須分組）
TOOL_NAMESPACE = "cindy"
# 到期前多久主動 refresh（秒）
REFRESH_MARGIN = 300
# 這些 refresh 錯誤代表 refresh token 已不可用，必須由 admin 重新登入（scripts/siwc_login.py start）
_TERMINAL_REFRESH_ERRORS = {
    "invalid_grant", "invalid_refresh_token", "token_expired", "refresh_token_expired",
    "refresh_token_invalidated", "refresh_token_reused", "invalid_client",
}


class ChatGPTAuthError(RuntimeError):
    """憑證已不可用（需重新登入）；router 視為 provider 失敗、轉 fallback。"""


class _TokenStore:
    """SIWC 憑證檔的讀取、到期前 refresh 與原子寫回（同一行程內以 lock 序列化）。"""

    def __init__(self, path: str):
        self._path = path
        self._cred: dict | None = None
        self._mtime = 0.0
        self._lock = asyncio.Lock()
        self._dead = False

    def _expires_at(self) -> float:
        saved = datetime.fromisoformat(self._cred["saved_at"]).timestamp()
        return saved + int(self._cred.get("expires_in", 3600))

    def _reload_if_changed(self) -> None:
        mtime = os.stat(self._path).st_mtime
        if self._cred is None or mtime != self._mtime:
            with open(self._path) as f:
                self._cred = json.load(f)
            self._mtime = mtime
            # admin 在主機重新登入會換掉檔案 → 解除停用
            self._dead = False

    def _write(self, cred: dict) -> None:
        d = os.path.dirname(self._path)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(cred, f, indent=2)
            os.replace(tmp, self._path)
        except BaseException:
            os.unlink(tmp)
            raise
        self._cred = cred
        self._mtime = os.stat(self._path).st_mtime

    async def _refresh(self) -> None:
        cred = self._cred
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(TOKEN_URL, data={
                "grant_type": "refresh_token",
                "client_id": cred["client_id"],
                "refresh_token": cred["refresh_token"],
                "resource": API_BASE,
            })
        if resp.status_code != 200:
            try:
                code = resp.json().get("error", "")
            except ValueError:
                code = ""
            if code in _TERMINAL_REFRESH_ERRORS:
                self._dead = True
                raise ChatGPTAuthError(
                    f"ChatGPT refresh token unusable ({code}) — run scripts/siwc_login.py start on the host")
            # 暫時性錯誤：保留憑證，交給下次再試
            raise RuntimeError(f"ChatGPT token refresh failed: HTTP {resp.status_code}")
        tok = resp.json()
        new = dict(cred)
        new.update({
            "access_token": tok["access_token"],
            "refresh_token": tok.get("refresh_token", cred["refresh_token"]),
            "token_type": tok.get("token_type", "Bearer"),
            "expires_in": tok.get("expires_in", 3600),
            "saved_at": datetime.now().astimezone().isoformat(),
        })
        if tok.get("id_token"):
            new["id_token"] = tok["id_token"]
        if tok.get("scope"):
            new["scopes"] = sorted(tok["scope"].split())
        self._write(new)
        logger.info("ChatGPT access token refreshed (refresh token rotated: %s)",
                    new["refresh_token"] != cred["refresh_token"])

    async def access_token(self, force_refresh: bool = False) -> str:
        async with self._lock:
            self._reload_if_changed()
            if self._dead:
                raise ChatGPTAuthError("ChatGPT credentials unusable — re-login required")
            if force_refresh or self._expires_at() - time.time() < REFRESH_MARGIN:
                await self._refresh()
            return self._cred["access_token"]


def _input_content(content):
    """內部 content（字串或 multimodal block list）→ Responses input content。"""
    if isinstance(content, str):
        return content
    parts = []
    for p in content:
        ptype = p.get("type")
        if ptype == "text":
            parts.append({"type": "input_text", "text": p["text"]})
        elif ptype == "image":
            data = p["data"]
            if isinstance(data, bytes):
                data = base64.b64encode(data).decode("utf-8")
            parts.append({"type": "input_image", "image_url": f"data:{p['mime_type']};base64,{data}"})
        else:
            # router 能力閘門已擋 audio/video；此處防禦，避免模型在沒拿到內容時照樣作答
            raise ValueError(f"ChatGPTClient unsupported content block type: {ptype}")
    return parts


def _to_responses_input(messages: list[Message], system_prompt: str | None) -> tuple[str | None, list]:
    """內部 Message → (instructions, input items)。

    system 一律併入 instructions（官方文件標明 system role item 會被拒）；
    assistant 的 tool_calls → function_call items；role=tool → function_call_output。
    """
    instructions = [system_prompt] if system_prompt else []
    items: list = []
    for m in messages:
        if m.role == Role.SYSTEM:
            if m.content:
                instructions.append(m.content)
            continue
        if m.role == Role.TOOL:
            items.append({"type": "function_call_output", "call_id": m.tool_call_id, "output": m.content or ""})
            continue
        if m.content:
            items.append({"role": m.role.value, "content": _input_content(m.content)})
        for tc in m.tool_calls or []:
            items.append({
                "type": "function_call", "call_id": tc.id, "name": tc.name, "namespace": TOOL_NAMESPACE,
                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
            })
    return ("\n\n".join(instructions) or None), items


def _tools_to_responses(tools: list[ToolSpec] | None):
    if not tools:
        return None
    return [{
        "type": "namespace",
        "name": TOOL_NAMESPACE,
        "description": "Cindy 的家庭助理工具",
        "tools": [
            {"type": "function", "name": t.name, "description": t.description, "parameters": t.parameters}
            for t in tools
        ],
    }]


def _parse_items(items: list[dict]) -> tuple[str, list[ToolCall]]:
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for it in items:
        if it.get("type") == "message":
            for c in it.get("content") or []:
                if c.get("type") == "output_text":
                    text_parts.append(c.get("text", ""))
        elif it.get("type") == "function_call":
            raw = it.get("arguments") or "{}"
            try:
                args = json.loads(raw)
            except (ValueError, TypeError):
                logger.warning("function_call arguments 非合法 JSON: %r", raw)
                args = {}
            tool_calls.append(ToolCall(id=it["call_id"], name=it["name"], arguments=args))
    return "".join(text_parts), tool_calls


class ChatGPTClient(ModelClient):
    """ChatGPT Plus（Sign in with ChatGPT）客戶端。"""

    def __init__(self, model: str | None = None, credentials_path: str | None = None):
        # 預設值須與 routing_config.json providers.chatgpt.model 一致（preflight 會同時檢查兩者）
        self._model = model or "gpt-6.1-sol"
        self._tokens = _TokenStore(credentials_path or os.environ["SIWC_CREDENTIALS"])

    def _client(self, token: str) -> AsyncOpenAI:
        # 重試交給 router fallback；SDK 自帶重試會在額度錯誤時白等
        return AsyncOpenAI(api_key=token, base_url=API_BASE, max_retries=0)

    async def chat(
        self,
        messages: list[Message],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[ToolSpec] | None = None,
        tool_choice: str = "auto",
        thinking_budget: int | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        # temperature / max_tokens：此路徑不支援（送出會 400），接受但忽略以維持介面一致
        instructions, items = _to_responses_input(messages, system_prompt)
        kwargs: dict = {"model": model or self._model, "input": items, "store": False, "stream": True}
        if instructions:
            kwargs["instructions"] = instructions
        # thinking_budget=0（routing 規則標記的感知類快路徑）→ reasoning effort low；
        # 實測 OCR 29s → 20s、輸出不變（2026-10-26）。其餘維持模型預設（medium）
        if thinking_budget == 0:
            kwargs["reasoning"] = {"effort": "low"}
        resp_tools = _tools_to_responses(tools)
        if resp_tools:
            kwargs["tools"] = resp_tools
            kwargs["tool_choice"] = "required" if tool_choice == "any" else tool_choice

        token = await self._tokens.access_token()
        try:
            stream = await self._client(token).responses.create(**kwargs)
        except openai.AuthenticationError:
            # access token 可能被提前撤銷：強制 refresh 一次再試
            token = await self._tokens.access_token(force_refresh=True)
            stream = await self._client(token).responses.create(**kwargs)

        out_items: list[dict] = []
        final = None
        try:
            async for ev in stream:
                if ev.type == "response.output_item.done":
                    out_items.append(ev.item.model_dump())
                elif ev.type in ("response.completed", "response.incomplete", "response.failed"):
                    final = ev
        except asyncio.CancelledError:
            logger.info("chatgpt turn cancelled — closing stream")
            raise
        finally:
            try:
                await stream.close()
            except BaseException:
                pass

        if final is None:
            raise RuntimeError("ChatGPT stream ended without a terminal event")
        if final.type == "response.failed":
            err = getattr(final.response, "error", None)
            code = getattr(err, "code", None) or "unknown"
            # subscription_sharing_usage_limit_exceeded 等額度錯誤：不重試，交給 router fallback
            raise RuntimeError(f"ChatGPT response failed: {code} — {getattr(err, 'message', '')}")

        content, tool_calls = _parse_items(out_items)
        usage = {}
        u = getattr(final.response, "usage", None)
        if u:
            usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens}
            cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
            if cached:
                usage["cache_read_tokens"] = cached

        if tool_calls:
            finish_reason = "tool_calls"
        elif final.type == "response.incomplete":
            reason = getattr(getattr(final.response, "incomplete_details", None), "reason", "")
            finish_reason = "length" if reason == "max_output_tokens" else (reason or "incomplete")
        else:
            finish_reason = "stop"

        return LLMResponse(
            content=content,
            model=getattr(final.response, "model", None) or kwargs["model"],
            provider="chatgpt",
            usage=usage,
            cached=bool(usage.get("cache_read_tokens")),
            finish_reason=finish_reason,
            tool_calls=tool_calls,
        )

    def provider_name(self) -> str:
        return "chatgpt"

    def model_name(self) -> str:
        return self._model

    async def check_model(self, model_id: str) -> None:
        # GET /v1/models（SIWC 回 {"models":[{slug, visibility, ...}]}，非標準 list 形狀）→ 直接用 httpx
        token = await self._tokens.access_token()
        async with httpx.AsyncClient(timeout=CHECK_MODEL_TIMEOUT) as http:
            resp = await http.get(f"{API_BASE}/models", headers={"Authorization": f"Bearer {token}"})
        if resp.status_code != 200:
            # 帶 status_code 讓 preflight._classify 分類（401/403 → unauthorized）
            err = RuntimeError(f"ChatGPT /models HTTP {resp.status_code}: {resp.text[:200]}")
            err.status_code = resp.status_code
            raise err
        body = resp.json()
        served = [m.get("slug") or m.get("id") for m in body.get("models", body.get("data", []))
                  if m.get("visibility", "list") == "list"]
        if model_id not in served:
            raise ModelIdMismatch(model_id, served)

    async def supports_vision(self) -> bool:
        return True
