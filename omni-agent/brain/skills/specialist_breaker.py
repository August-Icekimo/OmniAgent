"""AGY specialist 的 429 circuit breaker（提案 D3，完整實作）。

狀態落 `home_context`（key=`agy:circuit_breaker`），crash-safe，**不需新 schema**
（沿用 router 既有的 quota-cooldown kv 模式）。

語意：
- API Key 層遇 429（Free Tier 額度耗盡）→ breaker **open** `AGY_BREAKER_OPEN_SECONDS`
  （預設 5hr）→ open 期間新委派直接降級、不送 AGY → 屆時 **half-open** 以 DB CAS
  搶「唯一試打權」（併發下僅一人放行），成功則 **close**、再失敗（仍 429）則重新 trip；
  試打未收尾（crash / 非配額失敗）超過 stale 窗後可被重搶。
- open 狀態損毀（open_until 不可判讀）時 fail-open 走 half-open，不永久鎖死委派。
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
# half-open 試打權的失效窗：搶到權的試打若既沒 close 也沒重新 trip（例如行程 crash、
# 非配額類失敗），超過此秒數後允許他人重搶，避免卡死。須 > 委派逾時（預設 60s）。
_HALF_OPEN_STALE_SECONDS = int(os.getenv("AGY_BREAKER_HALF_OPEN_STALE_SECONDS", "180"))

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

    allowed=False → breaker 仍 open（或 half-open 試打權已被別人搶走），
    呼叫端應直接降級、不送 AGY。
    half_open=True → 本次呼叫以 CAS 搶到唯一試打權（成功要 close、429 要重新 trip；
    其他失敗留在 half_open，過 stale 窗後可被重搶）。
    無 pool 或無狀態 → (True, False)（視為 closed）。
    """
    if not pool:
        return True, False
    row = await pool.fetchrow("SELECT value FROM home_context WHERE key=$1", _KEY)
    if not row:
        return True, False
    val = _as_dict(row["value"])
    state = val.get("state")
    if state == "open":
        try:
            ou = datetime.fromisoformat(val["open_until"]) if val.get("open_until") else None
        except (ValueError, TypeError):
            ou = None
        if ou is None:
            # 狀態損毀（open 卻無可判讀的到期時間）：fail-open 走 half-open 試打，
            # 不讓 breaker 永久鎖死委派。
            logger.warning("breaker 狀態異常（open 但 open_until 不可判讀），視為到期")
        elif _now() < ou:
            return False, False  # 仍 open
        # 已到期（或狀態損毀）→ CAS 搶 half-open 試打權：併發下僅一人放行
        claimed = await _claim_half_open(pool, from_state="open")
        return claimed, claimed
    if state == "half_open":
        # 有人已在試打。若其超過 stale 窗仍未收尾（crash / 非配額失敗），允許重搶。
        claimed = await _claim_half_open(pool, from_state="half_open", stale_only=True)
        return claimed, claimed
    return True, False


async def _claim_half_open(pool, from_state: str, stale_only: bool = False) -> bool:
    """以單條 UPDATE 做 compare-and-set，原子地把試打權標到自己名下。

    回 True 表示本次呼叫搶到權（WHERE 命中恰一列）；併發時輸家拿 0 列回 False。
    """
    stale_cond = (
        "AND ((value->>'claimed_at') IS NULL "
        "OR (value->>'claimed_at')::timestamptz < now() - make_interval(secs => $3))"
        if stale_only else ""
    )
    sql = f"""
        UPDATE home_context
        SET value = value || jsonb_build_object('state', 'half_open', 'claimed_at', $2::text),
            updated_at = now()
        WHERE key = $1 AND value->>'state' = '{from_state}' {stale_cond}
        """
    args = [_KEY, _now().isoformat()]
    if stale_only:
        args.append(float(_HALF_OPEN_STALE_SECONDS))
    try:
        tag = await pool.execute(sql, *args)
    except Exception as e:  # noqa: BLE001 — claimed_at 損毀等罕見錯不阻斷（視為沒搶到）
        logger.warning("breaker half-open CAS 失敗: %s", e)
        return False
    return tag == "UPDATE 1"


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
