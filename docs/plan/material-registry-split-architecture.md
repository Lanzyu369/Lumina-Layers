# 独立耗材库服务与 Lumina 分发版拆分计划

日期：2026-06-12  
基线分支：PR #242 `Min/feat/material-registry-package-v2`  
当前本仓库规划分支：`shmx/feat/material-registry-split-plan`

## 结论

确认采用“分发版 Lumina 只读同步，独立耗材库服务负责上传、审批、发布和单节点 catalog/package 分发”的架构。当前阶段不建设 replica 只读节点，也不要求 Lumina 客户端支持多个 Registry fallback URL。

分发版 Lumina 可以完全离线运行。用户不连接官方耗材库时，仍可使用本地耗材库完成校准、保存、导入、导出和生成。远端耗材库只是一个可选的官方/团队耗材来源，用于下载已发布的耗材包并同步到本地。

耗材库服务不随 Lumina 分发。它是独立部署的动态服务，负责角色 token 鉴权、上传、审批、发布、catalog 生成、package 分发、下架和审计。

## 角色边界

### 分发版 Lumina

分发版 Lumina 是本地应用和远端耗材库的只读客户端。

应保留的能力：

- 本地耗材校准、保存、编辑、删除、导入和导出。
- 启动时或用户手动触发时，从配置的远端 Registry 拉取 catalog。
- 从远端 Registry 下载 package，校验 `package_sha256`、manifest、文件 hash 和 `content_hash` 后安装。
- 维护本地 `materials/_sync/index.json`，记录已安装 revision、来源、channel、路径和回滚信息。
- 远端不可用时继续使用本地已有耗材。

不应包含的能力：

- 不暴露官方耗材上传入口。
- 不暴露审批、批准为 official、批量审批入口。
- 不内置 Registry 托管端路由。
- 不携带官方写入密码或审批 token。
- 不把用户本地耗材自动上传到官方服务。

当前 PR #242 中，分发版 Lumina 应保留或调整的接口：

- 保留：`GET /api/material-sync/status`
- 保留：`GET /api/material-sync/catalog`
- 保留：`POST /api/material-sync/install-from-registry`
- 保留：`POST /api/material-sync/refresh`
- 调整：`POST /api/material-sync/rollback` 应改为本地操作，不再依赖官方审批密码。
- 保留但重新命名/隔离语义：本地 ZIP 导入接口可继续存在，但它不是官方上传。

当前 PR #242 中，应从分发版 Lumina 移出的接口：

- `POST /api/material-registry/v1/packages/upload`
- `POST /api/material-registry/v1/packages/upload-local`
- `POST /api/material-registry/v1/packages/{package_path:path}/approve`
- 分发版 UI 中的上传、审批、官方密码输入、勾选非 official 后批量批准等管理入口。

### 独立耗材库服务

耗材库服务是动态服务，是官方耗材数据的写边界。

应包含的能力：

- 上传 v2 material bundle/package。
- 校验 package：ZIP 安全、manifest schema、UTF-8、文件 hash、content hash、大小、文件数、channel 合法性。
- 建立或更新 `material_id`、`revision_id`、channel、visibility、审核状态和 package 元数据。
- 审批 pending revision 并发布到 official/team/community 等 channel。
- 提供只读 catalog 和 package 下载。
- 提供管理端 UI 或 API 给维护者执行上传、审批、回滚发布状态、下架和审计查看。
- 可使用角色 token 作为第一阶段鉴权方式，但 token 原文不得写入日志、审计记录、catalog 或错误响应。

### 独立耗材内容仓库

耗材内容仓库用于组织源耗材数据和构建可发布 package，不承载 Lumina 主应用代码。

已确认拆成两个独立仓库：

- `Lumina-materials`：耗材内容仓库，只存耗材源数据、package、seed、构建脚本和内容 CI。
- `Lumina-material-registry`：动态服务仓库，只存上传/审批服务、管理端 UI 或管理 API、权限、持久化模型、catalog/package 下载服务和单节点发布可靠性逻辑。

不要把服务代码、主应用代码和大规模内容数据长期混在一个仓库。

