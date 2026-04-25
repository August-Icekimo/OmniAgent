## 1. Routing Configuration

- [x] 1.1 F-01 routing_config.json — 集中定義所有路由規則
  - [x] AC: 成功從 JSON 載入 provider 能力、規則與配額。
  - [x] AC: 缺失檔案時 fallback 至預設值。

## 2. Dynamic Routing Logic

- [x] 2.1 F-02 評估者與執行者分離 — Flash 統一做複雜度評估
  - [x] AC: 複雜度評估由 Flash 執行，執行可由 local/claude 執行。
- [x] 2.2 F-03 system_prompt.py — self-assessment 提示詞
  - [x] AC: Planner 收到包含 complexity 欄位的 JSON 評估結果。
- [x] 2.3 F-05 AgentState 擴充與 planner_node 整合
  - [x] AC: `AgentState` 包含 `selected_provider`, `routing_reason`, `complexity`。
  - [x] AC: 支援 `/provider` 覆蓋指令。

## 3. Upgrade & Quota Management

- [x] 3.1 F-06 升級確認流程 — 15 秒自動繼續
  - [x] AC: 觸發 `require_confirmation` 規則時發送確認訊息，15s 超時自動升級。
- [x] 3.2 F-07 升級配額管理 — 每日 20 次 + 冷卻保護
  - [x] AC: 狀態存入 `home_context`，支援 admin override。

## 4. Stability & Observability

- [x] 4.1 F-08 LocalClient 啟動健康檢查與測試跳過
  - [x] AC: 啟動時 ping Mac Mini，離線時自動排除 local。
- [x] 4.2 F-09 BrainResponse 新增路由資訊
  - [x] AC: 回應包含 `routing_reason` 欄位。
