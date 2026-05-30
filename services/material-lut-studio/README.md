# Material-LUT Studio (MLS)

独立的"耗材档案 + LUT"服务与可视化界面，从 Lumina Studio 主项目中解耦（路线 B）。

## 角色 (Role)

MLS 是耗材档案 (`materials/`) 与 LUT 预设 (`lut-preset/`) 的**数据所有者**：

- 对外暴露 REST API（默认端口 `:8100`），承接原先散落在主项目
  `api/routers/lut.py` 和 `api/routers/single_stage.py` 里的耗材/LUT 管理端点。
- 提供独立的可视化前端（默认端口 `:5180`），用于浏览/导入/导出耗材档案、
  管理求解缓存、查看与对比 LUT。
- 主 Lumina 项目通过 HTTP 客户端 (`api/clients/mls_client.py`) 访问管理类接口；
  转换管线的热路径通过 `core/material_lut_provider.py` 的"预取 + 本地缓存"
  边界访问数据，避免逐像素网络调用。

## 数据归属 (Data Ownership)

- **只有 MLS 可以写** `materials/`、`materials/_solver_cache/`、`lut-preset/`。
- 主项目对这些目录**只读**，并通过版本号/指纹失效本地缓存。
- MLS 复用主项目仓库内的纯领域逻辑（`core/`、`utils/lut_manager.py`、
  `config.py`、`api/schemas/`），不复制算法代码，避免两份实现漂移。

## 目录结构 (Layout)

```
services/material-lut-studio/
├── backend/                  # FastAPI 后端 (:8100)
│   ├── server.py             # 启动入口 (uvicorn)
│   ├── app.py                # 应用工厂
│   ├── bootstrap.py          # 把仓库根加入 sys.path，复用 core/utils/config
│   ├── data_root.py          # 数据根路径所有权
│   ├── schemas.py            # MLS 专属响应模型（复用 api.schemas.lut）
│   └── routers/
│       ├── health.py
│       ├── materials.py      # 耗材档案 CRUD / 导入导出
│       ├── solver_cache.py   # 求解缓存管理
│       └── lut.py            # LUT 列表 / 详情 / 对比 / 合成
└── frontend/                 # React + Vite + pnpm 可视化界面 (:5180)
```

## 本地运行 (Run)

后端（在仓库根目录，使用项目虚拟环境）：

```bash
python services/material-lut-studio/backend/server.py
# 或指定端口
MLS_PORT=8100 python services/material-lut-studio/backend/server.py
```

前端（在 `services/material-lut-studio/frontend/`）：

```bash
pnpm install
pnpm dev          # http://localhost:5180
```

## 与主项目的关系 (Relationship)

| 能力 | 迁移前 | 迁移后 |
| --- | --- | --- |
| LUT 列表/详情/对比/合成 | `api/routers/lut.py` | MLS `routers/lut.py` |
| 耗材档案 CRUD/导入导出 | `api/routers/single_stage.py` | MLS `routers/materials.py` |
| 求解缓存管理 | `api/routers/single_stage.py` | MLS `routers/solver_cache.py` |
| 管线热路径数据读取 | 进程内直接 import | `core/material_lut_provider.py`（预取+缓存） |

详见仓库根 `progress/` 下的解耦推进记录。
