import json
import logging
import os
import time
from typing import Annotated, Any, Dict, List, Optional, TypedDict

import httpx
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from llm import Message, Role, ModelRouter
from .prompts import build_system_prompt, build_tools_prompt, build_assessment_prompt

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
            "plan_routing_ms": 0.0,           # step 1+2: provider selection
            "plan_complexity_prompt_ms": 0.0,  # step 3: build assessment prompt
            "plan_complexity_llm_ms": 0.0,     # step 3: complexity assessment LLM call
            "plan_complexity_parse_ms": 0.0,   # step 3: parse assessment response
            "plan_upgrade_check_ms": 0.0,      # step 4: check_upgrade()
            "plan_skills_prompt_ms": 0.0,      # step 5: build skills prompt
            "plan_main_llm_ms": 0.0,           # step 5: main planning LLM call
            "plan_skill_parse_ms": 0.0,        # step 5: parse plan/skill response
        }
        self.is_cold_start = False
        self.executor_chosen = "unknown"
        self.complexity = "unknown"
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
            "complexity": self.complexity,
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
    complexity: Optional[str]
    complexity_reason: Optional[str]
    upgrade_requested: bool
    attachment: Optional[Dict[str, Any]]

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
            return {
                "plan": {
                    "skill": "file_analyze",
                    "is_write": False,
                    "summary": f"分析檔案：{state['attachment']['file_name']}"
                },
                "selected_provider": None, # 讓 router 決定最好的 (OAuth 優先)
                "routing_reason": "attachment_routing"
            }

        # 如果已經有 plan (例如從 pending confirmation 載入)，跳過重新規劃
        if state.get("plan"):
            timer.end_span("plan_graph_entry_ms")
            timer.is_complete = True
            return {}

        timer.end_span("plan_graph_entry_ms")
        
        router = state["model_router"]
        user_id = state["user_id"]

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

        # 3. 複雜度評估 (由 Gemini Flash 統一執行)
        complexity = "medium"
        complexity_reason = "default"

        # 只有在非手動覆蓋的情況下進行評估
        if "override" not in routing_reason:
            try:
                # 準備評估用的提示詞
                timer.start_span()
                assessment_system = build_system_prompt(state["system_prompt"])
                timer.end_span("plan_complexity_prompt_ms")

                # 使用 Gemini Flash 進行評估 (假設 router 有註冊 gemini)
                timer.start_span()
                eval_response = await router.chat(
                    messages,
                    system_prompt=assessment_system,
                    provider=None, # 使用預設路由 (OAuth 優先)
                    temperature=0.0 # 評估需穩定
                )
                timer.end_span("plan_complexity_llm_ms")

                # 解析評估結果
                timer.start_span()
                content = eval_response.content
                if "```json" in content:
                    json_str = content.split("```json")[-1].split("```")[0].strip()
                    eval_data = json.loads(json_str)
                    complexity = eval_data.get("complexity", "medium")
                    complexity_reason = eval_data.get("reasoning", "eval")
                timer.end_span("plan_complexity_parse_ms")
            except Exception as e:
                logger.error(f"Complexity assessment failed: {e}")

        timer.complexity = complexity

        # 4. 檢查升級規則
        upgrade_requested = False
        upgrade_info = {}
        if "override" not in routing_reason:
            timer.start_span()
            upgrade_info = await router.check_upgrade(selected_provider, complexity, user_id)
            if upgrade_info.get("upgrade"):
                upgrade_requested = True
                if not upgrade_info.get("require_confirmation", True):
                    # 靜默升級
                    selected_provider = upgrade_info["target_provider"]
                    routing_reason = upgrade_info["reason"]
                    upgrade_requested = False # 不需經過確認節點
            timer.end_span("plan_upgrade_check_ms")

        timer.executor_chosen = selected_provider

        # 5. 判斷是否需要技能 (使用目前選定的 provider 執行)
        timer.start_span()
        skills_context = build_tools_prompt(os.getenv("SKILLS_URL"))
        full_system = state["system_prompt"] + "\n\n" + skills_context
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

        timer.start_span()
        content = response.content
        plan = None
        final_reply = None

        try:
            if "```json" in content:
                json_str_skill = content.split("```json")[-1].split("```")[0].strip()
                plan_candidate = json.loads(json_str_skill)
                if isinstance(plan_candidate, dict) and "skill" in plan_candidate:
                    plan = plan_candidate
                else:
                    final_reply = content
            else:
                final_reply = content
        except Exception as e:
            logger.warning(f"Failed to parse plan JSON: {e}")
            final_reply = content
        timer.end_span("plan_skill_parse_ms")

        timer.is_complete = True
        return {
            "selected_provider": selected_provider,
            "routing_reason": routing_reason,
            "complexity": complexity,
            "complexity_reason": complexity_reason,
            "upgrade_requested": upgrade_requested,
            "plan": plan,
            "final_reply": final_reply,
            "messages": messages # 更新後的訊息 (如果剝離了前綴)
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
    plan = state["plan"]
    
    # 如果不是寫操作，或者已經收到確認，直接跳過
    if not plan.get("is_write") or state["confirmation_received"]:
        return {}
    
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
            
        return {"final_reply": reply}

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
    return {"final_reply": response.content}

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
