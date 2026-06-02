# Local Docker Deployment

本页记录 Windows 本机临时部署流程，用于把 Lumina Studio 主应用跑在 Docker
Desktop 中，并把运行时数据写入 E 盘，避免撑爆 C 盘。当前本地部署恢复为
Lumina 主应用完整开发基线：耗材、LUT、校准和提取路由都由主应用本地提供。

## Services

容器内启动主应用的两个服务：

| Service | Port | URL |
| --- | --- | --- |
| Main frontend | 4174 | `http://localhost:4174` |
| Main backend | 8000 | `http://localhost:8000/api/health` |

## Runtime Data

默认运行时根目录：

```powershell
E:\Lumina-Layers\lumina-runtime
```

The deployment script bind-mounts these paths into the container:

| Host path | Container path | Purpose |
| --- | --- | --- |
| `E:\Lumina-Layers\lumina-runtime\output` | `/app/output` | previews, temp files, generated models |
| `E:\Lumina-Layers\lumina-runtime\logs` | `/app/logs` | structured JSONL logs |
| `E:\Lumina-Layers\lumina-runtime\feedback` | `/app/feedback` | bug-report bundles |
| `E:\Lumina-Layers\lumina-runtime\lut-preset` | `/app/lut-preset` | local LUT presets used by the main app |
| `E:\Lumina-Layers\lumina-runtime\user_settings.json` | `/app/user_settings.json` | backend settings |

On first run, `lut-preset/` is seeded from the repository if the runtime copy is
empty.

## Build And Start

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\docker_local_deploy.ps1
```

For LAN or tunnel testing, pass the host name that testers will use:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\docker_local_deploy.ps1 `
  -PublicHost "your-tunnel-host.example"
```

To keep the container's internal Vite port at `4174` but expose a different
host port, pass `-PublicFrontendPort`. For the production split test where
`online.luminastudio.com.cn:53278` should reach this machine over IPv6:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\docker_local_deploy.ps1 `
  -PublicHost "online.luminastudio.com.cn" `
  -PublicFrontendPort 53278
```

Material and LUT data are served from the main app's local routes and the
bind-mounted runtime directories.

## Operations

```powershell
docker logs -f lumina-layers-local
docker rm -f lumina-layers-local
docker system df
```

## Auto Update

Run once:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\docker_auto_update.ps1 `
  -Remote origin `
  -Branch dev-refactor
```

Watch mode, polling every five minutes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\docker_auto_update.ps1 `
  -Remote origin `
  -Branch dev-refactor `
  -Watch `
  -IntervalSeconds 300
```

The auto-update script refuses to run when the worktree has local changes.
Commit or stash local changes first, then rerun it.

## Manual Assistance Points

Human input is still needed when:

- Git requires credentials or cannot access GitHub.
- Docker Desktop is not running or asks for privileged setup.
- The public host/tunnel URL changes and the container must be restarted with a
  new `-PublicHost`.
