import json
import logging
from datetime import datetime
import asyncpg

logger = logging.getLogger("brain.memory.short_term")

class ShortTermMemory:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def save(self, user_id: str, platform: str, messages: list[dict]):
        """
        Saves user and assistant messages to the `conversations` table.
        Updates the memory index (summary) for the user.
        """
        if not self.pool:
            logger.warning(f"No DB pool, skipping short-term save for user {user_id}")
            return

        try:
            async with self.pool.acquire() as conn:
                # Store the full conversation
                await conn.execute(
                    "INSERT INTO conversations (user_id, platform, messages) VALUES ($1, $2, $3)",
                    user_id, platform, messages
                )

                # Update memory index (lightweight summary) - accumulate history
                key = f"memory_index:{user_id}"
                row = await conn.fetchrow("SELECT value FROM home_context WHERE key = $1", key)
                existing_summary = row['value'] if row else []

                new_entries = []
                for msg in messages:
                    if msg['role'] == 'user':
                        text = msg['content'][:50] + ("..." if len(msg['content']) > 50 else "")
                        new_entries.append(text)

                # Prepend new entries and truncate to last 5
                updated_summary = (new_entries + existing_summary)[:5]

                if updated_summary:
                    await conn.execute(
                        """
                        INSERT INTO home_context (key, value)
                        VALUES ($1, $2)
                        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                        """,
                        key, updated_summary
                    )
        except Exception as e:
            logger.error(f"Failed to save short-term memory for user {user_id}: {e}")
            # Do not re-raise to avoid breaking /chat

    async def load(self, user_id: str, limit: int = 5) -> list[dict]:
        """
        Loads the most recent N rounds of conversation history.
        """
        if not self.pool:
            return []

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT messages FROM conversations WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
                    user_id, limit
                )

                history = []
                # Rows are newest first, we want them oldest first
                for row in reversed(rows):
                    history.extend(row['messages'])
                return history
        except Exception as e:
            logger.error(f"Failed to load short-term memory for user {user_id}: {e}")
            return []
