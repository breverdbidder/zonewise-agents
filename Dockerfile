FROM python:3.12-slim

WORKDIR /app

# Minimal system deps (playwright browsers not preinstalled — optional scraping paths)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run injects PORT; local/Render fallback 8000
ENV PORT=8000
EXPOSE 8000

# shell form so $PORT expands at runtime
CMD uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8000}
