import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import StateGraph, END

from llm import Message, Role, ModelRouter, ToolCall
from .tools import TOOL_SPECS, execute_tool, tool_needs_confirmation

logger = logging.getLogger("brain.agent")

# Process-global: marks only the first request handled by this worker process.
_is_first_run = True

# tool-call 迴圈一回合內最多幾次工具來回，防無限迴圈 / 失控
MAX_TOOL_ITERATIONS = 5
# 工具決策固定 temp=0（spike 驗證最穩定、可重現）
TOOL_TEMPERATURE = 0.0

# 給模型的工具使用守則：能跑就呼叫工具拿真實結果，絕不自己編造輸出/連結。
_TOOL_MITIGATION = (
    "\n\n## 工具使用（重要）\n"
    "你有一組工具可呼叫。當使用者的需求涉及「在系統執行/查看命令」「即時或最新資訊"
    "（新聞/天氣/股價/時事）」「喚醒或管理伺服器」等實際動作時，**務必呼叫對應工具取得真實結果**，"
    "**絕對不要自己編造命令輸出、搜尋結果或任何連結**。一般閒聊、意見、既有知識問答則正常直接回答、不呼叫工具。\n"
    "拿到工具結果後，用 Cindy 的語氣**精簡**總結；終端機原始輸出不要整段貼進聊天（使用者可另開檢視頁看完整內容）。"
)


class PlannerTimer:
    """Helper to measure planner latency spans."""
    def __init__(self, request_id: str):
        self.request_id = request_id
        self.start_time = time.perf_counter()
        self.last_mark = self.start_time
        self.spans = {
            "plan_graph_entry_ms": 0.0,
            "plan_routing_ms": 0.0,
        }
        self.is_cold_start = False
        self.executor_chosen = "unknown"
        self.is_complete = False

    def start_span(self):
        self.last_mark = time.perf_counter()

    def end_span(self, span_name: str):
        now = time.perf_counter()
        self.spans[span_name] = self.spans.get(span_name, 0.0) + (now - self.last_mark) * 1000
        self.last_mark = now

    def emit(self):
        total_ms = (time.perf_counter() - self.start_time) * 1000
        logger.info(json.dumps({
            "event": "planner_timing",
            "request_id": self.request_id,
            "is_cold_start": self.is_cold_start,
            "executor_chosen": self.executor_chosen,
            "total_ms": total_ms,
            "is_complete": self.is_complete,
            **self.spans,
        }))


class AgentState(TypedDict):
    """LangGraph 狀態結構。"""
    user_id: str
    source_message_id: Optional[str]
    platform: str
    messages: List[Message]
    system_prompt: str
    plan: Optional[Dict[str, Any]]
    confirmation_received: bool
    skill_result: Optional[Dict[str, Any]]
    final_reply: Optional[str]
    model_router: ModelRouter

    selected_provider: Optional[str]
    routing_reason: Optional[str]
    attachment: Optional[Dict[str, Any]]
    last_usage: Optional[Dict[str, Any]]

    # --- tool-call 迴圈 ---
    tool_iterations: int
    # terminal 工具執行後待附在最終回覆的 viewer 連結
    pending_viewer_link: Optional[str]
    # 寫入型工具確認往返：恢復執行旗標 + 待持久化的 pending（給 main.py 存 confirm:pending）
    resume_tools: bool
    pending_tools: Optional[Dict[str, Any]]


# --- 訊息序列化（確認往返時存進 home_context，跨回合恢復用）---

