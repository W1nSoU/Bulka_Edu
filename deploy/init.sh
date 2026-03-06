#!/usr/bin/env bash
# deploy/init.sh — First-time deployment setup
# Run this ONCE on the server before docker-compose up.
# Usage: bash deploy/init.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$SCRIPT_DIR/data"

echo "════════════════════════════════════════════════"
echo "  Bulka Edu — Deployment Initialisation"
echo "════════════════════════════════════════════════"

# ── 1. Copy .env ──────────────────────────────────────────────────────────────
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    cp "$PROJECT_ROOT/.env.docker.example" "$PROJECT_ROOT/.env"
    echo "✅ .env created — EDIT IT NOW before continuing!"
    echo "   nano $PROJECT_ROOT/.env"
    exit 0
fi

# ── 2. Verify HARDWARE_ID_OVERRIDE is set ────────────────────────────────────
source "$PROJECT_ROOT/.env"
if [ -z "${HARDWARE_ID_OVERRIDE:-}" ]; then
    HW=$(python3 -c "import secrets; print(secrets.token_hex(16))")
    echo ""
    echo "⚠️  HARDWARE_ID_OVERRIDE is not set."
    echo "    Generated value (add to .env):"
    echo ""
    echo "    HARDWARE_ID_OVERRIDE=$HW"
    echo ""
    exit 1
fi

# ── 3. Create data directory for secret files ─────────────────────────────────
mkdir -p "$DATA_DIR"
chmod 700 "$DATA_DIR"

# ── 4. Activate license key ───────────────────────────────────────────────────
if [ ! -f "$DATA_DIR/.license" ]; then
    echo ""
    read -rp "Enter license key (XXXX-XXXX-XXXX-XXXX): " LICENSE_KEY
    if [ -z "$LICENSE_KEY" ]; then
        echo "❌ License key cannot be empty."
        exit 1
    fi
    # Activate in a temp container that has access to DATA_DIR
    docker run --rm \
        -v "$DATA_DIR:/app/security_functions" \
        -e SECURITY_DATA_DIR=/app/security_functions \
        -e HARDWARE_ID_OVERRIDE="$HARDWARE_ID_OVERRIDE" \
        bulka-edu:latest \
        python3 -m security_functions.key_store activate "$LICENSE_KEY"
    echo "✅ License activated → $DATA_DIR/.license"
else
    echo "✅ License file already present."
fi

# ── 5. Copy _hashes.py to security_data (for _p4 integrity check) ────────────
cp "$PROJECT_ROOT/security_functions/_hashes.py"     "$DATA_DIR/_hashes.py"
cp "$PROJECT_ROOT/security_functions/_integrity.py"  "$DATA_DIR/_integrity.py"

# ── 6. Build Docker image ─────────────────────────────────────────────────────
echo ""
echo "🔨 Building Docker image..."
docker build -t bulka-edu:latest "$PROJECT_ROOT"
echo "✅ Image built."

# ── 7. Run seal to update .chksum with container paths ───────────────────────
docker run --rm \
    -v "$DATA_DIR:/app/security_functions" \
    -e SECURITY_DATA_DIR=/app/security_functions \
    -e HARDWARE_ID_OVERRIDE="$HARDWARE_ID_OVERRIDE" \
    bulka-edu:latest \
    python3 security_functions/_seal.py
echo "✅ .chksum updated."

echo ""
echo "════════════════════════════════════════════════"
echo "  Deployment ready! Start with:"
echo "  docker-compose up -d"
echo "════════════════════════════════════════════════"
