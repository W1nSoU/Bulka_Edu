"""
Block 1.2 — Hardware ID Collection
Collects MAC, CPU, HDD identifiers → combines into SHA-256 hardware_id.
Cross-platform: macOS, Linux, Windows.
Docker: set HARDWARE_ID_OVERRIDE env-var for a stable container identity.

Hardware binding is managed SERVER-SIDE (private_server/db.py).
This module only collects and hashes the hardware fingerprint.
"""

import hashlib
import os
import platform
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Optional, Dict

# ── hardware collectors ───────────────────────────────────────────────────────

def _get_mac() -> str:
    """Return the primary MAC address as a hex string."""
    return hex(uuid.getnode())


def _get_cpu_id() -> str:
    """Return a stable CPU identifier string."""
    system = platform.system()
    try:
        if system == "Darwin":
            out = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).decode().strip()
            return out or platform.processor()

        elif system == "Linux":
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
            return platform.processor()

        elif system == "Windows":
            out = subprocess.check_output(
                ["wmic", "cpu", "get", "ProcessorId"],
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).decode()
            lines = [l.strip() for l in out.splitlines() if l.strip()]
            return lines[1] if len(lines) > 1 else platform.processor()

    except Exception:
        pass
    return platform.processor() or "unknown_cpu"


def _get_disk_id() -> str:
    """Return a stable disk/volume identifier."""
    system = platform.system()
    try:
        if system == "Darwin":
            out = subprocess.check_output(
                ["diskutil", "info", "/"],
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).decode()
            for line in out.splitlines():
                if "Volume UUID" in line or "Disk / Partition UUID" in line:
                    return line.split(":", 1)[1].strip()

        elif system == "Linux":
            # Try blkid for root partition UUID
            out = subprocess.check_output(
                ["blkid", "-s", "UUID", "-o", "value"],
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).decode()
            first = out.strip().splitlines()
            return first[0] if first else "unknown_disk"

        elif system == "Windows":
            out = subprocess.check_output(
                ["wmic", "diskdrive", "get", "SerialNumber"],
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).decode()
            lines = [l.strip() for l in out.splitlines() if l.strip()]
            return lines[1] if len(lines) > 1 else "unknown_disk"

    except Exception:
        pass
    return "unknown_disk"


# ── hardware_id builder ───────────────────────────────────────────────────────

def collect_hardware_components() -> Dict[str, str]:
    """Return a dict of raw hardware identifiers."""
    return {
        "mac":  _get_mac(),
        "cpu":  _get_cpu_id(),
        "disk": _get_disk_id(),
    }


def build_hardware_id(components: Optional[Dict[str, str]] = None) -> str:
    """
    Combine MAC + CPU + DISK into a single SHA-256 hardware_id string.
    Docker/CI: if HARDWARE_ID_OVERRIDE is set, it is used as-is (allows
    stable container identity without physical hardware probing).
    """
    override = os.getenv("HARDWARE_ID_OVERRIDE", "").strip()
    if override:
        return hashlib.sha256(override.encode()).hexdigest()

    if components is None:
        components = collect_hardware_components()
    raw = f"{components['mac']}|{components['cpu']}|{components['disk']}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_components(c: Dict[str, str], hwid: str) -> None:
    print("\n" + "=" * 60)
    print("  🔩  Hardware Profile — Block 1.2")
    print("=" * 60)
    print(f"  MAC       : {c['mac']}")
    print(f"  CPU       : {c['cpu']}")
    print(f"  DISK      : {c['disk']}")
    print(f"  hardware_id (SHA-256):")
    print(f"    {hwid}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Bulka Edu — Hardware ID (Block 1.2)"
    )
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("info", help="Show this machine's hardware_id")

    args = parser.parse_args()

    if args.cmd == "info":
        c = collect_hardware_components()
        hwid = build_hardware_id(c)
        _print_components(c, hwid)
    else:
        parser.print_help()
