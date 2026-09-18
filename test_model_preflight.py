"""手動跑 model preflight（與 brain 啟動時同一函式）。

用法（repo 根目錄，需 omni-agent/.env 內的 API key）：
    set -a; . omni-agent/.env; set +a; python test_model_preflight.py
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.abspath("omni-agent/brain"))

logging.basicConfig(level=logging.WARNING)

from config.config_loader import load_routing_config  # noqa: E402
from llm.router import create_default_router  # noqa: E402
from llm.preflight import run_model_preflight  # noqa: E402


async def main() -> int:
    router = create_default_router()
    if not router._clients:
        print("no provider registered — check ANTHROPIC_API_KEY / GEMINI_API_KEY / MLX_BASE_URL")
        return 2
    results = await run_model_preflight(router, load_routing_config())
    width = max(len(r.model_id) for r in results)
    for r in results:
        status = "OK  " if r.ok else "FAIL"
        unused = " (unused)" if r.unused else ""
        print(f"{status} {r.provider:7s} {r.model_id:{width}s}{unused}")
        for src in r.sources:
            print(f"       source: {src}")
        if not r.ok:
            print(f"       {r.error_class}: {r.detail}")
    failed = sum(1 for r in results if not r.ok)
    print(f"\n{len(results) - failed} ok, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