def serialize_messages(messages: List[Message]) -> list:
    out = []
    for m in messages:
        d = {"role": m.role.value, "content": m.content}
        if m.tool_calls:
            d["tool_calls"] = [{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in m.tool_calls]
        if m.tool_call_id:
            d["tool_call_id"] = m.tool_call_id
        if m.name:
            d["name"] = m.name
        out.append(d)
    return out


def deserialize_messages(data: list) -> List[Message]:
    out = []
    for d in data or []:
        tcs = [ToolCall(id=t["id"], name=t["name"], arguments=t.get("arguments", {}))
               for t in d.get("tool_calls", [])] or None
        out.append(Message(
            role=Role(d["role"]), content=d.get("content", ""),
            tool_calls=tcs, tool_call_id=d.get("tool_call_id"), name=d.get("name"),
        ))
    return out


# --- viewer 連結清理（沿用：移除模型仿造的連結/程式碼圍欄）---

_VIEWER_LINK_RE = re.compile(r"\[[^\]]*\]\((?:https?://)?[^)]*?/terminal/view/[^)]*\)")
_VIEWER_URL_RE = re.compile(r"(?:https?://)?\S*/terminal/view/\S+")
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def _sanitize_terminal_reply(text) -> str:
    """清掉模型可能仿造的 viewer 連結與貼出的程式碼圍欄區塊。"""
    if not text:
        return ""
    text = _VIEWER_LINK_RE.sub("", text)
    text = _VIEWER_URL_RE.sub("", text)
    text = _CODE_FENCE_RE.sub("", text)
    text = re.sub(r"```.*$", "", text, flags=re.DOTALL)  # 未閉合尾段 fence
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# --- 工具結果 → 餵回模型的文字 ---

def _tool_result_to_text(name: str, result: dict) -> str:
    """把工具結果轉成回填給模型的文字（精簡、有界）。"""
    if not isinstance(result, dict):
        return str(result)
    if not (result.get("success", True) and result.get("status") != "error"):
        return f"[工具失敗] {result.get('error', '未知錯誤')}"
    data = result.get("data", result)
    if name == "web_search":
        web = (data or {}).get("web", []) if isinstance(data, dict) else []
        if not web:
            return "（沒有任何搜尋結果）"
        return "\n".join(
            f"{r.get('position', i+1)}. {r.get('title','')}\n   來源：{r.get('url','')}\n   {r.get('description','')}"
            for i, r in enumerate(web)
        )
    if name == "terminal":
        d = data if isinstance(data, dict) else {}
        if d.get("task_id") and d.get("status") in ("pending", "running"):
            return f"已在背景啟動（task_id={d.get('task_id')}），稍後可查看進度。"
        out = d.get("output", "")
        ec = d.get("exit_code")
        return f"exit_code={ec}\n{out}" if out else f"exit_code={ec}（無輸出）"
    return json.dumps(result, ensure_ascii=False)[:2000]


def _describe_tool(name: str, args: dict) -> str:
    if name == "terminal":
        return f"在系統執行 `{(args or {}).get('command','')}`"
    if name == "wake_on_lan":
        return f"喚醒 {(args or {}).get('mac','')}"
    if name == "cockpit":
        return f"cockpit {(args or {}).get('action','')} {(args or {}).get('service','')}".strip()
    return f"{name} {args}"


# --- Nodes ---

async def planner_node(state: AgentState):
    """入口：附件走 file_analyze；否則決定 provider，進入 tool-call 迴圈。

    （已移除舊的 prompt-JSON 規劃與 self-upgrade 舉旗。）
    """
    global _is_first_run
    logger.info("Entering planner_node")
    timer = PlannerTimer(state.get("source_message_id") or "unknown")
    timer.is_cold_start = _is_first_run
    _is_first_run = False

    try:
        # 確認往返恢復：直接進工具節點執行已批准的 tool_calls
        if state.get("resume_tools"):
            timer.end_span("plan_graph_entry_ms")
            timer.is_complete = True
            return {}

        # 附件 → file_analyze（維持既有 Phase 4B 機制）
        if state.get("attachment"):
            timer.end_span("plan_graph_entry_ms")
            timer.executor_chosen = "attachment_routing"
            timer.is_complete = True
            selected_provider = None
            routing_reason = "attachment_routing"
            media_type = state["attachment"].get("media_type") or "file"
            if media_type in ("sticker", "tgs_sticker", "animation"):
                normalized = "sticker" if media_type == "tgs_sticker" else media_type
                decision = state["model_router"].select_provider({"message_type": normalized})
                selected_provider = decision["provider"]
                routing_reason = f"attachment_routing+{decision['reason']}"
                timer.executor_chosen = selected_provider
            return {
                "plan": {"skill": "file_analyze", "is_write": False,
                         "summary": f"分析檔案：{state['attachment']['file_name']}"},
                "selected_provider": selected_provider,
                "routing_reason": routing_reason,
            }

        timer.end_span("plan_graph_entry_ms")
        router = state["model_router"]
        messages = state["messages"]
        last_msg_text = messages[-1].content if messages else ""
        selected_provider = None
        routing_reason = ""

        timer.start_span()
        # 手動 provider 覆蓋：/provider claude 你好
        if isinstance(last_msg_text, str) and last_msg_text.startswith("/provider "):
            parts = last_msg_text.split(" ", 2)
            if len(parts) >= 2 and parts[1].lower() in router._clients:
                selected_provider = parts[1].lower()
                routing_reason = f"override:{selected_provider}"
                messages[-1].content = parts[2] if len(parts) > 2 else ""

        if not selected_provider:
            decision = router.select_provider({
                "text": last_msg_text if isinstance(last_msg_text, str) else "",
                "message_type": "text",
            })
            selected_provider = decision["provider"]
            routing_reason = decision["reason"]
        timer.end_span("plan_routing_ms")
        timer.executor_chosen = selected_provider
        timer.is_complete = True

        return {
            "selected_provider": selected_provider,
            "routing_reason": routing_reason,
            "messages": messages,
            "tool_iterations": 0,
        }
    finally:
        timer.emit()


async def agent_node(state: AgentState):
    """tool-call 迴圈的 LLM 回合：帶 tools 呼叫，附加 assistant 回應。

    回應若含 tool_calls 且未達上限 → 交給 tools_node；否則產出最終回覆
    （清理仿造連結/輸出，並補上 terminal viewer 連結）。
    """
    logger.info("Entering agent_node")
    router = state["model_router"]
    system = state["system_prompt"] + _TOOL_MITIGATION

    response = await router.chat(
        state["messages"],
        system_prompt=system,
        provider=state.get("selected_provider"),
        tools=TOOL_SPECS,
        tool_choice="auto",
        temperature=TOOL_TEMPERATURE,
        caller="agent_node",
    )

    selected_provider = state.get("selected_provider")
    if response.provider and response.provider != selected_provider:
        logger.info(f"Provider fallback: {selected_provider} -> {response.provider}")
        selected_provider = response.provider

    messages = list(state["messages"])
    messages.append(Message(
        role=Role.ASSISTANT,
        content=response.content or "",
        tool_calls=list(response.tool_calls) if response.tool_calls else None,
    ))

    out: dict = {"messages": messages, "selected_provider": selected_provider,
                 "last_usage": response.usage}

    iterations = state.get("tool_iterations", 0)
    if response.tool_calls and iterations < MAX_TOOL_ITERATIONS:
        logger.info(f"agent_node: {len(response.tool_calls)} tool_call(s), iter={iterations}")
        return out  # route_after_agent → tools

    # 最終回覆
    reply = _sanitize_terminal_reply(response.content)
    if not reply:
        reply = ("這次有點處理不過來，剛剛沒能順利完成，可以再說一次嗎？"
                 if response.tool_calls else "嗯……我想想怎麼回你比較好。")
    link = state.get("pending_viewer_link")
    if link:
        reply = f"{reply}\n\n[📄 查看完整終端機輸出]({link})"
    out["final_reply"] = reply
    return out


async def tools_node(state: AgentState):
    """執行最後一則 assistant 訊息要求的 tool_calls：安全把關 → 確認 → 執行 → 回填。"""
    logger.info("Entering tools_node")
    messages = list(state["messages"])
    last = messages[-1] if messages else None
    tool_calls = (getattr(last, "tool_calls", None) or []) if last else []
    pool = getattr(state["model_router"], "_db_pool", None)
    confirmed = state.get("confirmation_received", False)
    pending_link = state.get("pending_viewer_link")
    out: dict = {"tool_iterations": state.get("tool_iterations", 0) + 1}

    for tc in tool_calls:
        name, args = tc.name, (tc.arguments or {})

        # --- 安全把關：terminal admin 閘門 + 危險命令封鎖 ---
        if name == "terminal":
            from skills.terminal import is_dangerous
            command = str(args.get("command") or "")
            is_admin = False
            if pool:
                try:
                    row = await pool.fetchrow("SELECT role FROM users WHERE id = $1", state.get("user_id"))
                    is_admin = bool(row and row["role"] == "admin")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"terminal admin check failed: {e}")
            if not is_admin:
                out["messages"] = messages
                out["final_reply"] = "這個我只聽 Iceman 的，沒辦法幫你在系統上執行命令喔。"
                return out
            danger = is_dangerous(command)
            if danger:
                out["messages"] = messages
                out["final_reply"] = f"這個命令太危險了（{danger}），我不能幫你跑。"
                return out

        # --- 寫入型工具：執行前確認往返 ---
        if tool_needs_confirmation(name, args) and not confirmed:
            out["messages"] = messages
            out["final_reply"] = f"好的，我準備幫你「{_describe_tool(name, args)}」。這會變更系統狀態，請問這樣可以嗎？"
            out["pending_tools"] = {
                "messages": serialize_messages(messages),
                "tool_iterations": state.get("tool_iterations", 0),
            }
            return out

        # --- 執行 ---
        result = await execute_tool(name, args, state["model_router"])

        if name == "terminal":
            await _record_terminal_pointer(state, args, str(args.get("command") or ""), result)
            data = result.get("data") or {}
            task_id = data.get("task_id")
            if task_id:
                import terminal_logs
                link = terminal_logs.build_view_url(task_id)
                if link:
                    pending_link = link

        messages.append(Message(
            role=Role.TOOL, content=_tool_result_to_text(name, result),
            tool_call_id=tc.id, name=name,
        ))

    out["messages"] = messages
    if pending_link:
        out["pending_viewer_link"] = pending_link
    return out


