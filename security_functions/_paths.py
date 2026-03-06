"""
Path resolver for security data files.
Supports three modes:
  1. Normal Python   — files in security_functions/
  2. Docker          — files in SECURITY_DATA_DIR env (e.g. /app/security_data)
  3. PyInstaller     — files adjacent to the frozen executable
"""

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def security_base() -> Path:
    """Return the base dir for security source/logic files (_integrity.py etc.)."""
    if is_frozen():
        return Path(sys._MEIPASS) / "security_functions"  # type: ignore[attr-defined]
    return Path(__file__).parent


def data_base() -> Path:
    """
    Return the base dir for MUTABLE security data files
    (.license, .salt, .master_secret, .chksum, master_keys.db).
    Priority: SECURITY_DATA_DIR env → exe dir (frozen) → source dir.
    """
    override = os.getenv("SECURITY_DATA_DIR", "").strip()
    if override:
        p = Path(override)
        p.mkdir(parents=True, exist_ok=True)
        return p
    if is_frozen():
        p = Path(sys.executable).parent / ".security"
        p.mkdir(parents=True, exist_ok=True)
        return p
    return Path(__file__).parent
