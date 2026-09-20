# 颜色调整状态一致性修复测试报告

日期：2026-09-20

## 1. 测试基线与 RED → GREEN

调查开始时记录的相关基线：

- 后端相关既有测试：`93 passed`。
- 前端选择/自动预览相关测试：`56 passed`。
- 基线代码中，全局替换后下一次选区使用旧 `content_revision`、legacy/native 配方增层触发 session 重建、已应用配方依赖临时选区、生成不等待编辑提交等路径均没有覆盖完整状态契约。

本次先加入受控 Promise/事件闩锁测试，先观察到以下 RED：

- 全局换色响应没有权威选区内容版本，下一次选择链路无法确认服务端版本。
- legacy/native 配方增层会把基础层数当成自动预览输入，导致 session/编辑状态被清空。
- A 配方快照在 B 选区变化后无法从实时 `selected_region_masks` 稳定解析。
- 生成请求可以早于 in-flight 替换完成；旧生成响应可在较新编辑之后回写。
- 提交响应丢失时，旧实现直接按失败路径处理，无法知道服务端是否已推进内容版本。
- reset 的缓存提交失败会留下“缓存旧、会话新”的半回滚状态。
- GLB 调度异常若沿用内容失败语义，会让已提交二维内容被错误回滚。

## 2. 通过的确定性回归

### 后端

命令：

```text
python3 -m pytest tests/test_editor_selection_unit.py tests/test_selection_recipe_regression.py tests/test_recipe_override_applied_mask_snapshot_unit.py tests/test_dynamic_material_editing_unit.py tests/test_converter_replace_integration_unit.py tests/test_replace_colors_batch_unit.py tests/test_converter_generate_unit.py tests/test_async_glb_unit.py -q
```

结果：`383 passed, 1 warning`。

另外的生成/拼图集成回归：

```text
python3 -m pytest tests/test_converter_puzzle_integration_unit.py tests/test_converter_generate_integration_unit.py -q
```

结果：`15 passed, 1 warning`。

覆盖的真实状态路径包括：

- 真实 batch replace endpoint 返回权威 selection 文档；随后 50 次连续内容编辑，revision 单调递增，最终 RGB 与未涉及区域的材料矩阵一致。
- 受控 A 配方快照 → clear/改选 B → B 动态换色；A/B 非重叠，A 的材料矩阵与持久 mask 保持。
- recipe mask 缺失、损坏、形状不符时确定性拒绝，不回退到实时选区或全图。
- reset 在 cache commit 注入失败时保留旧 session 字段。
- 生成进入 worker 前拒绝过期 `editor_content_revision`。
- GLB executor/scheduler 注入失败时，RGB/材料矩阵仍保持已提交状态，派生 GLB 单独进入错误边界。
- 选择、替换、配方和历史恢复响应均参与真实 `SelectionDocument`/版本处理，没有把核心逻辑全部 mock 掉。

### 前端

相关选择/预览/生成回归：

```text
python3 scripts/run_vitest.py run src/__tests__/converter-store-selection-race.test.ts src/__tests__/converter-store-relief-generate.test.ts src/__tests__/autoPreview.test.ts src/__tests__/converter-store-layer-images-invalidate.test.ts src/__tests__/color2DOverlayAutoPreview.test.ts src/stores/__tests__/converter-native-source.test.ts
```

结果：`6 files passed, 159 tests passed`。

此外，`converter-store-confirm-replacement-gradient-region.test.ts` 单文件结果为 `7 passed`。新加入的两个受控时序用例证明：

1. 选区 mutation 未确认时，selection-scoped replace 不会提前发请求；确认后发送服务端确认的 revision。
2. 内容 commit 未完成时，后续 selection mutation 不会使用旧 content revision；内容响应到达后请求使用新 revision。

补充的响应丢失与会话切换回归：

```text
python3 scripts/run_vitest.py run src/__tests__/converter-store-selection-race.test.ts src/__tests__/converter-store-relief-generate.test.ts src/__tests__/converter-store-confirm-replacement-gradient-region.test.ts
```

