# OmniAgent Roadmap

> Quarterly themes that guide backlog grooming.
> Update at start of each quarter.

## 2026 Q2 — Phase 5: Family Preference Awareness
**Theme**: Cindy 認得家人，並能依不同傳輸 channel 套用個人化的偏好與隱私設定。

Candidate epics:
- 家庭成員偏好資料模型 (`user_preferences` 表 + 跨平台繼承規則)
  - Domain: `identity`, `memory`
  - 偏好類型：稱呼、回覆語氣、推播時段、敏感話題黑名單
- Per-channel 偏好套用機制
  - Domain: `gateway`, `brain`
  - LINE/Telegram/BlueBubbles 各自的隱私顆粒度（例如 LINE 群組 vs 私訊）
- 偏好學習與顯式覆寫
  - Domain: `brain`, `memory`
  - Cindy 從互動中推斷偏好；家人可用自然語言主動修正
- 隱私邊界規則
  - Domain: `security`, `identity`
  - 家人 A 的偏好/記憶絕不洩漏給家人 B；admin 例外規則

## 2026 Q2–Q3 Bridge — Phase 5.5: Skills Expansion + Per-member Skill ACL

**Theme**: 補充 Cindy 的主流 Agent Skill 庫，並建立成員層級的 Skill 組合權限系統。

Candidate epics:
- 主流 Agent Skills 擴張
  - Domain: `skills`
  - Candidate: calendar 整合、天氣、新聞摘要、提醒/排程、購物清單、更深的 Home Assistant 整合
  - 細項待 idea grooming 階段定義
- Per-member Skill ACL
  - Domain: `skills`, `identity`, `security`
  - 每位成員擁有不同的 Skill 組合（Admin 有 shell，小孩限定作業助手+天氣...）
  - ACL 儲存於 `user_preferences` 或獨立 `skill_permissions` 表
  - 為 Phase 5.9 的 Shell preauth list 提供基礎權限模型

> 📋 Candidate Skills 清單待 idea grooming 細化，不在此預先鎖定優先序。

---

## 2026 Q3 — Phase 5.9: Agent Capabilities

**Theme**: 從「會說話的 assistant」進化為「會行動的 agent」——給 Cindy 觸角：知識觸角、系統觸角、記憶觸角、智慧觸角。

Candidate epics:
- Web Search & Browse
  - Domain: `skills`
  - Web 搜尋 + 網頁讀取解析；結果可寫入成員 Workspace
- Shell + Approve/Preauth（HomeLab 控制）
  - Domain: `skills`, `security`
  - 完整 shell 執行 + admin preauth allowlist
  - 非 preauth 指令走 human-in-the-loop 審批（LINE/Telegram 確認）
  - 審批超時 → queue 住等下次，不自動取消也不自動執行
  - Preauth list 以 Phase 5.5 Per-member Skill ACL 為基礎延伸
- Private Workspace（跨對話私人目錄）
  - Domain: `skills`, `memory`, `identity`
  - 每位成員擁有獨立工作區；Cindy 有全域讀取權；Linux group 模擬隔離
  - 任務中間產物寫入 `.tmp/{task_id}/`，任務完成後清除
  - 保留 `lessons_learned/{date}_{task}.md` 供人類與後續 AAAK 使用
  - 任務產物 owner = 發出任務的成員
- A2A Orchestration
  - Domain: `brain`, `skills`
  - Cindy 作為 orchestrator，以 subprocess CLI 委派專業任務給 Claude Code / Gemini CLI
  - 回收產出後由 Cindy 合成回覆給家人
  - Cindy 僅在 HomeLab 控制場景中作為 worker（受 Admin/家人驅動）
  - 初版用 subprocess CLI；不通再改 API

---

## 2026 Q4 — Phase 6: AAAK Memory Compression (research)
**Theme**: 用 Associative Array Augmented Kernel 把長期記憶壓縮為可注入 prompt 的「直覺片段」，靈感來自 MemPalace 記憶系統。需等 Phase 5–5.9 上線一段時間讓記憶沉澱後才能有料可壓縮（類人類睡眠夢境的記憶清洗機制）。Phase 5.9 產出的 Lessons Learned MD 是 AAAK 的天然原料之一。

Candidate epics:
- AAAK 概念驗證（PoC）
  - Domain: `memory`, `llm`
  - 設計聯想鍵（associative key）的擷取與索引；初版可用 embedding cluster centroid
- 直覺提示字（intuition snippet）注入機制
  - Domain: `brain`, `llm`
  - System prompt 中保留專屬區塊；token budget 與 routing 整合
- 記憶壓縮率與召回品質量測
  - Domain: `memory`
  - 對照組：原始記憶 vs AAAK 壓縮版的回覆品質差異
- 與既有 memory 系統的共存策略
  - Domain: `memory`, `brain`
  - AAAK 是 augment 不是 replace；兩層查詢的優先順序

## 2027 Q1 — TBD
**Theme**: 待 Phase 5.9 / Phase 6 retro 後依進度與新發現重新規劃。

Candidate epics:
- (留白，根據 Phase 5.x / 6 retro 補入)

---

## Long-term Direction

OmniAgent 的長期方向有兩條主軸：

1. **People-centric awareness**: 從「Cindy 認得帳號」進化到「Cindy 認得人，且記得每個人在不同情境下的樣子」。Phase 4 的 UUID 身分系統是地基；Phase 5 的偏好系統是第一層；後續可能延伸到家人情緒辨識、家庭事件記憶（生日、紀念日、習慣作息）。

2. **Memory as native cognition**: 從「Cindy 查詢資料庫」進化到「Cindy 直覺地知道」。Phase 6 的 AAAK 是這條主軸的開端。長期目標是讓 Cindy 的記憶系統不只是 RAG，而是更接近人類記憶的聯想式、壓縮式、可融入 system prompt 的結構。MemPalace 是重要參考。

兩條主軸交會處：當家人偏好被壓縮成 AAAK 直覺片段時，Cindy 不需要每次查 DB 就「知道」要怎麼跟誰說話。這是長期願景。

Phase 5.9 的 Lessons Learned 機制是兩條主軸的橋：Agent 任務完成後沉澱的知識萃取，既是人類可讀的操作紀錄，也是 AAAK 夢境清洗的優質原料——行動記憶與認知記憶在此交會。
