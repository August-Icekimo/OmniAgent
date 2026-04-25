## Why

To establish the core connectivity layer for Omni-Agent. This involves creating a Go-based API Gateway to receive and validate webhooks (LINE, BlueBubbles), a PostgreSQL-backed message queue, and a stress management mechanism.

## What Changes

- `gateway/`: Implementation of the Go API Gateway.
- `db/migrations/`: Initial database schema (`001_init.sql`).

## Capabilities

### New Capabilities
- `gateway`: Unified webhook entry point with signature validation and StandardMessage conversion.
- `queue`: Persistent message storage and processing using PostgreSQL.
- `stress`: Basic system stress tracking based on queue depth.

## Impact

- Foundation for all future agent interactions.
- Ensures reliable message delivery and processing.
