# 颜色调整编辑状态一致性修复计划

> 本计划用于当前本地修复任务；不替代 `AGENTS.md`，也不把附件中的假设视为已确认根因。

## 目标与边界

修复颜色调整编辑、选区、预览、历史和生成之间的版本与空间状态一致性。复用现有
`SelectionDocument`、`SessionStore`、`replacement_history`、preview-cache revision、
GLB token/CAS 和已应用配方掩码快照；不新增第二套编辑状态、历史栈或 mask 系统。

验收重点：

1. 成功的内容修改从服务端响应同步真实 `selection_revision` / `content_revision`，客户端不猜版本。
2. 选区失败回滚同时校验选区版本和内容版本，旧 GET/旧响应不能覆盖新作品。
3. 配方编辑的派生层数不再伪装成基础预览输入；真实基础输入变化仍会触发自动预览。
4. 动态材料重建和生成都从同一份持久配方目标解析规则读取区域掩码。
5. 生成只消费已提交编辑快照；不等待无关 GLB，旧生成响应不能重新显示为最新下载结果。
6. 提交前失败保持上一份已提交作品；提交后只失败派生渲染时不撤销已提交编辑。

## 执行任务

### 1. 基线与证据记录

- 保存 `git status`、分支/HEAD、远程基线、Python/Node/pnpm、SessionStore 后端、worker
  配置、预览缓存/工件模式、实际运行进程来源。
- 运行与本问题直接相关的现有 pytest/Vitest 测试，记录通过/失败/环境阻塞。
- 检查真实按钮路径、`submitGenerate` / `submitFullPipeline`、API 响应结构、历史恢复、
  GLB 状态轮询和 Escape 传播；将证据分为“已复现”“代码证据”“待现场确认”。

### 2. 先写确定性失败测试（RED）

- 前端：同色/批量内容替换返回新的 selection 文档后，下一次 point/same-color/brush
  操作必须使用服务端返回的内容版本；旧内容版本的失败回滚不得恢复过期文档。
- 前端：同一 store 中两个 session 的选区队列互不阻塞；会话切换与旧响应不会写入当前页。
- 前端：legacy/native 配方增层不会被 `useAutoPreview` 当作基础输入清空 session；普通
  `setColorLayers` / `setLayerHeightMm` 仍会触发自动预览。
- 后端/核心：区域 A 的已应用配方掩码在清除/改选 B 后仍保护 A；B 的动态换色只重建
  自动区；缺失或错误持久掩码确定性拒绝，不扩大为全图。
- 前端/后端：生成在 replace/apply 请求尚未完成时等待该提交结果；编辑开始后晚到的生成响应
  不覆盖最新作品；失败响应不回滚已提交 cache/session 字段。
- 后端事务：在 cache commit 前注入失败时，replacement/recipe/mask/history/session 字段与
  cache 一起回滚；GLB 异步失败只记录派生失败。

测试使用受控 Promise、事件闩锁和小型 ndarray fixture，不使用随机 sleep；至少一条集成测试
走真实 SessionStore、真实 visible-region generation、真实材料矩阵/掩码和真实导出解析。

### 3. 最小实现

1. **统一内容响应同步**

   - 给 global single/batch replace、reset、recipe apply 等内容响应补充可选的权威
     `selection` 文档（服务端在内容版本递增后构造，不能由客户端 `+1`）。
   - 前端抽取一个内部 response reconciliation helper：统一更新 selection document、
     `confirmedSelectionRevisions`、预览/历史字段；删除 multi-select 成功分支的版本猜测。
   - selection mutation 仍保留真实 409；回滚条件同时比较 selection revision 和
     content revision，必要时 GET hydrate，而不是盲目恢复旧文档。
   - 把 selection mutation queue 改为按 session 分桶，避免跨 session 的全局串行化。

2. **基础输入与编辑派生分离**

   - `upsertRecipeOverrides` / `applyCustomRecipeOverride` 不再写回作为 auto-preview key
     的基础 `color_layers` / `layer_height_mm`。
   - 生成请求用一个纯函数从基础层数和当前 recipe override 推导有效层数；material 动态
     模式仍使用其既有 max/print-layer 规则。
   - 保留真实基础 setter 的自动预览行为，并补充同层数/增层/真实来源变化对照测试。

3. **持久空间目标解析**

   - 在 `api/selection_state.py` 增加共享的、形状校验的 applied-mask resolver：现代会话
     优先 `recipe_override_applied_masks`，旧会话才允许 live region fallback；缺失/损坏
     的现代条目抛出可映射的完整性错误。
   - replace 动态重建、recipe apply 的 dynamic metadata、generate worker inputs 使用同一
     resolver；传给 core 的始终是请求局部的 resolved masks，不把解包数组写回 SessionStore。
   - core 对声明的 recipe override 不再静默跳过缺失/形状错误 mask；由 API 边界转换成明确
     4xx/422，且不把 mask 扩大到全图。

4. **生成提交边界**

   - 增加按 session 的“最后一次内容提交” Promise barrier，仅等待 replace/recipe/reset/
     history 等内容提交 HTTP 结果，不等待无关 GLB。
   - generate 捕获提交前的 session/content snapshot；必要时把 editor content revision
     作为后端校验输入，拒绝 cache 已前进的半旧请求。
   - generate response guard 绑定 session、编辑 epoch/content snapshot 和设备身份；编辑
     开始后旧 3MF/GLB response 不能重新成为当前下载结果。
   - 未知/丢响应路径只做显式 selection/state hydrate，不自动重放 toggle/undo/redo；保留
     可恢复草稿和错误上下文。

5. **事务边界**

   - 为 reset 及其他会先写 session 字段的内容入口保存并恢复同一批 session 字段；cache
     revision conflict 或派生失败不能留下半提交 recipe/mask/history。
   - 保留现有 async GLB token/CAS；只在有证据的地方修复内容提交，不把 GLB 失败当成内容
     409 根因。

### 4. 绿色回归与有界验收

- 先逐条运行新增失败测试确认 RED，再实现后逐条确认 GREEN。
- 运行相关 backend pytest、frontend wrapper 的类型/测试/构建；按仓库脚本记录命令。
- 用确定性小 fixture 做 50 次连续编辑，验证正常流程无自身版本 409，并构造一个真实旧
  content/selection revision 请求确认仍被拒绝。
- 验证 undo/redo、session 切换、旧响应、提交前/提交后失败、A/B 非重叠矩阵和最终生成工件：
  解析 3MF 的材料身份/矩阵数据，不只检查 HTTP 200、PNG 或文件非空。
- 检查本次启动的测试/服务进程已退出；不触碰已有另一个 checkout 的运行进程。

### 5. 交付文档

现行契约与回归入口已收敛到[编辑工作流说明](../../context/editor/CONTEXT.md)，
包括统一发布边界、版本分类、持久 mask、生成快照和证据限制。
本计划对应的历史调查及测试记录保留在 Git 历史中；当时的环境与通过数不代表当前验证结果。
