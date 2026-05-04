import os
import time
import base64
import logging
import json
import httpx
from datetime import datetime, timezone
from typing import List, Optional, Any

from google import genai
from google.genai import types
from google.oauth2.credentials import Credentials

from .base import ModelClient, Message, LLMResponse, Role

logger = logging.getLogger("brain.llm.oauth_gemini_client")

# Default credentials for gemini-cli (public client)
DEFAULT_CLIENT_ID = "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com"
DEFAULT_CLIENT_SECRET = "" # Public clients often have no secret

class OAuthRefreshError(Exception):
    """Raised when OAuth token refresh fails."""
    pass

class OAuthGeminiClient(ModelClient):
    """Google Gemini Client using OAuth 2.0 (Pro Subscription Quota)."""

    def __init__(self, model: str = "gemini-2.0-pro-exp-02-05"):
        self._model = model
        self._refresh_token = os.environ.get("GEMINI_REFRESH_TOKEN")
        self._client_id = os.environ.get("GEMINI_CLIENT_ID", DEFAULT_CLIENT_ID)
        self._client_secret = os.environ.get("GEMINI_CLIENT_SECRET", DEFAULT_CLIENT_SECRET)
        self._db_pool = None
        self._access_token = None
        self._expiry_ms = 0
        self._cached_content = None # For context caching

    def set_db_pool(self, pool):
        """Set the database pool for token caching."""
        self._db_pool = pool

    async def _get_valid_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        now_ms = int(time.time() * 1000)

        # 1. Try to load from DB if not in memory or expired
        if (not self._access_token or self._expiry_ms < now_ms + 60000) and self._db_pool:
            try:
                row = await self._db_pool.fetchrow(
                    "SELECT access_token, expiry_ms FROM oauth_tokens WHERE provider = 'gemini'"
                )
                if row:
                    self._access_token = row['access_token']
                    self._expiry_ms = row['expiry_ms']
                    logger.debug("Loaded OAuth token from DB")
            except Exception as e:
                logger.error(f"Failed to load OAuth token from DB: {e}")

        # 2. Refresh if still expired (or not found)
        if not self._access_token or self._expiry_ms < now_ms + 60000:
            await self._refresh_access_token()

        return self._access_token

    async def _refresh_access_token(self):
        """Call Google OAuth endpoint to refresh the access token."""
        if not self._refresh_token:
            raise OAuthRefreshError("GEMINI_REFRESH_TOKEN not set")

        logger.info("Refreshing Gemini OAuth access token...")
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                data = {
                    "client_id": self._client_id,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                }
                if self._client_secret:
                    data["client_secret"] = self._client_secret

                response = await client.post("https://oauth2.googleapis.com/token", data=data)
                
                if response.status_code != 200:
                    logger.error(f"OAuth refresh failed with status {response.status_code}: {response.text}")
                    raise OAuthRefreshError(f"Google OAuth refresh failed: {response.status_code}")

                res_json = response.json()
                self._access_token = res_json["access_token"]
                
                # expires_in is in seconds, convert to expiry_ms
                expires_in = res_json.get("expires_in", 3500)
                self._expiry_ms = int(time.time() * 1000) + (expires_in * 1000)

                # 3. Save back to DB
                if self._db_pool:
                    try:
                        await self._db_pool.execute(
                            """
                            INSERT INTO oauth_tokens (provider, access_token, refresh_token, expiry_ms, updated_at)
                            VALUES ('gemini', $1, $2, $3, CURRENT_TIMESTAMP)
                            ON CONFLICT (provider) DO UPDATE 
                            SET access_token = EXCLUDED.access_token, 
                                expiry_ms = EXCLUDED.expiry_ms,
                                updated_at = CURRENT_TIMESTAMP
                            """,
                            self._access_token, self._refresh_token, self._expiry_ms
                        )
                        logger.info("Gemini OAuth token refreshed and cached in DB")
                    except Exception as e:
                        logger.error(f"Failed to save refreshed token to DB: {e}")
                else:
                    logger.warning("Gemini OAuth token refreshed but DB pool not available for caching")

        except httpx.RequestError as e:
            logger.error(f"Network error during OAuth refresh: {e}")
            raise OAuthRefreshError(f"Network error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during OAuth refresh: {e}")
            raise OAuthRefreshError(f"Refresh failed: {e}")

    async def _get_or_create_cache(self, client: genai.Client, system_prompt: str) -> Any:
        """Re-use existing context cache logic from GeminiClient."""
        # Simple implementation for now, can be expanded to match GeminiClient's logic
        if self._cached_content is not None:
            return self._cached_content

        if len(system_prompt) < 2000:
            return None

        try:
            cached = client.caches.create(
                model=self._model,
                config=types.CreateCachedContentConfig(
                    system_instruction=system_prompt,
                    ttl="3600s",
                ),
            )
            self._cached_content = cached
            return cached
        except Exception:
            return None

    async def chat(
        self,
        messages: List[Message],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        thinking_budget: int | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        """Send chat request using OAuth credentials."""
        token = await self._get_valid_token()
        target_model = model or self._model
        
        # Initialize SDK Client with OAuth token
        creds = Credentials(token=token)
        client = genai.Client(credentials=creds)

        contents = []
        for m in messages:
            if m.role == Role.SYSTEM:
                continue
            role = "user" if m.role == Role.USER else "model"

            parts = []
            if isinstance(m.content, str):
                parts.append(types.Part(text=m.content))
            elif isinstance(m.content, list):
                # Handle multimodal parts (Phase 4D)
                for p in m.content:
                    if p.get("type") == "text":
                        parts.append(types.Part(text=p["text"]))
                    elif p.get("type") == "image":
                        data = p["data"]
                        if isinstance(data, str):
                            data = base64.b64decode(data)
                        parts.append(types.Part(inline_data=types.Blob(
                            mime_type=p["mime_type"],
                            data=data
                        )))
                    elif p.get("type") == "audio":
                        data = p["data"]
                        if isinstance(data, str):
                            data = base64.b64decode(data)
                        parts.append(types.Part(inline_data=types.Blob(
                            mime_type=p["mime_type"],
                            data=data
                        )))
                    elif p.get("type") == "video":
                        data = p["data"]
                        if isinstance(data, str):
                            data = base64.b64decode(data)
                        parts.append(types.Part(inline_data=types.Blob(
                            mime_type=p["mime_type"],
                            data=data
                        )))

            contents.append(types.Content(role=role, parts=parts))

        generate_config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        if thinking_budget is not None and thinking_budget >= 0:
            generate_config.thinking_config = types.ThinkingConfig(
                include_thoughts=True,
                thinking_budget=thinking_budget
            )

        # Handle Context Caching
        cached_content = None
        if system_prompt:
            try:
                cached_content = await self._get_or_create_cache(client, system_prompt)
            except Exception as e:
                logger.warning(f"Context caching failed (non-blocking): {e}")
                cached_content = None

        if cached_content:
            config_params = {
                "temperature": temperature,
                "max_output_tokens": max_tokens,
                "cached_content": cached_content.name,
            }
            if thinking_budget is not None and thinking_budget >= 0:
                config_params["thinking_config"] = types.ThinkingConfig(
                    include_thoughts=True,
                    thinking_budget=thinking_budget
                )
            
            response = client.models.generate_content(
                model=target_model,
                contents=contents,
                config=types.GenerateContentConfig(**config_params),
            )
        else:
            if system_prompt:
                generate_config.system_instruction = system_prompt
            response = client.models.generate_content(
                model=target_model,
                contents=contents,
                config=generate_config,
            )

        usage = {}
        if response.usage_metadata:
            usage = {
                "input_tokens": response.usage_metadata.prompt_token_count,
                "output_tokens": response.usage_metadata.candidates_token_count,
            }
            if hasattr(response.usage_metadata, "cached_content_token_count"):
                usage["cache_read_tokens"] = response.usage_metadata.cached_content_token_count

        return LLMResponse(
            content=response.text,
            model=target_model,
            provider="gemini_oauth",
            usage=usage,
            cached=cached_content is not None,
        )

    def provider_name(self) -> str:
        return "gemini_oauth"

    def model_name(self) -> str:
        return self._model

    async def supports_vision(self) -> bool:
        return True
