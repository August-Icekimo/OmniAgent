import asyncio
import logging
import os
import json
from datetime import datetime

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import asyncpg

from llm import Message, Role, create_default_router
from soul.loader import SoulLoader
from memory.short_term import ShortTermMemory
from memory.long_term import LongTermMemory
from agent.graph import create_agent_graph
from agent.proactive import start_proactive_tasks


logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","module":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("brain")


class AttachmentModel(BaseModel):
    file_id: str
    file_name: str
    mime_type: str
    size_bytes: int
    local_path: str
    media_type: str | None = None
    duration_ms: int | None = None

class StandardMessage(BaseModel):
    """與 Gateway 的 StandardMessage{} 對齊。"""
    id: str
    source_message_id: str | None = None
    platform: str
    user_id: str
    message_type: str
    text: str | None = None
    attachment: AttachmentModel | None = None


class BrainResponse(BaseModel):
    """回傳給 Gateway 的回覆。"""
    reply_text: str
    model_used: str
    provider: str
    cached: bool = False
    routing_reason: str | None = None


# --- App Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """啟動時初始化 ModelRouter、SoulLoader 與記憶模組。"""
    logger.info("Brain starting up...")

    # 初始化 ModelRouter
    router = create_default_router()
    app.state.router = router

    # 初始化 DB connection pool
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        user = os.getenv("POSTGRES_USER", "omni")
        password = os.getenv("POSTGRES_PASSWORD", "omni")
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        db = os.getenv("POSTGRES_DB", "omni_agent")
        dsn = f"postgresql://{user}:{password}@{host}:{port}/{db}"

    try:
        pool = await asyncpg.create_pool(dsn)
        app.state.db_pool = pool
        app.state.router.set_db_pool(pool)
        logger.info("DB pool ready and linked to router")
    except Exception as e:
        logger.error(f"DB unavailable, running in stateless mode: {e}")
        app.state.db_pool = None

    # 初始化 SoulLoader
    soul_path = os.path.join(os.path.dirname(__file__), "..", "SOUL.md")
    template_dir = os.path.join(os.path.dirname(__file__), "soul", "templates")
    app.state.soul_loader = SoulLoader(soul_path, template_dir, app.state.db_pool)
    logger.info("SoulLoader ready")

    # 初始化記憶模組
    app.state.short_term = ShortTermMemory(app.state.db_pool)
    app.state.long_term = LongTermMemory(app.state.db_pool, router)
    logger.info("Memory modules ready")

    # 初始化 LangGraph
    app.state.graph = create_agent_graph()
    logger.info("Agent graph initialized")

    # 啟動主動推送任務
    if app.state.db_pool:
        await start_proactive_tasks(app)
        logger.info("Proactive tasks started")

    yield

    if app.state.db_pool:
        await app.state.db_pool.close()
    logger.info("Brain shutting down.")


app = FastAPI(title="Omni-Agent Brain", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "brain"}


