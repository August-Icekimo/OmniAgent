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

### Requirement: Short Video Analysis
The system must be able to watch videos behind links from YouTube and short-video platforms (TikTok, Instagram Reels, Douyin, X, Xiaohongshu, Bilibili) and describe their content, even though Gemini can only read YouTube URLs directly.

#### Scenario: YouTube Link
- **WHEN** `analyze_video_url` is called with a `youtube.com` / `youtu.be` URL
- **THEN** its duration must be probed with `yt-dlp` metadata only (a probe failure must not block analysis), the duration tiers below applied, and the URL passed to Gemini as a `file_uri` video part without downloading.

#### Scenario: Short-video Platform Link
- **WHEN** `analyze_video_url` is called with a URL on a whitelisted platform domain (or a known share short-link such as `vt.tiktok.com`, `v.douyin.com`, `xhslink.com`, `b23.tv`, `t.co`, expanded in-process with an SSRF check on every hop)
- **THEN** the video must be probed with `yt-dlp` restricted to that platform's extractors (`--use-extractors`; the generic extractor is never loaded), rejected before download if it is live, subject to the duration tiers below, downloaded (≤ 50MB and ≤ 720p preferred; long videos ≤ 150MB and ≤ 480p) to a per-request directory under `/workspace/uploads/video_fetch/`, transcoded with ffmpeg if larger than 15MB (resolution, fps and bitrate scaled to duration), and sent inline to Gemini
- **AND** the per-request directory must be removed whether the call succeeds or fails
- **AND** yt-dlp and ffmpeg must run as killable subprocesses with timeouts, at most one download at a time
- **AND** the result must be `{"success": true, "data": {url, final_url, platform, title, uploader, duration, caption, transcoded, analysis}}`; failures return `{"success": false, "error": <readable reason>}` and the skill never raises.

#### Scenario: Duration Tiers
- **WHEN** a video is 6 minutes or shorter
- **THEN** it must be analyzed directly.
- **WHEN** a video is longer than 6 minutes and at most 15 minutes, and the user has not confirmed
- **THEN** the tool must return `{"success": false, "needs_confirmation": true, "question": ...}` and the agent must pause through the existing confirmation round-trip (store `confirm:pending:<user_id>`, reply with the question)
- **AND** only after the user confirms must the tool be re-run with `confirmed=true` and the video analyzed.
- **WHEN** a video is longer than 15 minutes
- **THEN** it must be refused (the ceiling is bounded by `TURN_PROCESSING_TIMEOUT`).

#### Scenario: Reject Unsupported or Unsafe URLs
- **WHEN** the URL's host is not a whitelisted platform domain, or the URL fails `is_safe_url`
- **THEN** it must be refused without invoking yt-dlp.

#### Scenario: Platform Login Cookies
- **WHEN** a Netscape-format cookie file `<platform>.txt` exists in the read-only `YTDLP_COOKIE_DIR` mount
- **THEN** a temporary copy must be given to yt-dlp (the original is never modified), and cookie contents must never appear in logs or tool results
- **AND** login / rate-limit failures must return a message telling the user an administrator needs to set or refresh that platform's cookie, logged as `cookie_expired platform=<key>` at WARNING.

#### Scenario: Gemini-only Analysis
- **WHEN** Gemini is unavailable (router raises, or multimodal routing returns empty content)
- **THEN** the tool must fail with an explicit "only Gemini can analyze video" message; no other provider may answer as if it had watched the video.

#### Scenario: No Confirmation Needed
- **WHEN** the model calls `analyze_video_url`
- **THEN** it must execute without an up-front confirmation round-trip (only the duration tier can trigger one, after probing), and its output must be presented to the model as untrusted reference material.

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
