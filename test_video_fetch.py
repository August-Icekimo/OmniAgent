"""analyze_video_url（short-video-fetch）手動測試。

執行環境：需在 brain 容器內跑（yt-dlp、ffmpeg、Gemini 金鑰、cookie 掛載都在容器內）：
    podman cp test_video_fetch.py omni-agent-brain-1:/tmp/
    podman exec -w /app omni-agent-brain-1 python /tmp/test_video_fetch.py

需要外網與 Gemini 額度；平台反爬蟲會讓個別測項偶發失敗——先用
    podman exec omni-agent-brain-1 python -m yt_dlp --simulate '<url>'
區分是平台／yt-dlp 的問題還是程式問題（見 docs/short_video_fetch_sop.md）。

平台連結會失效，以下可用環境變數覆寫或補上（沒給就跳過該項）：
    VF_TIKTOK  VF_INSTAGRAM  VF_DOUYIN  VF_TWITTER  VF_XHS  VF_BILIBILI  VF_SHORTLINK
例：podman exec -e VF_TWITTER='https://x.com/.../status/...' -w /app omni-agent-brain-1 python /tmp/test_video_fetch.py

End-to-end：
    curl -s http://localhost:8000/chat -X POST -H 'Content-Type: application/json' \\
      -d '{"id":"t1","message_type":"text","user_id":"test","platform":"test","text":"這支影片在演什麼？https://www.tiktok.com/@pokemonlife22/video/7059698374567611694"}'
"""
import asyncio
import os
import sys

if os.path.isdir('omni-agent/brain'):
    sys.path.insert(0, os.path.abspath('omni-agent/brain'))
else:
    sys.path.insert(0, '/app')

from llm import create_default_router
from skills import video_fetch as vf

TIKTOK = os.getenv('VF_TIKTOK', 'https://www.tiktok.com/@pokemonlife22/video/7059698374567611694')
INSTAGRAM = os.getenv('VF_INSTAGRAM', 'https://www.instagram.com/reel/Chunk8-jurw/')
YOUTUBE_SHORTS = 'https://www.youtube.com/shorts/jNQXAC9IVRw'
YOUTUBE_LONG = 'https://www.youtube.com/watch?v=aqz-KE-bpKQ'      # Big Buck Bunny 10:35 → 需確認
YOUTUBE_TOO_LONG = 'https://www.youtube.com/watch?v=iG9CE55wbtY'  # TED 20:03 → 超過硬上限
OPTIONAL = {  # 沒給網址就跳過；抖音沒 cookie 時預期回「需要 cookie」
    'douyin': os.getenv('VF_DOUYIN', 'https://www.douyin.com/video/6961737553342991651'),
    'twitter': os.getenv('VF_TWITTER'),
    'xiaohongshu': os.getenv('VF_XHS'),
    'bilibili': os.getenv('VF_BILIBILI'),
    'short': os.getenv('VF_SHORTLINK'),
}

# 內網／IP 不在平台白名單 → 先以「不支援」擋下（連 DNS 都不查）
INTERNAL = [
    'http://postgres:5432/v.mp4', 'http://127.0.0.1:8000/health', 'http://192.168.1.1/x.mp4',
    'http://100.88.136.117/x', 'http://169.254.169.254/latest', 'file:///etc/passwd',
]
# 白名單網域但 SSRF 層應拒絕
BLOCKED = [
    'https://www.tiktok.com/@a/video/1?k=sk-abcdefghijklmnop',
    'ftp://www.tiktok.com/@a/video/1',
]
UNSUPPORTED = ['https://vimeo.com/76979871', 'https://example.com/video.mp4', 'https://evil-tiktok.com/@a/video/1']


async def ok(url, router, instruction=None):
    r = await vf.analyze_video_url(url, instruction, router)
    assert r['success'], f'{url}: {r.get("error")}'
    assert r['data']['analysis'].strip(), f'{url}: empty analysis'
    return r['data']


async def fail(url, router, must_contain):
    r = await vf.analyze_video_url(url, None, router)
    assert not r['success'], f'{url}: should fail'
    assert must_contain in r['error'], f'{url}: {r["error"]}'
    return r['error']


def unit():
    # 網域判定：子網域可、仿冒網域不可、短網址另類
    assert vf.classify_url('https://www.tiktok.com/@a/video/1') == 'tiktok'
    assert vf.classify_url('https://m.youtube.com/watch?v=x') == 'youtube'
    assert vf.classify_url('https://youtu.be/x') == 'youtube'
    assert vf.classify_url('https://x.com/a/status/1') == 'twitter'
    assert vf.classify_url('https://vt.tiktok.com/ZSabc/') == 'short'
    assert vf.classify_url('https://v.douyin.com/abc/') == 'short'
    assert vf.classify_url('https://evil-tiktok.com/x') is None
    assert vf.classify_url('https://tiktok.com.evil.io/x') is None
    # yt-dlp 錯誤分類
    c = vf.classify_ytdlp_error
    assert 'IP' in c('ERROR: [TikTok] 1: Your IP address is blocked from accessing this post', 'tiktok', False)
    assert '設定' in c('ERROR: [Douyin] 1: Fresh cookies (not necessarily logged in) are needed', 'douyin', False)
    assert '過期' in c('ERROR: [Instagram] x: Requested content is not available, rate-limit reached or login required', 'instagram', True)
    assert '沒有影片' in c("ERROR: [twitter] 1: No video could be found in this tweet", 'twitter', False)
    assert 'cookie' in c('ERROR: [XiaoHongShu] 1: No video formats found!', 'xiaohongshu', False)
    assert '更新 yt-dlp' in c('ERROR: [TikTok] 1: Unable to extract universal data for rehydration', 'tiktok', False)
    print('unit: classify_url / classify_ytdlp_error ok')


