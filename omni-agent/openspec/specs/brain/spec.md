## ADDED Requirements

### Requirement: Stateful Agentic Flow (LangGraph)
The brain must use a stateful graph to process complex requests that involve multiple steps or user confirmations.

#### Scenario: Planning and Tool Selection
- **WHEN** a user message is received
- **THEN** the `planner` node must analyze the intent and determine if a skill (tool) is required
- **AND** output a plan summary.

#### Scenario: Explicit Confirmation for Write Operations
- **WHEN** a plan involves a "write" operation (e.g., restarting a service)
- **THEN** the system must transition to the `confirmer` node
- **AND** ask the user for explicit approval before proceeding to execution.

#### Scenario: Tool Execution and Reporting
- **WHEN** a plan is approved or identified as "read-only"
- **THEN** the system must execute the skill via the Skills Server
- **AND** the `reporter` node must convert the technical output into a natural language response in Cindy's persona.

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
