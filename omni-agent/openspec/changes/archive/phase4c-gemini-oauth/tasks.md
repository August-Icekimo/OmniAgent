## 1. Database Implementation

- [x] 1.1 Add `oauth_tokens` table to PostgreSQL
  - [x] AC: Given a fresh database, when the Brain migration runs, then the `oauth_tokens` table exists with columns `provider TEXT PRIMARY KEY`, `access_token TEXT`, `refresh_token TEXT`, `expiry_ms BIGINT`, `updated_at TIMESTAMPTZ`.
  - [x] AC: Given the table exists, when Brain reads the `gemini` row, then it returns the stored access token and expiry.
  - [x] AC: Edge case: Given the table exists but has no `gemini` row, when Brain starts up, then it proceeds to refresh immediately without crashing.

## 2. LLM Client Implementation

- [x] 2.1 Implement `OAuthGeminiClient`
  - [x] AC: Given `GEMINI_REFRESH_TOKEN` is set in `.env`, when `OAuthGeminiClient` is instantiated, then it reads the variable and does not require `GEMINI_API_KEY` to function.
  - [x] AC: Given a valid (non-expired) access token exists in the `oauth_tokens` DB row, when `chat()` is called, then the request is sent using that token without calling the refresh endpoint.
  - [x] AC: Given the stored access token is expired (`expiry_ms < now_ms`), when `chat()` is called, then the client calls the Google OAuth refresh endpoint, stores the new token and updated expiry in DB, and proceeds with the request.
  - [x] AC: Given the refresh endpoint returns a new token, when the DB write succeeds, then subsequent calls within the token's lifetime do not trigger another refresh.
  - [x] AC: Edge case: Given the refresh endpoint returns an error (network failure, revoked token), when the exception is caught, then `OAuthGeminiClient` raises a recoverable `OAuthRefreshError` and does NOT silently return an empty response.

## 3. Token Management

- [x] 3.1 Token refresh implementation
  - [x] AC: Given a valid `refresh_token`, when the refresh call is made, then it POSTs to `https://oauth2.googleapis.com/token` with `grant_type=refresh_token`, `client_id`, and `client_secret` (sourced from env or hardcoded gemini-cli public client values).
  - [x] AC: Given a successful refresh response, when the new `access_token` and `expires_in` are returned, then `expiry_ms` is stored as `now_ms + (expires_in * 1000)`.
  - [x] AC: Given a concurrent Brain process also attempts refresh, when both read an expired token simultaneously, then only one refresh call is made (use DB `SELECT FOR UPDATE` or upsert with timestamp guard).
  - [x] AC: Edge case: Given `expires_in` is absent from the response, when storing expiry, then default to `now + 3500 seconds`.

## 4. Routing & Configuration

- [x] 4.1 Wire `OAuthGeminiClient` into `ModelRouter`
  - [x] AC: Given `GEMINI_REFRESH_TOKEN` is present in env, when `ModelRouter` initialises, then `OAuthGeminiClient` is registered as the primary Gemini provider.
  - [x] AC: Given `GEMINI_REFRESH_TOKEN` is absent from env, when `ModelRouter` initialises, then the existing `GeminiClient` (API key) is used as primary with no error.
  - [x] AC: Given `OAuthGeminiClient.chat()` raises `OAuthRefreshError`, when the router handles the exception, then it falls back to `GeminiClient` (API key) and logs a `WARNING` with the reason.
  - [x] AC: Given fallback to `GeminiClient` occurs, when the response is returned, then `routing_reason` in `BrainResponse` reflects `"gemini_oauth_fallback"`.
- [x] 4.2 Update `routing_config.json`
  - [x] AC: Given the updated `routing_config.json`, when parsed, then a `gemini_oauth` provider entry exists with `auth_type: "oauth"` and `model: "gemini-2.5-pro"`.
  - [x] AC: Given `gemini_oauth` is the primary provider, when `routing_config.json` is loaded, then the fallback order is `gemini_oauth → gemini_apikey → claude → local`.

## 5. Security & Performance

- [x] 5.1 Security — no credential leakage
  - [x] AC: Given any log level (DEBUG through ERROR), when Brain is running, then no log line contains the literal `refresh_token` value or `access_token` value.
  - [x] AC: Given an `OAuthRefreshError` is logged, when the log entry is written, then it contains only the error type and HTTP status code, not the token strings.
- [x] 5.2 Startup performance — avoid blocking refresh on boot
  - [x] AC: Given a valid non-expired token exists in DB, when Brain starts, then the first `/health` response is returned within normal startup time.
  - [x] AC: Given no token exists in DB on first boot, when Brain starts, then it performs one refresh call during initialisation.
