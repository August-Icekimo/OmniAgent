管理 chrysoberyl（192.168.68.77）上的 rapid-mlx 服務。

## 基本資訊

| 項目 | 值 |
|------|-----|
| SSH | `ssh 192.168.68.77` |
| Port | 8000 |
| Model | gemma-4-26b-4bit（`--mllm --no-thinking`） |
| 管理方式 | launchd plist |
| Plist 路徑 | `~/Library/LaunchAgents/com.icekimo.rapid-mlx.plist` |
| Stdout log | `~/Library/Logs/rapid-mlx.log` |
| Stderr log | `~/Library/Logs/rapid-mlx.err.log` |

## 操作方式

解析 `$ARGUMENTS`，依關鍵字執行對應動作。未提供 arguments 時，預設執行 **status**。

### status（預設）

```bash
ssh 192.168.68.77 "curl -s http://localhost:8000/health; echo; ps aux | grep rapid-mlx | grep -v grep | awk '{print \"PID:\", \$2, \"CPU:\", \$3\"%%\", \"MEM:\", \$4\"%%\"}'"
```

回報：healthy/not running、model_loaded、PID、CPU/MEM 使用率。

### stop

```bash
ssh 192.168.68.77 "launchctl unload ~/Library/LaunchAgents/com.icekimo.rapid-mlx.plist"
```

### start

```bash
ssh 192.168.68.77 "launchctl load ~/Library/LaunchAgents/com.icekimo.rapid-mlx.plist"
```

### restart

先 stop，再 start。等待 3 秒後執行 status 確認。

### logs [n]

顯示最後 n 行（預設 50）：

```bash
ssh 192.168.68.77 "tail -n 50 ~/Library/Logs/rapid-mlx.log"
```

如有 `--err`，改看 stderr log：

```bash
ssh 192.168.68.77 "tail -n 50 ~/Library/Logs/rapid-mlx.err.log"
```

### version

```bash
ssh 192.168.68.77 "rapid-mlx --version 2>/dev/null || /opt/homebrew/bin/rapid-mlx --version"
```

## 已知注意事項

- local 已於 2026-10 移出 brain 路由（觀察中），此服務非生產必要。
- `brew upgrade rapid-mlx` 後要進 Cellar venv 補 `Pillow` 與 `mlx-vlm==0.6.17`（**不可** `--force-reinstall`），否則 `--mllm` 啟動 crash。
- `--version` 讀的是磁碟版本，要確認運行版請比對 process 啟動時間。
