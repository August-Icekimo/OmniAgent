## Why

The goal of Phase 3 is to inject "memory" and "soul" into Omni-Agent (Cindy). This involves implementing a three-tier memory architecture (short-term, long-term RAG, light summary index) and a `SoulLoader` that renders a dynamic system prompt using `SOUL.md` and database state. This gives Cindy cross-conversation memory and a consistent personality.

## What Changes

- `brain/soul/loader.py`: SoulLoader implementation.
- `brain/soul/templates/context.md.jinja`: Jinja2 template for dynamic prompts.
- `brain/memory/short_term.py`: Short-term memory (conversations table).
- `brain/memory/long_term.py`: Long-term memory (pgvector embeddings).
- `brain/main.py`: Integration of all modules.
- `gateway/internal/stress/manager.go`: Mood/action logging.

## Capabilities

### New Capabilities
- `memory`: Supports short-term conversation history and long-term semantic RAG via pgvector.
- `soul`: Dynamic system prompt generation based on persona and real-time system state.

### Modified Capabilities
- `brain`: Integrated memory and soul modules into the `/chat` endpoint.

## Impact

- Requires `GEMINI_API_KEY` for embedding generation.
- PostgreSQL with `pgvector` extension must be available.
- Memory recall adds a slight latency (<500ms) to initial LLM processing.

## Open Questions

- `I-02-A` Embedding provider: Verified in codebase as `gemini-embedding-001`.
- `F-04` Summarization strategy: Implemented as Gemini-based extraction in `long_term.py`.
- `F-06` Trigger timing: Verified as async task after every assistant reply in `main.py`.
