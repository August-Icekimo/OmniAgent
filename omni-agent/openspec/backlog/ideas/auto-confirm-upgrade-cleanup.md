---
slug: auto-confirm-upgrade-cleanup
status: idea
domain: brain
size: XS
priority: P2
created: 2026-06-10
---

# auto_confirm_model_upgrade 殘餘清理

## Why
2026-06-10 hotfix（414fead）只修了 `round_messages` NameError，函式內還留有
幾個小問題；該背景任務每次升級確認都會執行，影響資料品質與可讀性。

## What (high-level)
- 移除未使用變數 `admin_chats`、`target_chat`
- metadata 的 `model` 欄位目前填 provider 名（如 `gemini`），應填實際 model 名
  （比照 /chat 主流程用 `client.model_name()`）
- 解決 `TODO: 支援 LINE 及其它平台`：auto-confirm 推送目前只支援 Telegram，
  LINE 使用者收不到自動升級後的結果（可改走 gateway messenger 統一投遞）

## Acceptance hints
- 升級確認後儲存的對話 metadata model 為實際 model 名
- LINE 使用者也能收到 auto-confirm 結果

## Open questions
- 推送是否應改為回寫 message_queue 由 gateway 投遞（統一 reply/push 與 footer 邏輯）？

## Links
- Related: brain/main.py auto_confirm_model_upgrade
- Origin: docs/archive/change_ideas-from-hermes.md 實測期間發現
