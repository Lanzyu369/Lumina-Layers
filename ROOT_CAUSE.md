# 颜色调整回退与生成报错：本地根因调查

日期：2026-09-20

## 结论与证据边界

本次确认的是本地代码和确定性测试中的状态一致性漏洞，不是对“多位用户现场请求”的事后推断。仓库没有提供用户现场的 request ID、服务端堆栈或页面录屏，因此不能把所有现场生成错误归因于同一条链路；下文把“已确认”和“待现场确认”分开记录。

已确认的共同问题是：编辑结果、共享选区、历史、预览派生工件和生成请求此前没有使用同一个已提交版本边界。失败后的局部回滚也只覆盖部分缓存字段，不能保证会话字段、持久 mask、历史和版本一起回滚。

## 调查基线

- 远程审查基线：`dev-refactor` / `fa219ace8ea4bd4c1ffafc74f0b212ca8d3932fc`。
- 工作分支：`MIn/fix/editor-state-consistency`；调查开始时工作树干净，未使用 `reset`、`clean`、回退或 cherry-pick。
- 运行时：Python 3.14.5，Node v25.9.0；`frontend/package.json` 声明版本 `2.0.0`、`pnpm@10.33.2`，本机实际 pnpm 11.19.0；构建实际使用 Vite 6.4.2、Vitest 4.1.7。仓库没有独立的后端应用版本字段，后端版本以当前提交代码标识。
- 运行实例核对：调查初期发现的开发服务工作目录是另一个 `/Users/min/CascadeProjects/Lumina-studio`，不是本 worktree；本次没有把它当作目标仓库的复现证据，也没有结束它。最终验证使用当前 worktree 的脚本和源码。
- SessionStore：默认 `LUMINA_BACKEND` 未设置，使用进程内内存 `SessionStore`，TTL 1800 秒；PostgreSQL 是显式环境变量分支。文件注册表默认同样是内存实现。
- Worker/cache：当前机器 `os.cpu_count()=10`，默认 `ProcessPoolExecutor` 上限为 `min(cpu, 4)=4`；macOS 默认每个子进程最多执行 1 个任务（环境变量未设置）。`LUMINA_MAX_WORKERS`、`LUMINA_PREVIEW_CACHE_MAX_BYTES` 未设置，预览缓存没有显式字节拦截上限；调查时主机总内存约 16 GiB、可用内存约 3.1 GiB，仅作环境记录，不是压测结论。
- 既有基线：后端相关测试 93 passed；前端选择/自动预览相关测试 56 passed。

## 已确认根因

### A. 全局/同色替换后客户端猜测了内容版本

基线中全局换色和批量换色会推进可见内容缓存 generation，但成功响应没有始终携带完整的共享 `SelectionDocument`。前端随后用本地 `content_revision + 1` 或保留旧选区继续发起点选/同色/画笔请求。真实时序是：

```text
selection/mutate(base=R, content=C) -> 客户端显示 R/C
replace-colors-batch -> 服务端提交内容并推进 generation=C'
下一次 selection/mutate(content=C) -> 服务端按真实 C' 拒绝 409
```

这不是“用户点击太快”才能触发的假设；同一 session 的顺序调用就能稳定复现。修复证据包括：`frontend/src/stores/converter/store.ts:357` 的权威响应合并、`api/routers/converter/replace.py:2649` 的服务端提交后选区版本绑定、`api/routers/converter/replace.py:3872` 的批量替色入口，以及真实替色 endpoint 的 50 次连续编辑测试。

现在所有相关替换响应都返回服务端生成的选区文档。客户端只接受不早于已确认版本的 `(selection_revision, content_revision)`，不再自行计算 revision。真实过期请求仍由后端 409 拒绝。

提交响应丢失也不再直接把本地乐观编辑当成未发生：前端先查询带 operation id 的
`GET /convert/editor-commit/{session_id}/{operation_id}`。回执明确区分三种状态：
`committed` 表示缓存/会话/历史已收敛，`failed` 表示服务端确认尚未提交，
`pending`/`unknown` 或查询失败表示结果未知。前两种状态可以释放同 session 的内容
屏障；未知状态保留草稿和错误上下文，暂停依赖选区、编辑和生成，不能根据版本差值猜
“成功”或“回滚”。`committed` 时再尽力读取
`GET /convert/selection/{session_id}` 以补齐选区文档；选区读取失败不改变已确认的
内容结果，而是继续使用本地已确认的 selection revision。旧 session 的响应先经过
session/epoch 校验，不会触碰新页面状态。该时序由
`converter-store-selection-race.test.ts` 的 response-lost、same-session stale、
unknown-receipt 和 hydration-failure 用例覆盖。

### B. 配方编辑被当作基础输入变化，触发破坏性自动预览

`useAutoPreview` 的 legacy/native `inputKey` 包含基础 `color_layers` 和 `layer_height_mm`（`frontend/src/hooks/useAutoPreview.ts:98-125`）。旧路径在 `upsertRecipeOverrides` / 应用配方时还会改写基础层数，于是配方增层被自动预览当成重新选择基础输入：`invalidatePreviewForAutoRefresh` 清除 session，再创建新 session，配方覆盖、局部替色和选区随之消失。

这条路径已用改变层数的 legacy 配方、同层数配方和 material 来源对照测试确认。修复不是删除自动预览依赖，而是把配方层数保留为编辑派生数据：`upsertRecipeOverrides` 只更新 `recipe_overrides`，生成时通过 `resolveRecipeAwareLayerCount` 计算实际层数；真实 source、几何或基础输入变化仍走原有预览失效路径。

### C. 已应用配方的空间目标依赖会变化的临时选区

