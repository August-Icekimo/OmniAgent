---
slug: specialist-deid-scope-expansion
status: idea
domain: security
size: M
priority: P1
created: 2026-08-29
---

# 委派去識別化擴充：暱稱、稱謂、電話（目前只遮 users.name 字面）

## Why
PR #13 的 de-id 只做 `users.name` 的字面替換（[specialist.py:22](../../../brain/skills/specialist.py#L22)），
但提案 AC 寫的是「家人姓名/**識別資訊**」— 兩者有落差，review M3 已明示範圍並
留待後續（`review_pr13` M3）。實際暴露面：

- **暱稱**：家人日常互不喊本名，planner 組 task 參數時原文帶的多半是暱稱 → 完全不被遮
- **稱謂**：「爸爸」「妹妹」「阿嬤」單獨看不算 PII，但與內容組合可還原家庭結構
- **電話/地址**：長文摘要委派若原文含這些，直接原樣出容器
- **planner 改寫**：planner 可能重述原文，遮蔽發生在改寫「之後」，遮得到字面但遮不到語意

現況風險可控（容器邊界即隱私邊界、AGY 單一用途、家庭規模），但每擴一個委派場景
就放大一次。此卡把「PoC 可接受」轉成「有意識的設計」。

## What (high-level)
把 de-id 從「單一欄位字面替換」升級成「有來源、有規則、可測」的遮蔽層：

1. **暱稱來源**：`users` 現行 schema 無 alias 欄位（001/002 migration 查證：
   只有 `name`/`role`/`preferences` JSONB）。兩個選項 —— 用 `preferences` 的
   `aliases: []` key（免 migration，延續 W26「JSONB 複用」手法），或等 Phase 5
   `user_preferences` 表落地時一併設計。傾向前者，後者接手時再搬。
2. **稱謂與 pattern**：稱謂白名單（爸爸/媽媽/哥哥/妹妹/阿公/阿嬤…）+ 電話號碼
   regex，各自可獨立開關 —— 稱謂遮蔽會傷摘要可讀性，預設行為需實測後定。
3. **可測**：`redact_names` 抽成有單元測試的純函式（現在沒有任何測試覆蓋），
   含子字串殘留、重疊名、空名單等 case。

## Acceptance hints
- 委派 task 文字中的暱稱、稱謂、電話依設定被遮蔽，AGY 端 log 驗證看不到原詞
- 遮蔽規則有開關；關閉時行為與現況（只遮 name）完全一致
- de-id 純函式有測試；長名先換的既有防子字串殘留行為不回歸
- 取名單/別名失敗仍不阻斷委派（維持現行 fail-soft，只 log warning）

## Open questions
- 稱謂預設遮或不遮？（遮了「幫我摘要爸爸傳的這篇」會變「幫我摘要[人名]傳的」，
  可能讓 AGY 誤解任務 —— 傾向預設不遮、可開）
- 別名放 `preferences.aliases` 還是等 Phase 5 `user_preferences` 表？
- 要不要一併處理「planner 改寫後語意殘留」？（本卡傾向不處理 —— 那是 prompt
  層問題，字面遮蔽解不了，需另立）

## Links
- Roadmap: openspec/backlog/ROADMAP.md#2026-q2--phase-5-family-preference-awareness
- 來源：docs/archive/review_pr13_antigravity-a2a-integration-path.md（M3 Minor）
- Related: brain/skills/specialist.py `redact_names`、brain/agent/tools.py `delegate_to_specialist`
- Related idea: antigravity-a2a-integration-path（已 resolved，本卡承接其 de-id 殘留）
- Depends on（軟）: Phase 5 `user_preferences` 資料模型 —— 不阻塞，可先用 preferences JSONB
