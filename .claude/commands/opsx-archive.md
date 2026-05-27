將完成的變更提案移至 `omni-agent/docs/archive/`，標記完成日期。

## 用途

變更實作完畢、PR 合併後，將提案檔案歸檔，保持 `docs/` 目錄整潔。
歸檔的檔案作為歷史記錄保留，不刪除。

## 步驟

1. **找到提案檔案**

   若 `$ARGUMENTS` 非空，尋找 `omni-agent/docs/change_<$ARGUMENTS>.md`。
   否則列出 `omni-agent/docs/` 下所有 `change_*.md`，請使用者選擇。

2. **確認所有任務已完成**

   掃描提案檔案，若仍有 `- [ ]` 未勾選，告知使用者並詢問是否仍要歸檔。

3. **在提案末尾加上完成記錄**

   在 Revision History 表格新增一行：
   ```
   | <next version> | <今天日期> | Archived — implementation complete |
   ```

4. **移動檔案**

   ```bash
   mkdir -p omni-agent/docs/archive
   mv omni-agent/docs/change_<name>.md omni-agent/docs/archive/change_<name>.md
   ```

5. **確認並提示**

   確認檔案已移動，提示使用者執行 `/commit` 提交歸檔動作。
