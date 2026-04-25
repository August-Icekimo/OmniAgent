# Phase 4A Implementation Plan — Dynamic ModelRouter Activation

This phase activates the dynamic routing logic within the Brain service. It transitions the default provider to Gemini Flash, implements a two-stage routing system (Assessment -> Execution), and adds proactive upgrade suggestions for complex tasks.

## User Review Required

> [!IMPORTANT]
> **Gemini 2.5 Flash as Default**: We will switch the project's default LLM from Claude to Gemini 2.5 Flash to take advantage of lower latency and cost for primary tasks.
> **15s Auto-Confirmation**: If a complex task requires an upgrade to Gemini 2.5 Pro, Cindy will ask for permission. If the user doesn't reply within 15 seconds, the system will automatically proceed with the upgrade to ensure continuity.
> **Thinking Budget**: We will integrate the `thinking_budget` parameter for Gemini models. This allows specialized rules (like vision tasks) to minimize internal "thought" for faster responses.

## Proposed Changes

---

### 1. Configuration System

Centralize all routing and provider settings.

#### [NEW] [routing_config.json](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/brain/config/routing_config.json)
- Define `providers` (gemini, claude, local) with their model strings and status.
- Define `routing_rules` (image input, simple text, skill intent, default).
- Define `upgrade_rules` and `upgrade_quota` (20/day).

#### [NEW] [config_loader.py](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/brain/config/config_loader.py)
- Logic to load the JSON config with hardcoded fallback defaults if the file is missing.

---

### 2. Prompt Refactoring

Clean up the prompts module and add complexity assessment instructions.

#### [MODIFY] [system_prompt.py](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/brain/agent/prompts/system_prompt.py) (Renamed from `system.py`)
- Implement `build_assessment_prompt()` to ask the LLM for `complexity` and `reasoning`.
- Implement `build_system_prompt()` to combine SOUL.md, memories, and skills context.

#### [MODIFY] [tools_prompt.py](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/brain/agent/prompts/tools_prompt.py) (Renamed from `tools.py`)
- Implement `build_tools_prompt()` to centralize skill descriptions.

---

### 3. LLM Layer Enhancements

#### [MODIFY] [gemini_client.py](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/brain/llm/gemini_client.py)
- Add `thinking_budget` (int) support to the `chat` method.

#### [MODIFY] [router.py](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/brain/llm/router.py)
- Implement `select_provider(message_context)` using rules from config.
- Implement `check_upgrade(complexity, provider)` logic.
- Implement `check_quota(user_id)` using `home_context` table for persistence.
- Add local provider health check logic (skip in test env).

---

### 4. Agent Graph Integration

#### [MODIFY] [graph.py](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/brain/agent/graph.py)
- Update `AgentState` with routing/complexity fields.
- Update `planner_node` to:
    1. Check for manual provider overrides (e.g., `/provider claude`).
    2. Route to an initial provider.
    3. If not override, call Gemini Flash to assess complexity.
    4. Determine if an upgrade is requested based on complexity and rules.
- Add components to handle the 15s confirmation wait (potentially involving a background task or state check).

---

### 5. API & Main Logic

#### [MODIFY] [main.py](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/brain/main.py)
- Update `BrainResponse` schema to include `routing_reason`.
- Integrate the new config loader.
- Ensure `Asia/Taipei` timezone is handled for quota resets.

## Open Questions

- **Confirmation Flow Implementation**: Should the 15-second "auto-confirm" block the `/chat` request (hanging for 15s) or should it return immediately saying "I'm thinking..." and then push the final answer later? 
    - *Proposed*: Return immediately with the "waiting" message, and have a background task in Brain push the final result via the Telegram Bot API if no "No" is received in 15s. This provides a better UX.
- **Quota DB Fail-Open**: In case of DB failure, should we allow all upgrades? (Spec says "fail-open").

## Verification Plan

### Automated Tests
- Run `podman compose up` and verify all services start.
- Test `/chat` with `/provider` override.
- Test `/chat` with an image (should route to Gemini with specific routing_reason).
- Validate `routing_config.json` loading with invalid JSON.

### Manual Verification
- Trigger a "high complexity" task (e.g., by forcing it in DB or using a complex prompt).
- Verify the Telegram confirmation message from Cindy.
- Wait 15s without replying -> Verify the agent proceeds and sends the final response.
- Reply "no" within 15s -> Verify the agent continues with the original model or cancels the upgrade.
- Verify quota tracking in `home_context` via `psql`.
