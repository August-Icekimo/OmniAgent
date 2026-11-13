---
slug: group-chat-participation
status: idea
domain: gateway
size: L
priority: P2
created: 2026-11-11
---

# Cindy 參與多人群組對話（該不該開口的判斷）

## Why
Cindy 目前只支援 LINE／Telegram **1:1**：gateway 以 `event.Source.UserId` 識別使用者
（gateway/internal/handler/line.go），turn 依 per-user 序列化；conversational-turn-assembly 與
topic-threading-and-open-loops 兩卡皆明列「群組 deferred」。家庭群組是家人最自然的使用場景，
現在 Cindy 在群組裡等於不存在。

## What (high-level)
Cindy 能加入家庭群組，在被點名或「隱性被問」（例：「誰知道明天會不會下雨？」）時適度回應，
其餘時間安靜旁聽；插話敏感度可調（亂插話比漏接代價高，預設保守）。

## Acceptance hints
- 明確點名（@Cindy／回覆 Cindy 的訊息／提及名字）必回
- 一般閒聊不插話
- 判斷層失效（逾時／離線）時退回「只回應明確點名」——fail-closed、不卡 turn（記取 local-llm-retirement Task 1 卡 361s 的教訓）
- 群組內容不洩漏到私訊（依 Open question 2 的隱私決策）

## Open questions
<!-- 2026-11-11 Jev／Apple fm 討論後記錄；等開發群組聊天時一併討論 -->
1. **群組身分模型**：一個 chat 多發話者、未註冊成員如何處理；per-chat vs per-user 序列化與
   turn 組裝邊界（schema first，需先確認 DB 變更）。
2. **隱私邊界**：群組↔私訊記憶互通規則（群組聽到的事能否在私訊提起？反之？）；ROADMAP 已點出
   「LINE 群組 vs 私訊」顆粒度。2026-10-26「隱私非剛性需求」是 1:1 結論，群組涉及未同意的家人訊息，需重新確認。
3. **平台能見度**：Telegram bot 預設 privacy mode 只收指令／點名，需關閉才看得到其他訊息；LINE bot 預設收全部。
4. **「該不該開口」判斷層**：規則優先（點名類 0 成本）＋殘餘隱性提問交分類器；設計為可抽換介面
   （如 `should_respond(msg, ctx) → p`，以校準機率對門檻）。後端候選：
   - Jev 雲端（TypeSafe AI，非自回歸、校準機率；宣稱 70–500ms、$0.042/1M input；新創、Waitlist，數字未獨立驗證）
   - 自架 Nimble（宣稱 Qwen3.5-9B 底座的開源 Jev 替代；2026-11-11 搜尋未證實存在）
   - ~~macOS 27 `fm serve`（OpenAI 相容，model=`system`）~~ **2026-11-13 排除**：chrysoberyl 已升 27.2.1，
     但為國行 CH/A 硬體，`system`＝`deviceNotEligible`、`pcc` 亦不可用（Apple Intelligence 區域鎖，改地區無解）
   - 現有 LLM＋精簡 prompt（慢、無可信機率，但零新依賴）
   群組場景判斷失效可 fail-closed，故自架的離線弱點在此可接受（與 1:1 不同）。
5. **成本**：每則群組訊息都要判斷，若走 ChatGPT 會吃與 admin 共用的 Plus 額度——判斷層選型的主要理由。
6. 是否先在 1:1 做意圖／話題判斷的**影子模式**（只記錄判斷、不影響行為）累積準確率，與 topic-threading 共用。
7. LINE 群組回覆／push 配額影響。

## Links
- Roadmap: openspec/backlog/ROADMAP.md（隱私顆粒度：LINE 群組 vs 私訊）
- Depends on: conversational-turn-assembly（已歸檔）
- Related: topic-threading-and-open-loops、local-llm-retirement
- 參考：Jev 文章 https://x.com/criscxuan/status/2101841402896474478 ；macOS 27 `fm` 教學 https://www.kocpc.com.tw/archives/669991