应用手工配方时，后端已经有 `recipe_override_applied_masks`，但动态材料重建此前继续读取可变的 `selected_region_masks`。后续 clear/改选会清理 `__editor_selection__:<revision>` 条目，导致早先的区域 A 在动态换色 B 或生成时可能没有保护 mask。这个问题可能静默覆盖材料矩阵，不应被描述成必然抛出某一种异常。

现在 `api/selection_state.py:82-170` 统一解析规则：具备快照能力的 session 只使用应用时的位压缩 mask；缺失、空、形状不符时确定性报错，不能扩大为全图；只有真正没有快照键的旧 session 才允许显式 legacy fallback。`api/routers/converter/replace.py:1125-1136`、`api/routers/converter/replace.py:5652-5664` 和 `api/routers/converter/generate.py:1606-1621`、`api/routers/converter/generate.py:2225-2235`、动态重建入口共同使用该规则。A 配方 → 改选 B → B 动态换色的非重叠矩阵测试已通过。

### D. 生成请求没有明确等待编辑提交，也没有服务端版本门槛

此前 `submitGenerate` 可以与正在进行的换色/配方请求并行，生成输入会拼接半旧半新的 store 状态；后端也没有用编辑内容版本阻止这种请求。现在前端等待选区和内容屏障，捕获生成 epoch 并丢弃旧生成响应；请求携带服务端确认的 `editor_content_revision` 与 `selection_revision`。标准、拼图和大画幅生成都在共享的短锁内捕获完整 session 深拷贝，并在组装 worker 输入前后校验两种版本；响应回传实际输入版本。worker 只消费这份不可变快照，派生 GLB 不属于生成前置等待条件。

因此真正过期的生成仍是 409，而不是被“吞掉”；正常顺序编辑不需要失败后重新点击来同步。

### E. 缓存回滚与会话/派生工件提交边界不一致

`reset_replacements` 原先在缓存提交前清理 session 的 replacement、配方和快照字段；如果缓存事务失败，上一份缓存可能还在，但会话已丢失编辑状态。现在清理动作位于 `cache.commit` 成功之后（`api/routers/converter/replace.py:1605-1770`），并增加了失败保持旧会话字段的测试。

GLB 是派生工件，不是 RGB/材料矩阵的提交条件。替换/配方成功提交后，GLB 调度异常由 `api/routers/converter/replace.py:596-620` 和 `api/routers/converter/async_glb.py` 的显式边界处理：记录带 `content_commit=committed` 的结构化 warning，并通过现有 token/CAS 发布派生错误状态；不会把已提交作品回滚成旧作品。GLB token/CAS 仍保留，旧任务不能覆盖新内容。

前端清空替换在请求失败时也保存并恢复颜色映射、历史、配方、区域计数和预览派生字段；
若状态查询确认清空已经提交，则不恢复这些字段，只同步服务端版本并保留错误上下文。

## 第二轮复审收口

第二轮复审重点验证了“失败后到底是什么状态”，而不是把所有非 200 都当作回滚：

- 后端新增有界的 editor commit receipt（每个 session 最近 64 条），operation id、
  `editor_content_revision`、可见缓存 generation、选区 revision 和提交状态一起记录；
  这只是现有 session/缓存/历史提交点的确认记录，不是第二套作品状态或历史。
- 同 session 的同类内容编辑在前端先占位再等待；已知提交前失败会释放后续编辑，未知
  回执保持屏障挂起。旧响应的成功和错误分支都查询同一个 operation receipt；同一个
  `operation_id` 的重复请求在后端提交前被 409 拒绝，不能重复写入替换、历史或版本。
  旧响应不会直接 repaint 当前作品，也不会盲目重放 toggle、undo、redo；同步按钮只能
  查询同一个 operation receipt。
- 标准、拼图、大画幅生成均在 worker 前复制完整 session 输入，并以内容/选区两个独立
  revision 做双重 CAS 式校验；worker 结束后再次校验，旧导出结果不会注册成当前作品。
- 配方 cache 已发布后若历史/派生会聚阶段抛错，不再恢复旧 session 或让 cache 事务回滚；
  保留已发布状态并维持 pending/unknown，让页面走明确同步路径，而不是制造新 cache 配旧
  配方的“半回滚”。
- 证据等级：本地真实 endpoint/SessionStore/缓存/历史状态参与的 converter、generate、
  puzzle 回归为 A 级；受控 Promise 的前端竞态为 A 级行为证据；没有现场 request id、
  生产堆栈或真实用户素材，因此“多位用户最后生成错误”的具体类别仍为 C 级待确认。

## “回退”现象的单独调查

`Color2DOverlay` 的 Escape 处理只在 `frontend/src/components/widget/Color2DOverlay.tsx:65-78` 调用 `closeOverlay()`，作用是退出 2D 颜色子页；现有 `color2DOverlayAutoPreview.test.tsx` 覆盖了 overlay 内的自动预览归属。没有本地证据表明 Escape 本身清理了作品、历史或 session，因此没有删除正常退出行为，也没有把它宣称为根因。

本地“回退”可由以下状态链解释：旧内容响应被过期响应覆盖、自动预览重建 session、失败恢复把乐观选区而非已确认选区写回、或 GLB 失败被误当成编辑失败。修复分别落在权威版本合并、派生配方与基础输入分离、确认选区回滚和 GLB 派生边界；页面退出本身不承担作品回滚。

## 未确认事项

- 没有用户现场日志、request ID 或真正生产生成堆栈，无法确认现场“最后生成报错”具体属于 session 失效、参数校验、矩阵不一致、求解失败还是仅 GLB 失败。
- 本地已证明过期生成会被 409 拒绝、GLB 调度失败不会撤销二维编辑，但没有把这两点外推为所有现场失败的唯一来源。
- 未执行无上限大内存压测，也没有启动并保留新的本地服务进程。
