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

至少执行两类测试：

1. 更新检查单元测试：版本比较、资产选择、错误处理（`tests/application/test_update_checker.py`、`tests/api/test_update_endpoint.py`）。
2. 真实 GitHub API 检查：旧版能发现当前 Release，当前版不误报。

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