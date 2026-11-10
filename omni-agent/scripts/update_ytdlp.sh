#!/usr/bin/env bash
# 更新 brain 容器內的 yt-dlp（short-video-fetch）。
#
# yt-dlp 刻意不釘版：TikTok／IG／抖音一改版舊版就失效，只能靠升級追。
# 何時跑：brain log 出現 `ytdlp_extractor_error`，或 Cindy 回「可能是平台改版…需要更新 yt-dlp」。
#
# 用法（在 omni-agent/ 或任意目錄皆可）：
#   scripts/update_ytdlp.sh
#
# 做的事：--no-cache 重建 brain（requirements 的 yt-dlp>= 會抓到 PyPI 最新版）→ 重啟 → 等 health → 印版本。
# 注意：--no-cache 會連同其他依賴一起重抓；被釘上限的套件（anthropic、openai、av）仍受 requirements 限制。
set -euo pipefail

cd "$(dirname "$0")/.."

before=$(podman exec omni-agent-brain-1 python -m yt_dlp --version 2>/dev/null || echo "（容器未執行）")
echo "目前 yt-dlp：${before}"

podman compose build --no-cache brain
podman compose up -d brain

echo -n "等待 brain health"
for _ in $(seq 1 60); do
    if curl -sf http://localhost:8000/health >/dev/null; then
        echo " OK"
        break
    fi
    echo -n "."
    sleep 2
done
curl -sf http://localhost:8000/health >/dev/null || { echo; echo "brain health 檢查失敗，請看 podman compose logs brain" >&2; exit 1; }

after=$(podman exec omni-agent-brain-1 python -m yt_dlp --version)
echo "yt-dlp：${before} → ${after}"
