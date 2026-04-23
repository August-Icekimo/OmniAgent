import sys
import os
import json
sys.path.insert(0, os.path.abspath('omni-agent/brain'))

from config.config_loader import load_routing_config
from llm.router import ModelRouter, create_default_router

router = create_default_router()
print("Registered clients:", router._clients.keys())

decision = router.select_provider({
    "text": "not so sure, check it out again.",
    "message_type": "text",
    "has_skill_intent": False
})
print("Decision for short text:", decision)

decision = router.select_provider({
    "text": "This is a much longer text that should not match short_simple rule.",
    "message_type": "text",
    "has_skill_intent": False
})
print("Decision for long text:", decision)
