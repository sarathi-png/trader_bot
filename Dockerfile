# Quotex Signal Bot — production image (ARM64 Ampere A1 + AMD64).
#
# Build (on the VM):   docker build -t quotex-bot .
# Run (live/demo):     docker run -d --name quotex-bot --restart=always \
#                        --env-file .env \
#                        -v "$PWD/data:/app/data" \
#                        -v "$PWD/sessions:/app/sessions" \
#                        -v "$PWD/logs:/app/logs" \
#                        quotex-bot
#
# Secrets (.env) and state (data/, sessions/, logs/) stay OUTSIDE the image
# via --env-file and volumes. Never COPY a real .env into the image.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# git: pyquotex is installed from a git URL (see requirements.txt).
# gcc/g++: safety net for any sdist fallback (numpy/pandas ship wheels for
# both ARM64 and AMD64, but a compiler avoids a hard failure).
# sqlite3: CLI for on-host DB inspection.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git gcc g++ sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Chromium for SSID extraction/refresh. Playwright ships linux-arm64 and
# linux-amd64 builds; --with-deps pulls the OS libraries it needs.
RUN python -m playwright install --with-deps chromium

# Copy source only (see .dockerignore: no .env, sessions/, data/, logs/).
COPY auth/ ./auth/
COPY backtest/ ./backtest/
COPY config/ ./config/
COPY core/ ./core/
COPY database/ ./database/
COPY engine/ ./engine/
COPY strategies/ ./strategies/
COPY tg_bot/ ./tg_bot/
COPY tests/ ./tests/
COPY main.py run.py ./

RUN mkdir -p data sessions logs

# Live mode when .env holds QUOTEX_EMAIL/PASSWORD, mock mode otherwise
# (run.py auto-detects). No default CMD args: configure via environment.
CMD ["python", "run.py"]
