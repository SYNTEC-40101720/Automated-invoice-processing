# GitHub Release 发布 SOP

## 1. 目标

为 SYNTEC 电子票据处理系统建立一条可重复、可验证的 GitHub Release 发布流程：

```text
同步版本 -> 构建 -> 合规校验 -> 生成 ZIP + SHA-256 -> 上传 Release -> 验证
```

应用支持更新检查：启动时查询 GitHub 最新 Release，发现新版本时提示用户并跳转 Release 页面手动下载。**应用不在程序内下载或安装更新。**

版本号管理遵循 SemVer：版本只由 `bump_version.py` 显式递增；`build_syntec.py` 打包时校验版本源一致并拒绝已发布的版本号，保证 Release 标签与实际构建产物一一对应。

## 2. 发布参数表

| 参数 | 值 |
|---|---|
| GitHub 仓库 | `SYNTEC-40101720/Automated-invoice-processing` |
| 标签格式 | `vX.Y.Z`（三段数字版本） |
| Release 资产 | `SYNTEC-Invoice-Processor-vX.Y.Z.zip`（ASCII 文件名） |
| ZIP 顶层目录 | `SYNTEC-电子票据处理系统/`（完整安装目录） |
| 手动更新需保留 | `config.ini`、`logs/`、`发票收件箱/`（不打进 ZIP） |

## 3. 前置条件

- 应用有唯一、可比较的运行时版本，并同步包管理器、前端和 Windows 文件版本。
- GitHub 仓库的 Release 权限和发布工具已经验证，例如：

  ```powershell
  gh auth status --hostname github.com
  ```

## 4. 版本检查行为

应用调用固定仓库的 `GET https://api.github.com/repos/SYNTEC-40101720/Automated-invoice-processing/releases/latest`：

1. 只接受 `https` 的 GitHub API 响应。
2. 解析 `vX.Y.Z` 为数字元组后比较，禁止按字符串排序。
3. 网络错误、HTTP 错误、JSON 无效或标签无效时返回"检查未完成"，应用正常启动。
4. 只有最新版本大于当前版本时才提示新版本；不降级。
5. 资产选择用于横幅提示，要求文件名以 `SYNTEC-Invoice-Processor` 前缀开头且以 `.zip` 结尾，下载地址必须是固定仓库的 HTTPS 地址。

### 资产命名注意事项

GitHub 会自动重命名包含中文或部分特殊字符的 Release 资产名，导致前缀匹配失败。因此统一使用 ASCII 资产名 `SYNTEC-Invoice-Processor-vX.Y.Z.zip`。

## 5. Release 发布步骤

### 5.1 同步版本

统一递增版本并检查以下来源：

- `pyproject.toml` 运行时版本（`scripts/bump_version.py` 同步）
- `package.json` 前端版本
- Windows `FileVersion`、`ProductVersion`（`version_info.txt`）

**版本号规则（SemVer）**：

1. 版本号只通过 `python scripts/bump_version.py [patch|minor|major]` 显式递增；打包脚本不修改任何版本文件。
2. `bump_version.py` 拒绝递增到已有 tag 的版本号（本地或远端 `vX.Y.Z` 已存在即视为已发布或已占用）。
3. `build_syntec.py` 打包前校验五个版本源一致，并拒绝打包远端已有 tag 的版本号，防止重复发布。

```bash
python scripts/bump_version.py patch   # 补丁：bug 修复
python scripts/bump_version.py minor   # 次版本：新功能或有破坏性变更
python scripts/bump_version.py major   # 主版本：重大架构变化
```

### 5.2 构建

执行 `python scripts/build_syntec.py`，确认：

- 输出文件名以 `SYNTEC` 开头。
- CompanyName、ProductName、LegalCopyright 包含 `SYNTEC`。
- Windows 版本使用四段数字。
- 使用 `--onedir --windowed --noupx`。
- 在纯英文、无空格路径下执行 PyInstaller。

### 5.3 生成和上传资产

`build_syntec.py` 会在生成 ZIP 的同时落盘摘要文件 `dist/SYNTEC-Invoice-Processor-vX.Y.Z.zip.sha256`（格式：`<sha256>  <文件名>`），无需再手工执行 Get-FileHash。

创建 Release 并上传 ASCII 资产：

```powershell
gh release create vX.Y.Z `
  .\dist\SYNTEC-Invoice-Processor-vX.Y.Z.zip `
  --repo SYNTEC-40101720/Automated-invoice-processing `
  --title "vX.Y.Z" `
  --notes "Release notes"
```

