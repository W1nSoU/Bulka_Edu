"""
_seal.py — Run this after ANY change to security_functions/*.py files.
Writes encoded SHA-256 hashes into _hashes.py (never touches _integrity.py).
Also records _integrity.py and _hashes.py into .chksum for _p4() checks.
Usage:  python3 security_functions/_seal.py
"""

import hashlib
import re
import sys
from pathlib import Path

BASE = Path(__file__).parent

_KA = bytes([0x42, 0x55, 0x4C, 0x4B])
_KB = bytes([0x41, 0x5F, 0x45, 0x44])


def _xk(i: int) -> int:
    return _KA[i % 4] ^ _KB[i % 4]


def _enc(h: str) -> list:
    return [b ^ _xk(i) for i, b in enumerate(bytes.fromhex(h))]


def _dec(v: list) -> str:
    return bytes([b ^ _xk(i) for i, b in enumerate(v)]).hex()


def seal() -> None:
    hashes_file  = BASE / "_hashes.py"
    integrity_file = BASE / "_integrity.py"

    if not hashes_file.exists() or not integrity_file.exists():
        print("❌ _hashes.py or _integrity.py not found.", file=sys.stderr)
        sys.exit(1)

    # ── Hash all .py files except _seal.py, _hashes.py, _integrity.py ─────────
    py_files = sorted(
        f for f in BASE.glob("*.py")
        if f.name not in ("_seal.py", "_hashes.py", "_integrity.py")
    )

    sm: dict = {}
    print("Hashing source files:")
    for f in py_files:
        h = hashlib.sha256(f.read_bytes()).hexdigest()
        sm[f.name] = _enc(h)
        print(f"  {f.name}: {h[:24]}…")

    # ── Write _SM to _hashes.py ───────────────────────────────────────────────
    lines = ["_SM: Dict[str, List[int]] = {\n"]
    for name, enc in sm.items():
        lines.append(f'    "{name}": {enc},\n')
    lines.append("}")
    new_block = "".join(lines)

    content = hashes_file.read_text(encoding="utf-8")
    pattern = r'_SM: Dict\[str, List\[int\]\] = \{[^}]*\}'
    if not re.search(pattern, content, flags=re.DOTALL):
        print("⚠️  _SM pattern not matched in _hashes.py", file=sys.stderr)
        sys.exit(1)
    updated = re.sub(pattern, new_block, content, flags=re.DOTALL)
    hashes_file.write_text(updated, encoding="utf-8")
    if updated == content:
        print(f"\n✅ _hashes.py already up-to-date ({len(sm)} file hashes).")
    else:
        print(f"\n✅ _hashes.py updated with {len(sm)} file hashes.")

    # ── Round-trip verification ───────────────────────────────────────────────
    print("\nVerifying round-trips:")
    for f in py_files:
        h_orig = hashlib.sha256(f.read_bytes()).hexdigest()
        assert _dec(sm[f.name]) == h_orig, f"Decode mismatch: {f.name}"
        print(f"  ✅ {f.name}")

    # ── Record _integrity.py + _hashes.py into .chksum ────────────────────────
    chksum = BASE / ".chksum"
    existing: dict = {}
    if chksum.exists():
        for line in chksum.read_text(encoding="utf-8").splitlines():
            if ":" in line:
                n, rest = line.split(":", 1)
                existing[n.strip()] = rest.strip()

    for name, path in [("_integrity.py", integrity_file),
                        ("_hashes.py",    hashes_file)]:
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        existing[name] = str(_enc(h))
        print(f"  ✅ {name}: {h[:24]}… → .chksum")

    chksum.write_text(
        "\n".join(f"{k}:{v}" for k, v in existing.items()) + "\n",
        encoding="utf-8",
    )
    try:
        chksum.chmod(0o600)
    except OSError:
        pass
    print(f"\n✅ .chksum updated ({len(existing)} entries).")
    print("\nDone. Distribute _hashes.py + .chksum with the deployment.")


if __name__ == "__main__":
    seal()
