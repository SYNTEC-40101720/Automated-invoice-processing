# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the SYNTEC invoice desktop application."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


ROOT = Path(SPECPATH)
BACKEND = ROOT / "backend"
APP_NAME = "SYNTEC-电子票据处理系统"
block_cipher = None

# OCR 级联（RapidOCR/onnxruntime）依赖资源：模型、字典、配置与原生 DLL。
# rapidocr_onnxruntime 自带模型文件随包分发（onnx + ppocr_keys 等）。
_RAPIDOCR_DATAS = collect_data_files("rapidocr_onnxruntime")
_ONNXRUNTIME_BINARIES = collect_dynamic_libs("onnxruntime")
_CV2_BINARIES = collect_dynamic_libs("cv2")


a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(BACKEND)],
    binaries=[
        *_ONNXRUNTIME_BINARIES,
        *_CV2_BINARIES,
    ],
    datas=[
        (str(ROOT / "logo.ico"), "."),
        (str(ROOT / "web" / "dist"), "web/dist"),
        *_RAPIDOCR_DATAS,
    ],
    hiddenimports=[
        "invoice_processor.api.app",
        "invoice_processor.desktop.launcher",
        "webview",
        "webview.platforms.edgechromium",
        "clr_loader",
        "pythonnet",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "rapidocr_onnxruntime",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "httpx"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "logo.ico"),
    version=str(ROOT / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)