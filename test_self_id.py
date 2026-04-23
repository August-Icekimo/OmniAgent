import asyncio
import os
import sys

# add brain to path
sys.path.insert(0, os.path.abspath('omni-agent/brain'))

from llm.oauth_gemini_client import OAuthGeminiClient
from llm.base import Message, Role

async def main():
    client = OAuthGeminiClient(model="gemini-2.5-pro")
    messages = [
        Message(role=Role.USER, content="What is your exact model name and version? Are you Pro or Flash?")
    ]
    response = await client.chat(messages, max_tokens=100)
    print(f"Model used: {response.model}")
    print(f"Response: {response.content}")

if __name__ == "__main__":
    asyncio.run(main())
