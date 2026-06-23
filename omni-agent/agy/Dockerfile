FROM python:3.13-slim

# 連線測試用 curl（healthcheck / 除錯）；保持精簡以縮小攻擊面。
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agy_server.py agent.py ./

# 非 root 執行；共享產物目錄掛在獨立 volume（compose 設定）。
# 先在 image 內以 agy 擁有者建立掛載點，空的 named volume 初始化時繼承此擁有權，
# 讓非 root 的 agy 可寫入 /a2a-workspace（與 brain 共享）。
RUN useradd --create-home --uid 10002 agy \
    && mkdir -p /a2a-workspace \
    && chown -R agy:agy /a2a-workspace
USER agy

EXPOSE 8000

CMD ["uvicorn", "agy_server:app", "--host", "0.0.0.0", "--port", "8000"]
