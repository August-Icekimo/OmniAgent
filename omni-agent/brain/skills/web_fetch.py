"""網頁正文擷取（fetch_url 工具）— 設計參考 hermes-agent tools/web_tools.py 的 web_extract。

流程（每個 URL）：
    is_safe_url → 靜態抓取（httpx，自管 redirect、每跳重檢）
      ├─ PDF → pypdf 取文字
      ├─ HTML → trafilatura 擷取正文；正文過少（JS 動態頁）→ headless Chromium 渲染後再擷取
      └─ 其他文字型 → 直接解碼
    → 頭尾截斷到預算

統一回傳格式（對齊 web_search.py 契約，never raise）：
    成功: {"success": True, "data": {"pages": [
              {"url", "final_url", "title", "content", "truncated", "rendered", "error"}]}}
    失敗: {"success": False, "error": "<可讀錯誤訊息>"}

安全：每個對外請求（含 redirect 每一跳、瀏覽器每個子請求與 WebSocket）都過 url_safety.is_safe_url。
Playwright 的 route 對 redirect 只攔第一跳，故瀏覽器請求一律以 route.fetch(max_redirects=0) 代抓，
在 route 內自行跟隨 redirect（每跳重檢）後才把最終回應交回瀏覽器。
"""

import asyncio
import io
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

import httpx

from skills.url_safety import is_safe_url

logger = logging.getLogger("brain.skills.web_fetch")

MAX_URLS = 3
MAX_CONTENT_CHARS = 8000
TAIL_CHARS = 2000
HEAD_CHARS = MAX_CONTENT_CHARS - TAIL_CHARS - 60  # 預留省略標記，總長不超過預算
MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
STATIC_TIMEOUT = 15.0
RENDER_TIMEOUT = 25.0
MIN_CONTENT_CHARS = 200  # 靜態擷取少於此字數 → 視為 JS 動態頁，改渲染
# 正文含「請開啟 JavaScript」類提示且不長 → 也是 JS 殼頁（例：CWA 鄉鎮預報靜態 683 字全是空表頭）
JS_HINT_MAX_CHARS = 3000
_JS_HINT_RE = re.compile(
    r"(不支援|啟用|開啟|启用|开启).{0,6}JavaScript|JavaScript.{0,12}(功能|狀態|状态)|"
    r"(enable|turn on|requires?|need) (javascript|js)\b|javascript (is )?(required|disabled)",
    re.IGNORECASE,
)
PDF_MAX_PAGES = 30
# 靜態抓取被擋（常見於反爬蟲）時改用瀏覽器再試
RENDER_ON_STATUS = {403, 429, 503}

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

# 瀏覽器同時只開一個（brain 無 mem_limit，Chromium 每次約數百 MB）
_render_lock = asyncio.Semaphore(1)


class FetchError(Exception):
    """可直接給模型看的單頁失敗原因。"""


def truncate_content(text: str) -> Tuple[str, bool]:
    """超出預算取頭尾，中間標示省略字數。"""
    if len(text) <= MAX_CONTENT_CHARS:
        return text, False
    omitted = len(text) - HEAD_CHARS - TAIL_CHARS
    return (
        text[:HEAD_CHARS].rstrip()
        + f"\n\n…（中段已省略 {omitted} 字）…\n\n"
        + text[-TAIL_CHARS:].lstrip()
    ), True


# --- 靜態抓取 ---------------------------------------------------------------

async def _static_get(url: str) -> Tuple[str, int, str, bytes]:
    """回傳 (final_url, status, content_type, body)。redirect 每一跳都重新檢查。"""
    current = url
    async with httpx.AsyncClient(
        headers=_HEADERS, follow_redirects=False, timeout=STATIC_TIMEOUT
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            async with client.stream("GET", current) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise FetchError(f"HTTP {resp.status_code} redirect 但沒有目標網址")
                    nxt = urljoin(current, location)
                    ok, reason = await is_safe_url(nxt)
                    if not ok:
                        logger.warning("fetch_url BLOCKED redirect %s -> %s (%s)", current, nxt, reason)
                        raise FetchError(f"已拒絕：轉址目標不安全（{reason}）")
                    current = nxt
                    continue
                ctype = resp.headers.get("content-type", "").lower()
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > MAX_BYTES:
                        if "pdf" in ctype:
                            raise FetchError("檔案超過 5MB 上限")
                        del buf[MAX_BYTES:]
                        break
                return str(resp.url), resp.status_code, ctype, bytes(buf)
    raise FetchError(f"轉址超過 {MAX_REDIRECTS} 次")


# --- 擷取 -------------------------------------------------------------------

def _extract_html(html: Any, url: str) -> Tuple[str, str]:
    """回傳 (title, 正文)。"""
    import trafilatura

    text = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_tables=True,
        include_links=False,
        include_images=False,
        favor_recall=True,
    ) or ""
    title = ""
    try:
        meta = trafilatura.extract_metadata(html)
        title = (meta.title if meta else "") or ""
    except Exception:  # noqa: BLE001 — metadata 失敗不影響正文
        pass
    return title, text.strip()


