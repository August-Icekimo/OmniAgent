import json
import logging
import os
import re
import time
from typing import Annotated, Any, Dict, List, Optional, TypedDict

import httpx
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from llm import Message, Role, ModelRouter
from .prompts import build_tools_prompt

logger = logging.getLogger("brain.agent")

# Process-global: marks only the first request handled by this worker process.
# Each Uvicorn worker has its own flag; multi-worker deploys produce one cold-start per worker.
_is_first_run = True


class PlannerTimer:
    """Helper to measure planner latency spans."""
    def __init__(self, request_id: str):
        self.request_id = request_id
        self.start_time = time.perf_counter()
        self.last_mark = self.start_time
        self.spans = {
            "plan_graph_entry_ms": 0.0,
            "plan_routing_ms": 0.0,        # step 1+2: provider selection
            "plan_skills_prompt_ms": 0.0,  # step 3: build skills+upgrade prompt
            "plan_main_llm_ms": 0.0,       # step 3: main planning LLM call (local)
            "plan_skill_parse_ms": 0.0,    # step 3: parse plan/skill response
            "plan_upgrade_llm_ms": 0.0,    # step 3b: upgrade retry (gemini), 0 if not triggered
        }
        self.is_cold_start = False
        self.executor_chosen = "unknown"
        self.is_complete = False

    def start_span(self):
        self.last_mark = time.perf_counter()

    def end_span(self, span_name: str):
        now = time.perf_counter()
        self.spans[span_name] += (now - self.last_mark) * 1000
        self.last_mark = now

    def emit(self):
        total_ms = (time.perf_counter() - self.start_time) * 1000
        log_data = {
            "event": "planner_timing",
            "request_id": self.request_id,
            "is_cold_start": self.is_cold_start,
            "executor_chosen": self.executor_chosen,
            "total_ms": total_ms,
            "is_complete": self.is_complete,
            **self.spans
        }
        # Force JSON string as message to ensure structured logging even if config is simple
        logger.info(json.dumps(log_data))


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

    # --- Phase 4A 動態路由相關 ---
    selected_provider: Optional[str]
    routing_reason: Optional[str]
    upgrade_requested: bool
    attachment: Optional[Dict[str, Any]]

    # 產生 final_reply 的那次 LLM call 的 usage（input/output tokens），
    # 供 main.py 回填 BrainResponse 的 context_tokens（gateway footer 用）。
    last_usage: Optional[Dict[str, Any]]

def _is_upgrade_signal(content: str) -> bool:
    """Return True if local model output contains an upgrade_needed flag."""
    try:
        stripped = content.strip()
        if stripped.startswith("{"):
            data = json.loads(stripped)
            return isinstance(data, dict) and data.get("upgrade_needed") is True
        if "```json" in stripped:
            json_str = stripped.split("```json")[-1].split("```")[0].strip()
            data = json.loads(json_str)
            return isinstance(data, dict) and data.get("upgrade_needed") is True
    except Exception:
        pass
    # Fallback: catch any format variation (embedded in text, no code fence, etc.)
    return '"upgrade_needed": true' in content or '"upgrade_needed":true' in content


# --- Nodes ---

