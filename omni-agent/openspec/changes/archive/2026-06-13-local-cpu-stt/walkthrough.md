# Local CPU STT — 實作總結

我們已經成功將 OmniAgent 的語音轉錄流程由 Gemini 雲端端點移至 `katharine` 節點進行本機 CPU 處理！這將大幅節省語音處理的 Audio token 費用，並為日後的複雜語音應用打下基礎。

## 做了哪些改變？

### 1. 基礎架構升級 (Infrastructure)
- **相依性更新**：在 `brain/Dockerfile` 中補上了 `ffmpeg`，確保能解析來自 LINE 或 Telegram 各式各樣的錄音格式。同時在 `requirements.txt` 中加入了 `faster-whisper>=1.0.0`。
- **快取持久化**：為 `compose.yml` 中的 `brain` 服務加上了 `whisper-models` volume。確保第一次花時間下載的 462MB `small` 模型檔能夠在 Docker 容器重啟後被保留下來。

### 2. Brain 服務核心改造 (`main.py`)
- **啟動預載模型**：我們在 FastAPI 的 `lifespan` 裡匯入了 `faster_whisper.WhisperModel`，並強制綁定為 `device="cpu"` 以及 `compute_type="int8"`。如此一來，這個佔約 ~1GB RAM 的模型會跟著應用程式一起常駐，避免了每次收發語音都要重新 Load Model 的延遲。
- **STT 非同步轉錄機制**：
  ```python
  async def _transcribe_voice_local(attachment, model):
      ...
      # 因為 WhisperModel.transcribe 是阻擋式操作，
      # 我們利用 asyncio 的 threadpool (run_in_executor)
      # 來確保 STT 的運算不會卡住 FastAPI 的 Main Thread。
  ```
- **Graph 前攔截與自動降級 (Fallback)**：
  在進入 LangGraph 路由之前，攔截 `message_type == "voice"` 的訊息。如果本機轉錄成功，則將文字無縫塞進 `msg.text` 並丟掉 attachment。
  若出現意外錯誤（例如檔案損毀或模型載入失敗），它會自動退回原本的模式：保留 attachment 並進入 Graph 觸發 `file_analyze` → `Gemini` 雲端路徑。
- **紀錄與回顯**：
  轉錄完成後，除了在背後非同步存入 `voice_transcripts` 之外，我們也會在傳回給使用者的 `BrainResponse` 末端塞入像 `(🎙️ 聽寫：[轉錄文字])` 這樣的字眼，讓全家人都能明確地看到 Cindy "聽" 到了什麼。

## 如何測試？

1. **重新建立容器**：
   ```bash
   cd /home/icekimo/gitWrk/OmniAgent/omni-agent
   docker compose up -d --build brain
   ```
2. **觀察 Log**：
   在容器啟動的當下，可以用 `docker compose logs -f brain` 確認有看到 `Local STT model loaded (faster-whisper small)`。第一次啟動可能會稍慢（因為要從 HuggingFace 下載模型）。
3. **實際發送語音**：
   透過 Telegram 傳送一句「今天天氣真好」的語音訊息，接著看看 OmniAgent 怎麼回覆你，回覆末端應該會帶有你的語句回顯！
