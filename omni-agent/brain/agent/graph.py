import json
import logging
import os
from typing import Annotated, Any, Dict, List, Optional, TypedDict

import httpx
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from llm import Message, Role, ModelRouter

logger = logging.getLogger("brain.agent")

class AgentState(TypedDict):
    """LangGraph 狀態結構。"""
    user_id: str
    platform: str
    messages: List[Message]
    system_prompt: str
    plan: Optional[Dict[str, Any]]
    confirmation_received: bool
    skill_result: Optional[Dict[str, Any]]
    final_reply: Optional[str]
    model_router: ModelRouter

# --- Nodes ---

async def planner_node(state: AgentState):
    """PLAN 節點：決定是否需要呼叫技能。"""
    logger.info("Entering planner_node")
    
    # 如果已經有 plan (例如從 pending confirmation 載入)，跳過重新規劃
    if state.get("plan"):
        return {}
        
    router = state["model_router"]
    
    # 注入技能描述 (簡化版，未來可動態從 Skills Server 獲取)
    skills_context = """
    ## Available Skills
    - wake_on_lan: params {"mac": "AA:BB:CC..."}. [Write]
    - cockpit: params {"action": "status"|"restart_service", "service": "..."}. status is Read, restart_service is [Write].
    - home_assistant: Not implemented yet. [Read]
    
    If a skill is needed, output ONLY a JSON block:
    ```json
    {"skill": "skill_name", "params": {}, "is_write": true/false, "summary": "What I will do"}
    ```
    If no skill is needed, just reply normally.
    """
    
    full_system = state["system_prompt"] + "\n\n" + skills_context
    
    response = await router.chat(
        state["messages"],
        system_prompt=full_system,
    )
    
    content = response.content
    try:
        # 嘗試尋找 JSON 塊
        if "```json" in content:
            json_str = content.split("```json")[-1].split("```")[0].strip()
            plan = json.loads(json_str)
            return {"plan": plan}
    except Exception as e:
        logger.warning(f"Failed to parse plan JSON: {e}")

    return {"final_reply": content}

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
    skills_url = os.getenv("SKILLS_URL")
    
    if not skills_url:
        return {"skill_result": {"status": "error", "error": "SKILLS_URL not configured"}}
        
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{skills_url}/skill/execute",
                json={"skill": plan["skill"], "params": plan["params"]},
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
    plan = state["plan"]
    
    report_prompt = f"""
    ## Skill Result
    Skill: {plan['skill']}
    Result: {json.dumps(result)}
    
    以 Cindy 的語氣，向用戶報告執行結果。如果成功，用溫暖的方式分享；如果失敗，誠實說明原因。不要輸出 JSON。
    """
    
    response = await router.chat(
        state["messages"],
        system_prompt=state["system_prompt"] + "\n\n" + report_prompt,
    )
    return {"final_reply": response.content}

# --- Router ---

def route_after_planner(state: AgentState):
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
    workflow.add_node("confirmer", confirmer_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("reporter", reporter_node)
    
    workflow.set_entry_point("planner")
    
    workflow.add_conditional_edges("planner", route_after_planner)
    workflow.add_conditional_edges("confirmer", route_after_confirmer)
    workflow.add_edge("executor", "reporter")
    workflow.add_edge("reporter", END)
    
    return workflow.compile()