async def _record_terminal_pointer(state, params, command, result):
    """在 home_context 寫/更新 `terminal_log:<task_id>` 指標（寫入失敗不影響執行）。"""
    data = result.get("data") or {}
    task_id = data.get("task_id") or (params or {}).get("task_id")
    if not task_id:
        return
    pool = getattr(state["model_router"], "_db_pool", None)
    if not pool:
        return
    is_poll = bool((params or {}).get("task_id"))
    try:
        if is_poll:
            await pool.execute(
                "UPDATE home_context SET value = value || $2::jsonb, updated_at = NOW() WHERE key = $1",
                f"terminal_log:{task_id}", json.dumps({"status": data.get("status") or "running"}),
            )
        else:
            status = "running" if (params or {}).get("background") else ("done" if result.get("success") else "error")
            await pool.execute(
                "INSERT INTO home_context (key, value) VALUES ($1, $2) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
                f"terminal_log:{task_id}",
                json.dumps({"task_id": task_id, "command": command, "status": status, "created_at": time.time()}),
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"record terminal pointer failed: {e}")


async def executor_node(state: AgentState):
    """EXECUTE 節點：僅服務附件 file_analyze 路徑（其餘技能走 tool-call 迴圈）。"""
    logger.info("Entering executor_node")
    plan = state.get("plan")
    if plan and plan.get("skill") == "file_analyze":
        from skills.file_analyzer import FileAnalyzer
        analyzer = FileAnalyzer(state["model_router"], db_pool=getattr(state["model_router"], "_db_pool", None))
        attachment = state["attachment"]
        result = await analyzer.analyze(
            attachment["local_path"], attachment["mime_type"],
            instruction=state["messages"][-1].content if state["messages"] else None,
            media_type=attachment.get("media_type"), user_id=state.get("user_id"),
            platform=state.get("platform"), source_message_id=state.get("source_message_id"),
            duration_ms=attachment.get("duration_ms"),
        )
        return {"skill_result": {"status": "ok", "analysis": result}}
    return {"skill_result": {"status": "error", "error": "executor 只處理 file_analyze"}}


