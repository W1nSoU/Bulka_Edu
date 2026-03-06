# ─────────────────────────────────────────────────────────────────────────────
# Bulka Edu Bot — Dockerfile
# Supports: Docker standalone, docker-compose, PyInstaller pre-build
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# System deps for cryptography, psutil, faiss
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ libffi-dev libssl-dev \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-server.txt* ./
RUN pip install --upgrade pip \
 && pip install --prefix=/install --no-warn-script-location -r requirements.txt \
 && { [ -f requirements-server.txt ] && pip install --prefix=/install --no-warn-script-location -r requirements-server.txt || true; }


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="Bulka Edu" \
      description="Bulka Edu Telegram Bot with license enforcement"

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
COPY security_functions/ ./security_functions/
COPY private_server/     ./private_server/
COPY main.py .

# ── Strip secrets from the image — they come from volumes at runtime ──────────
RUN rm -f security_functions/.license \
          security_functions/.salt \
          security_functions/.master_secret \
          security_functions/.chksum \
          security_functions/master_keys.db \
          security_functions/guard.log \
          private_server/.env \
          private_server/activation_log.db

# ── Security data directory (VOLUME — never bake into image) ─────────────────
RUN mkdir -p /app/security_data /app/private_server/data \
 && chmod 700 /app/security_data

# ── ENV defaults (override in docker-compose or --env-file) ──────────────────
# Telegram bot
ENV BOT_API_TOKEN=""
ENV DEV_CHAT_ID=""
ENV MAIN_DEVELOPER_ID=""
ENV GROQ_API_KEY=""
ENV DAYS_TOTAL=5
ENV DEBUG=false
ENV LOG_TO_FILE=true

# License / verification
ENV LICENSE_VERIFY_URL="https://your-server.com:8443/api/verify"
ENV LICENSE_TIMEOUT=10
ENV LICENSE_SSL_VERIFY=true
# Override hardware fingerprint for stable Docker identity
# Set to a secret constant string — same value across all restarts
ENV HARDWARE_ID_OVERRIDE=""

# Security data path (used by _paths.py)
ENV SECURITY_DATA_DIR="/app/security_data"

# Server-side (used when running private_server inside this container)
ENV API_SECRET_KEY=""
ENV HOST=0.0.0.0
ENV PORT=8443

# Telegram master-bot
ENV MASTER_BOT_TOKEN=""
ENV MASTER_CHAT_ID=""
ENV MASTER_ALLOWED_IDS=""
ENV NOTIFY_ON_OK_FIRST=true
ENV NOTIFY_ON_OK_REPEAT=false

# ── Volume declarations ───────────────────────────────────────────────────────
# Mount these from host to persist license state across restarts.
# See docker-compose.yml for named-volume definitions.
VOLUME ["/app/security_data"]
VOLUME ["/app/private_server/data"]

# ── Healthcheck ───────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python3 -c "import httpx; httpx.get('http://localhost:8443/api/health', timeout=5)" \
    || exit 1

# ── Default entrypoint: edu bot ───────────────────────────────────────────────
CMD ["python3", "main.py"]
