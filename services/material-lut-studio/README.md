# Material-LUT Studio (MLS)

独立的「耗材档案 + LUT」服务，从 Lumina Studio 主项目中解耦（路线 B / 选项 A）。

## 角色 (Role)

MLS 是耗材档案 (`materials/`) 与 LUT 预设 (`lut-preset/`) 的**数据所有者**：

- **后端**：FastAPI 服务（默认端口 `:8100`），承接原先散落在主项目
  `api/routers/lut.py` 与 `api/routers/single_stage.py` 里的耗材 / LUT 管理端点，
  并通过 `dependency_overrides` 复用主仓库的领域路由（不复制业务逻辑）。
- **前端**：作为主仓库 `frontend/` 内的第二个 Vite 入口构建（`vite.mls.config.ts`），
  默认端口 `:5180`。它与主转换器应用共享整套面板、组件与依赖树（零重复），但独立
  托管路由与构建输出。
- 主 Lumina 项目通过 HTTP 客户端 (`api/clients/mls_client.py`) 访问管理类接口；
  转换管线的热路径通过 `core/material_lut_provider.py` 的「预取 + 本地缓存」
  边界访问数据，避免逐像素网络调用。受环境变量 `LUMINA_MLS_ENABLED` 控制，默认
  关闭以便迁移期回退到本地读盘。

## 数据归属 (Data Ownership)

- **只有 MLS 可以写** `materials/`、`materials/_solver_cache/`、`lut-preset/`。
- 主项目对这些目录**只读**，并通过版本号/指纹失效本地缓存。
- MLS 复用主项目仓库内的纯领域逻辑（`core/`、`utils/lut_manager.py`、
  `config.py`、`api/schemas/`），不复制算法代码，避免两份实现漂移。

## 写入鉴权 (Write Auth)

MLS 默认只读，写操作（删除 / 编辑 / 导入 / 上传 / 合并 / 构建求解缓存等）需要
携带 `X-MLS-Password` 请求头。密码加载优先级：

1. 环境变量 `MLS_WRITE_PASSWORD`（推荐用于部署环境）。
2. 本目录下的 `config.json` 文件中的 `write_password` 字段。
3. 两者均空 → 服务对外完全开放（仅适合本地单用户开发）。

仓库内的 `config.json` 是部署期占位，**不要**在生产部署直接使用其中的默认值；
请改设环境变量或修改文件。详见 `backend/auth.py`。

## 目录结构 (Layout)

```
services/material-lut-studio/
├── backend/                  # FastAPI 后端 (:8100)
│   ├── server.py             # 启动入口 (uvicorn)
│   ├── app.py                # 应用工厂
│   ├── auth.py               # 写入密码加载与中间件
│   ├── bootstrap.py          # 把仓库根加入 sys.path，复用 core/utils/config
│   ├── data_root.py          # 数据根路径所有权
│   ├── dependencies.py       # MLS 进程内 SessionStore / FileRegistry 单例
│   └── routers/
│       ├── auth.py           # GET /status、POST /verify
│       ├── health.py
│       ├── materials.py      # 耗材档案 CRUD / 导入 / 导出
│       ├── solver_cache.py   # 求解缓存管理 + 色彩分布图详情
│       ├── lut.py            # LUT 列表 / 详情 / 对比 / 合成（薄适配主路由）
│       └── data.py           # 跨服务器数据 API（耗材参数 / 指纹 / 缓存文件）
├── start_mls.py              # 仅启动后端的薄封装
├── config.example.json       # 写入密码配置示例
└── config.json               # 入库的默认密码占位（部署期请覆盖）
```

> **注**：MLS **没有**独立的 frontend 子目录。前端入口就是仓库根的
> `frontend/mls.html` + `frontend/src/mls/`，通过 `frontend/vite.mls.config.ts`
> 运行在 `:5180`。

## 本地运行 (Run)

**推荐方式**：仓库根的 `start_all.py` 一次性启动主转换器（`:8000` / `:4174`）+
MLS 后端（`:8100`）+ MLS 前端（`:5180`）四个进程，并支持热键单服务重启：

```bash
python start_all.py
# 仅启动 MLS 两端：
python start_all.py --only mls
```

**仅启动 MLS 后端**（前端在别处管理时）：

```bash
python services/material-lut-studio/start_mls.py
# 或指定端口
MLS_PORT=8100 python services/material-lut-studio/start_mls.py
```

**仅启动 MLS 前端**：

```bash
cd frontend
pnpm dev:mls       # http://localhost:5180
```

## 与主项目的关系 (Relationship)

| 能力 | 迁移前 | 迁移后 |
| --- | --- | --- |
| LUT 列表 / 详情 / 对比 / 合成 | `api/routers/lut.py` | MLS `routers/lut.py`（薄适配） + 主路由复用挂在 `/api/lut/...` |
| 耗材档案 CRUD / 导入 / 导出 | `api/routers/single_stage.py` | MLS `routers/materials.py` + 复用 `extractor`/`single_stage` 路由 |
| 求解缓存管理 | `api/routers/single_stage.py` | MLS `routers/solver_cache.py` |
| 管线热路径数据读取 | 进程内直接 import | `core/material_lut_provider.py`（预取 + 缓存，受 `LUMINA_MLS_ENABLED` 控制） |

详见仓库根 `progress/material-lut-service-decouple.md` 的解耦推进记录。
