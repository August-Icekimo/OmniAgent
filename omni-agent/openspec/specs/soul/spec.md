## ADDED Requirements

### Requirement: Dynamic Persona Rendering
The agent's system prompt must be dynamically generated to reflect its core personality and current state.

#### Scenario: Base Persona Injection
- **WHEN** the `SoulLoader` is initialized
- **THEN** it must read the static core of `SOUL.md`
- **AND** ensure it is always present in the rendered system prompt

#### Scenario: System State Awareness
- **WHEN** rendering the prompt and recent `stress_logs` exist
- **THEN** the prompt must include the current system stress level and mood (e.g., "Cindy is feeling busy")

#### Scenario: Family Context Awareness
- **WHEN** rendering the prompt and `home_context` contains active events or today's plans
- **THEN** these must be injected into the `## Family Pulse` or `## Today` sections of the prompt

### Requirement: Robustness and Fallbacks
The persona rendering must not fail even if dependencies (like the database) are unavailable.

#### Scenario: Database Failure Fallback
- **WHEN** the database is unreachable during prompt rendering
- **THEN** the system must fall back to the static `SOUL.md` content
- **AND** omit dynamic sections without crashing the Brain service
