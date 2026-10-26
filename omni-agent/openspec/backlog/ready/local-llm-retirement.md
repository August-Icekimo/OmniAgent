---
slug: local-llm-retirement
status: ready
domain: llm
size: M
priority: P1
created: 2026-10-26
---

# Local LLM（rapid-mlx Gemma）降級為萬不得已，觀察後退役

## Why
local Gemma 雖省錢，但實用性不足、交辦不了重大任務，結果 admin 反而繞過 Cindy
直接用原生 Claude / AGY — 預設模型讓人不想用 Cindy，失去家庭助理的意義。
省錢理由在實驗室用量下也不成立（雲端估 US$1–7/月），維護成本卻持續累積：
升級必壞（Pillow / mlx-vlm）、prefill cap 8192（9.5k 整台崩）、abort 假確認、
prompt cache 關閉、thought-marker 殘留 workaround、chrysoberyl 常離線。
隱私分流已確認**不是**剛性需求（2026-10-26 admin 確認）。

更急的是可用性：`routing_config.json` 5 條 routing_rules **全部導 local**，
local 離線時連線卡滿 timeout 才 fallback（實測 `ConnectTimeout` 130s；
local_client timeout 120s × openai SDK 預設重試 2 次 ≈ 360s > `TURN_PROCESSING_TIMEOUT`
300s）→ 推論 chrysoberyl 離線期間 turn 會在 fallback 前逾時、Cindy 不回話。
（code 推導 + 單次連線實測，尚未以真實 turn 端到端驗證。）

## What (high-level)
分三階段，前段可隨時回退：

1. **降級（改設定，不刪程式碼）**
   - provider 定位（2026-10-26 grooming 定案）：**Gemini 主力（文字＋多模態）、
     Claude 備援**；fallback_chain 改 `["gemini", "claude"]`，移除 local。
   - routing_rules 改導 gemini（或刪除改由 default 承接）。
   - 前置：admin 已於 2026-10-26 儲值 US$5（測試用，auto-reload 未確認），
     Gemini 恢復；單輪 tool_call 實測 OK，多輪 functionResponse 回填迴圈仍待驗證。
2. **觀察 2–4 週**：Gemini 主力的品質、延遲、成本；local 未被需要。
   同期評估 **ChatGPT Plus「Sign in with ChatGPT」** 是否值得接入（見下方 Context）。
   觀察期結束時決定：Gemini 長期保留與否、是否另開 ChatGPT 接入 change。
3. **退役**：移除 local provider 與周邊，同步 spec 與文件（清單見 Context）。

設計原則（grooming 定案）：**第一線模型本身具視覺能力時，不再設「第二模型轉譯／
升級保底」**。Gemma 專屬的貼圖／圖片升級路徑與首行搶救邏輯於退役時整段移除
（連帶消除 `_perceive_image` 升級時誤送文字而非圖片的既有 bug，file_analyzer.py:245/265）。

範圍外：
- brain 行程內 faster-whisper 本地 STT 保留（與 MLX 無關）。
- Claude 圖片支援 → 另卡 `claude-vision-support`。

## Acceptance hints
- **階段 1**
  - 先以一則真實 turn 驗證「local 離線 → turn 逾時不回話」推論（gateway + brain log），
    記錄結果（同時釐清 9/15 後無對話的原因）
  - Gemini tool calling smoke：function_call 觸發（✅ 10-26 單輪）+ functionResponse 回填，多輪迴圈可完成
  - 改設定後 chrysoberyl 離線時，文字／圖片／貼圖 turn 皆在正常延遲內由 Gemini 回覆
  - 正常路徑不觸發 fallback：回覆、長期記憶摘要、PDF 摘要不再帶 `🤔` 前綴
  - Gemini 故障時文字 turn 由 Claude 接手；多模態誠實降級（Claude 尚無視覺）
- **階段 2**：觀察期結束有數據（turn 成功率、延遲、每月 Gemini／Claude 花費）
  與 ChatGPT Plus 評估結論，記錄於本 change
- **階段 3**
  - `grep -ri "mlx\|gemma\|LocalClient"` 只剩歷史文件／archive
  - llm spec「Local LLM Integration」以 delta REMOVED；`specs/local-thinking/` 整個移除
  - `omni-agent/CLAUDE.md` fallback chain 說明、`AGENT.md` 架構圖同步更新
  - `rapid-mlx` 指令依三方 parity 規則（`.agent/` `.gemini/` `.claude/`）同 commit 移除
  - `openai` 套件：若觀察期決定接 ChatGPT 則保留，否則自 requirements 移除
  - idea `local-prompt-cap-preflight`、`routing-long-output-detection` 轉 won't-do
  - 語音 STT 行為不變

## Open questions

## Links
- Related spec: openspec/specs/llm/spec.md（Requirement: Local LLM Integration）、
  openspec/specs/local-thinking/spec.md
- Related idea: claude-vision-support（Claude 視覺備援，另卡）
- Depends on: admin 於 AI Studio 儲值（✅ 2026-10-26 US$5；auto-reload 視觀察期用量決定）
- 退役後將失效的 idea：local-prompt-cap-preflight、routing-long-output-detection

## Context（grooming 調查記錄，2026-10-26）

**現況路由**
- 預設 provider = `fallback_chain[0]`（router.py:23）；未指定 provider 的呼叫
  （long_term 摘要、file_analyzer PDF 摘要／OCR 評估）走 gemini → 現 402 →
  fallback Claude 並加 `🤔` 前綴，前綴汙染摘要內容
- local 註冊只看 `MLX_BASE_URL`（router.py:353），`enabled` 欄位無作用（退役後無關，不修）
- Claude `supports_vision()` 回 False（claude_client.py:147）→ local 退役後僅 Gemini 可視覺
- Gemini tool 路徑未實機驗證（gemini_client.py:111）；Claude 單輪 tool_call 於
  2026-10-26 實測 OK

**退役移除清單**
brain/llm/local_client.py、router.py（import／註冊／預設鏈）、config/config_loader.py
預設、llm/preflight.py local 分支、skills/file_analyzer.py Gemma workaround 與升級路徑、
config/routing_config.json local 區塊、test_vision_local.py 與 test_router／
test_model_preflight／test_terminal／test_web_search 中的 local 參照、.env.example、
scripts/init-omni-agent.sh、AGENT.md、CLAUDE.md、.claude/commands/rapid-mlx.md（＋parity）、
brain/requirements.txt（openai 視觀察期結論）

**ChatGPT Plus 評估素材**（DevDay 2026-09-29「Sign in with ChatGPT」）
- 官方允許 open-source／locally hosted app 用方案額度，agent host 明列 self-hosted VM；
  OAuth PKCE → `POST /v1/responses`，須 `store:false`、`stream:true`，額度用罄串流中斷
  （`subscription_sharing_usage_limit_exceeded`）不自動轉付費
- 資格：quickstart 只點名 Plus／Pro；Go（$8）未確認、Codex 僅限桌面 app＋Luna → 不考慮
- Plus（$20）：GPT-6.1 Sol 15–160、GPT-6 Luna 350–3,000、Astra 5–45 次／5h（官方估計）＋週上限
- 模型皆 text+image 輸入、function calling（須 Responses API）、1.05M context；
  **無影片／音訊** → 影片仍需 Gemini
- 未確認：preview 是否拒 `temperature`／system role（第三方說法）、多人共用一訂閱的政策
- 實驗室用量下按量 API 比訂閱便宜；Cindy 出實驗室、用量上升後才划算
