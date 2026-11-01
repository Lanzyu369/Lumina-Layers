# 多机开发环境约定

## 一句话原则

移动硬盘只装「代码 + 数据」；开发环境（Python 虚拟环境 `.venv`、前端
`node_modules`）是**可重建的临时物**——不入库、不随盘迁移，换机器或盘符变动后，
用仓库根目录的 `dev_setup.bat` 一键重建。

## 盘符为什么不是问题

- 所有启动/构建脚本用 `%~dp0` 取脚本自身所在目录，不写死盘符（如 `start_app.bat`）。
- 代码内路径一律用相对路径 + 环境变量 + 用户数据目录（`config.py`），不出现盘符。
- `machine_registry` 只存相对路径，禁止写入开发机盘符/安装绝对路径（见
  `machine-adapter-v2-maintenance.md`）。

## 为什么仍要每台机器重建环境

`.venv` 内部记录的是「创建它的那台机器」的 Python 绝对路径与版本。单纯盘符
变动通常还能用（venv 会相对自身定位），但换了机器、或 Python 版本/安装位置不同，
venv 就会失效。因此 venv 不在机器间共享，而是每台机器各自重建。

## 每台机器首次（或盘符变动后）

1. 安装固定版本：Python 3.13、Node.js、pnpm@10.33.2。
2. 双击仓库根目录的 `dev_setup.bat`，脚本会依次：
   - 检测/重建 `.venv`
   - 安装 `requirements.txt`（可选 `requirements-glb-v2.txt`）
   - 安装 `frontend/` 与 `electron/` 的依赖
3. 之后双击 `start_app.bat` 启动开发环境。

> 注意：`frontend/package.json` 里有一个从 GitHub Releases 拉取的依赖
> `@lumina/workshop-sdk`，安装依赖时需要能访问 GitHub 网络。

## 版本约定

| 组件 | 版本 | 锁定方式 |
|---|---|---|
| Python | 3.13 | `dev_setup.bat` 内检测并提示 |
| pnpm | 10.33.2 | `package.json` 的 `packageManager` 字段 |
| 前端依赖 | - | `frontend/pnpm-lock.yaml` |
| Electron 依赖 | - | `electron/pnpm-lock.yaml` |

## 禁止事项

- 不要在任何代码/配置里写死盘符（`G:`、`E:` 等）或安装绝对路径。
- 不要把 `.venv`、`node_modules` 提交到 git（已在 `.gitignore` 中忽略）。
