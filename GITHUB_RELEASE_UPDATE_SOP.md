# GitHub Release 自动更新 SOP

## 1. 目标

为 Windows 桌面工具建立一条可重复、可验证、可回滚的 GitHub Release 自动更新链路：

```text
查询 Release -> 比较版本 -> 选择资产 -> 下载校验 -> 安全解压
-> 关闭主程序 -> 同盘替换 -> 恢复用户数据 -> 重启 -> 验收
```

这份 SOP 适用于 Python/PyInstaller、.NET 或其他能生成独立安装目录的桌面应用。文中的应用名、仓库名、文件名和目录均为参数，不应直接照抄。

## 2. 跨项目参数表

| 参数 | 示例 | 说明 |
|---|---|---|
| GitHub 仓库 | `OWNER/REPOSITORY` | 只允许一个可信仓库 |
| 标签格式 | `v1.2.3` | 使用三段数字版本 |
| 主程序 | `SYNTEC-电子票据处理系统.exe` | 必须存在于安装目录根部 |
| 更新器 | `SYNTEC-电子票据更新器.exe` | 必须能脱离主程序运行 |
| Release 资产 | `SYNTEC-Invoice-Processor-v1.2.3.zip` | 使用 ASCII 文件名 |
| ZIP 顶层目录 | `SYNTEC-电子票据处理系统/` | 解压后包含完整安装目录 |
| 安装目录 | `D:\Apps\Product` | 运行时目录，通常位于 D 盘或其他数据盘 |
| 保留数据 | `config.ini`、`logs/`、业务数据 | 替换时必须明确列出 |

## 3. 前置条件

- 应用有唯一、可比较的运行时版本，并同步包管理器、前端和 Windows 文件版本。
- GitHub 仓库的 Release 权限和发布工具已经验证，例如：

  ```powershell
  gh auth status --hostname github.com
  ```

- 已明确当前安装目录、主程序名、更新器名和必须保留的用户数据。
- 主程序和更新器都能在目标 Windows 环境启动。
- 更新器不会依赖正在被替换的安装目录中的自身文件。

## 4. 版本检查实现

调用固定仓库的：

```text
GET https://api.github.com/repos/OWNER/REPOSITORY/releases/latest
```

实现要求：

1. 只接受 `https` 的 GitHub API 响应。
2. 解析 `vX.Y.Z` 或 `X.Y.Z` 为数字元组后比较，禁止按字符串排序。
3. 网络错误、HTTP 错误、JSON 无效或标签无效时返回“检查未完成”。
4. 只有最新版本大于当前版本时才继续选择安装资产。
5. 版本相同或最新版本更低时不允许降级。

资产选择必须同时满足：

- 文件名以应用专属前缀开头。
- 文件名以 `.zip` 结尾。
- 资产名是单一文件名，不包含路径。
- `browser_download_url` 是固定仓库的 `https://github.com/.../releases/download/` 地址。
- 需要兼容旧包时，显式列出旧前缀，不要放宽成“任意 ZIP”。

### 资产命名注意事项

GitHub 会自动重命名包含中文或部分特殊字符的 Release 资产名。中文资产名可能被保存成类似 `Product-.-v1.2.3.zip`，导致本地更新器的前缀匹配失败。

因此新项目统一使用 ASCII 资产名，例如：

```text
SYNTEC-Invoice-Processor-v7.0.5.zip
ProductName-v1.2.3.zip
```

## 5. 下载、校验和解压

下载阶段：

- 写入临时目录，不直接覆盖安装目录。
- 使用流式读取并限制最大下载大小。
- Release 提供 `digest` 时校验 SHA-256；校验失败立即拒绝。
- 拒绝空文件和不符合预期的内容类型。

解压阶段：

- 每个 ZIP 成员的解析后路径必须位于解压根目录内。
- 拒绝 `../` 路径穿越、绝对路径和符号链接。
- 解压后检查主程序、更新器和运行时依赖是否存在。
- 允许 ZIP 顶层目录固定，也可以实现“唯一包含主程序的目录”发现，但不能静默选择多个候选目录。

