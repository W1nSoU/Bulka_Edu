"""
Block 1.1 — Master Key Generation
Generates, names, and securely stores Master Keys (AES-256).
All keys reside on the developer's server only.
"""

import os
import secrets
import string
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
import base64
from typing import Optional, List

# ── paths (Docker/PyInstaller aware) ─────────────────────────────────────────
from security_functions._paths import data_base as _data_base
BASE_DIR    = _data_base()
DB_PATH     = BASE_DIR / "master_keys.db"
SECRET_FILE = BASE_DIR / ".master_secret"

# ── key alphabet ─────────────────────────────────────────────────────────────
ALPHABET = string.ascii_uppercase + string.digits  # extend with specials if needed

# ── encryption helpers ────────────────────────────────────────────────────────

def _load_or_create_secret() -> bytes:
    """Load or generate the AES-256 encryption secret for the key store."""
    if SECRET_FILE.exists():
        raw = SECRET_FILE.read_bytes()
        return base64.urlsafe_b64decode(raw)
    # Generate a new 256-bit secret
    secret = secrets.token_bytes(32)
    SECRET_FILE.write_bytes(base64.urlsafe_b64encode(secret))
    SECRET_FILE.chmod(0o600)  # owner-read-only
    return secret


def _encrypt(data: str, secret: bytes) -> str:
    """AES-256-GCM encrypt a string; returns base64-encoded ciphertext."""
    aesgcm = AESGCM(secret)
    nonce  = secrets.token_bytes(12)
    ct     = aesgcm.encrypt(nonce, data.encode(), None)
    return base64.urlsafe_b64encode(nonce + ct).decode()


def _decrypt(token: str, secret: bytes) -> str:
    """AES-256-GCM decrypt a base64-encoded ciphertext."""
    raw   = base64.urlsafe_b64decode(token.encode())
    nonce = raw[:12]
    ct    = raw[12:]
    aesgcm = AESGCM(secret)
    return aesgcm.decrypt(nonce, ct, None).decode()


# ── database ──────────────────────────────────────────────────────────────────

def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS master_keys (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL UNIQUE,
            key_enc     TEXT    NOT NULL,   -- AES-256-GCM encrypted key value
            created_at  TEXT    NOT NULL,
            is_active   INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.commit()


# ── public API ────────────────────────────────────────────────────────────────

def generate_master_key(name: str, include_specials: bool = False) -> dict:
    """
    Generate a 16-character Master Key, name it, and persist it encrypted.

    Args:
        name:             Human-readable label (company / server / purpose).
        include_specials: If True, adds special chars to the alphabet.

    Returns:
        dict with 'name', 'key', 'created_at'.
    """
    name = name.strip()
    if not name:
        raise ValueError("Key name must not be empty.")

    alphabet = ALPHABET
    if include_specials:
        alphabet += "!@#$%^&*"

    raw_key = "".join(secrets.choice(alphabet) for _ in range(16))
    # Format as XXXX-XXXX-XXXX-XXXX for readability
    formatted = "-".join(raw_key[i:i+4] for i in range(0, 16, 4))

    secret     = _load_or_create_secret()
    key_enc    = _encrypt(formatted, secret)
    created_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    with sqlite3.connect(DB_PATH) as conn:
        _init_db(conn)
        try:
            conn.execute(
                "INSERT INTO master_keys (name, key_enc, created_at) VALUES (?, ?, ?)",
                (name, key_enc, created_at),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError(f"A Master Key with name '{name}' already exists.")

    return {"name": name, "key": formatted, "created_at": created_at}


def list_master_keys() -> List[dict]:
    """Return all stored Master Keys (decrypted) sorted by creation date."""
    if not DB_PATH.exists():
        return []

    secret = _load_or_create_secret()
    with sqlite3.connect(DB_PATH) as conn:
        _init_db(conn)
        rows = conn.execute(
            "SELECT id, name, key_enc, created_at, is_active FROM master_keys ORDER BY id"
        ).fetchall()

    result = []
    for row_id, name, key_enc, created_at, is_active in rows:
        try:
            key = _decrypt(key_enc, secret)
        except Exception:
            key = "<decryption error>"
        result.append({
            "id": row_id,
            "name": name,
            "key": key,
            "created_at": created_at,
            "is_active": bool(is_active),
        })
    return result


def get_master_key(name: str) -> Optional[dict]:
    """Retrieve a single Master Key by name."""
    for entry in list_master_keys():
        if entry["name"] == name:
            return entry
    return None


def deactivate_master_key(name: str) -> bool:
    """Mark a Master Key as inactive (soft-delete)."""
    if not DB_PATH.exists():
        return False
    with sqlite3.connect(DB_PATH) as conn:
        _init_db(conn)
        cur = conn.execute(
            "UPDATE master_keys SET is_active = 0 WHERE name = ?", (name,)
        )
        conn.commit()
    return cur.rowcount > 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_report(entry: dict) -> None:
    print("\n" + "=" * 50)
    print("  ✅  Master Key Generated — Block 1.1")
    print("=" * 50)
    print(f"  Name       : {entry['name']}")
    print(f"  Key        : {entry['key']}")
    print(f"  Created    : {entry['created_at']}")
    print(f"  Storage    : {DB_PATH}")
    print(f"  Encryption : AES-256-GCM")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Bulka Edu — Master Key Generator (Block 1.1)"
    )
    sub = parser.add_subparsers(dest="cmd")

    gen = sub.add_parser("generate", help="Generate a new Master Key")
    gen.add_argument("name", help="Unique label for this key (e.g. 'CompanyA')")
    gen.add_argument("--specials", action="store_true",
                     help="Include special characters in the key")

    sub.add_parser("list", help="List all stored Master Keys")

    deact = sub.add_parser("deactivate", help="Deactivate a key by name")
    deact.add_argument("name")

    args = parser.parse_args()

    if args.cmd == "generate":
        entry = generate_master_key(args.name, include_specials=args.specials)
        _print_report(entry)

    elif args.cmd == "list":
        keys = list_master_keys()
        if not keys:
            print("No Master Keys found.")
        else:
            print(f"\n{'ID':<4} {'Name':<20} {'Key':<19} {'Created':<22} {'Active'}")
            print("-" * 80)
            for k in keys:
                active = "✅" if k["is_active"] else "❌"
                print(f"{k['id']:<4} {k['name']:<20} {k['key']:<19} {k['created_at']:<22} {active}")

    elif args.cmd == "deactivate":
        ok = deactivate_master_key(args.name)
        print(f"{'Deactivated' if ok else 'Not found'}: {args.name}")

    else:
        parser.print_help()
