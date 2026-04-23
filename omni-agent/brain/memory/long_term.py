import asyncio
import logging
import os
from typing import List, Optional

import asyncpg
from google import genai
from google.genai import types as genai_types

logger = logging.getLogger("brain.memory.long_term")

# Gemini Embedding model — native output is 3072, we truncate to 768
# to fit within pgvector HNSW index limit (max 2000 dims).
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMS = 768


class LongTermMemory:
    def __init__(self, pool: asyncpg.Pool, router=None):
        self.pool = pool
        self.router = router
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            self._genai_client = genai.Client(api_key=api_key)
        else:
            self._genai_client = None
            logger.warning("GEMINI_API_KEY not set — long-term memory embedding disabled")

    async def _get_embedding(self, text: str) -> List[float]:
        """Gets embedding from Google Gemini Embedding API."""
        if not self._genai_client:
            logger.error("Gemini client not available for embedding")
            return []

        try:
            result = self._genai_client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=text,
                config=genai_types.EmbedContentConfig(
                    output_dimensionality=EMBEDDING_DIMS,
                ),
            )
            return list(result.embeddings[0].values)
        except Exception as e:
            logger.error(f"Gemini embedding failed: {e}")
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
            response = await self.router.chat(llm_messages, system_prompt=system_prompt)
            if response and response.content:
                return response.content.strip()
            else:
                logger.warning("Summarization returned empty content, using fallback")
                for m in reversed(messages):
                    if m['role'] == 'user':
                        return m['content']
                return ""
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
            # Convert embedding to pgvector-compatible string format
            embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO memory_embeddings (user_id, content, embedding) VALUES ($1, $2, $3::vector)",
                    user_id, summary, embedding_str
                )
            logger.info(f"Stored long-term memory for user {user_id}, dims={len(embedding)}")
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
            embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

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
                    user_id, embedding_str, limit
                )
                return [row['content'] for row in rows]
        except Exception as e:
            logger.error(f"Failed to recall long-term memory: {e}")
            return []
