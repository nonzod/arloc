# -*- mode: python ; coding: utf-8 -*-
# Build: uv run pyinstaller packaging/arloc.spec --noconfirm
import sys as _sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(ROOT / "arloc" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "arloc" / "ui" / "style.qss"), "arloc/ui"),
        (str(ROOT / "arloc" / "ui" / "resources"), "arloc/ui/resources"),
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
    icon=str(ROOT / "packaging" / ("arloc.ico" if _sys.platform == "win32" else "arloc.png")),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Arloc")
if _sys.platform == "darwin":
    app = BUNDLE(coll, name="Arloc.app", icon=str(ROOT / "packaging" / "arloc.png"),
                 bundle_identifier="it.tourtools.arloc")
