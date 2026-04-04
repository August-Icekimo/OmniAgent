"""Omni-Agent Brain — FastAPI 入口。

接收 Gateway 轉發的 StandardMessage，
透過 SoulLoader 組裝 system prompt，
經由 ModelRouter 呼叫 LLM 取得回覆。
"""

import logging
import os

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from llm import Message, Role, create_default_router


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
    """啟動時初始化 ModelRouter。"""
    logger.info("Brain starting up...")
    app.state.router = create_default_router()
    # TODO Phase 2: 初始化 SoulLoader，讀取 SOUL.md
    # TODO Phase 3: 初始化 DB connection pool
    logger.info("Brain ready.")
    yield
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

    # TODO Phase 2: 用 SoulLoader 渲染 system prompt
    # system_prompt = await soul_loader.render(user_id=msg.user_id)
    system_prompt = None  # 暫時無 system prompt

    messages = [Message(role=Role.USER, content=msg.text)]

    try:
        response = await router.chat(
            messages,
            system_prompt=system_prompt,
        )
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")

    return BrainResponse(
        reply_text=response.content,
        model_used=response.model,
        provider=response.provider,
        cached=response.cached,
    )
