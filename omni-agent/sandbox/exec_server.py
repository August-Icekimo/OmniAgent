"""沙箱 exec 服務 — 在受限容器內執行 shell 命令。

刻意保持極小：只負責「收命令、跑、回結果」，不做身分/權限判斷
（那是 brain 端 terminal 技能與 graph confirmer 的責任）。本服務的防線是
容器層級隔離（read_only 檔案系統、無 secret、資源限制、僅內網可達）加上
此處的超時、process group 清理與輸出截斷。

回傳格式對齊 brain/skills/web_search.py 的契約：
    成功: {"success": True, "data": {"output", "exit_code", "truncated"}}
    失敗: {"success": False, "error": "<可讀訊息>"}
"""

import asyncio
import logging
import os
import signal
import uuid
from typing import Dict, Optional

from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sandbox.exec")

# 工作目錄：唯一可寫路徑（compose 掛 volume），所有命令預設在此執行
WORK_ROOT = "/sandbox/work"

# 輸出截斷上限：命令輸出會整包回給 brain 並注入 reporter prompt，
# 必須限制總量以免撐爆 local 模型 context（對齊 web_search 的截斷防護）。
MAX_OUTPUT_CHARS = 4000

# 前景命令的超時硬上限（秒），避免單一命令卡住服務
MAX_TIMEOUT = 120

app = FastAPI(title="omni-agent sandbox exec")

# 背景任務狀態：存記憶體即可，容器重啟即清空（中階版可接受）
_tasks: Dict[str, Dict] = {}


class ExecRequest(BaseModel):
    command: str
    timeout: int = 30
    workdir: Optional[str] = None


class BackgroundRequest(BaseModel):
    command: str


def _safe_workdir(workdir: Optional[str]) -> str:
    """限制工作目錄落在 WORK_ROOT 內，擋路徑穿越。"""
    if not workdir:
        return WORK_ROOT
    resolved = os.path.realpath(os.path.join(WORK_ROOT, workdir))
    if resolved != WORK_ROOT and not resolved.startswith(WORK_ROOT + os.sep):
        return WORK_ROOT
    return resolved


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    return text[:MAX_OUTPUT_CHARS] + "\n…（輸出過長已截斷）", True


async def _run(command: str, timeout: int, workdir: str) -> Dict:
    """執行單一命令，超時則殺整個 process group。"""
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=workdir,
        start_new_session=True,  # 自成 process group，方便整組清理
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        return {"success": False, "error": f"命令逾時（{timeout}s）已強制終止"}

    output, truncated = _truncate(stdout.decode("utf-8", errors="replace"))
    return {
        "success": True,
        "data": {
            "output": output,
            "exit_code": proc.returncode,
            "truncated": truncated,
        },
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/exec")
async def exec_command(req: ExecRequest):
    if not req.command.strip():
        return {"success": False, "error": "命令為空"}
    timeout = max(1, min(int(req.timeout), MAX_TIMEOUT))
    workdir = _safe_workdir(req.workdir)
    try:
        return await _run(req.command, timeout, workdir)
    except Exception as exc:  # noqa: BLE001 — 一律包成 dict 回傳，不讓 brain 端收到 500
        logger.warning(f"exec failed: {exc}")
        return {"success": False, "error": f"執行失敗：{exc}"}


async def _run_background(task_id: str, command: str):
    _tasks[task_id]["status"] = "running"
    try:
        result = await _run(command, MAX_TIMEOUT, WORK_ROOT)
        if result.get("success"):
            data = result["data"]
            _tasks[task_id].update(
                status="done", output=data["output"], exit_code=data["exit_code"]
            )
        else:
            _tasks[task_id].update(status="error", error=result.get("error", "未知錯誤"))
    except Exception as exc:  # noqa: BLE001
        _tasks[task_id].update(status="error", error=str(exc))


@app.post("/exec/background")
async def exec_background(req: BackgroundRequest):
    if not req.command.strip():
        return {"success": False, "error": "命令為空"}
    task_id = uuid.uuid4().hex[:12]
    _tasks[task_id] = {"status": "pending", "output": "", "exit_code": None}
    asyncio.create_task(_run_background(task_id, req.command))
    return {"success": True, "data": {"task_id": task_id}}


@app.get("/exec/status/{task_id}")
async def exec_status(task_id: str):
    task = _tasks.get(task_id)
    if not task:
        return {"success": False, "error": f"找不到任務 {task_id}"}
    return {"success": True, "data": {"task_id": task_id, **task}}
