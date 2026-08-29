"""
SYNTEC 域控规范打包脚本

用法：
    python build_syntec.py          # 自动清理 + 打包 + 合规验证

输出：
    dist/SYNTEC-电子票据处理系统/
    ├── SYNTEC-电子票据处理系统.exe
    ├── SYNTEC-电子票据更新器.exe
    └── _internal/  (Python 运行时 + 依赖)

Release 资产：
    dist/SYNTEC-Invoice-Processor-v{version}.zip
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from src.version import __version__

# 强制 UTF-8 输出，避免 emoji 在 GBK 终端报错
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parent
APP_NAME = "SYNTEC-电子票据处理系统"
UPDATER_NAME = "SYNTEC-电子票据更新器"
RELEASE_ARCHIVE_PREFIX = "SYNTEC-Invoice-Processor"
VERSION_FILE = ROOT / "version_info.txt"
PYPROJECT_FILE = ROOT / "pyproject.toml"
WEB_PACKAGE_FILE = ROOT / "web" / "package.json"
WEB_LOCK_FILE = ROOT / "web" / "package-lock.json"
MAIN_SCRIPT = ROOT / "main.py"
UPDATER_SCRIPT = ROOT / "src" / "desktop" / "update_helper.py"
WEB_DIR = ROOT / "web"
WEB_DIST_DIR = WEB_DIR / "dist"
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
NPM_COMMAND = "npm.cmd" if os.name == "nt" else "npm"

# 🔴 域控强制要求：路径必须纯英文
if any(ord(c) > 127 for c in str(ROOT)):
    sys.exit(
        "❌ 项目路径包含中文字符！\n"
        f"   当前路径: {ROOT}\n"
        "   请将项目移到纯英文路径后重新打包。"
    )


def run(cmd: list[str], desc: str = "") -> None:
    print(f"\n▶ {desc or ' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        sys.exit(f"❌ 失败 (exit {result.returncode})")


def validate_version_sources() -> None:
    """确保运行时、前端和 Windows 资源使用同一版本。"""
    with PYPROJECT_FILE.open("rb") as handle:
        pyproject_version = tomllib.load(handle)["project"]["version"]
    package_version = json.loads(
        WEB_PACKAGE_FILE.read_text(encoding="utf-8")
    )["version"]
    lock_data = json.loads(WEB_LOCK_FILE.read_text(encoding="utf-8"))
    lock_version = lock_data["version"]
    lock_package_version = lock_data["packages"][""]["version"]
    version_info = VERSION_FILE.read_text(encoding="utf-8")
    windows_version = f"{__version__}.0"
    version_parts = ', '.join((*__version__.split('.'), '0'))
    expected_version_fields = (
        f"filevers=({version_parts})",
        f"prodvers=({version_parts})",
        f"StringStruct(u'FileVersion', u'{windows_version}')",
        f"StringStruct(u'ProductVersion', u'{windows_version}')",
    )
    mismatches = []
    for name, value in (
        ("pyproject.toml", pyproject_version),
        ("web/package.json", package_version),
        ("web/package-lock.json", lock_version),
        ("web/package-lock.json packages root", lock_package_version),
    ):
        if value != __version__:
            mismatches.append(f"{name}: {value} != {__version__}")
    mismatches.extend(
        f"version_info.txt 缺少 {field}"
        for field in expected_version_fields
        if field not in version_info
    )
    if mismatches:
        sys.exit("❌ 版本信息不一致:\n   " + "\n   ".join(mismatches))
    print(f"✅ 版本信息一致: {__version__} / {windows_version}")


def verify() -> None:
    """验证打包输出的域控合规性"""
    exe = DIST_DIR / APP_NAME / f"{APP_NAME}.exe"
    internal = DIST_DIR / APP_NAME / "_internal"

    print("\n" + "=" * 56)
    print("🔍 域控合规验证")
    print("=" * 56)

    errors = []

    # 1. exe 存在
    if not exe.exists():
        errors.append(f"exe 不存在: {exe}")
    else:
        print(f"✅ exe 存在: {exe.name}")

    updater = DIST_DIR / APP_NAME / f"{UPDATER_NAME}.exe"
    if not updater.exists():
        errors.append(f"更新器不存在: {updater}")
    else:
        print(f"✅ 更新器存在: {updater.name}")

    # 2. 文件名以 SYNTEC 开头
    if not exe.name.startswith("SYNTEC"):
        errors.append(f"❌ exe 文件名不以 SYNTEC 开头: {exe.name}")
    else:
        print("✅ 文件名以 SYNTEC 开头")

    # 3. _internal 完整性
    required_files = ["python3.dll", "_ctypes.pyd"]
    for f in required_files:
        found = list(internal.glob(f"*{f}"))
        if not found:
            errors.append(f"❌ _internal 缺少核心文件: {f}")
        else:
            print(f"✅ _internal 包含 {found[0].name}")

    # 4. 版本信息 (PowerShell)
    try:
        ps_cmd = (
            f"(Get-Item '{exe}').VersionInfo | "
            f"Select-Object CompanyName, LegalCopyright, FileVersion, ProductVersion | "
            f"Format-List"
        )
        result = subprocess.run(
            ["powershell", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=15,
        )
        print(f"\n📋 版本信息:\n{result.stdout}")

        if "SYNTEC" not in result.stdout:
            errors.append("❌ 版本信息中不包含 SYNTEC")
        else:
            print("✅ 版本信息包含 SYNTEC")
        if f"{__version__}.0" not in result.stdout:
            errors.append(f"❌ exe 版本不是 {__version__}.0")
        else:
            print(f"✅ exe 版本为 {__version__}.0")
    except Exception as e:
        print(f"⚠️ 无法读取版本信息: {e}")

    # 汇总
    print("\n" + "=" * 56)
    if errors:
        for e in errors:
            print(e)
        sys.exit(f"\n❌ {len(errors)} 项不合规，请修正后重新打包")
    else:
        print("✅ 域控合规检查全部通过")
        print(f"📦 输出: {exe.parent}")


def create_release_archive() -> Path:
    """将完整安装目录压缩成可供应用自动更新的 Release 资产。"""
    package_dir = DIST_DIR / APP_NAME
    if not package_dir.is_dir():
        sys.exit(f"❌ 缺少打包目录: {package_dir}")

    archive_base = DIST_DIR / f"{RELEASE_ARCHIVE_PREFIX}-v{__version__}"
    archive_path = Path(
        shutil.make_archive(
            str(archive_base),
            "zip",
            root_dir=str(DIST_DIR),
            base_dir=APP_NAME,
        )
    )
    digest = hashlib.sha256()
    with archive_path.open("rb") as archive_file:
        for chunk in iter(lambda: archive_file.read(1024 * 1024), b""):
            digest.update(chunk)
    print(f"📦 Release ZIP: {archive_path}")
    print(f"   大小: {archive_path.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"   SHA-256: {digest.hexdigest()}")
    return archive_path


def main():
    if not WEB_DIR.exists():
        sys.exit("❌ 缺少 web/ 前端目录")

    validate_version_sources()
    run([NPM_COMMAND, "--prefix", str(WEB_DIR), "run", "build"], "构建 Web 前端")
    if not (WEB_DIST_DIR / "index.html").exists():
        sys.exit("❌ Web 前端构建未生成 web/dist/index.html")

    # 默认清理旧构建产物，保证每次打包干净一致
    for d in (BUILD_DIR, DIST_DIR):
        if d.exists():
            shutil.rmtree(d)
            print(f"🧹 已清理 {d.name}/")

    if not VERSION_FILE.exists():
        sys.exit(f"❌ 缺少 {VERSION_FILE.name}")

    # PyInstaller 打包命令（域控合规）
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--windowed",
        "--name", APP_NAME,
        # 🔴 exe 内嵌图标（资源管理器 + 任务栏）
        "--icon", str(ROOT / "logo.ico"),
        "--version-file", str(VERSION_FILE),
        "--noupx",               # 🔴 域控禁止 UPX 压缩
        "--clean",
        # 运行时窗口图标（复制到 bundle 根目录）
        "--add-data", f"logo.ico{os.pathsep}.",
        "--add-data", f"{WEB_DIST_DIR}{os.pathsep}web/dist",
        "--collect-all", "webview",
        str(MAIN_SCRIPT),
    ]

    run(cmd, "PyInstaller 打包")
    updater_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", UPDATER_NAME,
        "--icon", str(ROOT / "logo.ico"),
        "--version-file", str(VERSION_FILE),
        "--noupx",
        "--clean",
        "--noconfirm",
        "--distpath", str(DIST_DIR / APP_NAME),
        "--workpath", str(BUILD_DIR / UPDATER_NAME),
        "--specpath", str(BUILD_DIR / UPDATER_NAME),
        str(UPDATER_SCRIPT),
    ]
    run(updater_cmd, "打包独立更新器")
    verify()
    create_release_archive()


if __name__ == "__main__":
    main()
