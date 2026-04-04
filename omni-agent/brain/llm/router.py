"""ModelRouter — 路由決策 + 小腦袋模型升級策略。

路由邏輯：
- 預設使用 Claude（主力模型，語感最佳）
- 視覺/multimodal 任務 → Gemini（成本較低）
- 簡單日常任務（查詢、翻譯等） → Local MLX（零成本）
- 過載升級時 → 切換至更強模型（如 Claude Opus）

Phase 2 先實作基本路由（固定 Claude），
Phase 4 再加入完整的動態升級策略。
"""

import logging
from .base import ModelClient, Message, LLMResponse
from .claude_client import ClaudeClient
from .gemini_client import GeminiClient
from .local_client import LocalClient

logger = logging.getLogger(__name__)


class ModelRouter:
    """管理多個 LLM provider，決定每次請求要用哪一個。"""

    def __init__(self):
        self._clients: dict[str, ModelClient] = {}
        self._default_provider: str = "claude"

    def register(self, client: ModelClient) -> None:
        """註冊一個 provider。"""
        self._clients[client.provider_name()] = client
        logger.info(
            "Registered LLM provider: %s (%s)",
            client.provider_name(),
            client.model_name(),
        )

    def set_default(self, provider: str) -> None:
        """設定預設 provider。"""
        if provider not in self._clients:
            raise ValueError(f"Unknown provider: {provider}")
        self._default_provider = provider

    async def chat(
        self,
        messages: list[Message],
        *,
        system_prompt: str | None = None,
        provider: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """路由請求到適當的 provider。

        Args:
            messages: 對話訊息列表
            system_prompt: system prompt（會利用 provider 的 cache 機制）
            provider: 指定 provider，None 則使用預設
            temperature: 溫度參數
            max_tokens: 最大回覆 token 數
        """
        target = provider or self._default_provider
        client = self._clients.get(target)

        if client is None:
            # fallback 到任何可用的 provider
            if self._clients:
                target = next(iter(self._clients))
                client = self._clients[target]
                logger.warning(
                    "Provider '%s' not available, falling back to '%s'",
                    provider,
                    target,
                )
            else:
                raise RuntimeError("No LLM providers registered")

        logger.info("Routing to provider: %s (%s)", target, client.model_name())

        response = await client.chat(
            messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # Log cache 命中狀態（成本監控用）
        if response.cached:
            logger.info(
                "Cache HIT on %s — saved tokens: %s",
                target,
                response.usage.get("cache_read_tokens", "unknown"),
            )

        return response


def create_default_router() -> ModelRouter:
    """建立預設 router，自動偵測可用的 provider。

    根據環境變數判斷哪些 provider 可用：
    - ANTHROPIC_API_KEY → Claude
    - GEMINI_API_KEY → Gemini
    - MLX_BASE_URL → Local MLX
    """
    import os

    router = ModelRouter()

    if os.environ.get("ANTHROPIC_API_KEY"):
        router.register(ClaudeClient())
        router.set_default("claude")
        logger.info("Claude provider enabled (default)")

    if os.environ.get("GEMINI_API_KEY"):
        router.register(GeminiClient())
        logger.info("Gemini provider enabled")

    if os.environ.get("MLX_BASE_URL"):
        router.register(LocalClient())
        logger.info("Local MLX provider enabled")

    if not router._clients:
        logger.warning("No LLM providers configured! Set API keys in .env")

    return router