async def reporter_node(state: AgentState):
    """REPORT 節點：僅服務附件 file_analyze 的感知回覆組稿。"""
    logger.info("Entering reporter_node")
    router = state["model_router"]
    result = state["skill_result"]
    analysis = result.get("analysis", "分析失敗")

    messages = list(state["messages"])
    if messages:
        last = messages[-1]
        messages[-1] = Message(role=last.role, content=f"{last.content}\n\n[感知：{analysis}]")
    perception_system = state["system_prompt"] + "\n\n請根據訊息中 [感知] 標記的實際內容回覆，不要依賴對話歷史中的推測。"

    response = await router.chat(
        messages, system_prompt=perception_system,
        provider=state.get("selected_provider"), caller="reporter_node_perception",
    )
    reply = response.content
    if not reply or len(reply.strip()) == 0:
        reply = f"嗯……我看到了這個：{analysis}"
    return {"final_reply": reply, "last_usage": response.usage}


# --- Routing ---

def route_after_planner(state: AgentState):
    if state.get("resume_tools"):
        return "tools"
    plan = state.get("plan")
    if plan and plan.get("skill") == "file_analyze":
        return "executor"
    return "agent"


def route_after_agent(state: AgentState):
    if state.get("final_reply"):
        return END
    last = state["messages"][-1] if state.get("messages") else None
    if last and getattr(last, "tool_calls", None) and state.get("tool_iterations", 0) < MAX_TOOL_ITERATIONS:
        return "tools"
    return END


def route_after_tools(state: AgentState):
    # 安全拒絕 / 確認暫停 → 直接結束；否則回 agent 讓模型看工具結果續跑
    if state.get("final_reply"):
        return END
    return "agent"


# --- Graph Definition ---

def create_agent_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("planner", planner_node)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tools_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("reporter", reporter_node)

    workflow.set_entry_point("planner")
    workflow.add_conditional_edges("planner", route_after_planner)
    workflow.add_conditional_edges("agent", route_after_agent)
    workflow.add_conditional_edges("tools", route_after_tools)
    workflow.add_edge("executor", "reporter")
    workflow.add_edge("reporter", END)

    return workflow.compile()
