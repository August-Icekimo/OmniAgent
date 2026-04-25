## 1. Unified Identity System

- [x] 1.1 S-01 DB Migration — 統一身份 Schema
  - [x] AC: 原 `family_members` 資料遷移至 `users` 與 `line_accounts`。
  - [x] AC: `conversations` 的 `user_id` 更新為 UUID。
- [x] 1.2 S-02 Bootstrap — 第一個 Admin 從 env var 初始化
  - [x] AC: 若無 admin 則依 `TELEGRAM_ADMIN_CHAT_ID` 建立。
- [x] 1.3 S-03 Gateway Telegram Handler — 改用 DB 身份查詢
  - [x] AC: 查詢 `telegram_accounts` 表判斷授權。
  - [x] AC: 自動處理 `stranger` 並寫入 `stranger_knocks`。

## 2. Skills Server

- [x] 2.1 F-01 Skills Server — 獨立 Go 容器建立
  - [x] AC: `skills` 容器啟動並提供 `/health` 與 `/skill/execute`。
- [x] 2.2 F-02 Skill — Wake-on-LAN
  - [x] AC: 接收 MAC 並發送 magic packet。
- [x] 2.3 F-03 Skill — Cockpit 伺服器管理
  - [x] AC: 查詢狀態 (CPU/RAM/Disk) 與重啟服務。

## 3. Agent Intelligence & Proactive

- [x] 3.1 F-05 LangGraph — 多步對話流程
  - [x] AC: 實作 PLAN → CONFIRM → EXECUTE → REPORT 流程。
- [x] 3.2 F-06 主動推送 — StressOverload 升級提案
  - [x] AC: 高壓時推送升級提案給 admin。
- [x] 3.3 F-07 升級提案狀態持久化
  - [x] AC: 狀態存入 `home_context` 避免重複發送。

## 4. Integration & Security

- [x] 4.1 I-01 compose.yml — 新增 skills service
  - [x] AC: `skills` service 不對外 expose port。
- [x] 4.2 I-02 Brain → Skills Server 呼叫介面
  - [x] AC: Brain 透過 `SKILLS_URL` 呼叫 skills。
- [x] 4.3 I-03 Telegram 主動推送 — Brain 呼叫 Bot API
  - [x] AC: Brain 能主動呼叫 `sendMessage`。