推荐的安装包结构：

```text
ProductName-v1.2.3.zip
└── ProductName/
    ├── ProductName.exe
    ├── ProductName-updater.exe
    └── _internal/
```

## 6. 替换和回滚

推荐使用独立更新器，并按以下顺序执行：

1. 主程序完成下载和解压。
2. 将更新器复制到临时目录。
3. 主程序退出，更新器等待主进程消失。
4. 将旧安装目录移动到同一磁盘卷的备份目录。
5. 将新目录移动到原安装路径。
6. 从旧目录恢复配置、日志和业务数据。
7. 启动新程序。
8. 替换和启动流程确认成功后删除旧备份。

### 必须遵守的安全规则

- 临时目录、备份目录和安装目录必须位于同一磁盘卷。Windows 不能跨盘执行目录 `rename`。
- 如果必须跨盘操作，使用明确的复制式替换、校验和回滚，不要直接把 `rename` 当成跨盘移动。
- 在旧目录移动成功前，异常处理绝不能删除原安装目录。
- 新目录替换失败时，恢复旧备份；恢复失败必须保留现场并报告错误。
- 用户数据恢复失败也必须触发回滚或阻止启动，不能静默丢失配置。
- 更新器自身应先复制到临时目录再运行，避免替换时锁住旧安装目录。
- 更新成功后再清理旧备份和临时文件；失败现场至少保留更新日志。

伪代码顺序：

```python
wait_for_process_exit(pid)
old_dir = target_dir.parent / backup_name  # 与 target_dir 同一卷
try:
    target_dir.rename(old_dir)
    source_dir.rename(target_dir)
    restore_user_data(old_dir, target_dir)
    start_application(target_dir)
except Exception:
    if target_dir.exists():
        remove_path(target_dir)
    if old_dir.exists() and not target_dir.exists():
        old_dir.rename(target_dir)
    raise
else:
    remove_path(old_dir)
```

注意：`target_dir.rename(old_dir)` 本身失败时，不能先执行 `remove_path(target_dir)`。应先判断旧目录是否已经成功移动，或把清理动作放在对应的成功分支内。

## 7. Release 发布步骤

### 7.1 同步版本

统一递增版本并检查以下来源：

- Python/C# 运行时版本
- `package.json`、锁文件或其他前端版本
- Windows `FileVersion`、`ProductVersion`
- Release 标签

### 7.2 构建

根据项目技术栈执行构建。Python/PyInstaller 的 SYNTEC 域控项目还应确认：

- 输出文件名以 `SYNTEC` 开头。
- CompanyName、ProductName、LegalCopyright 包含 `SYNTEC`。
- Windows 版本使用四段数字。
- 使用 `--onedir --windowed --noupx`，并包含独立更新器。
- 在纯英文、无空格路径下执行 PyInstaller。

### 7.3 生成和上传资产

生成完整 ZIP 后计算摘要：

```powershell
Get-FileHash .\dist\ProductName-v1.2.3.zip -Algorithm SHA256
```

创建 Release 并上传 ASCII 资产：

```powershell
gh release create v1.2.3 `
  .\dist\ProductName-v1.2.3.zip `
  --repo OWNER/REPOSITORY `
  --title "v1.2.3" `
  --notes "Release notes"
```

发布后验证：

```powershell
gh release view v1.2.3 --repo OWNER/REPOSITORY --json tagName,isDraft,isPrerelease,url,assets
```

重点确认：

- `isDraft=false`
- `isPrerelease=false`
- 资产 `state=uploaded`
- 资产名仍为预期 ASCII 名称
- 资产大小合理
- GitHub digest 与本地 SHA-256 一致

## 8. 验收矩阵

