## 1. API Gateway

- [x] 1.1 Webhook Receiver
  - [x] AC: Receive LINE webhooks and return 200.
  - [x] AC: Validate LINE signature.
- [x] 1.2 StandardMessage Mapping
  - [x] AC: Convert platform-specific payloads to `StandardMessage`.

## 2. Persistence & Queue

- [x] 2.1 DB Schema Implementation
  - [x] AC: Create `conversations`, `message_queue`, `stress_logs`.
- [x] 2.2 Queue Manager
  - [x] AC: Persist incoming messages to DB with `pending` status.

## 3. Stress Management

- [x] 3.1 StressManager Skeleton
  - [x] AC: Monitor queue depth and log stress level.
