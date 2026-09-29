"""SYNTEC 电子票据处理系统 发布包启动冒烟脚本。

对 PyInstaller 产物（或源码模式）做真实启动探活：
自选空闲端口 + 注入已知令牌 → 启动 → 轮询 /system/health → 版本核对 →
日志无 CRITICAL → 真实关窗（WM_CLOSE，走完整 finally 清理）→ 端口释放断言。

仅适用于交互式 Windows 桌面会话（pywebview 需要真实窗口站），
CI / 无桌面环境请勿执行；非 Windows 平台直接拒绝。

用法（详细参数见 --help）：

    python scripts/smoke_launch.py                    # auto：优先 dist EXE
    python scripts/smoke_launch.py --target source   # 源码模式
    python scripts/smoke_launch.py --legacy-alive-only  # 旧产物降级探活
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# 强制 UTF-8 输出，避免 GBK 终端中文报错
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
APP_NAME = "SYNTEC-电子票据处理系统"
HEALTH_PATH = "/api/v1/system/health"
READY_TIMEOUT = 60.0  # EXE 冷启动（PyInstaller 解压）可能较慢
POLL_INTERVAL = 0.2
SOAK_SECONDS = 3.0
GRACEFUL_CLOSE_TIMEOUT = 15.0

# 关窗用 Win32 消息常量
WM_CLOSE = 0x0010


def _expected_version() -> str:
    """读取 backend/invoice_processor/version.py 的当前版本号。"""
    sys.path.insert(0, str(ROOT / "backend"))
    from invoice_processor.version import __version__  # noqa: PLC0415

    return __version__


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _require_windows_desktop() -> None:
    """冒烟必须运行在交互式 Windows 桌面会话上。"""
    if os.name != "nt":
        sys.exit("❌ 冒烟脚本仅支持 Windows（pywebview 桌面壳依赖真实窗口站）。")
    if not sys.stderr.isatty() and not sys.stdout.isatty():
        # 允许重定向输出，但完全没有控制台时大概率在 CI/服务上下文中
        print("⚠️ 未检测到交互式控制台，桌面窗口可能无法创建。")


def _resolve_target(args: argparse.Namespace) -> tuple[list[str], Path]:
    """返回 (启动命令, 日志基目录)。日志基目录用于核对 logs/invoice.log。"""
    dist_exe = ROOT / "dist" / APP_NAME / f"{APP_NAME}.exe"
    source_main = ROOT / "main.py"
    if args.target == "exe":
        if not dist_exe.is_file():
            sys.exit(
                f"❌ 未找到打包产物: {dist_exe}"
                "\n   请先执行 python scripts/build_syntec.py"
            )
        return ([str(dist_exe)], dist_exe.parent)
    if args.target == "source":
        if not source_main.is_file():
            sys.exit(f"❌ 未找到源码入口: {source_main}")
        return (
            [sys.executable, str(source_main)],
            ROOT,
        )
    # auto：优先 EXE，回退源码
    if dist_exe.is_file():
        print(f"ℹ️ auto 模式选择打包产物: {dist_exe.name}")
        return ([str(dist_exe)], dist_exe.parent)
    print("ℹ️ auto 模式未发现 dist 产物，回退源码模式（python main.py）")
    return ([sys.executable, str(source_main)], ROOT)


def _fetch_health(
    port: int,
    token: str,
    timeout: float = 5.0,
) -> tuple[int, dict[str, Any] | None]:
    """请求 health 端点，返回 (HTTP 状态码, JSON 或 None)。"""
    url = f"http://127.0.0.1:{port}{HEALTH_PATH}"
    request = urllib.request.Request(url, headers={"X-Local-Token": token})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(str(exc)) from exc


def _wait_until_ready(
    port: int,
    token: str,
    expect_version: str,
    legacy_alive_only: bool,
) -> dict[str, Any]:
    """轮询 health 直到就绪；校验状态与版本。

    legacy_alive_only：不注入令牌启动的旧产物收到 401 即视为存活。
    """
    deadline = time.monotonic() + READY_TIMEOUT
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            status, payload = _fetch_health(port, token)
            if legacy_alive_only:
                if status == 401:
                    print("✅ 旧产物探活成功（未注入令牌，health 返回 401 即存活）")
                    return {}
                if status == 200:
                    print("✅ health 200（旧产物未启用令牌校验）")
                    return payload or {}
                raise RuntimeError(f"health 返回意外状态码 {status}")
            if status == 200 and payload is not None:
                if payload.get("status") != "ok":
                    sys.exit(f"❌ health status 异常: {payload}")
                if str(payload.get("version")) != expect_version:
                    sys.exit(
                        f"❌ 版本不匹配: health={payload.get('version')} "
                        f"预期={expect_version}"
                    )
                print(f"✅ health 就绪: status=ok version={payload['version']}")
                return payload
            last_error = RuntimeError(f"health 返回 {status}")
        except (RuntimeError, OSError) as exc:
            last_error = exc
        time.sleep(POLL_INTERVAL)
    sys.exit(f"❌ 服务启动超时（{READY_TIMEOUT:.0f}s）: {last_error}")


def _check_log_file(log_base: Path) -> Path:
    """soak 后核对 logs/invoice.log 生成且无 CRITICAL。"""
    log_path = log_base / "logs" / "invoice.log"
    if not log_path.is_file():
        sys.exit(f"❌ 未生成日志文件: {log_path}")
    content = log_path.read_text(encoding="utf-8", errors="replace")
    if "CRITICAL" in content:
        sys.exit(f"❌ 日志存在 CRITICAL 记录: {log_path}")
    print(f"✅ 日志正常: {log_path.name}（无 CRITICAL）")
    return log_path


def _close_window_gracefully(proc: subprocess.Popen[Any]) -> bool:
    """真实模拟用户关窗：FindWindowW + WM_CLOSE → 走完整 finally 清理。"""
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    hwnd = user32.FindWindowW(None, "SYNTEC · 电子票据工作台")
    if not hwnd:
        print("⚠️ 未找到桌面窗口句柄（源码模式窗口可能未创建）")
        return False
    user32.SendMessageW(hwnd, WM_CLOSE, 0, 0)
    try:
        proc.wait(timeout=GRACEFUL_CLOSE_TIMEOUT)
        print("✅ 干净退出：窗口关闭流程正常收敛")
        return True
    except subprocess.TimeoutExpired:
        print("⚠️ WM_CLOSE 后进程未在时限内退出，回退强制终止")
        return False


def _assert_port_released(port: int, timeout: float = 10.0) -> None:
    """断言端口已释放（干净退出的直接证据）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            try:
                sock.bind(("127.0.0.1", port))
                print(f"✅ 端口 {port} 已释放")
                return
            except OSError:
                time.sleep(0.2)
    sys.exit(f"❌ 端口 {port} 在 {timeout:.0f}s 内未释放，疑似进程残留")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=("auto", "exe", "source"),
        default="auto",
        help="冒烟对象：auto 优先 dist EXE，否则源码模式",
    )
    parser.add_argument("--exe", help="显式指定 EXE 路径（覆盖默认 dist 位置）")
    parser.add_argument(
        "--port", type=int, default=None, help="固定端口（默认自选空闲端口）",
    )
    parser.add_argument(
        "--soak", type=float, default=SOAK_SECONDS, help="就绪后观察时长（秒）",
    )
    parser.add_argument(
        "--expect-version",
        default=None,
        help="期望版本号（默认读取 backend/invoice_processor/version.py）",
    )
    parser.add_argument(
        "--legacy-alive-only",
        action="store_true",
        help="降级探活模式：不注入令牌，收到 401 即判定存活（用于旧产物）",
    )
    args = parser.parse_args()

    _require_windows_desktop()
    expect_version = args.expect_version or _expected_version()
    port = args.port or _find_free_port()
    token = "" if args.legacy_alive_only else secrets.token_urlsafe(32)

    cmd, log_base = _resolve_target(args)
    if args.exe:
        exe_path = Path(args.exe).resolve()
        if not exe_path.is_file():
            sys.exit(f"❌ 指定的 EXE 不存在: {exe_path}")
        cmd = [str(exe_path)]
        log_base = exe_path.parent

    env = {
        **os.environ,
        "PLATFORM_HOST": "127.0.0.1",
        "PLATFORM_PORT": str(port),
    }
    if token:
        env["PLATFORM_LOCAL_TOKEN"] = token

    print("=" * 56)
    print(f"🚀 启动冒烟: {' '.join(cmd)}")
    print(f"   端口: {port} | 期望版本: {expect_version} | 模式: "
          f"{'降级探活' if args.legacy_alive_only else '完整校验'}")
    print("=" * 56)

    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env)
    exit_code: int | None = None
    try:
        _wait_until_ready(port, token, expect_version, args.legacy_alive_only)
        print(f"⏳ 就绪后观察 {args.soak:.0f}s ...")
        time.sleep(args.soak)
        if not args.legacy_alive_only:
            log_path = _check_log_file(log_base)
            print(f"   日志路径: {log_path}")
        exited = proc.poll()
        if exited is not None:
            sys.exit(f"❌ 观察期内进程意外退出（exit={exited}）")
        if args.legacy_alive_only:
            # 旧产物降级模式：确认存活即结束，强制终止
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True, check=False,
            )
            print("✅ 降级探活完成（taskkill 结束旧产物）")
            return
        if not _close_window_gracefully(proc):
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True, check=False,
            )
        exit_code = proc.wait(timeout=GRACEFUL_CLOSE_TIMEOUT)
        if exit_code not in (0, None):
            print(f"⚠️ 进程退出码 {exit_code}（窗口关闭路径可能存在未收敛资源）")
        _assert_port_released(port)
        print("\n✅ 冒烟全部通过")
    finally:
        # 兜底回收，防止任何路径下的进程残留
        if proc.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True, check=False,
            )


if __name__ == "__main__":
    main()