def _extract_pdf(body: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(body))
        texts = []
        for page in reader.pages[:PDF_MAX_PAGES]:
            texts.append(page.extract_text() or "")
            if sum(len(t) for t in texts) > MAX_CONTENT_CHARS * 3:
                break
        return "\n\n".join(t.strip() for t in texts if t.strip())
    except Exception as e:  # noqa: BLE001
        raise FetchError(f"PDF 無法解析（{type(e).__name__}）")


def _decode_text(body: bytes, ctype: str) -> str:
    charset = None
    if "charset=" in ctype:
        charset = ctype.split("charset=", 1)[1].split(";", 1)[0].strip()
    for enc in filter(None, (charset, "utf-8", "big5", "latin-1")):
        try:
            return body.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


# --- 渲染 -------------------------------------------------------------------

async def _guard_route(route) -> None:
    """瀏覽器每個請求：擋多媒體、SSRF 檢查、代抓並檢查 redirect。"""
    req = route.request
    if req.resource_type in ("image", "media", "font"):
        await route.abort()
        return
    scheme = urlsplit(req.url).scheme
    if scheme in ("data", "blob"):
        await route.continue_()
        return
    ok, reason = await is_safe_url(req.url)
    if not ok:
        logger.warning("fetch_url BLOCKED browser request %s (%s)", req.url, reason)
        await route.abort("blockedbyclient")
        return
    # route 代抓並自行跟隨 redirect（每跳重檢）。以 3xx fulfill 時 Chromium 不會跟隨（實測導向 chrome-error），
    # 故在此跟到最終回應再交回瀏覽器。
    current = req.url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            resp = await route.fetch(url=current, max_redirects=0, timeout=RENDER_TIMEOUT * 1000)
            location = resp.headers.get("location") if 300 <= resp.status < 400 else None
            if not location:
                break
            nxt = urljoin(current, location)
            ok, reason = await is_safe_url(nxt)
            if not ok:
                logger.warning("fetch_url BLOCKED browser redirect %s -> %s (%s)", current, nxt, reason)
                await route.abort("blockedbyclient")
                return
            current = nxt
        else:
            await route.abort("failed")
            return
    except Exception:  # noqa: BLE001 — 連線失敗交給瀏覽器當一般網路錯誤
        await route.abort("failed")
        return
    await route.fulfill(response=resp)


async def _guard_websocket(ws) -> None:
    http_url = "http" + ws.url[2:] if ws.url.startswith("ws") else ws.url
    ok, reason = await is_safe_url(http_url)
    if not ok:
        logger.warning("fetch_url BLOCKED browser websocket %s (%s)", ws.url, reason)
        await ws.close()
        return
    ws.connect_to_server()


_STRIP_HIDDEN_JS = """() => {
  const els = Array.from(document.body ? document.body.querySelectorAll('*') : []);
  const hidden = els.filter(el => {
    const cs = getComputedStyle(el);
    return cs.display === 'none' || cs.visibility === 'hidden';
  });
  hidden.forEach(el => el.remove());
  return hidden.length;
}"""


async def _render(url: str) -> Tuple[str, str, str, str]:
    """headless Chromium 渲染。回傳 (final_url, title, html, innerText)。"""
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout

    async with _render_lock:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            try:
                context = await browser.new_context(
                    user_agent=USER_AGENT, locale="zh-TW", timezone_id="Asia/Taipei",
                    service_workers="block",
                )
                await context.route("**/*", _guard_route)
                await context.route_web_socket("**/*", _guard_websocket)
                page = await context.new_page()
                deadline = time.monotonic() + RENDER_TIMEOUT
                await page.goto(url, wait_until="domcontentloaded", timeout=RENDER_TIMEOUT * 1000)
                remaining = max(1.0, deadline - time.monotonic())
                try:
                    await page.wait_for_load_state("networkidle", timeout=remaining * 1000)
                except PWTimeout:
                    pass  # 長輪詢頁面等不到 idle，用當下 DOM
                # 移除 CSS 隱藏元素：trafilatura 不懂 CSS，隱藏內容會與可見內容黏在一起
                # （例：CWA 溫度 <span class=tem-C>24</span><span class=tem-F style=display:none>75</span> → "2475"）
                await page.evaluate(_STRIP_HIDDEN_JS)
                html = await page.content()
                inner = await page.evaluate("document.body ? document.body.innerText : ''")
                return page.url, await page.title(), html, inner or ""
            finally:
                await browser.close()


