# SVG / Vector 描边支持 — Task 1 反例归档

> 工单: **LUM-20260527-001** ("svg 加不了描边")
> Bugfix workflow Task 1.6（汇总运行）产出物
> 归档范围: SVG vector outline support 的 Task 1.1–1.5 反例与 anchor。
> 后续验证: [`svg-vector-outline-fix-verification.md`](./svg-vector-outline-fix-verification.md)
> 和 [`svg-vector-outline-acceptance-checkpoint.md`](./svg-vector-outline-acceptance-checkpoint.md)

## 摘要 / Summary

按 bug-condition methodology，Task 1 的 4 个 exploration 测试 **必须** 在当前 main
上失败（失败 = 反例已捕获，bug 客观存在）；Task 1.2（请求层 anchor）**必须** PASS
（PASS = 请求层无回潮，可作为防回归 anchor）。本次汇总运行的结果与该规约 **完全一致**：

| Task | 文件 | 框架 | 当前 main 期望 | 实际结果 |
|---|---|---|---|---|
| 1.1 | `frontend/src/__tests__/outline-settings-vector.property.test.tsx` | Vitest + fast-check + RTL | FAIL | **FAIL** (3 中 2 失败，1 sanity PASS) |
| 1.2 | `frontend/src/__tests__/converter-vector-outline-payload.property.test.ts` | Vitest + fast-check | PASS | **PASS** (3/3) — anchor 成立 |
| 1.3 | `tests/test_vector_outline_pipeline_properties.py::test_vector_generate_includes_outline_geometry[(_anchor)]` | pytest + Hypothesis | FAIL | **FAIL** (PBT + anchor 各 1 例) |
| 1.4 | `tests/test_vector_outline_pipeline_properties.py::test_vector_preview_generate_outline_parity[(_anchor)]` | pytest + Hypothesis | FAIL | **FAIL** (PBT + anchor 各 1 例) |
| 1.5 | `frontend/src/__tests__/feedback-advanced-params-vector-outline.property.test.tsx` | Vitest + fast-check + RTL | FAIL | **FAIL** (3/3 全失败) |

> **重点说明**：1.2 PASS **不是** counterexample —— 它是 anchor，证明 store
> `submitGenerate` 已经把 `enable_outline=true` / `outline_width=*` 透传给 generate
> body（参见 `frontend/src/stores/converter/store.ts` 的 `submitGenerate` 第
> 5586/5587 行）。换言之 bug **不在** 请求层；后续 Task 3 的 fix 不应改 store。

## 运行命令与输出

* 前端：`python scripts/run_vitest.py run -- src/__tests__/outline-settings-vector.property.test.tsx src/__tests__/converter-vector-outline-payload.property.test.ts src/__tests__/feedback-advanced-params-vector-outline.property.test.tsx`
  * Wrapper: `.venv/bin/python scripts/run_vitest.py run …`（仓库无系统 `python`，仅
    venv 提供 `python3.12`）
  * Exit code: **1**（预期 — 失败用例是 bug 反例）
  * Test Files: 2 failed (1.1 + 1.5) | 200 passed（含 1.2）
  * Tests: 5 failed | 1622 passed | 1 skipped (1628)
  * Duration: 26.12s
  * 完整日志: [`progress/svg-vector-outline-counterexamples-frontend.log`](./svg-vector-outline-counterexamples-frontend.log)
* 后端：`python -m pytest tests/test_vector_outline_pipeline_properties.py -v --hypothesis-show-statistics`
  * Wrapper: `.venv/bin/python -m pytest …`（同上原因）
  * Exit code: **1**（预期 — 4 例全是 bug 反例）
  * 4 failed in 0.99s
  * Hypothesis 统计：两个 PBT 测试都在 **reuse phase** 即落到 falsifying example
    （shrunken 后单跑），未进入 generate phase；意味着 `.hypothesis/examples/` 中
    已经有此前运行收敛过的最小反例直接复用。
  * 完整日志: [`progress/svg-vector-outline-counterexamples-backend.log`](./svg-vector-outline-counterexamples-backend.log)

## 各任务反例 ／ Counterexample per task

### Task 1.1 — `OutlineSettings` 在 vector 模式下不再 disabled
* 文件: `frontend/src/__tests__/outline-settings-vector.property.test.tsx`
* design.md 行号映射: **E1**（"checkbox 可勾" 但当前 main `disabled`）
* 失败用例 1：`OutlineSettings — vector outline exploration (Task 1.1) > vector mode allows the user to toggle enable_outline (currently fails on main)`
  * fast-check shrunken counterexample: **`[false, 0.5]`**
    （即 `enable_outline=false`、`outline_width=0.5`，shrunken 1 次；seed `840770981`）
  * 触发的断言: `expect(checkbox.disabled).toBe(false)`
    ⇒ Expected `false`, Received `true`
  * 根因映射: 设计文档 "Hypothesized Root Cause" 第 1 条 — `OutlineSettings.tsx:24` 的 `disabled={isVector}` 静默拦截
