# 第二轮复审响应

日期：2026-09-20

本文件逐项回应《Lumina_编辑一致性_报告复审与第二轮收口Prompt.md》。审查结论只覆盖当前 worktree 的源码与确定性测试；没有用户现场 request ID、生产堆栈或真实用户素材，因此不把现场“最后生成报错”归因成某一个已确认根因。

## 1. 非确定响应与“回退”语义

已补齐 `api/editor_commit.py` 和 `GET /api/convert/editor-commit/{session_id}/{operation_id}`。每个 session 只保留最近 64 条操作确认元数据，状态为 `pending`、`committed`、`failed` 或 `unknown`。它不保存第二份 RGB、mask、历史或作品状态。

- `committed`：服务端已完成现有缓存、会话字段、历史和版本收敛；前端记录服务端返回的编辑版本，并尽力重新读取共享选区文档。
- `failed`：服务端在提交边界前确认没有发布；前端保留上一份已提交作品，允许下一次编辑继续。
- `pending`、`unknown` 或查询失败：结果未知；前端保留草稿和错误上下文，挂起依赖编辑、选区和生成，不按版本差值猜成功或回滚，也不重放 toggle/undo/redo。

旧 session 或旧响应不会直接覆盖当前页面；旧响应无论成功还是错误，都会查询同一个 operation receipt。若同一 `operation_id` 已有回执，服务端在缓存、历史或会话变更前返回 409，客户端必须查询原回执而不是重放。`converter-store-selection-race.test.ts` 使用受控 Promise 覆盖了同 session 旧响应、会话切换、response lost、unknown receipt、旧错误响应和选区 hydration 失败。Escape 仍只退出 `Color2DOverlay`，没有证据表明它清理作品或历史，因此未删除正常退出行为。

## 2. 统一提交边界与锁

内容编辑继续复用现有 preview-cache transaction、`SessionStore`、replacement history、`SelectionDocument` 和 GLB token/CAS。没有新增第二套编辑 store、mask、历史、数据库事件溯源或全局锁。

`_preview_cache_transaction` 和带 history 的事务现在在 session 级 `replacement_history_lock` 内完成缓存与会话收敛；`cache.commit` 成功前不清理旧作品字段。选区变更也通过 `_replacement_selection_lock` 按统一的 `replacement_history -> selection` 顺序获取锁，避免内容提交与选区 checkpoint 产生反向等待。GLB 调度在提交回执发布之后执行，GLB 失败只进入派生工件错误边界，不撤销已提交 RGB、材料矩阵、配方和历史。

已对 reset、普通替色、批量替色、区域替色、配方、渐变、自由色、撤销/重做等入口接入 operation receipt。提交前可确定失败会写入 `failed`；缓存或会话已经越过发布边界后再出错则保持 `pending/unknown`，避免把部分提交伪报成回滚。配方覆盖特别验证了 cache 已发布后历史写入失败的路径：旧 session 不再恢复，已发布 cache/配方保持，回执不伪报 `failed`。

## 3. 生成快照

标准、拼图和大画幅入口都调用 `api/routers/converter/generate.py` 的共享快照逻辑，拼图入口复用同一 helper：

1. 在 session 级 history/selection 短锁内校验客户端提供的 `editor_content_revision` 和 `selection_revision`；
2. 深拷贝生成需要的完整 session/cache 输入；
3. 释放锁后再组装 worker 参数和执行昂贵任务；
4. worker 前后再次校验当前 session 版本；
5. 响应携带实际输入版本，旧生成结果不能注册为当前作品。

生成不等待与它无关的 GLB 任务。真实过期生成仍返回 409，版本校验没有被删除。`tests/test_converter_generate_unit.py`、拼图/生成集成回归以及大画幅相关测试覆盖了 worker 开始后 session 变化仍只消费不可变快照的路径。

## 4. 配方与持久空间目标

配方层数属于 `recipe_overrides` 的编辑派生状态，不再把它写回基础 `color_layers`/`layer_height_mm` 后触发破坏性自动预览。legacy/native 增层、同层数和 material 来源已有对照测试；真实 source、几何和基础输入变化仍保留原自动预览失效路径。

已应用手工配方继续使用 `recipe_override_applied_masks` 的持久压缩 mask。动态重建、生成和历史恢复统一调用 `resolve_recipe_override_masks`：现代 session 缺少或损坏必要 mask 时确定性拒绝，不读取后续变化的临时 `editor_selection`，不扩大为全图；只有没有快照键的旧 session 才使用显式 legacy fallback。A 配方 → clear/改选 B → 非重叠 B 动态换色的材料矩阵回归已通过。

## 5. 前端排序与响应处理

内容编辑在第一次 `await` 前同步占位；同 session 同类内容编辑串行，选区等待内容提交，依赖选区的内容操作和生成等待选区提交。成功响应统一合并服务端 `SelectionDocument` 和版本，客户端不再执行 `content_revision + 1`。旧响应如果可能已经在服务端执行，则查询同一 operation receipt；旧错误响应也走这条路径，不会仅仅丢弃响应或重放操作。

前端 barrier 只是请求排序器，不保存作品或历史。已知 pre-commit 失败释放后续队列；unknown receipt 保持挂起，ActionBar 提供显式“同步编辑状态”入口。受控 Promise 测试验证了提交前失败可继续、unknown 会暂停、确认后才能恢复，以及同一事件循环内的同类编辑不会同时使用旧版本。

## 6. 证据等级与未确认风险

- A 级：本地真实 endpoint、`SessionStore`、preview cache、replacement history、材料矩阵和生成快照参与的后端回归；受控 Promise 的前端竞态回归。
- B 级：前端 store 与 API 客户端的版本/回执合并测试；构建和 lint。
- C 级：用户现场“多位用户最后生成报错”的具体类别。当前没有现场 request ID、堆栈或真实素材，不能确认它属于 session 失效、参数校验、矩阵不一致、求解失败还是仅 GLB 预览失败。

全量后端收集仍受环境缺少 `rasterio`、`lumina_svg_core` 阻断；全量前端只剩不相关的 `batchStore.test.ts` 既有参数快照失败。本轮相关 converter/generate/puzzle 测试、前端受影响集合、构建、lint、compileall 和 diff check 已分别执行，详见 `TEST_REPORT.md`。
