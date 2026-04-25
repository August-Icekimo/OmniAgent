# OpenSpec 遷移指導手冊 — Gemini 3 Flash 執行版

> **版本**: 1.0 | **日期**: 2026-04-25
> **產出者**: Claude (Opus) — 架構師
> **執行者**: Gemini 3 Flash — 遷移工人
> **專案**: Omni-Agent (Cindy)

---

## 你的角色

你是**遷移工人**。讀取 `docs/` 下的舊文件，按本手冊的模板與規則轉換，寫入 `openspec/` 對應路徑。

**你不做架構判斷。** 遇到模糊內容，在輸出中插入 `<!-- REVIEW: 描述問題 -->` 標記，讓人類後續審查。

---

## 全局規則

### 保留規則
1. **保留**仍有效的 Acceptance Criteria（Given/When/Then 格式）
2. **保留** Project Context 與 Scope（搬入 `proposal.md`）
3. **保留** Non-Functional Requirements 與 Integration Requirements
4. **保留**原文語言（中英混合），不翻譯

### 過濾規則
1. **刪除** `## Testing Notes` — 測試環境說明不是規格
2. **刪除** `## Do Not Modify` — Agent 指令不是規格
3. **刪除** `## Suggested Commit Message` — 不是規格
4. **刪除** `## Revision History` — 不是規格
5. **刪除** 超過 10 行的程式碼區塊 — 改為引用 codebase 路徑（如 `See: brain/llm/router.py`）
6. **刪除** 5 行以內的 struct/function 簽名 — 可保留作為介面參考

### Open Questions 處理（重要！）
**不盲搬。** 對每個 Open Question：
1. 檢查是否標記為 `[x]`（已 resolved）→ 刪除
2. 若標記為 `?`，檢查 codebase 中是否已有對應實作 → 若有，刪除並標注「已在 codebase 中解決」
3. 若確實未解決 → 保留，搬入 `proposal.md` 的 `## Open Questions` 段

### Acceptance Criteria 狀態標記
- 已完成的 Phase（所有 checkbox 為 `[x]`）→ 在 `spec.md` 中保持 `[x]`
- 未完成的 Phase（checkbox 為 `[ ]`）→ 在 archive 的 `tasks.md` 中標記為 `[ ]`，在 `spec.md` 中不放入

---

## 輸出模板

### 模板 A: `proposal.md`（歸檔用）

```markdown
## Why

<!-- 從原文 ## Project Context 抽取動機 -->

## What Changes

<!-- 從原文 ## Scope 的 In scope 段落轉述 -->

## Capabilities

### New Capabilities
- `<domain-name>`: <簡述此 phase 新增的能力>

### Modified Capabilities
- `<existing-domain>`: <簡述修改了什麼>

## Impact

<!-- 從原文 ## Scope 的 Assumptions 抽取 -->

## Open Questions

<!-- 僅放入確實未解決的問題 -->
```

### 模板 B: `tasks.md`（歸檔用）

```markdown
## 1. <Task Group Name>

- [x] 1.1 <Task Title>
  - [x] AC: Given ... when ... then ...
  - [x] AC: Given ... when ... then ...

## 2. <Task Group Name>

- [x] 2.1 <Task Title>
```

> 所有已完成 Phase 的 checkbox 標記為 `[x]`。

### 模板 C: `specs/<domain>/spec.md`（Source of Truth）

```markdown
## ADDED Requirements

### Requirement: <requirement name>
<requirement description>

#### Scenario: <scenario name>
- **WHEN** <condition>
- **THEN** <expected outcome>
```

> 這是 OpenSpec 官方格式。將原文的 Given/When/Then 轉為 WHEN/THEN。
> 已完成的功能用 `ADDED`，被後續 Phase 修改過的用 `MODIFIED`。

### 模板 D: `design.md`（僅有架構決策時使用，選用）

```markdown
## Context
<!-- 背景 -->

## Goals / Non-Goals
**Goals:** ...
**Non-Goals:** ...

## Decisions
<!-- 關鍵設計決策 -->

## Risks / Trade-offs
<!-- 已知風險 -->
```

---

## Domain 映射總表

每個 `specs/<domain>/spec.md` 從多個 Phase 文件中合併而來：

