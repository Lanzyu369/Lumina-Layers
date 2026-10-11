# Electron 集成架构

Electron 主进程负责启动本机 Python 后端和 Vite 前端、管理窗口与子进程，并提供浏览器无法直接使用的文件和创意工坊能力。环境准备与启动命令见 [`desktop-electron.md`](desktop-electron.md)。

## 运行链路

`electron/main.cjs` 选择后端端口，启动 `api_server.py`，验证本次后端健康，再启动 Vite 并打开页面。Vite 将 API 请求代理到选定的后端地址；前端页面固定使用 `http://127.0.0.1:4174`。

`backend-endpoint.cjs` 负责端口检查和后端健康响应校验。已保存的后端端口用于保持地址稳定；端口冲突会明确报错。关闭应用只停止它自己启动的子进程。

## 窗口与前端桥接

主窗口使用 `contextIsolation: true`、`nodeIntegration: false`，通过 `preload.cjs` 暴露有限的 IPC 接口。前端在浏览器运行时仍使用 Web API；只在存在 `window.electronAPI` 时使用桌面能力。

设置中的语言同步到主进程，用于退出确认等原生对话框。确认退出前保留窗口；确认后关闭窗口并清理后端和 Vite。文件保存、默认导出目录、原生热床模型与创意工坊文件选择分别由现有桥接模块处理。

## 创意工坊

主进程注册 `lumina-workshop` 协议，将模块资源请求交给当前后端。`workshop-security.cjs` 检查 IPC 来源、窗口导航、下载和模块访问权限，保护用户本地文件与宿主状态。相关功能见 [`context/workshop/CONTEXT.md`](context/workshop/CONTEXT.md)。

## 验证入口

运行 `pnpm --dir electron test` 检查桌面行为与桥接模块。窗口或生命周期改动还应实际启动源码客户端，检查加载、退出确认和子进程清理。Python 与 React 功能使用各自的回归测试入口。