# --- 單頁流程 ---------------------------------------------------------------

async def _fetch_one(url: str) -> Dict[str, Any]:
    page: Dict[str, Any] = {
        "url": url, "final_url": url, "title": "", "content": "",
        "truncated": False, "rendered": False, "error": None,
    }
    t0 = time.monotonic()
    try:
        ok, reason = await is_safe_url(url)
        if not ok:
            logger.warning("fetch_url BLOCKED %s (%s)", url, reason)
            raise FetchError(f"已拒絕：{reason}")

        need_render = False
        status = 0
        try:
            final_url, status, ctype, body = await asyncio.wait_for(
                _static_get(url), timeout=STATIC_TIMEOUT
            )
        except FetchError:
            raise
        except (httpx.HTTPError, asyncio.TimeoutError) as e:
            raise FetchError(f"頁面打不開（{type(e).__name__}）")
        page["final_url"] = final_url

        if status in RENDER_ON_STATUS:
            need_render = True
        elif status >= 400:
            raise FetchError(f"頁面打不開（HTTP {status}）")
        elif "pdf" in ctype or body[:5] == b"%PDF-":
            page["content"] = await asyncio.to_thread(_extract_pdf, body)
        elif "html" in ctype or "xml" in ctype or body.lstrip()[:1] == b"<":
            title, text = await asyncio.to_thread(_extract_html, body, final_url)
            page["title"], page["content"] = title, text
            need_render = len(text) < MIN_CONTENT_CHARS or (
                len(text) < JS_HINT_MAX_CHARS and bool(_JS_HINT_RE.search(text))
            )
        else:
            page["content"] = _decode_text(body, ctype).strip()

        if need_render:
            try:
                r_url, r_title, html, inner = await asyncio.wait_for(
                    _render(page["final_url"]), timeout=RENDER_TIMEOUT + 10
                )
            except Exception as e:  # noqa: BLE001 — 渲染失敗時保留靜態結果
                logger.warning("fetch_url render failed %s: %s", url, e)
                if not page["content"]:
                    raise FetchError(f"頁面打不開（瀏覽器渲染失敗：{type(e).__name__}）")
            else:
                page["rendered"] = True
                page["final_url"] = r_url
                title, text = await asyncio.to_thread(_extract_html, html, r_url)
                # trafilatura 會丟掉表格以外的動態區塊；不足時退回整頁可見文字
                if len(text) < MIN_CONTENT_CHARS and len(inner.strip()) > len(text):
                    text = "\n".join(ln.strip() for ln in inner.splitlines() if ln.strip())
                page["title"] = r_title or title or page["title"]
                if len(text) > len(page["content"]):
                    page["content"] = text

        if not page["content"].strip():
            raise FetchError("頁面沒有可讀的正文（可能需要登入，或為純圖片／互動頁）")
        page["content"], page["truncated"] = truncate_content(page["content"])
    except FetchError as e:
        page["error"] = str(e)
    except Exception as e:  # noqa: BLE001 — never raise
        logger.exception("fetch_url unexpected error for %s", url)
        page["error"] = f"頁面打不開（{type(e).__name__}）"
    logger.info(
        "fetch_url %s: %s chars, rendered=%s, truncated=%s, error=%s, %.1fs",
        url, len(page["content"]), page["rendered"], page["truncated"], page["error"],
        time.monotonic() - t0,
    )
    return page


async def fetch_urls(urls: List[Any]) -> Dict[str, Any]:
    if isinstance(urls, str):
        urls = [urls]
    clean: List[str] = []
    for u in urls or []:
        if isinstance(u, dict):
            u = u.get("url") or u.get("href")
        if isinstance(u, str) and u.strip() and u.strip() not in clean:
            clean.append(u.strip())
    if not clean:
        return {"success": False, "error": "缺少網址 urls"}
    if len(clean) > MAX_URLS:
        logger.info("fetch_url: %d urls, only first %d fetched", len(clean), MAX_URLS)
        clean = clean[:MAX_URLS]
    pages = await asyncio.gather(*(_fetch_one(u) for u in clean))
    return {"success": True, "data": {"pages": list(pages)}}