| Domain | 來源 Phase | 抽取內容 |
|--------|-----------|---------|
| `gateway` | Phase 1 (test), 3.5, 4 (S-02,S-03), 4b (F-01,F-02) | Webhook 驗證、StandardMessage、Attachment、檔案下載、Bootstrap |
| `brain` | Phase 2 (jules), 4 (F-05), 4a (F-05,F-09) | FastAPI、/chat 端點、LangGraph、BrainResponse |
| `memory` | Phase 3 (F-03~F-06) | 短期/長期記憶、embedding、摘要索引 |
| `soul` | Phase 3 (F-01,F-02) | SoulLoader、Jinja2 模板、動態注入 |
| `skills` | Phase 4 (F-01~F-04), 4b (F-04~F-06) | Skills Server、WoL、Cockpit、FileAnalyzer |
| `identity` | Phase 4 (S-01~S-04) | users、telegram/line_accounts、stranger、bootstrap |
| `llm` | Phase 2 (§2.2~2.6), 4a (F-01~F-09), 4c (全部) | ModelRouter、routing_config、OAuth、Caching、Fallback |
| `security` | SECURITY.md, Phase 3.5 (NF-01), 4 (NF-01), 4b (NF-02) | WAF、Log 個資保護、路徑安全、credential 保護 |

---

## 遷移任務清單

### 執行順序與理由

1. **Phase 4C 先做**（最乾淨的 conv2spec 格式，練手）
2. **Phase 3 → 3.5**（記憶/靈魂/Telegram，domain 邊界清楚）
3. **Phase 4 → 4a → 4b**（逐步累積 domain specs）
4. **Phase 2 最後做**（28KB 大檔，大量程式碼需過濾）
5. **Walkthrough 文件統一歸檔**（不需要拆分 domain）

---

### 任務 1: Phase 4C — Gemini OAuth

**輸入**: `docs/feature_omni-agent-phase4c-gemini-oauth.md` (11KB)
**涉及 Domain**: `llm`
**難度**: ⭐ (最乾淨)

#### Step 1: 建立 archive
```bash
# 已建好目錄: openspec/changes/archive/phase4c-gemini-oauth/
```

#### Step 2: 產出 `proposal.md`
- 從 `## Project Context` 全文 → `## Why`
- 從 `## Scope` → `## What Changes` + `## Impact`
- Capabilities: `llm` (Modified — 新增 OAuth provider)
- Open Questions: 原文 `## Open Questions` 寫「No blocking open questions」→ 不搬

#### Step 3: 產出 `tasks.md`
- 抽取所有 `### Task:` 標題與其下的 Acceptance Criteria
- 共 8 個 Task (含 NFR、Integration)
- 此 Phase 的 checkbox 原文為 `[ ]`（未打勾），但 **codebase 已實作完成**
  - 驗證方式: 檢查 `brain/llm/oauth_gemini_client.py` 是否存在
  - 若已存在 → 全部標記 `[x]`

#### Step 4: 產出 `specs/llm/spec.md`（新建或 APPEND）
- 抽取有效的 Acceptance Criteria，轉為 WHEN/THEN 格式
- 來源 Tasks: oauth_tokens table、OAuthGeminiClient、Token refresh、Wire into ModelRouter、routing_config.json 更新、.env 文件
- NFR: credential 不洩漏 → 也放入 spec

#### Step 5: 產出 `design.md`（選用）
- 此 Phase 有明確的 token refresh 架構決策 → 建議產出
- Context: 為什麼用 OAuth 而非 API key
- Decisions: DB cache token、refresh_token 不進 container

---

### 任務 2: Phase 3 — Memory + SoulLoader

**輸入**: `docs/feature_omni-agent-phase3-memory-soulloader.md` (16KB)
**涉及 Domain**: `memory`, `soul`
**難度**: ⭐⭐

#### Step 2: `proposal.md`
- Project Context + Scope 全搬

#### Step 3: `tasks.md`
- F-01~F-02 → soul domain
- F-03~F-06 → memory domain
- F-07 → brain domain (串接)
- F-08 → gateway domain (StressManager 補完)
- NF-01~NF-03, I-01~I-03

#### Step 4a: `specs/memory/spec.md` (新建)
- F-03: 短期記憶持久化
- F-04: 摘要索引
- F-05: Embedding 生成與儲存
- F-06: 記憶召回
- NF-02: 效能約束 (500ms)

#### Step 4b: `specs/soul/spec.md` (新建)
- F-01: SoulLoader render()
- F-02: Jinja2 模板
- NF-01: 記憶作為提示非事實

#### Open Questions 處理
- `I-02-A` Embedding provider → 檢查 `brain/memory/long_term.py` 確認實際用的是 voyage 還是 openai
- `F-04` 摘要策略 → 檢查 codebase 實作
- `F-06` 觸發時機 → 檢查 codebase 實作

---

### 任務 3: Phase 3.5 — Telegram

**輸入**: `docs/feature_omni-agent-phase3.5-telegram.md` (12KB)
**涉及 Domain**: `gateway`
**難度**: ⭐

