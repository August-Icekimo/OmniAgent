import asyncio
import logging
import os
import httpx
import asyncpg
from typing import List, Optional

logger = logging.getLogger("brain.memory.long_term")

class LongTermMemory:
    def __init__(self, pool: asyncpg.Pool, router=None):
        self.pool = pool
        self.router = router
        self.voyage_api_key = os.getenv("VOYAGE_API_KEY")
        self.voyage_url = "https://api.voyageai.com/v1/embeddings"

    async def _get_embedding(self, text: str) -> List[float]:
        """Gets embedding from Voyage AI with retry logic."""
        if not self.voyage_api_key:
            logger.error("VOYAGE_API_KEY not found in environment")
            return []

        max_retries = 3
        async with httpx.AsyncClient() as client:
            for attempt in range(max_retries):
                payload = {
                    "input": [text],
                    "model": "voyage-3"
                }
                headers = {
                    "Authorization": f"Bearer {self.voyage_api_key}",
                    "Content-Type": "application/json"
                }
                try:
                    resp = await client.post(self.voyage_url, json=payload, headers=headers, timeout=10.0)
                    if resp.status_code == 200:
                        data = resp.json()
                        return data['data'][0]['embedding']
                    elif resp.status_code >= 500 or resp.status_code == 429:
                        logger.warning(f"Voyage AI API error {resp.status_code}, retrying ({attempt+1}/{max_retries})...")
                        await asyncio.sleep(2 ** attempt)
                    else:
                        logger.error(f"Voyage AI embedding failed: {resp.status_code} - {resp.text}")
                        break
                except Exception as e:
                    logger.error(f"Error calling Voyage AI: {e}")
                    await asyncio.sleep(2 ** attempt)
        return []

    async def _summarize_conversation(self, messages: List[dict]) -> str:
        """Uses LLM (Gemini) to summarize the conversation round."""
        if not self.router:
            # Fallback to simple concatenation
            return "\n".join([f"{m['role']}: {m['content']}" for m in messages[-2:]])

        # Import inside to avoid circular dependency
        from llm import Message, Role

        system_prompt = (
            "你是一個負責提取家庭對話重點的秘書。請用 100 字以內摘要這段對話的關鍵資訊，"
            "例如家人的偏好、提到的計畫或重要生活瑣事。如果沒有有意義的資訊，回傳「無重要資訊」。"
        )

        # messages is a list of dicts from conversations table
        # Convert to LLM Message objects
        llm_messages = [Message(role=Role(m['role']), content=m['content']) for m in messages]

        try:
            # We want to force Gemini for this as per requirement
            response = await self.router.chat(llm_messages, system_prompt=system_prompt, provider="gemini")
            return response.content.strip()
        except Exception as e:
            logger.error(f"Summarization failed: {e}")
            # Fallback to last user message
            for m in reversed(messages):
                if m['role'] == 'user':
                    return m['content']
            return ""

    async def store(self, user_id: str, messages: List[dict]):
        """
        Extracts key info, generates embedding, and stores in `memory_embeddings`.
        Intended to be called asynchronously.
        """
        if not self.pool:
            return

        summary = await self._summarize_conversation(messages)
        if not summary or "無重要資訊" in summary:
            return

        embedding = await self._get_embedding(summary)
        if not embedding:
            return

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO memory_embeddings (user_id, content, embedding) VALUES ($1, $2, $3)",
                    user_id, summary, embedding
                )
            logger.info(f"Stored long-term memory for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to store long-term memory: {e}")

    async def recall(self, user_id: str, query: str, limit: int = 3) -> List[str]:
        """
        Performs semantic search using pgvector.
        """
        if not self.pool:
            return []

        query_embedding = await self._get_embedding(query)
        if not query_embedding:
            return []

        try:
            async with self.pool.acquire() as conn:
                # Using cosine similarity operator <=>
                # pgvector 0.8+ uses <=> for cosine distance
                rows = await conn.fetch(
                    """
                    SELECT content FROM memory_embeddings
                    WHERE user_id = $1 AND (embedding <=> $2::vector) < 0.8
                    ORDER BY embedding <=> $2::vector ASC
                    LIMIT $3
                    """,
                    user_id, query_embedding, limit
                )
                return [row['content'] for row in rows]
        except Exception as e:
            logger.error(f"Failed to recall long-term memory: {e}")
            return []
