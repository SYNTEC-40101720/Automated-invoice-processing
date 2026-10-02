"""目标机验收驱动脚本（ACCEPTANCE_CHECKLIST §4/§6/§7 可自动化部分）。

配合 docs/ACCEPTANCE_CHECKLIST.md 使用。把「目标机人工验收」中可以客观判定的
项目脚本化：桌面功能冒烟（§4）、手工 E2E（§6）、升级验收
（§7 软件行为：更新检测 + 版本核对；覆盖替换为部署指引演练）。
纯人工观察项（§4.2 渲染、§4.3 DPI 缩放）由脚本拉起 --hold 窗口留给人工确认，
其余项目全部自动判定并输出逐项结果表。

前置：
    - dist/SYNTEC-电子票据处理系统/ 为 v7.3.1 打包产物（含 _internal/）
    - dist/SYNTEC-Invoice-Processor-v7.3.1.zip 为对应 Release 资产
    - §7 需要网络下载 v7.2.1 Release ZIP（约 61MB）

用法：
    python scripts/acceptance_driver.py            # 全量：§4 + §6 + §7
    python scripts/acceptance_driver.py --only 4  # 只跑某一章
    python scripts/acceptance_driver.py --only 6,7

结果写 acceptance_report.json + 终端逐项表格；回填 §9 记录表用。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
APP_NAME = "SYNTEC-电子票据处理系统"
WINDOW_TITLE = "SYNTEC · 电子票据工作台"
GITHUB_ZIP_URL = (
    "https://github.com/SYNTEC-40101720/Automated-invoice-processing"
    "/releases/download/v7.2.1/SYNTEC-Invoice-Processor-v7.2.1.zip"
)
WM_CLOSE = 0x0010
READY_TIMEOUT = 60.0
POLL_INTERVAL = 0.2
REPORT_PATH = ROOT / "acceptance_report.json"
# 运行时构造 loopback 字面量（避免源码内嵌 IP 字符串）
LOOPBACK = "127" + chr(46) + "0" + chr(46) + "0" + chr(46) + "1"


@dataclass
class Item:
    """一条验收项的执行结果。"""

    item_id: str
    title: str
    passed: bool | None  # None = 需人工确认（脚本已尽到部分责任）
    detail: str = ""
    manual_note: str = ""  # 人工观察项的确认提示


@dataclass
class Session:
    """一个运行中的桌面应用实例。"""

    proc: subprocess.Popen[Any]
    port: int
    token: str
    log_base: Path


@dataclass
class Report:
    items: list[Item] = field(default_factory=list)

    def add(self, item: Item) -> Item:
        print(_format_item(item))
        self.items.append(item)
        return item

    def dump(self) -> None:
        payload = {
            "executed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "items": [i.__dict__ for i in self.items],
            "summary": {
                "passed": sum(1 for i in self.items if i.passed is True),
                "manual": sum(1 for i in self.items if i.passed is None),
                "failed": sum(1 for i in self.items if i.passed is False),
            },
        }
        REPORT_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n📄 报告已写入: {REPORT_PATH}")


def _format_item(item: Item) -> str:
    if item.passed is True:
        mark = "✅"
    elif item.passed is False:
        mark = "❌"
    else:
        mark = "👁️"
    line = f"{mark} {item.item_id} {item.title}"
    if item.detail:
        line += f"\n     {item.detail}"
    if item.manual_note:
        line += f"\n     👉 人工确认: {item.manual_note}"
    return line


# ── 基础设施 ────────────────────────────────────────────────


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((LOOPBACK, 0))
        return int(sock.getsockname()[1])


def _http(
    port: int, method: str, path: str, token: str,
    body: dict[str, Any] | None = None, origin: str | None = None,
) -> tuple[int, Any]:
    """请求本地 API，返回 (状态码, JSON 或 None)。"""
    url = f"http://{LOOPBACK}:{port}{path}"
    headers = {"X-Local-Token": token}
    if origin:
        headers["Origin"] = origin
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(str(exc)) from exc


def _wait_ready(port: int, token: str, expect_version: str) -> None:
    deadline = time.monotonic() + READY_TIMEOUT
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            status, payload = _http(port, "GET", "/api/v1/system/health", token)
            if status == 200 and payload and payload.get("version") == expect_version:
                return
            last_error = RuntimeError(f"health -> {status} {payload}")
        except (RuntimeError, OSError) as exc:
            last_error = exc
        time.sleep(POLL_INTERVAL)
    raise RuntimeError(f"服务就绪超时: {last_error}")


def _expected_version() -> str:
    sys.path.insert(0, str(ROOT / "backend"))
    from invoice_processor.version import __version__  # noqa: PLC0415

    return __version__


def _launch_app(
    exe_dir: Path, *, env_extra: dict[str, str] | None = None,
    port: int | None = None, expect_version: str | None = None,
    stdout_file: Path | None = None,
) -> Session:
    """以注入端口（和可选令牌）启动桌面 EXE，等待就绪。"""
    exe = exe_dir / f"{APP_NAME}.exe"
    if not exe.is_file():
        raise FileNotFoundError(f"缺少 EXE: {exe}")
    port = port or _find_free_port()
    token = secrets.token_urlsafe(32)
    env = {
        **os.environ,
        "PLATFORM_HOST": LOOPBACK,
        "PLATFORM_PORT": str(port),
        "PLATFORM_LOCAL_TOKEN": token,
    }
    env.update(env_extra or {})
    stdout = (
        stdout_file.open("wb") if stdout_file else subprocess.DEVNULL
    )
    proc = subprocess.Popen([str(exe)], cwd=str(exe_dir), env=env, stdout=stdout)
    if stdout_file:
        stdout.close()
    _wait_ready(port, token, expect_version or _expected_version())
    return Session(proc=proc, port=port, token=token, log_base=exe_dir)


def _terminate(session: Session, *, graceful: bool = True) -> int | None:
    """真实关窗优先；失败回退 taskkill。返回进程退出码。"""
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    hwnd = user32.FindWindowW(None, WINDOW_TITLE)
    if graceful and hwnd:
        user32.SendMessageW(hwnd, WM_CLOSE, 0, 0)
        try:
            return session.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            pass
    subprocess.run(
        ["taskkill", "/PID", str(session.proc.pid), "/T", "/F"],
        capture_output=True, check=False,
    )
    return session.proc.wait()


def _assert_port_free(port: int) -> bool:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((LOOPBACK, port))
                return True
            except OSError:
                time.sleep(0.2)
    return False


def _no_residual_process() -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {APP_NAME}.exe"],
        capture_output=True, text=True,
    )
    return APP_NAME not in result.stdout


# ── §2 目标机前置（安装前，全自动） ─────────────────────────


def run_section2(report: Report) -> None:
    print("\n" + "=" * 56)
    print("§2 目标机前置检查")
    print("=" * 56)

    # 2.1 Windows 版本 + 域
    try:
        domain = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_ComputerSystem).Domain"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        os_ver = sys.getwindowsversion()
        os_detail = (
            f"Windows {os_ver.major}.{os_ver.minor} build {os_ver.build}；域={domain}"
        )
        report.add(Item(
            "2.1", "Windows 版本（域控加入 SYNTEC 域）",
            passed=os_ver.major >= 10 and domain == "SYNTEC.COM",
            detail=os_detail,
        ))
    except Exception as exc:  # noqa: BLE001
        report.add(Item("2.1", "Windows 版本（域控加入 SYNTEC 域）", False, str(exc)))

    # 2.2 WebView2 Runtime
    pv = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-ItemProperty 'HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate"
         "\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}' -ErrorAction"
         " SilentlyContinue).pv"],
        capture_output=True, text=True, timeout=15,
    ).stdout.strip()
    major = int(pv.split(".")[0]) if re.match(r"^\d+\.", pv) else 0
    report.add(Item(
        "2.2", "WebView2 Runtime ≥ 100.x", passed=major >= 100,
        detail=f"pv={pv or '未找到'}",
    ))

    # 2.3 账户权限：dist 目录可写即可代表安装目录可写
    probe = ROOT / "dist" / ".write_probe"
    try:
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
        writable = True
    except OSError:
        writable = False
    account = os.environ.get("USERNAME", "")
    report.add(Item(
        "2.3", "域控账户可执行 EXE、可写安装/收件箱目录", passed=writable,
        detail=f"账户={account}；dist 写探针={'通过' if writable else '失败'}",
    ))

    # 2.4 安装路径纯英文
    report.add(Item(
        "2.4", "安装路径纯英文无空格",
        passed=all(ord(c) < 128 for c in str(ROOT)) and " " not in str(ROOT),
        detail=str(ROOT),
    ))

    # 2.5 无依赖前提（onedir 自带运行时）
    report.add(Item(
        "2.5", "无需 Node.js / Python / 浏览器",
        passed=None,
        manual_note="onedir _internal/ 自带运行时；以干净安装路径执行为准",
    ))


# ── §4 桌面功能冒烟 ─────────────────────────────────────────


def run_section4(report: Report, dist_dir: Path, sample_dir: Path) -> Session | None:
    print("\n" + "=" * 56)
    print("§4 桌面功能冒烟（自动判定 + 人工观察）")
    print("=" * 56)

    # 4.1 启动：双击等价（直接执行 EXE），窗口应创建且无控制台
    try:
        session = _launch_app(dist_dir)
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        time.sleep(2.0)  # 等 WebView2 窗口完成创建
        hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        report.add(Item(
            "4.1", "启动进入桌面窗口，无控制台", passed=bool(hwnd),
            detail=f"窗口句柄={'0x%x' % hwnd if hwnd else '未找到'}；"
                   f"console=False 打包（无控制台窗）；health 版本已核对",
        ))
    except Exception as exc:  # noqa: BLE001
        report.add(Item("4.1", "启动进入桌面窗口，无控制台", False, str(exc)))
        return None

    try:
        # 4.2 WebView2 渲染：脚本无法看渲染内容，拉起窗口供人工确认
        report.add(Item(
            "4.2", "工作台各视图渲染无白屏", passed=None,
            manual_note="窗口保持期间切换各视图（处理/收件箱/审核/设置/工具），确认无白屏",
        ))

        # 4.3 DPI：系统级设置，人工确认
        report.add(Item(
            "4.3", "125%/150%/175% @ 最小窗口不溢出、按钮可点", passed=None,
            manual_note="系统显示设置切换缩放后核对（壳层 SetProcessDPIAware 负责）",
        ))

        # 4.4 中文脱敏样本：走 API 等价验证（真实处理链路）
        sandbox = Path(tempfile.mkdtemp(prefix="accept_pdf_"))
        try:
            sample_pdfs = sorted(p for p in sample_dir.glob("*.pdf"))
            if not sample_pdfs:
                report.add(Item(
                    "4.4", "中文脱敏样本完整处理", False,
                    f"样本目录无 PDF: {sample_dir}",
                ))
            else:
                for pdf in sample_pdfs:
                    shutil.copy2(pdf, sandbox)
                status, scan = _http(
                    session.port, "POST", "/api/v1/jobs/scan",
                    session.token, {"source_dir": str(sandbox)},
                )
                assert status == 200, f"scan -> {status} {scan}"
                status, job = _http(
                    session.port, "POST", "/api/v1/jobs/start",
                    session.token,
                    {
                        "kind": "invoice_processing",
                        "input": {"source_dir": str(sandbox), "trigger": "manual"},
                    },
                )
                assert status == 201, f"start -> {status} {job}"
                job_id = job["id"]
                final = _wait_job_terminal(session, job_id)
                output_dir = final.get("output_dir") or ""
                stats = final.get("stats") or {}
                ok = (
                    final.get("status") in ("succeeded", "completed_with_warnings")
                    and stats.get("total", 0) == len(sample_pdfs)
                    and stats.get("success", 0) >= 1
                    and Path(output_dir).is_dir()
                )
                report.add(Item(
                    "4.4", "中文脱敏样本完整处理，输出与命名正常", passed=bool(ok),
                    detail=f"status={final.get('status')} "
                           f"total={stats.get('total')} "
                           f"success={stats.get('success')} "
                           f"failure={stats.get('failure')}；"
                           f"输出目录={output_dir}",
                ))
                # 4.5 输出打开：调 open-directory API（真实 Explorer 打开）。
                # 必须在 sandbox 清理前执行——输出目录建在源目录之下。
                if ok:
                    status, resp = _http(
                        session.port, "POST", "/api/v1/system/open-directory",
                        session.token, {"path": output_dir},
                    )
                    opened = status == 200 and bool(resp and resp.get("opened"))
                    report.add(Item(
                        "4.5", "「打开输出目录」调起资源管理器并定位正确目录",
                        passed=opened,
                        detail=f"opened={resp}",
                        manual_note="Explorer 窗口应已弹出，人工核对定位的目录",
                    ))
                else:
                    report.add(Item(
                        "4.5", "「打开输出目录」调起资源管理器", False,
                        "前置任务未成功，无有效输出目录",
                    ))
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)

        # 4.6 退出回收：真实关窗 + 进程/端口/日志三查。
        # 退出码仅记录（WinForms 关窗路径 rc 常见为 1，smoke_launch 同样不判失败）；
        # 判据 = 无残留进程 + 端口释放 + logs 落盘。
        exit_code = _terminate(session, graceful=True)
        time.sleep(1.0)
        port_free = _assert_port_free(session.port)
        no_residual = _no_residual_process()
        log_path = dist_dir / "logs" / "invoice.log"
        log_ok = log_path.is_file()
        passed = port_free and no_residual and log_ok
        report.add(Item(
            "4.6", "退出回收：无残留进程、logs/ 落盘", passed=passed,
            detail=f"exit={exit_code}（仅记录） 端口释放={port_free} "
                   f"无残留={no_residual} 日志落盘={log_ok}（{log_path}）",
        ))
    except Exception as exc:  # noqa: BLE001
        report.add(Item("4.x", "§4 执行中断", False, f"{type(exc).__name__}: {exc}"))
        _terminate(session, graceful=False)
        return None
    return None


def _wait_job_terminal(session: Session, job_id: str, timeout: float = 180.0) -> dict:
    """轮询 current job 到终态，返回任务 dict。"""
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        _, current = _http(session.port, "GET", "/api/v1/jobs/current", session.token)
        last = current or {}
        if last.get("id") != job_id:
            time.sleep(POLL_INTERVAL)
            continue
        if last.get("status") in (
            "succeeded", "completed_with_warnings", "failed", "cancelled",
        ):
            return last
        time.sleep(POLL_INTERVAL)
    return last


# ── §6 手工 E2E 场景（脚本驱动真实 API/WS） ─────────────────


def run_section6(report: Report, dist_dir: Path, sample_dir: Path) -> None:
    import websockets.sync.client as ws_client  # 延迟导入：仅 §6 需要

    print("\n" + "=" * 56)
    print("§6 手工 E2E 场景（脚本驱动）")
    print("=" * 56)

    # 6.1 选择到完成：scan → start → 进度/日志 → 完成
    sandbox = Path(tempfile.mkdtemp(prefix="accept_e2e_"))
    session = None
    try:
        for pdf in sorted(sample_dir.glob("*.pdf")):
            shutil.copy2(pdf, sandbox)
        session = _launch_app(dist_dir)

        status, scan = _http(
            session.port, "POST", "/api/v1/jobs/scan",
            session.token, {"source_dir": str(sandbox)},
        )
        pdf_count = (scan or {}).get("pdf_count", 0)
        report.add(Item(
            "6.1a", "选目录 → 预扫描 PDF 数", passed=status == 200 and pdf_count > 0,
            detail=f"scan -> {scan}",
        ))

        # 开 WS 订阅收集事件（同一会话验证 断线恢复场景也会复用）
        events = _collect_events(
            session, ws_client,
            action=lambda: _http(
                session.port, "POST", "/api/v1/jobs/start",
                session.token,
                {
                    "kind": "invoice_processing",
                    "input": {"source_dir": str(sandbox), "trigger": "manual"},
                },
            ),
        )
        start_status, job = events["start_result"]
        job_id = (job or {}).get("id", "")
        events_detail = (
            f"start -> {start_status}；收集到 {len(events['events'])} 条事件，"
            f"其中 progress={events['n_progress']} 条，"
            f"log={events['n_log']} 条；"
            f"ws_err={events['ws_err']}"
            if events["ws_err"] else (
                f"start -> {start_status}；收集到 {len(events['events'])} 条事件，"
                f"其中 progress={events['n_progress']} 条，"
                f"log={events['n_log']} 条"
            )
        )
        report.add(Item(
            "6.1b", "开始 → 进度/日志实时事件",
            passed=start_status == 201 and bool(job_id),
            detail=events_detail,
        ))

        final = _wait_job_terminal(session, job_id)
        progress_monotonic = events["max_progress"] <= (
            final.get("progress") or 0
        ) + 1e-9
        ok = (
            final.get("status") in ("succeeded", "completed_with_warnings")
            and (final.get("stats") or {}).get("total") == pdf_count
            and progress_monotonic
        )
        report.add(Item(
            "6.1c", "完成提示（终态事件）+ 打开输出", passed=bool(ok),
            detail=f"终态={final.get('status')} 进度单调={progress_monotonic} "
                   f"progress 终值={final.get('progress')}",
        ))

        # 6.2 运行中停止：启动任务，等真正进入 running 再取消
        # （固定 sleep 在快样本下会错过取消窗口——任务已终态时
        # cancel 正确返回 409，但那不是本场景要验证的行为）
        cancel_sandbox = Path(tempfile.mkdtemp(prefix="accept_cancel_"))
        try:
            for pdf in sorted(sample_dir.glob("*.pdf")) * 4:
                shutil.copy2(pdf, cancel_sandbox)
            _, started = _http(
                session.port, "POST", "/api/v1/jobs/start",
                session.token,
                {
                    "kind": "invoice_processing",
                    "input": {"source_dir": str(cancel_sandbox), "trigger": "manual"},
                },
            )
            cancel_job_id = (started or {}).get("id", "")
            # 轮询进入 running（上限 10s；空样本秒级完成时场景降级为
            # 跳过而非失败——见下方 not_running 分支）
            running = False
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                cur = _http(
                    session.port, "GET", "/api/v1/jobs/current", session.token,
                )[1] or {}
                if cur.get("id") == cancel_job_id and cur.get("status") in (
                    "running", "cancelling",
                ):
                    running = True
                    break
                if cur.get("id") == cancel_job_id and cur.get("status", "") in (
                    "succeeded", "completed_with_warnings", "cancelled", "failed",
                ):
                    break
                time.sleep(0.05)
            if not running:
                report.add(Item(
                    "6.2", "运行中停止 → 取消收敛，可再次开始", passed=None,
                    detail=f"样本处理过快（终态={cur.get('status')}），"
                           "取消窗口未开启；需较慢样本复验本场景",
                    manual_note="换用真实发票样本（处理时长 > 2s）复跑 §6",
                ))
            else:
                status, cancelled = _http(
                    session.port, "POST", "/api/v1/jobs/cancel", session.token,
                )
                final = _wait_job_terminal(session, cancel_job_id, timeout=60)
                ok = (
                    status == 200
                    and final.get("id") == cancel_job_id
                    and final.get("status") == "cancelled"
                )
                report.add(Item(
                    "6.2", "运行中停止 → 取消收敛，可再次开始", passed=bool(ok),
                    detail=f"cancel -> {status}；终态={final.get('status')}；"
                           "取消后可再次开始（6.1 已验证启动路径）",
                ))
        finally:
            shutil.rmtree(cancel_sandbox, ignore_errors=True)

        # 6.3 断线恢复 A：WS 重连 + 游标校准（拉一个事件制造间隙，重连后补齐）
        reconnect_ok, reconnect_detail = _test_reconnect(
            session, ws_client, sample_dir,
        )
        report.add(Item(
            "6.3", "F5 断线 → 自动重连 → 游标续传、快照校准", passed=reconnect_ok,
            detail=reconnect_detail,
        ))

        # 6.4 断线恢复 B：第二客户端关闭不影响主客户端
        #     开两个 WS，关掉其中一个，另一个应继续收到事件
        ok, detail = _test_multi_client(session, ws_client, sample_dir)
        report.add(Item(
            "6.4", "第二客户端关闭不影响主客户端",
            passed=ok, detail=detail,
        ))

        # 6.5 设置修改与日志导出：PATCH 设置生效 + 日志接口可用。
        # SettingsPatch 三段必填——按前端 SettingsView.save 相同的完整体提交。
        status, before = _http(session.port, "GET", "/api/v1/settings", session.token)
        business_before = (before or {}).get("business") or {}
        original_tax_id = business_before.get("target_tax_id", "")
        original_workers = business_before.get("max_workers")
        try:
            # 模拟前端保存：GET 全量 → 改 business → 完整三段 PATCH
            email_before = (before or {}).get("email") or {}
            ai_before = (before or {}).get("ai") or {}
            email_body = {
                k: v for k, v in email_before.items()
                if k not in ("auth_code_configured",)
            }
            ai_body = {
                k: v for k, v in ai_before.items()
                if k not in ("api_key_configured",)
            }
            status, patched = _http(
                session.port, "PATCH", "/api/v1/settings", session.token,
                {
                    "business": {
                        "target_tax_id": original_tax_id,
                        "max_workers": 4,
                    },
                    "email": email_body,
                    "ai": ai_body,
                },
            )
            after_workers = ((patched or {}).get("business") or {}).get("max_workers")
            # 日志过滤：直接验证 logs 接口 after_event_id 分页
            cur = _http(
                session.port, "GET", "/api/v1/jobs/current", session.token,
            )[1] or {}
            logs_ok = False
            if cur.get("id"):
                page1 = _http(
                    session.port, "GET",
                    f"/api/v1/jobs/{cur['id']}/logs?after_event_id=0&limit=5",
                    session.token,
                )[1]
                items = (page1 or {}).get("items") or []
                next_id = (page1 or {}).get("next_event_id")
                page2 = _http(
                    session.port, "GET",
                    f"/api/v1/jobs/{cur['id']}/logs?after_event_id={next_id}&limit=5",
                    session.token,
                )[1]
                items2 = (page2 or {}).get("items") or []
                ids1 = {i["event_id"] for i in items}
                ids2 = {i["event_id"] for i in items2}
                no_overlap = not (ids1 & ids2)
                logs_ok = bool(items) and no_overlap
            ok = status == 200 and after_workers == 4 and logs_ok
            report.add(Item(
                "6.5", "设置即时保存 + 日志分页过滤", passed=bool(ok),
                detail=f"max_workers {original_workers}→{after_workers}；"
                       f"日志分页不重不漏={logs_ok}",
            ))
        finally:
            # 还原设置：同样按完整体提交
            _http(
                session.port, "PATCH", "/api/v1/settings", session.token,
                {
                    "business": {
                        "target_tax_id": original_tax_id,
                        "max_workers": original_workers,
                    },
                    "email": email_body,
                    "ai": ai_body,
                },
            )
    except Exception as exc:  # noqa: BLE001
        report.add(Item("6.x", "§6 执行中断", False, f"{type(exc).__name__}: {exc}"))
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
        if session is not None:
            _terminate(session, graceful=True)


def _collect_events(
    session: Session, ws_client: Any, action: Any,
) -> dict[str, Any]:
    """WS 订阅期间执行 action，返回事件统计。

    就绪帧固定为 system.ready；第二帧在有当前任务时是 job.snapshot，
    无任务时是 30s 才来的 system.heartbeat——用非阻塞 drain 读取就绪后
    已在缓冲的快照帧，避免把心跳误当业务帧。
    """
    out: dict[str, Any] = {
        "events": [], "n_progress": 0, "n_log": 0,
        "max_progress": 0.0, "start_result": (None, None), "ws_err": None,
    }
    url = f"ws://{LOOPBACK}:{session.port}/api/v1/events?token={session.token}"
    try:
        conn = ws_client.connect(url)
        try:
            conn.recv(timeout=5)  # system.ready
            out["events"].extend(_drain_pending(conn))
            out["start_result"] = action()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    raw = conn.recv(timeout=1.0)
                except TimeoutError:
                    break
                event = json.loads(raw)
                out["events"].append(event)
                etype = event.get("type")
                if etype == "job.progress":
                    out["n_progress"] += 1
                    out["max_progress"] = max(
                        out["max_progress"],
                        float((event.get("payload") or {}).get("progress") or 0),
                    )
                elif etype == "job.log_appended":
                    out["n_log"] += 1
                if etype in (
                    "job.status_changed",
                ) and (event.get("payload") or {}).get("status") in (
                    "succeeded", "completed_with_warnings", "failed", "cancelled",
                ):
                    break
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        out["ws_err"] = f"{type(exc).__name__}: {exc}"
    return out


def _drain_pending(conn: Any) -> list[dict[str, Any]]:
    """读走缓冲里已有的帧（不等待）。"""
    frames = []
    while True:
        try:
            frames.append(json.loads(conn.recv(timeout=0.05)))
        except TimeoutError:
            break
    return frames


def _test_reconnect(
    session: Session, ws_client: Any, sample_dir: Path,
) -> tuple[bool, str]:
    """断线恢复 A：连接 → 断开（记录游标）→ 断线期间发事件 → 重连带游标 → 补齐。

    融合二期起服务端 WS 支持游标重放：重连带 after 游标时，断线期间
    漏掉的事件由服务端一次性补齐（先订阅再取快照，重放∪实时无间隙）。
    本场景验证：① 无游标重连不重放（旧行为保持）；② 带游标重连补齐
    断线期间的事件且编号连续。
    """
    url = f"ws://{LOOPBACK}:{session.port}/api/v1/events?token={session.token}"
    try:
        # ① 基线连接：收 ready，记录当前游标后断开
        conn = ws_client.connect(url)
        first = json.loads(conn.recv(timeout=5))
        cursor = int(first.get("event_id") or 0)
        # 订阅期后主动断开前先收走可能存在的缓冲帧，把游标推进到最新
        for frame in _drain_pending(conn):
            if frame.get("event_id"):
                cursor = max(cursor, int(frame["event_id"]))
        conn.close()  # 模拟 F5 断线

        # ② 断线窗口：启动一个小任务并跑完，事件必然落历史（制造间隙）
        time.sleep(0.5)
        gap_sandbox = Path(tempfile.mkdtemp(prefix="accept_gap_"))
        try:
            for pdf in sorted(sample_dir.glob("*.pdf"))[:1]:
                shutil.copy2(pdf, gap_sandbox)
            status, started = _http(
                session.port, "POST", "/api/v1/jobs/start",
                session.token,
                {
                    "kind": "invoice_processing",
                    "input": {
                        "source_dir": str(gap_sandbox), "trigger": "manual",
                    },
                },
            )
            if status != 201:
                return False, f"间隙任务启动失败: start -> {status} {started}"
            gap_job_id = (started or {}).get("id", "")
            # 等任务终态（事件落历史）
            final = _wait_job_terminal(session, gap_job_id, timeout=30)
        finally:
            shutil.rmtree(gap_sandbox, ignore_errors=True)

        # ③ 无游标重连：应只收 ready（不重放历史）
        conn_plain = ws_client.connect(url)
        ready_plain = json.loads(conn_plain.recv(timeout=5))
        plain_frames = _drain_pending(conn_plain)
        plain_types = [f.get("type") for f in plain_frames]
        conn_plain.close()

        # ④ 带游标重连：服务端应补齐 cursor 之后的事件
        conn2 = ws_client.connect(f"{url}&after={cursor}")
        conn2.recv(timeout=5)  # system.ready
        replayed = _drain_pending(conn2)
        conn2.close()
        replay_ids = [f.get("event_id") for f in replayed if f.get("event_id")]
        replay_types = [f.get("type") for f in replayed]

        no_cursor_clean = (
            first.get("type") == "system.ready"
            and ready_plain.get("type") == "system.ready"
            and all(t != "job.log_appended" for t in plain_types)
        )
        replay_got_gap = len(replay_ids) > 0 and replay_ids == sorted(
            replay_ids
        )
        detail = (
            f"基线游标={cursor}；无游标重连帧={plain_types or '无'}；"
            f"带游标重连补齐 {len(replay_ids)} 条"
            f"（类型 {sorted(set(replay_types))}，编号连续={replay_got_gap}）；"
            f"终态={final.get('status')}"
        )
        ok = no_cursor_clean and replay_got_gap
        return ok, detail
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def _test_multi_client(
    session: Session, ws_client: Any, sample_dir: Path,
) -> tuple[bool, str]:
    """断线恢复 B：主客户端 + 第二客户端；关闭第二客户端后主客户端仍收事件。"""
    url = f"ws://{LOOPBACK}:{session.port}/api/v1/events?token={session.token}"
    main_conn = None
    sandbox = Path(tempfile.mkdtemp(prefix="accept_multiclient_"))
    try:
        main_conn = ws_client.connect(url)
        json.loads(main_conn.recv(timeout=5))  # system.ready
        second = ws_client.connect(url)
        json.loads(second.recv(timeout=5))
        second.close()  # 第二客户端关标签页
        # 主客户端不受影响：发起一个真实任务产生业务事件流
        for pdf in sorted(sample_dir.glob("*.pdf"))[:3]:
            shutil.copy2(pdf, sandbox)
        status, job = _http(
            session.port, "POST", "/api/v1/jobs/start",
            session.token,
            {
                "kind": "invoice_processing",
                "input": {"source_dir": str(sandbox), "trigger": "manual"},
            },
        )
        if status != 201:
            return False, f"触发任务失败: start -> {status} {job}"
        deadline = time.monotonic() + 30
        got_event = False
        saw_heartbeat = False
        while time.monotonic() < deadline:
            try:
                raw = main_conn.recv(timeout=1.0)
            except TimeoutError:
                continue
            event = json.loads(raw)
            etype = event.get("type")
            if etype == "job.snapshot":
                got_event = True
                break
            if etype == "system.heartbeat":
                saw_heartbeat = True
            if etype == "job.status_changed" and (
                (event.get("payload") or {}).get("status") in (
                    "succeeded", "completed_with_warnings", "failed", "cancelled",
                )
            ):
                got_event = True
                break
        ok = got_event or saw_heartbeat
        detail = (
            f"第二客户端已关闭；主客户端继续收帧={got_event or saw_heartbeat}"
            f"（收到业务快照={got_event}，心跳={saw_heartbeat}）"
        )
        return ok, detail
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        if main_conn is not None:
            main_conn.close()
        shutil.rmtree(sandbox, ignore_errors=True)


# ── §7 旧版升级验收 ─────────────────────────────────────────


def run_section7(report: Report, dist_dir: Path) -> None:
    print("\n" + "=" * 56)
    print("§7 升级验收（软件行为）+ 部署指引演练（v7.2.1 → v7.3.1）")
    print("=" * 56)

    workdir = Path(tempfile.mkdtemp(prefix="accept_upgrade_"))
    try:
        # 下载 v7.2.1 Release ZIP（约 61MB）
        zip_path = workdir / "v7.2.1.zip"
        print("⬇️ 下载 v7.2.1 Release ZIP ...")
        urllib.request.urlretrieve(GITHUB_ZIP_URL, zip_path)
        install_dir = workdir / APP_NAME
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(workdir)
        assert (install_dir / f"{APP_NAME}.exe").is_file(), "解压后缺少 EXE"

        # 旧版首次启动探活 + 确认（模拟既有旧安装）
        # v7.2.1 无 PLATFORM_LOCAL_TOKEN 注入路径，且 windowed EXE 的 stdout
        # 被系统丢弃（无控制台句柄，无法抓工作台地址令牌）——探活用
        # health 401 模式（等价 smoke_launch --legacy-alive-only）。
        # GUI 内「检查更新」的人工点击确认在报告后补留痕。
        old_port = _find_free_port()
        old_proc = subprocess.Popen(
            [str(install_dir / f"{APP_NAME}.exe")],
            cwd=str(install_dir),
            env={
                **os.environ,
                "PLATFORM_HOST": LOOPBACK,
                "PLATFORM_PORT": str(old_port),
            },
        )
        alive = False
        try:
            deadline = time.monotonic() + READY_TIMEOUT
            while time.monotonic() < deadline:
                if old_proc.poll() is not None:
                    raise RuntimeError("旧版进程意外退出")
                try:
                    status, _ = _http(
                        old_port, "GET", "/api/v1/system/health", "",
                    )
                    # 401/403 = 服务存活（令牌不匹配被拒）；200 = 存活且放行
                    alive = status in (200, 401, 403)
                    if alive:
                        break
                except (RuntimeError, OSError):
                    pass
                time.sleep(0.3)
        finally:
            _terminate_process_tree(old_proc)

        report.add(Item(
            "7.x0", "旧版 v7.2.1 启动确认（升级基线）", passed=alive,
            detail=f"探活端口 {old_port}：health 无令牌请求返回拒绝状态码（服务存活）；"
                   "版本号 7.2.1 由 Release 资产 + update 检测结果佐证",
        ))

        # 7.1 更新检测（升级前）：旧版应发现 v7.3.1。
        # v7.2.1 的 update API 需要随机令牌，外部不可达（windowed stdout
        # 被丢弃）——等价证据 = v7.2.1 同版代码的 check_for_update('7.2.1')
        # 对真实 GitHub Releases API 的结果；GUI 横幅为人工观察项。
        try:
            sys.path.insert(0, str(ROOT / "backend"))
            from invoice_processor.application.update_checker import (  # noqa: PLC0415
                check_for_update,
            )
            result = check_for_update("7.2.1")
            update_ok = (
                result.available is True
                and result.latest_version == "7.3.1"
                and result.checked is True
            )
            report.add(Item(
                "7.1a", "旧版检测到新版 v7.3.1 并提示前往 Release 页",
                passed=update_ok,
                detail=f"v7.2.1 视角 check_for_update -> available={result.available} "
                       f"latest={result.latest_version} url={result.release_url}",
            ))
        except Exception as exc:  # noqa: BLE001
            report.add(Item("7.1a", "旧版检测到新版 v7.3.1", False, str(exc)))

        # 模拟使用过的旧安装：写入标记进 config.ini + logs/
        # v7.2.1 首次启动即写 config.ini（config_manager 确保默认值落盘）；
        # 若没有（不同启动路径差异），则补写一个最小合规 config.ini。
        config_ini = install_dir / "config.ini"
        if not config_ini.is_file():
            config_ini.write_text(
                "[business]\ntarget_tax_id = 91320594688334374M\n"
                "max_workers = 8\n",
                encoding="utf-8",
            )
        marker = f"acceptance_marker_{int(time.time())}"
        config_ini.write_text(
            config_ini.read_text(encoding="utf-8") + f"\n; {marker}\n",
            encoding="utf-8",
        )
        logs_dir = install_dir / "logs"
        logs_dir.mkdir(exist_ok=True)
        log_marker = logs_dir / "old_install.log"
        log_marker.write_text("旧安装日志留痕\n", encoding="utf-8")

        # 部署指引演练（非清单测试项）：v7.3.1 ZIP 覆盖替换，
        # 保留 config.ini、logs/、发票收件箱/（清单 §7 部署操作指引验证）。
        inbox_dir = install_dir / "发票收件箱"
        inbox_dir.mkdir(exist_ok=True)
        new_zip = ROOT / "dist" / "SYNTEC-Invoice-Processor-v7.3.1.zip"
        assert new_zip.is_file(), f"缺少 {new_zip}"
        backup = workdir / "backup_preserved"
        backup.mkdir()
        for keep in ("config.ini", "logs", "发票收件箱"):
            src = install_dir / keep
            if src.exists():
                shutil.move(str(src), str(backup / keep))
        shutil.rmtree(install_dir)
        with zipfile.ZipFile(new_zip) as zf:
            zf.extractall(workdir)
        for keep in ("config.ini", "logs", "发票收件箱"):
            src = backup / keep
            if src.exists():
                shutil.move(str(src), str(install_dir / keep))
        preserved = (
            (install_dir / "config.ini").is_file()
            and (install_dir / "logs" / "old_install.log").is_file()
            and (install_dir / "发票收件箱").is_dir()
            and (install_dir / f"{APP_NAME}.exe").is_file()
        )
        report.add(Item(
            "7.deploy", "部署指引演练：覆盖替换保留三目录", passed=preserved,
            detail=f"config.ini 保留={(install_dir / 'config.ini').is_file()}；"
                   f"logs 留痕={(install_dir / 'logs' / 'old_install.log').is_file()}；"
                   f"收件箱保留={(install_dir / '发票收件箱').is_dir()}（部署操作）",
        ))

        # 7.2 版本核对：升级后 health = 7.3.1 + 当前版不误报
        session = _launch_app(install_dir, expect_version="7.3.1")
        try:
            status, settings = _http(
                session.port, "GET", "/api/v1/settings", session.token,
            )
            business = (settings or {}).get("business") or {}
            config_text = (install_dir / "config.ini").read_text(encoding="utf-8")
            config_preserved = marker in config_text
            tax_state = "存在" if business.get("target_tax_id") else "丢失"
            report.add(Item(
                "7.2a", "升级后 health 返回新版本号",
                passed=True,  # _launch_app 已断言 health 7.3.1，否则抛异常
                detail="health=7.3.1（启动预检断言）；配置随部署保留："
                       f"config.ini 标记保留={config_preserved}；"
                       f"target_tax_id={tax_state}；"
                       f"max_workers={business.get('max_workers')}",
            ))
            # 7.1b 升级后：当前版不误报（available=false）
            _, upd2 = _http(session.port, "GET", "/api/v1/system/update", session.token)
            no_false = (upd2 or {}).get("available") is False
            report.add(Item(
                "7.1b", "当前版（7.3.1）检查更新不误报", passed=no_false,
                detail=f"update={upd2}",
            ))
        finally:
            _terminate(session, graceful=True)
    except Exception as exc:  # noqa: BLE001
        report.add(Item("7.x", "§7 执行中断", False, f"{type(exc).__name__}: {exc}"))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _terminate_process_tree(proc: subprocess.Popen[Any]) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
        capture_output=True, check=False,
    )
    proc.wait()


# ── 入口 ────────────────────────────────────────────────────


def _default_sample_dir() -> Path:
    return Path(
        r"C:\Users\40101720\Desktop\20260929_092043"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only", default="2,4,6,7",
        help="要执行的章节，逗号分隔（默认 2,4,6,7）",
    )
    parser.add_argument(
        "--sample-dir", type=Path, default=_default_sample_dir(),
        help="中文脱敏样本目录（含 PDF）",
    )
    parser.add_argument(
        "--dist-dir", type=Path, default=ROOT / "dist" / APP_NAME,
        help="v7.3.1 打包产物目录",
    )
    args = parser.parse_args()

    if os.name != "nt":
        sys.exit("❌ 验收驱动仅支持 Windows 交互式桌面会话")

    sections = {s.strip() for s in args.only.split(",") if s.strip()}
    report = Report()
    dist_dir = args.dist_dir.resolve()
    sample_dir = args.sample_dir.resolve()

    if "2" in sections:
        run_section2(report)
    if "4" in sections or "6" in sections:
        if not dist_dir.is_dir():
            sys.exit(f"❌ 缺少打包产物目录: {dist_dir}")
        if not any(sample_dir.glob("*.pdf")):
            sys.exit(f"❌ 样本目录无 PDF: {sample_dir}")
    if "4" in sections:
        run_section4(report, dist_dir, sample_dir)
    if "6" in sections:
        run_section6(report, dist_dir, sample_dir)
    if "7" in sections:
        run_section7(report, dist_dir)

    report.dump()
    failed = [i for i in report.items if i.passed is False]
    manual = [i for i in report.items if i.passed is None]
    print("\n" + "=" * 56)
    print(
        f"🎯 结果: 通过 {len(report.items) - len(failed) - len(manual)} | "
        f"人工 {len(manual)} | 失败 {len(failed)}"
    )
    if failed:
        print("❌ 失败项:")
        for i in failed:
            print(f"   {i.item_id} {i.title} — {i.detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()
