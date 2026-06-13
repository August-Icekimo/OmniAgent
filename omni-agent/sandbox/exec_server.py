"""沙箱 exec 服務 — 在受限容器內執行 shell 命令。

刻意保持極小：只負責「收命令、跑、回結果」，不做身分/權限判斷
（那是 brain 端 terminal 技能與 graph confirmer 的責任）。本服務的防線是
容器層級隔離（read_only 檔案系統、無 secret、資源限制、僅內網可達）加上
此處的超時、process group 清理與輸出截斷。

回傳格式對齊 brain/skills/web_search.py 的契約：
    成功: {"success": True, "data": {"output", "exit_code", "truncated", "task_id"}}
    失敗: {"success": False, "error": "<可讀訊息>"}

**Log 持久化（terminal viewer 用）**：每次執行（前景與背景）都產生 task_id，
把原始 bytes（保留 ANSI 色碼、不截斷）逐步寫入共享 volume 的 `<task_id>.log`，
並維護 `<task_id>.meta.json`（status/exit_code/command/created_at）。brain 端
viewer 與 WebSocket 即時串流直接讀這個共享 volume；背景任務狀態也以 meta 檔
為準（不再僅依賴記憶體），容器重啟後仍可查。
"""

import asyncio
import json
import logging
import os
import signal
import tempfile
import time
import uuid
from typing import Dict, Optional

from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sandbox.exec")

# 工作目錄：唯一可寫路徑（compose 掛 volume），所有命令預設在此執行
WORK_ROOT = "/sandbox/work"

# Log 持久化根目錄：共享可寫 volume，brain 端掛載同一 volume 讀取。
LOG_ROOT = os.getenv("LOG_ROOT", "/sandbox/logs")

# 聊天預覽用的輸出截斷上限：截斷只套用在「回給 brain 注入 reporter prompt」的
# 預覽字串，**不**套用在落地的 log 檔（log 檔保留完整原始輸出供 viewer 呈現）。
MAX_OUTPUT_CHARS = 4000

# 前景命令的超時硬上限（秒），避免單一命令卡住服務
MAX_TIMEOUT = 120

app = FastAPI(title="omni-agent sandbox exec")


class ExecRequest(BaseModel):
    command: str
    timeout: int = 30
    workdir: Optional[str] = None


class BackgroundRequest(BaseModel):
    command: str


def _ensure_log_root() -> None:
    try:
        os.makedirs(LOG_ROOT, exist_ok=True)
    except OSError as exc:
        logger.warning(f"無法建立 LOG_ROOT {LOG_ROOT}: {exc}")


def _log_path(task_id: str) -> str:
    return os.path.join(LOG_ROOT, f"{task_id}.log")


def _meta_path(task_id: str) -> str:
    return os.path.join(LOG_ROOT, f"{task_id}.meta.json")


