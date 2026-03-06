"""Internal module."""

import os
import random
import secrets
import sys
import time
import logging
from pathlib import Path
from typing import List

def _resolve_base() -> Path:
    override = os.getenv("SECURITY_DATA_DIR", "").strip()
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "security_functions"
    return Path(__file__).parent

_B = _resolve_base()
_L = _B / "guard.log"

_il = logging.getLogger("_sd")
_il.setLevel(logging.DEBUG)
_il.propagate = False
if not _il.handlers:
    _fh = logging.FileHandler(_L, encoding="utf-8")
    _fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ"
    ))
    _il.addHandler(_fh)


# ── primitive ops ─────────────────────────────────────────────────────────────

def _fsync_write(path: Path, data: bytes) -> None:
    with open(path, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


def _multi_wipe(path: Path, passes: int = 3) -> None:
    """Multi-pass random overwrite — makes sector recovery impractical."""
    try:
        sz = max(path.stat().st_size if path.exists() else 512, 512)
        for _ in range(passes):
            _fsync_write(path, secrets.token_bytes(sz))
            time.sleep(random.uniform(0.001, 0.005))
    except Exception:
        pass


def _corrupt_module(path: Path) -> None:
    """
    Overwrite a source file with an irreversible mangled payload:
      Pass 1 — shuffle lines, keep ⌊1/3⌋, XOR-interleave with random noise.
      Pass 2 — overwrite remaining content with pure random bytes.
      Pass 3 — truncate to randomised smaller size and wipe again.
    """
    try:
        if not path.exists():
            return
        original = path.read_bytes()
        sz = len(original)

        lines = original.split(b"\n")
        random.shuffle(lines)
        kept   = lines[: max(1, len(lines) // 3)]
        partial = b"\n".join(kept)

        noise   = bytearray(secrets.token_bytes(sz))
        partial_b = bytearray(partial.ljust(sz, b"\x00"))

        # XOR every 3rd byte with partial content
        for i in range(0, sz, 3):
            noise[i] = noise[i] ^ partial_b[i % len(partial_b)]

        _fsync_write(path, bytes(noise))

        # Pass 2 — pure random overwrite
        _fsync_write(path, secrets.token_bytes(sz))

        # Pass 3 — truncate + wipe to confuse carving tools
        trunc = random.randint(sz // 4, sz // 2)
        _fsync_write(path, secrets.token_bytes(trunc))
    except Exception:
        pass


def _erase(path: Path) -> None:
    """Wipe then unlink."""
    _multi_wipe(path, passes=3)
    try:
        path.unlink(missing_ok=True)
    except Exception:
        try:
            path.unlink()
        except Exception:
            pass


def _blind_dir(p: Path) -> None:
    """Rename the package directory to a hidden random name."""
    try:
        new = p.parent / f".{secrets.token_hex(6)}"
        p.rename(new)
    except Exception:
        pass


# ── destruction sequence ──────────────────────────────────────────────────────

def _phase_a(py_files: List[Path]) -> None:
    """Corrupt first half of source files."""
    half = py_files[: max(1, len(py_files) // 2)]
    for p in half:
        _il.debug("ph_a %s", p.name)
        _corrupt_module(p)


def _phase_b(py_files: List[Path]) -> None:
    """Erase second half of source files."""
    rest = py_files[max(1, len(py_files) // 2):]
    for p in rest:
        _il.debug("ph_b %s", p.name)
        _erase(p)


def _phase_c() -> None:
    """Wipe credential and binding files."""
    targets = [
        _B / ".license",
        _B / ".salt",
        _B / ".master_secret",
        _B / ".chksum",
        _B / "master_keys.db",
        _B / "activation_log.db",
    ]
    random.shuffle(targets)
    for p in targets:
        if p.exists():
            _il.debug("ph_c %s", p.name)
            _multi_wipe(p, passes=4)


def _phase_d() -> None:
    """Blind the package directory (last resort)."""
    _il.debug("ph_d dir_blind")
    _blind_dir(_B)


# ── public entry point ────────────────────────────────────────────────────────

def trigger_self_destruct(reason: str = "") -> None:
    """
    Executes all destruction phases in randomised order.
    Called automatically by _die() and _block() on any integrity failure.
    Exits the process unconditionally after corruption.
    """
    _il.error("SD %s", reason[:80])

    py_files: List[Path] = list(_B.glob("*.py"))
    random.shuffle(py_files)

    # randomise phase execution order (A/B must precede D)
    phase_order = [_phase_a, _phase_b, _phase_c]
    random.shuffle(phase_order)

    for phase in phase_order:
        try:
            if phase in (_phase_a, _phase_b):
                phase(py_files)
            else:
                phase()
        except SystemExit:
            raise
        except Exception:
            pass

    # directory blind always runs last
    _phase_d()

    _il.error("SD_DONE")
    sys.exit(1)
