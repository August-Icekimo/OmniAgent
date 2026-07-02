"""AGY 摘要 specialist 的手動驗證腳本（不經 brain，直接打 A2A）。

用法（在 agy 容器內，或任何裝了 a2a-sdk[http-server] 且能連到 AGY 的環境）：
    podman compose exec -T agy python - < agy/test_summarize.py
或：
    python test_summarize.py            # BASE 預設 http://localhost:8000

驗證 Task 2：Agent Card 可解析 + single-turn 摘要 task 回結構化結果。
"""

import asyncio
import os

import httpx
from a2a.client import (
    A2ACardResolver,
    ClientConfig,
    ClientFactory,
    create_text_message_object,
)

BASE = os.getenv("AGY_TEST_URL", "http://localhost:8000")

_SAMPLE = (
    "OmniAgent 是一個 HomeLab 家庭 AI 助理，代號 Cindy，由 Go API gateway、"
    "Python FastAPI brain 與單一 PostgreSQL 組成，統一 LINE、Telegram、iMessage 並支援多家 LLM。"
    "系統採 turn-based 組裝：gateway 收訊入佇列，forwarder 把同一使用者的連續訊息組成一個 turn "
    "送往 brain 背景處理，結果寫回 turns 表再投遞。近期新增 A2A specialist agent 架構，讓 Cindy "
    "可把長文摘要等外包工作委派給隔離容器中的 ADK 2.0 agent，透過 A2A protocol 跨容器通訊。"
) * 3


def _extract_text(obj) -> str:
    out = []
    for p in (getattr(obj, "parts", None) or []):
        r = getattr(p, "root", p)
        t = getattr(r, "text", None)
        if t:
            out.append(t)
    return "".join(out)


async def summarize(text: str) -> str:
    async with httpx.AsyncClient(timeout=120) as hx:
        card = await A2ACardResolver(httpx_client=hx, base_url=BASE).get_agent_card()
        client = ClientFactory(ClientConfig(httpx_client=hx)).create(card)
        msg = create_text_message_object(content="請用繁中摘要以下文字（3-4 句）：\n" + text)
        final = ""
        async for event in client.send_message(msg):
            if isinstance(event, tuple):
                task, _ = event
                for art in (getattr(task, "artifacts", None) or []):
                    final = _extract_text(art) or final
            else:
                final = _extract_text(event) or final
        return final.strip()


if __name__ == "__main__":
    result = asyncio.run(summarize(_SAMPLE))
    print("SUMMARY:", result or "<EMPTY>")
