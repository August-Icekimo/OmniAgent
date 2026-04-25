## Why

To optimize performance and cost by dynamically selecting the most appropriate LLM provider for each task. The system uses a two-tier routing strategy: Gemini Flash performs a quick complexity assessment, and complex tasks are upgraded to Gemini 2.5 Pro. This phase also introduces quota management and centralized routing rules.

## What Changes

- `brain/config/routing_config.json`: Centralized routing and upgrade rules.
- `brain/llm/router.py`: Implemented `select_provider`, `check_upgrade`, and quota management.
- `brain/agent/graph.py`: Integrated routing logic into the `planner_node`.
- `brain/agent/prompts/`: Standardized prompt building for assessment and tools.
- `brain/main.py`: Added `routing_reason` to response and implemented the upgrade confirmation flow.

## Capabilities

### Modified Capabilities
- `llm`: Enhanced with dynamic routing, complexity-based upgrades, and usage quotas (20 upgrades/day, 10-minute cooldown).

## Impact

- Improved response quality for complex tasks.
- Cost savings by using cheaper models (Flash/Local) for simple tasks.
- 15-second auto-confirmation for model upgrades.

## Open Questions

- `thinking_budget`: Integrated as a parameter in `GeminiClient.chat()`.
- UTC+8 Midnight Reset: Quota reset logic respects local time.
