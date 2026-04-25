## Context

To reduce costs and utilize existing Gemini Advanced subscriptions, we need to authenticate via OAuth 2.0. This allows the agent to use the subscription quota instead of pay-per-token API keys.

## Goals

- Primary use of OAuth-based Gemini Pro.
- Automatic token refresh without human intervention.
- Safe fallback to API key if OAuth fails.

## Decisions

### DB-Based Token Cache
We use a PostgreSQL table `oauth_tokens` to store the `access_token` and its `expiry_ms`. This ensures that:
1. Containers are stateless regarding current session tokens.
2. Multiple brain instances can share the same token.
3. Refreshing is handled once for all instances (atomic update).

### OAuth Refresh Logic
- The `OAuthGeminiClient` checks the expiry before every request.
- If expired, it performs a POST to Google's token endpoint.
- Uses `SELECT FOR UPDATE` (or similar DB guard) to prevent concurrent refresh storms.

### Fallback Mechanism
- The `ModelRouter` catches `OAuthRefreshError`.
- It automatically retries the request using the `GeminiClient` (API key).
- This ensures high availability even if the subscription token is temporarily revoked or network-blocked.

## Risks / Trade-offs

- **Risk**: `refresh_token` expiration or revocation.
  - **Mitigation**: Fallback to API key and log warning for manual intervention.
- **Trade-off**: Slightly higher latency on the first request after token expiry due to refresh round-trip.
