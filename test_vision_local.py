"""Local Gemma 4 視覺鏈路測試（change_local-gemma-multimodal-perception）。

驗證：LocalClient block 轉換與輸出清理、router 能力閘門與貼圖試點路由、
LocalClient → chrysoberyl 圖片 E2E。
比照 test_router.py：手動執行 `python test_vision_local.py`。
"""
import asyncio
import binascii
import os
import sys

sys.path.insert(0, os.path.abspath('omni-agent/brain'))

from llm import Message, Role  # noqa: E402
from llm.router import create_default_router  # noqa: E402
from llm.local_client import LocalClient, _clean_output, _to_openai_content  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    status = "OK  " if cond else "FAIL"
    print(f"{status} {name} {detail}")
    if not cond:
        FAILURES.append(name)


# 64x64 純紅 PNG（pure-python 生成，無 PIL 依賴）
def red_png() -> bytes:
    import struct
    import zlib

    def chunk(t, d):
        c = struct.pack('>I', len(d)) + t + d
        return c + struct.pack('>I', binascii.crc32(t + d) & 0xffffffff)

    w = h = 64
    raw = b''.join(b'\x00' + b'\xff\x00\x00' * w for _ in range(h))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw))
            + chunk(b'IEND', b''))


print("=== 1. LocalClient 單元：輸出清理 ===")
check("thought 截斷", _clean_output("Red//thought\nRedRed") == "Red//")
check("外文殘token修剪", _clean_output("答案。\nต์") == "答案。")
check("emoji 結尾保留", _clean_output("好喔！🎉") == "好喔！🎉")
check("正常內容不動", _clean_output("這是貼圖描述。") == "這是貼圖描述。")
check("清空觸發空回應", _clean_output("ต์") == "")

print("=== 2. LocalClient 單元：content block 轉換 ===")
check("純文字原樣", _to_openai_content("hi") == "hi")
parts = _to_openai_content([
    {"type": "text", "text": "describe"},
    {"type": "image", "mime_type": "image/png", "data": b"abc"},
])
check("image 轉 data URI", parts[1]["image_url"]["url"].startswith("data:image/png;base64,"))
try:
    _to_openai_content([{"type": "audio", "mime_type": "audio/wav", "data": "x"}])
    check("audio block 拒收", False)
except ValueError:
    check("audio block 拒收", True)

print("=== 3. Router 規則路由 ===")
router = create_default_router()
has_local = "local" in router._clients
print(f"(registered: {list(router._clients.keys())})")
expectations = {
    "sticker": "local" if has_local else "gemini",
    "animation": "local" if has_local else "gemini",
    "image": "gemini",
    "voice": "gemini",
    "video": "gemini",
    "text": None,  # 走一般規則，不檢查
}
for mt, expected in expectations.items():
    d = router.select_provider({"message_type": mt, "text": "x"})
    if expected:
        check(f"message_type={mt} -> {expected}", d["provider"] == expected, f"(got {d})")


async def main():
    if not has_local:
        print("SKIP E2E: local provider 未註冊（MLX_BASE_URL 未設或 test mode）")
        return

    print("=== 4. E2E: LocalClient 圖片 ===")
    client = LocalClient()
    content = [
        {"type": "image", "mime_type": "image/png", "data": red_png()},
        {"type": "text", "text": "這張圖是什麼顏色？請用一個詞回答。"},
    ]
    resp = await client.chat([Message(role=Role.USER, content=content)], max_tokens=100)
    print(f"(content={resp.content!r} finish={resp.finish_reason})")
    check("local 圖片回應非空", bool(resp.content.strip()))
    check("無 thought 殘留", "thought" not in resp.content)

    print("=== 5. E2E: router.chat 多模態候選鏈（primary=local）===")
    resp = await router.chat(
        [Message(role=Role.USER, content=content)],
        provider="local",
        max_tokens=100,
        caller="test_vision_local",
    )
    print(f"(provider={resp.provider} content={resp.content!r} finish={resp.finish_reason})")
    check("router 多模態經 local 成功", resp.provider == "local" and bool(resp.content.strip()))

    print("=== 6. E2E: local 失敗 fallback gemini（模擬 chrysoberyl 離線）===")
    router._clients["local"] = LocalClient(base_url="http://127.0.0.1:9/v1")
    resp = await router.chat(
        [Message(role=Role.USER, content=content)],
        provider="local",
        max_tokens=100,
        caller="test_vision_fallback",
    )
    print(f"(provider={resp.provider} content={resp.content[:60]!r})")
    check("local 離線時自動 fallback gemini", resp.provider == "gemini" and bool(resp.content.strip()))
    router._clients["local"] = LocalClient()  # 還原

    print("=== 7. E2E: FileAnalyzer 貼圖感知（含首行救援/升級保底）===")
    from skills.file_analyzer import FileAnalyzer
    analyzer = FileAnalyzer(router)
    result = await analyzer._perceive_image(
        [
            {"type": "image", "mime_type": "image/png", "data": red_png()},
            {"type": "text", "text": "這是貼圖，請描述其情緒、物體或意圖。請以簡短的一句話回傳，格式如：[sticker: 某某動作，表達某某心情]。"},
        ],
        message_type="sticker",
        caller="test_sticker_perception",
    )
    print(f"(result={result!r})")
    check("貼圖感知結果非空", bool(result.strip()))
    check("貼圖感知結果為單行", "\n" not in result.strip())


asyncio.run(main())

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} checks: {FAILURES}")
    sys.exit(1)
print("ALL CHECKS PASSED")
