# 桌面客户端（Electron）开发与使用指南

本文是 Electron 桌面客户端的**操作性手册**：如何准备环境、启动开发版、打包安装版，以及常见故障排查。架构设计背景见 [`electron-integration.md`](electron-integration.md)。

## 1. 三种运行形态

| 形态 | 启动方式 | 后端来源 | 前端来源 | 适用场景 |
|---|---|---|---|---|
| 纯 Web | `python start_all.py` | 本机 Python 直跑 | Vite 开发服务器 | 日常开发、浏览器调试 |
| 桌面开发版 | `cd electron && pnpm start` | 主进程自动 spawn `python api_server.py` | 主进程自动 spawn Vite | 带原生窗口的开发调试 |
| 桌面安装版 | `python scripts/build_desktop.py` 产出 NSIS 安装包 | PyInstaller 打包的 `lumina-backend.exe` | Vite 构建产物（本地文件加载） | 分发给最终用户 |

桌面开发版不需要先手动跑 `start_all.py`：Electron 主进程就是总指挥，会自己拉起并看管后端和前端子进程。

## 2. 环境准备（一次性）

按顺序执行以下四步；任何一步缺了，客户端都会在启动链路的对应环节失败。

```powershell
# 1) 后端 Python 依赖（建议较新的 Python 3.x；CI 基准为 3.12，3.14 亦验证可用）
pip install -r requirements.txt
# requirements-glb-v2.txt 是可选的光栅预览依赖（rasterio），不装不影响启动

# 2) pnpm：版本由各 package.json 的 packageManager 字段钉死（当前 10.33.2）
#    若 `pnpm` 不在 PATH，两种解法任选：
corepack enable          # 需要管理员权限（写 Node 安装目录）
# 或免管理员，逐条命令前缀 corepack：
corepack pnpm --version

# 3) 前端依赖（frontend/ 与 electron/ 各自独立安装，不要在仓库根目录执行）
cd frontend; corepack pnpm install; cd ..

# 4) Electron 依赖（postinstall 会下载约 200MB 的 electron.exe 二进制）
cd electron; corepack pnpm install; cd ..
```

**为什么不能合并成一个根目录 workspace**：2026-08 曾做过根目录 pnpm workspace 实验，因破坏 Docker 构建、与"各目录独立安装"的既有约定冲突而放弃。上游采用的方案是在各子目录内分别声明安装脚本白名单：`frontend/` 用 `pnpm-workspace.yaml` 的 `allowBuilds`，`electron/` 用其 `package.json` 的 `pnpm.onlyBuiltDependencies`（如 esbuild、electron）。保持现状即可。

## 3. 启动桌面开发版

```powershell
cd electron
pnpm start        # 或 corepack pnpm start
```

主进程（`main.cjs`）的启动顺序，理解它有助于排查问题：

1. **清理端口**：强杀占用 8000（后端）和 4174（前端）的残留进程——所以不要指望同时跑一个独立 Web 会话再开桌面版，后者会把前者杀掉；
2. **拉起后端**：spawn `python api_server.py`，轮询 `/api/health`（超时后弹错误框退出）；
3. **拉起前端**：spawn `node frontend/node_modules/vite/bin/vite.js`，等 4174 端口就绪；
4. **开窗**：加载 `http://127.0.0.1:4174`，加载失败每 2 秒自动重试；期间显示 splash 过渡窗口。

其他行为：单实例锁（重复启动会聚焦已有窗口）；关闭窗口弹双语确认框；确认退出时收掉整棵子进程树——Windows 下对整棵进程树执行 `taskkill /T /F`，macOS/Linux 下向 detached 进程组发送 `SIGTERM`（`process.kill(-pid, "SIGTERM")`，失败时回退到单进程 `SIGTERM`），不会留后台残留。

## 4. 打生产安装包

```powershell
python scripts/build_desktop.py
```

脚本串联三步：Vite 构建前端 → PyInstaller 按 `lumina_studio.spec` 打后端 → electron-builder 出 NSIS 安装器。产物在 `electron/dist_electron/Lumina Studio Setup x.y.z.exe`。注意打包机必须先完成第 2 节的环境准备。

## 5. 日志与排障

日志位置（dev 与打包版相同）：以 Electron `app.getPath("logs")` 为准，文件名为 `lumina-electron.log`（主进程和两个子进程的输出都汇到这里；后端自身的结构化日志仍在 `<repo>/logs/` 下）。Windows 示例：`%APPDATA%\lumina-electron\logs\lumina-electron.log`；macOS 示例：`~/Library/Logs/lumina-electron/lumina-electron.log`；Linux 遵循 XDG 规范。

| 症状 | 原因 | 处理 |
|---|---|---|
| 启动即报 Backend Start Failed | Python 依赖未装或 `python` 不在 PATH | 补第 2 节第 1 步；`python --version` 自检 |
| `node_modules/electron/dist/electron.exe` 缺失 | 安装时构建脚本被 pnpm 拦截 | 在 `electron/` 重跑安装；检查其 `package.json` 的 `onlyBuiltDependencies` 含 `electron`；或 `pnpm approve-builds` |
| `pnpm` 无法识别 | 未全局启用 corepack | 用 `corepack pnpm ...` 替代，或管理员执行 `corepack enable` |
| 窗口白屏且日志反复 retry | Vite 未就绪或被杀 | 看 4174 是否被无关进程占用；确认没和其他工具抢端口 |
| 首次启动特别慢 | electron 二进制下载 + Vite 冷启动 | 正常现象，仅首次 |

应急清场（等价于主进程的开场动作）：

```powershell
python start_all.py --kill   # 项目自带包装器，优先用它
```

## 6. 手动冒烟清单

改动 `main.cjs` / 打包配置 / 升级 Electron 版本后，过一遍：

1. `pnpm start` → 仅出现 1 个软件窗口 + 短暂 splash，全程无命令行黑框；后端 8000、前端 4174 就绪；
2. 点窗口 X → 弹中文确认框；取消=窗口保留，确认=窗口关闭且任务管理器无 `python api_server` / `node vite` 残留；
3. 设置里切 English 后再点 X → 确认框变英文；
4. （打包版）安装 Setup.exe → 双击启动只有 1 个 "Lumina Studio" 窗口，后台有 `lumina-backend.exe`，关窗后消失；
5. 回归确认纯 Web 模式不受影响：`python start_all.py` 正常。

Electron 自身单测：`cd electron && corepack pnpm test`（Node 内置 test runner，覆盖 workshop 安全边界与文件选择器）。