async def planner_node(state: AgentState):
    """PLAN 節點：決定初始路由、評估複雜度並判斷是否需要技能。"""
    global _is_first_run
    logger.info("Entering planner_node")
    
    request_id = state.get("source_message_id") or "unknown"
    timer = PlannerTimer(request_id)
    timer.is_cold_start = _is_first_run
    _is_first_run = False

    try:
        # --- Phase 4B: Attachment Routing ---
        if state.get("attachment"):
            timer.end_span("plan_graph_entry_ms")
            logger.info("Attachment detected, routing to file_analyze")
            timer.executor_chosen = "attachment_routing"
            timer.is_complete = True

            # 貼圖/GIF 試點：回覆組稿（reporter 感知路徑）也依規則路由（local 短快），
            # footer 才能誠實反映實際出力的 provider。其餘附件類型維持 None（gemini 預設）
            selected_provider = None  # 讓 router 決定最好的 (OAuth 優先)
            routing_reason = "attachment_routing"
            media_type = state["attachment"].get("media_type") or "file"
            if media_type in ("sticker", "tgs_sticker", "animation"):
                normalized = "sticker" if media_type == "tgs_sticker" else media_type
                decision = state["model_router"].select_provider({"message_type": normalized})
                selected_provider = decision["provider"]
                routing_reason = f"attachment_routing+{decision['reason']}"
                timer.executor_chosen = selected_provider

            return {
                "plan": {
                    "skill": "file_analyze",
                    "is_write": False,
                    "summary": f"分析檔案：{state['attachment']['file_name']}"
                },
                "selected_provider": selected_provider,
                "routing_reason": routing_reason
            }

        # 如果已經有 plan (例如從 pending confirmation 載入)，跳過重新規劃
        if state.get("plan"):
            timer.end_span("plan_graph_entry_ms")
            timer.is_complete = True
            return {}

        timer.end_span("plan_graph_entry_ms")
        
        router = state["model_router"]

        # 1. 處理手動 Provider 覆蓋 (例如: /provider claude 你好)
        timer.start_span()
        messages = state["messages"]
        last_msg_text = messages[-1].content if messages else ""
        selected_provider = None
        routing_reason = ""

        if last_msg_text.startswith("/provider "):
            parts = last_msg_text.split(" ", 2)
            if len(parts) >= 2:
                target_p = parts[1].lower()
                if target_p in router._clients:
                    selected_provider = target_p
                    routing_reason = f"override:{target_p}"
                    # 剝離前綴
                    clean_text = parts[2] if len(parts) > 2 else ""
                    messages[-1].content = clean_text
                else:
                    logger.warning(f"Unknown provider in override: {target_p}")

        # 2. 自動判斷路由 (如果不受覆蓋)
        thinking_budget = -1
        if not selected_provider:
            routing_decision = router.select_provider({
                "text": last_msg_text,
                "message_type": "text", # 預設，未來可從 state 獲取
                "has_skill_intent": False # 初始假設
            })
            selected_provider = routing_decision["provider"]
            routing_reason = routing_decision["reason"]
            thinking_budget = routing_decision.get("thinking_budget", -1)
        timer.end_span("plan_routing_ms")

        timer.executor_chosen = selected_provider
        upgrade_requested = False

        # 3. 判斷是否需要技能，local model 可自我舉旗升級
        timer.start_span()
        skills_context = build_tools_prompt(os.getenv("SKILLS_URL"))
        upgrade_instruction = (
            "\n\n## 回覆長度（強制規則）\n"
            "每次回覆**最多 3 句話**。不使用標題、列點或長篇分析。簡短、溫暖、直接。\n\n"
            "## 能力邊界（強制規則）\n"
            "你沒有網路存取能力，無法獲得任何即時資訊。\n"
            "遇到以下任何情況，你**必須**只輸出下方 JSON，不得嘗試回答、猜測或編造：\n"
            "- 使用者詢問今日/最新/現在的新聞、頭條、時事\n"
            "- 使用者詢問股市行情、股價、匯率、加密貨幣價格\n"
            "- 使用者詢問即時天氣\n"
            "- 任何需要你「上網查」才能回答的問題\n"
            "- 你不確定答案且捏造內容會造成誤導的情況\n"
            "- 使用者要求長篇輸出（寫文章、報告、故事，或指定數百字以上的篇幅）——"
            "你的輸出長度上限很小，硬寫會被截斷\n\n"
            '{"upgrade_needed": true}\n\n'
            "違反此規則（例如假裝自己在搜尋、編造新聞內容）是嚴重錯誤。"
        )
        full_system = state["system_prompt"] + "\n\n" + skills_context + upgrade_instruction
        timer.end_span("plan_skills_prompt_ms")

        timer.start_span()
        response = await router.chat(
            messages,
            system_prompt=full_system,
            provider=selected_provider,
            thinking_budget=thinking_budget,
            caller="planner_node"
        )
        timer.end_span("plan_main_llm_ms")

        # router 的 fallback 鏈可能換了實際回答者（如 local 超時改由 gemini 代打），
        # 同步回 selected_provider，否則 footer 標籤與後續升級判斷都會錯
        if response.provider and response.provider != selected_provider:
            logger.info(f"Provider fallback detected: {selected_provider} -> {response.provider}")
            selected_provider = response.provider
            routing_reason = f"{routing_reason}+fallback:{response.provider}"
            timer.executor_chosen = selected_provider

        timer.start_span()
        content = response.content
        plan = None
        final_reply = None

        output_tokens = response.usage.get("output_tokens", "?") if response.usage else "?"
        logger.info(f"[planner_debug] local response tokens={output_tokens}, plan_main_llm_ms={timer.spans['plan_main_llm_ms']:.0f}, content (first 300 chars): {content[:300]!r}")

        # 空回應視為升級訊號（local model 被 max_tokens 截斷前未輸出任何文字）
        if not content.strip():
            logger.warning("Local model returned empty content, treating as upgrade signal")
            content = '{"upgrade_needed": true}'

        # 確定性保底：輸出被 max_tokens 硬截（finish_reason=length）直接升級重試，
        # 不依賴模型自覺舉旗——對話歷史的續寫慣性常壓過 prompt 指令
        truncated = (
            selected_provider == "local"
            and getattr(response, "finish_reason", "") == "length"
        )
        if truncated:
            logger.info("Local output hit max_tokens (finish_reason=length), treating as upgrade signal")

        # 偵測舉旗訊號，靜默升級至 gemini
        if truncated or _is_upgrade_signal(content):
            timer.end_span("plan_skill_parse_ms")
            timer.start_span()
            logger.info("Local model signaled upgrade, retrying with gemini")
            # 升級時不傳 upgrade_instruction，避免 gemini 也回傳舉旗訊號
            upgrade_system = state["system_prompt"] + "\n\n" + skills_context
            response = await router.chat(
                messages,
                system_prompt=upgrade_system,
                provider="gemini",
                thinking_budget=-1,
                caller="planner_node_upgrade"
            )
            timer.end_span("plan_upgrade_llm_ms")
            content = response.content
            if getattr(response, "finish_reason", "") == "length":
                # 升級鏈頂層仍被截斷：無路可升，至少留下可見訊號（考慮調高 max_tokens）
                logger.warning("Upgrade provider output also hit max_tokens; reply is truncated")
            logger.info(f"[planner_debug] upgrade response (first 300 chars): {content[:300]!r}")
            # 升級後仍是舉旗 JSON 或空回應（歷史汙染可能讓模型學舌）：
            # 絕不把原始 JSON 出貨給使用者，改誠實回報
            if not content.strip() or _is_upgrade_signal(content):
                logger.error("Upgrade response is still an upgrade flag or empty; using honest fallback")
                content = "嗯……這題我想得有點吃力，剛剛沒能順利完成。可以再問我一次嗎？"
            selected_provider = "gemini"
            routing_reason = "self_upgrade"
            timer.executor_chosen = selected_provider
            timer.start_span()  # 重啟 parse span 計算升級後回應的解析時間

        try:
            if "```json" in content:
                json_str_skill = content.split("```json")[-1].split("```")[0].strip()
                plan_candidate = json.loads(json_str_skill)
                if isinstance(plan_candidate, dict) and "skill" in plan_candidate:
                    logger.info(f"[planner_debug] parsed skill plan: {plan_candidate}")
                    plan = plan_candidate
                else:
                    logger.info(f"[planner_debug] json found but no skill key, treating as final_reply")
                    final_reply = content
            else:
                final_reply = content
        except Exception as e:
            logger.warning(f"[planner_debug] plan JSON parse failed: {e}, treating as final_reply")
            final_reply = content
        logger.info(f"[planner_debug] outcome — plan={plan is not None}, final_reply={final_reply is not None}, provider={selected_provider}, reason={routing_reason}")
        timer.end_span("plan_skill_parse_ms")

        timer.is_complete = True
        return {
            "selected_provider": selected_provider,
            "routing_reason": routing_reason,
            "upgrade_requested": upgrade_requested,
            "plan": plan,
            "final_reply": final_reply,
            "messages": messages,
            "last_usage": response.usage
        }
    finally:
        timer.emit()

