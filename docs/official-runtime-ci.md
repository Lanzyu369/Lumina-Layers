# 官方安装包的云端候选构建

源码及开发继续在公开 Lumina-Layers。官方安装包、私有适配源码、构建日志及诊断均保留在私有分发链路。公开源码 nightly 的发布规则不变。

`Build private official runtime candidates` 仅能从本仓库 `main` 手动运行。它验证源码提交已进入 main 历史，然后用标准 Windows x64 与 macOS arm64 runner 并行构建。macOS 使用 `macos-15`；目标部署版本仍由现有打包器约束。

运行时固定四项输入：Layers 完整 SHA、Distribution 完整 SHA、发行轨道和 Unix 时间戳；重跑失败 job 继续使用原输入。`public` 对应正式版，`nightly` 使用同一公开来源并生成 nightly 版本名。兼容既有启动器的内部频道字段由私有发行工具处理。

## 首次启用

先审核并推送包含 `scripts/cloud_candidate.py` 的私有 Distribution 提交，再在 Layers 配置：

- Variables：`DISTRIBUTION_APP_CLIENT_ID`、`R2_ENDPOINT`、`R2_BUCKET`。
- Secrets：`DISTRIBUTION_APP_PRIVATE_KEY`、`R2_ACCESS_KEY_ID`、`R2_SECRET_ACCESS_KEY`。
- GitHub App 只需读取 `Lumina-Distribution` 的 contents。R2 使用现有发行桶的专用上传凭据。

这些配置不能放进源码、dispatch 输入或日志。dispatch 输入及工作流日志公众可见，release notes 只填写可公开的变更说明。

## 构建与发行的衔接

任务只构建和验证候选，然后调用现有 `scripts.ci_candidate upload` 直接写入私有 R2。它不创建公开 Release 资产或 Actions Artifacts，也不把工作目录、成品或私有源码放入 Actions 缓存。构建细节只进入私有诊断对象。

控制端用实际 `run_id`、各平台成功的 `attempt`、`target` 和固定 `source_sha` 调用现有 `scripts.ci_candidate fetch`。拿到相同身份的两端候选后，继续原有增量生成、私有源验证和授权分发步骤。重跑单个平台时，保留另一平台已成功的 attempt；不要混用不同源码、Distribution 或发布时间的候选。

此工作流不更新在线 catalog、不调整用户权益、不发布或重建启动器，也不恢复已暂停的自动发版。迁移完成需另有两端真实云构建及私有传输通过记录；静态验证不等同于已上线。

Runner 类型依据：[GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。
