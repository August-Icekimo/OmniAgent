## Why

OmniAgent 的 OpenSpec 工作流目前只覆蓋「進行中與已完成」的工作（`changes/` 與 `changes/archive/`），缺少**想法捕捉、grooming、與 sprint 規劃**這三層。後果是：

- 想法散落在對話、便利貼、記憶中，沒有單一可信來源
- 沒有時間盒（time-box）規劃機制，容易戰術性勝利但戰略性飄移
- AI agents（Antigravity, Gemini CLI, Claude Code）無法協助 backlog 管理，因為沒有結構化的可讀位置
- WIP 的「One feature at a time」原則只是文字宣告，沒有機械強制

本 change 在 `openspec/` 下加一層輕量 backlog 系統，並透過兩個新命令 `/opsx:capture` 與 `/opsx:plan` 將其接入既有 OpenSpec 工作流，使 ideas → ready → sprints → changes → archive 形成完整鏈路。

## What Changes

### New Capabilities
- **backlog**: 全新 capability，包含目錄結構、模板、grooming/planning 流程
- **`/opsx:capture` 命令**: 將想法寫入 `openspec/backlog/ideas/<slug>.md`
- **`/opsx:plan` 命令**: 開新 sprint，從 `ready/` 挑卡片產生 sprint 文件

### Modified Capabilities
- **OpenSpec workflow（既有）**: `/opsx:propose` 加上硬性 WIP=1 檢查與 slug 連續性檢查；`/opsx:archive` 在歸檔時 `git rm` 對應的 ready 卡片；`/opsx:plan` 開新 sprint 前要求上一 sprint 已完成 retro

### New Files
- `openspec/backlog/`（含 `ROADMAP.md`、`_templates/item.md`、`_templates/sprint.md`、`ideas/.gitkeep`、`ready/.gitkeep`、`sprints/.gitkeep`、`sprints/archive/.gitkeep`）
- `.agent/workflows/opsx-capture.md`、`.agent/workflows/opsx-plan.md`
- `.gemini/commands/opsx/capture.toml`、`.gemini/commands/opsx/plan.toml`
- `.claude/commands/opsx-capture.md`、`.claude/commands/opsx-plan.md`
- `.agent/skills/openspec-capture/SKILL.md`、`.agent/skills/openspec-plan/SKILL.md`
- `.gemini/skills/openspec-capture/SKILL.md`、`.gemini/skills/openspec-plan/SKILL.md`

### Modified Files
- `omni-agent/AGENT.md`: 新增 §7.5 Backlog & Sprint Workflow；§6 強化 WIP 規則；§7 命令表擴充
- `.agent/workflows/opsx-propose.md`、`.gemini/commands/opsx/propose.toml`、`.claude/commands/opsx-propose.md`: 加入 WIP=1 硬性檢查與 slug 連續性檢查
- `.agent/workflows/opsx-archive.md`、`.gemini/commands/opsx/archive.toml`、`.claude/commands/opsx-archive.md`: 加入 archive 完成後 `git rm` 對應 ready 卡片的步驟

## Capabilities

### New
- `backlog`: Lightweight Agile backlog & sprint layer on top of OpenSpec

### Modified
- `openspec-workflow`（透過命令層更新）: 接入 backlog 流程，加入 WIP 強制與 slug 連續性

## Impact

- **Repo 結構變更**: `openspec/` 下新增 `backlog/` 子樹，但 OpenSpec CLI（`openspec list/status/instructions`）行為完全不受影響
- **AGENT.md 變更**: 新增一節，是 agent 行為的 source of truth，所有後續開發必須遵循
- **AI agents 行為變更**: 三個既有命令（`propose`、`archive`、`plan`）行為調整，新增兩個命令（`capture`、`plan`）；任何 propose 行為都會先檢查 WIP=1 與 ready 卡片存在
- **無 runtime 服務影響**: 不動 Brain/Gateway/Skills/DB schema/SOUL.md
- **無 secure-gateway 影響**: 本 change 僅限 OmniAgent repo

## Open Questions（已於對話中解決，列此供 archive 追溯）

- ✅ Q1 完成的 ready 卡片如何處理？→ **不保留，archive 時 `git rm`，靠 `changes/archive/` 追溯**
- ✅ Q2 `/opsx:plan` 中途起 sprint 的行為？→ **拒絕，上一 sprint 未 retro 不能 plan 新的**
- ✅ Q3 ROADMAP.md 初始內容？→ **Seed 當前計畫已完成：Phase 5 (Family Preference Awareness, 2026 Q2) + Phase 6 (AAAK Memory Compression, 2026 Q3) 內容由 Icekimo 提供並寫入 design.md，可直接使用**
- ✅ Q4 Domain pre-commit hook？→ **不加，保持輕量**
- ✅ Q5 `/opsx:capture` CLI 旗標？→ **兩者皆可，旗標缺略則對話補齊**
- ✅ Q6 `/opsx:retro` 命令？→ **未來加，本輪預留 hook 位置**

## 需後續確認的內容

（無）ROADMAP 內容已於 design.md 完整 seed，apply 階段可直接套用。
