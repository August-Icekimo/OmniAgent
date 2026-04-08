# Jules Task: Omni-Agent Phase 2 — 架構重構 + Brain 骨架實作

## 背景

Omni-Agent 是一個部署於 HomeLab 的家庭多模態 AI 助理。Phase 1（Go Gateway + PostgreSQL）已完成並通過驗收。現在要進行 Phase 2，但架構有一個重大變更：**棄用 LiteLLM 獨立容器，改為在 Brain 層內建原廠 SDK 直連**。

原因：只使用 3 家 LLM provider（Claude、Gemini、本地 MLX），用原廠 SDK 可以善用 **Claude Prompt Caching** 和 **Gemini Context Caching** 大幅降低成本。

## 本 PR 要完成的事項

這個 PR 有 **兩大任務**：

1. **架構文件更新**：更新 `CLAUDE.md` 反映新架構（四層→三層），刪除 `router/` 目錄
2. **Brain 骨架實作**：建立 `brain/llm/` 模組 + FastAPI 入口 + SoulLoader 骨架

---

## 任務 1：架構文件更新

### 1.1 更新 `omni-agent/CLAUDE.md`

#### §1 架構圖（第 20-57 行）

將四層架構改為三層。刪除 "The Router — LiteLLM" 那整個方塊，把路由功能合併進 "The Brain" 方塊：

**新架構圖：**
```
外部世界
  │  LINE Webhook / BlueBubbles (iMessage)
  ▼
┌─────────────────────────────────────────┐
│  The Senses — Go API Gateway            │
│  · 接收並驗證 Webhook 簽章              │
│  · 統一轉換為 StandardMessage{}         │
│  · 非同步回覆（應對 LINE 3 秒 timeout） │
│  · 內建 StressManager 小腦袋機制        │
└───────────────┬─────────────────────────┘
                │ HTTP (StandardMessage JSON)
                ▼
┌─────────────────────────────────────────┐
│  The Brain — Python FastAPI + LangGraph │
│  · 對話狀態管理（LangGraph stateful）   │
│  · SoulLoader：組裝 system prompt       │
│  · ModelRouter：原廠 SDK 智慧路由       │
│    ├─ Claude (anthropic SDK + cache)    │
│    ├─ Gemini (google-genai SDK + cache) │
│    └─ Local MLX (openai SDK → Mac Mini) │
│  · MCP Skills 呼叫                      │
│  · RAG 記憶檢索（pgvector）             │
└───────────────┬─────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│  The Hippocampus — PostgreSQL（唯一 DB） │
│  · pgvector：長期語意記憶               │
│  · SKIP LOCKED：Message Queue           │
│  · LISTEN/NOTIFY：即時推送              │
│  · JSONB：家庭資料、設備狀態            │
│  · stress_logs：小腦袋日記              │
└─────────────────────────────────────────┘
```

同時刪除架構圖下方 Brain 和 Router 之間的 `│ OpenAI-format API` 那行連接線（因為不再有獨立的 Router 層）。

#### §2.3 小腦袋策略 B（第 134 行附近）

將「透過 LiteLLM 切換更強模型」改為：
```
透過 ModelRouter 切換更強模型
```

#### §4 目錄結構（第 208-260 行）

替換為以下新結構（刪除 `router/`，新增 `brain/llm/`，刪除 `brain/agent/router.py`）：

```
omni-agent/
├── compose.yml                   # Podman-compatible
├── .env.example
├── SOUL.md                       # 人格核心（git 管理，Markdown）
├── CLAUDE.md                     # 本文件
│
├── gateway/                      # The Senses (Go) — Phase 1 ✅
│   ├── Dockerfile
│   ├── cmd/server/main.go
│   └── internal/
│       ├── handler/
│       │   ├── line.go
│       │   └── bluebubbles.go
│       ├── model/
│       │   └── standard_message.go
│       ├── stress/
│       │   └── manager.go        # 小腦袋機制
│       ├── queue/
│       │   └── queue.go
│       └── forwarder/
│           └── brain.go
│
├── brain/                        # The Brain (Python)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── agent/
│   │   ├── graph.py              # LangGraph state machine
│   │   └── prompts/
│   │       ├── system.py
│   │       └── tools.py
│   ├── llm/                      # ModelRouter + 原廠 SDK
│   │   ├── __init__.py
│   │   ├── base.py               # ModelClient ABC
│   │   ├── claude_client.py      # anthropic SDK + prompt caching
│   │   ├── gemini_client.py      # google-genai SDK + context caching
│   │   ├── local_client.py       # openai SDK → Mac Mini MLX
│   │   └── router.py             # 路由決策 + 模型升級策略
│   ├── memory/
│   │   ├── short_term.py         # conversations table
│   │   └── long_term.py          # pgvector RAG
│   ├── skills/                   # MCP Tools
│   │   ├── proxmox.py
│   │   ├── wake_on_lan.py
│   │   └── home_assistant.py
│   └── soul/
│       ├── loader.py             # SOUL.md + DB → Markdown prompt
│       └── templates/
│           └── context.md.jinja
│
└── docs/
    ├── architecture.md
    └── SECURITY.md
```

