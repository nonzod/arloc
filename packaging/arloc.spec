# -*- mode: python ; coding: utf-8 -*-
# Build: uv run pyinstaller packaging/arloc.spec --noconfirm
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(ROOT / "arloc" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "arloc" / "ui" / "style.qss"), "arloc/ui"),
        (str(ROOT / "templates"), "templates"),
    ],
    hiddenimports=["keyring.backends", "openpyxl"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Arloc",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Arloc")
import sys as _sys
if _sys.platform == "darwin":
    app = BUNDLE(coll, name="Arloc.app", bundle_identifier="it.tourtools.arloc")
