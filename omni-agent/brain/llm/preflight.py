"""Model preflight — brain 啟動時驗證每個設定的 model id 仍可用。

背景：Claude provider 曾因 model id 退役而靜默 404 八個月（fallback chain 讓它看起來
一切正常）。本模組在 lifespan 建好 ModelRouter 後，對每個 provider 設定的 model id
做一次中繼資料查詢（零生成 token），結果寫 log；失敗的出 WARNING 並指明
**哪個 id、來自哪個檔案的哪個鍵、什麼錯誤**，讓人不看程式碼就知道改哪裡。

設計約束：
- 不阻擋啟動、不 raise：呼叫端以背景 task 執行，本函式內任何 provider 失敗只記錄。
- local（rapid-mlx）離線是預期情境，措辭降級為 INFO，與雲端退役區分。
- 每個 id 只查一次；同 provider 內多個來源指向同一 id 時合併列出來源。
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .base import CHECK_MODEL_TIMEOUT, ModelIdMismatch

logger = logging.getLogger("brain.llm.preflight")

CONFIG_FILE = "brain/config/routing_config.json"
# client 建構子預設值所在檔案（來源標示用）
_CLIENT_FILES = {
    "claude": "brain/llm/claude_client.py",
    "gemini": "brain/llm/gemini_client.py",
    "local": "brain/llm/local_client.py",
}


@dataclass
class PreflightResult:
    provider: str
    model_id: str
    sources: list[str] = field(default_factory=list)
    ok: bool = False
    # retired_or_unknown | unauthorized | unreachable | id_mismatch | not_supported | other
    error_class: str = ""
    detail: str = ""
    unused: bool = False  # 設定有寫但目前無程式路徑會用到（如 upgrade_model）
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def collect_targets(router, config: dict) -> list[PreflightResult]:
    """列出待檢 (provider, model_id) 與其來源。只含已註冊的 provider。"""
    providers_cfg = config.get("providers", {})
    targets: dict[tuple[str, str], PreflightResult] = {}

    def add(provider: str, model_id: str | None, source: str, unused: bool = False):
        if not model_id:
            return
        key = (provider, model_id)
        r = targets.get(key)
        if r is None:
            r = targets[key] = PreflightResult(provider=provider, model_id=model_id)
        r.sources.append(source)
        # 只要有任一來源是實際會用的，就不標 unused
        r.unused = unused if len(r.sources) == 1 else (r.unused and unused)

    for name, client in router._clients.items():
        cfg = providers_cfg.get(name, {})
        add(name, cfg.get("model"), f"{CONFIG_FILE}:providers.{name}.model")
        add(name, cfg.get("upgrade_model"),
            f"{CONFIG_FILE}:providers.{name}.upgrade_model", unused=True)
        add(name, client.model_name(),
            f"{_CLIENT_FILES.get(name, type(client).__name__)}:__init__ default")

    return list(targets.values())


def _classify(exc: BaseException) -> tuple[str, str]:
    """把 SDK 例外對映到 error_class 與可動手的 detail。"""
    if isinstance(exc, ModelIdMismatch):
        return "id_mismatch", f"server serves {exc.served}"
    if isinstance(exc, NotImplementedError):
        return "not_supported", str(exc)
    if isinstance(exc, asyncio.TimeoutError):
        return "unreachable", f"timeout after {CHECK_MODEL_TIMEOUT:.0f}s"

    # anthropic.APIStatusError → .status_code；google.genai.errors.APIError → .code
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    name = f"{type(exc).__module__}.{type(exc).__name__}"
    msg = str(exc).replace("\n", " ")
    if len(msg) > 200:
        msg = msg[:200] + "…"
    detail = f"{name} status={status} :: {msg}" if status else f"{name} :: {msg}"

    if status == 404:
        return "retired_or_unknown", detail
    if status in (401, 403):
        return "unauthorized", detail
    # Gemini 對無效 key 回 400 INVALID_ARGUMENT「API key not valid」，語意上仍是憑證問題
    if status == 400 and "api key" in msg.lower():
        return "unauthorized", detail
    # 連線類：openai.APIConnectionError / httpx.ConnectError / anthropic.APIConnectionError…
    if "Connection" in type(exc).__name__ or "Connect" in type(exc).__name__:
        return "unreachable", detail
    return "other", detail


async def _check_one(router, r: PreflightResult) -> PreflightResult:
    client = router._clients[r.provider]
    try:
        await client.check_model(r.model_id)
        r.ok = True
    except BaseException as e:  # noqa: BLE001 — 逐項隔離，任何例外都不得外洩
        if isinstance(e, asyncio.CancelledError):
            raise
        r.ok = False
        r.error_class, r.detail = _classify(e)
    r.checked_at = datetime.now(timezone.utc)
    return r


def _log_result(r: PreflightResult) -> None:
    sources = ", ".join(r.sources)
    tag = " (configured, currently unused)" if r.unused else ""
    if r.ok:
        logger.info("model preflight OK: %s/%s%s [%s]", r.provider, r.model_id, tag, sources)
        return
    if r.provider == "local" and r.error_class == "unreachable":
        logger.info(
            "model preflight: local MLX server offline (expected when chrysoberyl is down): "
            "%s/%s [%s] — %s", r.provider, r.model_id, sources, r.detail,
        )
        return
    logger.warning(
        "model preflight FAILED: %s/%s%s class=%s — fix in: %s — %s",
        r.provider, r.model_id, tag, r.error_class, sources, r.detail,
    )


async def run_model_preflight(router, config: dict) -> list[PreflightResult]:
    """對所有已註冊 provider 的設定 id 做可用性檢查，回傳結果清單（永不 raise）。"""
    targets = collect_targets(router, config)
    if not targets:
        logger.info("model preflight: no registered providers, nothing to check")
        return []

    results = await asyncio.gather(
        *(_check_one(router, r) for r in targets), return_exceptions=True
    )
    final: list[PreflightResult] = []
    for r, out in zip(targets, results):
        if isinstance(out, BaseException):  # _check_one 已吞例外，此為最後防線
            r.ok = False
            r.error_class, r.detail = _classify(out)
        final.append(r)

    for r in final:
        _log_result(r)
    n_ok = sum(1 for r in final if r.ok)
    n_fail = len(final) - n_ok
    (logger.warning if n_fail else logger.info)(
        "model preflight: %d ok, %d failed", n_ok, n_fail
    )
    return final
