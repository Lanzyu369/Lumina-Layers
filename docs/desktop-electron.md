# 桌面客户端（Electron）源码运行指南

Electron 为 Python + React 应用提供原生窗口、文件选择与保存、创意工坊宿主和退出确认。运行环境仍需安装 Python、Node.js 及项目依赖。架构说明见 [`electron-integration.md`](electron-integration.md)。

## 1. 运行方式

| 方式 | 命令 | 后端 | 前端 |
|---|---|---|---|
| 浏览器 | `python start_all.py` | 本机 Python | Vite |
| 桌面窗口 | `cd electron` 后执行 `pnpm start` | 主进程启动 `api_server.py` | 主进程启动 Vite |

macOS/Linux 可使用 `python3`。桌面窗口会管理自己的后端和前端进程，无需先运行 `start_all.py`。

## 2. 原生 3MF 依赖

本分支支持普通 64 位 CPython 3.12～3.14：Windows x64、Linux x86-64
（glibc 2.28+）和 Apple Silicon macOS 14+。Intel Mac、Linux ARM、Alpine、
Windows ARM、32 位或 free-threaded Python 尚无完整应用所需的 wheel 组合。

3MF 导出链路使用两个独立依赖：

- 元数据 SDK：`fatcat-metadata==0.1.1`，Python 导入名为 `fatcat_metadata`。
  requirements 自动从
  [PyPI 0.1.1](https://pypi.org/project/fatcat-metadata/0.1.1/) 选择预编译包。
  Lumina 使用公共 SDK，不再应用 FatCat 补丁或添加 `+lumina.1` 版本后缀。
- 写包库：`neroued-3mf==0.4.0+fatcat.production.1`，由
  [公开 fork 的 GitHub Release](https://github.com/MOVIBALE/neroued_3mf/releases/tag/fatcat-production-1)
  提供相同 Python/系统/架构的预编译包。这是等待
  [上游 PR #17](https://github.com/Neroued/neroued_3mf/pull/17) 的临时兼容版本，
  属于写包库的版本，与 FatCat SDK 的版本独立。

### 使用预编译包

在下一节创建并激活干净的虚拟环境后，从 Lumina 仓库根目录执行：

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

无需克隆 SDK、准备本地 wheelhouse、指定源码 SHA、应用补丁或安装 C++ 编译器。
`requirements.txt` 对四个原生核心包要求二进制 wheel；平台或 Python 不匹配时会
在安装阶段失败。GitHub Release 资产可公开下载，不依赖有时限的 Actions artifact。
已有实验环境含旧版 `lumina-3mf-metadata-cpp` 或本地同版本构建时，建议重新创建
虚拟环境，避免共享包文件或旧依赖混入；这不是首次安装步骤。

如果之前安装过版本同为 `0.1.1` 的审核候选包，需替换成正式 PyPI 构建：

```bash
python -m pip install --force-reinstall --no-cache-dir --only-binary=:all: fatcat-metadata==0.1.1
```

### 维护者从源码构建

来源提交、仓库和版本由 `scripts/fatcat_packaging_contract.py`
统一维护。FatCat 来自公开仓库
[`MOVIBALE/fatcat-metadata`](https://github.com/MOVIBALE/fatcat-metadata)，固定
完整提交 `86a199c20e0277b519e1acbca6ea0d9a5ec5fbb1`。构建脚本从其根目录
的 `pyproject.toml` 构建 `0.1.1` wheel，无需进入 `cpp/`，不会修改 SDK 源码。
以下仅供维护者准备发行包或进行原生开发，普通源码运行
跳过本节。它需要 Git、CMake 和 C++20 编译器（FatCat 本身使用 C++17）。

writer 固定在公开提交 `a6043434d6cd9a2a76553ffdcdf0dda081d9b19c`，
版本为 `neroued-3mf==0.4.0+fatcat.production.1`。两个源码目录都应保持干净；
Lumina 不再保存或应用 writer 补丁。上游合并并正式发布后，再切换到官方版本。
从 Lumina 仓库根目录准备本地源码并构建：

```powershell
git clone https://github.com/MOVIBALE/fatcat-metadata ..\fatcat-metadata
git -C ..\fatcat-metadata checkout 86a199c20e0277b519e1acbca6ea0d9a5ec5fbb1
git clone https://github.com/MOVIBALE/neroued_3mf.git ..\neroued-3mf
git -C ..\neroued-3mf checkout a6043434d6cd9a2a76553ffdcdf0dda081d9b19c

python scripts/build_3mf_native_wheels.py `
  --fatcat-root ..\fatcat-metadata `
  --neroued-source ..\neroued-3mf `
  --install
```

构建产物可以提供给使用相同 Python、操作系统和 CPU 架构的机器。
`--install` 会校验 manifest 中的源码提交和 wheel SHA256，
先卸载旧的 `lumina-3mf-metadata-cpp`，再以 `--no-deps --force-reinstall` 安装
本次精确 wheel。两个包共用 `fatcat_metadata_data`，不能在新包安装后才卸载旧包。
本地修改 SDK 并以同一版本重新构建时也需要此安装步骤，不能只依赖普通 `pip install -r`。
已有当前构建产物时可运行 `python scripts/build_3mf_native_wheels.py --install-only`。
生成目录仅受控更新原生 wheel，其他文件保留。完成后再安装
`requirements.txt` 中的其余应用依赖。

SVG 运行时固定使用独立项目发布的 `lumina-svg-core==0.3.2`（AGPLv3）。
`requirements-native-svg.txt` 会从公开 PyPI 选择匹配 Python、系统和架构的安装包。
支持 Python 3.12～3.14；Linux x86-64 要求 glibc 2.28+，Mac 的 Python 3.12/3.13
安装包要求 macOS 12+，3.14 要求 macOS 14+。完整 Lumina 应用仍要求 macOS 14+，
由全部原生依赖的支持交集决定。已有开发环境可单独执行
`python -m pip install --upgrade -r requirements-native-svg.txt`。

## 3. 环境准备

先安装 Python 3.12～3.14、[Node.js 24.x LTS](https://nodejs.org/en/download)
和 [pnpm 10.33.2](https://pnpm.io/installation)；Node.js 22.x 必须至少为 22.13。
在仓库根目录创建虚拟环境：

```bash
python -m venv .venv
```

Windows PowerShell 用 `.\.venv\Scripts\Activate.ps1` 激活；macOS/Linux 用
`source .venv/bin/activate`（系统仅提供 `python3` 时，用它创建虚拟环境）。然后执行：

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
pnpm --dir frontend install --frozen-lockfile
pnpm --dir electron install --frozen-lockfile
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
| pnpm 无法识别 | 按 pnpm 官方安装说明安装 10.33.2；不要假定所有 Node.js 都自带 Corepack。 |

项目启动器残留可用 `python start_all.py --kill` 清理。只清理本项目启动的进程。

## 6. 验证

桌面测试使用 `pnpm --dir electron test`。修改启动、退出或窗口行为时，检查窗口能打开、退出确认有效、退出后自己的子进程已停止。修改前后端业务功能时，按实际受影响的功能运行测试。
