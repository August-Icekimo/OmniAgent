## Why

Phase 2 refactored the system from a four-tier to a three-tier architecture by deprecating the independent LiteLLM router and integrating native LLM SDKs (Claude, Gemini, Local MLX) directly into the Brain service. This change enables better utilization of provider-specific features like Claude Prompt Caching and Gemini Context Caching to reduce costs and latency.

## What Changes

- `CLAUDE.md`: Updated architecture diagrams and directory structure.
- `router/`: Deleted the independent LiteLLM service directory.
- `brain/llm/`: Implemented native adapters for Claude, Gemini, and Local (OpenAI-compatible) models.
- `brain/main.py`: Initialized the FastAPI application and ModelRouter integration.
- `brain/requirements.txt`: Added native LLM SDK dependencies.

## Capabilities

### New Capabilities
- `llm`: Direct integration with Anthropic and Google GenAI SDKs.
- `brain`: Core FastAPI entry point for processing standardized messages.

## Impact

- Reduced complexity by removing one service layer.
- Lower operational costs through aggressive prompt/context caching.
- Direct access to state-of-the-art model features.

## Open Questions

- None at the completion of Phase 2.
