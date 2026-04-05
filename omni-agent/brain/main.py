"""Omni-Agent Brain — FastAPI 入口。

接收 Gateway 轉發的 StandardMessage，
透過 SoulLoader 組裝 system prompt，
經由 ModelRouter 呼叫 LLM 取得回覆。
"""

import asyncio
import logging
import os

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import asyncpg

from llm import Message, Role, create_default_router
from soul.loader import SoulLoader
from memory.short_term import ShortTermMemory
from memory.long_term import LongTermMemory


logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","module":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("brain")


class StandardMessage(BaseModel):
    """與 Gateway 的 StandardMessage{} 對齊。"""
    id: str
    platform: str
    user_id: str
    message_type: str
    text: str | None = None


class BrainResponse(BaseModel):
    """回傳給 Gateway 的回覆。"""
    reply_text: str
    model_used: str
    provider: str
    cached: bool = False


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
        # Fallback to individual vars if DATABASE_URL is not set
        user = os.getenv("POSTGRES_USER", "omni")
        password = os.getenv("POSTGRES_PASSWORD", "omni")
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        db = os.getenv("POSTGRES_DB", "omni_agent")
        dsn = f"postgresql://{user}:{password}@{host}:{port}/{db}"

    try:
        pool = await asyncpg.create_pool(dsn)
        app.state.db_pool = pool
        logger.info("DB pool ready")
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
    """接收 Gateway 轉發的訊息，呼叫 LLM 回覆。"""
    if not msg.text:
        raise HTTPException(status_code=400, detail="Empty message text")

    router = app.state.router
    soul_loader = app.state.soul_loader
    short_term = app.state.short_term
    long_term = app.state.long_term

    # 1. SoulLoader 渲染 system prompt
    try:
        system_prompt = await soul_loader.render(user_id=msg.user_id)
    except Exception as e:
        logger.error(f"SoulLoader failed: {e}")
        system_prompt = "I am Cindy, a family AI assistant."

    # 2. 長期記憶召回
    long_term_context = ""
    if app.state.db_pool:
        memories = await long_term.recall(msg.user_id, msg.text)
        if memories:
            long_term_context = "\n\n## Long-term Memory\n以下為過去對話摘要，僅供參考，請以當前對話為準：\n"
            for m in memories:
                long_term_context += f"- {m}\n"
            system_prompt += long_term_context

    # 3. 短期記憶載入歷史
    history = []
    if app.state.db_pool:
        history = await short_term.load(msg.user_id, limit=5)

    # 組合訊息
    llm_messages = []
    for h in history:
        llm_messages.append(Message(role=Role(h['role']), content=h['content']))
    llm_messages.append(Message(role=Role.USER, content=msg.text))

    try:
        # 4. 呼叫 ModelRouter
        response = await router.chat(
            llm_messages,
            system_prompt=system_prompt,
        )

        # 5. 儲存本輪對話 (user message + assistant reply)
        if app.state.db_pool:
            round_messages = [
                {"role": "user", "content": msg.text},
                {"role": "assistant", "content": response.content}
            ]
            # 非同步執行儲存與索引更新，不 block 回應
            asyncio.create_task(short_term.save(msg.user_id, msg.platform, round_messages))

            # 6. 非同步觸發長期記憶 embedding 生成
            asyncio.create_task(long_term.store(msg.user_id, round_messages))

    except Exception as e:
        logger.error("LLM call failed: %s", e)
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")

    return BrainResponse(
        reply_text=response.content,
        model_used=response.model,
        provider=response.provider,
        cached=response.cached,
    )