async def main():
    unit()
    router = create_default_router()
    assert 'gemini' in router._clients, 'gemini provider 未註冊'

    # 1. SSRF 與白名單：不呼叫 yt-dlp 就拒絕
    for u in INTERNAL + UNSUPPORTED:
        await fail(u, router, '不支援')
    for u in BLOCKED:
        await fail(u, router, '拒絕')
    print(f'reject: {len(INTERNAL)} internal, {len(UNSUPPORTED)} unsupported, {len(BLOCKED)} unsafe')

    # 2. YouTube：file_uri 直讀，不下載
    d = await ok(YOUTUBE_SHORTS, router)
    assert d['platform'] == 'YouTube'
    print(f"youtube: {d['analysis'][:60]!r}")

    # 3. TikTok：下載 → inline
    d = await ok(TIKTOK, router)
    assert d['platform'] == 'TikTok' and not d['transcoded'] and d['duration']
    print(f"tiktok: {d['duration']}s {d['analysis'][:60]!r}")

    # 4. Instagram Reels
    d = await ok(INSTAGRAM, router)
    assert d['platform'] == 'Instagram'
    print(f"instagram: {d['analysis'][:60]!r}")

    # 5. 超過 inline 上限 → ffmpeg 轉檔後仍可分析（調低門檻強制觸發）
    saved = vf.MAX_INLINE_BYTES, vf.TRANSCODE_TARGET_BYTES
    vf.MAX_INLINE_BYTES, vf.TRANSCODE_TARGET_BYTES = 400_000, 300_000
    try:
        d = await ok(TIKTOK, router, '畫面中出現什麼角色？')
        assert d['transcoded']
    finally:
        vf.MAX_INLINE_BYTES, vf.TRANSCODE_TARGET_BYTES = saved
    print(f"transcode: {d['analysis'][:60]!r}")

    # 6. 長度分級：> 6 分鐘先問、同意後才跑；> 15 分鐘直接拒絕（YouTube 也先 probe 長度）
    r = await vf.analyze_video_url(YOUTUBE_LONG, None, router)
    assert not r['success'] and r.get('needs_confirmation') and '要繼續' in r['question'], r
    d = await vf.analyze_video_url(YOUTUBE_LONG, '用兩句話講劇情', router, confirmed=True)
    assert d['success'] and d['data']['duration'] > vf.CONFIRM_DURATION_SEC, d
    await fail(YOUTUBE_TOO_LONG, router, '上限')
    # 下載路徑的長影片級（調低門檻讓 6 秒 TikTok 觸發；同時強制轉檔）
    saved = vf.CONFIRM_DURATION_SEC, vf.MAX_DURATION_SEC
    vf.CONFIRM_DURATION_SEC = 3
    try:
        r = await vf.analyze_video_url(TIKTOK, None, router)
        assert r.get('needs_confirmation'), r
        vf.MAX_DURATION_SEC = 4
        await fail(TIKTOK, router, '上限')
    finally:
        vf.CONFIRM_DURATION_SEC, vf.MAX_DURATION_SEC = saved
    for dur in (60, 270, 400, 600, vf.MAX_DURATION_SEC):  # 轉檔參數估算不超出 inline 預算
        _res, vb, _fps, ab = vf.transcode_params(dur)
        assert (vb + ab) * dur / 8 <= vf.MAX_INLINE_BYTES, dur
    print('duration tiers: >6min asks, confirmed runs, >15min rejected; transcode budget ok')

    # 7. 其他平台（可選）
    for key, url in OPTIONAL.items():
        if not url:
            print(f'{key}: skipped（未提供 VF_ 網址）')
            continue
        r = await vf.analyze_video_url(url, None, router)
        if r['success']:
            print(f"{key}: ok {r['data']['platform']} {r['data']['analysis'][:50]!r}")
        elif key == 'douyin' and not vf._cookie_file('douyin'):
            assert 'cookie' in r['error'], r['error']
            print(f'{key}: 無 cookie，回應如預期：{r["error"]}')
        else:
            print(f'{key}: FAILED {r["error"]}')

    # 8. Gemini 不可用 → 明確錯誤，不讓其他 provider 假裝看過
    gemini = router._clients.pop('gemini')
    try:
        await fail(YOUTUBE_SHORTS, router, 'Gemini')
    finally:
        router._clients['gemini'] = gemini
    print('gemini unavailable: honest error')

    # 9. 暫存清乾淨
    left = os.listdir(vf.WORK_ROOT) if os.path.isdir(vf.WORK_ROOT) else []
    assert not left, f'leftover workdirs: {left}'
    print('cleanup: no leftover')

    print('ALL PASSED')


if __name__ == '__main__':
    asyncio.run(main())