async def upgrade_confirm_node(state: AgentState):
    """處理模型升級確認。"""
    logger.info("Entering upgrade_confirm_node")
    
    # 根據 SOUL.md 語氣生成的確認文字
    reply = "嗯……這個問題有點複雜，我想切換到比較強的模型來處理。\n大概多花幾秒，費用會多一點點。沒意見的話 15 秒後我就自己決定了。"
    return {"final_reply": reply}

async def confirmer_node(state: AgentState):
    """CONFIRM 節點：處理需要用戶確認的操作。"""
    logger.info("Entering confirmer_node")
    plan = state.get("plan")

    if not plan:
        return {}

    # --- terminal 技能：admin 閘門 + allowlist/危險命令判定（不信任 LLM 給的 is_write）---
    if plan.get("skill") == "terminal":
        from skills.terminal import is_allowlisted, is_dangerous

        command = str((plan.get("params") or {}).get("command") or "").strip()

        # 1. admin 閘門：只有本人（users.role == 'admin'）能用終端機
        pool = getattr(state["model_router"], "_db_pool", None)
        is_admin = False
        if pool:
            try:
                row = await pool.fetchrow(
                    "SELECT role FROM users WHERE id = $1", state.get("user_id")
                )
                is_admin = bool(row and row["role"] == "admin")
            except Exception as e:
                logger.warning(f"terminal admin check failed: {e}")
        if not is_admin:
            logger.info(f"terminal denied for non-admin user {state.get('user_id')}")
            return {"final_reply": "這個我只聽 Iceman 的，沒辦法幫你在系統上執行命令喔。"}

        # 2. 危險命令：直接拒絕，不進入確認/執行
        danger = is_dangerous(command)
        if danger:
            logger.warning(f"terminal blocked dangerous command ({danger}): {command!r}")
            return {"final_reply": f"這個命令太危險了（{danger}），我不能幫你跑。"}

        # 3. allowlist 決定是否免確認；覆寫 is_write 後交給下方既有確認邏輯
        plan["is_write"] = not is_allowlisted(command)

    # 如果不是寫操作，或者已經收到確認，直接跳過
    if not plan.get("is_write") or state["confirmation_received"]:
        return {"plan": plan}
    
    # 如果是寫操作且尚未確認，回覆確認請求
    summary = plan.get("summary", "執行此操作")
    reply = f"好的，我準備幫你「{summary}」。這涉及系統更改，請問這樣可以嗎？"
    return {"final_reply": reply}

