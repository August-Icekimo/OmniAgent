import logging
import os
import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .base import ModelClient, Message, LLMResponse
from .claude_client import ClaudeClient
from .gemini_client import GeminiClient
from .local_client import LocalClient
from config.config_loader import load_routing_config

logger = logging.getLogger(__name__)

class ModelRouter:
    """管理多個 LLM provider，提供動態路由與升級決策。"""

    def __init__(self, db_pool=None):
        self._clients: Dict[str, ModelClient] = {}
        self._config = load_routing_config()
        self._db_pool = db_pool
        self._default_provider = self._config.get("fallback_chain", ["gemini"])[0]
        
    def set_db_pool(self, db_pool):
        """延後設定 DB pool（例如在 app lifespan 中），並同步給支援 DB 的 Client。"""
        self._db_pool = db_pool
        for client in self._clients.values():
            if hasattr(client, "set_db_pool"):
                client.set_db_pool(db_pool)

    def register(self, client: ModelClient) -> None:
        """註冊一個 provider。"""
        self._clients[client.provider_name()] = client
        logger.info(
            "Registered LLM provider: %s (%s)",
            client.provider_name(),
            client.model_name(),
        )

    def select_provider(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """根據上下文決定初始 provider。"""
        # 0. audio/video 強制 Gemini（claude 無 audio、local 音訊/視訊未接線）。
        #    image 自 2026-06 起改走 routing_rules：local gemma（--mllm）具 vision，
        #    image_input 規則導 local 試點，FileAnalyzer._vision_chat 內含 gemini 升級保底。
        #    sticker/animation 自 Phase 1 起亦走 routing_rules。
        msg_type = context.get("message_type", "text")
        if msg_type in ["voice", "video"]:
            return {"provider": "gemini", "reason": f"multimodal:{msg_type}"}

        # 1. 檢查規則匹配
        rules = self._config.get("routing_rules", [])
        
        # 排序：優先級高的在前
        sorted_rules = sorted(rules, key=lambda x: x.get("priority", 0), reverse=True)
        
        for rule in sorted_rules:
            condition = rule.get("condition", "*")
            if self._match_condition(condition, context):
                provider = rule.get("provider")
                if provider in self._clients:
                    return {
                        "provider": provider,
                        "reason": f"auto:{rule['name']}",
                        "thinking_budget": rule.get("thinking_budget")
                    }
        
        # 2. Fallback
        return {
            "provider": self._default_provider,
            "reason": "default",
            "thinking_budget": -1
        }

    def _match_condition(self, condition: str, context: Dict[str, Any]) -> bool:
        """簡單的條件匹配邏輯。"""
        if condition == "*":
            return True
            
        # 支援的條件格式範例: "message_type == 'image'", "text_length < 50 AND no_skill_intent"
        # 這裡實作一個極度簡化的解析器
        try:
            msg_type = context.get("message_type", "text")
            text = context.get("text", "")
            text_length = len(text)
            has_skill_intent = context.get("has_skill_intent", False)
            
            if "message_type == 'image'" in condition and msg_type == "image":
                return True
            in_match = re.search(r"message_type in \(([^)]+)\)", condition)
            if in_match:
                allowed = [s.strip().strip("'\"") for s in in_match.group(1).split(",")]
                if msg_type in allowed:
                    return True
            if "has_skill_intent" in condition and has_skill_intent:
                return True
            if "text_length < 50" in condition and text_length < 50:
                if "no_skill_intent" in condition and not has_skill_intent:
                    return True
                if "no_skill_intent" not in condition:
                    return True
        except Exception:
            pass
            
        return False

    async def check_upgrade(self, current_provider: str, complexity: str, user_id: str) -> Dict[str, Any]:
        """檢查是否需要升級模型。"""
        rules = self._config.get("upgrade_rules", [])
        
        for rule in rules:
            if rule["trigger_provider"] == current_provider and rule["trigger_complexity"] == complexity:
                # 檢查配額
                quota_ok = await self.check_quota(user_id)
                if not quota_ok:
                    logger.warning(f"Upgrade quota exceeded for user {user_id}")
                    return {"upgrade": False, "reason": "quota_exceeded"}
                
                return {
                    "upgrade": True,
                    "target_provider": rule["upgrade_to_provider"],
                    "target_model": rule.get("upgrade_to_model"),
                    "require_confirmation": rule.get("require_confirmation", True),
                    "auto_confirm_seconds": rule.get("auto_confirm_seconds", 15),
                    "reason": f"upgrade:complexity_{complexity}"
                }
                
        return {"upgrade": False}

    async def check_quota(self, user_id: str) -> bool:
        """檢查每日升級配額與冷卻時間。"""
        if not self._db_pool:
            logger.warning("DB unavailable, allowing upgrade (fail-open)")
            return True
            
        try:
            now = datetime.now() # 容器內已設為 Asia/Taipei
            today = now.strftime("%Y-%m-%d")
            quota_key = f"upgrade_quota:{today}"
            cooldown_key = f"upgrade_cooldown:{user_id}"
            
            # 1. 檢查當日總次數 (全系統或按需分配，這裡先實作全系統限制)
            quota_limit = self._config.get("upgrade_quota", {}).get("daily_limit", 20)
            
            row = await self._db_pool.fetchrow("SELECT value FROM home_context WHERE key = $1", quota_key)
            current_count = 0
            if row:
                current_count = row['value'].get('count', 0)
            
            if current_count >= quota_limit:
                # 檢查是否有 admin override
                override_row = await self._db_pool.fetchrow("SELECT value FROM home_context WHERE key = $1", f"upgrade_quota_override:{today}")
                if not override_row or current_count >= override_row['value'].get('limit', quota_limit):
                    return False
            
            # 2. 檢查冷卻時間 (10 分鐘內最多 3 次)
            cooldown_minutes = self._config.get("upgrade_quota", {}).get("cooldown_minutes", 10)
            cooldown_limit = self._config.get("upgrade_quota", {}).get("cooldown_limit", 3)
            
            cw_row = await self._db_pool.fetchrow("SELECT value FROM home_context WHERE key = $1", cooldown_key)
            history = []
            if cw_row:
                history = cw_row['value'].get('history', [])
                
            # 清理過期歷史
            cutoff = (now - timedelta(minutes=cooldown_minutes)).isoformat()
            history = [h for h in history if h > cutoff]
            
            if len(history) >= cooldown_limit:
                return False
                
            return True
        except Exception as e:
            logger.error(f"Quota DB check failed: {e}. Fail-open.")
            return True

    async def consume_quota(self, user_id: str):
        """消耗一次升級配額。"""
        if not self._db_pool:
            return
            
        try:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            quota_key = f"upgrade_quota:{today}"
            cooldown_key = f"upgrade_cooldown:{user_id}"
            
            # 更新當日計數
            await self._db_pool.execute("""
                INSERT INTO home_context (key, value) 
                VALUES ($1, jsonb_build_object('count', 1))
                ON CONFLICT (key) DO UPDATE SET value = jsonb_build_object('count', (home_context.value->>'count')::int + 1)
            """, quota_key)
            
            # 更新冷卻歷史
            cw_row = await self._db_pool.fetchrow("SELECT value FROM home_context WHERE key = $1", cooldown_key)
            history = []
            if cw_row:
                history = cw_row['value'].get('history', [])
            
            history.append(now.isoformat())
            # 只保留最近幾筆
            history = history[-10:]
            
            await self._db_pool.execute("""
                INSERT INTO home_context (key, value) 
                VALUES ($1, $2)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, cooldown_key, json.dumps({"history": history}))
            
        except Exception as e:
            logger.error(f"Failed to consume quota: {e}")

    def context_length(self, provider: str) -> int:
        """回傳 provider 設定的 context window 上限（tokens），未設定回 0。"""
        raw = self._config.get("providers", {}).get(provider, {}).get("context_length")
        try:
            return int(raw) if raw else 0
        except (TypeError, ValueError):
            return 0

    async def chat(
        self,
        messages: List[Message],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        provider: str | None = None,
        thinking_budget: int | None = None,
        tools: list | None = None,
        tool_choice: str = "auto",
        caller: str = "unknown"
    ) -> LLMResponse:
        """主入口：根據配置和 fallback 鏈選擇合適的 provider。

        傳入 `tools` 時啟用 provider-native function calling，回應可能含
        `tool_calls`（見 LLMResponse）。"""
        logger.info(f"Router.chat called by {caller}")
        
        # 1. 決定候選名單
        primary_target = provider or self._default_provider
        fallback_chain = self._config.get("fallback_chain", ["gemini", "claude", "local"])
        
        # 構建嘗試清單：指定或預設的排第一，其餘按 fallback_chain 順序
        candidates = [primary_target]
        for fb in fallback_chain:
            # 確保 fb 在註冊名單中且不在候選名單中
            if fb in self._clients and fb not in candidates:
                candidates.append(fb)
                
        last_error = None
        fallback_triggered = False
        
        msg_type = "text"
        has_audio_video = False
        for m in messages:
            if hasattr(m, 'content') and isinstance(m.content, list):
                 # This is a complex multimodal message part list (Phase 4D)
                 msg_type = "multimodal"
                 if any(p.get("type") in ("audio", "video") for p in m.content):
                     has_audio_video = True

        for i, target in enumerate(candidates):
            client = self._clients.get(target)
            if not client:
                continue

            # 多模態能力閘門 (Phase 1)：
            # - audio/video payload 僅 gemini 可處理（claude 無 audio、local 未接線）
            # - image payload 依 client 能力查詢（supports_vision）
            if msg_type == "multimodal":
                if has_audio_video:
                    if target != "gemini":
                        logger.warning(f"Provider {target} does not support audio/video payload. Skipping.")
                        continue
                elif not await client.supports_vision():
                    logger.warning(f"Provider {target} does not support image payload. Skipping.")
                    continue

            # 獲取 provider 專屬配置 (例如 model 覆蓋)
            provider_config = self._config.get("providers", {}).get(target, {})
            target_model = provider_config.get("model")
            target_thinking_budget = thinking_budget if thinking_budget is not None else provider_config.get("thinking_budget", -1)
            # provider config 為上限；呼叫端明確指定時取兩者較小值（如貼圖感知收緊輸出）
            config_max_tokens = provider_config.get("max_tokens")
            if max_tokens is not None:
                target_max_tokens = min(max_tokens, config_max_tokens) if config_max_tokens else max_tokens
            else:
                target_max_tokens = config_max_tokens or 4096

            if i > 0:
                logger.warning(f"Fallback triggered: {candidates[0]} failed (likely Quota/429), trying {target}...")
                fallback_triggered = True

            logger.info(f"Router: attempting {target} with model {target_model}")
            try:
                # 執行對話
                try:
                    response = await client.chat(
                        messages,
                        system_prompt=system_prompt,
                        temperature=temperature,
                        max_tokens=target_max_tokens,
                        thinking_budget=target_thinking_budget,
                        tools=tools,
                        tool_choice=tool_choice,
                        model=target_model
                    )
                except TypeError:
                    # 處理不支持 thinking_budget 的 Client
                    response = await client.chat(
                        messages,
                        system_prompt=system_prompt,
                        temperature=temperature,
                        max_tokens=target_max_tokens,
                        tools=tools,
                        tool_choice=tool_choice,
                    )
                
                # 如果是退路觸發的，加上思考表情符號
                if fallback_triggered:
                    response.content = "🤔 " + response.content
                    
                return response
                
            except Exception as e:
                logger.error(f"Provider {target} failed: {e}")
                last_error = e
                continue
        
        # 如果所有候選 Provider 都失敗了
        if msg_type == "multimodal":
             # Phase 4D: 多模態失敗不拋出通用錯誤，讓調用端能處理 Honest Fallback
             logger.error(f"Multimodal routing failed after trying all candidates: {candidates}")
             return LLMResponse(content="", model="none", provider="none", usage={})

        raise RuntimeError(f"All providers in fallback chain failed. Last error: {last_error}")

def create_default_router() -> ModelRouter:
    """建立路由並偵測可用 Provider。"""
    router = ModelRouter()
    config = load_routing_config()

    if os.environ.get("ANTHROPIC_API_KEY"):
        router.register(ClaudeClient())
        logger.info("Claude provider enabled")

    if os.environ.get("GEMINI_API_KEY"):
        router.register(GeminiClient())
        logger.info("Gemini API Key provider enabled")

    if os.environ.get("MLX_BASE_URL"):
        is_test = os.environ.get("OMNI_ENV") == "test"
        if is_test:
            logger.info("Local MLX provider disabled in test mode")
        else:
            local_config = config.get("providers", {}).get("local", {})
            client = LocalClient(
                thinking_budget=local_config.get("thinking_budget", -1),
            )
            router.register(client)
            logger.info("Local MLX provider enabled")

    return router
