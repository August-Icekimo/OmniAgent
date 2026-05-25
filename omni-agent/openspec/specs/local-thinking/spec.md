## ADDED Requirements

### Requirement: Local Provider Thinking Mode
The `LocalClient` SHALL support an opt-in thinking mode for models that expose it (e.g., Gemma 4). When enabled, the client MUST pass `enable_thinking: true` in the `extra_body` of the OpenAI-compatible chat completion request. When disabled (default), the field MUST NOT be sent.

#### Scenario: Thinking disabled by default
- **WHEN** `LocalClient` is constructed without a `thinking_budget`
- **THEN** chat requests MUST NOT include `extra_body.enable_thinking`
- **AND** TTFT MUST remain at steady-state (~120 ms on chrysoberyl)

#### Scenario: Thinking enabled via routing config
- **WHEN** `routing_config.json` sets `thinking_budget > 0` on the `local` provider
- **THEN** `LocalClient` MUST include `extra_body: {"enable_thinking": true}` in the request
- **AND** the response MAY contain reasoning tokens before the answer token

#### Scenario: Thinking budget field in routing rule
- **WHEN** a routing rule targeting `local` includes `"thinking_budget": 0`
- **THEN** `LocalClient` MUST send `extra_body: {"enable_thinking": false}` for that request
- **AND** `thinking_budget: -1` MUST be treated the same as `0` (thinking off)