| 场景 | 期望结果 |
|---|---|
| 当前版本低于 Release | `available=true`、`installable=true` |
| 当前版本等于 Release | `available=false` |
| 当前版本高于 Release | 不降级，`available=false` |
| Release 无合规 ZIP | `installable=false` |
| 资产前缀错误 | 忽略资产 |
| 下载地址非固定仓库 HTTPS | 忽略资产 |
| 网络超时或 JSON 无效 | 检查未完成，不误报最新 |
| SHA-256 不匹配 | 拒绝安装 |
| ZIP 路径穿越或符号链接 | 拒绝解压 |
| 缺少主程序或更新器 | 拒绝安装 |
| 主进程仍运行 | 等待或返回忙碌，不覆盖文件 |
| 临时目录与目标目录跨盘 | 阻止 `rename`，不得删除旧目录 |
| 替换失败 | 恢复旧目录，保留日志 |
| 配置和日志存在 | 更新后仍存在且内容不变 |
| 更新成功 | 新程序启动，旧备份再清理 |

至少执行三类测试：

1. 更新器单元测试：版本、资产、摘要、ZIP 安全和回滚路径。
2. 真实 GitHub API 检查：旧版能发现当前 Release，当前版不误报。
3. Windows 安装目录冒烟：真实关闭、替换、恢复数据和重启。

## 9. 故障处理

### 检测到更新但不可安装

依次检查：

1. GitHub Release 是否为稳定 Release。
2. 资产是否为 ASCII 文件名。
3. 资产名是否符合应用专属前缀。
4. `browser_download_url` 是否为固定仓库的 HTTPS 地址。
5. API 返回的资产是否已经被 GitHub 自动重命名。

### 更新后配置丢失

1. 立即停止再次更新。
2. 保留更新日志和旧备份目录。
3. 检查保留数据清单是否包含实际配置、日志和业务目录。
4. 从旧备份恢复后再启动应用。
5. 修复数据恢复和异常回滚顺序，再重新打包发布。

### Windows 报跨盘移动错误

通常是 `WinError 17`。检查临时备份目录是否位于 `%TEMP%` 的 C 盘，而安装目录位于 D 盘。将 staging 和 backup 改到安装目录父级，或实现复制式替换；禁止通过删除旧目录来绕过错误。

## 10. 发布记录模板

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
更新器版本资源：
旧版检测结果：
当前版检测结果：
配置/日志保留结果：
Windows 冒烟结果：
未覆盖的环境：
已知限制：
```

## 11. 本项目落地示例

本项目已在 2026-08-29 验证以下实现：

- Release：`v7.0.5`
- 资产：`SYNTEC-Invoice-Processor-v7.0.5.zip`
- 资产 SHA-256：`08fe89c0e13e5b9029e103d6c56703e42fb1c15b1a4f13400894906d125d1895`
- `7.0.4` 检测结果：发现 `7.0.5`，可安装
- `7.0.5` 检测结果：无可用更新
- 完整 Python 测试：`140 passed`
- 额外修复：GitHub 中文资产名自动重命名；更新器改用 ASCII 资产名并兼容历史名称

### 2026-08-31 发布记录：v7.0.11

- 应用：SYNTEC 电子票据处理系统
- 仓库：`SYNTEC-40101720/Automated-invoice-processing`
- 当前版本：`7.0.10`
- 目标版本：`7.0.11`
- Release URL：https://github.com/SYNTEC-40101720/Automated-invoice-processing/releases/tag/v7.0.11
- 资产：`SYNTEC-Invoice-Processor-v7.0.11.zip`
- 资产大小：`53,967,838` bytes（约 51.47 MiB）
- 资产 SHA-256：`e5c9e26753e251bfa7640141d0bc641319f2e9c34d21d406ec742e15651df8f8`
- 主程序/更新器版本资源：`7.0.11.0`；CompanyName 为 `SYNTEC`；语言为中性
- ZIP 结构：单一顶层目录，包含主程序、独立更新器和 `_internal/web/dist/index.html`
- 完整 Python 测试：`144 passed`
- 前端构建：`npm run build` 通过
- 旧版检测、当前版检测：本次未执行真实旧安装目录检查
- 配置、日志和业务数据保留：本次未执行 Windows 安装替换冒烟
- 未覆盖环境：真实域控机器、干净 Windows 环境和实际更新替换/回滚流程
