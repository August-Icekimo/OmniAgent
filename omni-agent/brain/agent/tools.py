"""工具註冊表：skill → ToolSpec（provider-native function calling）+ 執行分派。

ToolSpec 描述提供給模型（見 llm/base.py）；執行分派沿用既有 skill 實作
（terminal→sandbox、web_search→SearXNG、其餘→SKILLS_URL）。安全把關（terminal
admin 閘門、危險命令封鎖）在 graph 的工具迴圈執行前進行，不在此。
"""

import logging
import os

import httpx

from llm import ToolSpec

logger = logging.getLogger("brain.agent.tools")


# 提供給模型的工具清單（描述沿用 tools_prompt 的語意，附 JSON schema）
TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="terminal",
        description=(
            "在 HomeLab 受限沙箱執行 shell 命令（查看系統狀態、磁碟、程序、檔案等）。"
            "僅管理者本人可用；使用者明確要求「執行/跑/查看系統」某個命令時才用，閒聊不要用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要執行的 shell 命令"},
                "timeout": {"type": "integer", "description": "逾時秒數，預設 30"},
                "background": {"type": "boolean", "description": "長命令是否背景執行，預設 false"},
            },
            "required": ["command"],
        },
    ),
    ToolSpec(
        name="web_search",
        description=(
            "搜尋網路上的即時資訊（新聞、天氣、店家、時事，或你不確定的最新知識）。"
            "涉及「現在/今天/最新/最近」或訓練資料之後的事實優先用；一般閒聊或意見交流不用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜尋關鍵字"},
                "limit": {"type": "integer", "description": "結果數，預設 5"},
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="wake_on_lan",
        description="喚醒指定的伺服器（送 Wake-on-LAN magic packet）。",
        parameters={
            "type": "object",
            "properties": {
                "mac": {"type": "string", "description": "目標機器 MAC 位址，格式 AA:BB:CC:DD:EE:FF"},
            },
            "required": ["mac"],
        },
    ),
    ToolSpec(
        name="cockpit",
        description="HomeLab 伺服器管理：查詢狀態或重啟服務。",
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status", "restart_service"]},
                "service": {"type": "string", "description": "服務名稱（restart_service 時必填）"},
            },
            "required": ["action"],
        },
    ),
]

# 名稱 → ToolSpec，方便查詢
TOOL_SPECS_BY_NAME = {t.name: t for t in TOOL_SPECS}


def tool_needs_confirmation(name: str, args: dict) -> bool:
    """此 tool_call 是否屬「寫入/有副作用」需先確認。

    terminal 依 allowlist 判定（唯讀命令免確認）；admin 閘門與危險命令封鎖另在
    graph 迴圈把關。未知工具一律視為寫入（保守）。
    """
    if name == "web_search":
        return False
    if name == "cockpit":
        return (args or {}).get("action") == "restart_service"
    if name == "terminal":
        from skills.terminal import is_allowlisted
        return not is_allowlisted(str((args or {}).get("command", "")))
    return True  # wake_on_lan 及未知工具：保守視為寫入


async def execute_tool(name: str, args: dict, model_router) -> dict:
    """執行單一工具，回傳統一 dict 結果（沿用既有 skill 實作）。"""
    args = args or {}

    if name == "terminal":
        from skills.terminal import get_terminal_skill
        skill = get_terminal_skill()
        command = str(args.get("command") or "").strip()
        if not command and not args.get("task_id"):
            return {"success": False, "error": "缺少命令 command"}
        return await skill.execute(
            command,
            timeout=args.get("timeout", 30),
            background=bool(args.get("background", False)),
            task_id=args.get("task_id"),
        )

    if name == "web_search":
        from skills.web_search import get_web_search_provider
        provider = get_web_search_provider()
        query = str(args.get("query") or "").strip()
        if not query:
            return {"success": False, "error": "缺少搜尋關鍵字 query"}
        return await provider.search(query, limit=args.get("limit", 5))

    # 其餘技能（wake_on_lan / cockpit …）走 Go Skills Server
    skills_url = os.getenv("SKILLS_URL")
    if not skills_url:
        return {"status": "error", "error": "SKILLS_URL not configured"}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{skills_url}/skill/execute",
                json={"skill": name, "params": args},
                timeout=10.0,
            )
            return resp.json()
    except Exception as e:  # noqa: BLE001
        logger.error(f"Skill execution failed ({name}): {e}")
        return {"status": "error", "error": str(e)}
