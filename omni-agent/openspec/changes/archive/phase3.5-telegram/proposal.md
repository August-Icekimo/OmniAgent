## Why

To add Telegram Bot as the second primary messaging channel for Omni-Agent. Telegram is positioned as the "HomeLab Management + Family Backup Channel," which alleviates the 3-second timeout pressure from LINE and provides a foundation for proactive notifications in Phase 4.

## What Changes

- `gateway/internal/handler/telegram.go`: New handler for Telegram webhooks.
- `gateway/cmd/server/main.go`: Registration of `/webhook/telegram` route.
- `.env.example`: Added Telegram configuration variables.

## Capabilities

### Modified Capabilities
- `gateway`: Added support for Telegram messaging channel, including webhook handling, secret token validation, and StandardMessage conversion.

## Impact

- Requires a valid Telegram Bot Token and Webhook Secret.
- Requires a public HTTPS URL (or tunnel) for Telegram to push updates.
- Initial implementation uses a whitelist (`TELEGRAM_ALLOWED_CHAT_IDS`) in environment variables (later moved to DB).

## Open Questions

- `F-04-B` Idempotency: Currently relies on Telegram's webhook confirmation; no explicit DB-level deduplication implemented yet.
- `F-03-A` DB management for chat_id: Handled in Phase 4.
