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
- Native SVG uses the independent AGPL-3.0-only `lumina-svg-core` 0.3.1 release.
  Studio CI installs and verifies the published wheels on Windows, both Mac
  architectures and Linux. Linux x86-64 wheels use manylinux_2_28 / glibc 2.28+;
  Python 3.12/3.13 Mac wheels require macOS 12+, and Python 3.14 requires 14+.
  Unsupported wheel targets need the release source archive and a C++17 toolchain.
- Linux cgroup CPU/memory limits and the optional local GEOS dense-buffer
  runtime remain independent of deployment packaging.
- The Studio repository's Windows desktop build uses `scripts/build_desktop.py`
  and `lumina_studio.spec`. The official Windows/macOS beta pipeline is maintained
  in the private Lumina-Distribution repository; its source overlay must use the
  same FatCat dependency and picker-asset contract before integrating this branch.
  The former Gradio `main.py` packaging workflow and bundled application
  3MF template file have been retired; metadata data comes from FatCat.

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
本仓库的 Windows 桌面构建使用 `scripts/build_desktop.py` 和 `lumina_studio.spec`；
官方 Windows/macOS 内测流水线位于私有 Lumina-Distribution 仓库，其覆盖脚本
需要同步 FatCat 依赖及选择器资源合同后才能集成本分支。旧 Gradio
启动文件的打包流程及本体内置 3MF 模板文件已移除，元数据配置来自 FatCat。
SVG 使用独立项目发布的 AGPLv3 运行时 `lumina-svg-core` 0.3.1，CI 安装并核验
发布包。Linux x86-64 要求 glibc 2.28+；Mac 的 Python 3.12/3.13 包要求 macOS 12+，
3.14 要求 macOS 14+。没有兼容 wheel 的平台需要从发行源码包构建。

2026-10-06 起移除 Docker 构建、部署、定时自动更新、数据库容器配置、
相关 CI 及公网测试访问旁路。旧开关 `LUMINA_ALLOW_PUBLIC_GRAY_API` 和
`VITE_ALLOW_ALL_HOSTS` 不再生效，开发服务器仍支持显式主机名单。
历史文档仅记录当时的实现和验证结果，以本文和当前安装指南为准。
本次源代码清理不会删除已有服务、定时任务或用户数据。
