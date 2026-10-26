#!/usr/bin/env python3
"""Sign in with ChatGPT（OSS / self-hosted 流程）登入工具 — 讓 brain 以 admin 的 ChatGPT Plus 額度呼叫模型。

依 developers.openai.com/siwc/token-sharing-open-source（2026-10-26 讀取）：PKCE S256 + 動態註冊
（client_id=dynamic_agent_client → callback 回傳 issued oaiapp_...）。Debian 主機沒有瀏覽器，
127.0.0.1 callback 回不到主機，所以分兩段：

    python3 scripts/siwc_login.py start                  # 印出授權 URL，任一瀏覽器開啟並同意
    python3 scripts/siwc_login.py finish '<callback URL>' # 把瀏覽器網址列（連不上的那頁）整串貼回
    python3 scripts/siwc_login.py refresh                # 手動 refresh 一次（驗證輪替）
    python3 scripts/siwc_login.py status                 # 顯示帳號、scope、到期時間（不印 token）

憑證寫在 $SIWC_DIR（預設 ~/.config/omni-agent/siwc/），0600、原子寫入，絕不進 git、不印到終端。
只用標準庫，主機不需額外套件。
"""
import base64
import hashlib
import json
import os
import secrets
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

AUTHORIZE_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
REDIRECT_URI = "http://127.0.0.1:1455/auth/callback"
AGENT_NAME = "OmniAgent"
PLAN_SCOPE = "chatgpt.tokens.use.direct"

SIWC_DIR = os.path.expanduser(os.environ.get("SIWC_DIR", "~/.config/omni-agent/siwc"))
HOST_FILE = os.path.join(SIWC_DIR, "host_id")
PENDING_FILE = os.path.join(SIWC_DIR, "pending.json")
CRED_FILE = os.path.join(SIWC_DIR, "credentials.json")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _write_private(path: str, data: dict) -> None:
    """原子寫入 + 0600：先寫同目錄暫存檔再 rename，避免 refresh 中斷留下半截憑證。"""
    os.makedirs(SIWC_DIR, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=SIWC_DIR, prefix=".tmp-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def _read(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _host_id() -> str:
    """每台 host 一個、持久化的 ext_agent_host_id（urn:uuid 格式，官方支援）。"""
    if os.path.exists(HOST_FILE):
        return open(HOST_FILE).read().strip()
    os.makedirs(SIWC_DIR, mode=0o700, exist_ok=True)
    host_id = f"urn:uuid:{uuid.uuid4()}"
    with open(HOST_FILE, "w") as f:
        f.write(host_id + "\n")
    os.chmod(HOST_FILE, 0o600)
    return host_id


def _jwt_claims(token: str) -> dict:
    # 只解 payload 取 email/sub/nonce；簽章驗證留給 brain 端（spike 階段）
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def _post_form(url: str, form: dict) -> dict:
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(form).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        sys.exit(f"token endpoint HTTP {e.code}: {body[:500]}")


def _save_tokens(tok: dict, client_id: str, host_id: str, id_token: str | None = None) -> dict:
    id_token = tok.get("id_token") or id_token
    claims = _jwt_claims(id_token) if id_token else {}
    scopes = sorted((tok.get("scope") or "").split())
    cred = {
        "email": claims.get("email"),
        "issuer": claims.get("iss"),
        "subject": claims.get("sub"),
        "client_id": client_id,
        "ext_agent_host_id": host_id,
        "id_token": id_token,
        "access_token": tok["access_token"],
        "refresh_token": tok["refresh_token"],
        "token_type": tok.get("token_type", "Bearer"),
        "expires_in": tok.get("expires_in", 3600),
        "scopes": scopes,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_private(CRED_FILE, cred)
    return cred


def cmd_start() -> None:
    host_id = _host_id()
    prior = _read(CRED_FILE) if os.path.exists(CRED_FILE) else None
    verifier = _b64url(secrets.token_bytes(32))
    pending = {
        "state": secrets.token_urlsafe(24),
        "nonce": secrets.token_urlsafe(24),
        "verifier": verifier,
        "client_id": prior["client_id"] if prior else "dynamic_agent_client",
        "created": time.time(),
    }
    params = {
        "client_id": pending["client_id"],
        "ext_agent_host_id": host_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": pending["state"],
        "nonce": pending["nonce"],
        "code_challenge_method": "S256",
        "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()),
    }
    if prior:
        # 重新授權：沿用 issued client_id，不帶 agent_name_hint
        if prior.get("email"):
            params["login_hint"] = prior["email"]
    else:
        params["agent_name_hint"] = AGENT_NAME
    _write_private(PENDING_FILE, pending)
    print("在任一瀏覽器開啟以下網址並同意授權：\n")
    print(f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}\n")
    print("最後頁面會導向 127.0.0.1（連不上是正常的），把網址列整串複製，執行：")
    print("  python3 scripts/siwc_login.py finish '<貼上 callback URL>'")


def cmd_finish(callback_url: str) -> None:
    if not os.path.exists(PENDING_FILE):
        sys.exit("沒有進行中的授權，先執行 start")
    pending = _read(PENDING_FILE)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(callback_url).query)
    get = lambda k: (q.get(k) or [None])[0]
    if get("state") != pending["state"]:
        sys.exit("state 不符，拒絕（請重新 start）")
    if get("error"):
        os.unlink(PENDING_FILE)
        sys.exit(f"授權未完成：{get('error')} {get('error_description') or ''}")
    client_id = get("client_id") or pending["client_id"]
    if client_id == "dynamic_agent_client":
        sys.exit("新註冊的 callback 沒有回傳 issued client_id，註冊未完成")
    if pending["client_id"] != "dynamic_agent_client" and client_id != pending["client_id"]:
        sys.exit("callback 回傳的 client_id 與既有註冊不同，拒絕覆蓋")
    tok = _post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": get("code"),
        "code_verifier": pending["verifier"],
        "redirect_uri": REDIRECT_URI,
        "resource": RESOURCE,
    })
    if tok.get("id_token") and _jwt_claims(tok["id_token"]).get("nonce") != pending["nonce"]:
        sys.exit("id_token nonce 不符，拒絕")
    cred = _save_tokens(tok, client_id, _host_id())
    os.unlink(PENDING_FILE)
    _print_status(cred)


