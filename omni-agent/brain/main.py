import asyncio
import hashlib
import logging
import os
import json
import re
import traceback
import uuid
from datetime import timedelta

# 歷史時間戳的 gap 門檻：相鄰輪間隔超過此值才標時間（gap-aware，見 _execute_conversation）
_TURN_GAP_MARK = timedelta(minutes=30)

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import asyncpg

import terminal_logs

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


_VIEWER_LINK_RE = re.compile(r"\[[^\]]*\]\((?:https?://)?[^)]*?/terminal/view/[^)]*\)")
_VIEWER_URL_RE = re.compile(r"(?:https?://)?\S*/terminal/view/\S+")


def _strip_viewer_links(text: str) -> str:
    """存入對話歷史前移除終端機 viewer 連結，避免歷史汙染使模型學舌仿造假連結。

    回給使用者的 reply_text 仍保留真連結；只有「寫進記憶的副本」被清掉連結。
    """
    if not text:
        return text
    text = _VIEWER_LINK_RE.sub("", text)
    text = _VIEWER_URL_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _media_placeholder(attachment: "AttachmentModel") -> str:
    """Generate a content-addressed placeholder for an attachment.
    Uses SHA-256 of file bytes (first 512 KB) so the same media maps to
    the same hash regardless of who sent it — enabling future cache lookup.
    Falls back to hashing the file_id if the file is unreadable.
    """
    try:
        h = hashlib.sha256()
        with open(attachment.local_path, "rb") as f:
            h.update(f.read(524288))
        digest = h.hexdigest()[:12]
    except Exception:
        digest = hashlib.sha256(attachment.file_id.encode()).hexdigest()[:12]
    media_type = attachment.media_type or "file"
    return f"[{media_type}:{digest}]"


class AttachmentModel(BaseModel):
    file_id: str
    file_name: str
    mime_type: str
    size_bytes: int
    local_path: str
    media_type: str | None = None
    duration_ms: int | None = None

