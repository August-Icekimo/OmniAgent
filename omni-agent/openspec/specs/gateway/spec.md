## ADDED Requirements

### Requirement: Multi-Channel Webhook Handling
The gateway must receive and validate incoming messages from multiple platforms.

#### Scenario: Telegram Webhook Validation
- **WHEN** a POST request is received at `/webhook/telegram` with a valid `X-Telegram-Bot-Api-Secret-Token`
- **THEN** the gateway must return HTTP 200
- **AND** process the message into the internal queue

#### Scenario: Unauthorized Access Rejection
- **WHEN** a webhook request has an invalid or missing secret token
- **THEN** the gateway must return HTTP 401
- **AND** log the unauthorized attempt without storing the payload

### Requirement: Standardized Message Format
Incoming platform-specific messages must be converted to a common `StandardMessage` format.

#### Scenario: Telegram to StandardMessage
- **WHEN** a Telegram text message is received from an authorized `chat_id`
- **THEN** it must be mapped to a `StandardMessage` with `platform: "telegram"` and `user_id` set to the chat ID string.

### Requirement: Access Control (Whitelist)
The gateway must restrict message processing to authorized users only.

#### Scenario: Authorized Chat ID
- **WHEN** the sender's `chat_id` is present in the `TELEGRAM_ALLOWED_CHAT_IDS` whitelist
- **THEN** the message is accepted and queued.

#### Scenario: Stranger Message Handling
- **WHEN** the sender's `chat_id` is NOT in the whitelist
- **THEN** the message is ignored
- **AND** a "stranger handled" status is returned to prevent retries

### Requirement: File Attachment Support
The gateway must support receiving and downloading files from messaging platforms.

#### Scenario: Telegram File Download
- **WHEN** a Telegram `document` or `photo` update is received
- **THEN** the gateway must check the file size (limit 10MB)
- **AND** download the file to the shared `/workspace/uploads/` directory
- **AND** include the `Attachment` metadata in the `StandardMessage`.

#### Scenario: File Size Limit Enforcement
- **WHEN** a received file exceeds the 10MB limit
- **THEN** the gateway must reject the file
- **AND** notify the user about the size limit without queueing the message.
