"""URL 安全檢查（SSRF 防護）— 概念參考 hermes-agent tools/url_safety.py。

fetch_url 會替模型打開任意網址；brain 位於 compose 內網（postgres、sandbox、searxng…）
且可達 HomeLab LAN 與 Tailscale，故每個對外請求（含每一跳 redirect、headless 瀏覽器的
每個子請求）都必須先通過 is_safe_url。

殘餘風險：DNS rebinding（檢查後、連線前 IP 改變）未完全防堵，以「每次請求都重新檢查」縮小窗口。
"""

import asyncio
import ipaddress
import logging
import re
import socket
from typing import Optional, Tuple
from urllib.parse import unquote, urlsplit

logger = logging.getLogger("brain.skills.url_safety")

# Tailscale 等 CGNAT 段；Python 的 is_private 不涵蓋 100.64.0.0/10
_CGNAT = ipaddress.ip_network("100.64.0.0/10")

# URL 內夾帶 secret 的常見前綴（先 URL-decode 再比對）
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|sk_(live|test)_[A-Za-z0-9]{8,}|gh[pousr]_[A-Za-z0-9]{16,}|"
    r"github_pat_[A-Za-z0-9_]{16,}|xox[abprs]-[A-Za-z0-9\-]{8,}|AIza[0-9A-Za-z_\-]{20,}|"
    r"ya29\.[0-9A-Za-z_\-]{10,}|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})"
)


def _ip_block_reason(ip: ipaddress._BaseAddress) -> Optional[str]:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link-local"
    if ip.is_multicast:
        return "multicast"
    if ip.is_unspecified:
        return "unspecified"
    if isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT:
        return "CGNAT/Tailscale"
    if ip.is_private:
        return "私網"
    if ip.is_reserved:
        return "保留位址"
    if not ip.is_global:
        return "非公網位址"
    return None


def check_url_syntax(url: str) -> Tuple[Optional[str], Optional[str]]:
    """不打網路的靜態檢查。回傳 (host, None) 或 (None, 拒絕原因)。"""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None, "網址格式錯誤"
    if parts.scheme not in ("http", "https"):
        return None, f"不支援的協定：{parts.scheme or '（無）'}"
    if parts.username or parts.password:
        return None, "網址不可夾帶帳號密碼"
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        return None, "網址缺少主機名稱"
    if _SECRET_RE.search(unquote(unquote(url))):
        return None, "網址疑似夾帶金鑰／token"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        reason = _ip_block_reason(ip)
        return (None, f"目標為{reason}位址") if reason else (host, None)
    # 非 IP 字面值：無點主機名（compose 服務名 postgres/searxng、localhost）一律拒絕；
    # 數字形式的怪異 IP（0x7f000001、2130706433）也在此擋下（getaddrinfo 會把它們解成 IP）
    if "." not in host:
        return None, "不允許內部主機名稱"
    if host.endswith((".local", ".internal", ".lan", ".home", ".localhost")):
        return None, "不允許內部網域"
    return host, None


async def is_safe_url(url: str) -> Tuple[bool, Optional[str]]:
    """完整檢查（含 DNS 解析）。回傳 (是否安全, 拒絕原因)。"""
    host, reason = check_url_syntax(url)
    if reason:
        return False, reason
    try:
        ipaddress.ip_address(host)
        return True, None  # IP 字面值已在 syntax 檢查過
    except ValueError:
        pass
    try:
        loop = asyncio.get_running_loop()
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, None, type=socket.SOCK_STREAM), timeout=5
        )
    except (socket.gaierror, asyncio.TimeoutError, OSError) as e:
        return False, f"無法解析主機 {host}（{type(e).__name__}）"
    if not infos:
        return False, f"無法解析主機 {host}"
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr.split("%", 1)[0])
        except ValueError:
            return False, f"主機 {host} 解析出無效位址"
        r = _ip_block_reason(ip)
        if r:
            return False, f"主機 {host} 解析到{r}位址"
    return True, None
