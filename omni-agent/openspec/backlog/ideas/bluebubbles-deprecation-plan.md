---
slug: bluebubbles-deprecation-plan
status: idea
domain: gateway
size: XS
priority: P2
created: 2026-04-29
---

# BlueBubbles Deprecation Plan

## Why

BlueBubbles 是 Phase 1 時期接 iMessage 的權宜方案,跑在 Mac 上、靠 webhook 推訊息給 Gateway。
但它從未被正式寫進 `specs/gateway/spec.md`,handler 邏輯只支援純 text、不處理回應路徑、
沒有身分系統整合,屬於「半廢棄但還活著」的狀態。Phase 4E 的 Apple Embodiment 上線後,
iPhone SE 3 + Apple Intelligence Actions 將直接承擔 iMessage/FaceTime 通道,
BlueBubbles 將變成死碼。需要一份明確的退場計畫文件,
讓 4E 上線後能乾淨地收斂這條舊路徑,且讓未來讀 repo 的人理解這段演進。

## What (high-level)

產出一份 deprecation 計畫文件(不動 code、不動 compose、不動 .env),
記錄 BlueBubbles 的歷史定位、退場觸發條件(Phase 4E archive 完成且穩定運行 N 天)、
退場時要動的範圍清單(handler/route/env/messenger/DB)、以及替代方案(Phase 4E)。
實際的程式移除工作不在本卡範圍,留給後續一張獨立的 ready/change 卡處理。

## Acceptance hints
- (to be drafted during grooming)

## Open questions
- 純計畫文件是否該走 OpenSpec change 流程?還是該走 `docs/decisions/` 純 PR 路徑?
  這個問題的答案會決定本卡是否該存在,或該改寫成 ADR。
- 計畫文件的最終存放位置:`docs/decisions/`、`openspec/changes/archive/` 之外的某處、
  還是直接寫進 `specs/gateway/spec.md` 作為 MODIFIED 條目的註解?
- 退場觸發條件的「N 天」具體數字:Phase 4E archive 後立即可動、7 天、30 天、
  或無時間鎖只看「Phase 4E 通過家庭實際使用驗證」的軟標準?
- 既有 `conversations` 表中 `platform=imessage` 的歷史紀錄處置,需不需要在計畫中
  先表態(保留 / 遷移 / 清理)?還是留給未來那張實際移除卡決定?
- 計畫中要不要明確列出「BlueBubbles server 在 Mac 上的關閉步驟」?
  這超出 OmniAgent repo 範圍,但屬於完整退場的一環。

## Links
- Roadmap: openspec/backlog/ROADMAP.md (no current alignment — 屬 Phase 4E 收尾工作,
  下次 ROADMAP 更新時建議將 4E 與其衍生卡片獨立成一個 mini-quarter section)
- Related spec: openspec/specs/gateway/spec.md
- Depends on: phase-4e-apple-embodiment
