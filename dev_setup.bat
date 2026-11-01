@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   Lumina Studio - 多机开发环境初始化 (dev_setup)
echo   适用于：换机器 / 移动硬盘盘符变动后，重建本地开发环境
echo ============================================================
echo.

REM ---------- 1. 定位 Python ----------
where python >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 python，请先安装 Python 3.13 并勾选 Add to PATH
    goto :fail
)
for /f "delims=" %%v in ('python -c "import sys; print(str(sys.version_info.major) + chr(46) + str(sys.version_info.minor))"') do set "PYVER=%%v"
echo [1/5] 检测到 Python !PYVER!
if not "!PYVER!"=="3.13" (
    echo [警告] 项目在 Python 3.13 上验证过，当前为 !PYVER!，可能出现依赖兼容问题。
)
echo.

REM ---------- 2. 准备 .venv ----------
echo [2/5] 准备虚拟环境 .venv ...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if errorlevel 1 (
        echo        现有 .venv 不可用（换机器/盘符），正在重建...
        rmdir /s /q ".venv"
    )
)
if not exist ".venv\Scripts\python.exe" (
    python -m venv ".venv"
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败
        goto :fail
    )
)
echo        虚拟环境就绪
echo.

REM ---------- 3. 安装 Python 依赖 ----------
echo [3/5] 安装 Python 依赖 (requirements.txt) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] Python 依赖安装失败
    goto :fail
)
set /p "GLB=        是否安装可选 GLB 原生加速依赖 (rasterio/manifold3d)？[y/N]: "
if /i "!GLB!"=="y" (
    ".venv\Scripts\python.exe" -m pip install -r requirements-glb-v2.txt
)
echo.

REM ---------- 4. 准备 pnpm ----------
echo [4/5] 准备 pnpm ...
where pnpm >nul 2>&1
if errorlevel 1 (
    echo        未找到 pnpm，正在安装 pnpm@10.33.2 ...
    call npm install -g pnpm@10.33.2
    if errorlevel 1 (
        echo [错误] pnpm 安装失败
        goto :fail
    )
)
for /f "delims=" %%v in ('pnpm --version') do set "PNPMVER=%%v"
echo        pnpm !PNPMVER!
echo.

REM ---------- 5. 安装前端 / Electron 依赖 ----------
echo [5/5] 安装前端与 Electron 依赖 ...
pushd frontend
call pnpm install
if errorlevel 1 (
    popd
    echo [错误] frontend 依赖安装失败
    goto :fail
)
popd

pushd electron
call pnpm install
if errorlevel 1 (
    popd
    echo [错误] electron 依赖安装失败
    goto :fail
)
popd
echo.

echo ============================================================
echo   初始化完成！双击 start_app.bat 启动开发环境
echo ============================================================
pause
exit /b 0

:fail
echo.
echo 初始化未完成，请根据上面的错误信息排查。
pause
exit /b 1