async def executor_node(state: AgentState):
    """EXECUTE 節點：呼叫 Skills Server。"""
    logger.info("Entering executor_node")
    plan = state["plan"]
    
    # --- Phase 4B/4D: File Analysis Execution ---
    if plan and plan.get("skill") == "file_analyze":
        from skills.file_analyzer import FileAnalyzer
        analyzer = FileAnalyzer(state["model_router"], db_pool=getattr(state["model_router"], "_db_pool", None))
        attachment = state["attachment"]
        result = await analyzer.analyze(
            attachment["local_path"],
            attachment["mime_type"],
            instruction=state["messages"][-1].content if state["messages"] else None,
            media_type=attachment.get("media_type"),
            user_id=state.get("user_id"),
            platform=state.get("platform"),
            source_message_id=state.get("source_message_id"),
            duration_ms=attachment.get("duration_ms"),
        )
        return {"skill_result": {"status": "ok", "analysis": result}}

    # --- web_search: in-process 執行，不經 Go Skills Server ---
    if plan and plan.get("skill") == "web_search":
        from skills.web_search import get_web_search_provider
        provider = get_web_search_provider()
        params = plan.get("params") or {}
        query = str(params.get("query") or "").strip()
        if not query:
            return {"skill_result": {"success": False, "error": "缺少搜尋關鍵字 query"}}
        result = await provider.search(query, limit=params.get("limit", 5))
        return {"skill_result": result}

    # --- terminal: in-process 執行，呼叫沙箱容器 exec 服務 ---
    if plan and plan.get("skill") == "terminal":
        from skills.terminal import get_terminal_skill
        skill = get_terminal_skill()
        params = plan.get("params") or {}
        command = str(params.get("command") or "").strip()
        is_poll = bool(params.get("task_id"))
        if not command and not is_poll:
            return {"skill_result": {"success": False, "error": "缺少命令 command"}}
        result = await skill.execute(
            command,
            timeout=params.get("timeout", 30),
            background=bool(params.get("background", False)),
            task_id=params.get("task_id"),
        )
        # home_context 指標：task_id → log 指標（供回溯與 7 天保留期清理）
        await _record_terminal_pointer(state, params, command, result)
        return {"skill_result": result}

    skills_url = os.getenv("SKILLS_URL")
    
    if not skills_url:
        return {"skill_result": {"status": "error", "error": "SKILLS_URL not configured"}}
        
    try:
        skill_name = plan.get("skill") if plan else "unknown"
        skill_params = plan.get("params") if plan else {}
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{skills_url}/skill/execute",
                json={"skill": skill_name, "params": skill_params},
                timeout=10.0
            )
            result = resp.json()
            return {"skill_result": result}
    except Exception as e:
        logger.error(f"Skill execution failed: {e}")
        return {"skill_result": {"status": "error", "error": str(e)}}

