## ADDED Requirements

### Requirement: Agentic Flow via Native Tool Calling (LangGraph)
The brain must use a stateful graph with **provider-native tool calling** (function calling) to decide when to invoke skills, rather than prompt-based JSON. This prevents the model from fabricating tool output: tool results are injected by the harness, never generated as the model's answer.

#### Scenario: Tool-Call Loop
- **WHEN** a (non-attachment) user message is received
- **THEN** the `planner` node selects a provider and the `agent` node calls the LLM with the registered tool specs (`temperature=0`)
- **AND** if the model emits `tool_calls`, the `tools` node executes them and feeds real results back, looping until the model returns a final answer or the iteration cap (5) is reached.

#### Scenario: No Fabricated Execution
- **WHEN** the model has not emitted a `tool_call`
- **THEN** the reply is a normal chat answer and MUST NOT claim to have run a command or include a tool-derived link (sanitized defensively).

#### Scenario: Safety Gates Before Execution
- **WHEN** a `terminal` tool_call is requested
- **THEN** non-admin users are refused, and dangerous commands are blocked before reaching the sandbox.

#### Scenario: Explicit Confirmation for Write Operations
- **WHEN** a tool_call is write/side-effecting (e.g., non-allowlisted terminal command, wake_on_lan, cockpit restart_service) and not yet confirmed
- **THEN** execution pauses and the system asks for approval, persisting the pending tool-call conversation
- **AND** on the user's approval the next turn resumes and executes the approved tool_call.

#### Scenario: Attachment Path Unchanged
- **WHEN** a message carries an attachment
- **THEN** it routes to `file_analyze` (executor → reporter), independent of the tool-call loop.

Note: the legacy prompt-JSON planner and the local-model self-upgrade flag (`upgrade_needed`) have been removed.

### Requirement: Proactive System Assistance
The brain must monitor system state and proactively propose optimizations or report anomalies.

#### Scenario: Model Upgrade Proposal
- **WHEN** the system detects high stress (e.g., `StressOverload`)
- **THEN** it must proactively send a proposal to the admin to upgrade to a more powerful LLM model
- **AND** wait for confirmation before switching.

### Requirement: Automated Workspace Management
The system must manage temporary files in the shared workspace to prevent storage exhaustion.

#### Scenario: Workspace Cleanup
- **WHEN** the hourly cleanup task runs
- **THEN** it must delete files that haven't been accessed for more than 120 hours
- **AND** remove their corresponding entries from the `file_workspace_log` table.

### Requirement: Terminal Execution Feedback & Web Log Viewer
Terminal command output must not flood the chat channel. The brain must report only a concise summary plus a signed link to a web viewer that renders the full, ANSI-colored log, with real-time streaming for long-running commands.

#### Scenario: Concise Chat Summary with Viewer Link
- **WHEN** the `terminal` skill executes a command (foreground or background)
- **THEN** the `reporter` node must produce a brief natural-language summary in Cindy's persona (not the raw output)
- **AND** append a `[📄 查看完整終端機輸出]` link of the form `<CINDY_VIEWER_BASE_URL>/terminal/view/<task_id>?t=<token>`
- **AND** record a `terminal_log:<task_id>` pointer (command, created_at, status) in `home_context`
- **AND** if `CINDY_VIEWER_BASE_URL` or the signing secret is unset, degrade to summary-only (no broken link).

#### Scenario: Authenticated, Token-Scoped Log Access
- **WHEN** a user opens `GET /terminal/view/{task_id}`
- **THEN** access is gated upstream by the secure-gateway Caddy `admin_policy` (Google OAuth)
- **AND** the brain additionally verifies a short-lived HMAC token bound to `task_id` (default 24h)
- **AND** invalid/expired/missing token → 403, unset secret → 503, unknown task_id → 404.

#### Scenario: Real-Time Output Streaming
- **WHEN** a client connects to `WS /terminal/ws/{task_id}` with a valid token
- **THEN** the brain replays the existing log from the shared volume, then tails and pushes new raw bytes in real time
- **AND** closes gracefully after the task reaches `done`/`error` per its `meta.json`.

#### Scenario: Log Retention
- **WHEN** the daily terminal-log cleanup task runs
- **THEN** it must delete `<task_id>.log`/`.meta.json` older than `TERMINAL_LOG_RETENTION_DAYS` (default 7)
- **AND** remove their corresponding `terminal_log:<task_id>` entries from `home_context`.

### Requirement: Attachment Routing
The brain must prioritize file analysis when an attachment is present in the message.

#### Scenario: Routing to FileAnalyzer
- **WHEN** a `StandardMessage` contains an `attachment`
- **THEN** the `planner` node must automatically select the `file_analyze` skill
- **AND** skip the confirmation node (as it is a read-only operation).

### Requirement: Local Speech-to-Text Preprocessing
The system must optimize voice message processing by transcribing audio locally before passing it to the graph.

#### Scenario: Preprocessing Voice Attachment
- **WHEN** a `StandardMessage` with `message_type: "voice"` is received
- **THEN** the system must use a local CPU-based STT engine (e.g., faster-whisper) to transcribe the audio
- **AND** if successful, inject the transcribed text into the message text, consume the attachment, and route it as a standard text message.
- **AND** if it fails, fallback to passing the raw audio attachment to the graph for multimodal LLM processing.