本地仓库落点约定：

当前 Lumina 主仓库目录为 `E:\Work\PythonProject\Lumina-Layers`。两个新仓库必须建立在当前项目文件夹的父文件夹 `E:\Work\PythonProject` 下，作为 Lumina 主仓库的同级仓库，不放入 `Lumina-Layers` 内部，也不作为当前仓库的 submodule。

```text
E:\Work\PythonProject\
  Lumina-Layers\
  Lumina-materials\
  Lumina-material-registry\
```

推荐目录结构：

```text
Lumina-materials/
  README.md
  AGENTS.md
  materials-src/
    official/
      <brand>/<material>/
        material.json
        stage_A_parameters.json
    community/
      <brand>/<material>/
        material.json
        stage_A_parameters.json
    team/
      <brand>/<material>/
        material.json
        stage_A_parameters.json
  manifests/
    materials-index.json
    channels.json
    release.json
  packages/
    official/
      mat_<id>/rev_<id>-<sha12>.zip
    community/
      mat_<id>/rev_<id>-<sha12>.zip
    team/
      mat_<id>/rev_<id>-<sha12>.zip
  seed/
    lumina-materials-seed.zip
  scripts/
    build_packages.py
    validate_packages.py
    build_seed.py
  tests/
    test_package_manifest.py
  .github/workflows/
    validate.yml
    release.yml
```

目录职责：

- `materials-src/` 是可审阅源数据，用于 PR review。
- `packages/` 是不可变构建产物，可由 CI 生成并发布到 release/object storage。
- `seed/` 是给 Lumina 分发版内置的 official-only 初始耗材快照。
- `manifests/` 存放可复现构建清单、channel 定义和 release 元数据。
- `scripts/` 只处理耗材包构建与校验，不依赖 Lumina 前端或转换主流程。

## 构建与分发关系

### 耗材库仓库构建结果

耗材库仓库每次 release 产出：

- `material-registry-packages.zip`：按 channel 组织的 v2 package 集合。
- `lumina-materials-seed.zip`：分发版 Lumina 可内置的官方初始耗材快照。
- `catalog.json` 或服务端可导入的 catalog seed。
- `release.json`：包含版本号、commit、package 数量、channel、hash、生成时间。

### Lumina 主仓库构建结果

Lumina 主仓库构建时消费某个固定版本的耗材 release artifact。

推荐策略：

1. 构建参数指定耗材 release 版本或本地 artifact 路径。
2. CI 下载并校验只包含 official 耗材的 `lumina-materials-seed.zip`。
3. 桌面包和 Docker 镜像把 seed 放入只读资源区。
4. 首次启动时，如果用户运行时 `materials/` 为空，则把 seed 安装到可写运行时目录。
5. 后续同步只更新可写运行时目录，不修改应用安装目录内的 seed。

这样能同时满足：

- 分发版自带初始耗材，离线可用。
- 官方耗材库不随应用一起部署。
- 用户本地修改不会被应用升级覆盖。
- 远端同步可以在有网络时补充或更新耗材。

当前本仓库需要的改造点：

- `config.py` 的 `MATERIALS_DIR` 需要支持环境变量覆盖和桌面用户数据目录，不应只依赖当前工作目录。
- Docker 本地部署脚本需要区分应用运行时 `materials/` 与耗材 seed。
- Electron/PyInstaller 打包脚本需要引入 seed artifact，而不是直接依赖仓库内完整 `materials/`。
- `.gitignore` 和 PR #242 当前把 `material-registry-packages/` 放进主仓库的策略需要调整：主仓库不应长期持有官方耗材包集合。

## 单 Registry 发布与读取

第一阶段推荐“单独 Registry 服务 + 单读端点”。不建设多地只读/缓存节点。

原因：

- 上传、审批和发布需要强一致的写边界。
- `material_id/revision_id` 和 channel 状态不能被多个节点并发改写。
- package 是不可变内容；修正内容必须生成新 revision。
- 分发版 Lumina 只需要稳定读取一个已配置 Registry，不需要知道写入实现细节。

当前推荐拓扑：