#### Step 4: `specs/gateway/spec.md` (新建或 APPEND)
- F-01: Webhook 接收與簽章驗證
- F-02: StandardMessage 轉換
- F-03: chat_id 白名單 → **注意**: Phase 4 已改為 DB 管理，此條標記 `MODIFIED`
- F-04: Message Queue 寫入
- F-05: 回應時間 ≤ 5 秒
- F-06: 環境變數

#### Open Questions 處理
- `I-01-A` 公開 URL → 已解決（Caddy reverse proxy in secure-gateway）
- `F-04-B` 冪等性 → 檢查 codebase
- `F-03-A` DB 管理 → **已在 Phase 4 實作**，刪除

---

### 任務 4: Phase 4 — Identity + Skills + Proactive

**輸入**: `docs/feature_omni-agent-phase4.md` (18KB)
**涉及 Domain**: `identity`, `skills`, `brain`, `gateway`
**難度**: ⭐⭐⭐ (跨 4 個 domain)

#### Step 4a: `specs/identity/spec.md` (新建)
- S-01: 統一身份 Schema
- S-02: Bootstrap admin
- S-03: DB 身份查詢（取代 Phase 3.5 的白名單）
- S-04: Stranger 每日彙整

#### Step 4b: `specs/skills/spec.md` (新建)
- F-01: Skills Server 容器
- F-02: Wake-on-LAN
- F-03: Cockpit
- F-04: Home Assistant stub

#### Step 4c: APPEND `specs/brain/spec.md`
- F-05: LangGraph 多步流程
- F-06~F-07: 主動推送 + 狀態持久化

#### Step 4d: APPEND `specs/gateway/spec.md`
- 將 S-02, S-03 的 gateway 相關 AC 合併

#### Open Questions
- Cockpit API 認證 → 檢查 `skills/handler/cockpit.go` 確認實作
- LangGraph CONFIRM 回覆偵測 → 檢查 `brain/agent/graph.py`
- 升級模型 → 檢查 `brain/config/routing_config.json`
- Stranger 制式回覆 → 檢查 `.env` 或 codebase

---

### 任務 5: Phase 4A — Dynamic ModelRouter

**輸入**: `docs/feature_omni-agent-phase4a.md` (22KB)
**涉及 Domain**: `llm`, `brain`
**難度**: ⭐⭐⭐

#### Step 4: APPEND `specs/llm/spec.md`
- F-01: routing_config.json
- F-02: 評估者與執行者分離
- F-03~F-04: system_prompt.py / tools_prompt.py
- F-06~F-07: 升級確認 + 配額管理
- F-08: LocalClient 健康檢查
- I-03: thinking_budget

#### 注意
- **此 Phase 的 checkbox 為 `[ ]`** — 需檢查 codebase 確認是否已實作
  - 檢查: `brain/config/routing_config.json` 是否存在
  - 檢查: `brain/llm/router.py` 是否有 `select_provider`
- Open Questions 已全部標記 `[x]` → 全部刪除
- F-01 有大段 JSON 結構 → 保留（這是 config schema 定義，不是程式碼）

---

### 任務 6: Phase 4B — File Analysis

**輸入**: `docs/feature_omni-agent-phase4b-file-analysis.md` (21KB)
**涉及 Domain**: `skills`, `gateway`, `brain`
**難度**: ⭐⭐⭐

#### Step 4a: APPEND `specs/gateway/spec.md`
- F-01: Attachment struct
- F-02: Telegram 檔案下載

#### Step 4b: APPEND `specs/skills/spec.md`
- F-04: FileAnalyzer
- F-06: WoL DB 查詢
- F-07: Workspace cleanup

#### Step 4c: APPEND `specs/brain/spec.md`
- F-05: LangGraph attachment routing

#### 注意
- F-01 有 Go struct 定義 (5行) → 保留作為介面參考
- F-04 有 Python class 骨架 (8行) → 保留

---

### 任務 7: Phase 2 — Brain Skeleton

**輸入**: `docs/jules_phase2_spec.md` (28KB)
**涉及 Domain**: `brain`, `llm`
**難度**: ⭐⭐⭐⭐ (大量程式碼需過濾)

#### 特殊處理
此文件與其他 `feature_*.md` 格式不同，它是「任務指令書」而非 conv2spec 產出。

#### Step 2: `proposal.md`
- `## 背景` → `## Why`
- `## 本 PR 要完成的事項` → `## What Changes`

#### Step 3: `tasks.md`
- 任務 1: 架構文件更新 (1.1~1.3)
- 任務 2: Brain 骨架實作 (2.1~2.9)