发布后验证：

```powershell
gh release view vX.Y.Z --repo SYNTEC-40101720/Automated-invoice-processing --json tagName,isDraft,isPrerelease,url,assets
```

重点确认：

- `isDraft=false`
- `isPrerelease=false`
- 资产 `state=uploaded`
- 资产名仍为预期 ASCII 名称
- 资产大小合理
- GitHub digest 与本地 SHA-256 一致（以 `.zip.sha256` 文件为准）

## 6. 验收矩阵

| 场景 | 期望结果 |
|---|---|
| 当前版本低于 Release | `available=true`，横幅提示新版本 |
| 当前版本等于 Release | `available=false` |
| 当前版本高于 Release | 不降级，`available=false` |
| Release 无合规 ZIP | 横幅仍提示版本号，无资产信息 |
| 资产前缀错误 | 忽略资产 |
| 下载地址非固定仓库 HTTPS | 忽略资产 |
| 网络超时或 JSON 无效 | 检查未完成，不误报最新，应用正常启动 |

测试覆盖（全部自动化，不再做旧版升级演练）：

1. 更新检查单元测试：版本比较、资产选择、错误处理（`tests/application/test_update_checker.py`、`tests/api/test_update_endpoint.py`），随 §1.2 pytest 全绿判定。
2. 真实 GitHub API 联通性：发布后可在本机执行 `python -c "from invoice_processor.application.update_checker import check_for_update; print(check_for_update())"` 快速核对（当前版应 `available=false`）。

## 7. 故障处理

### 检测到新版本但看不到资产信息

依次检查：

1. GitHub Release 是否为稳定 Release（非 draft、非 prerelease）。
2. 资产是否为 ASCII 文件名。
3. 资产名是否以 `SYNTEC-Invoice-Processor` 开头。
4. `browser_download_url` 是否为固定仓库的 HTTPS 地址。
5. API 返回的资产是否已经被 GitHub 自动重命名。

### 手动更新后配置丢失

1. 停止使用并保留原安装目录的 `config.ini`、`logs/` 和 `发票收件箱/`。
2. 将它们复制回新安装目录对应位置。

## 8. 发布记录模板

```text
应用：
仓库：
当前版本：
目标版本：
Release URL：
资产名：
资产大小：
SHA-256：
主程序版本资源：
旧版检测结果：
当前版检测结果：
未覆盖的环境：
已知限制：
```

## 9. 发布记录

### v7.3.4（2026-10-03 发布）

```text
应用：SYNTEC-电子票据处理系统
仓库：SYNTEC-40101720/Automated-invoice-processing
当前版本：7.3.3
目标版本：7.3.4
Release URL：https://github.com/SYNTEC-40101720/Automated-invoice-processing/releases/tag/v7.3.4
资产名：SYNTEC-Invoice-Processor-v7.3.4.zip
资产大小：61.64 MB（64,630,958 字节）
SHA-256：5c0fa974d8d58b75f4e1fec479964435bd7c5075a2870efd713877bb63e3b14b（GitHub digest 一致）
主程序版本资源：CompanyName=SYNTEC，FileVersion/ProductVersion=[IP_ADDRESS]，LegalCopyright=Copyright © SYNTEC 2026
质量基线：217 条 Python 测试、Ruff、TypeScript、Vitest 17 条、Vite 构建通过；PyInstaller 域控合规通过
启动冒烟：health=7.3.4，日志无 CRITICAL，进程干净退出且端口释放
当前版检测结果：available=false 不误报（7.3.4 = Release 最新，实测核对）
桌面验收：§2+§4+§6 全量 16 项全过 0 失败；取消场景占位样本处理过快降级跳过（与 v7.3.2 相同特性，复跑 --only 6 仍降级，取消链路由单测覆盖）
已知限制：AI 提示注入与真实税控 PDF 语料版式验证不在范围（PROJECT_DEV 遗留项）
```

内容：14 条审查缺陷修复批次（邮箱拉取批次目录隔离、ZIP 成员名清洗与加密/损坏容错、拉取单飞锁、配置健壮性 %/BOM/GBK/密文损坏、乘车日期正则双花括号、三层类别判定、打车单程 100 元与高铁座位差标、Excel 公式注入防护、关窗等待任务终态）+ 前端 WS 事件游标重构（跨重启游标回退保护）；测试基线 168 → 217，Vitest 8 → 17。文档基线同步整合（ARCHITECTURE/PROJECT_DEV/README 版本历史与测试数统一）。

