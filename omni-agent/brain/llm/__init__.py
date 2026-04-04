"""LLM module — 原廠 SDK 直連，取代 LiteLLM。"""

from .base import ModelClient, Message, LLMResponse, Role
from .router import ModelRouter, create_default_router

__all__ = [
    "ModelClient",
    "Message",
    "LLMResponse",
    "Role",
    "ModelRouter",
    "create_default_router",
]
