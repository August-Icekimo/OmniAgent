---
slug: antigravity-a2a-integration-path
status: idea
domain: brain
size: M
priority: P1
created: 2026-06-10
discussed: 2026-06-21
---

# A2A Integration Path — ADK 2.0 Specialist Agents

## Why
Phase 5.9 plans A2A orchestration via subprocess CLI, but agy's headless mode is
currently broken for exactly that pattern: `--print` silently drops stdout when
invoked from a non-TTY subprocess (google-antigravity/antigravity-cli#76), and
no conversation ID is surfaced, so a wrapper cannot maintain per-member threads
(#7). Building the delegation channel on this path risks shipping a feature that
fails silently in production and needs rework when the official path matures.

## What (high-level)
Cindy delegates outsourced work to **ADK 2.0 specialist agents** running in
isolated containers. The original subprocess CLI plan and the Antigravity SDK
(`google-antigravity`, still in preview) are both superseded by Google's
**Agent Development Kit** (`google-adk` 2.0, stable, Apache 2.0, open-source).
ADK 2.0 provides native A2A protocol support, Task API for structured
delegation, graph-based Workflow runtime, and cross-container/cross-server
communication. The AGY container runs self-built specialist agents (not agy CLI
instances), communicating with Brain via the A2A protocol over compose 內網.

## Design decisions (2026-06-21 discussion)

### D1. Container isolation — AGY 獨立容器，沿用 Sandbox 隔離模式

AGY runtime 跑在獨立容器中，不與 Brain 共享 process space。
沿用 Sandbox 容器的安全模式：

- `read_only: true`（檔案系統唯讀）
- 不掛 `.env`（隔絕所有 secret）
- `mem_limit` / `pids_limit`（資源上限）
- `no-new-privileges`（禁止提權）

理由：
- Brain 的 env 含 DB credential、OAuth token 等，不應暴露給 agent runtime
- 容器邊界天然解決 people memory 去識別化問題（見 Q5 resolved）
- 失控 agent 不會拖垮 Brain 主服務
- 已有 Sandbox 成功先例，不需要發明新模式

### D2. 工作交接 — A2A Protocol（主通道）+ 共享 Volume（產物）

```
Brain 容器 (Cindy, LangGraph)            AGY 容器 (ADK 2.0 FastAPI)
┌────────────────────────┐             ┌──────────────────────┐
│  A2A Client            │             │  A2A Server          │
│  ├─ Task API 委派      │──(A2A)─────→│  ├─ Specialist Agent │
│  ├─ Agent Card 發現    │             │  ├─ Custom Tools     │
│  │                     │  ←──result──│  ├─ Gemini API (key) │
│  │        ↕ a2a-workspace volume ↕   │  └─ agent.json       │
└────────────────────────┘             └──────────────────────┘
```

- 任務指令、狀態透過 **A2A protocol**（標準化的 agent-to-agent HTTP 協議）
- ADK 2.0 的 Task API 提供 multi-turn、single-turn、workflow node 模式
- Agent Card (`agent.json`) 宣告 agent 能力，支援動態發現
- 大型產物（code、文件）透過共享 volume
- A2A protocol 是 framework-agnostic — 未來可對接非 ADK agent（LangGraph 等）

### D3. Auth — AGY 用 API Key，與 Cindy OAuth 完全分離

ADK 2.0 不支援 OAuth（僅 API Key）。這反而簡化了架構：
**Cindy 的日常對話（OAuth 訂閱）和 AGY 的 A2A 任務（API Key）計費完全分離**，
互不干擾。

```
Cindy 日常對話:  OAuth 訂閱 → 零成本，吃 Google One AI Premium 配額
AGY A2A 任務:    API Key   → Free Tier（初期）/ Tier 1（量大時升級）
```

AGY 容器的 API Key 由 Brain 在啟動容器時透過環境變數注入（僅此一個 secret，
不掛完整 `.env`）。

429 處理（circuit breaker，僅 API Key 層）：

```
API Key Free Tier ──429──→ 任務暫停 5hr ──→ 重試
                           通知 admin
```

參數：
- Free Tier API Key 寫在 Brain 的 `.env`，由 Brain 啟動 AGY 容器時注入
- Free Tier data policy（input 可能被 Google 訓練）：**可接受**，A2A 任務內容為
  craft-level，不含家人隱私

Free Tier 限制（2026-06 查詢值）：
- ~15-30 RPM, ~1,500 RPD, Flash only（Pro 已於 2026/04 移出 Free Tier）
- 日常 A2A 用量遠低於 daily cap，足以支撐初期

未來升級路徑：當 A2A 用量常態性超出 Free Tier 時，開 billing 升 Tier 1
（~150-300 RPM），但目前不需要。

### D4. 技術選型 — ADK 2.0 取代 Antigravity SDK

2026-06-21 調查結論：原 card 預設的 Antigravity SDK (`google-antigravity`) 不適合。

| 選項 | 評估 |
|------|------|
| ~~Subprocess CLI~~ | 排除（D1 決議，CLI bug + 抽象層次不對） |
| ~~Antigravity SDK~~ | 排除 — Preview，API 會破壞性變更，不支援 OAuth，依賴 compiled binary |
| **ADK 2.0 (`google-adk`)** | ✅ 採用 — Stable 2.0，A2A protocol 原生支援，Task API，開源 Apache 2.0 |

關鍵差異：AGY 容器跑的不是 agy CLI instance，而是**用 ADK 2.0 自建的
specialist agent**。Brain (Cindy) 透過 A2A protocol 委派任務，specialist agent
用 Gemini API + custom tools 執行，產物寫入共享 volume。

ADK 2.0 特性與我們需求的對應：
- Task API → 結構化 A2A delegation（multi-turn, single-turn）
- A2A protocol → 跨容器 HTTP 通訊（天然支援 D1 容器隔離）
- Workflow Runtime → graph-based 執行，routing, fan-out/fan-in, human-in-the-loop
- Agent Card → agent 能力宣告與動態發現
- Framework-agnostic → 未來可對接 LangGraph / CrewAI 等其他框架的 agent

## Acceptance hints
- (to be drafted during grooming)

## Open questions

### Resolved

- ~~SDK auth model~~ → **D3**: AGY 用 API Key only（ADK 2.0 不支援 OAuth）。
  Cindy 日常對話走 OAuth 訂閱，AGY A2A 任務走 API Key Free Tier，
  計費完全分離。Free Tier data policy 可接受（craft-level, 無家人隱私）。
- ~~SDK preview 穩定度~~ → **D4**: 改用 ADK 2.0（`google-adk`，stable release），
  不用 Antigravity SDK（`google-antigravity`，preview，API 不穩，不支援 OAuth）。
  不需要等任何 GA 信號。
- ~~Mjolnir vs SDK safety policies~~ → **D1**: 容器隔離後三者不衝突：
  Mjolnir 在 Brain 端決策、容器限制做 enforcement、ADK safety policies
  為容器內第三道防線，各在不同層次。
- ~~craft memory vs people memory 去識別化~~ → **D1**: Brain 在送任務前
  做 de-identification，AGY 容器永遠看不到 people memory。容器邊界即為
  隱私邊界。
- ~~CLI 修好後是否重新可行~~ → 即使 #76/#7 修復，subprocess CLI 在
  「長時間併發多成員工作線程」的場景下仍不是正確的抽象層次。ADK 2.0 + 獨立容器
  是更乾淨的架構。CLI 不保留為 fallback。
- ~~Hermes foreman 角色重疊~~ → D4 轉向 ADK 2.0 自建 specialist agent 後，
  Hermes「操作 agy」的 skill 與我們的路線已無交集。Hermes 是獨立的 agent 專案，
  不阻擋此 card。若 Hermes 未來有可用能力，可透過 A2A protocol + Agent Card
  被 Cindy 動態發現並委派，但那是獨立的 card。
- ~~是否拆 card~~ → D1–D4 緊密耦合（容器隔離 → A2A protocol → auth → 技術選型），
  建議保持統一 card。grooming 時若範圍太大再拆。

### All original questions resolved (7/7)

## Links
- Roadmap: openspec/backlog/ROADMAP.md#phase-59-agent-capabilities
- Related spec: openspec/specs/brain/spec.md
- ADK 2.0: https://github.com/google/adk-python
- A2A protocol: https://a2a-protocol.org
- Depends on: mjolnir-trust-model (creative-agency circle semantics)