#### §5 Phase 表（第 264-272 行）

替換為：

```markdown
| Phase | 目標 | 關鍵產出 |
|---|---|---|
| **1** ✅ | Go Gateway + Queue | `StandardMessage{}`, Webhook 驗證, `StressManager` 骨架, PG Queue |
| **2** | Python Brain + 原廠 SDK | FastAPI 端點, LangGraph 基礎, `SoulLoader`, `ModelClient` ABC + Claude/Gemini/Local adapter, prompt/context caching |
| **3** | 記憶系統 | conversations table, pgvector RAG, `StressManager` 寫日記 |
| **4** | MCP Skills + 模型升級 | Function Calling, Proxmox/WoL 工具, `ModelRouter` 完整 escalation 實作 |
```

### 1.2 刪除 `omni-agent/router/` 目錄

刪除以下檔案：
- `omni-agent/router/config.yaml`
- `omni-agent/router/Dockerfile`

刪除 `omni-agent/router/` 目錄本身。

### 1.3 刪除 `omni-agent/brain/agent/router.py`

此空檔的職責已移至 `brain/llm/router.py`，刪除。

---

## 任務 2：Brain 骨架實作

### 2.1 建立 `omni-agent/brain/llm/base.py`

```python
"""ModelClient ABC — 統一所有 LLM provider 的介面。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Message:
    role: Role
    content: str
    # 未來擴充 multimodal 時可加 images: list[bytes] 等欄位


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    usage: dict = field(default_factory=dict)
    # usage 範例: {"input_tokens": 100, "output_tokens": 50, "cache_read_tokens": 80}
    cached: bool = False


class ModelClient(ABC):
    """所有 LLM provider 的抽象基底類別。"""

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """發送對話請求，回傳 LLM 回應。"""
        ...

    @abstractmethod
    def provider_name(self) -> str:
        """回傳 provider 名稱，如 'claude', 'gemini', 'local'。"""
        ...

    @abstractmethod
    def model_name(self) -> str:
        """回傳目前使用的模型名稱。"""
        ...

    @abstractmethod
    async def supports_vision(self) -> bool:
        """此 provider 是否支援圖片輸入。"""
        ...
```

### 2.2 建立 `omni-agent/brain/llm/claude_client.py`

使用 `anthropic` 官方 SDK。重點：**啟用 Prompt Caching**。

```python
"""Claude provider — 使用 anthropic 官方 SDK，啟用 Prompt Caching。"""

import os
import anthropic
from .base import ModelClient, Message, LLMResponse, Role


class ClaudeClient(ModelClient):
    """Anthropic Claude 客戶端，支援 prompt caching。"""

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self._client = anthropic.AsyncAnthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
        )
        self._model = model

    async def chat(
        self,
        messages: list[Message],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        kwargs: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": m.role.value, "content": m.content}
                for m in messages
                if m.role != Role.SYSTEM
            ],
        }

        # Prompt Caching：將 system prompt 標記為可快取
        # 這會讓 Anthropic 在伺服器端快取此段 prompt，後續請求直接命中
        # 對於每次都注入的 SOUL.md 來說，cache hit rate 會非常高
        if system_prompt:
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        response = await self._client.messages.create(**kwargs)

        usage = {}
        if response.usage:
            usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
            # cache 相關 usage 欄位（如果有的話）
            if hasattr(response.usage, "cache_creation_input_tokens"):
                usage["cache_creation_tokens"] = response.usage.cache_creation_input_tokens
            if hasattr(response.usage, "cache_read_input_tokens"):
                usage["cache_read_tokens"] = response.usage.cache_read_input_tokens

        cached = usage.get("cache_read_tokens", 0) > 0

        return LLMResponse(
            content=response.content[0].text,
            model=self._model,
            provider="claude",
            usage=usage,
            cached=cached,
        )

    def provider_name(self) -> str:
        return "claude"

    def model_name(self) -> str:
        return self._model

    async def supports_vision(self) -> bool:
        return True
```

