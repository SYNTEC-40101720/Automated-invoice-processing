---
name: github-release-updater
description: "Use when implementing, reviewing, testing, packaging, or releasing a desktop application's GitHub Release auto-update flow, including version comparison, asset selection, ZIP verification, staged replacement, rollback, and release validation."
argument-hint: "说明应用平台、当前版本、安装目录、主程序/更新器名称和 Release 资产格式"
---

# GitHub Release 自动更新

## 适用场景

用于 Windows 桌面工具或其他可分发应用的 GitHub Release 自动更新。目标是让应用能够安全地：

1. 查询目标仓库的最新稳定 Release。
2. 判断最新版本是否高于当前版本。
3. 选择可信的安装资产并下载。
4. 校验大小、SHA-256 和 ZIP 内容。
5. 在主程序退出后替换安装目录并重启。
6. 在替换失败时保留或恢复旧版本。

## 先收集的参数

- GitHub 仓库：`OWNER/REPOSITORY`
- 版本来源：运行时版本、包管理器版本、Windows 文件版本等
- 主程序文件名和独立更新器文件名
- 安装目录、临时目录和用户数据目录
- Release 资产前缀与 ZIP 顶层目录名
- 需要保留的配置、日志、收件箱或用户数据
- 当前打包方式、目标平台和是否需要静默 GUI 更新

不要在未确认这些参数前假设资产名称、安装目录或用户数据位置。

## 推荐架构

### 1. 版本检查

使用 GitHub Releases API 的 `/releases/latest`：

- 只接受固定仓库的 `https://api.github.com` 响应。
- 解析 `vX.Y.Z` 或 `X.Y.Z`，按数字元组比较，不按字符串比较。
- 网络错误、JSON 错误或无效标签应返回“检查未完成”，不能误报“已是最新”。
- 只有版本高于当前版本时才选择安装资产。

### 2. 资产选择

- 资产名必须有应用专属前缀并以 `.zip` 结尾。
- 新项目优先使用纯 ASCII 名称，例如 `ProductName-v1.2.3.zip`。
- GitHub 会自动重命名包含中文或其他特殊字符的 Release 文件名；不要把中文文件名作为自动更新契约。
- 只接受固定仓库 `releases/download/` 下的 HTTPS 下载地址。
- 同一 Release 中有多个资产时，明确选择规则，不要选第一个任意 ZIP。
- 可兼容历史资产名时，增加明确的旧前缀，不要放宽为任意 ZIP。

### 3. 下载与校验

- 下载到临时目录，不直接写入安装目录。
- 限制最大下载大小，按流式读取累计大小。
- Release 提供 `digest` 时校验 SHA-256；摘要不匹配必须拒绝安装。
- 拒绝空文件、超大文件和非 ZIP 内容。
- ZIP 解压前检查每个成员的解析后路径必须位于解压根目录内。
- 拒绝符号链接或其他会逃逸解压目录的成员。
- 解压后必须找到唯一的主程序文件，并检查更新器和运行时依赖。

### 4. 安装替换

推荐由独立更新器执行：

1. 主程序下载并解压完成后，把更新器复制到临时目录。
2. 关闭主程序，更新器等待主进程退出。
3. 将旧安装目录移动到同一卷的备份目录。
4. 将解压后的新目录移动到安装目录。
5. 从旧目录恢复配置、日志和其他用户数据。
6. 启动新版本。
7. 新版本启动成功或替换流程完成后再删除旧目录。

关键约束：

- 临时备份目录必须和安装目录位于同一磁盘卷；Windows 不能跨盘 `rename`。
- 跨盘场景不要直接调用目录 `rename`。要么把 staging/backup 放到目标目录父级，要么实现明确的复制式替换和回滚。
- 在“旧目录移动成功”之前，异常处理不得删除原安装目录。
- 替换失败时，只有在确认新目录已创建后才删除新目录，并把旧备份恢复回目标位置。
- 用户数据恢复失败也必须触发回滚或明确阻止启动，不能静默丢配置。
- 更新器自身不能从正在被替换的安装目录运行，应先复制到临时目录。

## Release 发布流程

1. 递增一个新的 `X.Y.Z` 版本，并同步所有运行时、前端、包元数据和 Windows 资源字段。
2. 构建前端和桌面包；Windows/PyInstaller 项目确认 `SYNTEC` 文件名、版本资源和 `--noupx` 等域控要求。
3. 生成完整 ZIP，保留固定顶层目录，例如：

   ```text
   ProductName-vX.Y.Z.zip
   └── ProductName/
       ├── ProductName.exe
       ├── ProductName-updater.exe
       └── _internal/
   ```

4. 计算并记录 SHA-256。
5. 创建稳定 Release，标签使用 `vX.Y.Z`，不要使用 Draft 或 Pre-release 作为生产更新源。
6. 上传 ASCII 文件名的 ZIP。
7. 通过 GitHub API 或 `gh release view` 验证资产名、大小、digest 和 `uploaded` 状态。
8. 从旧版本执行一次真实检查：应得到 `available=true` 且 `installable=true`。
9. 从当前版本执行一次真实检查：应得到 `available=false`。
10. 记录 Release URL、资产名、摘要、测试结果和已知限制。

## 必测矩阵

- 当前版本低于 Release：发现更新且可安装
- 当前版本等于 Release：不提示更新
- Release 版本更低：不降级
- Release 无合规 ZIP：`installable=false`
- 资产名错误、非固定仓库 URL 或非 HTTPS：拒绝
- 网络超时、HTTP 错误、无效 JSON、无效版本标签
- 空文件、超大文件、SHA-256 不匹配
- ZIP 路径穿越、符号链接、缺少主程序、多个候选目录
- 主进程仍在运行、安装目录不可写、跨盘临时目录
- 替换失败后的旧目录恢复、配置和日志保留
- 更新器从临时目录运行并成功重启

## 代码审查重点

重点找以下高风险问题：

- 用字符串排序版本号。
- 接受任意 Release 或任意下载域名。
- 只检查扩展名，不检查资产前缀和下载 URL。
- ZIP 直接解压到安装目录。
- 先删除旧目录，再尝试移动新目录。
- 异常处理在跨盘 `rename` 失败时删除原目录。
- 更新器运行在即将被替换的目录内。
- 未保留用户配置、日志或业务数据。
- 只测了单元测试，没有用真实旧版本调用 GitHub API。

## 输出验收报告

完成任务时至少报告：

- 当前版本、目标版本和 Release URL
- 最终资产名、文件大小和 SHA-256
- 主程序/更新器是否存在及版本元数据
- 旧版检测、当前版检测和替换冒烟结果
- 配置、日志和用户数据是否保留
- 未执行的真实机台、域控或干净环境测试