```text
maintainer/admin
  -> registry service
       -> package storage
       -> registry persistence
       -> audit log
       -> active catalog snapshot

Lumina clients
  -> configured registry read endpoint
  -> local materials/_sync/index.json
```

写入规则：

- 所有上传、审批、发布、下架只进入独立 Registry 服务。
- package 发布后不可变；修正内容必须生成新 revision。
- 审批只能从 pending revision 转为已发布 revision；改 channel、下架、回滚发布状态必须走独立管理接口并写审计。
- catalog 更新必须基于已校验、已发布状态生成，并以原子方式切换 active snapshot，避免客户端读到半成品。

读取规则：

- official/community approved 可以公开读取。
- team/private/unlisted 需要 token 或登录态。
- catalog 可以按 channel、权限和分页返回。
- package 下载 URL 必须和 catalog 受同一权限体系保护。

当前不做的事情：

- 不建设 replica 只读节点。
- 不要求 event cursor、跨节点 package 同步或 replica catalog 原子切换。
- 不要求 Lumina 客户端支持多个 Registry fallback URL。

## 边界条件

### 离线与远端不可用

- Lumina 未配置远端 Registry 时，云端同步 UI 应显示未配置或隐藏，但本地耗材功能完全可用。
- 远端 catalog 请求失败时，不应阻断本地校准、生成或已有耗材使用。
- package 下载失败时，只记录失败，不删除本地旧 revision。
- 自动同步失败不应把应用启动变成失败。

### 本地冲突

- 远端 package 不得静默覆盖用户本地耗材目录。
- 命中 `local_directory + content_hash` 时可标记为已安装。
- `material_id` 相同但本地内容不同，应提示更新、安装副本或保留本地修改。
- 本地用户删除文件后，`_sync/index.json` 可以保留记录，但 UI 要显示本地缺失。

### 安全

- 分发版 Lumina 不包含官方写入密钥。
- 分发版 Lumina 不暴露 Registry 上传/审批路由。
- package URL 必须同源或经过明确允许的下载域校验，禁止重定向越权。
- package 下载前后都要校验大小、hash 和 manifest。
- ZIP 导入必须拒绝绝对路径、`..`、Windows drive path、重复必需角色、hash mismatch。
- 管理服务必须有审计日志：上传者、审批者、revision、channel、时间、来源 IP/request_id。

### 数据与版本

- `material_id` 表示耗材谱系。
- `revision_id` 表示不可变发布版本。
- `content_hash` 表示核心内容一致性。
- `local_directory` 只表示本机安装路径，不是全局身份。
- `usage_stats.json`、`_solver_cache/`、preview cache、日志和临时文件不得进入官方 package。

### 性能

- Lumina 热路径不应逐像素访问远端服务。
- catalog 拉取需要分页、搜索和缓存。
- 大 package 下载要有大小上限、超时、失败重试和断路策略。
- 本地 listing 应从 `materials/` 与 `_sync/index.json` 快速合并，避免每次 UI 刷新扫描所有 ZIP。

## 实现计划

### 阶段 0：冻结架构文档

- 在本仓库记录本计划。
- 明确 PR #242 中哪些内容属于 Lumina 客户端，哪些属于独立 Registry 服务。
- 明确分发版不包含上传/审批。

验收：

- 本文档合入规划分支。
- 后续实现任务能按本计划拆 issue。

### 阶段 1：把 Lumina 分发版收敛为只读远端客户端

修改方向：

- 在本仓库增加运行模式或构建模式：distribution 默认不注册 `material_registry_router`。
- 移除或隐藏分发版前端中的上传、审批、官方密码输入和批量批准 UI。
- 保留 catalog、install-from-registry、refresh、status。
- 将 rollback 改成本地操作，不要求官方密码。
- 明确本地 ZIP 导入/导出与官方上传无关。

重点文件：

- `api/app.py`
- `api/routers/material_sync.py`
- `api/routers/material_registry.py`
- `frontend/src/api/materialSync.ts`
- `frontend/src/components/MaterialCloudSyncPanel.tsx`
- `frontend/src/i18n/translations.ts`
- `tests/test_material_sync_api_unit.py`
- `frontend/src/__tests__/material-cloud-sync-panel.test.tsx`

