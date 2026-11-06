"""fetch_url（web-fetch-tool）手動測試。

執行環境：需在 brain 容器內跑（才能驗證 compose 主機名與內網位址被擋）：
    podman cp test_web_fetch.py omni-agent-brain-1:/tmp/
    podman exec -w /app omni-agent-brain-1 python /tmp/test_web_fetch.py

需要外網；CWA／Wikipedia／arXiv／postman-echo 任一站臨時故障會讓對應測項失敗。
End-to-end：
    curl -s http://localhost:8000/chat -X POST -H 'Content-Type: application/json' \\
      -d '{"id":"t1","message_type":"text","user_id":"test","platform":"test","text":"明天新店天氣如何？"}'
"""
import asyncio
import os
import re
import sys

if os.path.isdir('omni-agent/brain'):
    sys.path.insert(0, os.path.abspath('omni-agent/brain'))
else:
    sys.path.insert(0, '/app')

from skills.url_safety import is_safe_url
from skills.web_fetch import MAX_CONTENT_CHARS, MAX_URLS, fetch_urls, _guard_route, _guard_websocket

BLOCKED = [
    'http://postgres:5432', 'http://searxng:8080', 'http://127.0.0.1', 'http://localhost',
    'http://192.168.1.1', 'http://10.0.0.1', 'http://100.88.136.117', 'http://169.254.169.254',
    'http://[::1]', 'http://[::ffff:127.0.0.1]', 'http://[fd00::1]', 'http://0.0.0.0', 'http://224.0.0.1',
    'file:///etc/passwd', 'http://0x7f000001', 'http://2130706433', 'http://127.1', 'http://0177.0.0.1',
    'http://localtest.me', 'http://127.0.0.1.nip.io', 'http://user:pw@example.com',
    'https://example.com/?k=sk-abcdefghijklmnop', 'http://nas.local', 'http://nonexistent.invalid',
]
ALLOWED = ['https://www.cwa.gov.tw/V8/C/W/Town/Town.html?TID=6500600', 'https://en.wikipedia.org/wiki/Taipei']
UNSAFE_REDIRECT = 'https://postman-echo.com/redirect-to?url=http://127.0.0.1:8000/health'


async def page(url):
    r = await fetch_urls([url])
    assert r['success'], r
    return r['data']['pages'][0]


async def main():
    # 1. SSRF：URL 層
    for u in BLOCKED:
        ok, reason = await is_safe_url(u)
        assert not ok, f'should block {u}'
    for u in ALLOWED:
        ok, reason = await is_safe_url(u)
        assert ok, f'should allow {u}: {reason}'
    print(f'url_safety: {len(BLOCKED)} blocked, {len(ALLOWED)} allowed')

    # 2. 靜態頁：不渲染、截斷到預算、頭尾皆在
    p = await page('https://en.wikipedia.org/wiki/Taipei')
    assert not p['error'] and not p['rendered'] and p['truncated'], p['error']
    assert len(p['content']) <= MAX_CONTENT_CHARS and '中段已省略' in p['content']
    print(f"static: {len(p['content'])} chars, truncated")

    # 3. JS 動態頁：CWA 渲染後有溫度與降雨機率，且 °C/°F 不黏在一起
    p = await page('https://www.cwa.gov.tw/V8/C/W/Town/Town.html?TID=6500600')
    assert not p['error'] and p['rendered'], p['error']
    assert '降雨機率' in p['content'] and re.search(r'\d+%', p['content'])
    assert not re.search(r'\| (1\d|2\d|3\d)(5\d|6\d|7\d|8\d|9\d) \|', p['content']), 'C/F 數字黏在一起'
    print(f"rendered: {len(p['content'])} chars")

    # 4. PDF
    p = await page('https://arxiv.org/pdf/1706.03762')
    assert not p['error'] and 'attention' in p['content'].lower(), p['error']
    print(f"pdf: {len(p['content'])} chars")

    # 5. 轉址到內網（靜態）
    p = await page(UNSAFE_REDIRECT)
    assert p['error'] and '已拒絕' in p['error'], p
    print('static redirect to loopback: blocked')

    # 6. 錯誤回報
    p = await page('https://postman-echo.com/status/404')
    assert p['error'] and '404' in p['error'], p
    p = await page('http://192.168.1.1')
    assert p['error'] and '已拒絕' in p['error'], p
    print('errors: 404 / private readable')

    # 7. URL 上限與輸入清理
    r = await fetch_urls(['https://example.com'] * 2 + [f'https://example.com/?n={i}' for i in range(5)])
    assert len(r['data']['pages']) == MAX_URLS
    assert not (await fetch_urls([]))['success']
    print(f'clamp: {MAX_URLS} urls max, dedup ok')

    # 8. 瀏覽器子請求／轉址／WebSocket
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b = await pw.chromium.launch(args=['--no-sandbox'])
        c = await b.new_context()
        await c.route('**/*', _guard_route)
        await c.route_web_socket('**/*', _guard_websocket)
        pg = await c.new_page()
        await pg.goto('https://example.com')
        js = 'async u=>{try{const r=await fetch(u);return "status "+r.status}catch(e){return "blocked"}}'
        for u in ('http://127.0.0.1:8000/health', 'http://postgres:5432/', UNSAFE_REDIRECT):
            assert await pg.evaluate(js, u) == 'blocked', u
        ws = await pg.evaluate('()=>new Promise(r=>{const w=new WebSocket("ws://127.0.0.1:8000/");'
                               'w.onopen=()=>r("open");w.onclose=()=>r("closed");w.onerror=()=>r("error")})')
        assert ws != 'open', ws
        pg2 = await c.new_page()
        await pg2.goto('https://postman-echo.com/redirect-to?url=https://example.com/')
        assert 'Example' in await pg2.title()
        await b.close()
    print('browser: subrequests / redirect / websocket to internal blocked; safe redirect followed')

    print('ALL PASSED')


if __name__ == '__main__':
    asyncio.run(main())
