FROM python:3.13-slim

WORKDIR /app

# 安裝系統依賴（asyncpg 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libcairo2-dev libpango1.0-dev libjpeg-dev libgif-dev librsvg2-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
