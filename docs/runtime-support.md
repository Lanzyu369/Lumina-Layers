# Runtime support

## Current contract

- Run from source with `python api_server.py` or `python start_all.py`, or use
  the Electron desktop app. See the [installation guide](../README.md#installation)
  and [desktop guide](desktop-electron.md).
- Packaged Electron starts the backend and uses its built frontend serving.
  `LUMINA_SERVE_FRONTEND_DIST` and `LUMINA_FRONTEND_DIST_DIR` remain supported.
- Local settings, slicer launch, feedback, cache cleanup and material management
  keep their origin guards. The retired `LUMINA_ALLOW_PUBLIC_GRAY_API` variable
  has no effect.
- Development servers keep explicit `VITE_ALLOWED_HOSTS` configuration. The
  retired `VITE_ALLOW_ALL_HOSTS` variable no longer bypasses the host allowlist.
- PostgreSQL backends and migrations remain opt-in. Provision a database
  independently and follow the [server backend guide](server-mode-scaffold.md).
- Native SVG wheels and checks run on Windows, macOS and host Linux. Linux
  wheels use the Ubuntu 24.04 system ABI; an older glibc host needs a source build.
- Linux cgroup CPU/memory limits and the optional local GEOS dense-buffer
  runtime remain independent of deployment packaging.

## Retired on 2026-10-06

Docker image builds, Compose provisioning, PowerShell container deployment,
scheduled container updates, public-test origin bypasses, image-based CI and
container-based Linux wheel builds are removed. No replacement deployment or
compatibility switch is provided.

Historical design plans, experiment results and old changelog entries retain
their original evidence. References there to the retired deployment describe
past behavior and must not be used as current installation instructions.
This document owns the current support decision. Source changes do not remove
previously installed services, scheduled tasks or user data.

## 中文说明

当前支持源码本地运行和 Electron 桌面客户端。桌面页面服务、本地访问限制、
Linux 资源限额检测、可选 PostgreSQL 后端及本地 GEOS 构建均继续保留。
Linux 原生组件改为直接在 Ubuntu 24.04 主机上构建；较旧 glibc 系统需要源码构建。

2026-10-06 起移除 Docker 构建、部署、定时自动更新、数据库容器配置、
相关 CI 及公网测试访问旁路。旧开关 `LUMINA_ALLOW_PUBLIC_GRAY_API` 和
`VITE_ALLOW_ALL_HOSTS` 不再生效，开发服务器仍支持显式主机名单。
历史文档仅记录当时的实现和验证结果，以本文和当前安装指南为准。
本次源代码清理不会删除已有服务、定时任务或用户数据。