* 失败用例 2 (anchor)：`LUM-20260527-001 anchor: vector + outline_width=2.0 must be toggleable`
  * 输入（确定性，非 PBT）：`modeling_mode=ModelingMode.VECTOR`, `outline_width=2.0`
  * 触发的断言: `expect(checkbox.disabled).toBe(false)` ⇒ Expected `false`, Received `true`
* sanity 用例（PASS，记录在档不计入反例）：`OutlineSettings — vector outline exploration (Task 1.1) > non-vector modes never disable the outline checkbox`
  * 该用例验证 RASTER / HIGH_FIDELITY / RELIEF 等非 vector 模式 checkbox 一直可点 —
    在当前 main 上 PASS 是预期的（preservation hint）

### Task 1.2 — Frontend store 组装的 generate / preview payload (anchor)
* 文件: `frontend/src/__tests__/converter-vector-outline-payload.property.test.ts`
* design.md 行号映射: **E2 的请求层前置条件**（不是反例 — 是请求层不丢失意图的证据）
* 全部 3 个用例 PASS（独立运行验证：`python scripts/run_vitest.py run src/__tests__/converter-vector-outline-payload.property.test.ts` ⇒ `Test Files 1 passed (1) / Tests 3 passed (3)`）
  * `forwards enable_outline=true and outline_width across [0.5, 10.0]`（fast-check, 100 runs）
  * `LUM-20260527-001 anchor: outline_width=2.0 vector + 8-Color Max`
  * `preview anchor: store reads modeling_mode=VECTOR + enable_outline=true`
* **意义**：store `submitGenerate` 把 `enable_outline=true` 与精确的 `outline_width`
  写入 generate body；preview schema 本身不含 outline 字段 (`ConvertPreviewRequest` 无
  `enable_outline` / `outline_width`)，因此 preview anchor 落在 store 状态层。
  两端均与用户意图一致 → **请求层不是 bug 来源**。

### Task 1.3 — Backend vector 分支生成 `Outline` 几何
* 文件: `tests/test_vector_outline_pipeline_properties.py`
* design.md 行号映射: **E2**（3MF 不含 `Outline` 节点）+ **E5**（边界宽度也缺）
* 失败用例 1（PBT）：`test_vector_generate_includes_outline_geometry`
  * Hypothesis falsifying example: **`outline_width=1.0, color_mode='BW', base_channel_idx=0`**
  * 触发的断言: `assert "Outline" in exported_scene.geometry`
    ⇒ `'Outline' not in OrderedDict({'White': …, 'Red': …, 'Blue': …})`
    实际几何节点集为 `['Blue', 'Red', 'White']`，`Outline` **缺失**
  * 根因映射: 设计文档 "Hypothesized Root Cause" 第 2 条 — `_run_vector_branch` 跳过 S08 outline 注入
* 失败用例 2（anchor）：`test_vector_generate_includes_outline_geometry_anchor`
  * 输入：`outline_width=2.0, color_mode='8-Color Max', base_channel_idx=0`（工单 LUM-20260527-001 最小复现）
  * 触发的断言（同上）⇒ 几何节点 `['Blue', 'Red', 'White']`，`Outline` 缺失

### Task 1.4 — Backend preview ↔ generate outline 一致性
* 文件: `tests/test_vector_outline_pipeline_properties.py`
* design.md 行号映射: **E3**（preview GLB / 2D 也无 outline）
* 失败用例 1（PBT）：`test_vector_preview_generate_outline_parity`
  * Hypothesis falsifying example: **`outline_width=1.0, color_mode='BW'`**
  * 触发的断言：先通过 `gen_present == prev_present`（两边都为 `False`，"一致地缺失"），
    再被 `assert gen_present is True` 钉住 ⇒ `False is True` 不成立
  * 注：preview 分支同时报 `KeyError: 'actual_lut_path'`（vector_branch.py:647 / 679），
    是 preview 测试 stub 的副作用，不影响"两端均无 outline"这一结论 — 反例稳定
* 失败用例 2（anchor）：`test_vector_preview_generate_outline_parity_anchor`
  * 输入：`outline_width=2.0, color_mode='8-Color Max'`
  * 同样在 `assert gen_present is True` 失败 ⇒ `generate=False, preview=False`，
    两端一致地不生成 outline，违反 Property 1 的 "must render" 子句

### Task 1.5 — UI 拦截 → buildAdvancedParams 在 vector + outline 上忠实写入
* 文件: `frontend/src/__tests__/feedback-advanced-params-vector-outline.property.test.tsx`
* design.md 行号映射: **E4**（用户意图被 UI 静默丢弃，bug-report 无法忠实复现）
* 失败用例 1（PBT）：`vector mode: clicking checkbox flips store.enable_outline to true (currently fails)`
  * fast-check shrunken counterexample: **`[0.5]`**（`outline_width=0.5`；shrunken 1 次；seed `-850826112`）
  * 触发的断言：`fireEvent.click(checkbox)` 后 `useConverterStore.getState().enable_outline === true`
    ⇒ Expected `true`, Received `false`
  * 根因：UI 层 `disabled={isVector}` 拦截 onChange，store 永远写不到 `true`