验收：

- 分发模式下 `/api/material-registry/v1/packages/upload` 返回 404 或未注册。
- 分发模式前端不显示上传/审批控件。
- 本地耗材导入/导出仍可用。
- 未配置 `LUMINA_MATERIAL_REGISTRY_URL` 时，本地耗材库仍可用。

### 阶段 2：抽出独立耗材库服务

修改方向：

- 在 `E:\Work\PythonProject\Lumina-material-registry` 建立独立服务仓库。
- 以 PR #242 的 `api/routers/material_registry.py` 和 `core/material_registry.py` 为服务端起点。
- 独立服务保留 catalog、package download、upload、approve。
- 补齐动态服务需要的持久化模型：materials、revisions、channels、audit_events。
- 写入接口从简单 password 迁移到明确的角色 token 鉴权；第一阶段不强制账号系统，但必须区分 maintainer、approver、team/private read token。
- 管理 UI 从 Lumina 分发前端中移出。
- 上传接口必须设置请求体大小、ZIP entry 数量、单文件大小、总解压大小和压缩比上限。
- Registry 服务端必须重新计算并验证 `content_hash`，不能只信任 manifest 中声明的值。
- 审计日志只能记录 actor id、角色、token id 或 token 摘要，不能记录原始 token、Authorization header 或其可复原前缀。
- 审批只能作用于 pending revision；下架、改 channel、回滚发布状态必须使用独立接口和独立审计事件。

服务端第一阶段可以仍用文件系统 package root，但必须把 package root、catalog cache、audit log 和权限配置从主应用运行目录中剥离。

验收：

- 独立服务能上传 pending package。
- 管理员能审批为 official。
- Lumina 分发版只通过 read endpoint 安装 package。
- 审计日志能追踪上传和审批。
- 上传大文件、ZIP bomb、路径逃逸、hash mismatch、`content_hash` mismatch、local-only 文件入包都会失败。
- audit 记录不包含 token 原文或 Authorization header 前缀。
- 重复 `material_id + revision_id` 不会留下可发布的孤儿 pending package。

### 阶段 3：建立独立耗材内容仓库

修改方向：

- 在 `E:\Work\PythonProject\Lumina-materials` 建立独立内容仓库。
- 将主仓库中的大规模官方/社区耗材源数据迁出到 `Lumina-materials`。
- CI 使用 `scripts/build_packages.py` 生成 v2 package。
- CI 使用 `scripts/validate_packages.py` 校验所有 package。
- 发布 release artifact：`material-registry-packages.zip`、`lumina-materials-seed.zip`、`release.json`。

验收：

- 任意 package 可通过 `validate_material_bundle_archive()` 校验。
- `packages/` 中不存在重复 `material_id + revision_id`。
- `seed/lumina-materials-seed.zip` 可被 Lumina 导入并生成 `_sync/index.json`。
- CI 对乱码标记、hash mismatch、缺失必需文件、local-only 文件入包全部失败。

### 阶段 4：Lumina 构建消费耗材 seed

修改方向：

- Docker 构建支持 `MATERIALS_SEED_PATH` 或 `MATERIALS_SEED_URL`。
- Electron/PyInstaller 构建脚本下载/校验 seed artifact。
- 应用首次启动时把 seed 安装到可写 `materials/`。
- 应用升级时不覆盖已有本地耗材。

验收：

- 新安装离线启动后能看到 seed 耗材。
- 用户删除/修改本地耗材后，应用升级不会静默恢复覆盖。
- 未配置远端 Registry 时，本地校准保存流程仍通过。

### 阶段 5：单 Registry 发布可靠性

修改方向：

- 独立 Registry 生成 active catalog snapshot。
- catalog snapshot 只包含已发布、已校验通过且 package 文件存在的 revision。
- 审批、下架、改 channel、回滚发布状态后，catalog 以原子方式切换。
- Lumina 客户端继续使用单个 `LUMINA_MATERIAL_REGISTRY_URL`。
- 远端 Registry 不可用、catalog 失败或 package 下载失败时，Lumina 本地耗材库继续可用，不删除已有 revision。

