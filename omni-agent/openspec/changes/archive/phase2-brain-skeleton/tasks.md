## 1. Architecture & Documentation

- [x] 1.1 更新 `omni-agent/CLAUDE.md`
  - [x] AC: 將四層架構改為三層，移除 Router 層。
- [x] 1.2 刪除 `omni-agent/router/` 目錄
  - [x] AC: 移除 LiteLLM 相關設定與 Dockerfile。

## 2. Brain Core Implementation

- [x] 2.1 建立 `brain/llm/base.py`
  - [x] AC: 定義 `ModelClient` ABC 與統一介面。
- [x] 2.2 建立 `brain/llm/claude_client.py`
  - [x] AC: 整合 `anthropic` SDK 並啟用 Prompt Caching。
- [x] 2.3 建立 `brain/llm/gemini_client.py`
  - [x] AC: 整合 `google-genai` SDK 並支援 Context Caching。
- [x] 2.4 建立 `brain/llm/local_client.py`
  - [x] AC: 透過 `openai` SDK 連接本地 MLX server。
- [x] 2.5 建立 `brain/llm/router.py`
  - [x] AC: 實作 `ModelRouter` 基礎路由邏輯。

## 3. Integration & API

- [x] 3.1 更新 `brain/main.py`
  - [x] AC: 實作 FastAPI 入口與 `/chat` 基礎端點。
- [x] 3.2 更新 `brain/requirements.txt`
  - [x] AC: 加入 `fastapi`, `anthropic`, `google-genai` 等依賴。
