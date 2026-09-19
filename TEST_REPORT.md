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

结果：`272 files passed, 3009 tests passed, 1 skipped, 1 failed`。唯一失败是本次不相关的 `batchStore.test.ts` 参数快照断言：实现多传了 `coating_height_mm`、`enable_coating`、`svg_hole_*`；相关 native 生成测试和本次选择/替换测试均通过。未修改该既有 batch 参数契约，因此保留为交付前风险，而不是把它伪装成全量绿。

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