### v7.3.3（2026-10-02 发布）

```text
应用：SYNTEC-电子票据处理系统
仓库：SYNTEC-40101720/Automated-invoice-processing
当前版本：7.3.2
目标版本：7.3.3
Release URL：https://github.com/SYNTEC-40101720/Automated-invoice-processing/releases/tag/v7.3.3
资产名：SYNTEC-Invoice-Processor-v7.3.3.zip
资产大小：61.63 MB（64,625,902 字节）
SHA-256：8f85c9b3e99b69d85727151badc7f2271d42dee073ae6b3a91b3ea1814be0091
主程序版本资源：CompanyName=SYNTEC，FileVersion/ProductVersion=7.3.3.0，LegalCopyright=Copyright © SYNTEC 2026
质量基线：168 条 Python 测试、Ruff、TypeScript、Vitest 8 条、Vite 构建通过；PyInstaller 域控合规通过
启动冒烟：health=7.3.3，日志无 CRITICAL，进程干净退出且端口释放
桌面验收：§4 启动、输出目录打开和退出回收通过；12 份占位 PDF 无有效发票内容，completed_with_warnings（成功 0、失败 12），不作为业务识别验收
```

内容：设置页统一使用系统设置与本系统名称；替换侧栏、favicon 和桌面图标中的旧品牌图形；移除用户界面中的内部底座版本展示，并修正相关历史文档与发布说明。API 兼容字段保留。

### v7.3.2（2026-10-02 发布）

```text
应用：SYNTEC-电子票据处理系统
仓库：SYNTEC-40101720/Automated-invoice-processing
当前版本：7.3.1
目标版本：7.3.2
Release URL：https://github.com/SYNTEC-40101720/Automated-invoice-processing/releases/tag/v7.3.2
资产名：SYNTEC-Invoice-Processor-v7.3.2.zip
资产大小：61.69 MB（64,685,966 字节）
SHA-256：1d6abd3a49a0c520d30c11721d4e2987ecb27bda14f7d0d50314f75728672f21（GitHub digest 一致）
主程序版本资源：CompanyName=SYNTEC，FileVersion/ProductVersion=[IP_ADDRESS]
旧版检测结果：v7.3.1 视角 available=true latest=7.3.2（更新检测逻辑由 tests/application/test_update_checker.py 4 条单测覆盖）
当前版检测结果：v7.3.2 available=false 不误报（同上单测覆盖，§7 升级演练已于 101dc23 移除）
未覆盖的环境：WebView2/DPI 差异仍需目标环境验收（v7.3.1 已通过，本轮无渲染层变更）
已知限制：全部验收项自动判定（§2+§4+§6 16 项全过 0 人工）；取消场景在全量跑中因占位样本处理过快降级跳过，已单独复跑验证 cancel 200 → 终态 cancelled
```

内容：ARCHITECTURE §12.1 遗留评估项清零——发票 WS 空转等待 30s→0.5s + 断链监听任务（死链回收 ≤0.5s），GET /jobs/current 挂 JobSnapshotResponse 契约显式化；测试基线 165→168。附带修复：单实例互斥体测试 Linux CI 五连红（e71717a）。

### v7.3.1（2026-10-02 发布）

```text
应用：SYNTEC-电子票据处理系统
仓库：SYNTEC-40101720/Automated-invoice-processing
当前版本：7.3.0
目标版本：7.3.1
Release URL：https://github.com/SYNTEC-40101720/Automated-invoice-processing/releases/tag/v7.3.1
资产名：SYNTEC-Invoice-Processor-v7.3.1.zip
资产大小：61.69 MB（64,686,019 字节）
SHA-256：3bf2315ed2772b21c709973001faaf0e3150765b91cee1d0fba7fb84fc4ef300（GitHub digest 一致）
主程序版本资源：CompanyName=SYNTEC，FileVersion/ProductVersion=7.3.1.0
旧版检测结果：v7.2.1 视角 available=true latest=7.3.1（§7.1a）
当前版检测结果：v7.3.1 available=false 不误报（§7.1b）
未覆盖的环境：WebView2/DPI 差异仍需目标环境验收（v7.3.0 已通过，本轮无渲染层变更）
已知限制：更新检测全部由单测与验收脚本自动判定（§7 演练项已于 101dc23 移除，无人工观察项）
```

内容：事件总线融合二期 + 任务历史记录（含落地缺陷修复）+ 设置页版本信息改为运行时读取、health 响应返回底座版本字段；测试基线 150→165。
