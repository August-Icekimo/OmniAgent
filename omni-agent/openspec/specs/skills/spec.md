## ADDED Requirements

### Requirement: Modular Skill Execution
The system must provide an extensible interface for executing specialized technical tasks.

#### Scenario: Skill Execution Request
- **WHEN** the Brain service calls the Skills Server via `POST /skill/execute` with a skill name and parameters
- **THEN** the Skills Server must route the request to the appropriate handler
- **AND** return a standardized JSON response containing the execution status and results.

### Requirement: Server Management (Cockpit)
The system must be able to query and manage HomeLab servers via the Cockpit API.

#### Scenario: Query Host Status
- **WHEN** the `cockpit` skill is called with `action: "status"`
- **THEN** it must return CPU, RAM, and Disk usage statistics from the target host.

#### Scenario: Restart System Service
- **WHEN** the `cockpit` skill is called with `action: "restart_service"` and a valid service name
- **THEN** it must authenticate to the Cockpit API
- **AND** trigger the service restart.

### Requirement: Network Management (Wake-on-LAN)
The system must be able to wake up computers on the local network.

#### Scenario: Send Magic Packet
- **WHEN** the `wake_on_lan` skill is called with a valid MAC address
- **THEN** it must broadcast a Magic Packet (UDP) to the local network to wake the device.

### Requirement: File Analysis (Vision & OCR)
The system must be able to extract and summarize information from various file types.

#### Scenario: PDF Analysis
- **WHEN** the `file_analyze` skill receives a PDF file
- **THEN** it must extract the text content and use the LLM to generate a summary.

#### Scenario: Image Analysis (Vision)
- **WHEN** the `file_analyze` skill receives an image
- **THEN** it must use a Vision-capable LLM (e.g., Claude Vision) to perform OCR and describe the image content.

#### Scenario: Spreadsheet Analysis
- **WHEN** the `file_analyze` skill receives an Excel file
- **THEN** it must read the sheets (up to a limit) and provide a structured summary of the data.

### Requirement: Web Search (Real-time Information)
The system must be able to retrieve real-time information from the web for time-sensitive queries.

#### Scenario: Query Web Search
- **WHEN** the `web_search` skill is called with a query
- **THEN** it must query a self-hosted SearXNG instance (intranet-only) via its JSON API
- **AND** return a truncated, ranked list of `{title, url, description, position}` results
- **AND** never raise — failures return a serializable `{"success": false, "error": ...}`.

### Requirement: Web Page Fetch (Read Page Content)
The system must be able to read the main content of public web pages (including JavaScript-rendered pages and PDFs) so that search results can be verified beyond their snippets.

#### Scenario: Fetch Static Page
- **WHEN** the `fetch_url` skill is called with up to 3 `http`/`https` URLs
- **THEN** each page must be fetched in the brain process and its main content extracted with `trafilatura`
- **AND** content over 8000 characters must be truncated to head + tail with an explicit omission marker
- **AND** the result must be `{"success": true, "data": {"pages": [{url, final_url, title, content, truncated, rendered, error}]}}`; per-page failures go in `error`, the skill never raises.

#### Scenario: Render JavaScript Page
- **WHEN** the static extraction yields fewer than 200 characters, or fewer than 3000 characters containing an "enable JavaScript" hint, or the server answers 403/429/503
- **THEN** the page must be rendered with headless Chromium (Playwright), CSS-hidden elements removed, and content re-extracted.

#### Scenario: Block Internal Targets (SSRF)
- **WHEN** a URL, any redirect hop, or any request/WebSocket made by the rendered page targets a non-public address (private, loopback, link-local, CGNAT `100.64.0.0/10`, multicast, reserved), a dotless or internal-suffix hostname, embeds credentials, or carries a secret-like token
- **THEN** the request must be refused and logged as a WARNING, and the page error must state that it was refused.

#### Scenario: No Confirmation Needed
- **WHEN** the model calls `fetch_url`
- **THEN** it must execute without a confirmation round-trip (read-only, no side effects), and its content must be presented to the model as untrusted reference material.

### Requirement: Terminal Command Execution (Sandboxed)
The system must be able to execute shell commands to inspect HomeLab state, with strict isolation and authorization controls.

#### Scenario: Execute Command in Sandbox
- **WHEN** the `terminal` skill is called with a `command`
- **THEN** the command must execute inside a dedicated, restricted sandbox container (read-only filesystem, non-root, no secrets, intranet-only, resource-limited)
- **AND** the sandbox must enforce a timeout (killing the process group) and truncate output.

#### Scenario: Administrator-only Authorization
- **WHEN** a non-administrator (`users.role != 'admin'`) requests the `terminal` skill
- **THEN** the request must be refused without executing any command.

#### Scenario: Allowlist Bypasses Confirmation
- **WHEN** an administrator requests a command whose first token is in the safe read-only allowlist (and contains no shell chaining)
- **THEN** it must execute without a confirmation step (`is_write` forced to false).

#### Scenario: Non-allowlisted Command Requires Confirmation
- **WHEN** an administrator requests a command that is not on the allowlist
- **THEN** the system must store the pending plan and ask for confirmation before executing
- **AND** execute it only after the user confirms in a subsequent message.

#### Scenario: Dangerous Command Blocked
- **WHEN** a command matches a dangerous pattern (e.g. `rm -rf`, `sudo`, fork bomb, `curl ... | sh`)
- **THEN** it must be blocked at both the Brain skill and the sandbox layers, and never executed.
