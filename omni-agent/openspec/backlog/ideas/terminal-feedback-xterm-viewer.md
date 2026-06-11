---
slug: terminal-feedback-xterm-viewer
status: idea
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
- **Unified Log Storage**: Generate a unique `task_id` for every terminal execution, saving the raw output (including ANSI escape codes) in the `home_context` DB table.
- **Clean Chat Delivery**: Cindy reports only a high-level summary in the main chat response and appends a `[📄 查看完整終端機輸出]` link referencing the web viewer.

## Acceptance hints
- Running a terminal command returns a concise summary from Cindy with a link to the log page.
- Opening the link renders the command's full stdout/stderr with real-time ANSI terminal colors preserved.
- The main chat log is kept tidy and free of large terminal output blocks.

## Open questions
- **Security & Access Control**: Should the log viewer require authentication (e.g. admin session cookies or signature tokens) to prevent unauthorized viewing of system outputs?
- **Retention Policy**: How long should terminal logs be kept in the database before being automatically pruned?
- **Real-time Streaming**: For long-running background tasks, should the web viewer support real-time log streaming using WebSockets/SSE?

## Links
- Roadmap: openspec/backlog/ROADMAP.md#phase-59-agent-capabilities
- Related spec: openspec/specs/brain/spec.md