验收：

- 发布新 revision 后，catalog 返回同一 `material_id/revision_id/content_hash/package_sha256`。
- 下架或回滚发布状态后，catalog 不再返回对应 revision，但已发布 package 文件不可被静默改写。
- catalog 生成中断或 package hash mismatch 时，服务继续返回上一版有效 catalog。
- Lumina 客户端在单 Registry 不可用时返回确定错误，并继续保留本地已有耗材与 `_sync/index.json`。

## 验证步骤

### 本仓库客户端验证

```powershell
python -m pytest tests/test_material_sync_api_unit.py -v
python -m pytest tests/test_material_sync_scheduler_unit.py -v
python scripts/run_vitest.py run src/__tests__/material-cloud-sync-panel.test.tsx src/__tests__/material-sync-api.test.ts
```

需要新增或调整的断言：

- distribution 模式不注册 Registry 写路由。
- 前端不显示上传、审批和官方密码控件。
- rollback 不需要官方写入密码。
- Registry 未配置时 catalog/refresh 给出确定错误，本地 library/status 不失败。

### 独立耗材库服务验证

```powershell
python -m pytest tests/test_material_registry_api_unit.py -v
python -m pytest tests/test_material_sync_api_unit.py::test_refresh_material_sync_from_registry_installs_missing_package -v
```

需要新增或调整的断言：

- upload 需要维护者权限。
- approve 需要审批权限。
- catalog read 按 channel 和 token 过滤。
- package download 权限与 catalog 一致。
- audit event 记录上传和审批，但不泄露 token。
- upload 对 ZIP bomb、超大文件、超多 entry、hash mismatch 和 content_hash mismatch 失败。
- approve 只能审批 pending revision；重复审批、跨 channel 改写或直接审批已发布 package 失败。
- catalog 生成只包含已发布且文件仍存在的 revision。

### 独立耗材内容仓库验证

建议在独立仓库中提供：

```powershell
python scripts/validate_packages.py --packages packages
python scripts/build_seed.py --channel official --output seed/lumina-materials-seed.zip
python scripts/validate_packages.py --archive seed/lumina-materials-seed.zip
```

必须覆盖：

- UTF-8 JSON 读取。
- ZIP 路径逃逸。
- 必需角色重复或缺失。
- `material.json` 与 `stage_A_parameters.json` hash mismatch。
- `usage_stats.json`、`_solver_cache/` 入包失败。
- 重复 `material_id + revision_id` 失败。
- package 不可变：已发布 revision 文件内容变化失败。

### 打包验证

```powershell
python scripts/build_desktop.py
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\docker_local_deploy.ps1
```

需要新增：

- 指定 seed artifact 的构建参数。
- 构建后检查安装包/镜像包含 seed，但不包含 Registry 写入密钥。
- 首次启动生成可写 `materials/`。
- 无网络启动仍能列出 seed 耗材。

## 已确认与待确认问题

### 问题 1：耗材内容仓库和耗材库服务仓库是否分开？

状态：已确认，分开。

- `Lumina-materials`：只存耗材源数据、package、seed、构建脚本和内容 CI。
- `Lumina-material-registry`：存动态服务、管理端 UI 或管理 API、权限、持久化模型和单节点发布可靠性逻辑。

理由：内容仓库需要频繁 review 数据和 package；服务仓库需要部署、鉴权、数据库和运维。放在一起会让内容 PR、服务发布和安全边界互相干扰。

### 问题 2：第一阶段 seed 只包含 official，还是包含 official + 已审核 community？

状态：已确认，只包含 official 耗材。

理由：分发版的离线默认耗材应稳定、可解释、体积可控。community 可通过远端下载。

### 问题 3：是否需要多地只读节点？

状态：已确认，当前阶段不需要 replica 只读节点，也不需要 Lumina 客户端 fallback URL。

理由：单 Registry 服务已经能满足当前耗材发布与读取需求；去掉 replica 后，工程重点收敛到上传/审批安全、catalog 原子更新、下架/回滚发布状态和客户端单 URL 失败降级。
