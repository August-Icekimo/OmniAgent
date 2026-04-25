## ADDED Requirements

### Requirement: OAuth Gemini Integration
The system must support calling Google Gemini API using OAuth 2.0 credentials from a Google AI Premium subscription.

#### Scenario: Successful Chat with Valid Token
- **WHEN** a chat request is made and a valid OAuth access token is cached in the database
- **THEN** the request must be sent to Gemini API using the cached token
- **AND** no token refresh should be triggered

#### Scenario: Automatic Token Refresh
- **WHEN** a chat request is made and the cached OAuth access token is expired or missing
- **THEN** the system must call the Google OAuth refresh endpoint
- **AND** store the new access token in the database
- **AND** proceed with the original chat request

#### Scenario: Fallback to API Key
- **WHEN** the OAuth token refresh fails (e.g., revoked token, network error)
- **THEN** the `ModelRouter` must fall back to the standard API key provider
- **AND** the `BrainResponse` should indicate the fallback reason

### Requirement: Dynamic Model Routing
The system must dynamically select the best provider based on task context and complexity.

#### Scenario: Complexity-Based Upgrade
- **WHEN** a task is evaluated as "high" complexity by the primary provider (e.g., Gemini Flash)
- **THEN** the system must propose an upgrade to a more powerful model (e.g., Gemini Pro)
- **AND** wait for user confirmation (15s auto-confirm timeout) before proceeding.

#### Scenario: Manual Provider Override
- **WHEN** a user message starts with a `/provider <name>` command
- **THEN** the system must override automatic routing and use the specified provider for that request.

### Requirement: Usage Quotas and Safety
LLM usage must be controlled to prevent excessive costs and API abuse.

#### Scenario: Daily Upgrade Limit
- **WHEN** the system has reached the daily limit of 20 model upgrades
- **THEN** subsequent upgrade requests must be denied
- **AND** the task must be executed using the primary/fallback provider.

#### Scenario: Cooldown Protection
- **WHEN** a user triggers more than 3 upgrades within a 10-minute window
- **THEN** additional upgrades for that user must be blocked until the cooldown period expires.

### Requirement: Local LLM Integration
The system should utilize local LLM resources when available to reduce latency and costs for simple tasks.

#### Scenario: Local Provider Health Check
- **WHEN** the Brain service starts
- **THEN** it must perform a health check on the local LLM endpoint (Mac Mini)
- **AND** only enable the `local` provider if it is reachable.
