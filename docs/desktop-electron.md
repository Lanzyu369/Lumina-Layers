# 桌面客户端（Electron）源码运行指南

Electron 为 Python + React 应用提供原生窗口、文件选择与保存、创意工坊宿主和退出确认。运行环境仍需安装 Python、Node.js 及项目依赖。架构说明见 [`electron-integration.md`](electron-integration.md)。

## 1. 运行方式

| 方式 | 命令 | 后端 | 前端 |
|---|---|---|---|
| 浏览器 | `python start_all.py` | 本机 Python | Vite |
| 桌面窗口 | `cd electron` 后执行 `pnpm start` | 主进程启动 `api_server.py` | 主进程启动 Vite |

macOS/Linux 可使用 `python3`。桌面窗口会管理自己的后端和前端进程，无需先运行 `start_all.py`。

## 2. 原生 3MF 依赖

Python 3.12 及以上的 3MF 导出链路要求 `wheelhouse/3mf` 中存在当前平台的
`fatcat-metadata` C++ wheel（Python 导入名为 `fatcat_metadata`）和已打补丁的
`neroued-3mf` wheel。当前元数据包构建版本固定为 `0.1.0+lumina.1`，来源提交、仓库、
writer 版本和补丁位置统一由 `scripts/fatcat_packaging_contract.py` 维护。
Fat Cat 来自公开仓库
[`MOVIBALE/fatcat-metadata`](https://github.com/MOVIBALE/fatcat-metadata)，固定
完整提交 `63326e2d0985cfd4873bbd44684a8a8f0a7b3f0b`。该提交包含上游 C++17
构建修正。构建脚本把 `--fatcat-root`
视为该仓库根目录，从根 `pyproject.toml` 构建 wheel；无需进入 `cpp/` 子目录。
CI 会匿名检出该提交，并在目标平台构建 wheel。构建脚本自动应用
`reference/fatcat-patches/fatcat-native-export-compatibility.patch`，沿用 SDK
已有的废料口标记修正，并补齐 OrcaSlicer 原生擦料塔占地默认值。

Lumina 在 `reference/neroued-patches/neroued-3mf-v0.4.0-b7.patch` 保存精确的 B7
补丁。生产 writer 仍固定在上游提交
`331ac6fa62a719f0dddacf9f005861b187d54f0c`，应用补丁后版本为
`neroued-3mf==0.4.0+fatcat.b7`。从 Lumina 仓库根目录准备本地源码并构建：

```powershell
git clone https://github.com/MOVIBALE/fatcat-metadata ..\fatcat-metadata
git -C ..\fatcat-metadata checkout 63326e2d0985cfd4873bbd44684a8a8f0a7b3f0b
git clone https://github.com/neroued/neroued_3mf.git ..\neroued-3mf
git -C ..\neroued-3mf checkout 331ac6fa62a719f0dddacf9f005861b187d54f0c
$writerPatch = (Resolve-Path .\reference\neroued-patches\neroued-3mf-v0.4.0-b7.patch).Path
git -C ..\neroued-3mf apply $writerPatch

python scripts/build_3mf_native_wheels.py `
  --fatcat-root ..\fatcat-metadata `
  --neroued-source ..\neroued-3mf `
  --install
```

不要把另一台机器生成的 wheel 直接复制进来；wheel 必须与当前 Python、操作系统
和 CPU 架构匹配。`--install` 会校验 manifest 中的源码提交和 wheel SHA256，
先卸载旧的 `lumina-3mf-metadata-cpp`，再以 `--no-deps --force-reinstall` 安装
本次精确 wheel。两个包共用 `fatcat_metadata_data`，不能在新包安装后才卸载旧包。
同一版本重新构建也需要此安装步骤，不能只依赖普通 `pip install -r`。
已有当前构建产物时可运行 `python scripts/build_3mf_native_wheels.py --install-only`。
生成目录仅受控更新原生 wheel，其他文件保留。完成后再执行下面的
`pip install -r requirements.txt`；原生依赖的构建流程也按此顺序安装。

SVG 运行时固定使用独立项目发布的 `lumina-svg-core==0.3.1`（AGPLv3）。
`requirements-native-svg.txt` 会从 GitHub Releases 选择匹配 Python、系统和架构的安装包。
支持 Python 3.12～3.14；Linux x86-64 要求 glibc 2.28+，Mac 的 Python 3.12/3.13
安装包要求 macOS 12+，3.14 要求 macOS 14+。没有兼容 wheel 时会从发行源码包构建，
需要 Git 和 C++17 编译器。已有开发环境可单独执行
`python -m pip install --upgrade -r requirements-native-svg.txt`。

## 3. 环境准备

使用 Python 3.12，在仓库根目录创建并激活 `.venv`，先按上一节准备当前平台的 3MF 依赖，再安装其余依赖：

```bash
python -m pip install -r requirements.txt
corepack enable
pnpm --dir frontend install
pnpm --dir electron install
```

运行测试时另外安装 `requirements-dev.txt`；仅在明确启用 PostgreSQL 后端时安装 `requirements-postgres.txt`，配置方法见 [server-mode-scaffold.md](server-mode-scaffold.md)。

`frontend/` 和 `electron/` 分别安装依赖；pnpm 版本由各目录的 `packageManager` 固定。Electron 安装时会下载当前平台的运行时，其安装脚本已在 `onlyBuiltDependencies` 中允许。`requirements-glb-v2.txt` 是可选光栅预览依赖。

## 4. 启动与退出

```bash
pnpm --dir electron start
```

主进程按以下顺序启动：

1. 选择可用的后端端口；若已保存端口被占用则选择其他空闲端口，不会终止占用者。确认本次后端健康后，才将端口保存到用户数据目录的 `backend-port.json`。前端使用 4174 端口，被占用时则报错退出。
2. 优先选择仓库 `.venv` 或 `venv` 中的 Python，再回退到 `PATH`，启动 `api_server.py`。后端健康检查必须确认响应来自本次启动的 Lumina 进程。
3. 启动 `frontend/node_modules/vite/bin/vite.js`，把选定的后端地址传给 Vite 代理。
4. 打开 `http://127.0.0.1:4174`，页面加载失败时自动重试。启动期间显示过渡窗口。

已记住的后端端口被其他程序占用时，桌面窗口选择空闲端口，确认本次 Python 进程健康后才记录新端口。前端继续使用固定的 Vite 地址；不会终止占用端口的其他进程。

重复启动会聚焦已有窗口。关闭主窗口会弹出当前语言的退出确认框；确认后停止本次启动的 Python、Vite 及其子进程。

## 5. 日志与排障

桌面日志在 `app.getPath("logs")/lumina-electron.log`，记录主进程、Python 和 Vite 输出。Python 的结构化日志默认在仓库 `logs/`；分析方式见 [`logging-guide.md`](logging-guide.md)。

| 症状 | 检查与处理 |
|---|---|
| Backend Start Failed | 确认所选 Python 已安装 `requirements.txt`，查看桌面日志中的解释器路径。 |
| 后端长时间未就绪 | 检查原生依赖是否匹配当前 Python 和平台，查看 Python 日志。 |
| 本地端口不可用 | 关闭自己不再使用的服务，再重试。 |
| 窗口白屏 | 查看 Vite 输出，确认前端依赖完整、4174 端口可用。 |
| Electron 运行时缺失 | 在 `electron/` 重跑 `pnpm install`，确认 Electron 安装脚本获准执行。 |
| pnpm 无法识别 | 执行 `corepack enable`，或使用 `corepack pnpm`。 |

项目启动器残留可用 `python start_all.py --kill` 清理。只清理本项目启动的进程。

## 6. 验证

桌面测试使用 `pnpm --dir electron test`。修改启动、退出或窗口行为时，检查窗口能打开、退出确认有效、退出后自己的子进程已停止。修改前后端业务功能时，按实际受影响的功能运行测试。
