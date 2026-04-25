## 1. Soul & Persona

- [x] 1.1 F-01 SoulLoader — 讀取 SOUL.md 並渲染 system prompt
  - [x] AC: Given `SOUL.md` 存在，when `SoulLoader.render(user_id)` 被呼叫，then 回傳包含 SOUL.md 核心內容的字串。
  - [x] AC: Given `stress_logs` 有資料，when `render()` 被呼叫，then 包含 stress level 與 mood 資訊。
- [x] 1.2 F-02 SoulLoader — Jinja2 模板渲染動態區段
  - [x] AC: Given `recent_stress_logs`, `home_events`, `today_context` 有資料，when 模板渲染，then 輸出對應區段。

## 2. Memory System

- [x] 2.1 F-03 短期記憶 — 對話歷史持久化
  - [x] AC: Given `/chat` 請求完成，when 查詢 `conversations` table，then 該 user_id 有一筆新增記錄。
  - [x] AC: Given `short_term.load(user_id, limit=5)` 被呼叫，then 回傳最近 5 輪歷史。
- [x] 2.2 F-05 長期記憶 — Embedding 生成與儲存
  - [x] AC: Given 對話完成，when `long_term.store()` 被呼叫，then `memory_embeddings` 新增一筆 pgvector 記錄。
- [x] 2.3 F-06 長期記憶 — 記憶召回作為 context 提示
  - [x] AC: Given `memory_embeddings` 有相關記憶，when `/chat` 被呼叫，then system prompt 包含 `## Long-term Memory` 區段。

## 3. Integration & Polish

- [x] 3.1 F-07 Brain main.py — 串接所有模組
  - [x] AC: Given `/chat` 收到請求，then 按順序執行 SoulLoader, Recall, History Load, Router, Save, and Async Store.
- [x] 3.2 F-08 StressManager — 補完日記寫入
  - [x] AC: Given 不同 queue depth，when StressManager 評估，then `stress_logs` 寫入對應 level 與 mood。
- [x] 3.3 NF-02 效能 — 記憶操作不拖慢 /chat 回應
  - [x] AC: Given `long_term.recall()` 查詢，then 完成時間 < 500ms。
  - [x] AC: Given embedding 生成任務，then 以非同步背景任務執行。
