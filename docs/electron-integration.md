# Electron 集成方案

在现有 FastAPI (`api_server.py`) + Vite/React (`frontend/`) 架构上增加一个 Electron 外壳，主进程托管后端生命周期并提供原生窗口、退出确认、一键启停，同时兼顾开发期 HMR 体验与生产期的离线打包可分发产物，不改动任何业务代码。

## 1. 目录与产物
- 新建 `electron/` 子目录（与 `frontend/`、`api/` 同级），存放 `main.cjs`、`preload.cjs`、`package.json`、`build/` 图标等；避免与 `frontend/` 的 ESM 配置混合。
- 根目录新增 `package.json`（或复用根级工作区）承载根脚本：`npm run dev:electron` / `npm run build:electron`。如果不希望根目录出现 `node_modules`，则把所有 Electron 依赖放进 `electron/package.json`，根级只保留 npm scripts。建议后者。
- 新增 `start_app.bat`（Windows 一键入口），内部调用 `cd electron && npm start`；保留现有 `start_dev.bat` / `start_dev.py` 作为纯 web 模式备用。
- README/README_CN 增补 "Desktop (Electron)" 启动章节。

## 2. 运行模式切换（dev vs prod）
主进程根据 `app.isPackaged` 决定前端加载方式与后端来源：

| 场景 | 后端 | 前端 |
|---|---|---|
| `npm start`（开发） | spawn `python api_server.py`（venv 优先） | spawn Vite → 探测 `http://127.0.0.1:4174` 就绪后 `loadURL` |
| `npm run build`（打包后运行 exe） | spawn 打包的后端二进制 `resources/backend/lumina-backend.exe` | `loadFile(resources/app/dist/index.html)` |

这样开发时保留 HMR、生产时秒开并像普通桌面软件；用户不用关心两者差异。

## 3. 主进程 `electron/main.cjs` 关键逻辑
- **启动顺序**：`app.whenReady()` → 先探测/启动后端（`waitForHealth('http://127.0.0.1:8000/api/health')`，超时 30s，失败弹 `dialog.showErrorBox` 并 `app.quit()`）→ dev 模式再启动 Vite 并探测端口 → 创建 `BrowserWindow`。
- **子进程管理 + 零黑框**：使用 `child_process.spawn`，**所有**子进程 (`python`, `node vite.js`, 打包后的 `lumina-backend.exe`) 传 `{ windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'], detached: false }`，确保 Windows 下不弹命令行黑框；stdout/stderr 管道被主进程接管后写入 `app.getPath('logs')/lumina-electron.log`，同时在 dev 模式转发到 Electron DevTools Console。退出时 `taskkill /T /F /PID`（复用 `start_dev.py` 的成熟做法）。
- **单实例锁**：`app.requestSingleInstanceLock()`，已有实例则聚焦主窗口。
- **BrowserWindow**：1440×900，`webPreferences`: `contextIsolation:true`、`nodeIntegration:false`、`preload` 指向 `preload.cjs`，`sandbox:false`（为 preload 能用 ipcRenderer）。菜单栏生产模式下 `Menu.setApplicationMenu(null)`。
- **关闭确认**：
  - 渲染进程通过 preload 暴露 `window.electronAPI.setLanguage(lang)`；前端在 `settingsStore` 订阅 language 变化后 `electronAPI?.setLanguage(lang)` 同步到主进程（无 electronAPI 时静默回退，不影响 web 模式）。
  - 主进程维护 `currentLang`（默认从环境变量 / localStorage 不可读，落到 `"zh"`）。
  - `win.on('close', (e) => { ... })` 里 `e.preventDefault()`，调用 `dialog.showMessageBox({ type:'question', buttons:[cancel,quit], defaultId:0, cancelId:0, message, detail })`，文案按 `currentLang` 从主进程内置双语表读取（和 `frontend/src/i18n/translations.ts` 的 `app_quit_*` 键保持命名一致，未来可扩展）。
  - 用户确认后设 `isQuitting=true` 并 `win.destroy()` → `before-quit` 钩子里销毁后端/Vite 子进程 → `app.quit()`。
- **关窗即退**：`window-all-closed` 直接 `app.quit()`（含 macOS，以满足"关窗彻底关软件"）。

## 4. 渲染侧接入
- 新增 `frontend/src/integrations/electron.ts`：`export const electronAPI = (window as any).electronAPI ?? null;` 并导出 `useElectronLanguageSync()` hook。
- 在 `App.tsx` 顶层调用该 hook：监听 `settingsStore` 的 `language`，变化时 `electronAPI?.setLanguage(lang)`；无 electron 环境时什么都不做，web 模式零影响。
- `preload.cjs` 仅暴露极简 API：`setLanguage(lang)`、`getAppVersion()`，全部走 `contextBridge.exposeInMainWorld`。
- **不**引入新的 i18n 源；退出弹窗文案在主进程内置 `{ zh:{...}, en:{...} }` 常量，避免跨进程读取 translations。后续若加语种，只需同步该常量。

