## 1. Directory Scaffolding

- [x] 1.1 S-01 建立 `openspec/backlog/` 目錄樹
  - [x] AC: `openspec/backlog/{ideas,ready,sprints,sprints/archive,_templates}/` 全部存在
  - [x] AC: 各目錄含 `.gitkeep` 檔以便 git 追蹤空目錄
  - [x] AC: `openspec list --json` 輸出與套用前相同（CLI 未受影響）
- [x] 1.2 S-02 建立 `_templates/item.md` 與 `_templates/sprint.md`
  - [x] AC: `item.md` 含 frontmatter 範例（slug/status/domain/size/priority/created）與 6 個 body section
  - [x] AC: `sprint.md` 含 Window/Theme/Capacity/Goals/Committed/Stretch/Out of scope/Retro
  - [x] AC: 兩個模板皆可被讀取且 markdown 解析合法

## 2. ROADMAP

- [x] 2.1 S-03 建立 `openspec/backlog/ROADMAP.md`（含 Phase 5/6 真實主題，內容見 design.md §4）
  - [x] AC: 檔案存在並含 Q2 (Phase 5 Family Preference Awareness)、Q3 (Phase 6 AAAK Memory Compression)、Q4 (TBD) 三個季度區塊
  - [x] AC: 含 Long-term Direction 段落，包含 People-centric awareness 與 Memory as native cognition 兩條主軸
  - [x] AC: Phase 5 與 Phase 6 各列至少 4 個 candidate epics，且每個 epic 標註 Domain
  - [x] AC: 內容 byte-identical 於 design.md §4 提供的 markdown 區塊（複製貼上即可）

## 3. New Command: /opsx:capture

- [x] 3.1 F-01 `.agent/workflows/opsx-capture.md`
  - [x] AC: 檔案存在並含 frontmatter `description`
  - [x] AC: 步驟覆蓋：slug 推導 → 衝突檢查 → 缺欄位互動補齊 → domain 驗證 → 寫檔 → 確認輸出
  - [x] AC: 支援 CLI 旗標 `--domain --why --what`，缺則對話補齊（Q5 決策）
- [x] 3.2 F-02 `.gemini/commands/opsx/capture.toml`
  - [x] AC: TOML 格式合法且 `description` 與 `prompt` 欄位齊備
  - [x] AC: 步驟內容與 `.agent/` 版本語意等價
- [x] 3.3 F-03 `.claude/commands/opsx-capture.md`
  - [x] AC: 檔案格式與既有 `.claude/commands/opsx-propose.md` 風格一致（無 TodoWrite 引用）
  - [x] AC: 步驟內容與 `.agent/` 版本語意等價
- [x] 3.4 F-04 `.agent/skills/openspec-capture/SKILL.md` 與 `.gemini/skills/openspec-capture/SKILL.md`
  - [x] AC: YAML frontmatter 含 `name/description/license/compatibility/metadata` 五欄位
  - [x] AC: 兩檔內容除 `compatibility` 環境差異外完全相同
  - [x] AC: `description` 中明確指出何時觸發此 skill

## 4. New Command: /opsx:plan

- [x] 4.1 F-05 `.agent/workflows/opsx-plan.md`
  - [x] AC: 步驟覆蓋：上一 sprint retro 檢查 → 當前 ISO week 計算 → ready 卡片掃描 → AskUserQuestion 互動（goals/committed/stretch/oos/capacity）→ 視窗計算 → 移動舊 sprint 到 archive → 寫 sprint 檔 → 更新 ready 卡片 status
  - [x] AC: 上一 sprint retro 為空時 abort 並列出 sprint 路徑（Q2 決策）
  - [x] AC: 無 ready 卡片時 abort 並提示先 explore
  - [x] AC: 同一週 sprint 已存在時 abort 並列出既存路徑
- [x] 4.2 F-06 `.gemini/commands/opsx/plan.toml`
  - [x] AC: TOML 格式合法
  - [x] AC: 步驟內容與 `.agent/` 版本語意等價
- [x] 4.3 F-07 `.claude/commands/opsx-plan.md`
  - [x] AC: 步驟內容與 `.agent/` 版本語意等價
- [x] 4.4 F-08 `.agent/skills/openspec-plan/SKILL.md` 與 `.gemini/skills/openspec-plan/SKILL.md`
  - [x] AC: YAML frontmatter 結構正確
  - [x] AC: 兩檔內容除 `compatibility` 外完全相同

## 5. Modified Command: /opsx:propose（加入 WIP=1 與 sprint 連續性檢查）

- [x] 5.1 F-09 在 `.agent/workflows/opsx-propose.md` 加入 Pre-flight Check A（WIP=1 硬性檢查）
  - [x] AC: 步驟描述執行 `openspec list --json` 並計數非 archived 的 changes
  - [x] AC: count ≥ 1 時 abort 並印出既存 active change 名稱
  - [x] AC: 文件明示無 `--force` override（Q5 決策）
- [x] 5.2 F-10 在 `.agent/workflows/opsx-propose.md` 加入 Pre-flight Check B（slug 連續性）
  - [x] AC: 步驟描述讀取最新 sprint 檔的 Committed/Stretch 表
  - [x] AC: 提案的 slug 不在表中時 abort
  - [x] AC: slug 僅在 Stretch 時要求使用者確認後才繼續
  - [x] AC: 提案成功後將 `ready/<slug>.md` 的 status 更新為 `in-progress`
- [x] 5.3 F-11 同步更新 `.gemini/commands/opsx/propose.toml` 與 `.claude/commands/opsx-propose.md`
  - [x] AC: 三個檔案的 Pre-flight Check A/B 步驟語意完全一致
  - [x] AC: 修改在同一 commit 提交（避免 parity drift）

