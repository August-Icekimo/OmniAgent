## MODIFIED Requirements

### Requirement: Local LLM Integration
The system SHALL utilize local LLM resources when available to reduce latency and costs for simple tasks. The local provider MUST target chrysoberyl (`MLX_BASE_URL`, default `http://100.88.136.117:8000/v1`) running `gemma-4-26b` (4-bit quantized) via Rapid-MLX. The model identity MUST be configurable via `MLX_MODEL` environment variable.

#### Scenario: Local Provider Health Check
- **WHEN** the Brain service starts
- **THEN** it MUST perform a health check on the local LLM endpoint defined by `MLX_BASE_URL`
- **AND** only enable the `local` provider if the endpoint is reachable
- **AND** log the confirmed model name returned by the endpoint
