FROM python:3.13.17-slim

WORKDIR /app

# 安裝系統依賴（asyncpg 需 build-essential，faster-whisper 需 ffmpeg 等）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ffmpeg \
    libcairo2-dev libpango1.0-dev libjpeg-dev libgif-dev librsvg2-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# fetch_url 的 JS 渲染：Playwright 只裝 headless shell（省去完整 Chromium）＋系統依賴（web-fetch-tool）
RUN playwright install --with-deps --only-shell chromium && rm -rf /var/lib/apt/lists/*

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
