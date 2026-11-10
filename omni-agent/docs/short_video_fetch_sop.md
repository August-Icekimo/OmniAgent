# 短影音分析（analyze_video_url）維運 SOP

Cindy 收到影片連結時用 `analyze_video_url`：YouTube 直接交給 Gemini 讀網址；其他平台由 brain 用
yt-dlp 下載到暫存、必要時 ffmpeg 壓縮，再 inline 送 Gemini，結束即刪檔。設計見
`docs/archive/change_short-video-fetch.md`。

| 平台 | 匿名可用？ | 備註 |
|---|---|---|
| YouTube | ✅ | 不下載，Gemini 直讀 URL |
| TikTok | ✅（多數公開影片） | 少數影片會回「封鎖了這台主機的地區或 IP」，與 cookie 無關 |
| Instagram Reels | ⚠️ 常常可以 | 被限流或私人帳號時需 cookie |
| 抖音 | ❌ | 一定要 cookie（yt-dlp：「Fresh cookies are needed」，不必登入，有瀏覽過即可） |
| 小紅書 | ⚠️ | 匿名常拿不到影片 → 建議設 cookie |
| X（Twitter） | ✅ 多數 | 敏感內容需 cookie |
| B站 | ✅ 多數 | 部分有地區限制 |

---

## 1. Cookie 設定

### 放哪裡
主機目錄 `~/.config/omni-agent/ytdlp-cookies/`（可用 `.env` 的 `YTDLP_COOKIE_HOST_DIR` 改路徑），
唯讀掛載到 brain 的 `/ytdlp-cookies`。檔名固定為平台 key：

```
tiktok.txt  instagram.txt  douyin.txt  twitter.txt  xiaohongshu.txt  bilibili.txt
```

沒有檔案的平台就匿名嘗試。brain 每次會把 cookie 複製到暫存再交給 yt-dlp，原檔不會被改寫。

> 目錄必須先存在，podman 不會自動建立 bind mount 的來源目錄，不存在的話 brain 會起不來：
> ```bash
> mkdir -p ~/.config/omni-agent/ytdlp-cookies && chmod 700 ~/.config/omni-agent/ytdlp-cookies
> ```

### 怎麼匯出
1. 用**小號**（不要用主帳號，被平台風控時損失小）在桌機瀏覽器登入該平台，隨便看一兩支影片。
2. 裝「Get cookies.txt LOCALLY」之類**本機匯出、不上傳**的擴充套件，在該平台頁面匯出 **Netscape 格式**。
3. 傳到主機：
   ```bash
   scp instagram.txt icekimo@<homelab>:~/.config/omni-agent/ytdlp-cookies/instagram.txt
   chmod 600 ~/.config/omni-agent/ytdlp-cookies/*.txt
   ```
4. 不用重啟 brain，下一次請求就會讀到新檔。

cookie 等同登入憑證：不要進 git、不要貼到聊天、不要經由 Cindy 上傳。

### 怎麼知道過期了
- Cindy 回覆：「現有的 <平台> cookie 可能已過期，需要請管理員更新 cookie」
- brain log：
  ```bash
  podman compose logs brain | grep cookie_expired
  # cookie_expired platform=instagram had_cookie=True detail=...
  ```
  `had_cookie=False` 代表還沒設定該平台 cookie；`True` 代表已設定但失效，照上面步驟重新匯出。

---

## 2. 更新 yt-dlp

yt-dlp 刻意不釘版本上限（requirements：`yt-dlp>=…`），平台改版時要靠升級追。

### 何時要更新
- Cindy 回覆：「可能是平台改版導致下載工具失效，需要請管理員更新 yt-dlp」
- brain log 出現 `ytdlp_extractor_error`：
  ```bash
  podman compose logs brain | grep ytdlp_extractor_error
  ```

### 怎麼更新
```bash
cd ~/gitWrk/OmniAgent/omni-agent
scripts/update_ytdlp.sh      # --no-cache 重建 brain、重啟、印出新舊版本
```

### 先確認是不是 yt-dlp 的問題
```bash
podman exec omni-agent-brain-1 python -m yt_dlp --simulate --use-extractors tiktok '<影片網址>'
```
- 一樣失敗 → yt-dlp／平台問題：更新 yt-dlp，或到 yt-dlp GitHub issues 查該平台是否已知壞掉
- 成功 → 是我們的程式問題，看 `brain.skills.video_fetch` 的 log

---

## 3. 限制（設計上的）
- 長度分級（YouTube 也先 probe 長度）：
  - ≤ 6 分鐘：直接分析
  - 6–15 分鐘：Cindy 先問「要繼續分析嗎？」，使用者回「好／可以／確認」才跑（走既有寫入型工具的確認往返，`confirm:pending:<user>`）；下載改 ≤ 480p、上限 150MB
  - > 15 分鐘：拒絕。硬上限受 `TURN_PROCESSING_TIMEOUT`（預設 300s）約束，要放寬須一併調高該逾時與 `video_fetch.py` 的下載/轉檔逾時
- 直播不支援；IG 多影片貼文只取第一支
- 下載檔 ≤ 50MB（長影片 150MB）；> 15MB 會壓畫質再送：≲4.5 分鐘 480p、≲10 分鐘 360p@2fps、更長 360p@1fps（Gemini 本來就約 1fps 取樣，影響不大；細小文字可能看不清）
- 只有 Gemini 能看影片：Gemini 額度用完時，Cindy 會直接說無法分析，不會改用其他模型
- 同時只跑一個下載，家人同時丟影片時第二個會排隊