_VIEWER_LINK_RE = re.compile(r"\[[^\]]*\]\((?:https?://)?[^)]*?/terminal/view/[^)]*\)")
_VIEWER_URL_RE = re.compile(r"(?:https?://)?\S*/terminal/view/\S+")
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def _sanitize_terminal_reply(text) -> str:
    """清掉 reporter LLM 可能仿製的 viewer 連結與貼出的程式碼圍欄區塊。

    弱的 local 模型會因對話歷史含 viewer 連結樣式而學舌仿造假連結，也可能無視指示
    把原始輸出貼成 ``` 區塊。連結由 reporter deterministic 補上，這裡先把模型自產的
    連結/輸出區塊移除，確保聊天只有「一句話結論 + 唯一一條真連結」。
    """
    if not text:
        return ""
    text = _VIEWER_LINK_RE.sub("", text)
    text = _VIEWER_URL_RE.sub("", text)
    text = _CODE_FENCE_RE.sub("", text)        # 成對 ```...``` 區塊
    text = re.sub(r"```.*$", "", text, flags=re.DOTALL)  # 未閉合的尾段 ``` 也清掉
    return re.sub(r"\n{3,}", "\n\n", text).strip()


async def _record_terminal_pointer(state, params, command, result):
    """在 home_context 寫/更新 `terminal_log:<task_id>` 指標。

    啟動（前景/背景）時寫完整指標（含 command、created_at、status）；
    狀態輪詢時只合併更新 status，保留原 command。寫入失敗不影響執行結果。
    """
    data = result.get("data") or {}
    task_id = data.get("task_id") or params.get("task_id")
    if not task_id:
        return
    pool = getattr(state["model_router"], "_db_pool", None)
    if not pool:
        return
    is_poll = bool(params.get("task_id"))
    try:
        if is_poll:
            status = data.get("status") or "running"
            await pool.execute(
                "UPDATE home_context SET value = value || $2::jsonb, updated_at = NOW() "
                "WHERE key = $1",
                f"terminal_log:{task_id}",
                json.dumps({"status": status}),
            )
        else:
            if params.get("background"):
                status = "running"
            else:
                status = "done" if result.get("success") else "error"
            await pool.execute(
                "INSERT INTO home_context (key, value) VALUES ($1, $2) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
                f"terminal_log:{task_id}",
                json.dumps({
                    "task_id": task_id,
                    "command": command,
                    "status": status,
                    "created_at": time.time(),
                }),
            )
    except Exception as e:  # noqa: BLE001 — 指標寫入是附帶效果，不可拖垮主流程
        logger.warning(f"record terminal pointer failed: {e}")


