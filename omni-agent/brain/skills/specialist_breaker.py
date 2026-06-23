"""AGY specialist 的 429 circuit breaker（提案 D3，完整實作）。

狀態落 `home_context`（key=`agy:circuit_breaker`），crash-safe，**不需新 schema**
（沿用 router 既有的 quota-cooldown kv 模式）。

語意：
- API Key 層遇 429（Free Tier 額度耗盡）→ breaker **open** `AGY_BREAKER_OPEN_SECONDS`
  （預設 5hr）→ open 期間新委派直接降級、不送 AGY → 屆時 **half-open** 放行一次試打，
  成功則 **close**、再失敗（仍 429）則重新 trip。
- trip 時通知所有 admin（Telegram，沿用 proactive 的 admin 推播查詢）。
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger("brain.skills.specialist_breaker")

_KEY = "agy:circuit_breaker"
_OPEN_SECONDS = int(os.getenv("AGY_BREAKER_OPEN_SECONDS", str(5 * 3600)))

# 429 / 額度耗盡的文字標記（用於從委派失敗訊息分類是否為配額問題）。
_QUOTA_MARKERS = (
    "429", "resource_exhausted", "resourceexhausted", "quota",
    "rate limit", "ratelimit", "too many requests",
)


def is_quota_error(text: str) -> bool:
    t = (text or "").lower()
    return any(m in t for m in _QUOTA_MARKERS)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_dict(value) -> dict:
    """home_context.value（jsonb）可能被 asyncpg 回成 str 或 dict（本專案無註冊
    jsonb codec，main.py 以 json.loads 取用），兩種都容忍。"""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value or {}


async def allow(pool) -> tuple[bool, bool]:
    """回 (allowed, half_open)。

    allowed=False → breaker 仍 open，呼叫端應直接降級、不送 AGY。
    half_open=True → 已過 open_until，放行這一次試打（成功要 close、失敗要重新 trip）。
    無 pool 或無狀態 → (True, False)（視為 closed）。
    """
    if not pool:
        return True, False
    row = await pool.fetchrow("SELECT value FROM home_context WHERE key=$1", _KEY)
    if not row:
        return True, False
    val = _as_dict(row["value"])
    if val.get("state") != "open":
        return True, False
    try:
        ou = datetime.fromisoformat(val["open_until"]) if val.get("open_until") else None
    except (ValueError, TypeError):
        ou = None
    if ou and _now() >= ou:
        return True, True   # half-open
    return False, False     # 仍 open


async def trip(pool, reason: str = "429") -> None:
    """開啟 breaker（open 5hr）並通知 admin。"""
    if not pool:
        return
    until = _now() + timedelta(seconds=_OPEN_SECONDS)
    val = {
        "state": "open",
        "opened_at": _now().isoformat(),
        "open_until": until.isoformat(),
        "reason": reason[:300],
    }
    await pool.execute(
        """
        INSERT INTO home_context (key, value) VALUES ($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
        """,
        _KEY, json.dumps(val),
    )
    logger.warning("AGY circuit breaker OPEN until %s (reason=%s)", until.isoformat(), reason[:120])
    local = until.astimezone().strftime("%Y-%m-%d %H:%M")
    await _notify_admins(
        pool,
        f"⚠️ AGY specialist 暫停：偵測到 API 額度 429，已暫停委派至 {local}"
        f"（約 {_OPEN_SECONDS // 3600} 小時後自動重試）。",
    )


async def close(pool) -> None:
    """關閉 breaker（half-open 試打成功後呼叫）。"""
    if not pool:
        return
    await pool.execute(
        """
        INSERT INTO home_context (key, value) VALUES ($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
        """,
        _KEY, json.dumps({"state": "closed", "closed_at": _now().isoformat()}),
    )
    logger.info("AGY circuit breaker CLOSED")


async def _notify_admins(pool, text: str) -> None:
    """推播給所有 admin（Telegram），沿用 proactive._send_to_admins 的查詢。"""
    bot = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot:
        logger.warning("TELEGRAM_BOT_TOKEN 未設，breaker admin 通知略過")
        return
    try:
        rows = await pool.fetch(
            "SELECT chat_id FROM telegram_accounts ta "
            "JOIN users u ON ta.user_id = u.id WHERE u.role = 'admin'"
        )
        async with httpx.AsyncClient() as c:
            for r in rows:
                await c.post(
                    f"https://api.telegram.org/bot{bot}/sendMessage",
                    json={"chat_id": r["chat_id"], "text": text},
                    timeout=10,
                )
    except Exception as e:  # noqa: BLE001 — 通知失敗不可阻斷 breaker
        logger.warning("breaker admin notify failed: %s", e)