def cmd_refresh() -> None:
    cred = _read(CRED_FILE)
    tok = _post_form(TOKEN_URL, {
        "grant_type": "refresh_token",
        "client_id": cred["client_id"],
        "refresh_token": cred["refresh_token"],
        "resource": RESOURCE,
    })
    rotated = tok.get("refresh_token") != cred["refresh_token"]
    if "scope" not in tok:
        tok["scope"] = " ".join(cred["scopes"])
    new = _save_tokens(tok, cred["client_id"], cred["ext_agent_host_id"], cred.get("id_token"))
    print(f"refresh OK（refresh token {'已輪替' if rotated else '未輪替'}）")
    _print_status(new)


def _print_status(cred: dict) -> None:
    saved = datetime.fromisoformat(cred["saved_at"])
    expires = saved.timestamp() + int(cred.get("expires_in", 3600))
    print(f"帳號：{cred.get('email')}  client_id：{cred['client_id']}")
    print(f"scopes：{' '.join(cred['scopes'])}")
    print(f"ChatGPT 方案額度：{'✅ 已授權' if PLAN_SCOPE in cred['scopes'] else '❌ 未授權（不可推論）'}")
    print(f"access token 到期：{datetime.fromtimestamp(expires).isoformat(timespec='seconds')}")
    print(f"憑證檔：{CRED_FILE}")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "start":
        cmd_start()
    elif cmd == "finish" and len(sys.argv) == 3:
        cmd_finish(sys.argv[2])
    elif cmd == "refresh":
        cmd_refresh()
    elif cmd == "status":
        _print_status(_read(CRED_FILE))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
