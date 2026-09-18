import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

# 僅在 routing_config.json 缺檔／壞檔時生效；平時被完全遮蔽，最容易藏過期 model id。
# 啟動 preflight（llm/preflight.py）會檢查實際載入的設定，此處務必與 routing_config.json 同步。
DEFAULT_CONFIG = {
    "providers": {
        "gemini": {
            "model": "gemini-2.5-flash",
            "enabled": True,
            "thinking_budget": -1,
            "upgrade_model": "gemini-2.5-pro"
        },
        "claude": {
            "model": "claude-sonnet-4-6",
            "enabled": True
        },
        "local": {
            "model": "gemma-4-26b-4bit",
            "enabled": True,
            "health_check": True
        }
    },
    "routing_rules": [
        {
            "name": "default",
            "condition": "*",
            "provider": "gemini",
            "thinking_budget": -1,
            "priority": 0
        }
    ],
    "fallback_chain": ["gemini", "claude", "local"]
}

def load_routing_config() -> Dict[str, Any]:
    """載入路由設定檔。"""
    config_path = os.path.join(os.path.dirname(__file__), "routing_config.json")
    
    if not os.path.exists(config_path):
        logger.warning(f"Routing config missing at {config_path}, using defaults.")
        return DEFAULT_CONFIG
        
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            logger.info("Routing config loaded successfully.")
            return config
    except Exception as e:
        logger.error(f"Failed to load routing config: {e}. Falling back to defaults.")
        return DEFAULT_CONFIG
