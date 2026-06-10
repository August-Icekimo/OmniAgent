## ADDED Requirements

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
The system SHALL utilize local LLM resources when available to reduce latency and costs for simple tasks. The local provider MUST target chrysoberyl (`MLX_BASE_URL`, default `http://100.88.136.117:8000/v1`) running `gemma-4-26b` (4-bit quantized) via Rapid-MLX. The model identity MUST be configurable via `MLX_MODEL` environment variable.

#### Scenario: Local Provider Health Check
- **WHEN** the Brain service starts
- **THEN** it MUST perform a health check on the local LLM endpoint defined by `MLX_BASE_URL`
- **AND** only enable the `local` provider if the endpoint is reachable
- **AND** log the confirmed model name returned by the endpoint
