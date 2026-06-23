管理 chrysoberyl（100.88.136.117）上的 rapid-mlx 服務。

## 基本資訊

| 項目 | 值 |
|------|-----|
| SSH | `ssh 100.88.136.117` |
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
ssh 100.88.136.117 "curl -s http://localhost:8000/health; echo; ps aux | grep rapid-mlx | grep -v grep | awk '{print \"PID:\", \$2, \"CPU:\", \$3\"%%\", \"MEM:\", \$4\"%%\"}'"
```

回報：healthy/not running、model_loaded、PID、CPU/MEM 使用率。

### stop

```bash
ssh 100.88.136.117 "launchctl unload ~/Library/LaunchAgents/com.icekimo.rapid-mlx.plist"
```

### start

```bash
ssh 100.88.136.117 "launchctl load ~/Library/LaunchAgents/com.icekimo.rapid-mlx.plist"
```

### restart

先 stop，再 start。等待 3 秒後執行 status 確認。

### logs [n]

顯示最後 n 行（預設 50）：

```bash
ssh 100.88.136.117 "tail -n 50 ~/Library/Logs/rapid-mlx.log"
```

如有 `--err`，改看 stderr log：

```bash
ssh 100.88.136.117 "tail -n 50 ~/Library/Logs/rapid-mlx.err.log"
```

### version

```bash
ssh 100.88.136.117 "rapid-mlx --version 2>/dev/null || /opt/homebrew/bin/rapid-mlx --version"
```

## 已知注意事項

- `brew upgrade rapid-mlx` 後需重裝 Pillow：`pip install Pillow` 進 Cellar venv，否則 `--mllm` 啟動 crash。
- `--pin-system-prompt` 在 `--mllm` 模式下測試無效（Task 5 blocked）。
- 伺服器端雖有 running-request abort 實作，但 `cancelled:true` 是假確認，實測不會真停。
- Prompt cache 預設關閉。
