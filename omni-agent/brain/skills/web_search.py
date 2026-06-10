"""網路搜尋 provider — 介面契約移植自 hermes-agent plugins/web。

統一回傳格式（所有 provider 共用，未來新增後端時沿用）：
    成功: {"success": True, "data": {"web": [{"title", "url", "description", "position"}]}}
    失敗: {"success": False, "error": "<可讀錯誤訊息>"}

錯誤一律包成 dict 回傳而非 raise，上層（executor_node）永遠拿到可序列化結果。
"""

import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict

import httpx

logger = logging.getLogger("brain.skills.web_search")

# 截斷防護：搜尋結果是外部不可信文本，會整包注入 reporter prompt，
# 必須限制總量以免撐爆 local 模型 context 或觸發 max_tokens 截斷鏈。
MAX_RESULTS = 5
MAX_DESCRIPTION_CHARS = 300


class WebSearchProvider(ABC):
    """搜尋後端抽象。is_available() 只查設定、不打網路。"""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    async def search(self, query: str, limit: int = MAX_RESULTS) -> Dict[str, Any]:
        ...


class SearXNGWebSearchProvider(WebSearchProvider):
    """自架 SearXNG（compose 內網服務），經 /search?format=json 查詢。"""

    @property
    def name(self) -> str:
        return "searxng"

    def _base_url(self) -> str:
        return (os.getenv("SEARXNG_URL") or "").strip().rstrip("/")

    def is_available(self) -> bool:
        return bool(self._base_url())

    async def search(self, query: str, limit: int = MAX_RESULTS) -> Dict[str, Any]:
        base_url = self._base_url()
        if not base_url:
            return {"success": False, "error": "SEARXNG_URL 未設定，搜尋功能未啟用"}

        safe_limit = max(1, min(int(limit), MAX_RESULTS))

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{base_url}/search",
                    params={"q": query, "format": "json", "pageno": 1},
                    timeout=15.0,
                    headers={"Accept": "application/json"},
                )
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(f"SearXNG HTTP error: {exc}")
            return {"success": False, "error": f"SearXNG 回應 HTTP {exc.response.status_code}"}
        except httpx.RequestError as exc:
            logger.warning(f"SearXNG request error: {exc}")
            return {"success": False, "error": f"無法連線 SearXNG（{base_url}）：{exc}"}

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning(f"SearXNG response parse error: {exc}")
            return {"success": False, "error": "SearXNG 回應不是合法 JSON"}

        raw_results = data.get("results", [])

        # SearXNG 帶 score 欄位：降冪排序後截到 limit
        sorted_results = sorted(
            raw_results,
            key=lambda r: float(r.get("score", 0)),
            reverse=True,
        )[:safe_limit]

        web_results = [
            {
                "title": str(r.get("title", "")),
                "url": str(r.get("url", "")),
                "description": str(r.get("content", ""))[:MAX_DESCRIPTION_CHARS],
                "position": i + 1,
            }
            for i, r in enumerate(sorted_results)
        ]

        logger.info(
            f"SearXNG search '{query}': {len(web_results)} results "
            f"(from {len(raw_results)} raw, limit {safe_limit})"
        )
        return {"success": True, "data": {"web": web_results}}


def get_web_search_provider() -> WebSearchProvider:
    """回傳目前唯一的搜尋後端。未來多 provider 時在此依設定挑選。"""
    return SearXNGWebSearchProvider()
