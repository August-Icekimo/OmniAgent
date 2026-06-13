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