## 5. 生产打包（electron-builder）
- `electron/package.json` 添加 `electron-builder` 作为 devDependency，`build.extraResources` 把 `resources/backend/`（PyInstaller 产物）与 `resources/app/dist/`（`vite build` 产物）打包；`build.win.target = 'nsis'`，`nsis.oneClick = false` 允许用户选择安装路径。
- 新增 `scripts/build_desktop.py`（或纯 npm script 串）串联：
  1. `cd frontend && npm run build`（环境变量 `VITE_API_BASE_URL=http://127.0.0.1:8000/api` 使打包后的前端指向本地后端，替代 dev 代理）。
  2. `pyinstaller lumina_studio.spec`（已存在 spec；**核对 `console=False` / `--windowed`**，否则后端启动瞬间会闪黑框；核对入口为 `api_server.py` 并命名 `lumina-backend`）。
  3. `cd electron && npm run build` → 产出 `dist_electron/Lumina Studio Setup x.y.z.exe`。
- 路径定位：主进程用 `path.join(process.resourcesPath, 'backend', 'lumina-backend.exe')` 和 `path.join(process.resourcesPath, 'app', 'dist', 'index.html')`。
- electron-builder 默认生成 GUI 应用（`.exe` 主程序无控制台）；用户双击启动后**只可见 1 个 Lumina Studio 窗口**。
- 代码签名/公证不在本次范围，README 标注"未签名"。

## 6. 端口与健康探测
- 后端固定 8000（与 `api_server.py` 一致）。启动前调用现有 `start_dev.py` 中的 `_kill_listening([8000])` 等价 Node 实现（纯 `netstat -ano | findstr` + `taskkill`），确保上次异常残留不会阻塞。
- Vite 端口固定 4174（`FRONTEND_PORT` 常量一致）；启动后轮询 `GET http://127.0.0.1:4174`，就绪后再 `loadURL`，避免白屏闪烁。
- 后端健康：轮询 `/api/health`（若不存在，退化成 TCP 端口探测）。

## 7. 不回归保障
- 保留 `api_server.py` / `start_dev.py` / `start_dev.bat` 原有行为，web 模式 100% 不变。
- `frontend/src/integrations/electron.ts` 全守卫 `window.electronAPI`；web 环境下无副作用。
- `vite.config.ts` 不改代理规则；打包时只通过 env var 切换 `VITE_API_BASE_URL`。
- 所有用户面字符串若新增（目前仅退出弹窗标题/按钮）同步加到 `translations.ts` 对应键 `app_quit_confirm_title/message/quit/cancel`，供将来 i18n 扩展和与主进程双语常量一致对照。

## 8. 测试与验证
- 新增 `electron/__tests__/main-quit.test.cjs`（Vitest 或 Node `node:test`）单测双语常量选择逻辑，以及 `close` 事件的 preventDefault/destroy 分支（mock BrowserWindow + dialog）。
- 手动冒烟清单写入 `docs/desktop-electron.md`：
  1. `npm start` → 窗口打开、后端 8000、Vite 4174，HMR 生效；**屏幕上仅 1 个软件窗口，无任何命令行黑框**（PowerShell 手动调起除外）。
  2. 点 X → 中文弹窗（默认），取消=窗口保留；确认=窗口关闭且 `tasklist` 里无 `python.exe api_server.py` 与 `node.exe vite`。
  3. 切换语言为 English 后再点 X → 弹窗英文。
  4. 打包后的 `Setup.exe` 安装并双击启动 → 任务栏只有 1 个 "Lumina Studio" 图标；任务管理器能看到 `lumina-backend.exe` 后台进程，**屏幕上无任何命令行窗口**；关窗后该后台进程消失。
  5. `python start_dev.py` web 模式仍可正常使用（浏览器访问 4174 不受影响）。
- 回归：`python -m pytest tests/ -v` 与 `python scripts/run_vitest.py run` 全量通过（不应被改动，但触网代码引入后仍需确认）。

## 9. 不做的事（显式排除）
- 不做自动更新、代码签名、安装后自启动。
- 不替换现有 `start_dev.py` 启动器；Electron 是并列的第二入口。
- 不改动任何业务组件、store、API schema；除 `App.tsx` 顶层一行 hook 调用和新增文件外，现有前端代码零改动。
- 不引入 Tauri/Neutralino 等替代方案。

## 10. 风险点
- **PyInstaller 包体积大**：已有 `lumina_studio.spec`，需验证其实际产物能独立运行并监听 8000；若目前 spec 目标不同，可能需要小幅调整 entry，后续视情况处理。
- **Windows 杀子进程竞态**：依赖 `taskkill /T /F`，macOS/Linux 版本不在本次范围（打包 target 仅 win）。
- **首启动延迟**：dev 模式下 Vite + Python 并行拉起约 3-6s，期间显示轻量 loading 窗口（splash BrowserWindow 加载本地 `electron/splash.html`）。