## 6. Modified Command: /opsx:archive（加入 git rm ready card）

- [x] 6.1 F-12 在 `.agent/workflows/opsx-archive.md` 加入 Step 5.5
  - [x] AC: 步驟描述：在歸檔成功後檢查 `openspec/backlog/ready/<slug>.md` 存在則 `git rm`
  - [x] AC: 找不到對應 ready 卡片時不警告，僅 debug log（容許 legacy/手動 change）
  - [x] AC: 在當前 sprint 檔的 Committed 表對應列加上 `(archived YYYY-MM-DD)` 註記
- [x] 6.2 F-13 同步更新 `.gemini/commands/opsx/archive.toml` 與 `.claude/commands/opsx-archive.md`
  - [x] AC: 三個檔案的 Step 5.5 步驟語意完全一致
  - [x] AC: 修改在同一 commit 提交

## 7. AGENT.md 更新

- [x] 7.1 F-14 §6 Development Rules 加入 WIP limit (hard) 規則
  - [x] AC: 規則明文寫出「max 1 active OpenSpec change」與「no --force override」
  - [x] AC: 規則 grep 'WIP' 在 AGENT.md 全文僅出現於此一處（避免矛盾）
- [x] 7.2 F-15 §7 Workflow Commands 表格加入 capture / plan 兩列
  - [x] AC: 兩列描述為一句話，與其他既有列風格一致
- [x] 7.3 F-16 新增 §7.5 Backlog & Sprint Workflow 整節
  - [x] AC: 含 Pipeline 圖（ASCII），目錄佈局圖，Phase rules 表格，Sprint conventions，Hard rules 五子節
  - [x] AC: Hard rules 至少 5 條，含 `changes/` 必須源自 sprint 卡片、ready/ Open questions 必空、Domain 限 8 種、WIP=1、ROADMAP 主題在被 ready 卡片引用前必須是已 seed 的真實內容（非 TBD/TODO）
  - [x] AC: 章節編號未與既有衝突（§8 維持為 Cross-Workspace Map）
  - [x] AC: 所有內部 cross-reference 仍有效（grep 確認 `§7` 引用無失效）

## 8. Non-Functional & Validation

- [x] 8.1 NF-01 OpenSpec CLI 行為未受影響
  - [x] AC: 套用前後 `openspec list --json` 輸出 byte-identical（除時間戳）
  - [x] AC: `openspec validate`（若存在）不報錯
- [x] 8.2 NF-02 Three-way command parity
  - [x] AC: 對 `.agent/workflows/opsx-{capture,plan,propose,archive}.md`、`.gemini/commands/opsx/{capture,plan,propose,archive}.toml`、`.claude/commands/opsx-{capture,plan,propose,archive}.md` 共 12 個檔案做語意 diff，差異僅在格式包裝
  - [x] AC: AGENT.md §7.5 末段含一句話：「Updates to any opsx command MUST update all three sets in the same commit」
- [x] 8.3 NF-03 Git 歷史保留
  - [x] AC: 所有 idea→ready 移轉、舊 sprint→archive 移轉皆使用 `git mv`
  - [x] AC: ready→archived 採 `git rm`（Q1 決策）
- [x] 8.4 NF-04 ISO week 跨年正確性
  - [x] AC: 模擬 2026-12-30（W53）建立 sprint，檔名為 `2026-W53.md`
  - [x] AC: 模擬 2027-01-04（W01）建立 sprint，檔名為 `2027-W01.md` 而非 `2026-W01.md`
- [x] 8.5 NF-05 Domain 驗證測試
  - [x] AC: `/opsx:capture` 接到 `--domain foo` 時 abort 並提示 8 個合法值
  - [x] AC: `/opsx:capture` 接到 `--domain brain` 時通過驗證

## 9. End-to-End 煙霧測試

- [x] 9.1 IT-01 完整 idea → archive 流程
  - [x] AC: `/opsx:capture test-feature --domain skills --why "smoke test" --what "verify pipeline"` 寫入 `ideas/test-feature.md`
  - [x] AC: 手動將 `ideas/test-feature.md` `git mv` 至 `ready/`，補齊 acceptance hints，清空 open questions
  - [x] AC: `/opsx:plan` 提示 retro 缺失（若有舊 sprint 未收尾）；補完後再執行成功，產生本週 sprint 檔，test-feature 在 Committed
  - [x] AC: `/opsx:propose test-feature` 通過 WIP 與 sprint 雙檢查，建立 `changes/test-feature/`
  - [x] AC: 在 active change 存在的情況下 `/opsx:propose another-feature` 被拒絕
  - [x] AC: `/opsx:archive test-feature` 移動至 `changes/archive/<date>-test-feature/`，且 `ready/test-feature.md` 被 `git rm`，sprint 檔對應列被加上 `(archived <date>)`

## 10. Apply 階段提醒（非可驗收項目，但須在 PR 提交前完成）

- [x] 10.1 ~~Icekimo 替換 ROADMAP.md placeholder 為真實 Phase 5+ 主題~~ → **已於 design.md §4 完成 seed**（Phase 5 Family Preference Awareness + Phase 6 AAAK Memory Compression + Long-term Direction），apply 階段直接複製 design.md §4 的 markdown 區塊即可
- [x] 10.2 PR description 列出本 change 觸及的全部 12 個命令/skill 檔案路徑供 reviewer 確認
- [x] 10.3 Commit 切分建議：(a) backlog 目錄與模板、(b) capture 命令三套、(c) plan 命令三套、(d) propose 命令修改三套、(e) archive 命令修改三套、(f) AGENT.md 更新、(g) ROADMAP.md 真實內容
