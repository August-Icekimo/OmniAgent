從 `omni-agent/docs/change_<name>.md` 讀取任務，逐一實作並勾選完成。

## 用途

執行 `/opsx-propose` 產生的提案。每完成一個 task 立刻勾選，
保持提案檔案是進度的單一來源。

## 步驟

1. **找到提案檔案**

   若 `$ARGUMENTS` 非空，尋找 `omni-agent/docs/change_<$ARGUMENTS>.md`。
   否則列出 `omni-agent/docs/` 下所有 `change_*.md`，請使用者選擇。

2. **讀取提案，列出未完成任務**

   掃描所有 `- [ ]` 項目，呈現待辦清單給使用者確認要從哪裡開始。

3. **逐任務實作**

   對每個 Task：
   - 閱讀相關程式碼（不靠記憶，重新讀）
   - 實作變更
   - 執行驗證（若 Testing Notes 有指定指令則執行）
   - **立刻將提案檔案中對應的 `- [ ]` 改為 `- [x]`**
   - 簡短回報完成內容與結果

   遇到以下情況暫停並詢問使用者：
   - 需要修改 DB schema 或 migration
   - 需要安裝新套件
   - 需要修改 `routing_config.json` provider 設定
   - 實作過程發現提案的假設不成立

4. **全部完成後**

   - 確認所有 `- [ ]` 已勾選
   - 建議執行 `/commit` 建立 commit
   - 提示使用者：「完成後執行 `/opsx-archive <name>` 歸檔提案。」

## 注意事項

- **不修改 Out of scope 的東西**，即使看起來順手
- 每個 task 獨立完成，不批次修改後才勾選
- 若發現 Open Questions 影響實作，先問清楚再動手
