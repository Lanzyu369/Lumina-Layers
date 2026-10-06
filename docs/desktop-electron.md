# 桌面客户端（Electron）开发与使用指南

本文是 Electron 桌面客户端的**操作性手册**：如何准备环境、启动开发版、打包安装版，以及常见故障排查。架构设计背景见 [`electron-integration.md`](electron-integration.md)。

## 1. 三种运行形态

| 形态 | 启动方式 | 后端来源 | 前端来源 | 适用场景 |
|---|---|---|---|---|
| 纯 Web | Windows：`python start_all.py`；macOS/Linux：`python3 start_all.py` | 本机 Python 直跑 | Vite 开发服务器 | 日常开发、浏览器调试 |
| 桌面开发版 | `cd electron && pnpm start` | 主进程自动选择本机 Python 并启动 `api_server.py` | 主进程自动启动 Vite | 带原生窗口的开发调试 |
| 桌面安装版（当前仅 Windows） | `python scripts/build_desktop.py --workshop-seed-path <官方 seed>` 产出 NSIS 安装包 | PyInstaller 打包的 `lumina-backend.exe` | Vite 构建产物（本地文件加载） | 分发给最终用户 |

桌面开发版不需要先手动跑 `start_all.py`：Electron 主进程就是总指挥，会自己拉起并看管后端和前端子进程。

## 2. 环境准备（一次性）

按顺序执行以下四步；打包 Windows 安装版时还需要第 5 步。任何一步缺了，客户端都会在启动链路或构建链路的对应环节失败。下面先列 Windows PowerShell 命令：

```powershell
# 1) 后端 Python 依赖（建议较新的 Python 3.x；CI 基准为 3.12，3.14 亦验证可用）
python -m pip install -r requirements.txt
# requirements-glb-v2.txt 是可选的光栅预览依赖（rasterio），不装不影响启动

# 2) pnpm：版本由各 package.json 的 packageManager 字段钉死（当前 10.33.2）
#    若 `pnpm` 不在 PATH，两种解法任选：
corepack enable          # 需要管理员权限（写 Node 安装目录）
# 或免管理员，逐条命令前缀 corepack：
corepack pnpm --version

# 3) 前端依赖（frontend/ 与 electron/ 各自独立安装，不要在仓库根目录执行）
cd frontend; corepack pnpm install; cd ..

# 4) Electron 依赖（postinstall 会下载当前平台的 Electron 运行时）
cd electron; corepack pnpm install; cd ..

# 5) 仅打 Windows 安装包需要的 Python 构建工具
#    PyInstaller 不包含在 requirements.txt，避免给普通 Web/桌面开发用户增加依赖。
python -m pip install pyinstaller
```

macOS/Linux 的桌面开发环境使用 `python3`；当前打包脚本不支持在这些平台产出安装包：

```bash
python3 -m pip install -r requirements.txt
corepack enable
cd frontend && corepack pnpm install && cd ..
cd electron && corepack pnpm install && cd ..
```

手动安装和启动可以把命令写成 `corepack pnpm ...`；但 `scripts/build_desktop.py` 内部会直接调用 `pnpm`，所以打 Windows 安装包前必须通过 `corepack enable` 或其他方式确保裸 `pnpm` 已在 `PATH` 中。

**为什么不能合并成一个根目录 workspace**：2026-08 曾做过根目录 pnpm workspace 实验，因与"各目录独立安装"的既有约定冲突而放弃。上游采用的方案是在各子目录内分别声明安装脚本白名单：`frontend/` 用 `pnpm-workspace.yaml` 的 `allowBuilds`，`electron/` 用其 `package.json` 的 `pnpm.onlyBuiltDependencies`（如 esbuild、electron）。保持现状即可。

## 3. 启动桌面开发版

```powershell
cd electron
pnpm start        # 或 corepack pnpm start
```

主进程（`main.cjs`）的启动顺序，理解它有助于排查问题：

1. **清理端口**：Windows 用 `taskkill` 强制终止、macOS/Linux 用 `SIGTERM` 清理占用 8000（后端）和 4174（前端）的残留进程——所以不要指望同时跑一个独立 Web 会话再开桌面版，后者会终止前者；
2. **拉起后端**：优先选择项目虚拟环境中的解释器，否则 Windows 回退到 `python`、macOS/Linux 回退到 `python3`，再启动 `api_server.py` 并轮询 `/api/health`（超时后弹错误框退出）；
3. **拉起前端**：spawn `node frontend/node_modules/vite/bin/vite.js`，等 4174 端口就绪；
4. **开窗**：加载 `http://127.0.0.1:4174`，加载失败每 2 秒自动重试；期间显示 splash 过渡窗口。

其他行为：单实例锁（重复启动会聚焦已有窗口）；关闭窗口弹双语确认框；确认退出时收掉整棵子进程树——Windows 下对整棵进程树执行 `taskkill /T /F`，macOS/Linux 下向 detached 进程组发送 `SIGTERM`（`process.kill(-pid, "SIGTERM")`，失败时回退到单进程 `SIGTERM`），不会留后台残留。

