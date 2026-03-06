"""
security_functions/key_store.py
Client-side encrypted license key storage.

The license key is encrypted with an AES-256-GCM key DERIVED from the
machine's own hardware_id (PBKDF2-HMAC-SHA256).
This means the .license file is hardware-locked: copying it to another
machine will fail to decrypt even without the server check.
"""

import os
import base64
import secrets
from pathlib import Path
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ── paths (Docker/PyInstaller aware) ─────────────────────────────────────────
from security_functions._paths import data_base as _data_base
BASE_DIR      = _data_base()
LICENSE_FILE  = BASE_DIR / ".license"
SALT_FILE     = BASE_DIR / ".salt"


# ── key derivation ────────────────────────────────────────────────────────────

def _derive_aes_key(hardware_id: str, salt: bytes) -> bytes:
    """Derive a 256-bit AES key from hardware_id using PBKDF2-HMAC-SHA256."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=260_000,
    )
    return kdf.derive(hardware_id.encode())


def _load_or_create_salt() -> bytes:
    # scattered integrity probe — looks like routine initialisation
    try:
        (lambda _m: _m._p1())(
            __import__("security_functions._integrity", fromlist=["_p1"])
        )
    except SystemExit:
        raise
    except Exception:
        pass
    if SALT_FILE.exists():
        return base64.urlsafe_b64decode(SALT_FILE.read_bytes())
    salt = secrets.token_bytes(32)
    SALT_FILE.write_bytes(base64.urlsafe_b64encode(salt))
    SALT_FILE.chmod(0o600)
    return salt


# ── public API ────────────────────────────────────────────────────────────────

def save_license_key(license_key: str) -> None:
    """
    Encrypt and persist the license key, bound to this machine's hardware_id.
    Call this once when installing the bot on a new server.
    """
    from security_functions.hardware_id import build_hardware_id

    hardware_id = build_hardware_id()
    salt        = _load_or_create_salt()
    aes_key     = _derive_aes_key(hardware_id, salt)

    aesgcm = AESGCM(aes_key)
    nonce  = secrets.token_bytes(12)
    ct     = aesgcm.encrypt(nonce, license_key.strip().encode(), None)

    LICENSE_FILE.write_bytes(base64.urlsafe_b64encode(nonce + ct))
    LICENSE_FILE.chmod(0o600)

    # snapshot mutable security files for later integrity checks
    try:
        _ig = __import__("security_functions._integrity", fromlist=["_dm_record"])
        _ig._dm_record([".license", ".salt", ".master_secret"])
    except Exception:
        pass


def load_license_key() -> str:
    """
    Decrypt and return the stored license key using this machine's hardware_id.
    Raises FileNotFoundError if not yet activated.
    Raises ValueError on decryption failure (wrong hardware or tampered file).
    """
    if not LICENSE_FILE.exists():
        raise FileNotFoundError(
            "No license key found. Run: "
            "python -m security_functions.key_store activate <KEY>"
        )

    from security_functions.hardware_id import build_hardware_id

    hardware_id = build_hardware_id()
    salt        = _load_or_create_salt()
    aes_key     = _derive_aes_key(hardware_id, salt)

    raw   = base64.urlsafe_b64decode(LICENSE_FILE.read_bytes())
    nonce = raw[:12]
    ct    = raw[12:]

    try:
        aesgcm  = AESGCM(aes_key)
        plaintext = aesgcm.decrypt(nonce, ct, None)
        return plaintext.decode()
    except Exception:
        raise ValueError(
            "License key decryption failed. "
            "This may indicate a hardware change or a tampered license file."
        )


def is_activated() -> bool:
    """Return True if a license key file exists on this machine."""
    return LICENSE_FILE.exists()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Bulka Edu — License Key Store (Block 1.4)"
    )
    sub = parser.add_subparsers(dest="cmd")

    act = sub.add_parser("activate", help="Encrypt and store a license key on this machine")
    act.add_argument("key", help="License key in XXXX-XXXX-XXXX-XXXX format")

    sub.add_parser("show", help="Decrypt and display the stored license key")
    sub.add_parser("status", help="Check whether a license key is stored")

    args = parser.parse_args()

    if args.cmd == "activate":
        save_license_key(args.key)
        print(f"✅ License key stored and encrypted (hardware-locked).")
        print(f"   File: {LICENSE_FILE}")
    elif args.cmd == "show":
        try:
            k = load_license_key()
            print(f"🔑 License key: {k}")
        except Exception as e:
            print(f"❌ {e}")
    elif args.cmd == "status":
        if is_activated():
            print(f"✅ License file present: {LICENSE_FILE}")
        else:
            print("⚠️  No license key found on this machine.")
    else:
        parser.print_help()