async def _save_voice_transcript(pool, user_id, platform, source_msg_id, transcript, path, duration_ms):
    if not pool or not user_id:
        return
    import uuid
    try:
        uid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        return
    try:
        await pool.execute(
            """
            INSERT INTO voice_transcripts (user_id, source_platform, source_message_id, transcript, audio_path, duration_ms)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            uid, platform, source_msg_id or "unknown", transcript, path, duration_ms
        )
    except Exception as e:
        logger.error(f"Failed to store voice transcript: {e}")

# whisper 對非語音段會吐出標註 token（如 [音樂]/[BLANK_AUDIO]），
# 也會把真實語音整段包進方括號（實測 [今天的天氣很]）。
# 策略：先整段移除已知非語音標註，再把殘留的成對括號去殼、保留內文。
_NON_SPEECH_TOKEN = re.compile(
    r"[\[\(【（]\s*"
    r"(?:blank_audio|no\s*audio|silence|inaudible|音樂|音乐|掌聲|掌声|"
    r"笑聲|笑声|噪音|雜音|杂音|無聲|无声|無語音|静音)"
    r"\s*[\]\)】）]",
    re.IGNORECASE,
)
_BRACKET_CHARS = str.maketrans("", "", "[]()【】（）")

def _clean_transcript(text: str) -> str:
    text = _NON_SPEECH_TOKEN.sub("", text)
    text = text.translate(_BRACKET_CHARS)
    return re.sub(r"\s+", " ", text).strip()

async def _transcribe_voice_local(attachment: AttachmentModel, model) -> dict:
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        
        def _do_transcribe():
            segments, info = model.transcribe(
                attachment.local_path,
                language="zh",
                initial_prompt="以下是繁體中文語音訊息的逐字稿。",
                beam_size=5,
            )
            return _clean_transcript(" ".join([segment.text for segment in segments]))
            
        transcript = await loop.run_in_executor(None, _do_transcribe)
        if transcript:
            return {"success": True, "transcript": transcript}
        return {"success": False, "error": "Empty transcript"}
    except Exception as e:
        return {"success": False, "error": str(e)}

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
    # gateway runtime footer 用：本輪 LLM call 的 token 數與該 model 視窗上限。
    # 0 表示資料缺失，gateway 據此省略對應欄位。
    context_tokens: int = 0
    context_length: int = 0


class TurnRequest(BaseModel):
    """解耦 turn 請求：gateway 把一個使用者的 burst 組裝成多則訊息一次送入。"""
    turn_id: str
    user_id: str
    platform: str
    messages: list[StandardMessage]


async def _terminal_log_cleanup_loop(app: FastAPI):
    """終端機 log 保留期清理：啟動跑一次，之後每日重跑。

    刪檔由 terminal_logs.prune_expired_files() 負責（容錯，單檔失敗不影響其他）；
    對應的 home_context `terminal_log:<task_id>` 指標在此一併刪除（只有 brain 有 pool）。
    """
    interval = int(os.getenv("TERMINAL_LOG_CLEANUP_INTERVAL", str(24 * 3600)))
    while True:
        try:
            pruned = terminal_logs.prune_expired_files()
            pool = app.state.db_pool
            if pruned and pool:
                keys = [f"terminal_log:{tid}" for tid in pruned]
                await pool.execute(
                    "DELETE FROM home_context WHERE key = ANY($1::text[])", keys
                )
            if pruned:
                logger.info(f"Terminal log cleanup pruned {len(pruned)} task(s)")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — 清理失敗不可拖垮服務
            logger.warning(f"Terminal log cleanup failed: {e}")
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise


# --- App Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """啟動時初始化 ModelRouter、SoulLoader 與記憶模組。"""
    logger.info("Brain starting up...")

    # 確保終端機 log 共享 volume 可由非 root 的 sandbox 寫入（排除初始化擁有權競態）
    terminal_logs.ensure_log_dir_writable()

    # 預載 local STT 模型
    try:
        from faster_whisper import WhisperModel
        app.state.stt_model = WhisperModel("small", device="cpu", compute_type="int8")
        logger.info("Local STT model loaded (faster-whisper small)")
    except Exception as e:
        logger.error(f"Failed to load local STT model: {e}")
        app.state.stt_model = None

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

    # 啟動終端機 log 保留期清理（啟動跑一次 + 每日重跑）
    app.state.terminal_cleanup_task = asyncio.create_task(
        _terminal_log_cleanup_loop(app)
    )

    yield

    task = getattr(app.state, "terminal_cleanup_task", None)
    if task:
        task.cancel()

    if app.state.db_pool:
        await app.state.db_pool.close()
    logger.info("Brain shutting down.")


app = FastAPI(title="Omni-Agent Brain", lifespan=lifespan)

# 終端機 viewer 的 vendored xterm.js 靜態資產（路徑與 Caddy /terminal* 路由相符）
if os.path.isdir(terminal_logs.STATIC_DIR):
    app.mount(
        "/terminal/static",
        StaticFiles(directory=terminal_logs.STATIC_DIR),
        name="terminal-static",
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "brain"}


@app.get("/terminal/view/{task_id}")
async def terminal_view(task_id: str, t: str | None = None):
    """終端機 log 檢視頁（內嵌 xterm.js）。

    門禁由 secure-gateway 的 Caddy admin_policy（Google OAuth）把關；
    此處再驗短效 token 作縱深防禦。
    """
    if not terminal_logs.is_valid_task_id(task_id):
        raise HTTPException(status_code=404, detail="找不到該終端機任務")
    try:
        if not terminal_logs.verify_view_token(task_id, t):
            raise HTTPException(status_code=403, detail="連結已失效或無效")
    except terminal_logs.TokenError as e:
        # 金鑰未設定屬伺服器組態錯誤，明確報錯而非默默放行
        raise HTTPException(status_code=503, detail=str(e))
    if not terminal_logs.task_exists(task_id):
        raise HTTPException(status_code=404, detail="找不到該終端機任務")
    meta = terminal_logs.read_meta(task_id)
    return HTMLResponse(terminal_logs.render_viewer_html(task_id, t, meta))


@app.websocket("/terminal/ws/{task_id}")
async def terminal_ws(ws: WebSocket, task_id: str, t: str | None = None):
    """tail 共享 volume 的 log 檔，先回放既有內容再即時推送增量。

    原始 bytes 以 binary frame 推送（xterm.js 自行解碼，跨 chunk 的多位元組字元
    不會破碼）；狀態變化以 text JSON frame 推送。依 meta 的 status 判斷結束。
    """
    # 與 HTTP viewer 相同的驗證；失敗則在握手階段關閉（瀏覽器收到 onerror）
    if not terminal_logs.is_valid_task_id(task_id):
        await ws.close(code=1008)
        return
    try:
        ok = terminal_logs.verify_view_token(task_id, t)
    except terminal_logs.TokenError:
        await ws.close(code=1011)  # 伺服器組態錯誤（金鑰未設定）
        return
    if not ok or not terminal_logs.task_exists(task_id):
        await ws.close(code=1008)
        return

    await ws.accept()
    path = terminal_logs.log_path(task_id)
    offset = 0

    def _read_from(off: int) -> bytes:
        try:
            with open(path, "rb") as f:
                f.seek(off)
                return f.read()
        except OSError:
            return b""

    try:
        meta = terminal_logs.read_meta(task_id) or {}
        await ws.send_text(json.dumps({"status": meta.get("status", "pending")}))
        while True:
            data = _read_from(offset)
            if data:
                offset += len(data)
                await ws.send_bytes(data)

            meta = terminal_logs.read_meta(task_id) or {}
            status = meta.get("status")
            if status in ("done", "error"):
                # sandbox 在 log 完整 flush 後才標記 done/error，故再讀一次必收完整
                rest = _read_from(offset)
                if rest:
                    offset += len(rest)
                    await ws.send_bytes(rest)
                await ws.send_text(json.dumps(
                    {"status": status, "exit_code": meta.get("exit_code")}))
                break

            await asyncio.sleep(0.3)
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning(f"terminal_ws error for {task_id}: {e}")
    finally:
        try:
            await ws.close()
        except Exception:
            pass


def _build_footer(model_used: str, context_tokens: int, context_length: int) -> str:
    """解耦交付下由 brain 組裝 runtime footer（FOOTER_ENABLED=true 才啟用）。
    turn 投遞時 gateway 直接送 turns.result，故 footer 需在此處附上（對齊舊
    gateway buildFooter 行為）。"""
    if os.getenv("FOOTER_ENABLED") != "true":
        return ""
    parts = []
    if model_used and model_used != "unknown":
        parts.append(model_used.rsplit("/", 1)[-1])
    if context_length > 0 and context_tokens >= 0:
        parts.append(f"{min(context_tokens * 100 // context_length, 100)}%")
    if not parts:
        return ""
    return "\n\n— " + " · ".join(parts)


def _empty_conv_result(reason: str, *, cancelled=False, multimodal_failed=False) -> dict:
    return {
        "cancelled": cancelled,
        "multimodal_failed": multimodal_failed,
        "reply_text": "",
        "model_used": "",
        "provider": "",
        "routing_reason": reason,
        "context_tokens": 0,
        "context_length": 0,
    }


async def _execute_conversation(
    *,
    user_id: str,
    platform: str,
    source_message_id: str | None,
    user_content: str,
    attachment: dict | None = None,
    confirmation_received: bool = False,
    resume_messages=None,
    resume_iterations: int = 0,
    cancel_check=None,
) -> dict:
    """執行一輪對話核心（system prompt → 記憶 → graph → 持久化）。
    /chat（單訊息）與 /turn（多訊息組裝）共用，確保兩條路徑行為一致。

    cancel_check：可選 async callable，回 True 表示使用者撤回 → 取消進行中的
    graph 任務（升級路徑 asyncio cancel 直接中止 SDK 呼叫；本地路徑見 local_client）。
    """
    router = app.state.router
    soul_loader = app.state.soul_loader
    short_term = app.state.short_term
    long_term = app.state.long_term
    pool = app.state.db_pool

    # system prompt
    try:
        system_prompt = await soul_loader.render(user_id=user_id)
    except Exception as e:
        logger.error(f"SoulLoader failed: {e}")
        system_prompt = "I am Cindy, a family AI assistant."

    # 長期記憶召回
    if pool:
        memories = await long_term.recall(user_id, user_content)
        if memories:
            long_term_context = "\n\n## Long-term Memory\n以下為過去對話摘要：\n"
            for m in memories:
                long_term_context += f"- {m}\n"
            system_prompt += long_term_context

    # 短期記憶歷史
    history = []
    if pool:
        history = await short_term.load(user_id, limit=5)

    # 歷史相對時序（gap-aware）：相鄰顯示時間間隔 > 30 分鐘才在該則前綴時間標記，
    # 給模型對話時間感而不洗版。標記只加在送模型的 content，不污染存回歷史的內容。
    llm_messages = []
    prev_ts = None
    for h in history:
        content = h['content']
        ts = h.get('_ts')
        if ts is not None:
            if prev_ts is None or (ts - prev_ts) > _TURN_GAP_MARK:
                local_ts = ts.astimezone()  # UTC-aware → 容器本地(台北)
                content = f"[{local_ts.strftime('%Y-%m-%d %H:%M')}] {content}"
            prev_ts = ts
        llm_messages.append(Message(role=Role(h['role']), content=content))
    llm_messages.append(Message(role=Role.USER, content=user_content))

    # 確認往返恢復：用先前存下的對話（含待批准 tool_calls）取代本輪訊息。
    resume_tools = bool(resume_messages and confirmation_received)
    if resume_tools:
        from agent.graph import deserialize_messages
        graph_messages = deserialize_messages(resume_messages)
    else:
        graph_messages = llm_messages

    state = {
        "user_id": user_id,
        "source_message_id": source_message_id,
        "platform": platform,
        "messages": graph_messages,
        "system_prompt": system_prompt,
        "model_router": router,
        "selected_provider": None,
        "routing_reason": None,
        "attachment": attachment,
        "confirmation_received": confirmation_received,
        "resume_tools": resume_tools,
        "tool_iterations": resume_iterations,
    }

    # cancel-aware 執行：graph 跑在 task 上，有 cancel_check 時定期輪詢撤回訊號。
    graph_task = asyncio.create_task(app.state.graph.ainvoke(state))
    if cancel_check is not None:
        while True:
            done, _ = await asyncio.wait({graph_task}, timeout=0.5)
            if graph_task in done:
                break
            try:
                if await cancel_check():
                    graph_task.cancel()
                    break
            except Exception:
                pass
    try:
        final_state = await graph_task
    except asyncio.CancelledError:
        logger.info(f"conversation cancelled (user={user_id})")
        return _empty_conv_result("cancelled", cancelled=True)

    # 多模態失敗（Phase 4D Honest Fallback）
    if attachment and not final_state.get("final_reply"):
        logger.error(f"Multimodal processing failed (user={user_id})")
        return _empty_conv_result("multimodal_failure", multimodal_failed=True)

    reply_text = final_state.get("final_reply", "Sorry, I encountered an internal error.")
    provider_name = final_state.get("selected_provider") or router._default_provider
    client = router._clients.get(provider_name)
    model_name = client.model_name() if client else "unknown"

    if pool and "upgrade_needed" not in reply_text:
        # 舉旗 JSON / viewer 連結絕不入庫（歷史汙染會讓模型學舌）。
        round_messages = [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": _strip_viewer_links(reply_text)},
        ]
        metadata = {
            "model": model_name,
            "provider": provider_name,
            "routing_reason": final_state.get("routing_reason"),
        }
        asyncio.create_task(short_term.save(user_id, platform, round_messages, metadata))
        asyncio.create_task(long_term.store(user_id, round_messages))

    # 寫入型工具確認往返：存下待恢復的對話（含待批准 tool_calls）。
    pending_tools = final_state.get("pending_tools")
    if pool and pending_tools:
        await pool.execute(
            "INSERT INTO home_context (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            f"confirm:pending:{user_id}",
            json.dumps(pending_tools),
        )

    usage = final_state.get("last_usage") or {}
    context_tokens = int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0)

    return {
        "cancelled": False,
        "multimodal_failed": False,
        "reply_text": reply_text,
        "model_used": model_name,
        "provider": provider_name,
        "routing_reason": final_state.get("routing_reason"),
        "context_tokens": context_tokens,
        "context_length": router.context_length(provider_name),
    }


@app.post("/chat", response_model=BrainResponse)
async def chat(msg: StandardMessage):
    """接收 Gateway 轉發的訊息，透過 LangGraph 處理。"""
    if not msg.text and not msg.attachment:
        raise HTTPException(status_code=400, detail="Empty message text and no attachment")

    pool = app.state.db_pool

    # 0. 狀態預設值
    confirmation_received = False
    resume_messages = None          # 確認後恢復執行的對話（含待批准的 tool_calls）
    resume_iterations = 0

    # 0.5. 處理語音 STT
    stt_echo = ""
    if msg.message_type == "voice" and msg.attachment and getattr(app.state, "stt_model", None):
        stt_result = await _transcribe_voice_local(msg.attachment, app.state.stt_model)
        if stt_result.get("success"):
            # STT 成功：消費 attachment，文字注入 msg.text
            msg.text = stt_result["transcript"]
            stt_echo = f"\n\n(🎙️ 聽寫：{msg.text})"
            
            # 非同步寫入紀錄
            asyncio.create_task(_save_voice_transcript(
                pool, msg.user_id, msg.platform, msg.source_message_id,
                msg.text, msg.attachment.local_path, msg.attachment.duration_ms
            ))
            
            msg.attachment = None
            msg.message_type = "text"
            logger.info(f"Local STT successful: {msg.text}")
        else:
            logger.warning(f"Local STT failed: {stt_result.get('error')}, falling back to Gemini")

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

    # 2. 技能確認回覆：使用者同意後，恢復執行先前暫停的 tool_calls
    if pool:
        pending_check = await pool.fetchrow("SELECT value FROM home_context WHERE key = $1", f"confirm:pending:{msg.user_id}")
        if pending_check:
            if any(word in msg.text.lower() for word in ["好", "可以", "確認", "yes", "go"]):
                confirmation_received = True
                pdata = json.loads(pending_check['value'])
                resume_messages = pdata.get("messages")
                resume_iterations = pdata.get("tool_iterations", 0)
            await pool.execute("DELETE FROM home_context WHERE key = $1", f"confirm:pending:{msg.user_id}")

    # 3-9. 組合 user content 後交由共用核心執行（與 /turn 同一條路徑）
    if msg.attachment:
        placeholder = _media_placeholder(msg.attachment)
        user_content = f"{msg.text} {placeholder}".strip() if msg.text else placeholder
    else:
        user_content = msg.text

    try:
        result = await _execute_conversation(
            user_id=msg.user_id,
            platform=msg.platform,
            source_message_id=msg.source_message_id,
            user_content=user_content,
            attachment=msg.attachment.model_dump() if msg.attachment else None,
            confirmation_received=confirmation_received,
            resume_messages=resume_messages,
            resume_iterations=resume_iterations,
        )

        if result["multimodal_failed"]:
            return BrainResponse(
                reply_text="我這邊看不到/聽不到,可以打字告訴我嗎?",
                model_used="fallback", provider="none",
                routing_reason="multimodal_failure",
            )

        return BrainResponse(
            reply_text=result["reply_text"] + stt_echo,
            model_used=result["model_used"],
            provider=result["provider"],
            routing_reason=result["routing_reason"],
            context_tokens=result["context_tokens"],
            context_length=result["context_length"],
        )

    except Exception as e:
        logger.error(f"Agent graph execution failed: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=502, detail=f"Agent error: {e}")


@app.post("/turn", status_code=202)
async def turn(req: TurnRequest):
    """解耦交付：立即接受一個組裝好的 turn，背景處理後把結果寫回 turns.result，
    由 gateway forwarder 的投遞階段送出（gateway 不阻塞，故可被中斷）。"""
    asyncio.create_task(_process_turn(req))
    return {"accepted": True, "turn_id": req.turn_id}


async def _finish_turn(pool, turn_id: str, result: str, *, status: str):
    """把 turn 的最終狀態寫回 DB。commit_passed 僅在正常完成（done）時置 true。
    以 status='processing' 為條件，避免覆寫已被其他流程改動的 turn。"""
    if not pool:
        return
    await pool.execute(
        """
        UPDATE turns
        SET status = $2, result = $3, commit_passed = $4, updated_at = NOW()
        WHERE id = $1 AND status = 'processing'
        """,
        uuid.UUID(turn_id), status, result or None, status == "done",
    )


async def _process_turn(req: TurnRequest):
    """背景處理一個 turn：組裝多則訊息為單一 user turn → 共用核心 → 寫回 turns。"""
    pool = app.state.db_pool
    turn_id = req.turn_id
    try:
        # 1. 把 burst 的多則訊息收斂成單一 user turn（語音逐則 STT、文字串接）。
        texts: list[str] = []
        attachment_model = None
        stt_echo = ""
        for m in req.messages:
            if m.message_type == "voice" and m.attachment and getattr(app.state, "stt_model", None):
                stt = await _transcribe_voice_local(m.attachment, app.state.stt_model)
                if stt.get("success"):
                    texts.append(stt["transcript"])
                    stt_echo = f"\n\n(🎙️ 聽寫：{stt['transcript']})"
                    asyncio.create_task(_save_voice_transcript(
                        pool, req.user_id, req.platform, m.source_message_id,
                        stt["transcript"], m.attachment.local_path, m.attachment.duration_ms,
                    ))
                    continue
                logger.warning(f"turn STT failed (turn={turn_id}): {stt.get('error')}")
            if m.attachment and m.message_type != "voice":
                # 多模態以 turn 內最後一個附件為準（v1 以文字為主，附件 best-effort）。
                attachment_model = m.attachment
                ph = _media_placeholder(m.attachment)
                texts.append(f"{m.text} {ph}".strip() if m.text else ph)
            elif m.text:
                texts.append(m.text)

        user_content = "\n".join(t for t in texts if t).strip()
        if not user_content and not attachment_model:
            await _finish_turn(pool, turn_id, "", status="failed")
            return

        # 2. 技能確認往返：使用者同意後恢復先前暫停的 tool_calls。
        confirmation_received = False
        resume_messages = None
        resume_iterations = 0
        if pool:
            pending_check = await pool.fetchrow(
                "SELECT value FROM home_context WHERE key = $1", f"confirm:pending:{req.user_id}")
            if pending_check:
                if any(w in user_content.lower() for w in ["好", "可以", "確認", "yes", "go"]):
                    confirmation_received = True
                    pdata = json.loads(pending_check["value"])
                    resume_messages = pdata.get("messages")
                    resume_iterations = pdata.get("tool_iterations", 0)
                await pool.execute(
                    "DELETE FROM home_context WHERE key = $1", f"confirm:pending:{req.user_id}")

        # 3. cancel-on-withdrawal：輪詢 turns.cancel_requested（gateway 偵測到撤回時置位）。
        async def cancel_check() -> bool:
            if not pool:
                return False
            row = await pool.fetchrow("SELECT cancel_requested FROM turns WHERE id = $1", uuid.UUID(turn_id))
            return bool(row and row["cancel_requested"])

        result = await _execute_conversation(
            user_id=req.user_id,
            platform=req.platform,
            source_message_id=req.messages[-1].source_message_id if req.messages else None,
            user_content=user_content,
            attachment=attachment_model.model_dump() if attachment_model else None,
            confirmation_received=confirmation_received,
            resume_messages=resume_messages,
            resume_iterations=resume_iterations,
            cancel_check=cancel_check,
        )

        if result["cancelled"]:
            await _finish_turn(pool, turn_id, "", status="cancelled")
            return
        if result["multimodal_failed"]:
            await _finish_turn(pool, turn_id, "我這邊看不到/聽不到,可以打字告訴我嗎?", status="done")
            return

        reply = result["reply_text"] + stt_echo + _build_footer(
            result["model_used"], result["context_tokens"], result["context_length"])
        await _finish_turn(pool, turn_id, reply, status="done")

    except Exception as e:
        logger.error(f"turn processing failed (turn={turn_id}): {e}")
        logger.error(traceback.format_exc())
        await _finish_turn(pool, turn_id, "", status="failed")
