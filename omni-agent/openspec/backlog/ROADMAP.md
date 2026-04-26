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

## 2026 Q3 — Phase 6: AAAK Memory Compression (research)
**Theme**: 用 Associative Array Augmented Kernel 把長期記憶壓縮為可注入 prompt 的「直覺片段」，靈感來自 MemPalace 記憶系統。

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

## 2026 Q4 — TBD
**Theme**: 待 Phase 5 Q2 結束後依進度與發現的需求重新規劃。

Candidate epics:
- (留白，根據 Phase 5/6 retro 補入)

---

## Long-term Direction

OmniAgent 的長期方向有兩條主軸：

1. **People-centric awareness**: 從「Cindy 認得帳號」進化到「Cindy 認得人，且記得每個人在不同情境下的樣子」。Phase 4 的 UUID 身分系統是地基；Phase 5 的偏好系統是第一層；後續可能延伸到家人情緒辨識、家庭事件記憶（生日、紀念日、習慣作息）。

2. **Memory as native cognition**: 從「Cindy 查詢資料庫」進化到「Cindy 直覺地知道」。Phase 6 的 AAAK 是這條主軸的開端。長期目標是讓 Cindy 的記憶系統不只是 RAG，而是更接近人類記憶的聯想式、壓縮式、可融入 system prompt 的結構。MemPalace 是重要參考。

兩條主軸交會處：當家人偏好被壓縮成 AAAK 直覺片段時，Cindy 不需要每次查 DB 就「知道」要怎麼跟誰說話。這是長期願景。
