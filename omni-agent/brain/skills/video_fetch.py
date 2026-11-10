"""短影音分析（analyze_video_url 工具）— short-video-fetch。

Gemini 只能直讀 YouTube URL；TikTok／IG Reels／抖音等需先下載成檔案再 inline 送出。

流程：
    YouTube → video part 帶 file_uri，直接交給 Gemini（不下載）
    其他白名單平台 →
        is_safe_url → 短網址展開（自管 redirect、每跳重檢）→ 平台判定
        → yt-dlp probe（-J，不下載）→ 長度/直播檢查（> 6 分鐘需使用者同意，> 15 分鐘拒絕）
        → yt-dlp 依 probe 結果下載（--load-info-json，--max-filesize）
        → 超過 inline 上限 → ffmpeg 降畫質
        → FileAnalyzer.video_chat（inline）→ 刪暫存

統一回傳格式（對齊 web_fetch 契約，never raise）：
    成功: {"success": True, "data": {"url", "final_url", "platform", "title", "uploader",
                                    "duration", "caption", "transcoded", "analysis"}}
    失敗: {"success": False, "error": "<可讀錯誤訊息>"}

安全：
- 輸入 URL 與短網址展開的每一跳都過 url_safety.is_safe_url。
- yt-dlp 自己發的請求（API、CDN）無法逐跳檢查 → 以「平台網域白名單 + 只載入該平台的 extractor
  （--use-extractors，generic 不在內）」限制它只會打平台自己的端點。殘餘風險見 change doc。
- yt-dlp / ffmpeg 一律以 subprocess 執行：逾時可 kill，不會像 thread 一樣卡住 turn。
"""

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import sys
import uuid
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urljoin, urlsplit

import httpx

from skills.url_safety import is_safe_url

logger = logging.getLogger("brain.skills.video_fetch")

# 長度分兩級：≤ 6 分鐘直接分析；6–15 分鐘需使用者同意（graph 的確認往返）；> 15 分鐘拒絕。
# 硬上限受 TURN_PROCESSING_TIMEOUT（預設 300s）約束：probe＋下載＋轉檔＋Gemini＋回覆都要塞進去。
CONFIRM_DURATION_SEC = 6 * 60
MAX_DURATION_SEC = 15 * 60
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
MAX_DOWNLOAD_BYTES_LONG = 150 * 1024 * 1024
# Gemini inline request 上限約 20MB，base64 膨脹 4/3 → 原檔 15MB 以下才安全（Open Question 1）
MAX_INLINE_BYTES = 15 * 1024 * 1024
TRANSCODE_TARGET_BYTES = 14 * 1024 * 1024  # 轉檔目標留 1MB 餘裕（位元率估算不精確）
PROBE_TIMEOUT = 45.0
DOWNLOAD_TIMEOUT = 90.0
DOWNLOAD_TIMEOUT_LONG = 120.0
TRANSCODE_TIMEOUT = 60.0
TRANSCODE_TIMEOUT_LONG = 90.0
MAX_REDIRECTS = 5
CAPTION_MAX_CHARS = 500

WORK_ROOT = os.getenv("VIDEO_FETCH_DIR", "/workspace/uploads/video_fetch")
COOKIE_DIR = os.getenv("YTDLP_COOKIE_DIR", "/ytdlp-cookies")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
)

# 平台 → 網域與 yt-dlp extractor（--use-extractors 為 fullmatch、不分大小寫）
PLATFORMS: Dict[str, Dict[str, Any]] = {
    "tiktok": {"label": "TikTok", "hosts": ("tiktok.com",), "extractors": "tiktok,vm\\.tiktok"},
    "instagram": {"label": "Instagram", "hosts": ("instagram.com",), "extractors": "instagram"},
    "douyin": {"label": "抖音", "hosts": ("douyin.com", "iesdouyin.com"), "extractors": "douyin"},
    "twitter": {"label": "X（Twitter）", "hosts": ("twitter.com", "x.com"), "extractors": "twitter,twitter:card,twitter:amplify"},
    "xiaohongshu": {"label": "小紅書", "hosts": ("xiaohongshu.com",), "extractors": "xiaohongshu"},
    "bilibili": {"label": "B站", "hosts": ("bilibili.com",), "extractors": "bilibili"},
}
# 分享用短網址：先自行展開（每跳 SSRF 重檢），展開後須落在 PLATFORMS 網域
SHORT_HOSTS = (
    "vt.tiktok.com", "vm.tiktok.com", "v.douyin.com", "xhslink.com", "b23.tv", "t.co",
)
YOUTUBE_HOSTS = ("youtube.com", "youtu.be")
YOUTUBE_EXTRACTORS = "youtube"  # 只取 metadata（長度）；YouTube 本身由 Gemini 直讀 URL，不下載
# 匿名常拿不到影片、通常需要 cookie 的平台（影響錯誤訊息措辭）
LOGIN_GATED = ("instagram", "douyin", "xiaohongshu")

