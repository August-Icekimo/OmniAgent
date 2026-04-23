# Podman 網路標籤錯誤分析與標準作業程序 (RCA & SOP)

## 1. 問題描述 (Issue Description)
在使用 `podman compose up` 時，出現以下錯誤訊息：
```text
network omni-agent_default was found but has incorrect label com.docker.compose.network set to "" (expected: "default")
Error: executing /usr/libexec/docker/cli-plugins/docker-compose up --build -d: exit status 1
```

## 2. 根本原因分析 (Root Cause Analysis, RCA)
此問題通常發生在 **Podman Compose 提供者 (Provider) 切換** 或 **版本更新** 之後：
- **提供者衝突**：系統中可能同時存在 `podman-compose` (Python 腳本) 與 `podman compose` (呼叫 `docker-compose` 二進位檔)。
- **標籤缺失**：舊版本或不同的提供者在建立網路時，未加入 `com.docker.compose.network` 標籤。
- **嚴格校驗**：目前的 `docker-compose` 插件會檢查現有網路的標籤是否符合預期（預期應為 `default`），若標籤為空或不符則拒絕啟動以確保環境一致性。

## 3. 標準作業程序 (SOP)

當遇到網路標籤不符的錯誤時，請按照以下步驟排除：

### 步驟 A：停止並移除容器
首先嘗試使用 compose 指令停止服務。
```bash
podman compose down
```
*注意：如果 `down` 指令也因為網路錯誤失敗，請手動強制移除相關容器。*

### 步驟 B：強制移除問題網路
手動移除導致衝突的網路，讓 Compose 下次啟動時能重新建立正確標籤的網路。
```bash
# 列出網路確認名稱
podman network ls

# 強制移除該網路 (例如 omni-agent_default)
podman network rm -f omni-agent_default
```

### 步驟 C：重新啟動服務
重新執行啟動指令，此時會自動建立帶有正確標籤的網路。
```bash
podman compose up --build -d
```

### 步驟 D：驗證網路標籤 (選用)
若要確認標籤是否已正確寫入，可執行：
```bash
podman network inspect omni-agent_default | grep labels -A 5
```
**預期輸出應包含：**
```json
"labels": {
     "com.docker.compose.network": "default",
     "com.docker.compose.project": "omni-agent",
     ...
}
```

## 4. 預防措施 (Prevention)
- **統一指令**：建議開發環境統一使用 `podman compose` (Podman 4.x+ 內建) 避免與舊版 `podman-compose` 混用。
- **乾淨啟動**：在進行重大配置更改時，建議先執行 `podman compose down` 徹底清理舊資源。
