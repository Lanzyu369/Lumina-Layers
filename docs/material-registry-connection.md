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

配置后，Lumina 会从云端 catalog 读取耗材列表，并按用户选择下载 package 到本地耗材库。云端不会自动读取或上传用户本地耗材。

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
