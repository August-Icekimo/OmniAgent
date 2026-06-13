"""終端機 log viewer 的 brain 端支援模組。

職責：
- 短效 HMAC token 的簽發 / 驗證（綁定 task_id + 過期時間，預設 24h）。
- 存取 sandbox 寫入共享 volume 的 `<task_id>.log` 與 `<task_id>.meta.json`。
- 提供 viewer HTML（內嵌 vendored xterm.js）與 7 天保留期清理。

安全模型：對外存取的「門」由 secure-gateway 的 Caddy（Google OAuth `admin_policy`）
把關；此處的 token 是縱深防禦的第二道——把每條 log 連結綁到特定 task_id 且 24h 後過期，
避免單一連結被無限期重用或跨 task 存取。
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from typing import Optional

logger = logging.getLogger("brain.terminal_logs")

# 共享 volume 在 brain 容器內的掛載路徑（與 compose 的 TERMINAL_LOG_DIR 對齊）
LOG_DIR = os.getenv("TERMINAL_LOG_DIR", "/terminal-logs")

# token 壽命（秒），預設 24 小時，可由環境變數調整
TOKEN_TTL_SECONDS = int(os.getenv("TERMINAL_VIEW_TOKEN_TTL", str(24 * 3600)))

# log 保留天數，預設 7 天
RETENTION_DAYS = int(os.getenv("TERMINAL_LOG_RETENTION_DAYS", "7"))

# task_id 來自 URL，嚴格白名單避免路徑穿越（sandbox 產生的是 12 位 hex）
_VALID_TASK_ID = re.compile(r"^[A-Za-z0-9]{1,64}$")


class TokenError(Exception):
    """金鑰未設定等組態錯誤；端點據此回 5xx，而非默默放行或回 403。"""


def _secret() -> bytes:
    return os.getenv("TERMINAL_VIEW_SECRET", "").strip().encode("utf-8")


def _sign(task_id: str, exp: int) -> str:
    secret = _secret()
    if not secret:
        raise TokenError("TERMINAL_VIEW_SECRET 未設定，終端機檢視功能停用")
    msg = f"{task_id}.{exp}".encode("utf-8")
    sig = hmac.new(secret, msg, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")


def make_view_token(task_id: str, ttl: Optional[int] = None) -> str:
    """簽發綁定 task_id 的短效 token，格式 `<exp>.<sig>`。

    sig = HMAC(secret, "<task_id>.<exp>")，故 token 不可跨 task 重用，
    也不含明文敏感資訊（只有過期時間戳 + HMAC）。
    """
    exp = int(time.time()) + int(ttl if ttl is not None else TOKEN_TTL_SECONDS)
    return f"{exp}.{_sign(task_id, exp)}"


def verify_view_token(task_id: str, token: Optional[str]) -> bool:
    """驗證 token：金鑰未設定 → raise TokenError；過期/竄改/task 不符 → False。"""
    if not _secret():
        raise TokenError("TERMINAL_VIEW_SECRET 未設定，終端機檢視功能停用")
    if not token or "." not in token:
        return False
    exp_str, _, sig = token.partition(".")
    try:
        exp = int(exp_str)
    except ValueError:
        return False
    if exp < int(time.time()):
        return False
    try:
        expected = _sign(task_id, exp)
    except TokenError:
        raise
    return hmac.compare_digest(sig, expected)


# --- log / meta 存取 ---

def is_valid_task_id(task_id: str) -> bool:
    return bool(_VALID_TASK_ID.match(task_id or ""))


def log_path(task_id: str) -> str:
    return os.path.join(LOG_DIR, f"{task_id}.log")


def meta_path(task_id: str) -> str:
    return os.path.join(LOG_DIR, f"{task_id}.meta.json")


def read_meta(task_id: str) -> Optional[dict]:
    try:
        with open(meta_path(task_id), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def task_exists(task_id: str) -> bool:
    """以 meta 檔存在與否判定 task 是否存在（log 檔可能尚未產生即 pending）。"""
    return is_valid_task_id(task_id) and os.path.exists(meta_path(task_id))


def build_view_url(task_id: str) -> Optional[str]:
    """組出帶簽名 token 的 viewer 連結；`CINDY_VIEWER_BASE_URL` 未設定或
    金鑰未設定時回 None，讓上層退化為「僅回摘要、不附壞連結」。"""
    base = os.getenv("CINDY_VIEWER_BASE_URL", "").strip().rstrip("/")
    if not base or not is_valid_task_id(task_id):
        return None
    try:
        token = make_view_token(task_id)
    except TokenError:
        return None
    from urllib.parse import quote
    return f"{base}/terminal/view/{task_id}?t={quote(token)}"


# --- 7 天保留期清理 ---

def prune_expired_files(now: Optional[float] = None) -> list:
    """刪除超過 RETENTION_DAYS 的 `<task_id>.log` / `.meta.json`，回傳被刪的 task_id。

    DB-free：只負責檔案；對應的 `home_context` 指標由 brain 端（有 pool）刪除。
    每檔獨立 try/except，單檔失敗不影響其他檔。
    """
    now = now if now is not None else time.time()
    cutoff = now - RETENTION_DAYS * 86400
    pruned: list = []
    try:
        names = os.listdir(LOG_DIR)
    except OSError:
        return pruned

    for name in names:
        if not name.endswith(".meta.json"):
            continue
        task_id = name[: -len(".meta.json")]
        mp = os.path.join(LOG_DIR, name)

        created = None
        try:
            with open(mp, "r", encoding="utf-8") as f:
                created = json.load(f).get("created_at")
        except (OSError, ValueError):
            created = None
        if not isinstance(created, (int, float)):
            try:
                created = os.path.getmtime(mp)
            except OSError:
                continue
        if created > cutoff:
            continue

        ok = True
        for p in (log_path(task_id), mp):
            try:
                os.remove(p)
            except FileNotFoundError:
                pass
            except OSError as e:
                ok = False
                logger.warning(f"刪除 {p} 失敗：{e}")
        if ok:
            pruned.append(task_id)

    return pruned


# vendored xterm.js 靜態資產目錄（brain/static/terminal，隨 image COPY 進去）
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static", "terminal")


def _esc(text: str) -> str:
    """最小 HTML 屬性/JSON 上下文跳脫，避免 command 內容破壞頁面。"""
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace("</", "<\\/")
        .replace("\"", "\\\"")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def render_viewer_html(task_id: str, token: str, meta: Optional[dict]) -> str:
    """產生內嵌 vendored xterm.js 的唯讀 log 檢視頁。

    頁面只帶 task_id + token，連線 `/terminal/ws/{task_id}` 由 WebSocket
    負責回放既有內容 + 即時串流（見 Task 5）。靜態資產一律走 `/terminal/static/`，
    與 Caddy 對 `/terminal*` 的反向代理路由相符。
    """
    command = _esc((meta or {}).get("command", ""))
    safe_task = _esc(task_id)
    safe_token = _esc(token)
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>終端機輸出 · {safe_task}</title>
<link rel="stylesheet" href="/terminal/static/xterm.css">
<style>
  html,body{{margin:0;height:100%;background:#1e1e1e;color:#ddd;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
  #bar{{padding:8px 12px;background:#2d2d2d;font-size:13px;display:flex;
    gap:12px;align-items:center;flex-wrap:wrap}}
  #cmd{{color:#9cdcfe;font-family:monospace;word-break:break-all}}
  #status{{margin-left:auto;padding:2px 8px;border-radius:4px;background:#444}}
  #status.running{{background:#5a4500}} #status.done{{background:#1f5c2e}}
  #status.error{{background:#6e1f1f}}
  #term{{position:absolute;top:42px;bottom:0;left:0;right:0;padding:6px}}
</style>
</head>
<body>
  <div id="bar">
    <span>📄 終端機輸出</span>
    <span id="cmd">{command}</span>
    <span id="status">connecting…</span>
  </div>
  <div id="term"></div>
  <script src="/terminal/static/xterm.js"></script>
  <script src="/terminal/static/addon-fit.js"></script>
  <script>
    const taskId = "{safe_task}";
    const token = "{safe_token}";
    const term = new Terminal({{convertEol:true, fontSize:13, scrollback:100000,
      theme:{{background:"#1e1e1e"}}}});
    const fit = new FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open(document.getElementById("term"));
    fit.fit();
    window.addEventListener("resize", () => fit.fit());

    const statusEl = document.getElementById("status");
    function setStatus(s){{ statusEl.textContent = s; statusEl.className = s; }}

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = proto + "//" + location.host + "/terminal/ws/" + taskId +
                "?t=" + encodeURIComponent(token);
    let ws;
    function connect(){{
      ws = new WebSocket(url);
      ws.binaryType = "arraybuffer";
      ws.onmessage = (ev) => {{
        if (typeof ev.data === "string") {{
          // 控制訊息：以 JSON 傳遞狀態
          try {{ const m = JSON.parse(ev.data);
                 if (m.status) setStatus(m.status); return; }} catch(e) {{}}
          term.write(ev.data);
        }} else {{
          term.write(new Uint8Array(ev.data));
        }}
      }};
      ws.onopen = () => setStatus("connected");
      ws.onclose = () => {{ if (statusEl.className === "" ||
        statusEl.textContent === "connected") setStatus("closed"); }};
      ws.onerror = () => setStatus("error");
    }}
    connect();
  </script>
</body>
</html>"""