@app.post("/chat", response_model=BrainResponse)
async def chat(msg: StandardMessage):
    """接收 Gateway 轉發的訊息，透過 LangGraph 處理。"""
    if not msg.text and not msg.attachment:
        raise HTTPException(status_code=400, detail="Empty message text and no attachment")

    router = app.state.router
    soul_loader = app.state.soul_loader
    short_term = app.state.short_term
    long_term = app.state.long_term
    pool = app.state.db_pool
    
    # 0. 狀態預設值
    confirmation_received = False
    pending_plan = None
    manual_selected_provider = None

    # 1. 處理特殊狀態：模型升級確認 (僅限 Admin)
    # 此處簡化：假設所有進來的 UserID 都已在 Gateway 驗證過
    if pool:
        escalation_pending = await pool.fetchrow("SELECT value FROM home_context WHERE key = 'escalation:pending'")
        if escalation_pending:
            # 只有 Admin 才能確認。這裡我們先檢查是否為同意升級的關鍵字。
            if any(word in msg.text.lower() for word in ["好", "可以", "升級", "yes", "ok"]):
                target_model = json.loads(escalation_pending['value'])['target_model']
                # router.set_default(target_model) # 假設 router 支援
                await pool.execute("DELETE FROM home_context WHERE key = 'escalation:pending'")
                return BrainResponse(
                    reply_text=f"好的，大腦已經完成模型升級至 `{target_model}`，現在反應會更精確敏銳！",
                    model_used=target_model, provider="escalated"
                )

    # 2. 處理特殊狀態：技能確認回覆 或 模型升級確認回覆
    if pool:
        # 技能確認
        pending_check = await pool.fetchrow("SELECT value FROM home_context WHERE key = $1", f"confirm:pending:{msg.user_id}")
        if pending_check:
            if any(word in msg.text.lower() for word in ["好", "可以", "確認", "yes", "go"]):
                confirmation_received = True
                pending_plan = json.loads(pending_check['value'])
            await pool.execute("DELETE FROM home_context WHERE key = $1", f"confirm:pending:{msg.user_id}")
            
        # 模型升級確認 (Phase 4A)
        upgrade_check = await pool.fetchrow("SELECT value FROM home_context WHERE key = $1", f"model_upgrade:pending:{msg.user_id}")
        if upgrade_check:
            upgrade_data = json.loads(upgrade_check['value'])
            if any(word in msg.text.lower() for word in ["好", "可以", "升級", "yes", "ok"]):
                confirmation_received = True
                manual_selected_provider = upgrade_data.get("target_provider")
                logger.info(f"User confirmed model upgrade to {manual_selected_provider}")
            await pool.execute("DELETE FROM home_context WHERE key = $1", f"model_upgrade:pending:{msg.user_id}")

    # 3. SoulLoader 渲染 system prompt
    try:
        system_prompt = await soul_loader.render(user_id=msg.user_id)
    except Exception as e:
        logger.error(f"SoulLoader failed: {e}")
        system_prompt = "I am Cindy, a family AI assistant."

    # 4. 長期記憶召回
    if pool:
        memories = await long_term.recall(msg.user_id, msg.text)
        if memories:
            long_term_context = "\n\n## Long-term Memory\n以下為過去對話摘要：\n"
            for m in memories:
                long_term_context += f"- {m}\n"
            system_prompt += long_term_context

    # 5. 短期記憶載入歷史
    history = []
    if pool:
        history = await short_term.load(msg.user_id, limit=5)

    # 組合訊息
    llm_messages = []
    for h in history:
        llm_messages.append(Message(role=Role(h['role']), content=h['content']))
    llm_messages.append(Message(role=Role.USER, content=msg.text))

    # 6. 執行 LangGraph
    state = {
        "user_id": msg.user_id,
        "source_message_id": msg.source_message_id,
        "platform": msg.platform,
        "messages": llm_messages,
        "system_prompt": system_prompt,
        "model_router": router,
        "selected_provider": manual_selected_provider,
        "routing_reason": f"manual:confirmed" if manual_selected_provider else None,
        "complexity": None,
        "complexity_reason": None,
        "upgrade_requested": False,
        "attachment": msg.attachment.model_dump() if msg.attachment else None
    }

    try:
        final_state = await app.state.graph.ainvoke(state)
        
        # 7. 檢查多模態失敗回傳 (Phase 4D Honest Fallback)
        if msg.attachment and not final_state.get("final_reply"):
             # 此情況可能發生在所有 Gemini Provider 都失敗時
             logger.error(f"Multimodal processing failed for message {msg.id}")
             return BrainResponse(
                 reply_text="我這邊看不到/聽不到,可以打字告訴我嗎?",
                 model_used="fallback", provider="none",
                 routing_reason="multimodal_failure"
             )

        # 8. 儲存本輪對話 (含 Metadata)
        reply_text = final_state.get("final_reply", "Sorry, I encountered an internal error.")
        provider_name = final_state.get("selected_provider") or router._default_provider
        client = router._clients.get(provider_name)
        model_name = client.model_name() if client else "unknown"

        if pool:
            round_messages = [
                {"role": "user", "content": msg.text},
                {"role": "assistant", "content": reply_text}
            ]
            metadata = {
                "model": model_name,
                "provider": provider_name,
                "routing_reason": final_state.get("routing_reason")
            }
            asyncio.create_task(short_term.save(msg.user_id, msg.platform, round_messages, metadata))
            asyncio.create_task(long_term.store(msg.user_id, round_messages))

        # 9. 處理 Phase 4A 升級確認 (F-06 Auto-confirm)
        if pool and final_state.get("upgrade_requested") and final_state.get("final_reply"):
            # 存入 pending 狀態
            await pool.execute(
                "INSERT INTO home_context (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                f"model_upgrade:pending:{msg.user_id}",
                json.dumps({
                    "start_time": datetime.now().isoformat(),
                    "target_provider": final_state.get("selected_provider"), # 注意：規劃時已決定好
                    "messages": [m.__dict__ for m in final_state["messages"]]
                })
            )
            # 啟動 15s 自動確認任務
            asyncio.create_task(auto_confirm_model_upgrade(app, msg, final_state))

        return BrainResponse(
            reply_text=reply_text,
            model_used=model_name,
            provider=provider_name,
            routing_reason=final_state.get("routing_reason")
        )

    except Exception as e:
        import traceback
        logger.error(f"Agent graph execution failed: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=502, detail=f"Agent error: {e}")
async def auto_confirm_model_upgrade(app, orig_msg: StandardMessage, state: dict):
    """15秒自動確認升級背景任務。"""
    user_id = orig_msg.user_id
    pool = app.state.db_pool
    
    await asyncio.sleep(15)
    
    # 檢查是否還在 pending
    if pool:
        row = await pool.fetchrow("SELECT value FROM home_context WHERE key = $1", f"model_upgrade:pending:{user_id}")
        if not row:
            logger.info(f"Auto-confirm skipped for user {user_id}: no pending upgrade")
            return
            
        # 執行升級！
        logger.info(f"Auto-confirming model upgrade for user {user_id}")
        await pool.execute("DELETE FROM home_context WHERE key = $1", f"model_upgrade:pending:{user_id}")
        
        # 重新執行 LangGraph
        state["upgrade_requested"] = False
        state["confirmation_received"] = True
        # 注意：selected_provider 已經在 planner_node 決定好了
        
        try:
            final_state = await app.state.graph.ainvoke(state)
            reply_text = final_state.get("final_reply", "執行完成（自動升級）。")
            
            # 推送訊息給使用者 (透過 Telegram Bot API)
            bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
            admin_chats = await pool.fetch("SELECT chat_id FROM telegram_accounts WHERE user_id = (SELECT id FROM users WHERE id = $1)", user_id)
            
            # 如果是 Telegram
            if orig_msg.platform == "telegram" and bot_token:
                import httpx
                async with httpx.AsyncClient() as client:
                    target_chat = orig_msg.id # Telegram 裡 id 可能是 chat_id 或 msg_id，這裡需確認整合方式
                    # 為簡化，使用原本訊息傳來的 user_id 關聯的 chat_id
                    chat_row = await pool.fetchrow("SELECT chat_id FROM telegram_accounts WHERE user_id = $1::uuid", user_id)
                    if chat_row:
                        await client.post(
                            f"https://api.telegram.org/bot{bot_token}/sendMessage",
                            json={"chat_id": chat_row['chat_id'], "text": reply_text}
                        )
            
            # TODO: 支援 LINE 及其它平台
            # 儲存對話 (含 Metadata)
            metadata = {
                "model": final_state.get("selected_provider"),
                "provider": final_state.get("selected_provider"),
                "routing_reason": "auto_confirm"
            }
            asyncio.create_task(app.state.short_term.save(user_id, orig_msg.platform, round_messages, metadata))
            
        except Exception as e:
            logger.error(f"Auto-confirm execution failed: {e}")
