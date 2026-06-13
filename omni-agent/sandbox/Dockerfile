FROM python:3.13-slim

# 沙箱常用唯讀工具（coreutils 已內建；procps 提供 ps/free/uptime，curl 供連線測試）
RUN apt-get update && apt-get install -y --no-install-recommends \
    procps curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY exec_server.py .

# 非 root 執行；工作目錄與 log 目錄掛在獨立 volume（compose 設定）。
# 先在 image 內以 sandbox 擁有者建立掛載點，空的 named volume 初始化時會繼承此
# 擁有權，讓非 root 的 sandbox 可寫入 log（/sandbox/logs 由 brain 與 sandbox 共享，
# brain 端開機時另會 chown 一次以排除初始化競態，見 brain/terminal_logs.py）。
RUN useradd --create-home --uid 10001 sandbox \
    && mkdir -p /sandbox/work /sandbox/logs \
    && chown -R sandbox:sandbox /sandbox
USER sandbox

EXPOSE 8000

CMD ["uvicorn", "exec_server:app", "--host", "0.0.0.0", "--port", "8000"]
