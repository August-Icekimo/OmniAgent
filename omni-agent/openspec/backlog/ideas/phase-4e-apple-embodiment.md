---
slug: phase-4e-apple-embodiment
status: idea
domain: gateway, skills
size: L
priority: P1
created: 2026-05-11
---

# Phase 4E — Apple Embodiment

## Why

BlueBubbles 是 Phase 1 的權宜方案，透過 Mac 上的非官方 API 橋接 iMessage，
存在被 Apple 封號的風險，且功能受限於純文字、無法觸及 Apple 生態的完整能力。

iPhone SE 3 (2022) 是一台完整的 Apple 裝置，原生支援 iMessage、FaceTime、Mail、
Shortcuts、Apple Intelligence Actions，且擁有 GPS、陀螺儀、加速度計等物理感測器。
把它交給 Cindy 使用，等於讓她從「只有腦子的 AI」進化為「長出身體的 Agent」——
她不只能說話，還能感知物理世界、觸及 Apple 生態的所有通道。

這是 Cindy 從 assistant 走向 embodied agent 的關鍵一步。

## What (high-level)

用 iPhone SE 3 作為 Cindy 的物理載體（embodiment），採用 **Hybrid 架構**：
**Swift app（常駐核心）+ Shortcuts Automation（iMessage 橋接）**。

### Gateway 層：Apple 生態通道
- **iMessage**: 透過 Shortcuts Automation 收發（Apple 不開放 iMessage API 給第三方 app）
- **Mail**: 讀取/發送 email，作為正式通訊管道
- ~~**FaceTime**~~: **排除** — Apple 未開放任何程式化控制 API，技術不可行

### Skills 層：物理感測器界面（Swift app 原生存取）
- **GPS 定位**: CoreLocation — Cindy 知道自己在哪裡，可回報位置、地理圍欄觸發
- **陀螺儀 / 加速度計**: CoreMotion — 姿態感知，安防場景（裝置被移動偵測）
- **相機**: AVFoundation — 按需拍照/掃描（未來可延伸視覺感知）
- **麥克風**: AVFoundation — 環境音偵測（未來可延伸聽覺感知）

### Hybrid 通訊架構

```
┌─────────────────────────────────────────────────┐
│  iPhone SE 3 — Cindy's Body                     │
│                                                 │
│  ┌──────────────────────┐                       │
│  │  CindyAgent.app      │ ← Swift 原生 app      │
│  │  (Background Mode)   │                       │
│  │  · CoreLocation GPS  │                       │
│  │  · CoreMotion 陀螺儀  │                       │
│  │  · HTTP/WS → Brain   │                       │
│  │  · APNs listener     │                       │
│  │  · App Intents 暴露   │ ←── Shortcuts 可呼叫  │
│  └──────────┬───────────┘                       │
│             │ App Intents                        │
│             ▼                                    │
│  ┌──────────────────────┐                       │
│  │  Shortcuts Automation │ ← iMessage 橋接層     │
│  │  · Trigger: 收到 msg  │                       │
│  │  · Action: call app  │                       │
│  │  · Action: send msg  │                       │
│  └──────────────────────┘                       │
└───────────────────────┬─────────────────────────┘
                        │ HTTPS / WebSocket
                        ▼
              Security Gateway (Synology)
                        │
                        ▼
              Go Gateway (Debian)  ← 新增 apple handler
                        │
                        ▼
                   Brain (Python)
```

### iMessage 資料流

```
收訊: 家人 iMessage → Shortcuts trigger → App Intent → CindyAgent.app → Gateway → Brain
回覆 (Phase 1, 免費帳號): Brain → Gateway → CindyAgent.app (HTTP polling) → 觸發 Shortcuts "Send Message" → iMessage 送出
回覆 (穩定後, Developer Program): Brain → APNs push → CindyAgent.app → 觸發 Shortcuts "Send Message" → iMessage 送出
```

## Resolved Decisions

| 決策 | 結論 | 理由 |
|------|------|------|
| Apple ID | ✅ Cindy 獨立 iCloud 帳號 | 隔離家人帳號，獨立身分 |
| FaceTime | ❌ 排除 | Apple 無任何程式化控制 API |
| 架構 | Hybrid (Swift + Shortcuts) | Shortcuts 壟斷 iMessage 收發；Swift 壟斷感測器 + 背景常駐 |
| 螢幕常亮 | 否 | Background Location Mode 即可維持 app 活躍 |
| Developer Program | 分階段：初期免費帳號（7 天重簽），穩定一季後升級 $99/yr | 開發期重簽頻率本來就高，免費帳號夠用；APNs 等穩定後再解鎖 |
| Swift 開發 | 自學 SwiftUI + AI 輔助 (Cursor/Gemini) | 部署環境與硬體已就位，可直接開始實測 |
| 電池管理 | 80% 充電上限 | iOS 內建「最佳化電池充電」+ 80% 上限設定 |
| Repo | 獨立子專案 `cindy-sense` (`/home/icekimo/gitWrk/cindy-sense`) | 不同物理節點 = 不同 repo（同 secure-gateway 慣例）；Xcode 工具鏈與 Go/Python 不混 |

## Acceptance hints
- CindyAgent.app 可背景常駐超過 24hr 不被系統殺掉
- 透過 Shortcuts 收到 iMessage 後 < 10s 內訊息抵達 Brain
- Brain 回覆 → CindyAgent.app → Shortcuts 發 iMessage，家人可正常收到（Phase 1 用 HTTP polling）
- GPS 定位資料可透過 Gateway 回報至 Brain
- Go Gateway 新增 apple handler，格式符合 StandardMessage 規範
- 免費帳號 7 天重簽流程可在 < 5min 內完成（Xcode 一鍵）
- BlueBubbles handler 可在 4E 穩定運行後安全移除

## Open questions
- Shortcuts "Send Message" 的 rate limit 具體數字不明，
  需實測 Cindy 日常回覆量是否會觸發 Apple 限流。
- App Intents 在 Shortcuts trigger 和 Swift app 之間的資料傳遞格式：
  JSON string? 結構化 Intent parameter?

## Cross-Workspace Map (Phase 4E 後)

| Repo | Path | Node | Role |
|------|------|------|------|
| **OmniAgent** | `/home/icekimo/gitWrk/OmniAgent` | Debian 13 | Brain + Senses (Go gateway + Python brain) |
| **secure-gateway** | `/home/icekimo/gitWrk/secure-gateway` | Synology NAS | Front-door security |
| **cindy-sense** | `/home/icekimo/gitWrk/cindy-sense` | iPhone SE 3 | Apple Embodiment (Swift app + Shortcuts 橋接) |

## Links
- Roadmap: openspec/backlog/ROADMAP.md (建議下次更新時加入 Phase 4E section)
- Related spec: openspec/specs/gateway/spec.md
- Related idea: openspec/backlog/ideas/bluebubbles-deprecation-plan.md
- Technical analysis: (conversation 1d295e31 artifacts/shortcuts_vs_swift_analysis.md)
- Depends on: (none — 可獨立啟動，完成後觸發 BB deprecation)