* 失败用例 2（PBT）：`vector mode: buildAdvancedParams.outline.enable_outline ends up true (currently fails)`
  * fast-check shrunken counterexample: **`[0.5]`**（同上；seed `-1409981083`）
  * 触发的断言：`buildAdvancedParams(state, "converter", { maxBytes: 8192 }).outline.enable_outline === true`
    ⇒ Expected `true`, Received `false`
  * 这一条直接证明 bug-report 复现链路读到的也是 `false`，Property 1 "bug-report 持久化" 子句不满足
* 失败用例 3（anchor）：`LUM-20260527-001 anchor: vector + outline_width=2.0 ticket 必须写入 enable_outline=true`
  * 输入（确定性，非 PBT）：`modeling_mode=ModelingMode.VECTOR`, `outline_width=2.0`
  * 触发的断言：点击 checkbox 后 `useConverterStore.getState().enable_outline === true`
    ⇒ Expected `true`, Received `false`

## 反例 → design.md "Examples" 表对照

| design.md 行 | 描述（节选） | 由哪个测试 / 反例钉住 |
|---|---|---|
| E1 | vector 模式 checkbox 应可勾，当前 disabled 静默 | 1.1 PBT (`[false, 0.5]`) + 1.1 anchor (`outline_width=2.0`) |
| E2 | vector + outline_width=2.0 ⇒ 3MF 必含 `Outline`，当前不含 | 1.3 anchor (`outline_width=2.0, 8-Color Max`) + 1.3 PBT (`outline_width=1.0, BW`) |
| E3 | preview GLB / 2D 必含 outline，当前同样无 | 1.4 PBT (`outline_width=1.0, BW`) + 1.4 anchor (`outline_width=2.0, 8-Color Max`) |
| E4 | UI 拦截 → store.enable_outline 被静默规整为 false → buildAdvancedParams 读到 false | 1.5 PBT 1 + 1.5 PBT 2 (`[0.5]`) + 1.5 anchor |
| E5 | `outline_width=0.5` 边界值同样无 ring | 1.3 PBT 区间 `[0.5, 10.0]` 覆盖 + 1.5 PBT shrunken 直接落到 `0.5` |

## Hypothesis 统计 / Statistics highlights

```
test_vector_generate_includes_outline_geometry:
  - during reuse phase (0.39 s):
    - Typical runtimes: ~ 391 ms, of which < 1 ms in data generation
    - 0 passing, 1 failing, 0 invalid
    - Found 1 distinct error
  - Stopped because nothing left to do

test_vector_preview_generate_outline_parity:
  - during reuse phase (0.01 s):
    - Typical runtimes: ~ 7 ms, of which < 1 ms in data generation
    - 0 passing, 1 failing, 0 invalid
    - Found 1 distinct error
  - Stopped because nothing left to do
```

> reuse phase 即可 falsify ⇒ `.hypothesis/examples/` 中已经有早期收敛过的最小
> 反例数据库；这正是设计期望的"PBT 反例稳定可重放"，无需重新跑 generate phase。
> 两个 anchor 测试不是 Hypothesis 驱动，因此不出现在统计区，而是各自一条
> 显式 FAILED 行。

## fast-check 反例汇总（前端）

| 测试 | seed | path | shrunken counterexample | shrink 次数 |
|---|---|---|---|---|
| 1.1 PBT | `840770981` | `0:0` | `[false, 0.5]` | 1 |
| 1.5 PBT 1 | `-850826112` | `0:0` | `[0.5]` | 1 |
| 1.5 PBT 2 | `-1409981083` | `0:0` | `[0.5]` | 1 |

## 边界确认

* 未修改任何业务源文件 (`frontend/src/components/**`, `frontend/src/stores/**`,
  `core/**`, `api/**`, `tests/test_*.py` 中本次 spec 范围外的测试)。
* 未修改任务计划、设计说明或需求说明。
* 仅写入 `progress/` 下三个文件：本归档 + 两个原始日志。
* 文档为 UTF-8，无 mojibake；中文 + 英文术语并存，可读。

## 后续 / Next

* Task 2.x：写 preservation property tests，必须在当前 main 上 PASS 才能进入
  Task 3 修复。
* Task 3.x：依据 design.md "Fix Implementation"，分别修
  `OutlineSettings.tsx`（解除 `disabled={isVector}`，按决策矩阵 D1–D8）+
  `core/pipeline/vector_branch.py`（注入 `_generate_vector_outline_mesh`，
  generate / preview 共用 helper）+ 相关 i18n / 日志 / bug-report。
* Task 3.6 验收：Task 1 当前所有 FAIL 必须翻 PASS；1.2 anchor 仍 PASS；
  Task 2 全 PASS。