结果：`3 files passed, 41 tests passed`。其中新增用例让替换请求失败后查询
`GET /convert/selection/{session_id}`；服务端内容版本推进时，前端保留编辑映射并同步
权威 `content_revision`，旧 session 的失败响应仍不改写新页面。另有针对旧请求/session
切换的 `colorReplaceArchFix.property.test.ts` 与 `gradient-groups-panel.test.tsx` 单文件复跑通过，
分别为 `27 passed` 和 `29 passed`。

## 3. 类型、构建、静态检查

```text
cd frontend && pnpm build
```

结果：通过（`tsc -b && vite build`，Vite 6.4.2）。存在原有 dynamic import 和大 chunk warning；没有 TypeScript 错误。

```text
cd frontend && pnpm lint
```

结果：通过，0 errors、68 warnings。warning 为仓库既有风格/React Fast Refresh/raw color 等问题，不是本次修复新增的阻断错误。

```text
python3 -m compileall -q api core tests
git diff --check
```

结果：均通过。

## 4. 全量扫描与环境阻塞

最终前端全量命令：

```text
python3 scripts/run_vitest.py run
```

结果：`272 files passed, 3016 tests passed, 1 skipped, 1 failed`。唯一失败是本次不相关的 `batchStore.test.ts` 参数快照断言：实现多传了 `coating_height_mm`、`enable_coating`、`svg_hole_*`；相关 native 生成测试和本次选择/替换测试均通过。未修改该既有 batch 参数契约，因此保留为交付前风险，而不是把它伪装成全量绿。

后端全量收集到 `6747/6750` 个测试后被两个可选依赖导入错误阻断，原因是环境缺少：

- `rasterio`：`tests/test_glb_v2_kernel_unit.py`
- `lumina_svg_core`：`tests/test_native_svg_benchmark_contract_unit.py`

这两项不是本次改动触碰的模块；相关可运行的 converter/generate/puzzle 回归已单独执行并通过。未执行无上限大内存压测。

## 5. 人工验收步骤

1. 启动当前分支的后端与前端，创建一个小尺寸确定性预览。
2. 在同一个 session 依次执行：点选 → 同色选择/全局换色 → 画笔切换 → 再点选 → 再换色；观察网络请求中的 `selection_revision`、`content_revision`，不应因正常顺序操作出现自身版本 409。
3. 在选区请求保持 pending 时立即点击颜色替换；应看到替换请求等待，选区确认后只提交一次。
4. 对 legacy/native 配方把层数从 N 改为 N+1，再与同层数及 material 来源对照；session、选区和已应用配方不能被自动预览清空。
5. 区域 A 应用手工配方，清空/改选 B，B 做动态换色并生成；检查 A/B 非重叠区域的材料矩阵和导出模型，不只看 PNG。
6. 编辑后立即生成、再继续编辑；旧生成响应不能覆盖新编辑，过期请求应得到明确 409。
7. 对编辑、清空、撤销、重做各做一次并立即生成；若只出现 GLB 失败，二维作品和材料矩阵仍应保留，重试 GLB 不应重放颜色编辑。

现场日志仍需包含 request/session 安全标识、请求/当前 content revision、selection revision、提交阶段、HTTP 状态和页面状态，才能继续确认用户环境中的具体生成错误类别。

## 6. 第二轮复审与收口结果

第二轮复审针对“响应丢失后是否知道服务端究竟做没做”以及“生成是否拿到完整快照”补了真实
SessionStore/预览缓存/历史参与的回归。提交回执只记录最近 64 个 operation id，作为现有
提交边界的确认元数据，不是第二套作品状态。

### 本轮确定性回归

后端命令：

```text
python3 -m pytest tests/test_color_replace_unit.py tests/test_converter_replace_integration_unit.py tests/test_replace_colors_batch_unit.py tests/test_editor_commit_unit.py tests/test_converter_generate_unit.py tests/test_converter_puzzle_unit.py tests/test_converter_generate_integration_unit.py tests/test_converter_recipe_override_unit.py -q -W error::pytest.PytestUnraisableExceptionWarning
```

