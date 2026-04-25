## Why

Omni-Agent (Cindy) currently calls the Gemini API using a `GEMINI_API_KEY` (pay-per-token billing). Icekimo holds a paid Google One AI Premium / Gemini Advanced subscription whose quota is accessible via OAuth 2.0 credentials. This phase adds an `OAuthGeminiClient` to the Brain service so that Cindy uses the Pro subscription quota by default, falling back to the API key only when OAuth refresh fails.

## What Changes

- `OAuthGeminiClient` implementation
- Token refresh logic
- PostgreSQL access-token cache (`oauth_tokens` table)
- `.env` variable `GEMINI_REFRESH_TOKEN`
- Routing config update to prefer OAuth provider
- Fallback to `GEMINI_API_KEY`

## Capabilities

### Modified Capabilities
- `llm`: Added `OAuthGeminiClient` to support Google One AI Premium subscription quota, providing high-quality Pro model access without direct per-token billing.

## Impact

- `refresh_token` in `.env` must be valid and not revoked.
- Google OAuth 2.0 token endpoint must be reachable from the Brain container.
- Existing `GeminiClient` (API key path) remains as a fallback.
- `gemini-2.5-pro` is the target model for the OAuth provider.

## Open Questions

(None)
