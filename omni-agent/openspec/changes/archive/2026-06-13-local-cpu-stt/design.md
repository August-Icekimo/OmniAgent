# Local CPU STT — 語音訊息在 Katharine 本地轉錄

本計畫將實作 `local-cpu-stt` 功能，在 `brain` 服務中加入 `faster-whisper` 本地轉錄，降低延遲與 API 費用。

## User Review Required
> [!IMPORTANT]
> - **回顯機制 (Echo) 呈現方式**：計畫將在 `BrainResponse` 回傳給 Gateway 的 `reply_text` 尾部，自動附加上 `\n\n(🎙️ 語音辨識：{transcript})` 的後綴。這樣最為保險且不影響 LLM 的推論。請確認這個呈現方式是否滿意。
> - **模型下載時間**：第一次 `docker compose up -d` 啟動 `brain` 容器時，會在 lifespan hook 自動下載 ~462MB 的 model 檔案。啟動時間會稍微拉長約數十秒，之後會緩存在 volume 中。

## Open Questions
- 沒有任何未決的問題，依據先前的討論進行。

## Proposed Changes

### Docker & Infrastructure

#### [MODIFY] [compose.yml](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/compose.yml)
- 為 `brain` 服務加入一個 named volume `whisper-models:/root/.cache/huggingface`，確保容器重建時不需要重新下載模型。

#### [MODIFY] [brain/Dockerfile](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/brain/Dockerfile)
- 在 `apt-get install` 清單中加入 `ffmpeg`，提供 `faster-whisper` 解析各種語音格式（如 M4A, OGG）的底層依賴。

#### [MODIFY] [brain/requirements.txt](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/brain/requirements.txt)
- 新增 `faster-whisper>=1.0.0` 依賴。

---

### Brain Service Core

#### [MODIFY] [brain/main.py](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/brain/main.py)
- **Lifespan Hook (`lifespan`)**:
  - 啟動時匯入 `faster_whisper.WhisperModel`。
  - 實例化 `WhisperModel("small", device="cpu", compute_type="int8")` 並存放在 `app.state.stt_model`。
- **STT 輔助函式 (`_transcribe_voice_local`)**:
  - 接收 attachment 參數。
  - 使用 `app.state.stt_model.transcribe(..., language="zh", initial_prompt="以下是繁體中文語音訊息的逐字稿。")` 進行轉錄。
  - 處理成功與失敗的例外狀況。
- **Chat Endpoint (`chat`)**:
  - 在將訊息丟進 LangGraph 之前，檢查 `msg.message_type == "voice"` 且 `msg.attachment` 不為空。
  - 呼叫 `_transcribe_voice_local`。
  - **成功時**：
    - 將轉錄文字放入 `msg.text`。
    - 設 `msg.attachment = None`（防止 graph 進入 `file_analyze` 分支）。
    - 設 `msg.message_type = "text"`。
    - 記錄到 `voice_transcripts` DB 表。
    - 在最後從 Graph 取得 `reply_text` 後，於末端附加上 `\n\n(🎙️ 聽寫：{transcript})`，讓使用者知道 Cindy 聽到了什麼。
  - **失敗時**：
    - 記錄錯誤日誌。
    - 不改變 `msg.attachment` 與 `msg.message_type`，訊息會照舊流入 graph 的 `file_analyze` 路徑，觸發原有的 Gemini audio fallback。

## Verification Plan

### Manual Verification
1. 重建 `brain` 容器並檢查日誌，確認 `faster-whisper` 模型在啟動時成功載入。
2. 從 Telegram 傳送一段中文語音給 OmniAgent。
3. 觀察 `brain` 日誌，確認走 local STT 路徑，且成功轉錄。
4. 收到回覆時，確認回覆末端帶有 `(🎙️ 聽寫：...)` 的回顯。
5. 傳送一段純文字，確保不會觸發 STT 邏輯，功能正常。
6. 檢查 PostgreSQL 的 `voice_transcripts` 資料表，確認轉錄紀錄有被寫入，且 `provider` 欄位不為 `gemini`。
