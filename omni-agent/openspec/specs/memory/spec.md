## ADDED Requirements

### Requirement: Short-term Conversation Memory
The system must persist recent dialogue rounds to maintain context within a session.

#### Scenario: Dialogue Persistence
- **WHEN** a chat interaction completes (user message and assistant reply)
- **THEN** the round must be saved to the `conversations` table
- **AND** it must be retrievable by `user_id` for subsequent rounds

#### Scenario: History Loading
- **WHEN** a new request is processed
- **THEN** the system must load up to N recent rounds of history
- **AND** include them in the LLM message context

### Requirement: Long-term Semantic Memory
The system must support semantic recall of past interactions using vector embeddings.

#### Scenario: Memory Storage
- **WHEN** a conversation round is completed
- **THEN** a summary of the key information must be extracted
- **AND** an embedding must be generated (using `gemini-embedding-001`)
- **AND** stored in the `memory_embeddings` table asynchronously

#### Scenario: Semantic Recall
- **WHEN** a user asks a question that relates to past info
- **THEN** the system must perform a pgvector similarity search
- **AND** inject relevant memories into the system prompt as "contextual hints"

### Requirement: Memory Indexing
The system should maintain a high-level summary of the user's status and preferences.

#### Scenario: Summary Index Update
- **WHEN** multiple interactions have occurred
- **THEN** a lightweight summary index (stored in `home_context`) should be updated
- **AND** injected into the persona's dynamic prompt
