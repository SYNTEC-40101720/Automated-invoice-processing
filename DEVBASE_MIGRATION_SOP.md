# Zy-DevBase 框架统一迁移 SOP

> **目标**：将发票项目中通用的、已验证的能力提升到 [Zy-DevBase](https://github.com/SYNTEC-40101720/Zy-DevBase) 基础仓库，使其成为后续所有 SYNTEC 桌面工具的基础轮子。
>
> **日期**：2026-09-05
> **状态**：已确认 14 项决策，待分批实施

## 当前执行进度

当前分支：`refactor/devbase-migration`

已完成：

- 业务包迁移到 `backend/invoice_processor`
- 纳入 `backend/devbase` 通用框架包
- 发票流水线增加同步执行入口，并注册为 `invoice_processing` Task
- 发票应用工厂复用 DevBase 安全层、生命周期和静态资源能力
- 标准 `/jobs/start`、`/jobs/cancel` 和运行时快照端点已接入
- 根入口支持桌面/浏览器调试模式
- NativeBridge 复用 DevBase 通用目录能力，保留发票专属方法
- `/api/v1/tools` 和前端 Sidebar 已接入工具清单
- 当前 Python 测试：`166 passed`

尚未完成：

- 旧 `/jobs` 业务兼容 API 还未完全切换为 DevBase 标准 JobRuntime 契约
- 发票事件总线与 DevBase 事件游标尚未统一
- 更新器、配置和日志仍保留发票项目扩展实现，后续再抽取公共部分
- 前端业务视图仍使用原有发票任务响应模型

---

## 决策汇总表

| # | 差异项 | 决策 | 提升范围 |
|---|---|---|---|
| 1 | 安全层（Token + CSP） | 完整提升，默认开启 | DevBase `api/app.py` + `api/dependencies.py` |
| 2 | `main.py` 双模式启动 | 完整提升 | DevBase `main.py` |
| 3 | `domain/ports.py` 端口契约 | 提升 `ProgressSink` + 扩展端口 | DevBase `domain/ports.py` |
| 4 | `ToolRegistry` + `Task` 清单 | 完整引入，支持链式串联 | DevBase `application/manifest.py` + `application/task.py` |
| 5a | 运行时命名 | 统一用 `JobRuntime` | DevBase `application/job_runtime.py` |
| 5b | 状态机丰富度 | 丰富状态机提升 | DevBase `domain/job.py` |
| 5c | `LifecyclePolicy` 窗口生命周期 | 留在 DevBase | DevBase `application/lifecycle.py` |
| 6 | `EventBus` 事件总线 | 两者融合（有界队列+游标重放） | DevBase `application/event_bus.py` |
| 7 | `ResourceProvider` 资源提供者 | 完整提升 | DevBase `domain/resources.py` |
| 8 | PyInstaller 打包 | `.spec` + 预检/后验脚本分离 | DevBase `devbase.spec` + `scripts/` |
| 9 | GitHub Release 自动更新体系 | 完整提升 | DevBase `desktop/update_*.py` + `application/update_checker.py` + 前端 + SOP |
| 10 | `NativeBridge` 本机桥接 | 通用方法提升，附扩展文档 | DevBase `desktop/native_bridge.py` |
| 11 | 前端共享组件 | 全部通用组件提升 | DevBase `web/src/` |
| 12 | 配置管理 + DPAPI 密钥 | 通用骨架提升 | DevBase `config_manager.py` + `secret_store.py` + `config.py` |
| 13 | `logger_config.py` 日志配置 | 提升，`log_name` 参数化 | DevBase `logger_config.py` |
| 14 | `bump_version.py` 版本同步 | 提升，路径适配 DevBase | DevBase `bump_version.py` |

---

## 各项迁移规格

### 1. 安全层（Token + CSP）

**来源**：发票项目 `src/api/app.py` + `src/api/dependencies.py`

**DevBase 目标文件**：
- `backend/devbase/api/app.py` — `create_app()` 增加 `local_token` 参数 + 安全头中间件
- `backend/devbase/api/dependencies.py` — 新增 `require_local_token` + `validate_websocket_token`

**验收标准**：
- [ ] `create_app(local_token="xxx")` 时所有 `/api/v1` 路由校验 `X-Local-Token` 头
- [ ] WebSocket `/events` 连接前校验 query 参数中的 token
- [ ] HTTP 响应包含 CSP / X-Content-Type-Options / Referrer-Policy 头
- [ ] `docs_url=None`，仅保留 `openapi.json`
- [ ] 不传 `local_token` 时自动生成随机 token

---

### 2. `main.py` 双模式启动

**来源**：发票项目无（DevBase 已有基础版，发票项目缺）

**DevBase 目标文件**：`main.py`（根目录）

**验收标准**：
- [ ] `python main.py` 默认桌面模式（pywebview）
- [ ] `python main.py --browser` 浏览器调试模式
- [ ] `python main.py --browser --reload` 配合 Vite 热更新
- [ ] `python main.py --no-browser` 启动服务不开浏览器
- [ ] `--host` / `--port` 可覆盖默认监听地址
- [ ] `PLATFORM_HOST` / `PLATFORM_PORT` 环境变量支持
- [ ] 缺少 `web/dist/index.html` 时提前报错提示构建前端
- [ ] 服务就绪后才打开窗口（轮询 HTTP 200）

---

### 3. `domain/ports.py` 端口契约

**来源**：发票项目无（新建，DevBase 已有 `ProgressSink`）

**DevBase 目标文件**：`backend/devbase/domain/ports.py`

**验收标准**：
- [ ] `ProgressSink` Protocol：`report_progress(fraction, message)` + `is_cancelled()`
- [ ] `@runtime_checkable` 结构化协议
- [ ] 扩展端口预留（如 `DisplaySink` 等，待实现时细化）
- [ ] domain 层零框架依赖
- [ ] `__all__` 导出完整

---

### 4. `ToolRegistry` + `Task` 声明式清单

**来源**：发票项目无（新建，DevBase 已有基础版）

**DevBase 目标文件**：
- `backend/devbase/application/manifest.py` — `ToolDescriptor` + `ToolRegistry`
- `backend/devbase/application/task.py` — `Task` Protocol + `TaskContext` + `TaskNotFoundError`

**验收标准**：
- [ ] `ToolDescriptor` 字段：kind/title/group/glyph/access_key/supports_input/mode/task
- [ ] `ToolRegistry.register(descriptor)` + `get(kind)` + `descriptors()` 按 group/kind 排序
- [ ] `Task` Protocol：`__call__(ctx: TaskContext, **kwargs) -> dict`
- [ ] `TaskContext` 实现 `ProgressSink`
- [ ] **链式串联**：支持 pipeline 模式，一个 kind 完成后自动触发下一个（发票 4 阶段需要）
- [ ] `GET /api/v1/tools` 返回已注册工具清单
- [ ] 前端侧边栏从清单动态渲染导航

---

### 5a. 运行时命名统一 `JobRuntime`

**来源**：发票项目 `JobService` → 重命名为 `JobRuntime`

**DevBase 目标文件**：`backend/devbase/application/job_runtime.py`

**验收标准**：
- [ ] 类名统一为 `JobRuntime`
- [ ] 发票项目后续改名同步

---

### 5b. 丰富状态机提升

**来源**：发票项目 `src/domain/job.py`

**DevBase 目标文件**：`backend/devbase/domain/job.py`

**验收标准**：
- [ ] `JobStatus`：QUEUED / RUNNING / CANCELLING / SUCCEEDED / COMPLETED_WITH_WARNINGS / CANCELLED / FAILED
- [ ] `JobTrigger`：MANUAL / INBOX / EMAIL
- [ ] `JobPhase`：SCAN / PROCESS / POST_PROCESS / LOCAL_AUDIT / AI_AUDIT / ARCHIVE / DONE
- [ ] `is_terminal` 属性覆盖所有终态
- [ ] 使用 `StrEnum`（Python 3.12）

---

### 5c. `LifecyclePolicy` 窗口生命周期

**来源**：DevBase 已有，发票项目后续接入

**DevBase 目标文件**：`backend/devbase/application/lifecycle.py`

**验收标准**：
- [ ] `LifecyclePolicy` 含 `close_mode` 配置
- [ ] `WindowLifecycle` 窗口关闭时按策略停止活跃任务
- [ ] 发票项目后续接入时通过 `create_app(lifecycle_policy=...)` 传入

---

### 6. `EventBus` 融合

**来源**：发票项目 `src/application/event_bus.py` + DevBase `InMemoryEventBus`

**DevBase 目标文件**：`backend/devbase/application/event_bus.py`

**验收标准**：
- [ ] `EventSubscription` 有界队列（`maxsize`）+ 关键事件不丢
- [ ] `_latest_progress` progress 去重（只保留最新一条）
- [ ] 阻塞读 `get(timeout)` 适配 WebSocket 循环
- [ ] `close()` 优雅关闭 + `EventStreamClosed` 异常
- [ ] `RuntimeSnapshot(events, event_cursor)` 游标重放
- [ ] WebSocket 重连时先发快照 + 从游标续推
- [ ] 线程安全（Condition + Lock）

---

### 7. `ResourceProvider` 资源提供者

**来源**：发票项目无（DevBase 已有，补全 key 体系）

**DevBase 目标文件**：`backend/devbase/domain/resources.py`

**验收标准**：
- [ ] `ResourceProvider` Protocol：`string(key, /, **kwargs) -> str`
- [ ] `InMemoryResourceProvider` 含基础 key 表（job 状态相关）
- [ ] `get_default()` 进程级单例
- [ ] 未知 key 原样返回，不报错
- [ ] 缺少格式参数时返回模板原文
- [ ] 可替换为 locale-aware 实现

---

### 8. PyInstaller 打包 `.spec` + 脚本分离

**来源**：发票项目 `build_syntec.py` + `version_info.txt`

**DevBase 目标文件**：
- `devbase.spec` — 标准 PyInstaller spec（双 exe：主程序 + 更新器）
- `scripts/precheck.py` — 版本一致性 + 中文路径检查
- `scripts/postverify.py` — 域控合规验证 + Release ZIP + SHA-256
- `scripts/build_release.py` — 一键串联：precheck → npm build → PyInstaller → postverify

**验收标准**：
- [ ] `.spec` 使用 `--noupx`（域控禁止 UPX）
- [ ] `.spec` 含双 EXE + COLLECT（主程序 + 更新器）
- [ ] `version_info.txt` 含 SYNTEC 命名规范
- [ ] `precheck.py` 校验 pyproject + package.json + version_info 版本一致
- [ ] `precheck.py` 检查项目路径纯英文
- [ ] `postverify.py` PowerShell 读 exe VersionInfo 确认 SYNTEC + 版本
- [ ] `postverify.py` 生成 Release ZIP + SHA-256
- [ ] `build_release.py` 一键完整流程

---

### 9. GitHub Release 自动更新体系

**来源**：发票项目 `src/desktop/update_helper.py` + `update_manager.py` + `update_protocol.py` + `src/application/update_checker.py` + `UpdateBanner.tsx` + `GITHUB_RELEASE_UPDATE_SOP.md`

**DevBase 目标文件**：
- `backend/devbase/desktop/update_helper.py` — 独立更新器
- `backend/devbase/desktop/update_manager.py` — 更新管理器
- `backend/devbase/desktop/update_protocol.py` — 协议常量
- `backend/devbase/application/update_checker.py` — 版本比较 + 资产选择
- `backend/devbase/api/routes/` — 更新端点
- `web/src/components/UpdateBanner.tsx` — 前端更新 UI
- `GITHUB_RELEASE_UPDATE_SOP.md` — SOP 文档

**验收标准**：
- [ ] 版本比较：semver 比较，选出最新 Release
- [ ] 资产选择：按命名规则匹配正确的 ZIP
- [ ] 下载：ZIP 到临时目录 + SHA-256 校验
- [ ] 触发更新器：写 ready 文件 → 启动独立 update_helper.exe
- [ ] 更新器接管：等主程序退出 → 解压替换 → 重启
- [ ] 回滚：替换失败时从备份恢复
- [ ] 前端 UpdateBanner 显示更新进度 + 应用按钮
- [ ] SOP 文档含完整流程 + 验收步骤

---

### 10. `NativeBridge` 本机桥接

**来源**：发票项目 `src/desktop/native_bridge.py`

**DevBase 目标文件**：`backend/devbase/desktop/native_bridge.py`

**提升范围（通用方法）**：
- `select_directory(title="选择文件夹") -> str` — title 参数化
- `open_directory(path) -> bool`
- `get_runtime_info() -> dict`

**留项目级（发票专属）**：
- `select_pdf_files()`
- `save_log_dialog()`
- `write_log(content)`

**验收标准**：
- [ ] 通用方法提升到 DevBase
- [ ] `select_directory` 的 title 可定制
- [ ] `open_directory` 含 `directory_checker` 回调
- [ ] `get_runtime_info` 返回 platform/webview2/version
- [ ] pywebview `window` 对象暴露 Python 方法
- [ ] 扩展模式文档说明如何添加业务方法

---

### 11. 前端共享组件

**来源**：发票项目 `web/src/`

**DevBase 目标文件**：`web/src/`

**提升范围（通用）**：
| 文件 | 说明 |
|---|---|
| `api/client.ts` | 含 token 注入、WS 重连 |
| `api/types.ts` | 含 JobResponse 等通用类型 |
| `stores/workbench.ts` | 比 useState 更成熟的状态管理 |
| `components/Sidebar.tsx` | 融合最完整版（折叠+拖拽+主题） |
| `components/StatusBar.tsx` | 版本/状态显示 |
| `components/BottomPanel.tsx` | 空态骨架，不含发票业务 |
| `components/UpdateBanner.tsx` | 配合更新体系 |

**留项目级（发票专属）**：
- `features/AuditView.tsx`
- `features/InboxView.tsx`
- `features/processing/ProcessingView.tsx`

**验收标准**：
- [ ] API client 自动注入 `X-Local-Token` 头
- [ ] API client WS 自动重连含游标恢复
- [ ] `workbench.ts` store 管理视图状态
- [ ] Sidebar 从 `/api/v1/tools` 动态渲染导航
- [ ] UpdateBanner 显示更新进度
- [ ] StatusBar 显示版本和连接状态
- [ ] 主题切换 system/light/dark
- [ ] `features/` 目录留空给派生项目

---

### 12. 配置管理 + DPAPI 密钥

**来源**：发票项目 `src/config_manager.py` + `src/secret_store.py` + `src/config.py`

**DevBase 目标文件**：
- `backend/devbase/config_manager.py` — 通用 INI 读写骨架
- `backend/devbase/secret_store.py` — DPAPI 加解密
- `backend/devbase/config.py` — 常量入口 + reload 模式
- `config.ini` — 模板：只有 `[app]` section（host/port/theme）

**验收标准**：
- [ ] `secret_store`：`encrypt(plain)` / `decrypt(cipher)` / `dpapi:` 前缀
- [ ] `secret_store`：非 Windows 降级 base64
- [ ] `config_manager`：`configparser` + 首次生成模板 + RLock
- [ ] `config_manager`：`get(section, key, default)` 通用读取
- [ ] `config.py`：`reload_config()` 热重载模式
- [ ] 模板 `config.ini` 只有 `[app]` section
- [ ] 派生项目追加业务 section 文档说明

---

### 13. `logger_config.py` 日志配置

**来源**：发票项目 `src/logger_config.py`

**DevBase 目标文件**：`backend/devbase/logger_config.py`

**验收标准**：
- [ ] `setup_logging(log_name="app.log")` 参数化
- [ ] PyInstaller 兼容（`sys.frozen` 判断 exe 路径）
- [ ] `RotatingFileHandler`（1MB + 5 备份）
- [ ] 幂等初始化（多次调用不重复加 handler）
- [ ] `logs/` 目录自动创建

---

### 14. `bump_version.py` 版本同步

**来源**：发票项目 `bump_version.py`

**DevBase 目标文件**：`bump_version.py`（根目录）

**验收标准**：
- [ ] 同步 5 个文件：`version.py` + `pyproject.toml` + `package.json` + `package-lock.json` + `version_info.txt`
- [ ] 路径适配 DevBase 结构（`backend/pyproject.toml` + `web/package.json`）
- [ ] `bump(version, level)` 三级递增（patch/minor/major）
- [ ] `--check` 只查不改
- [ ] `LegalCopyright` 年份自动更新
- [ ] Windows 版本四元组格式
- [ ] CLI：`python bump_version.py [patch|minor|major] [--check]`

---

## 实施优先级建议

| 批次 | 项 | 理由 |
|---|---|---|
| P0 | 1, 2, 3, 5a, 5b, 7, 6, 13 | 纯后端基础，互相依赖少，改动小 |
| P1 | 4, 5c | 依赖 ports + 状态机，架构核心 |
| P1 | 12, 14 | 配置 + 版本工具链 |
| P2 | 11 | 前端组件提升 |
| P2 | 8, 10 | 打包 + NativeBridge |
| P3 | 9 | 更新体系（最复杂，依赖前端+后端+打包） |

---

## 后续：发票项目适配

DevBase 升级完成后，发票项目需做的适配改动：
1. 包名从 `src.*` → 适配 DevBase 结构
2. `JobService` → `JobRuntime`
3. 发票流程拆为 4 个 `ToolDescriptor`（scan/process/audit/archive）
4. 删除发票项目中的提升代码副本，改为继承 DevBase
5. 补充发票专属业务 section 到 `config.ini`
6. 补充发票专属 `NativeBridge` 方法
7. 补充发票专属前端 Feature 视图