结果：`382 passed, 1 warning`。

前端命令：

```text
python3 scripts/run_vitest.py run src/__tests__/converter-store-selection-race.test.ts
```

结果：`16 passed`。覆盖同色/批量换色后的权威内容版本、成功与错误旧响应的回执查询、选区 hydration
失败时保留 selection revision、同类内容编辑串行、已知提交前失败可继续以及 unknown
receipt 暂停依赖操作并由显式同步恢复。

最终受影响文件命令：

```text
python3 scripts/run_vitest.py run src/__tests__/converter-store-selection-race.test.ts src/__tests__/converter-store-relief-generate.test.ts src/__tests__/autoPreview.test.ts src/__tests__/converter-store-layer-images-invalidate.test.ts src/__tests__/color2DOverlayAutoPreview.test.ts src/stores/__tests__/converter-native-source.test.ts src/__tests__/converter-store-confirm-replacement-gradient-region.test.ts src/__tests__/converter-store-dynamic-material-transport.test.ts src/__tests__/converter-store-gradient-region-pixel-replace.test.ts src/__tests__/converter-store-replacement-height-identity.test.ts src/__tests__/freeColor.test.ts src/__tests__/gradient-groups-panel.test.tsx src/__tests__/gradient-multi-region-merge.test.ts src/__tests__/colorReplaceArchFix.property.test.ts
```

最终受影响文件集合命令覆盖颜色调整、选区竞态、自动预览、生成、配方、自由色、渐变和
旧请求属性测试，结果为 `14 files passed, 274 tests passed`。这些测试使用受控 Promise/
事件闩锁，不依赖随机 sleep。

后端生成新增覆盖标准、拼图、大画幅共用的编辑/选区双版本校验，以及 worker 开始后修改
SessionStore 时仍只消费不可变快照。后端真实 endpoint 回归另执行了 50 次连续内容编辑，
revision 单调递增且非选中区域材料矩阵保持一致。

复审补丁回归：`tests/test_editor_commit_unit.py` 验证已完成 operation id 的重复提交在
实际编辑前被拒绝；`tests/test_converter_recipe_override_unit.py` 注入 cache 已发布后
历史失败，确认新 cache/配方保持、旧 session 不回滚且回执不伪报 failed。两项均通过。

### 当前验证命令状态

```text
cd frontend && pnpm build
```

通过；TypeScript 与 Vite 构建无错误，保留仓库原有 dynamic import/大 chunk warning。

```text
cd frontend && pnpm lint
```

通过，0 errors、68 warnings；warning 是仓库既有风格/React Fast Refresh/raw color 问题。

```text
python3 -m compileall -q api core tests
git diff --check
```

通过（最终代码变更后已复跑）。

```text
python3 -m pytest tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v
python3 scripts/log_quality_check.py --mode fast
```

通过：日志治理单测 `21 passed`，fast quality gate `PASS`；没有新增非结构化日志、超预算
INFO 或缺少可操作字段的 WARNING/ERROR。

```text
python3 scripts/run_vitest.py run
```

未全绿：当前已知唯一失败仍是与本次状态边界无关的
`src/stores/__tests__/batchStore.test.ts` 参数快照断言；实现新增
`coating_height_mm`、`enable_coating` 和 `svg_hole_*` 参数，而本次未修改该既有契约。
全量结果为 `272 files passed, 3016 tests passed, 1 skipped, 1 failed`；受影响的颜色调整/
生成测试均通过，不能把这项不相关 fixture 失败改写成全量通过。

```text
python3 -m pytest tests/ -v
```

收集阶段受环境可选依赖阻断：直接执行该命令得到 `3 deselected, 2 errors`，缺少
`rasterio`（`tests/test_glb_v2_kernel_unit.py`）和 `lumina_svg_core`
（`tests/test_native_svg_benchmark_contract_unit.py`）。这不是本次修改触碰的模块；可运行的
converter/generate/puzzle 集合已单独通过。未执行无上限大内存压测。

### 仍需现场确认的风险

