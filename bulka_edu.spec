# -*- mode: python ; coding: utf-8 -*-
# ─────────────────────────────────────────────────────────────────────────────
# bulka_edu.spec — PyInstaller build spec
#
# Build:
#   pip install pyinstaller
#   pyinstaller bulka_edu.spec
#
# Output: dist/bulka_edu   (one-dir mode, preserves relative paths)
# ─────────────────────────────────────────────────────────────────────────────

import sys
from pathlib import Path

ROOT = Path(".").resolve()

# ── Hidden imports ────────────────────────────────────────────────────────────
_hidden = [
    # aiogram internals referenced dynamically
    "aiogram.fsm.storage.memory",
    "aiogram.client.default",
    # standard library used via importlib
    "importlib.util",
    "importlib.machinery",
    # DB
    "aiosqlite",
    "sqlite3",
]

# ── Data files to bundle (read-only code assets) ─────────────────────────────
_datas = [
    # Bot assets
    (str(ROOT / "days"),   "days"),
    (str(ROOT / "img"),    "img"),
    (str(ROOT / "data"),   "data"),
]

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=_datas,
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["test_*", "_pytest", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# ── One-dir executable ────────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="bulka_edu",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="bulka_edu",
)