## 4. 打生产安装包

此流程只产出 Windows NSIS 安装包。发布构建必须提供已经校验过的官方 `.lumina-workshop` seed；脚本不会在缺少它时悄悄产出不完整的发布包。

```powershell
# 发布包：显式传入官方 Workshop seed
$workshopSeed = "C:\path\to\official.lumina-workshop"
python scripts/build_desktop.py --workshop-seed-path $workshopSeed
```

也可设置 `WORKSHOP_SEED_PATH` 环境变量后执行同一命令。仅供本地开发验证、且明确接受不含官方 Workshop seed 的安装包时，使用：

```powershell
python scripts/build_desktop.py --allow-missing-workshop-seed
```

不要分发用 `--allow-missing-workshop-seed` 生成的安装包。脚本会依次构建 Vite 前端、PyInstaller 后端和 electron-builder 的 NSIS 安装器。产物在 `electron/dist_electron/Lumina Studio Setup x.y.z.exe`。注意打包机必须先完成第 2 节的环境准备（包括 `pyinstaller`）。

## 5. 日志与排障

Electron 日志（开发版与打包版都适用）的唯一规范位置是 `app.getPath("logs")/lumina-electron.log`。父目录由 Electron 按平台和当前应用名决定，开发版与打包版的应用名可能不同；常见形式为 Windows 的 `%APPDATA%\<应用名>\logs`、macOS 的 `~/Library/Logs/<应用名>`，Linux 则遵循 XDG 目录。不要把 `lumina-electron` 当作所有运行形态都固定不变的父目录。

开发版会把主进程、Python 后端和 Vite 的输出写入该文件；打包版前端直接加载本地构建产物，没有 Vite 子进程，因此日志只汇集主进程与内置后端的输出。

开发版后端的结构化 JSON Lines 日志默认在 `<repo>/logs/`。打包版没有仓库目录，且当前 one-file PyInstaller 后端没有单独的稳定结构化日志落点；排障时请以 `lumina-electron.log` 为准，不要尝试在安装目录或 `<repo>/logs/` 查找它。

| 症状 | 原因 | 处理 |
|---|---|---|
| 开发版启动即报 Backend Start Failed | Python 依赖未装或解释器不在 `PATH` | 补第 2 节第 1 步；Windows 用 `python --version`，macOS/Linux 用 `python3 --version` 自检 |
| 打包版启动即报 Backend Start Failed | 内置后端缺失、损坏或无法执行 | 先查看 `lumina-electron.log`，再重新安装；不要用本机 Python 依赖覆盖安装包 |
| `node_modules/electron/dist/` 缺少平台运行时（Windows 常见为 `electron.exe`） | 安装时构建脚本被 pnpm 拦截 | 在 `electron/` 重跑安装；检查其 `package.json` 的 `onlyBuiltDependencies` 含 `electron`；或 `pnpm approve-builds` |
| `pnpm` 无法识别 | 未全局启用 corepack | 用 `corepack pnpm ...` 替代，或管理员执行 `corepack enable` |
| 窗口白屏且日志反复 retry | Vite 未就绪或被杀 | 看 4174 是否被无关进程占用；确认没和其他工具抢端口 |
| 安装 Electron 依赖较慢 | `pnpm install` 正在下载当前平台的 Electron 运行时 | 等待安装完成；下载发生在安装阶段，不是应用启动阶段 |
| 开发版首次启动较慢 | Vite 冷启动 | 正常现象，后续启动通常会更快 |
| 打包时报 Workshop seed required | 未提供官方 Workshop seed | 发布包传 `--workshop-seed-path <路径>`；仅本地开发验证才用 `--allow-missing-workshop-seed` |
| 打包时报 `pyinstaller` 无法识别 | 未安装打包工具 | 执行 `python -m pip install pyinstaller` 后重试 |

项目级应急清场可使用仓库包装器。它只清理识别到的 Lumina 项目进程，与 Electron 启动时直接处理 8000/4174 监听者的逻辑并不完全等价：

```powershell
python start_all.py --kill   # 项目自带包装器，优先用它
```

```bash
python3 start_all.py --kill
```

## 6. 手动冒烟清单

改动 `main.cjs` / 打包配置 / 升级 Electron 版本后，过一遍：

1. `pnpm start` → 仅出现 1 个软件窗口 + 短暂 splash，全程无命令行黑框；后端 8000、前端 4174 就绪；
2. 点窗口 X → 弹中文确认框；取消=窗口保留，确认=窗口关闭且不再残留 `api_server.py` / `node vite`（打包版为内置后端）进程；
3. 设置里切 English 后再点 X → 确认框变英文；
4. （打包版）安装 Setup.exe → 双击启动只有 1 个 "Lumina Studio" 窗口，后台有 `lumina-backend.exe`，关窗后消失；
5. 回归确认纯 Web 模式不受影响：Windows 执行 `python start_all.py`，macOS/Linux 执行 `python3 start_all.py`。

Electron 自身单测：`cd electron && corepack pnpm test`（Node 内置 test runner，覆盖 workshop 安全边界与文件选择器）。
