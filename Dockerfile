# ─────────────────────────────────────────────────────────────────────────────
# Bulka Edu Bot — Dockerfile
# Supports: Docker standalone, docker-compose
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ libffi-dev libssl-dev \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip \
 && pip install --prefix=/install --no-warn-script-location -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="Bulka Edu" \
      description="Bulka Edu Telegram Bot"

# Runtime system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        libssl3 libffi8 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Installed packages from builder
COPY --from=builder /install /usr/local

# ── Project source ────────────────────────────────────────────────────────────
COPY bot/           ./bot/
COPY database/      ./database/
COPY days/          ./days/
COPY tools/         ./tools/
COPY img/           ./img/
COPY main.py .

# ── ENV defaults (override in docker-compose or --env-file) ──────────────────
ENV BOT_API_TOKEN=""
ENV DEV_CHAT_ID=""
ENV MAIN_DEVELOPER_ID=""
ENV GROQ_API_KEY=""
ENV DAYS_TOTAL=5
ENV DEBUG=false
ENV LOG_TO_FILE=true

# ── Default entrypoint: edu bot ───────────────────────────────────────────────
CMD ["python3", "main.py"]