### 2.3 建立 `omni-agent/brain/llm/gemini_client.py`

使用新版 `google-genai` SDK。重點：**Context Caching**。

```python
"""Gemini provider — 使用 google-genai SDK，啟用 Context Caching。"""

import os
from google import genai
from google.genai import types
from .base import ModelClient, Message, LLMResponse, Role


class GeminiClient(ModelClient):
    """Google Gemini 客戶端，支援 context caching。"""

    def __init__(self, model: str = "gemini-2.5-flash"):
        self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self._model = model
        self._cached_content = None  # 快取 SOUL.md system prompt 用

    async def _get_or_create_cache(self, system_prompt: str) -> types.CachedContent | None:
        """建立或復用 Gemini Context Cache。
        
        Context Caching 可將大段 system prompt 快取在 Google 伺服器端，
        後續請求引用此 cache 即可，大幅降低 token 計費。
        """
        if self._cached_content is not None:
            # 檢查 cache 是否已過期
            try:
                # 嘗試取得 cache 狀態，若已過期會拋例外
                return self._cached_content
            except Exception:
                self._cached_content = None

        # 建立新 cache（最小 cache 需要 >= 4096 tokens 的內容）
        if len(system_prompt) < 2000:
            # system prompt 太短，不值得 cache
            return None

        try:
            cached = self._client.caches.create(
                model=self._model,
                config=types.CreateCachedContentConfig(
                    system_instruction=system_prompt,
                    ttl="3600s",  # 1 小時 TTL
                ),
            )
            self._cached_content = cached
            return cached
        except Exception:
            # Cache 建立失敗不影響正常運作，fallback 為不使用 cache
            return None

    async def chat(
        self,
        messages: list[Message],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        contents = []
        for m in messages:
            if m.role == Role.SYSTEM:
                continue
            role = "user" if m.role == Role.USER else "model"
            contents.append(types.Content(role=role, parts=[types.Part(text=m.content)]))

        generate_config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        # 嘗試使用 context cache
        cached_content = None
        if system_prompt:
            cached_content = await self._get_or_create_cache(system_prompt)

        if cached_content:
            # 透過 cached_content 呼叫，不需再送 system_instruction
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    cached_content=cached_content.name,
                ),
            )
        else:
            # 無 cache，直接帶 system_instruction
            if system_prompt:
                generate_config.system_instruction = system_prompt
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=generate_config,
            )

        usage = {}
        if response.usage_metadata:
            usage = {
                "input_tokens": response.usage_metadata.prompt_token_count,
                "output_tokens": response.usage_metadata.candidates_token_count,
            }
            if hasattr(response.usage_metadata, "cached_content_token_count"):
                usage["cache_read_tokens"] = response.usage_metadata.cached_content_token_count

        return LLMResponse(
            content=response.text,
            model=self._model,
            provider="gemini",
            usage=usage,
            cached=cached_content is not None,
        )

    def provider_name(self) -> str:
        return "gemini"

    def model_name(self) -> str:
        return self._model

    async def supports_vision(self) -> bool:
        return True
```

### 2.4 建立 `omni-agent/brain/llm/local_client.py`

使用 `openai` SDK 指向 Mac Mini 上的 `mlx-lm` OpenAI-compatible server。

