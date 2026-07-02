"""AGY specialist agent 服務 — 把 ADK 2.0 摘要 agent 以 A2A protocol 暴露。

容器隔離為主要防線（沿用 sandbox 模式）：read_only 檔案系統、不掛 `.env`、
僅注入單一 `GEMINI_API_KEY`、資源上限、no-new-privileges、僅 compose 內網可達。

啟動流程：
  1. 正規化 auth env（GEMINI_API_KEY → GOOGLE_API_KEY，關閉 Vertex），缺 key 直接 fail-fast。
  2. 用 google-adk 原生 A2A 橋 to_a2a() 把摘要 agent 轉成 A2A Starlette app
     （自動掛 A2A JSONRPC 路由 + Agent Card well-known endpoint，card 由 agent 自動建構）。
  3. 額外掛一個 /health 路由供 compose/brain 探活。
"""

import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agy.server")

# --- 1. Auth env 正規化（須在 import google.adk / google.genai 前完成）---
# AGY 唯一的 secret：經 compose environment 注入（來源 host 的 AGY_GEMINI_API_KEY，
# 與 Cindy 日常 OAuth/GEMINI_API_KEY 計費分離，見提案 D3）。容器不掛 `.env`。
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
if not GEMINI_API_KEY:
    # fail-fast：缺 key 時清楚報錯，不靜默啟動成一個無法推論的殼。
    raise RuntimeError(
        "AGY 啟動失敗：缺少 GEMINI_API_KEY。容器需注入 AGY 專用 API Key "
        "（compose: GEMINI_API_KEY=${AGY_GEMINI_API_KEY}）。"
    )
# google-genai / ADK 以 API Key 模式運作（非 Vertex）。genai 認 GOOGLE_API_KEY。
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")
os.environ.setdefault("GOOGLE_API_KEY", GEMINI_API_KEY)

# --- 2. 建 A2A app（import 在 env 設定後）---
from google.adk.a2a.utils.agent_to_a2a import to_a2a  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

from agent import root_agent  # noqa: E402

AGY_PORT = int(os.getenv("AGY_PORT", "8000"))
# Agent Card 對外公告的 RPC host：須是 brain（A2A client）可達的位址。
# compose 內網用服務名 agy；ADK 用 host/port 組 card 的 RPC URL。
AGY_HOST = os.getenv("AGY_HOST", "agy")

# to_a2a 回傳一個 Starlette app（已掛 A2A JSONRPC 路由 + Agent Card 端點）。
# 不傳 agent_card → ADK 依 agent 的 name/description/skills 自動建構（含「長文摘要」描述）。
app = to_a2a(root_agent, host=AGY_HOST, port=AGY_PORT)


async def _health(request):
    # 永不回傳金鑰本身，只報布林狀態。
    return JSONResponse({"status": "ok", "service": "agy", "api_key_present": True})


app.add_route("/health", _health, methods=["GET"])

logger.info("AGY summarizer A2A server ready (host=%s port=%s model=%s)",
            AGY_HOST, AGY_PORT, os.getenv("AGY_MODEL", "gemini-2.5-flash"))
