# Terminal Viewer — secure-gateway 相依（外部專案）

> 本檔說明 **OmniAgent 之外** 需在 `~/gitWrk/secure-gateway`（Caddy 邊緣代理）
> 完成的設定。OmniAgent 本身不含任何 OAuth / 瀏覽器 session 程式碼 —— 對外門禁
> 一律由 Caddy 的 caddy-security（Google OAuth + JWT）把關。

## 為什麼需要

`brain:8000` 預設只在 compose 內網可達。終端機 viewer（`GET /terminal/view/{task_id}`
與 `WS /terminal/ws/{task_id}`）要讓使用者從手機點聊天連結開啟，必須由 Caddy 新增一條
**auth 保護**的反向代理路由指向 `brain:8000`。

依設計決定，viewer **複用既有的 `cindy.{$DOMAIN_NAME}` subdomain**，
`CINDY_VIEWER_BASE_URL` = `https://cindy.{$DOMAIN_NAME}`。

## ⚠️ 既有 `cindy.` 區塊刻意無 auth

`cindy.{$DOMAIN_NAME}` 目前只保留 CrowdSec、移除 WAF 與 Auth（因為它服務 LINE/Telegram
webhook，webhook 不能被 OAuth 擋）。因此 **不能** 把整個 subdomain 套上 auth，必須只對
新增的 `/terminal*` 路由獨立套用 `admin_policy`，webhook 路由維持原狀。

## Caddyfile 變更範例（在 secure-gateway 套用）

於 `caddy_config/Caddyfile` 的 `cindy.{$DOMAIN_NAME}` site 區塊內，**在** webhook
`handle` 之前加入：

```caddyfile
cindy.{$DOMAIN_NAME} {
    # ...（既有 tls / log / crowdsec 不動）...

    # 終端機 viewer：admin 限定（Google OAuth），反代到 brain:8000
    handle /terminal* {
        authorize with admin_policy
        reverse_proxy {$COCKPIT_SERVER_IP}:8000 {
            # WebSocket 即時串流需正確轉發升級標頭
            header_up Host {host}
            header_up X-Forwarded-Proto {scheme}
        }
    }

    # ↓↓↓ 既有 webhook 路由維持不變（無 auth，僅 CrowdSec） ↓↓↓
    handle /webhook/line* {
        reverse_proxy {$COCKPIT_SERVER_IP}:8086
    }
    # ...（其餘 webhook handle 不動）...

    handle {
        respond "Not Found" 404
    }
}
```

要點：
- `authorize with admin_policy` 沿用 Caddyfile 既有的 admin 授權策略（Cockpit 同款），
  只有 `authp/admin` 角色（即 `ALLOWEDE_GMAIL`）能存取。
- `reverse_proxy` 目標埠是 **8000（brain）**，不是 8086（gateway）。需確認 brain 對 Caddy
  所在網路可達（compose 已 publish `BRAIN_PORT:8000`；或讓 Caddy 與 brain 同網段）。
- caddy-security 的 `authorize` 對 WebSocket 升級請求同樣會放行（驗證 JWT cookie），
  `reverse_proxy` 預設支援 `Connection: Upgrade`，無需額外 `@websocket` matcher。
- 套用後 `reload` Caddy（見 secure-gateway `Reload_SOP.md`）。

## 完整資料流

```
使用者(LINE/Telegram) ──訊息──▶ gateway:8086 ──/chat──▶ brain
                                                          │
                          terminal 技能 ─HTTP─▶ sandbox:8000 /exec
                                                          │  原始 ANSI log
                                                          ▼
                                          共享 volume `terminal-logs`
                                          /sandbox/logs (sandbox 寫)
                                          /terminal-logs (brain 讀/清)
                          ◀── 聊天：精簡摘要 + [📄 連結] ──┘
                                          （連結帶 24h 簽名 token）

使用者點連結(手機瀏覽器)
   │  https://cindy.{DOMAIN}/terminal/view/<task_id>?t=<token>
   ▼
Caddy(secure-gateway)  ──Google OAuth admin_policy──▶ 通過
   │  reverse_proxy → brain:8000
   ▼
brain  ── verify HMAC token(綁 task_id, 24h) ──▶ 回 viewer HTML(xterm.js)
   │
   └─ WS /terminal/ws/<task_id> ── tail 共享 volume log ──▶ 即時串流上色
```

## OmniAgent 端對應環境變數（見 `.env.example`）

| 變數 | 用途 |
|------|------|
| `TERMINAL_VIEW_SECRET` | viewer token 的 HMAC 金鑰（必填） |
| `CINDY_VIEWER_BASE_URL` | = `https://cindy.{$DOMAIN_NAME}`；未設定則聊天只回摘要 |
| `TERMINAL_VIEW_TOKEN_TTL` | token 壽命秒數（預設 86400 = 24h） |
| `TERMINAL_LOG_RETENTION_DAYS` | log 保留天數（預設 7） |
| `TERMINAL_LOG_CLEANUP_INTERVAL` | 清理週期秒數（預設 86400） |
| `LOG_ROOT` / `TERMINAL_LOG_DIR` | 共享 volume 在 sandbox / brain 的掛載路徑（compose 已寫死） |
