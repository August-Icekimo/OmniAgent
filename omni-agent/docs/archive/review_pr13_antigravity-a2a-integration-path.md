# PR #13 Review — A2A Specialist Agent（ADK 2.0 Foundation, W26 PoC）

> Reviewer: Claude Code ／ Date: 2026-07-02
> PR: [#13 feat(a2a)](https://github.com/August-Icekimo/OmniAgent/pull/13)（DRAFT, main ← feat/antigravity-a2a-integration-path, +741/−1, 12 files）
> 對照文件：[change_antigravity-a2a-integration-path.md](change_antigravity-a2a-integration-path.md)（v1.2）

## 總評

**建議：Approve（可轉 ready for review / merge），無阻擋性 bug。**
實作與提案 6 個 task 的 AC 逐條對得上，安全模式忠實鏡像 sandbox 先例，錯誤處理
（缺 env、逾時、降級）符合 terminal.py 既有 pattern。以下發現 1 個 Medium 邊界
案例與數個 Minor/Info 項，皆可 merge 後跟進。

## 提案 vs 實作 對照

| Task | 提案 AC | 實作 | 判定 |
|---|---|---|---|
| 1 容器骨架 | read_only/tmpfs/mem/pids/no-new-priv/無 env_file/不發布 port/共享 volume | compose.yml `agy` service 逐項具備；另加分項：非 root UID 10002 + 預建 `/a2a-workspace` 擁有權讓 named volume 繼承 | ✅ |
| 2 ADK agent + A2A server | A2A endpoint + Agent Card + 摘要能力 + 獨立可驗 + 缺 key fail-fast | `to_a2a()` 原生橋自動掛 JSONRPC + well-known card；`agy_server.py` 啟動即檢查 key、訊息清楚；`test_summarize.py` 不經 brain 可驗 | ✅ |
| 3 Brain client + tool | ToolSpec 註冊、single-turn 往返、缺 URL 明確錯誤、逾時降級 | `specialist.py` 仿 SANDBOX_URL pattern；60s client 逾時 < 300s turn 逾時（實查 `TURN_PROCESSING_TIMEOUT`，主張成立） | ✅ |
| 4 De-id + auth | 姓名遮蔽、單一 secret、key 不入 log | `redact_names`（長名先換防子字串殘留）；compose 僅注入 `AGY_GEMINI_API_KEY`→`GEMINI_API_KEY`；health/log 皆只回布林 | ✅（範圍註記見 M3） |
| 5 429 breaker | 429→open 5hr→half-open→close，落 DB crash-safe，通知 admin | `specialist_breaker.py`：`home_context` kv（實查 schema：key PK + jsonb value + updated_at，upsert 正確）；admin 查詢與 `proactive.py:75/99` 逐字一致 | ✅（邊界見 M1） |
| 6 端到端驗證 | 委派往返 + read_only + 資源限制 + volume 交換 | 文件誠實記錄：機制全驗通過；planner「自動選用」因既有 provider 退化（Gemini 403/quota）未能乾淨示範 | ✅（殘留風險見 I5） |

程式碼層面另驗證過：`model_router._db_pool` 屬性存在（router.py:22）、
`execute_tool` 由 graph.py:343 傳入 router、`users.name`/`telegram_accounts.chat_id`
schema 與 SQL 相符、asyncpg jsonb 回 str 的容忍（`_as_dict`）與 main.py 現行用法一致。

## Findings

> **2026-07-02 更新：M1–M4 已於 merge 前修正**（同分支 follow-up commit）。
> M1/M4 → `specialist_breaker.py`（fail-open + DB CAS 唯一試打權 + stale 重搶窗）、
> M2 → `tools.py`（breaker 檢查移到 de-id 查詢前）、
> M3 → change doc Task 4 明示 de-id 範圍（schema 無 alias 來源，已查證）。
> I1–I5 維持 merge 後跟進。

### M1（Medium）breaker 可能永久卡在 open

`specialist_breaker.py` `allow()`：`state == "open"` 但 `open_until` 缺失或
parse 失敗時回 `(False, False)` — **永不進入 half-open**，委派永久降級，只能手動
改 DB 解鎖。雖然 value 是我們自己寫的（機率低），但 breaker 這種安全機制建議
fail-open：parse 失敗時視為 half-open（放行一次試打）並 log warning。

```python
if ou is None or _now() >= ou:
    return True, True   # 無法判讀到期時間 → 視為 half-open，不永久鎖死
```

### M2（Minor）de-id 名單查詢在 breaker 檢查之前

`tools.py` `execute_tool`：breaker open 期間每次委派仍先跑一次
`SELECT name FROM users` 再被 breaker 擋下。把 `breaker.allow()` 移到 redact
之前可省無效查詢，語意也更直觀（先問能不能送、再整理要送什麼）。純效率，不影響正確性。

### M3（Minor）de-id 只遮「users 表的精確姓名」

`redact_names` 僅做 `users.name` 的字面替換。暱稱、稱謂（「爸爸」「妹妹」）、
電話等其他識別資訊不在範圍內；且 planner 組 task 參數時可能改寫過原文。以
PoC 的「容器邊界即隱私邊界 + 內容最後一道遮蔽」定位可接受，但提案 AC 寫的是
「家人姓名/識別資訊」，建議在 change doc 或未來 card 明示目前只覆蓋姓名字面。

### M4（Minor）half-open 併發放行不只一次

兩個 turn 同時委派、都落在 `open_until` 之後 → 都拿到 `half_open=True`、都打
AGY。家庭規模 + 5hr 窗口下實害趨近零，記錄備查即可（若要修，DB 端 compare-and-set
`state=half_open` 一行可解）。

### I1（Info）breaker 每次 re-trip 都會再通知 admin

額度長期耗盡時，每 5hr 的 half-open 失敗會重發一次 Telegram。當提醒功能算合理，
當噪音就加「已通知過則略過」。先觀察實際頻率再決定。

### I2（Info）Agent Card 公告 `http://agy:8000`，host 端測試會斷在 RPC 步驟

`AGY_HOST` 預設 `agy`：compose 內網正確；但從 host 跑 `test_summarize.py`
（`AGY_TEST_URL=localhost`）時 card 解析回 `agy` 主機名、RPC 會連不上。文件已寫
「在 agy 容器內執行」，維持即可；或在 test script 註解點明這個限制。

### I3（Info）agy 與 postgres 同在預設 compose 網路

compromised AGY 在網路層可達 `postgres:5432`（無 credential，僅連通性）。這與
sandbox 現況一致、非本 PR 引入；未來 hardening 可考慮獨立 network segment
（注意 agy 需要對外連 Gemini API，不能 `internal: true` 一刀切）。

### I4（Info）agy 無 compose healthcheck

現況只有 postgres 有 healthcheck，agy 不加是一致的；但 `/health` 端點和 curl
都已備好，加一個 healthcheck block 成本極低，可順手補。

### I5（Info）planner 自動選用 delegate_to_specialist 尚未實證

Task 6 附註已誠實記錄：機制驗通、但 planner 自動選用因 Gemini 403/quota 退化
無法示範。這是 merge 後的已知殘留 — 建議在 Gemini provider 修復後補一次實測，
避免「tool 掛著但 planner 從不選它」的沉默失效。

> **✅ RESOLVED（2026-07-02）**：修復 provider chain 後實證通過。根因：routing_config
> 的 claude model `claude-3-5-sonnet-20241022`（2025-10-28 退役）與 client 預設
> `claude-sonnet-4-20250514`（2026-06-15 退役）皆 404 → 換 `claude-sonnet-4-6`；
> Gemini API Key 直打已恢復（先前 403/quota 屬暫時性退化）。實測（真 SOUL.md prompt +
> TOOL_SPECS + tool_choice=auto）：Claude 口語/明確摘要 2/2 自動選用
> delegate_to_specialist；Gemini 明確摘要選用、口語短文自行摘要（合理判斷，非缺陷）。

## 加分項（值得保留的做法）

- **fail-fast 順序正確**：`agy_server.py` 在 import ADK 之前完成 env 正規化與缺 key 檢查。
- **Dockerfile volume 擁有權技巧**：image 內先 `chown` 掛載點，讓空 named volume 初始化繼承，非 root 可寫 — 這類 rootless podman 細節容易踩坑，註解也寫清楚了。
- **`read_workspace_file` 的 `os.path.basename` 防路徑穿越**，對 read_only 容器仍守住 volume 邊界。
- **降級訊息全走 `{"success": False, "error": ...}` 統一形狀**，與既有 skill 一致，planner 可讀。

---

## ADK / SDK 選型調查（依 review 要求）

### 版本現況（2026-07-02 實查 PyPI）

| 套件 | 最新版 | 本 PR 採用 | 說明 |
|---|---|---|---|
| `google-adk` | **2.3.0** | `>=2.3,<3` | `[a2a]` extra 釘 `a2a-sdk>=0.3.4,<0.4`（最新版仍如此） |
| `a2a-sdk` | **1.1.0** | `>=0.3.4,<0.4` | 1.x 改寫 server API（移除 `a2a.server.apps`），ADK `to_a2a` 尚未跟進 |

**結論：PR 釘 0.3.x 不是保守，是被迫且正確** — 只要用 ADK 原生 A2A 橋，就沒有
1.x 的選項。提案 v1.2 的「實作期修正」註記與 PyPI 現況相符。

### 選項比較

| 選項 | 優點 | 缺點 | 判定 |
|---|---|---|---|
| **(A) ADK 2.0 + `to_a2a` 橋 + a2a-sdk 0.3.x**（本 PR） | agent loop / tool-calling / Agent Card 全部白拿（agent.py 僅 51 行）；single-turn Task API 內建；未來 multi-turn / workflow 是 ADK 原生能力，不用重寫 | 釘死 a2a-sdk 0.3（A2A spec 0.3 線路協定，非 spec 1.0）；brain 與 agy 必須 lockstep 升級；ADK 依賴樹重（僅限 agy 容器，brain 不受累） | ✅ 採用，正確 |
| (B) 裸 a2a-sdk 1.1.0 server（不用 ADK） | 直上 spec 1.0、跟上生態系主線；依賴輕 | 要手刻 agent loop + tool-calling + Task 狀態機（google-genai 裸寫），PoC 成本翻倍；ADK 未來跟進 1.x 時等於白做 | ❌ 不划算 |
| (C) 純 FastAPI microservice（不用 A2A） | 最少依賴、最直觀 | 失去協定標準化 — roadmap 明列 Hermes / 外部 agent 對接，屆時要重做介面；Agent Card / task 語意全部自訂 | ❌ 與 Phase 5.9 方向相悖 |
| (D) subprocess CLI / Antigravity SDK | —（idea 卡 D1–D4 已排除：CLI #76/#7 bug、SDK preview 不穩且無 OAuth） | — | ❌ 前提已排除 |

### Client 端選型（提案 Open Question 的收斂）

提案留了「獨立 a2a-sdk client vs ADK 內建 client」待決；PR 實際採 **a2a-sdk client**。
這是對的：brain 只需要 client，不必把整個 `google-adk` 依賴樹拉進 brain image；
`a2a-sdk`（無 extra）很輕。建議把這個決定回寫進 change doc 的 Open Questions
（標記 resolved），歸檔時不留懸案。

### 升級路徑（watch item）

1. **觸發點**：`google-adk` 釋出支援 `a2a-sdk>=1.0` 的版本（追蹤
   [google/adk-python](https://github.com/google/adk-python) releases）。
2. **動作**：brain 與 agy 兩邊 requirements **同時**解鎖到 1.x — 線路協定
   （spec 0.3 vs 1.0）不保證互通，不可只升一邊。
3. **遷移成本預估：低**。brain 用的 `ClientFactory`/`ClientConfig`/
   `A2ACardResolver` 是 0.3 引入的新式 client API，1.x 延續同一套介面
   （升級時仍需實測）；agy 端 `to_a2a()` 介面由 ADK 收斂，跟著 ADK 升即可。
4. **風險上限**：兩容器、兩個 requirements 檔、一個 wire protocol — 影響面封閉，
   不會外溢到 gateway / DB。

### 依賴面總結

- agy 容器：`google-adk[a2a]` 重（含完整 ADK runtime），但隔離在專用 image，可接受。
- brain：只加 `a2a-sdk>=0.3.4,<0.4` 一行，httpx 沿用既有依賴，增量極小。✅
- 兩邊版本註解都有寫明配對原因與日期，未來人（包括未來的 Claude）可考。✅

---

## 建議的 merge 前後動作

**Merge 前（可選，皆非阻擋）：**
1. 修 M1（breaker parse 失敗 fail-open）— 3 行，建議順手。
2. M2 調整 breaker/de-id 順序 — 2 行搬移。

**Merge 後跟進：**
3. Change doc Open Questions 收斂：client 選型已定（a2a-sdk client）、admin 通知管道已定（proactive 同款查詢），標 resolved 後走 `/opsx-archive`。
4. I5：Gemini provider 修復後補驗 planner 自動選用。
5. Backlog 候選：a2a-sdk 1.x 升級 watch card（觸發條件寫明「ADK 支援 1.x」）。