#### Step 4: 更新 specs
- **不要**把 §2.1~§2.9 的完整程式碼搬入 spec
- 只抽取介面定義：
  - `ModelClient` ABC 的 method signatures → `specs/llm/spec.md`
  - `StandardMessage` Pydantic model fields → `specs/brain/spec.md`
  - `BrainResponse` fields → `specs/brain/spec.md`
- 引用 codebase: `See: brain/llm/base.py`, `See: brain/main.py`

---

### 任務 8: Walkthrough 與雜項歸檔

**輸入**: 以下文件
- `docs/test_phase1_walkthrough.md`
- `docs/test_phase2_walkthrough.md`
- `docs/test_phase3_walkthrough.md`
- `docs/test_phase3.5-telegram_walkthrough.md`
- `docs/feature_omni-agent-phase3.5-telegram_walkthrough.md`
- `docs/test_phase4_walkthrough.md`
- `docs/test_phase4b_walkthrough.md`
- `docs/phase3.5-Telegram Setup Completed.md`
- `docs/phase4_implementation_plan.md`
- `docs/phase4a_implementation_plan.md`
- `docs/phase4b_implementation_plan.md`
- `docs/phase4_task.md`
- `omni-agent/test_phase4a_walkthrough.md`

#### 處理方式
1. Walkthrough 文件 → 移至對應的 `archive/<phase>/walkthrough.md`
2. Implementation plan 文件 → 移至對應的 `archive/<phase>/design.md`（若該 phase 還沒有 design.md）
3. Task 文件 → 合併至對應的 `archive/<phase>/tasks.md`
4. 重複文件 → 刪除（如 `phase3.5-Telegram Setup Completed.md` 與 walkthrough 重複）

**不需要做格式轉換，直接移動即可。**

---

### 任務 9: 驗證與收尾

#### 9.1 結構驗證
```bash
# 確認所有 domain spec 都已建立
ls openspec/specs/*/spec.md

# 確認所有 archive 都有 proposal.md + tasks.md
for d in openspec/changes/archive/*/; do
  echo "=== $d ==="
  ls "$d"proposal.md "$d"tasks.md 2>/dev/null || echo "MISSING!"
done
```

#### 9.2 內容驗證
- [ ] 所有 `spec.md` 中無 `<!-- REVIEW -->` 標記殘留（或已處理）
- [ ] 所有 `spec.md` 中無超過 10 行的程式碼區塊
- [ ] 所有已完成 Phase 的 `tasks.md` checkbox 都是 `[x]`
- [ ] 所有 Open Questions 已按規則處理（resolved 的刪除、未解的保留）

#### 9.3 CLI 驗證（可選）
```bash
cd omni-agent
openspec list --specs
openspec validate
```

#### 9.4 收尾
- [ ] 在 `docs/` 頂部建立 `DEPRECATED.md`，說明這些文件已遷移至 `openspec/`
- [ ] 不刪除原始文件（保留 git history），但標記為 deprecated

---

## 特殊文件處理

### `docs/architecture.md` 和 `docs/SECURITY.md`

- `architecture.md` → 若內容與 `CLAUDE.md` §1 重複則不搬，標記 deprecated
- `SECURITY.md` → 內容搬入 `specs/security/spec.md`

### `docs/test_phase*.md`（測試規格文件）

這些是**測試清單**，不是 feature spec。處理方式：
- 從中抽取仍有效的驗收標準 → 合併到對應 domain 的 `spec.md`
- 其餘（測試步驟、curl 指令、環境設定）→ 不搬

### `docs/podman_network_error_sop.md`

這是 SOP 文件，不屬於 OpenSpec。保留在 `docs/` 不遷移。

---

## 執行節奏建議

| 批次 | 任務 | 預估輸出 | Context Window |
|------|------|---------|---------------|
| Batch 1 | 任務 1 (Phase 4C) | 4 files | 低 — 練手 |
| Batch 2 | 任務 2+3 (Phase 3+3.5) | 6 files | 中 |
| Batch 3 | 任務 4 (Phase 4) | 6 files | 高 — 跨 4 domain |
| Batch 4 | 任務 5+6 (Phase 4A+4B) | 4 files (APPEND) | 高 |
| Batch 5 | 任務 7 (Phase 2) | 4 files | 高 — 需過濾 |
| Batch 6 | 任務 8+9 (歸檔+驗證) | 移動+驗證 | 低 |

**每批次結束後 git commit**，commit message 格式：
```
docs(openspec): migrate phase-X to OpenSpec structure

- archive: proposal.md, tasks.md, design.md
- specs: <domain>/spec.md updated
```