def _write_meta(task_id: str, **fields) -> None:
    """合併更新 meta.json：先寫暫存檔再 rename，避免 brain 讀到半截 JSON。"""
    path = _meta_path(task_id)
    existing: Dict = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except (OSError, ValueError):
        existing = {}
    existing.update(fields)
    existing.setdefault("task_id", task_id)
    try:
        fd, tmp = tempfile.mkstemp(dir=LOG_ROOT, prefix=f".{task_id}.meta.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning(f"無法寫入 meta {path}: {exc}")


def _read_meta(task_id: str) -> Optional[Dict]:
    try:
        with open(_meta_path(task_id), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    return text[:MAX_OUTPUT_CHARS] + "\n…（輸出過長已截斷，完整內容見終端機檢視頁）", True


def _safe_workdir(workdir: Optional[str]) -> str:
    """限制工作目錄落在 WORK_ROOT 內，擋路徑穿越。"""
    if not workdir:
        return WORK_ROOT
    resolved = os.path.realpath(os.path.join(WORK_ROOT, workdir))
    if resolved != WORK_ROOT and not resolved.startswith(WORK_ROOT + os.sep):
        return WORK_ROOT
    return resolved


async def _pump_to_log(proc, log_file) -> bytearray:
    """逐塊讀取 stdout（已併入 stderr）的原始 bytes，即時寫入 log 檔並回傳全文。

    保留 ANSI 原始 bytes（不解碼、不截斷），讓 brain viewer 能渲染色彩；
    無緩衝即時 flush，背景長命令的 viewer 才能逐步看到輸出。
    """
    collected = bytearray()
    while True:
        chunk = await proc.stdout.read(4096)
        if not chunk:
            break
        collected.extend(chunk)
        try:
            log_file.write(chunk)
            log_file.flush()
        except OSError as exc:
            logger.warning(f"寫入 log 失敗：{exc}")
    return collected


async def _execute(task_id: str, command: str, timeout: int, workdir: str) -> Dict:
    """執行單一命令：串流落地 log、維護 meta，超時則殺整個 process group。"""
    _write_meta(
        task_id,
        command=command,
        status="running",
        exit_code=None,
        created_at=time.time(),
    )

    log_path = _log_path(task_id)
    try:
        log_file = open(log_path, "ab", buffering=0)
    except OSError as exc:
        logger.warning(f"無法開啟 log 檔 {log_path}: {exc}")
        log_file = None

    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=workdir,
        start_new_session=True,  # 自成 process group，方便整組清理
    )

    async def _drain() -> bytearray:
        if log_file is not None:
            return await _pump_to_log(proc, log_file)
        # 無法落地時退化為單純收集（不影響回傳契約）
        data = await proc.stdout.read()
        return bytearray(data)

    try:
        collected = await asyncio.wait_for(_drain(), timeout=timeout)
        await proc.wait()
    except asyncio.TimeoutError:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        note = f"\n…（命令逾時（{timeout}s）已強制終止）".encode("utf-8")
        if log_file is not None:
            try:
                log_file.write(note)
                log_file.flush()
            except OSError:
                pass
        _write_meta(task_id, status="error", exit_code=None,
                    error=f"命令逾時（{timeout}s）已強制終止", updated_at=time.time())
        return {"success": False, "error": f"命令逾時（{timeout}s）已強制終止", "task_id": task_id}
    finally:
        if log_file is not None and not log_file.closed:
            try:
                log_file.close()
            except OSError:
                pass

    exit_code = proc.returncode
    _write_meta(task_id, status="done", exit_code=exit_code, updated_at=time.time())

    output, truncated = _truncate(bytes(collected).decode("utf-8", errors="replace"))
    return {
        "success": True,
        "data": {
            "output": output,
            "exit_code": exit_code,
            "truncated": truncated,
            "task_id": task_id,
        },
    }


@app.on_event("startup")
async def _startup():
    _ensure_log_root()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/exec")
async def exec_command(req: ExecRequest):
    if not req.command.strip():
        return {"success": False, "error": "命令為空"}
    timeout = max(1, min(int(req.timeout), MAX_TIMEOUT))
    workdir = _safe_workdir(req.workdir)
    task_id = uuid.uuid4().hex[:12]
    try:
        return await _execute(task_id, req.command, timeout, workdir)
    except Exception as exc:  # noqa: BLE001 — 一律包成 dict 回傳，不讓 brain 端收到 500
        logger.warning(f"exec failed: {exc}")
        _write_meta(task_id, status="error", error=str(exc), updated_at=time.time())
        return {"success": False, "error": f"執行失敗：{exc}", "task_id": task_id}


async def _run_background(task_id: str, command: str):
    await _execute(task_id, command, MAX_TIMEOUT, WORK_ROOT)


@app.post("/exec/background")
async def exec_background(req: BackgroundRequest):
    if not req.command.strip():
        return {"success": False, "error": "命令為空"}
    task_id = uuid.uuid4().hex[:12]
    # 先寫 pending meta，讓 brain 端即使在命令啟動前查詢也拿得到狀態
    _write_meta(task_id, command=req.command, status="pending",
                exit_code=None, created_at=time.time())
    asyncio.create_task(_run_background(task_id, req.command))
    return {"success": True, "data": {"task_id": task_id}}


@app.get("/exec/status/{task_id}")
async def exec_status(task_id: str):
    """背景任務狀態：以共享 volume 的 meta.json 為準（容器重啟後仍可查）。

    同時回讀 log 檔內容（截斷為預覽），供 brain reporter 組稿。
    """
    meta = _read_meta(task_id)
    if not meta:
        return {"success": False, "error": f"找不到任務 {task_id}"}

    output = ""
    try:
        with open(_log_path(task_id), "rb") as f:
            output, _ = _truncate(f.read().decode("utf-8", errors="replace"))
    except OSError:
        output = ""

    return {
        "success": True,
        "data": {
            "task_id": task_id,
            "status": meta.get("status"),
            "exit_code": meta.get("exit_code"),
            "output": output,
            "error": meta.get("error"),
        },
    }
