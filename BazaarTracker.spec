# -*- mode: python ; coding: utf-8 -*-
#
# Build with:  pyinstaller BazaarTracker.spec
# Output in:   dist/BazaarTracker/BazaarTracker.exe
#
# Tesseract is bundled automatically if third_party/tesseract/tesseract.exe
# exists at build time (see README's "Building the .exe" section for where
# to get it) -- otherwise the build still works, it just falls back to
# whatever Tesseract is on the target machine's PATH at runtime.

from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

project_root = Path.cwd()
tesseract_dir = project_root / "third_party" / "tesseract"

hiddenimports = [
    "requests",
    "urllib3",
    "charset_normalizer",
    "certifi",
    "idna",
    "pytesseract",
    "PIL",
    "cv2",
    "numpy",
    "mss",
    "flask",
    "jinja2",
    "dotenv",
    "win32gui",
    "win32con",
    "win32api",
]

datas = [
    ("tracker/templates", "tracker/templates"),
    ("tracker/static", "tracker/static"),
]
datas += collect_data_files("certifi")

binaries = []

if tesseract_dir.exists():
    exe_path = tesseract_dir / "tesseract.exe"
    if exe_path.exists():
        binaries.append((str(exe_path), "third_party/tesseract"))
    for dll in tesseract_dir.glob("*.dll"):
        binaries.append((str(dll), "third_party/tesseract"))

    tessdata_dir = tesseract_dir / "tessdata"
    if tessdata_dir.exists():
        for traineddata in tessdata_dir.glob("*"):
            datas.append((str(traineddata), "third_party/tesseract/tessdata"))

a = Analysis(
    ["run.py"],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "test",
        "matplotlib",
        "pandas",
        "scipy",
        "IPython",
        "jupyter",
        "cv2.qt",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BazaarTracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="BazaarTracker",
)
