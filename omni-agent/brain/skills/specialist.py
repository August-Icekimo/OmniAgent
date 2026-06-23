"""A2A specialist 委派 — brain 端 A2A client，把外包工作委派給 AGY 容器。

仿 [terminal.py](terminal.py) 的 SANDBOX_URL pattern：
- `AGY_A2A_URL` 未設定 → 回明確錯誤而非 crash。
- AGY 無回應/逾時 → 回降級訊息（不卡死；turn 層另有逾時保護，見 brain/main.py）。

委派走 A2A protocol（a2a-sdk 0.3.x client）：解析 Agent Card → 建 client →
送 single-turn message → 收結構化 artifact 文字。
"""

import logging
import os

import httpx

logger = logging.getLogger("brain.skills.specialist")

# 單次委派的 client 端逾時（秒）。須 < brain turn 處理逾時，讓本端先優雅降級。
_DELEGATE_TIMEOUT = float(os.getenv("AGY_DELEGATE_TIMEOUT", "60"))


def redact_names(text: str, names: list[str], placeholder: str = "[人名]") -> str:
    """送出前去識別化：把家人姓名從 task 文字中抹除（提案 D1 隱私邊界）。

    容器邊界即隱私邊界 — AGY 永遠看不到 people memory。此處做最後一道內容遮蔽：
    長名先換（避免短名為長名子字串造成殘留），略過長度 < 2 的名字以免過度遮蔽。
    """
    if not text or not names:
        return text
    uniq = {n.strip() for n in names if n and len(n.strip()) >= 2}
    for n in sorted(uniq, key=len, reverse=True):
        text = text.replace(n, placeholder)
    return text


def _extract_text(obj) -> str:
    """從 a2a Message / Artifact 取出純文字（parts[*].root.text 串接）。"""
    out = []
    for p in (getattr(obj, "parts", None) or []):
        r = getattr(p, "root", p)
        t = getattr(r, "text", None)
        if t:
            out.append(t)
    return "".join(out)


class SpecialistClient:
    """連 AGY A2A server 的委派 client。"""

    def __init__(self, base_url: str | None = None):
        self._base_url = (base_url or os.getenv("AGY_A2A_URL") or "").strip().rstrip("/")

    async def delegate(self, task: str) -> dict:
        """把 task 文字委派給 AGY specialist，回統一 dict 結果。

        成功: {"success": True, "data": {"result": "<文字>"}}
        失敗: {"success": False, "error": "<可讀訊息>"}
        """
        if not self._base_url:
            return {"success": False, "error": "AGY_A2A_URL 未設定，specialist 委派未啟用"}
        task = (task or "").strip()
        if not task:
            return {"success": False, "error": "缺少委派內容 task"}

        try:
            from a2a.client import (
                A2ACardResolver,
                ClientConfig,
                ClientFactory,
                create_text_message_object,
            )
        except ImportError as e:  # a2a-sdk 未安裝（理論上 requirements 已含）
            return {"success": False, "error": f"a2a-sdk 未安裝: {e}"}

        try:
            async with httpx.AsyncClient(timeout=_DELEGATE_TIMEOUT) as hx:
                card = await A2ACardResolver(
                    httpx_client=hx, base_url=self._base_url
                ).get_agent_card()
                client = ClientFactory(ClientConfig(httpx_client=hx)).create(card)
                msg = create_text_message_object(content=task)
                final = ""
                status_err = ""  # 失敗時的狀態訊息（供上層分類 429 等）
                async for event in client.send_message(msg):
                    # event 可能是 (Task, update) tuple 或 Message
                    if isinstance(event, tuple):
                        a2a_task, _ = event
                        st = getattr(a2a_task, "status", None)
                        if st is not None:
                            sm = getattr(st, "message", None)
                            if sm:
                                mt = _extract_text(sm)
                                if mt:
                                    status_err = mt
                        for art in (getattr(a2a_task, "artifacts", None) or []):
                            txt = _extract_text(art)
                            if txt:
                                final = txt
                    else:
                        txt = _extract_text(event)
                        if txt:
                            final = txt
                if not final.strip():
                    # 把狀態訊息原文回傳，讓 breaker 能分類 429（額度）等失敗。
                    return {"success": False, "error": status_err or "specialist 回傳空結果"}
                return {"success": True, "data": {"result": final.strip()}}
        except (httpx.TimeoutException, TimeoutError):
            logger.warning("specialist 委派逾時 (%ss)", _DELEGATE_TIMEOUT)
            return {"success": False, "error": "specialist 處理逾時，請稍後再試"}
        except Exception as e:  # noqa: BLE001 — 委派失敗回降級訊息，不拋出
            logger.error("specialist 委派失敗: %s", e)
            return {"success": False, "error": f"specialist 委派失敗: {e}"}


_client: SpecialistClient | None = None


def get_specialist_client() -> SpecialistClient:
    global _client
    if _client is None:
        _client = SpecialistClient()
    return _client