没有用户现场 request id、服务端堆栈、页面录屏或真实素材，因此不能宣称“多位用户最后生成
错误”已经全部归因或解决。当前本地已确认：真实过期生成会明确拒绝；GLB 派生失败不会撤销
已提交二维内容；未知提交回执会暂停后续依赖操作。若现场仍有生成失败，应按操作回执、编辑
版本、选区版本、矩阵一致性和 GLB 派生阶段分别采集证据。

## 7. PR607 F1/F2 第二轮收口（2026-09-20）

本轮严格限定为《PR607_限定两项修复Prompt.md》中的 F1（编辑提交回执对账）和 F2（预览缓存提交边界）。没有新增旁路编辑状态、第二套历史/mask、数据库或全局锁。

### F1：回执现在恢复业务状态，而不只恢复版本号

先用受控 Promise 让编辑 HTTP 响应丢失，再单独返回查询回执，旧实现的失败现象为：

- clear 进入 `unknown` 后，服务端确认 `failed` 时前端仍停留在乐观清空状态；
- 配方 HTTP 响应丢失但回执为 `committed` 时，前端只更新版本/选区，配方和预览仍是旧状态；
- undo 响应丢失并被确认提交后，立即生成仍带着旧的 `replacement_regions`、`recipe_overrides` 和 `free_color_set`；
- 延迟确认的配方失败会留下本次乐观追加的 adjustment history。

新实现让服务端在已有 operation receipt 中返回有界的业务投影；前端先应用该投影，再完成版本、选区和 barrier 收敛。已确认失败时使用原有操作的 rollback snapshot 恢复前一份已提交状态；未知结果继续暂停，不重放 toggle/undo/redo。新受控测试覆盖上述四条路径。

### F2：缓存发布后不再回滚已发布数组

在真实 `/replace-color` endpoint、真实 SessionStore 和内存预览缓存中，注入“`cache.commit()` 后、receipt publish 调用返回后抛出 HTTP 422”的故障：旧实现会把 RGB/材料矩阵恢复为旧快照，但 session/history/内容版本已经前进，形成混合状态。新实现保留已发布的蓝色 RGB、更新后的材料矩阵、replacement record、内容版本和 committed receipt。

同一故障也覆盖 artifact-backed cache：外部化后的 artifact 仍保留已发布 RGB，未恢复旧文件。共用 `_preview_cache_transaction` 依据事务 `published` 标记只在提交前恢复工作副本；recipe 专用的 `close_cache_context_as_published` 绕过和重复的 selection 构造已删除。既有 GLB 调度失败测试继续确认派生工件失败不会撤销二维编辑。

### 本轮新鲜验证

```text
python3 -m pytest tests/test_editor_commit_unit.py tests/test_converter_replace_integration_unit.py tests/test_converter_recipe_override_unit.py tests/test_preview_cache_artifacts_unit.py tests/test_converter_replace_layer_sync_unit.py -q
```

结果：`122 passed, 1 warning`。warning 是既有 Starlette/httpx deprecation；F1 receipt、F2 内存/ artifact 提交边界和受影响替色/配方回归均通过。

```text
python3 scripts/run_vitest.py run src/__tests__/converter-store-commit-reconciliation.test.ts src/__tests__/converter-store-selection-race.test.ts src/__tests__/converter-store-layer-images-invalidate.test.ts
```

结果：`3 files passed, 25 tests passed`。

```text
cd frontend && pnpm build
```

结果：通过（TypeScript + Vite build）。保留既有 dynamic-import 和大 chunk warning。

```text
cd frontend && pnpm lint
```

结果：通过，`0 errors, 68 warnings`；warning 为仓库既有 Fast Refresh、raw color、React hooks 和硬编码文本规则提示。

```text
git diff --check
```

结果：通过。

全量前后端测试仍按前一节记录的环境限制处理：前端有一个与本轮无关的 batch 参数快照失败；后端全量收集受 `rasterio`、`lumina_svg_core` 可选依赖阻断。没有用户现场 request ID/堆栈/真实素材，因此本轮不把未知的生产生成错误宣称为已全部归因。
