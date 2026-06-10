"""web_search provider 手動測試。

執行環境：SearXNG 只在 compose 內網可達，建議進 brain 容器跑：
    podman cp test_web_search.py omni-agent-brain-1:/tmp/
    podman exec -e SEARXNG_URL=http://searxng:8080 omni-agent-brain-1 python /tmp/test_web_search.py

End-to-end 驗證（planner → executor → reporter 全鏈路）：
    curl -s http://localhost:8000/chat -X POST -H 'Content-Type: application/json' \
      -d '{"user_id": "test", "platform": "test", "text": "幫我查一下今天台北的天氣"}'
"""
import asyncio
import os
import sys

if os.path.isdir('omni-agent/brain'):
    sys.path.insert(0, os.path.abspath('omni-agent/brain'))
else:
    sys.path.insert(0, '/app')

from skills.web_search import get_web_search_provider, MAX_RESULTS, MAX_DESCRIPTION_CHARS


async def main():
    provider = get_web_search_provider()
    print("Provider:", provider.name, "| available:", provider.is_available())

    # 1. 正常搜尋：統一格式、position 從 1 起算
    r = await provider.search("台北天氣", limit=5)
    assert r["success"], r
    web = r["data"]["web"]
    assert web and web[0]["position"] == 1
    assert all({"title", "url", "description", "position"} <= set(x) for x in web)
    print(f"normal search: {len(web)} results, top = {web[0]['title'][:40]}")

    # 2. limit 夾制 + description 截斷
    r = await provider.search("python tutorial", limit=99)
    assert r["success"], r
    assert len(r["data"]["web"]) <= MAX_RESULTS
    assert all(len(x["description"]) <= MAX_DESCRIPTION_CHARS for x in r["data"]["web"])
    print(f"clamp/truncate: ok ({len(r['data']['web'])} results)")

    # 3. SEARXNG_URL 未設定 → 不可用、回可讀錯誤、不 raise
    saved = os.environ.pop("SEARXNG_URL", None)
    try:
        assert not provider.is_available()
        r = await provider.search("x")
        assert r["success"] is False and r["error"]
        print("unset url: ok ->", r["error"])
    finally:
        if saved:
            os.environ["SEARXNG_URL"] = saved

    # 4. 服務不可達 → success=False、不 raise
    os.environ["SEARXNG_URL"] = "http://127.0.0.1:9"
    r = await provider.search("x")
    assert r["success"] is False and r["error"]
    print("unreachable: ok ->", r["error"][:60])
    if saved:
        os.environ["SEARXNG_URL"] = saved

    print("ALL PASS")


asyncio.run(main())
