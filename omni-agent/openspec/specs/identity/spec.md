## ADDED Requirements

### Requirement: Unified Cross-Platform Identity
The system must maintain a single source of truth for user identities that spans multiple messaging platforms.

#### Scenario: User Identification by Platform ID
- **WHEN** a message is received from a platform (Telegram, LINE)
- **THEN** the system must look up the platform-specific ID (e.g., `chat_id`) in the corresponding account table (`telegram_accounts`, `line_accounts`)
- **AND** resolve it to a unique `user_id` (UUID) from the `users` table.

#### Scenario: Admin Bootstrapping
- **WHEN** the system starts up and no admin exists in the database
- **THEN** it must create an admin user using the `TELEGRAM_ADMIN_CHAT_ID` environment variable.

### Requirement: Stranger Management
The system must track and limit access for unrecognized users.

#### Scenario: First-time Stranger Interaction
- **WHEN** an unknown `chat_id` sends a message
- **THEN** the system must create a new user with the `stranger` role
- **AND** record the interaction in the `stranger_knocks` table for admin review
- **AND** respond with a standardized "not recognized" message.

#### Scenario: Daily Stranger Summary
- **WHEN** the daily summary task runs (e.g., at 23:00)
- **THEN** all un-notified `stranger_knocks` must be summarized and sent to system admins via Telegram.
