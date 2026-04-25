## 1. Infrastructure & Database

- [x] 1.1 S-01 DB Migration — wol_targets 與 file_workspace_log 表
  - [x] AC: 建立 `wol_targets` 與 `file_workspace_log` 表。
- [x] 1.2 S-02 Workspace Volume — 共用掛載區域
  - [x] AC: `omni-workspace` volume 掛載至 gateway 與 brain。

## 2. File Receipt & Management

- [x] 2.1 F-01 StandardMessage — Attachment Struct 擴充
  - [x] AC: `StandardMessage` 包含選填的 `Attachment` metadata。
- [x] 2.2 F-02 Gateway — Telegram 檔案下載
  - [x] AC: 下載 < 10MB 檔案至 workspace 並填入 `local_path`。
- [x] 2.3 F-07 Workspace Cleanup — Brain 背景 Cron Task
  - [x] AC: 每小時刪除超過 120 小時未存取的檔案。

## 3. Skills & Analysis

- [x] 3.1 F-04 Brain — FileAnalyzer Skill
  - [x] AC: 支援 PDF (text), Image (Vision OCR), Excel (pandas) 分析。
- [x] 3.2 F-05 LangGraph — Attachment Routing
  - [x] AC: 偵測到附件時優先路由至 `FileAnalyzer` 並跳過確認。
- [x] 3.3 F-06 WoL Target — DB 查詢取代手動 MAC 輸入
  - [x] AC: 透過 `ai_name` 查詢 MAC 並執行 WoL。

## 4. Integration & Security

- [x] 4.1 NF-01 檔案下載不 block Telegram Webhook 回應
  - [x] AC: 設定 4s timeout 確保在 5s 內回應 Telegram。
- [x] 4.2 NF-02 Workspace 路徑安全性
  - [x] AC: 防止 path traversal，驗證路徑前綴。
