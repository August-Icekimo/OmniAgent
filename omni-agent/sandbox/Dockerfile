FROM python:3.13-slim

# 沙箱常用唯讀工具（coreutils 已內建；procps 提供 ps/free/uptime，curl 供連線測試）
RUN apt-get update && apt-get install -y --no-install-recommends \
    procps curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY exec_server.py .

# 非 root 執行；工作目錄掛在獨立 volume（compose 設定）
RUN useradd --create-home --uid 10001 sandbox \
    && mkdir -p /sandbox/work \
    && chown -R sandbox:sandbox /sandbox
USER sandbox

EXPOSE 8000

CMD ["uvicorn", "exec_server:app", "--host", "0.0.0.0", "--port", "8000"]