# 同時只跑一個下載/轉檔（brain 無 mem_limit；也避免同一 IP 併發被平台限流）
_download_lock = asyncio.Semaphore(1)


class VideoFetchError(Exception):
    """可直接給模型看的失敗原因。"""


class NeedsConfirmation(Exception):
    """影片超過免確認長度，需使用者同意才繼續。"""

    def __init__(self, question: str):
        super().__init__(question)
        self.question = question


def _fmt_duration(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 60} 分 {sec % 60} 秒" if sec >= 60 else f"{sec} 秒"


def _host_matches(host: str, domains) -> bool:
    host = (host or "").lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in domains)


def classify_url(url: str) -> Optional[str]:
    """回傳 'youtube'／'short'／平台 key；不在白名單回 None。"""
    host = urlsplit(url).hostname or ""
    if _host_matches(host, SHORT_HOSTS):
        return "short"
    if _host_matches(host, YOUTUBE_HOSTS):
        return "youtube"
    for key, p in PLATFORMS.items():
        if _host_matches(host, p["hosts"]):
            return key
    return None


def supported_platforms_text() -> str:
    return "YouTube、" + "、".join(p["label"] for p in PLATFORMS.values())


async def _expand_short_url(url: str) -> str:
    """自管 redirect 展開分享短網址，每一跳都過 SSRF 檢查；落到白名單平台即停。"""
    current = url
    async with httpx.AsyncClient(
        follow_redirects=False, timeout=10.0, headers={"User-Agent": USER_AGENT}
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            ok, reason = await is_safe_url(current)
            if not ok:
                raise VideoFetchError(f"短網址導向被拒絕：{reason}")
            kind = classify_url(current)
            if kind not in (None, "short"):
                return current
            if kind is None:
                raise VideoFetchError(f"短網址導向到不支援的網站（{urlsplit(current).hostname}）")
            try:
                async with client.stream("GET", current) as resp:
                    location = resp.headers.get("location")
                    status = resp.status_code
            except httpx.HTTPError as e:
                raise VideoFetchError(f"短網址展開失敗（{type(e).__name__}）")
            if status not in (301, 302, 303, 307, 308) or not location:
                raise VideoFetchError(f"短網址沒有導向影片頁（HTTP {status}）")
            current = urljoin(current, location)
    raise VideoFetchError("短網址導向次數過多")


def _cookie_file(platform: str) -> Optional[str]:
    path = os.path.join(COOKIE_DIR, f"{platform}.txt")
    return path if os.path.isfile(path) else None


# --- yt-dlp 錯誤分類（stderr 文字）---
_ERR_IP_BLOCKED = re.compile(r"IP address is blocked|not available in your (country|region)|geo.?restrict", re.I)
_ERR_LOGIN = re.compile(
    r"log ?in|sign ?in|cookies|authenticat|private|rate.?limit|too many requests|"
    r"HTTP Error 429|requires? (a )?(login|account)|age.?restrict|confirm your age",
    re.I,
)
_ERR_UNSUPPORTED = re.compile(r"Unsupported URL|No suitable extractor", re.I)
_ERR_NOT_FOUND = re.compile(r"HTTP Error 404|not found|removed|deleted|does not exist|unavailable", re.I)
_ERR_NO_VIDEO = re.compile(r"no video|There'?s no video|No video formats found", re.I)


def classify_ytdlp_error(stderr: str, platform: str, had_cookie: bool) -> str:
    label = PLATFORMS.get(platform, {}).get("label", platform)
    last = next((ln for ln in reversed(stderr.strip().splitlines()) if ln.startswith("ERROR")), "")
    text = last or stderr[-500:]
    if _ERR_IP_BLOCKED.search(text):
        return f"{label} 封鎖了這台主機的地區或 IP，抓不到這則影片。"
    if _ERR_NO_VIDEO.search(text):
        if not had_cookie and platform in LOGIN_GATED:
            return f"在這則貼文裡找不到影片：可能是圖文貼文，或 {label} 需要登入 cookie 才看得到（請管理員設定）。"
        return "這則貼文裡沒有影片（可能是圖文貼文）。"
    if _ERR_UNSUPPORTED.search(text):
        return f"這個網址不是可下載的單則影片（支援：{supported_platforms_text()}）。"
    if _ERR_LOGIN.search(text):
        logger.warning("cookie_expired platform=%s had_cookie=%s detail=%s", platform, had_cookie, text[:200])
        if had_cookie:
            return f"{label} 要求登入，現有的 {label} cookie 可能已過期，需要請管理員更新 cookie。"
        return f"{label} 要求登入才能看這則影片，需要請管理員設定 {label} 的 cookie。"
    if _ERR_NOT_FOUND.search(text):
        return "影片不存在、已被刪除，或設為不公開。"
    logger.error("ytdlp_extractor_error platform=%s detail=%s", platform, text[:300])
    return f"{label} 的影片下載失敗，可能是平台改版導致下載工具失效，需要請管理員更新 yt-dlp。"


async def _run(cmd: list, timeout: float) -> Tuple[int, bytes, bytes]:
    """跑 subprocess；逾時 kill 並 raise TimeoutError。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        logger.error("executable not found: %s", cmd[0])
        raise VideoFetchError("影片處理工具未安裝（需請管理員檢查 brain 映像檔）。")
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode, out, err


def _ytdlp_base(platform: str, cookie_copy: Optional[str]) -> list:
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--use-extractors", PLATFORMS[platform]["extractors"] if platform in PLATFORMS else YOUTUBE_EXTRACTORS,
        "--no-playlist", "--playlist-items", "1",
        "--no-warnings", "--no-progress", "--ignore-config", "--no-cache-dir",
        "--socket-timeout", "20",
    ]
    if cookie_copy:
        cmd += ["--cookies", cookie_copy]
    return cmd


def _pick_entry(info: dict) -> dict:
    """IG 多影片貼文等會回 playlist → 取第一支有影片的。"""
    if info.get("_type") in ("playlist", "multi_video"):
        for e in info.get("entries") or []:
            if e and (e.get("formats") or e.get("url")):
                return e
        raise VideoFetchError("這則貼文裡沒有影片（可能是圖文貼文）。")
    return info


async def _probe(url: str, platform: str, cookie_copy: Optional[str], had_cookie: bool) -> dict:
    try:
        rc, out, err = await _run(_ytdlp_base(platform, cookie_copy) + ["-J", url], PROBE_TIMEOUT)
    except asyncio.TimeoutError:
        raise VideoFetchError("讀取影片資訊逾時，平台可能暫時連不上。")
    if rc != 0:
        raise VideoFetchError(classify_ytdlp_error(err.decode("utf-8", "replace"), platform, had_cookie))
    try:
        info = json.loads(out)
    except ValueError:
        raise VideoFetchError("下載工具回傳了無法解析的影片資訊。")
    return _pick_entry(info)


async def _probe_youtube(url: str) -> dict:
    """YouTube 只查長度/直播狀態。yt-dlp 少了 JS runtime 仍拿得到 metadata（formats 不需要）；
    probe 失敗不擋分析（回空 dict → 無長度資訊，照舊交 Gemini 直讀）。"""
    try:
        rc, out, err = await _run(
            _ytdlp_base("youtube", None) + ["-J", "--ignore-no-formats-error", url], PROBE_TIMEOUT
        )
        if rc == 0:
            return _pick_entry(json.loads(out))
        logger.warning("youtube probe failed (ignored): %s", err.decode("utf-8", "replace")[-200:])
    except (asyncio.TimeoutError, ValueError, VideoFetchError) as e:
        logger.warning("youtube probe failed (ignored): %s", e)
    return {}


def _check_limits(info: dict, confirmed: bool) -> bool:
    """回傳是否為長影片（走低畫質下載/轉檔）。超過硬上限 raise；需同意而未同意 raise NeedsConfirmation。"""
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
        raise VideoFetchError("這是直播，無法分析。")
    duration = info.get("duration")
    if not duration or duration <= CONFIRM_DURATION_SEC:
        return False
    if duration > MAX_DURATION_SEC:
        raise VideoFetchError(
            f"影片長 {_fmt_duration(duration)}，超過 {MAX_DURATION_SEC // 60} 分鐘上限，無法分析。"
        )
    if not confirmed:
        raise NeedsConfirmation(
            f"這支影片長 {_fmt_duration(duration)}，超過 {CONFIRM_DURATION_SEC // 60} 分鐘，"
            "分析會比較久（約 1–3 分鐘）、也比較耗 Gemini 額度，畫質會壓低。要繼續分析嗎？（回「好」繼續）"
        )
    return True


async def _download(info: dict, platform: str, workdir: str, cookie_copy: Optional[str], had_cookie: bool,
                    long: bool = False) -> str:
    max_bytes = MAX_DOWNLOAD_BYTES_LONG if long else MAX_DOWNLOAD_BYTES
    info_path = os.path.join(workdir, "info.json")
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(info, f)
    cmd = _ytdlp_base(platform, cookie_copy) + [
        "--load-info-json", info_path,
        # 偏好 ≤720p（長影片 ≤480p）、h264、mp4/m4a（Gemini 相容性最好、檔案也小）；合併用 image 內的 ffmpeg
        "-S", f"res:{480 if long else 720},vcodec:h264,ext:mp4:m4a",
        "-f", "b/bv*+ba",
        "--merge-output-format", "mp4",
        "--max-filesize", str(max_bytes),
        "-o", os.path.join(workdir, "video.%(ext)s"),
        "--print", "after_move:filepath",
    ]
    try:
        rc, out, err = await _run(cmd, DOWNLOAD_TIMEOUT_LONG if long else DOWNLOAD_TIMEOUT)
    except asyncio.TimeoutError:
        raise VideoFetchError("下載影片逾時。")
    if rc != 0:
        raise VideoFetchError(classify_ytdlp_error(err.decode("utf-8", "replace"), platform, had_cookie))
    path = out.decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
    path = path[0]
    if not path or not os.path.isfile(path):
        # --max-filesize 觸發時 yt-dlp 只印訊息、不報錯、也不產生檔案
        raise VideoFetchError(f"影片檔超過 {max_bytes // (1024 * 1024)}MB 上限，無法分析。")
    return path


def transcode_params(duration: Optional[float]) -> Tuple[int, int, Optional[int], int]:
    """依長度估位元率，回傳 (短邊解析度, 影像 bps, fps 上限或 None, 音訊 bps)。

    Gemini 預設約 1 fps 取樣影片，長影片把 fps 壓到 1–2 幾乎不損失分析品質，卻能把位元率留給畫面清晰度。"""
    dur = duration or CONFIRM_DURATION_SEC
    total_bps = int(TRANSCODE_TARGET_BYTES * 8 / dur)
    if total_bps >= 400_000:  # ≲ 4.5 分鐘
        return 480, min(900_000, total_bps - 64_000), None, 64_000
    if total_bps >= 180_000:  # ≲ 10 分鐘
        return 360, total_bps - 32_000, 2, 32_000
    return 360, max(50_000, total_bps - 32_000), 1, 32_000


async def _transcode(src: str, workdir: str, duration: Optional[float], long: bool = False) -> str:
    """降畫質（解析度/fps/位元率按長度估算），讓檔案落在 inline 上限內。"""
    res, video_bps, fps, audio_bps = transcode_params(duration)
    vf = f"scale='if(gt(iw,ih),-2,{res})':'if(gt(iw,ih),{res},-2)'"
    if fps:
        vf += f",fps={fps}"
    dst = os.path.join(workdir, "video_small.mp4")
    cmd = [
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", src,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast",
        "-b:v", str(video_bps), "-maxrate", str(video_bps), "-bufsize", str(video_bps * 2),
        "-c:a", "aac", "-b:a", str(audio_bps), "-ac", "1",
        "-movflags", "+faststart", dst,
    ]
    try:
        rc, _out, err = await _run(cmd, TRANSCODE_TIMEOUT_LONG if long else TRANSCODE_TIMEOUT)
    except asyncio.TimeoutError:
        raise VideoFetchError("影片太大，壓縮逾時。")
    if rc != 0 or not os.path.isfile(dst):
        logger.error("ffmpeg transcode failed: %s", err.decode("utf-8", "replace")[-300:])
        raise VideoFetchError("影片太大且壓縮失敗，無法分析。")
    return dst


def _mime_for(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska"}.get(
        ext, "video/mp4"
    )


async def _analyze(model_router, video_part: dict, instruction: Optional[str]) -> str:
    from skills.file_analyzer import FileAnalyzer
    if model_router is None:
        raise VideoFetchError("影片分析服務未就緒。")
    analyzer = FileAnalyzer(model_router)
    unavailable = "影片只能由 Gemini 分析，但 Gemini 目前無法使用（可能額度用完或服務異常），請稍後再試。"
    try:
        text = await analyzer.video_chat(video_part, instruction, caller="analyze_video_url")
    except Exception as e:  # noqa: BLE001 — router 全數失敗即 Gemini 不可用（影片只有 Gemini 能看）
        logger.error("video analysis via router failed: %s", e)
        raise VideoFetchError(unavailable)
    # router 對多模態全數失敗不 raise，而是回空內容（Honest Fallback，router.py）→ 同樣視為不可用，
    # 不能回 success 讓模型對著空分析自行腦補
    if not (text or "").strip():
        logger.error("video analysis returned empty content (multimodal routing failed)")
        raise VideoFetchError(unavailable)
    return text


async def _analyze_download(url: str, platform: str, model_router, instruction: Optional[str],
                            confirmed: bool = False) -> Dict[str, Any]:
    os.makedirs(WORK_ROOT, exist_ok=True)
    workdir = os.path.join(WORK_ROOT, uuid.uuid4().hex)
    os.makedirs(workdir)
    try:
        cookie_src = _cookie_file(platform)
        cookie_copy = None
        if cookie_src:
            # yt-dlp 結束時會回寫 cookie 檔；原檔唯讀掛載，給它一份暫存副本
            cookie_copy = os.path.join(workdir, "cookies.txt")
            shutil.copyfile(cookie_src, cookie_copy)
        had_cookie = cookie_copy is not None

        async with _download_lock:
            info = await _probe(url, platform, cookie_copy, had_cookie)
            long = _check_limits(info, confirmed)
            path = await _download(info, platform, workdir, cookie_copy, had_cookie, long=long)
            transcoded = False
            if os.path.getsize(path) > MAX_INLINE_BYTES:
                path = await _transcode(path, workdir, info.get("duration"), long=long)
                transcoded = True
                if os.path.getsize(path) > MAX_INLINE_BYTES:
                    raise VideoFetchError("影片壓縮後仍然太大，無法分析。")

        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        analysis = await _analyze(
            model_router, {"type": "video", "mime_type": _mime_for(path), "data": data}, instruction
        )
        caption = (info.get("description") or "").strip()
        return {
            "platform": PLATFORMS[platform]["label"],
            "final_url": info.get("webpage_url") or url,
            "title": info.get("title") or "",
            "uploader": info.get("uploader") or info.get("channel") or "",
            "duration": info.get("duration"),
            "caption": caption[:CAPTION_MAX_CHARS] + ("…" if len(caption) > CAPTION_MAX_CHARS else ""),
            "transcoded": transcoded,
            "analysis": analysis,
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def analyze_video_url(url: Any, instruction: Optional[str], model_router,
                            confirmed: bool = False) -> Dict[str, Any]:
    """工具入口。never raise。

    影片超過 CONFIRM_DURATION_SEC 且未經同意 → 回 {"success": False, "needs_confirmation": True, "question": ...}，
    由 graph 走確認往返；使用者同意後以 confirmed=True 重跑。"""
    url = str(url or "").strip()
    if not url:
        return {"success": False, "error": "缺少影片網址 url"}
    instruction = (str(instruction).strip() or None) if instruction else None
    try:
        kind = classify_url(url)
        if kind is None:
            # 白名單先擋（純字串比對），不在名單的網址連 DNS 都不查
            raise VideoFetchError(
                f"不支援這個網站的影片（支援：{supported_platforms_text()}）。一般網頁請改用 fetch_url。"
            )
        ok, reason = await is_safe_url(url)
        if not ok:
            raise VideoFetchError(f"網址被拒絕：{reason}")
        final_url = url
        if kind == "short":
            final_url = await _expand_short_url(url)
            kind = classify_url(final_url)

        if kind == "youtube":
            info = await _probe_youtube(final_url)
            _check_limits(info, confirmed)
            analysis = await _analyze(
                model_router, {"type": "video", "mime_type": "video/mp4", "file_uri": final_url}, instruction
            )
            data = {"platform": "YouTube", "final_url": final_url, "title": info.get("title") or "",
                    "uploader": info.get("uploader") or info.get("channel") or "",
                    "duration": info.get("duration"), "caption": "", "transcoded": False, "analysis": analysis}
        else:
            data = await _analyze_download(final_url, kind, model_router, instruction, confirmed=confirmed)
        data["url"] = url
        logger.info("analyze_video_url ok platform=%s url=%s transcoded=%s",
                    data["platform"], data["final_url"], data["transcoded"])
        return {"success": True, "data": data}
    except NeedsConfirmation as e:
        logger.info("analyze_video_url needs confirmation url=%s", url)
        return {"success": False, "needs_confirmation": True, "question": e.question, "error": e.question}
    except VideoFetchError as e:
        logger.info("analyze_video_url failed url=%s: %s", url, e)
        return {"success": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001 — 工具契約 never raise
        logger.exception("analyze_video_url unexpected error url=%s", url)
        return {"success": False, "error": f"影片分析發生未預期錯誤（{type(e).__name__}）"}
