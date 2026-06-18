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
| `E:\Lumina-Layers\lumina-runtime\materials` | `/app/materials` | local material library |
| `E:\Lumina-Layers\lumina-runtime\user_settings.json` | `/app/user_settings.json` | backend settings |

On first run, `lut-preset/` is seeded from the repository if the runtime copy is
empty. `materials/` is only a writable runtime volume. To preload official
materials, pass a reviewed seed artifact; the application imports it only when
the runtime material library is empty, then keeps all later user changes on the
runtime volume.

## Build And Start

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\docker_local_deploy.ps1
```

Optional official seed artifact:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\docker_local_deploy.ps1 `
  -MaterialsSeedPath "E:\Work\PythonProject\Lumina-materials\seed\lumina-materials-seed.zip"
```

Or build/download from a seed URL:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\docker_local_deploy.ps1 `
  -MaterialsSeedUrl "https://materials.example/releases/lumina-materials-seed.zip" `
  -MaterialsSeedSha256 "<sha256>"
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
bind-mounted runtime directories. Registry upload and approval routes are not
enabled in this distribution deployment.

## GLB Preview Kernel

本地 Docker 部署默认启用两条 GLB v2 预览链路：

```powershell
-GlbKernel v2
-VectorGlbKernel v2
```

该路径通过 `LUMINA_GLB_KERNEL=v2` 启用 `rasterio + manifold3d` 挤出实现；
如果依赖不可用或运行时失败，后端仍会回退到旧的 Shapely v1 路径。
这些原生依赖保存在 `requirements-glb-v2.txt`，由 Docker 镜像安装；普通
`pip install -r requirements.txt` 仍只安装默认 V1 路径需要的基础依赖。
`LUMINA_VECTOR_GLB_KERNEL=v2` 启用 SVG/vector 最终生成链路的 preview GLB
descriptor exporter；遇到冰箱贴凹槽、涂层或不支持的复杂几何时整次回退 V1。

真实前端 SVG 预览模型走 `preview_cache -> generate_segmented_glb`，也就是
`-GlbKernel` / `LUMINA_GLB_KERNEL` 这条链路。可用下面的本地 profile 入口
对同一张 SVG 做 V1/V2 对照：

```powershell
python scripts\profile_vector_preview_segmented_glb.py `
  "<path-to-complex-svg>" `
  --json-out logs\vector_preview_segmented_complex_svg_v1_v2.json
```

如需回退旧实现，重启本地部署时显式指定：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\docker_local_deploy.ps1 `
  -GlbKernel v1 `
  -VectorGlbKernel v1
```

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
