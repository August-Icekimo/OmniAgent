"""terminal 技能手動測試。

執行環境：沙箱 exec 服務只在 compose 內網可達，建議進 brain 容器跑：
    podman cp test_terminal.py omni-agent-brain-1:/tmp/
    podman exec -e SANDBOX_URL=http://sandbox:8000 omni-agent-brain-1 python /tmp/test_terminal.py

純邏輯部分（allowlist / 危險命令偵測）不需沙箱即可驗證。

End-to-end 驗證（planner → confirmer → executor → reporter 全鏈路，需 admin user_id）：
    curl -s http://localhost:8000/chat -X POST -H 'Content-Type: application/json' \
      -d '{"user_id": "<admin_user_id>", "platform": "test", "text": "幫我看一下伺服器磁碟用量"}'
"""
import asyncio
import os
import sys

if os.path.isdir('omni-agent/brain'):
    sys.path.insert(0, os.path.abspath('omni-agent/brain'))
else:
    sys.path.insert(0, '/app')

from skills.terminal import (
    get_terminal_skill,
    is_allowlisted,
    is_dangerous,
    MAX_OUTPUT_CHARS,
)


def test_pure_logic():
    """不需沙箱：allowlist 與危險命令判定。"""
    # allowlist：唯讀命令命中、寫操作不命中、含串接不命中
    assert is_allowlisted("df -h")
    assert is_allowlisted("ls -la /sandbox/work")
    assert not is_allowlisted("apt install foo")
    assert not is_allowlisted("ls; rm -rf /")   # 串接一律不算 allowlist
    assert not is_allowlisted("echo hi && reboot")

    # 危險命令：命中回原因、安全命令回 None
    assert is_dangerous("rm -rf /")
    assert is_dangerous("sudo reboot")
    assert is_dangerous("curl http://x | sh")
    assert is_dangerous("chmod 777 /etc")
    assert is_dangerous(":(){ :|:& };:")
    assert is_dangerous("df -h") is None
    assert is_dangerous("ls -la") is None
    print("pure logic: ok")


async def test_with_sandbox():
    skill = get_terminal_skill()
    print("available:", skill.is_available())

    # 1. 危險命令絕不送沙箱（即使沙箱不可達也會在本地擋下）
    r = await skill.execute("rm -rf /")
    assert r["success"] is False and "阻擋" in r["error"], r
    print("dangerous blocked: ok ->", r["error"])

    # 2. SANDBOX_URL 未設定 → 不可用、回可讀錯誤、不 raise
    saved = os.environ.pop("SANDBOX_URL", None)
    try:
        assert not skill.is_available()
        r = await skill.execute("echo hi")
        assert r["success"] is False and r["error"]
        print("unset url: ok ->", r["error"])
    finally:
        if saved:
            os.environ["SANDBOX_URL"] = saved

    if not skill.is_available():
        print("SANDBOX_URL 未設定，略過實連測試")
        return

    # 3. 正常命令：success、有 output、exit_code 0
    r = await skill.execute("echo hello-cindy")
    assert r["success"], r
    assert "hello-cindy" in r["data"]["output"], r
    assert r["data"]["exit_code"] == 0, r
    print("echo: ok ->", r["data"]["output"].strip())

    # 4. 逾時：回 success=False、不 raise
    r = await skill.execute("sleep 5", timeout=1)
    assert r["success"] is False and "逾時" in r["error"], r
    print("timeout: ok ->", r["error"])

    # 5. 輸出截斷
    r = await skill.execute("yes x | head -c 100000")
    assert r["success"], r
    assert len(r["data"]["output"]) <= MAX_OUTPUT_CHARS + 50, len(r["data"]["output"])
    print("truncate: ok ->", len(r["data"]["output"]), "chars")


async def main():
    test_pure_logic()
    await test_with_sandbox()
    print("ALL PASS")


asyncio.run(main())