```python
"""Local MLX provider — 使用 openai SDK 連接 Mac Mini mlx-lm server。"""

import os
from openai import AsyncOpenAI
from .base import ModelClient, Message, LLMResponse


class LocalClient(ModelClient):
    """本地 MLX 客戶端，透過 OpenAI-compatible API 連接 Mac Mini。"""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
    ):
        self._base_url = base_url or os.environ.get(
            "MLX_BASE_URL", "http://mac-mini.local:8086/v1"
        )
        self._model = model or os.environ.get("MLX_MODEL", "mlx-community/Meta-Llama-3.1-8B-Instruct-4bit")
        self._client = AsyncOpenAI(
            base_url=self._base_url,
            api_key="not-needed",  # mlx-lm 不需要 API key
        )

    async def chat(
        self,
        messages: list[Message],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        oai_messages = []
        if system_prompt:
            oai_messages.append({"role": "system", "content": system_prompt})
        for m in messages:
            oai_messages.append({"role": m.role.value, "content": m.content})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=oai_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        choice = response.choices[0]
        usage = {}
        if response.usage:
            usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }

        return LLMResponse(
            content=choice.message.content or "",
            model=self._model,
            provider="local",
            usage=usage,
            cached=False,  # 本地模型無 cache 機制
        )

    def provider_name(self) -> str:
        return "local"

    def model_name(self) -> str:
        return self._model

    async def supports_vision(self) -> bool:
        return False  # mlx-lm 目前不支援 vision
```

### 2.5 建立 `omni-agent/brain/llm/router.py`

```python
"""ModelRouter — 路由決策 + 小腦袋模型升級策略。

路由邏輯：
- 預設使用 Claude（主力模型，語感最佳）
- 視覺/multimodal 任務 → Gemini（成本較低）
- 簡單日常任務（查詢、翻譯等） → Local MLX（零成本）
- 過載升級時 → 切換至更強模型（如 Claude Opus）

Phase 2 先實作基本路由（固定 Claude），
Phase 4 再加入完整的動態升級策略。
"""

import logging
from .base import ModelClient, Message, LLMResponse
from .claude_client import ClaudeClient
from .gemini_client import GeminiClient
from .local_client import LocalClient

logger = logging.getLogger(__name__)


class ModelRouter:
    """管理多個 LLM provider，決定每次請求要用哪一個。"""

    def __init__(self):
        self._clients: dict[str, ModelClient] = {}
        self._default_provider: str = "claude"

    def register(self, client: ModelClient) -> None:
        """註冊一個 provider。"""
        self._clients[client.provider_name()] = client
        logger.info(
            "Registered LLM provider: %s (%s)",
            client.provider_name(),
            client.model_name(),
        )

    def set_default(self, provider: str) -> None:
        """設定預設 provider。"""
        if provider not in self._clients:
            raise ValueError(f"Unknown provider: {provider}")
        self._default_provider = provider

    async def chat(
        self,
        messages: list[Message],
        *,
        system_prompt: str | None = None,
        provider: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """路由請求到適當的 provider。
        
        Args:
            messages: 對話訊息列表
            system_prompt: system prompt（會利用 provider 的 cache 機制）
            provider: 指定 provider，None 則使用預設
            temperature: 溫度參數
            max_tokens: 最大回覆 token 數
        """
        target = provider or self._default_provider
        client = self._clients.get(target)

        if client is None:
            # fallback 到任何可用的 provider
            if self._clients:
                target = next(iter(self._clients))
                client = self._clients[target]
                logger.warning(
                    "Provider '%s' not available, falling back to '%s'",
                    provider,
                    target,
                )
            else:
                raise RuntimeError("No LLM providers registered")

        logger.info("Routing to provider: %s (%s)", target, client.model_name())

        response = await client.chat(
            messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # Log cache 命中狀態（成本監控用）
        if response.cached:
            logger.info(
                "Cache HIT on %s — saved tokens: %s",
                target,
                response.usage.get("cache_read_tokens", "unknown"),
            )

        return response


def create_default_router() -> ModelRouter:
    """建立預設 router，自動偵測可用的 provider。
    
    根據環境變數判斷哪些 provider 可用：
    - ANTHROPIC_API_KEY → Claude
    - GEMINI_API_KEY → Gemini
    - MLX_BASE_URL → Local MLX
    """
    import os

    router = ModelRouter()

    if os.environ.get("ANTHROPIC_API_KEY"):
        router.register(ClaudeClient())
        router.set_default("claude")
        logger.info("Claude provider enabled (default)")

    if os.environ.get("GEMINI_API_KEY"):
        router.register(GeminiClient())
        logger.info("Gemini provider enabled")

    if os.environ.get("MLX_BASE_URL"):
        router.register(LocalClient())
        logger.info("Local MLX provider enabled")

    if not router._clients:
        logger.warning("No LLM providers configured! Set API keys in .env")

    return router
```

### 2.6 建立 `omni-agent/brain/llm/__init__.py`

