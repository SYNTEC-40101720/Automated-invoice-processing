@echo off
REM ═══════════════════════════════════════════════════════════
REM SYNTEC 电子票据处理系统 - 打包脚本（符合域控环境规范）
REM 输出: dist\SYNTEC发票处理\SYNTEC发票处理.exe
REM
REM 域控规范要点:
REM   --onedir       单目录模式（打开速度快，避免单文件解压问题）
REM   --windowed     隐藏控制台
REM   --noupx        禁用 UPX 压缩（域控环境会阻止 UPX 压缩的 exe）
REM   --version-file 含 SYNTEC 的版本信息
REM   --name         必须以 SYNTEC 开头
REM
REM 注意: 项目路径必须为纯英文，否则 _internal 中 DLL 会缺失
REM ═══════════════════════════════════════════════════════════
setlocal

set APP_NAME=SYNTEC发票处理
set ICON=logo.ico
set VERSION_FILE=version_info.txt
set ENTRY=main.py

echo [1/3] 清理旧的构建产物...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist "%APP_NAME%.spec" del /q "%APP_NAME%.spec"

echo [2/3] 调用 PyInstaller 打包...
pyinstaller ^
    --onedir ^
    --windowed ^
    --noupx ^
    --clean ^
    --name "%APP_NAME%" ^
    --icon "%ICON%" ^
    --version-file "%VERSION_FILE%" ^
    --add-data "%ICON%;." ^
    --collect-all PySide6 ^
    "%ENTRY%"

if errorlevel 1 (
    echo.
    echo [错误] 打包失败
    exit /b 1
)

echo [3/3] 完成 - exe 位置: dist\%APP_NAME%\%APP_NAME%.exe
echo.
echo 验证版本信息:
powershell -Command "(Get-Item '.\dist\%APP_NAME%\%APP_NAME%.exe').VersionInfo | Format-List CompanyName, LegalCopyright, FileVersion, ProductName"
endlocal
