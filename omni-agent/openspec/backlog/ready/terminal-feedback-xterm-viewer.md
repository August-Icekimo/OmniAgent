---
slug: terminal-feedback-xterm-viewer
status: in-sprint
domain: brain
size: M
priority: P1
created: 2026-06-11
---

# Terminal Execution Progress Feedback & xterm.js Web Viewer

## Why
Printing raw terminal outputs directly in chat messages (LINE/Telegram) is messy, easily exceeds message length limits, and lacks ANSI color rendering. However, users need step-by-step progress feedback and the ability to expand and inspect full, colored command logs for debugging and tracing what went wrong.

## What (high-level)
- **Concise Progress Feedback**: Provide clean, step-by-step progress updates in the chat channel during command execution without cluttering the chat history.
- **FastAPI Log Viewer Route**: Add a GET `/terminal/view/{task_id}` endpoint in `brain/main.py` that serves a lightweight HTML page embedding `xterm.js` to render raw terminal logs with full ANSI colors.
- **Log Storage & Streaming**: Generate a unique `task_id` for every terminal execution. The terminal output is written to a dedicated storage structure (e.g., filesystem files), and `home_context` merely stores the association/pointer to it. The viewer will support real-time streaming (via WebSockets/SSE) to show the progress of long-running commands as they execute.
- **Access Control & Lifecycle**: The endpoint is protected by the existing Google OAuth gateway layer, and access is further secured using short-lived tokens tied to the `task_id`. Logs are kept for 7 days before being automatically pruned.
- **Clean Chat Delivery**: Cindy reports only a high-level summary in the main chat response and appends a `[📄 查看完整終端機輸出]` link referencing the web viewer.

## Acceptance hints
- Running a terminal command returns a concise summary from Cindy with a link to the log page.
- Opening the link securely (via OAuth + short-lived token) renders the command's stdout/stderr.
- Long-running commands stream their output in real-time via WebSockets/SSE to the viewer.
- Terminal outputs are stored on the filesystem (or a dedicated structure) rather than bloating the DB, with associations kept in `home_context`.
- Logs older than 7 days are automatically pruned.
- The main chat log is kept tidy and free of large terminal output blocks.

## Open questions

## Links
- Roadmap: openspec/backlog/ROADMAP.md#phase-59-agent-capabilities
- Related spec: openspec/specs/brain/spec.md
