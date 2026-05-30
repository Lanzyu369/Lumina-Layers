# 耗材档案 + LUT 解耦为独立服务（路线 B）

## 目标

把"耗材档案 (material archive)"与"LUT"从主 Lumina 项目中解耦为一个独立服务
**Material-LUT Studio (MLS)**，拥有自己的后端 API（`:8100`）和可视化前端
（`:5180`），通过 HTTP 与主项目对接。采用**路线 B**：MLS 成为这两类数据的
所有者；主项目通过 HTTP 客户端做管理类调用，通过"预取 + 本地缓存"边界做热路径
数据访问，避免逐像素网络调用。

## 已落地的结构

```
services/material-lut-studio/
├── README.md
├── start_mls.py                 # 一键起后端+前端的开发启动器
├── backend/                     # FastAPI (:8100)
│   ├── server.py                # uvicorn 启动入口
│   ├── app.py                   # 应用工厂 + /api/files/{id} 文件下载端点
│   ├── bootstrap.py             # 把仓库根加入 sys.path，复用 core/utils/config/api
│   ├── data_root.py             # 数据根所有权（materials/、lut-preset/、_solver_cache/）
│   ├── dependencies.py          # MLS 进程内 FileRegistry 单例
│   ├── routers/
│   │   ├── health.py            # GET /api/mls/health（含数据根快照）
│   │   ├── lut.py               # LUT 列表/详情/对比/合成/上传（薄适配主路由）
│   │   ├── materials.py         # 耗材档案 列表/更新/删除/导出/导入
│   │   └── solver_cache.py      # 求解缓存 列表/状态/构建/删除/取色建议（薄适配）
│   └── tests/test_mls_backend_unit.py
└── frontend/                    # React 19 + Vite + pnpm + Tailwind (:5180)
    └── src/{api,stores,components,i18n}  # 耗材库 / LUT 库 / 求解缓存 三视图
```

主项目侧新增：

- `api/services/lut_presentation.py` — 从 `api/routers/lut.py` 抽出的**会话无关
  LUT 展示逻辑**，主路由与 MLS 共享，避免复制粘贴（AGENTS.md 禁止重复逻辑）。
- `api/clients/mls_client.py` — 主项目访问 MLS 的管理类 HTTP 客户端。
- `core/material_lut_provider.py` — **热路径数据提供者**：管线统一收口，带进程内
  memo 缓存 + 基于 `material.json`/`stage_A_parameters.json` mtime 的**跨进程自
  失效**键。

## 关键设计决策

1. **薄适配，不复制逻辑**：MLS 的 LUT / solver-cache 路由直接复用主路由里会话
   无关的处理函数，仅换 `/api/mls/...` 前缀和数据归属。这样 merge/compare/solver
   等算法只有一份实现。
2. **会话耦合端点留在主项目**：`/api/lut/session/{id}/info`、
   `save-gradient-card-material` 依赖主应用 `SessionStore`，刻意不迁移。
3. **热路径不网络化**：管线（s01/s02/s03、p03）的耗材加载与 solver 缓存读取改走
   `core/material_lut_provider.py`，当前读共享磁盘；未来 MLS 成为唯一写入方时，
   仅改 provider 从 MLS 预取到本地缓存，管线代码无需改动。
4. **缓存自失效优于失效协议**：provider 的 memo 键折入档案文件 mtime，任何进程
   （含 MLS）改动文件都会让键失效并重载，无需脆弱的跨进程失效通知。

## 配置开关

- `MLS_PORT` / `MLS_HOST`：MLS 后端监听地址（默认 `127.0.0.1:8100`）。
- `MLS_MATERIALS_DIR` / `MLS_LUT_PRESET_DIR`：覆盖数据根（默认复用主项目路径）。
- `LUMINA_MLS_BASE_URL`：主项目访问 MLS 的基地址（默认 `http://127.0.0.1:8100`）。
- `LUMINA_MLS_ENABLED`：是否把管理类调用路由到 MLS（迁移期默认关闭，回退进程内）。

## 验证状态

- MLS 后端：22 个端点注册，真实数据冒烟通过（LUT 67、耗材 84、求解缓存 21、
  文件下载 200）。后端单元测试 8 项通过。
- MLS 前端：`pnpm build` 通过（TS 编译 + Vite 打包），经 Vite 代理端到端联调通过。
- 主项目：LUT/material/pipeline/single_stage 相关测试 1158 通过、16 跳过；日志治理
  测试 21 通过；provider 单测 5 项、MLS 客户端单测 12 项通过。
- 重构无损：抽取共享展示模块、热路径改走 provider 后，原有 canary / parity /
  pipeline 测试在更新 monkeypatch 目标后全绿。

## 后续可选项（未做）

- 打开 `LUMINA_MLS_ENABLED`，把主项目前端的耗材/LUT 管理面板入口指向 MLS（或保留
  入口跳转/嵌入）。
- 当确定 MLS 为唯一写入方后，在 provider 内实现"从 MLS 预取到本地缓存"，并补
  "源 session 关闭后下载 URL 仍可用"的跨服务回归测试。
