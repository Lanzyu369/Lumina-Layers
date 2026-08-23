# Lumina 耗材服务器连接说明

本文说明如何让 Lumina Studio 连接当前云端耗材 Registry。普通使用者只需要只读同步；上传、审批和私有频道访问属于维护者操作。当前部署状态、LUT 云库数量和维护交接流程见 [Lumina 云端耗材与 LUT Registry 交接文档](cloud-registry-handoff.md)。

## 与 LUT 云库的关系

Lumina 的云端资料库分成两条并列能力：

- 耗材云库：同步耗材档案和材料库 package，安装到本地耗材库，供耗材档案、材料包和相关打印参数流程使用。
- LUT 云库：同步 LUT 包和预设，安装到本地 `lut-preset/Cloud/...`，供现有 LUT 详情、预览和生成流程使用。

两者可以使用同一 Registry 服务地址和公开频道，也可以在部署上分开。它们的数据类型、安装目录和运行时用途不同：耗材云库不等同于 LUT 云库，LUT 云库也不会替代耗材档案管理。LUT 云库的公开行为见 [LUT 云库连接与多选 LUT 流程](lut-registry-cloud.md)。

## 服务地址

当前 Registry 地址：

```text
http://154.17.28.23/api/material-registry/v1
```

当前公开频道：

```text
official,community
```

`official` 和 `community` 是公开只读频道，不需要 token。`team`、上传和审批需要开发者 token。

`/materials/catalog`、`/packages/upload` 等路径由独立 Material Registry 服务提供；Lumina Studio 主应用只配置连接和同步，不在主应用仓库内实现这些服务端路由。

## 普通使用者配置

在运行 Lumina Studio 的环境中设置：

```powershell
$env:LUMINA_MATERIAL_REGISTRY_URL = "http://154.17.28.23/api/material-registry/v1"
$env:LUMINA_MATERIAL_REGISTRY_CHANNELS = "official,community"
```

如果使用本地 Docker 部署脚本，可以传入：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\docker_local_deploy.ps1 `
  -MaterialRegistryUrl "http://154.17.28.23/api/material-registry/v1" `
  -MaterialRegistryChannels "official,community"
```

脚本也会从当前进程环境或仓库根目录的 `.env.local` 转发以下可选配置：

```text
LUMINA_MATERIAL_REGISTRY_TOKEN
LUMINA_MATERIAL_REGISTRY_TIMEOUT_S
LUMINA_MATERIAL_SYNC_STARTUP_REFRESH
LUMINA_MATERIAL_SYNC_REFRESH_INTERVAL_S
```

私有 `team` 频道所需 token 应放在本机 `.env.local` 或受控部署环境中，不要写进脚本、提交或命令历史。

配置 URL 后，Lumina 默认在启动时刷新一次，之后每 6 小时刷新一次。需要仅手工安装时，可把 `LUMINA_MATERIAL_SYNC_STARTUP_REFRESH` 设为 `false`，并把 `LUMINA_MATERIAL_SYNC_REFRESH_INTERVAL_S` 设为 `0`。同步只会读取云端 catalog 和下载 package，不会读取或上传用户本地耗材。

如果同一个 `material_id` 在 catalog 中同时出现多个 revision，批量刷新会以 `ambiguous_revision` 失败关闭，不会根据 revision 字符串或返回顺序猜测最新版。用户仍可在云端耗材面板中明确选择某个 revision 手工安装。

## Catalog 条件同步

支持条件请求的独立 Registry 会在 `/materials/catalog` 的成功响应中返回
`ETag`。Lumina 在首次完整同步并确认所有 catalog 条目已经本地收敛后，将
validator 保存到耗材库的 `_sync/index.json`：

```text
catalog_validators[规范化 Registry URL][有序频道组合]
```

这是 schema `1.0` 的可选后端字段，不会出现在 `/api/material-sync/status`、
`/api/material-sync/refresh` 响应、前端状态或日志中。同一个 URL 的
`official,community` 与 `community,official` 是不同的请求表示，会分别保存。

下一次刷新前，Lumina 会重新计算本地状态摘要。摘要覆盖耗材目录中参与同步的
有效文件和同步索引绑定，忽略 `usage_stats.json`、`_solver_cache` 以及
validator 自身。只有当前摘要仍与保存值一致时才发送 `If-None-Match`：

- Registry 返回 `304 Not Modified` 且本地摘要仍一致时，不解析 catalog
  JSON，也不下载 package；公开刷新响应沿用上次条目数作为 `checked_count`，
  并全部计入 `skipped_count`。
- 若等待 `304` 期间本地内容发生变化，Lumina 最多补发一次不带条件头的完整
  catalog 请求。
- 若必需的 `material.json` 或 Stage-A 参数文件被删除或修改，下一次完整响应
  会按真实文件 hash 重新下载。原目录不会被覆盖，干净副本沿用现有时间后缀
  冲突规则安装。
- 无有效 `ETag`、存在包级失败或 catalog 尚未完全本地收敛时，当前频道组合的
  validator 会被清除，下一次继续执行完整请求。

旧 Registry 不返回 `ETag` 时无需额外配置，Lumina 会保持原有的 `200` 完整
同步行为。Lumina 主应用内的兼容 Registry 路由也继续走这条兼容路径，不复制
独立服务的服务端 ETag 实现。本次代码交付不包含云端部署；上面的条件请求只有
在独立 Registry 更新上线后才会生效。

## 连接验证

用浏览器或命令行打开：

```text
http://154.17.28.23/api/material-registry/v1/materials/catalog?channel=official&channel=community&limit=1
```

PowerShell 验证：

```powershell
Invoke-RestMethod `
  "http://154.17.28.23/api/material-registry/v1/materials/catalog?channel=official&channel=community&limit=1"
```

正常响应应包含：

```json
{
  "schema_version": "1.0",
  "channels": ["official", "community"],
  "count": 1,
  "total_count": 181,
  "materials": [
    {
      "material_id": "example-material",
      "name": "Example PLA White",
      "vendor": "Example Vendor",
      "channel": "official",
      "package_url": "http://154.17.28.23/api/material-registry/v1/packages/example-material.zip"
    }
  ]
}
```

`materials` 中会返回实际耗材条目。`total_count` 会随后续发布变化。

## 维护者上传

上传接口：

```text
POST http://154.17.28.23/api/material-registry/v1/packages/upload
```

独立 Registry 服务使用 Bearer token，不再使用旧版主应用的 official password header。

正确鉴权头：

```text
Authorization: Bearer <LUMINA_REGISTRY_TOKEN>
```

错误示例：

```text
X-Lumina-Material-Registry-Official-Password: ...
```

这个旧头不会被云端独立服务接受，会返回：

```json
{"detail":"maintainer role is required"}
```

真实 token 和开发者上传/审批命令不应写入公开仓库或 issue。

## 常见问题

### catalog 能访问，但上传返回 403

原因通常是没有带维护者 Bearer token，或仍在使用旧的 `X-Lumina-Material-Registry-Official-Password` 头。

### 上传接口 404

确认路径是：

```text
/api/material-registry/v1/packages/upload
```

不是：

```text
/api/material-registry/v1/materials/upload
```

### package 下载失败

Lumina 客户端要求 catalog URL 和 package URL 是同一个 origin，并拒绝重定向。不要把 catalog 指到一个域名、package 指到另一个域名。

### HTTPS

当前公开连接方式以本文“服务地址”小节为准。HTTPS、域名、反向代理和证书等部署细节由部署方在私有运维文档中维护，公开文档只记录普通连接者需要使用的地址和客户端配置。
