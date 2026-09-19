# Quotex Signal Bot — production image for Render.com
#
# Render uses Docker to build and deploy. This Dockerfile is optimized
# for Render's container environment.
#
# Build (locally):   docker build -t quotex-bot .
# Run (mock):        docker run -d --name quotex-bot --env-file .env \
#                        -v "$PWD/data:/app/data" -v "$PWD/sessions:/app/sessions" \
#                        -v "$PWD/logs:/app/logs" quotex-bot
#
# Secrets (.env) and state (data/, sessions/, logs/) stay OUTSIDE
# the image via volumes. Never COPY a real .env into the image.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install system dependencies (git for pip git URLs, sqlite3 for DB)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git gcc sqlite3 curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for Docker layer caching)
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy source code
COPY auth/ ./auth/
COPY config/ ./config/
COPY core/ ./core/
COPY database/ ./database/
COPY engine/ ./engine/
COPY strategies/ ./strategies/
COPY tg_bot/ ./tg_bot/
COPY main.py run.py ./
RUN mkdir -p data sessions logs

# Render sets environment variables via dashboard.
# If QUOTEX_EMAIL is empty, bot runs in mock mode automatically.
CMD ["python", "run.py"]
