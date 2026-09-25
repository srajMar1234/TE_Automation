# Production image for TE Report Studio (optional; Windows VM deploy prefers PM2 — see DEPLOY_WINDOWS.md)
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .

RUN mkdir -p logs data/cutover_history downloads/exports output

ENV PYTHONUNBUFFERED=1
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8501/_stcore/health || exit 1

CMD ["python", "-m", "streamlit", "run", "app/studio.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true", "--browser.gatherUsageStats=false"]