```python
"""LLM module — 原廠 SDK 直連，取代 LiteLLM。"""

from .base import ModelClient, Message, LLMResponse, Role
from .router import ModelRouter, create_default_router

__all__ = [
    "ModelClient",
    "Message",
    "LLMResponse",
    "Role",
    "ModelRouter",
    "create_default_router",
]
```

### 2.7 更新 `omni-agent/brain/main.py`

替換現有空檔，寫入 FastAPI 基本骨架：

```python
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
```

### 2.8 更新 `omni-agent/brain/requirements.txt`

替換現有空檔：

```
# FastAPI + ASGI server
fastapi>=0.115.0
uvicorn[standard]>=0.34.0

# LLM SDKs — 原廠直連
anthropic>=0.52.0
google-genai>=1.12.0
openai>=1.78.0

# Database (Phase 3 預備)
asyncpg>=0.30.0
pgvector>=0.3.0

# Template rendering for SoulLoader
jinja2>=3.1.6

# LangGraph (Phase 2 後半)
langgraph>=0.4.0

# Utilities
pydantic>=2.11.0
python-dotenv>=1.1.0
```

### 2.9 更新 `omni-agent/brain/Dockerfile`

替換現有空檔：

```dockerfile
FROM python:3.13-slim

WORKDIR /app

# 安裝系統依賴（asyncpg 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 2.10 更新 `omni-agent/compose.yml`

在現有的 `gateway` service 之後，加入 `brain` service。注意不要修改已有的 `postgres` 和 `gateway` 定義。

追加的 brain service：

```yaml
  brain:
    build:
      context: ./brain
    container_name: omni-agent-brain-1
    env_file:
      - .env
    ports:
      - "${BRAIN_PORT:-8000}:8000"
    depends_on:
      postgres:
        condition: service_started
    restart: unless-stopped
```

同時刪除 `version: '3.8'` 那行（已 deprecated）。

---

## 不要修改的檔案

以下已完成的 Phase 1 檔案**不可修改**：

- `gateway/` 目錄下的所有檔案
- `db/migrations/001_init.sql`
- `SOUL.md`
- `docs/test_phase1-gateway.md`
- `docs/test_phase1_walkthrough.md`
- `.gitignore`

## 不要修改的空檔（Phase 3/4 使用）

以下空檔保持不動：

- `brain/agent/graph.py`
- `brain/agent/prompts/system.py`
- `brain/agent/prompts/tools.py`
- `brain/memory/short_term.py`
- `brain/memory/long_term.py`
- `brain/skills/*.py`
- `brain/soul/loader.py`
- `brain/soul/templates/context.md.jinja`

---

## 驗收標準

1. **CLAUDE.md** 架構圖為三層（無 LiteLLM），目錄結構含 `brain/llm/` 而非 `router/`
2. **`router/` 目錄已刪除**
3. **`brain/agent/router.py` 已刪除**
4. **`brain/llm/`** 包含 6 個檔案：`__init__.py`, `base.py`, `claude_client.py`, `gemini_client.py`, `local_client.py`, `router.py`
5. **`brain/main.py`** 是可執行的 FastAPI app（`uvicorn main:app` 能啟動）
6. **`brain/requirements.txt`** 包含 `anthropic`, `google-genai`, `openai`, `fastapi`, `uvicorn`
7. **`brain/Dockerfile`** 能 build 成功
8. **`compose.yml`** 包含 `brain` service，不含 `litellm` 或 `router` service
9. **所有 Phase 1 檔案未被修改**

## Commit Message 建議

```
feat(brain): Phase 2 架構重構 — 棄 LiteLLM，改用原廠 SDK 直連

- 更新 CLAUDE.md：四層架構 → 三層架構
- 刪除 router/ 目錄（不再使用 LiteLLM 獨立容器）
- 新增 brain/llm/ 模組：
  - ModelClient ABC 統一介面
  - ClaudeClient: anthropic SDK + prompt caching
  - GeminiClient: google-genai SDK + context caching  
  - LocalClient: openai SDK → Mac Mini MLX
  - ModelRouter: 路由決策 + provider fallback
- 實作 Brain FastAPI 骨架（/health, /chat endpoints）
- 更新 compose.yml 加入 brain service

BREAKING CHANGE: 移除 LiteLLM 依賴，改用原廠 SDK
```
