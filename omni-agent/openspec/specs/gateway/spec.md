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

### Requirement: Clickable Reply Options
When a reply carries options (`turns.options`, `[{label, text}]`), the gateway must render them as platform-native buttons that send `text` as the user.

#### Scenario: LINE Quick Reply
- **WHEN** a LINE reply has options
- **THEN** a `quickReply` with `message` actions (≤ 13 items, label ≤ 20 characters) must be attached to the last message object only, including when the reply is split into multiple messages/batches
- **AND** if the reply is cached for slow-reply postback pickup, the options must be cached with it (`line_pending_replies.options`) and attached on pickup.

#### Scenario: Telegram Inline Keyboard
- **WHEN** a Telegram reply has options
- **THEN** an `inline_keyboard` (one row, `callback_data` = option text, options over 64 bytes skipped) must be attached to the last chunk only.

#### Scenario: Telegram Button Click
- **WHEN** a `callback_query` arrives from a known (non-stranger) chat
- **THEN** the gateway must answer it (`answerCallbackQuery`), remove the keyboard from that message, and enqueue the button text as a normal text message
- **AND** only the first click per message is accepted; callbacks from unknown chats are answered and otherwise ignored.

#### Scenario: Platforms Without Buttons
- **WHEN** the platform has no button support (iMessage) or options are absent/invalid
- **THEN** the reply is delivered as plain text, unchanged.
