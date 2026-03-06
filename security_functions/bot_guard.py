"""
security_functions/bot_guard.py  — Block 1.4
Bot startup guard: verifies license key + hardware before the bot runs.
Also provides start_periodic_recheck() for ongoing license validation.

Call check_or_die() as the VERY FIRST thing in main.py.
Add start_periodic_recheck(scheduler) after bot starts to keep checking.

Policy:
  - No license file         → BLOCK + exit  (завжди)
  - Decryption error        → BLOCK + self-destruct  (завжди)
  - Server returns BLOCK    → BLOCK + exit  (завжди)
  - Server returns REVOKED  → BLOCK + self-destruct  (завжди)
  - Server unreachable      → WARN + continue  (fail-open: сервер міг впасти)
  - Server returns OK       → proceed silently

При недоступності сервера:
  - Бот запускається / продовжує роботу
  - Повторні спроби кожні 10 хвилин поки сервер не відповість
  - Як тільки відповідь отримано — виконуємо дії (OK/BLOCK/REVOKED)
"""

import os
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# ── config (read from .env) ───────────────────────────────────────────────────
VERIFY_URL: str = os.getenv(
    "LICENSE_VERIFY_URL", "http://127.0.0.1:8443/api/verify"
)
REQUEST_TIMEOUT: float = float(os.getenv("LICENSE_TIMEOUT", "10"))
MAX_RETRIES: int = 1       # one retry on network error

# ── guard log (local file, rotated externally) ────────────────────────────────
LOG_PATH = Path(__file__).parent / "guard.log"

logging.basicConfig(level=logging.WARNING)
_log = logging.getLogger("bot_guard")

_file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                      datefmt="%Y-%m-%dT%H:%M:%SZ")
)
_log.addHandler(_file_handler)
_log.setLevel(logging.DEBUG)


# ── helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _write_block_banner(reason: str) -> None:
    banner = f"""
╔══════════════════════════════════════════════════════════════╗
║          🔒  BULKA EDU — BOT BLOCKED                        ║
╠══════════════════════════════════════════════════════════════╣
║  Reason : {reason:<50} ║
║  Time   : {_now():<50} ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner, file=sys.stderr)


def _block(reason: str, self_destruct: bool = False) -> None:
    """Log the block reason, optionally trigger self-destruct, then terminate."""
    _log.error("BLOCKED — %s", reason)
    _write_block_banner(reason)
    # Auto-detect tamper/hardware events requiring self-destruct
    _sd_triggers = ("integrity", "hardware", "tamper", "mismatch",
                    "decryption failed", "hw_", "revoked")
    should_destruct = self_destruct or any(t in reason.lower() for t in _sd_triggers)
    if should_destruct:
        try:
            (lambda _m: _m.trigger_self_destruct(reason))(
                __import__(
                    "security_functions._destruct",
                    fromlist=["trigger_self_destruct"],
                )
            )
        except SystemExit:
            raise
        except Exception:
            pass
    sys.exit(1)


# ── core verification ─────────────────────────────────────────────────────────

def _do_verify(license_key: str, hardware_id: str) -> dict:
    """
    POST to VERIFY_URL with retries.
    Returns parsed JSON dict or raises an exception.
    """
    payload = {"key": license_key, "hardware_id": hardware_id}

    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = httpx.post(
                VERIFY_URL,
                json=payload,
                timeout=REQUEST_TIMEOUT,
                # verify=True in production; set verify=False only for self-signed
                verify=os.getenv("LICENSE_SSL_VERIFY", "true").lower() != "false",
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            if attempt < MAX_RETRIES:
                _log.warning("Verification request timed out, retrying (%d/%d)…",
                             attempt + 1, MAX_RETRIES)
                continue
            raise
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Server returned HTTP {exc.response.status_code}"
            ) from exc


# ── public entry point ────────────────────────────────────────────────────────

def check_or_die() -> None:
    """
    Run the full license guard.  Call this before any bot logic.

    Flow:
      1. Load license key from encrypted local store
      2. Collect hardware_id from this machine
      3. POST /api/verify → expect {"status": "OK"}
      4. Any deviation → sys.exit(1)
    """
    # scattered integrity probe embedded in unrelated-looking flow
    try:
        getattr(
            __import__("security_functions._integrity", fromlist=["_p2"]), "_p2"
        )()
    except SystemExit:
        raise
    except Exception:
        pass

    # ── 1. Load license key ───────────────────────────────────────────────────
    try:
        from security_functions.key_store import load_license_key
        license_key = load_license_key()
    except FileNotFoundError as exc:
        _block(str(exc))
    except ValueError as exc:
        # Decryption failure = hardware changed locally
        _block(f"License decryption failed: {exc}")
    except Exception as exc:
        _block(f"Unexpected error reading license: {exc}")

    # ── 2. Collect hardware_id ────────────────────────────────────────────────
    try:
        from security_functions.hardware_id import build_hardware_id
        hardware_id = build_hardware_id()
    except Exception as exc:
        _block(f"Cannot collect hardware profile: {exc}")

    _log.info("Starting license check — key=%s… hw=%s…",
              license_key[:9], hardware_id[:16])

    # ── 3. Verify with server ─────────────────────────────────────────────────
    try:
        result = _do_verify(license_key, hardware_id)
    except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError):
        # Server is unreachable — fail-open: bot continues, will retry periodically
        _log.warning(
            "License server unreachable at startup — bot will start anyway. "
            "Will retry every %d min.", int(REQUEST_TIMEOUT)
        )
        print(
            f"⚠️  [{_now()}] License server unreachable — bot starting in offline mode. "
            "Retrying every 10 min.",
            file=sys.stderr,
        )
        return  # ← allow bot to start; periodic check will verify later
    except Exception as exc:
        _log.warning("License check error at startup: %s — continuing offline.", exc)
        return

    # ── 4. Evaluate response ──────────────────────────────────────────────────
    status = result.get("status", "BLOCK")
    reason = result.get("reason") or "No reason provided"

    if status == "OK":
        _log.info("License OK — bot is cleared to start.")
        return  # ← normal execution continues

    # REVOKED = key was deleted by admin → self-destruct
    if status == "REVOKED":
        _block(f"Key revoked by administrator: {reason}", self_destruct=True)

    # Any other non-OK status is treated as BLOCK (no self-destruct)
    _block(f"Server BLOCK: {reason}")



# ── periodic re-verification (running bot) ────────────────────────────────────

async def _periodic_check_task() -> None:
    """
    Async coroutine: re-verify license while the bot is running.
    Called every 10 min by APScheduler.

    Behavior:
      - Server unreachable → log warning, skip this tick, retry next time
      - Server returns OK  → silent continue
      - Server returns BLOCK/REVOKED → shutdown (+ self-destruct if REVOKED)
    """
    import asyncio

    try:
        from security_functions.key_store import load_license_key
        from security_functions.hardware_id import build_hardware_id

        license_key = load_license_key()
        hardware_id = build_hardware_id()
        result = _do_verify(license_key, hardware_id)

    except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError):
        # Server is down — skip this check, retry on next scheduled tick
        _log.warning(
            "Periodic license check: server unreachable — "
            "bot continues, will retry in 10 min."
        )
        return

    except SystemExit:
        raise

    except Exception as exc:
        # Any other error (local file issue etc.) — also retry, don't panic
        _log.warning("Periodic license check error: %s — will retry next tick.", exc)
        return

    # ── Evaluate server response ──────────────────────────────────────────────
    status = result.get("status", "BLOCK")
    reason = result.get("reason") or ""

    if status == "OK":
        _log.debug("Periodic license check OK.")
        return

    if status == "REVOKED":
        _log.error("Periodic check: KEY REVOKED — shutting down.")
        _write_block_banner(f"License revoked: {reason}")
        loop = asyncio.get_event_loop()
        loop.call_soon(lambda: _block(f"License revoked: {reason}", self_destruct=True))
        return

    # BLOCK or anything else → shutdown without self-destruct
    _log.error("Periodic check: BLOCK — %s. Shutting down.", reason)
    loop = asyncio.get_event_loop()
    loop.call_soon(lambda: _block(f"Periodic check failed: {reason}"))


def start_periodic_recheck(scheduler, interval_minutes: int = 10) -> None:
    """
    Register a periodic license re-verification job with APScheduler.
    Call this AFTER the bot starts successfully (after check_or_die()).

    Args:
        scheduler: APScheduler AsyncIOScheduler instance from main.py
        interval_minutes: how often to re-verify (default: 10 min)
    """
    scheduler.add_job(
        _periodic_check_task,
        "interval",
        minutes=interval_minutes,
        id="license_periodic_recheck",
        replace_existing=True,
        jitter=60,   # ±60s jitter to avoid synchronized calls from many bots
    )
    _log.info("Periodic license recheck scheduled every %d min.", interval_minutes)


# ── CLI (useful for testing the guard standalone) ─────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Bulka Edu — Bot Guard (Block 1.4)"
    )
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("check", help="Run the license check (same as bot startup)")

    args = parser.parse_args()

    if args.cmd == "check":
        print("Running license guard…")
        check_or_die()
        print("✅ License OK — bot would start.")
    else:
        parser.print_help()
