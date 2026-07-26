"""
SYNTEC 域控规范打包脚本

用法：
    python build_syntec.py          # 自动清理 + 打包 + 合规验证

输出：
    dist/SYNTEC-电子票据处理系统/
    ├── SYNTEC-电子票据处理系统.exe
    └── _internal/  (Python 运行时 + 依赖)
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

# 强制 UTF-8 输出，避免 emoji 在 GBK 终端报错
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
APP_NAME = "SYNTEC-电子票据处理系统"
VERSION_FILE = ROOT / "version_info.txt"
MAIN_SCRIPT = ROOT / "main.py"
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"

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

    # 2. 文件名以 SYNTEC 开头
    if not exe.name.startswith("SYNTEC"):
        errors.append(f"❌ exe 文件名不以 SYNTEC 开头: {exe.name}")
    else:
        print(f"✅ 文件名以 SYNTEC 开头")

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


def main():
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
        "--icon", str(ROOT / "logo.ico"),         # 🔴 exe 内嵌图标（资源管理器 + 任务栏）
        "--version-file", str(VERSION_FILE),
        "--noupx",               # 🔴 域控禁止 UPX 压缩
        "--clean",
        "--add-data", f"logo.ico{os.pathsep}.",   # 运行时窗口图标（复制到 bundle 根目录）
        "--collect-all", "PySide6",                # 收集所有 Qt 插件（含图片格式、样式等）
        str(MAIN_SCRIPT),
    ]

    run(cmd, "PyInstaller 打包")
    verify()


if __name__ == "__main__":
    main()
