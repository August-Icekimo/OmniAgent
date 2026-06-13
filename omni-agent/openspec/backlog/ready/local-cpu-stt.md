---
slug: local-cpu-stt
status: ready
domain: brain
size: M
priority: P1
created: 2026-06-13
---

# Local CPU STT — 語音訊息在 Katharine 本地轉錄

## Why

目前語音訊息（Telegram voice note / LINE 語音）全程靠 Gemini 雲端處理：整段
audio bytes base64 上傳後由 Gemini 同時轉錄+回應。這帶來三個痛點：

1. **費用**：audio token 比純文字貴很多，每則語音都消耗 Gemini quota
2. **延遲**：音訊 bytes 要從 katharine 上傳到 Google Cloud 再等回應
3. **運算集中**：所有語音運算都壓在雲端，katharine 的 CPU (5825U 8C/16T) 閒置

家人日常使用語音輸入的頻率預計達 70–100 次/天，累積的 audio token 費用可觀。

## What (high-level)

在 brain 服務的 `/chat` endpoint（LangGraph 之前）加入本地 CPU STT 前處理：
- 收到 `message_type: "voice"` 時，用 `faster-whisper` (small 模型) 在 katharine
  CPU 上轉錄為文字。**模型需在 lifespan 啟動時預先載入常駐記憶體**，避免首次延遲。
- 轉錄成功後，文字注入 `msg.text`，消費掉 attachment，讓 planner_node 當作一般
  打字訊息處理（走現有 ModelRouter 路由規則）
- **回顯機制**：轉錄成功後，在回覆訊息中自動包含 🎙️ 符號或將轉錄內容 echo，讓使用者知道聽到了什麼
- 轉錄失敗時 fallback 回現有 Gemini audio 路徑（`_analyze_voice()`）
- 繁體中文為主要語言，透過 `initial_prompt` 引導 Whisper 輸出繁體

## Acceptance hints

- 收到 Telegram voice note 時，brain log 顯示 `provider: local` 轉錄成功
- 轉錄後的文字走 planner_node 一般路由，回覆品質與打字輸入一致
- 系統在 lifespan 啟動時載入 faster-whisper small 模型，沒有首次語音延遲
- `voice_transcripts` 表紀錄 transcript + provider
- 本地 STT 失敗（模型未載入、ffmpeg 缺失等）自動 fallback 至 Gemini audio
- 繁體中文語音（10 秒）在 5825U 上 ≤10 秒完成轉錄
- brain container 重建後模型快取不丟失（volume 持久化）
- 系統會向使用者回顯 (echo) 轉錄的文字，確保體驗

## Open questions

- (None)

## Links

- Roadmap: openspec/backlog/ROADMAP.md#2026-q2q3-bridge--phase-55-skills-expansion--per-member-skill-acl
- Related spec: openspec/specs/brain/spec.md
- Related spec: openspec/specs/skills/spec.md
- Evaluation: (Antigravity conversation f4915b2e — stt-on-katharine-evaluation.md)
