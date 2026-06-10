"""終端機技能 — 在受限沙箱容器執行 shell 命令。

設計移植自 hermes-agent 的安全「概念」（allowlist、危險命令偵測、輸出截斷、超時），
但程式碼貼合 Cindy 架構：brain 端是瘦客戶端（如同 web_search.py 之於 SearXNG），
真正的執行與隔離在獨立的 sandbox 容器（見 sandbox/exec_server.py）。

統一回傳格式（對齊 web_search.py 契約）：
    成功: {"success": True, "data": {"output", "exit_code", "truncated"}}
    失敗: {"success": False, "error": "<可讀錯誤訊息>"}

錯誤一律包成 dict 回傳而非 raise，上層（executor_node）永遠拿到可序列化結果。

身分（admin 限定）與「先問再做」確認在 graph confirmer_node 把關；本技能做的是
縱深防禦的第二道：危險命令絕不送進沙箱，並區分 allowlist 與否。
"""

import logging
import os
import re
import shlex
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("brain.skills.terminal")

# 輸出截斷上限（與沙箱端對齊；雙重保險）。
MAX_OUTPUT_CHARS = 4000

# 免確認的安全唯讀命令（取命令第一個 token 比對）。
# 只放「查看狀態」類、不改系統的命令；其餘命令一律走確認流程。
ALLOWLIST = {
    "ls", "cat", "head", "tail", "pwd", "whoami", "date", "uname",
    "df", "du", "free", "uptime", "ps", "top", "env", "id", "hostname",
    "echo", "wc", "stat", "which", "uptime",
}

# 危險命令樣式（移植 hermes approval.py 的概念）：命中即直接拒絕，不送沙箱。
DANGEROUS_PATTERNS = [
    (r"\brm\s+(-[a-zA-Z]*\s+)*-?[a-zA-Z]*[rf]", "遞迴/強制刪除"),
    (r"\bmkfs\b", "格式化檔案系統"),
    (r"\bdd\b.*\bof=/dev/", "寫入區塊裝置"),
    (r">\s*/dev/sd", "寫入磁碟裝置"),
    (r"\bchmod\s+(-R\s+)?0?777\b", "全開權限"),
    (r":\(\)\s*\{.*\}\s*;\s*:", "fork bomb"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "關機/重啟"),
    (r"\b(curl|wget)\b.*\|\s*(sh|bash)\b", "下載直接執行"),
    (r"\bsudo\b", "提權"),
]


def _first_token(command: str) -> str:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return command.strip().split(" ", 1)[0]
    return tokens[0] if tokens else ""


def is_dangerous(command: str) -> Optional[str]:
    """命中危險樣式回傳原因字串，否則回 None。"""
    for pattern, reason in DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            return reason
    return None


def is_allowlisted(command: str) -> bool:
    """命令的第一個 token 在 allowlist 內，且不含 shell 串接（避免 `ls; rm`）。"""
    if re.search(r"[;&|`$><]|\$\(", command):
        return False
    return _first_token(command) in ALLOWLIST


class TerminalSkill:
    """沙箱命令執行的瘦客戶端。"""

    def _base_url(self) -> str:
        return (os.getenv("SANDBOX_URL") or "").strip().rstrip("/")

    def is_available(self) -> bool:
        return bool(self._base_url())

    async def execute(
        self,
        command: str,
        timeout: int = 30,
        background: bool = False,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        command = (command or "").strip()
        if not command:
            return {"success": False, "error": "缺少命令 command"}

        # 縱深防禦：危險命令絕不送沙箱（confirmer 已擋一次，這裡再擋一次）
        danger = is_dangerous(command)
        if danger:
            logger.warning(f"Blocked dangerous command ({danger}): {command!r}")
            return {"success": False, "error": f"命令被安全規則阻擋（{danger}），未執行"}

        base_url = self._base_url()
        if not base_url:
            return {"success": False, "error": "SANDBOX_URL 未設定，終端機功能未啟用"}

        # 查詢背景任務狀態
        if task_id:
            return await self._get(f"{base_url}/exec/status/{task_id}")

        if background:
            return await self._post(
                f"{base_url}/exec/background", {"command": command}, timeout=15.0
            )

        safe_timeout = max(1, min(int(timeout), 120))
        return await self._post(
            f"{base_url}/exec",
            {"command": command, "timeout": safe_timeout},
            timeout=safe_timeout + 10.0,
        )

    async def _post(self, url: str, json_body: dict, timeout: float) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=json_body, timeout=timeout)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(f"Sandbox HTTP error: {exc}")
            return {"success": False, "error": f"沙箱回應 HTTP {exc.response.status_code}"}
        except httpx.RequestError as exc:
            logger.warning(f"Sandbox request error: {exc}")
            return {"success": False, "error": f"無法連線沙箱：{exc}"}
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Sandbox response error: {exc}")
            return {"success": False, "error": f"沙箱回應異常：{exc}"}

    async def _get(self, url: str) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=15.0)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            return {"success": False, "error": f"沙箱回應 HTTP {exc.response.status_code}"}
        except httpx.RequestError as exc:
            return {"success": False, "error": f"無法連線沙箱：{exc}"}


def get_terminal_skill() -> TerminalSkill:
    return TerminalSkill()
