# Launcher and distribution ownership / 启动器与分发边界

- [Lumina-Launcher](https://github.com/lumina-layer-studio/Lumina-Launcher) is private and owns launcher UI, activation, installation, version selection and updates.
  启动器私有仓库负责启动器界面、激活、安装、版本选择和更新。
- [Lumina-Distribution](https://github.com/lumina-layer-studio/Lumina-Distribution) is private and owns official runtime packaging, seed selection, release manifests, incremental packages and publication.
  分发私有仓库负责官方运行包构建、预装资源选择、版本清单、增量包和发布。
- Studio owns the Electron/Python application and its managed-runtime interfaces, including `electron/managed-runtime.cjs`, `electron/managed-startup.cjs` and the `launcher-startup.json` protocol marker. These are consumers of launcher configuration, not a second launcher.
  Studio 保留 Electron/Python 本体和被启动接口；这些文件消费启动器配置，不是第二套启动器。

Managed versions share settings, custom/cloud LUTs and materials while keeping derived caches and logs version-scoped. Readiness requires an owned healthy backend and a loaded visible main window. Interface changes must be coordinated across repositories without importing another repository's source tree.

托管版本共享设置、自定义/云端 LUT 与耗材，派生缓存和日志按版本隔离。就绪状态必须同时满足自有后端健康、主窗口加载完成且可见。协议变更需跨仓库协调，不使用跨仓库源码导入。

Existing generic source-build and validation files are not removed solely because their names contain `build` or `release`. Official packaging changes belong in Distribution; native installer acceptance is separate from Studio's runtime regression tests.

现有通用源码构建与验证文件不会仅因名称含 `build` 或 `release` 被删除。官方打包变更归 Distribution；原生安装器验收与 Studio 运行时回归测试分别进行。