async def reporter_node(state: AgentState):
    """REPORT 節點：將結果轉換為自然語言。"""
    logger.info("Entering reporter_node")
    router = state["model_router"]
    result = state["skill_result"]
    plan = state.get("plan")
    
    if plan and plan.get("skill") == "file_analyze":
        # 取得分析結果（例如貼圖描述、語音逐字稿或影片摘要）
        analysis = result.get("analysis", "分析失敗")

        # 將感知結果注入到最後一則 user message 中，優先級高於對話歷史模式。
        # 若只放在 system prompt 末尾，模型容易跟著歷史 pattern 走（例如前一筆是貓，就把所有貼圖都說成貓）。
        messages = list(state["messages"])
        if messages:
            last = messages[-1]
            messages[-1] = Message(role=last.role, content=f"{last.content}\n\n[感知：{analysis}]")

        perception_system = state["system_prompt"] + "\n\n請根據訊息中 [感知] 標記的實際內容回覆，不要依賴對話歷史中的推測。"

        response = await router.chat(
            messages,
            system_prompt=perception_system,
            provider=state.get("selected_provider"),
            caller="reporter_node_perception"
        )
        
        reply = response.content
        if not reply or len(reply.strip()) == 0:
            logger.warning("Cindy soul response was empty, using analysis result as fallback.")
            reply = f"嗯……我看到了這個貼圖：{analysis}"

        return {"final_reply": reply, "last_usage": response.usage}

    if plan and plan.get("skill") == "web_search":
        # 搜尋結果是外部不可信文本：以明確邊界標記注入，並限制只根據結果回答
        if result.get("success"):
            web = result.get("data", {}).get("web", [])
            lines = [
                f"{r['position']}. {r['title']}\n   來源：{r['url']}\n   {r['description']}"
                for r in web
            ]
            results_block = "\n".join(lines) if lines else "（沒有任何結果）"
            query = (plan.get("params") or {}).get("query", "")
            report_prompt = f"""
[搜尋結果開始]（查詢：{query}）
{results_block}
[搜尋結果結束]

以 Cindy 的語氣回答使用者的問題。只根據上方 [搜尋結果] 的內容回答，並附上引用的來源網址；結果沒提到的不要編造。如果搜尋結果與問題無關或不足以回答，誠實說沒找到。不要輸出 JSON。
"""
        else:
            report_prompt = f"""
## 搜尋失敗
原因：{result.get('error', '未知錯誤')}

以 Cindy 的語氣誠實告訴使用者：網路搜尋暫時無法使用，所以拿不到即時資訊。簡短說明原因即可，不要編造答案，不要輸出 JSON。
"""
        response = await router.chat(
            state["messages"],
            system_prompt=state["system_prompt"] + "\n\n" + report_prompt,
            provider=state.get("selected_provider"),
            caller="reporter_node_web_search"
        )
        return {"final_reply": response.content, "last_usage": response.usage}

    # --- terminal: 聊天只回精簡摘要 + viewer 連結，完整輸出交給 web viewer ---
    if plan and plan.get("skill") == "terminal":
        import terminal_logs
        params = plan.get("params") or {}
        data = result.get("data") or {}
        task_id = data.get("task_id") or params.get("task_id")
        is_poll = bool(params.get("task_id"))
        is_background = bool(params.get("background"))

        # 關鍵：**不**把原始輸出餵給 reporter LLM。完整輸出交給 web viewer；
        # 聊天只給狀態 metadata，讓模型產生一句話結論。否則弱的 local 模型會把整段
        # 輸出貼進聊天（違反 clean delivery），且因對話歷史含 viewer 連結樣式而學舌
        # 仿製假連結（歷史汙染）。連結一律由本節點 deterministic 補上，模型不碰。
        if not result.get("success"):
            err = result.get("error", "未知錯誤")
            report_prompt = (
                f"終端機命令執行失敗，原因：{err}。"
                "請用 Cindy 的語氣簡短、誠實地說明，不要編造輸出，不要輸出 JSON，"
                "不要在回覆中放任何網址或連結。"
            )
        elif is_background and not is_poll:
            report_prompt = (
                "終端機命令已在背景啟動。請用 Cindy 的語氣簡短說「已經開始執行、"
                "稍後可以點下面的連結查看即時進度」，一兩句即可，不要輸出 JSON，"
                "不要自己放任何網址或連結。"
            )
        else:
            exit_code = data.get("exit_code")
            ok = (exit_code == 0)
            line_count = (data.get("output") or "").count("\n")
            outcome = "成功（exit code 0）" if ok else f"非零退出（exit code {exit_code}）"
            report_prompt = (
                f"終端機命令已執行完畢，結果：{outcome}，輸出約 {line_count} 行。"
                "請只用「一句話」以 Cindy 的語氣確認執行結果（例如成功與否），"
                "**不要**貼任何輸出內容、**不要**放任何網址或連結、不要輸出 JSON。"
                "完整輸出會由下方系統附上的連結呈現，你不需要重複。"
            )

        response = await router.chat(
            state["messages"],
            system_prompt=state["system_prompt"] + "\n\n" + report_prompt,
            provider=state.get("selected_provider"),
            caller="reporter_node_terminal",
        )
        reply = _sanitize_terminal_reply(response.content) or "命令處理完成。"
        link = terminal_logs.build_view_url(task_id) if task_id else None
        if link:
            reply = f"{reply}\n\n[📄 查看完整終端機輸出]({link})"
        return {"final_reply": reply, "last_usage": response.usage}

    report_prompt = f"""
    ## Skill Result
    Skill: {plan.get('skill', 'unknown')}
    Result: {json.dumps(result)}

    以 Cindy 的語氣，向用戶報告執行結果。如果成功，用溫暖的方式分享；如果失敗，誠實說明原因。不要輸出 JSON。
    """
    
    response = await router.chat(
        state["messages"],
        system_prompt=state["system_prompt"] + "\n\n" + report_prompt,
        provider=state.get("selected_provider"),
        caller="reporter_node"
    )
    return {"final_reply": response.content, "last_usage": response.usage}

# --- Router ---

def route_after_planner(state: AgentState):
    if state.get("upgrade_requested"):
        return "upgrade_confirm"
    if state.get("final_reply"):
        return END
    return "confirmer"

def route_after_confirmer(state: AgentState):
    if state.get("final_reply"):
        return END
    return "executor"

# --- Graph Definition ---

def create_agent_graph():
    workflow = StateGraph(AgentState)
    
    workflow.add_node("planner", planner_node)
    workflow.add_node("upgrade_confirm", upgrade_confirm_node)
    workflow.add_node("confirmer", confirmer_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("reporter", reporter_node)
    
    workflow.set_entry_point("planner")
    
    workflow.add_conditional_edges("planner", route_after_planner)
    workflow.add_edge("upgrade_confirm", END)
    workflow.add_conditional_edges("confirmer", route_after_confirmer)
    workflow.add_edge("executor", "reporter")
    workflow.add_edge("reporter", END)
    
    return workflow.compile()
