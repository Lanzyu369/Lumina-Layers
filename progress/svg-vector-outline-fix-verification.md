# SVG / Vector 描边支持 — Task 3.6 修复验证归档

> Spec: `.kiro/specs/svg-vector-outline-support/`
> 工单: **LUM-20260527-001** ("svg 加不了描边")
> Bugfix workflow Task 3.6（exploration 测试由 FAIL 转 PASS 验证）产出物
> 关联文档:
> - [`tasks.md`](../.kiro/specs/svg-vector-outline-support/tasks.md) §Tasks 3.1–3.6
> - 反例基线: [`svg-vector-outline-counterexamples.md`](./svg-vector-outline-counterexamples.md)
> - Preservation 基线: [`svg-vector-outline-preservation-baseline.md`](./svg-vector-outline-preservation-baseline.md)
> - 修复改动 (Task 3.1–3.5):
>   - `frontend/src/components/sections/OutlineSettings.tsx` (3.1)
>   - `frontend/src/i18n/translations.ts` (3.1)
>   - `api/workers/converter_workers.py` (3.2)
>   - `core/pipeline/vector_branch.py` (3.3)
>   - `tests/test_logging_exception_governance_unit.py` (3.2/3.3 governance whitelist)
>   - `frontend/src/data/announcements.ts` (3.5)
>   - Task 3.4 审计后无需改动

## 摘要 / Summary

按 bugfix workflow Task 3.6 的预期：Task 1 中 4 个 exploration 测试（1.1 / 1.3 / 1.4 / 1.5）
在 Task 3 修复前 **必须 FAIL**；修复后 **必须由 FAIL 翻转为 PASS**；1.2 是请求层 anchor，
修复前后均 **必须 PASS**（防止请求层回潮）。本次重跑结果与预期 **完全一致**：

| Task | 文件 | 框架 | 修复前结果 | 修复后结果 | 翻转 |
|---|---|---|---|---|---|
| 1.1 | `frontend/src/__tests__/outline-settings-vector.property.test.tsx` | Vitest + fast-check + RTL | FAIL | **PASS** (3/3) | FAIL → PASS ✅ |
| 1.2 | `frontend/src/__tests__/converter-vector-outline-payload.property.test.ts` | Vitest + fast-check | PASS | **PASS** (3/3) | 保持 PASS ✅ |
| 1.3 | `tests/test_vector_outline_pipeline_properties.py::test_vector_generate_includes_outline_geometry[_anchor]` | pytest + Hypothesis | FAIL | **PASS** (PBT 200 例 + anchor) | FAIL → PASS ✅ |
| 1.4 | `tests/test_vector_outline_pipeline_properties.py::test_vector_preview_generate_outline_parity[_anchor]` | pytest + Hypothesis | FAIL | **PASS** (PBT 200 例 + anchor) | FAIL → PASS ✅ |
| 1.5 | `frontend/src/__tests__/feedback-advanced-params-vector-outline.property.test.tsx` | Vitest + fast-check + RTL | FAIL | **PASS** (3/3) | FAIL → PASS ✅ |

四个 bug-condition 反例（1.1 / 1.3 / 1.4 / 1.5）全部翻转为 PASS，anchor (1.2) 保持 PASS，
**Property 1（Expected Behavior — SVG/Vector Outline Must Render）满足**。

## 运行命令、退出码与输出

### 前端

命令（与 Task 1.6 一致；`run_vitest.py` 不需要 `--` 分隔符，传后会被当成额外脚本参数）：

```
.venv/bin/python scripts/run_vitest.py run \
  src/__tests__/outline-settings-vector.property.test.tsx \
  src/__tests__/converter-vector-outline-payload.property.test.ts \
  src/__tests__/feedback-advanced-params-vector-outline.property.test.tsx
```

| 阶段 | 退出码 | Test Files | Tests | Duration |
|---|---|---|---|---|
| 修复前 (Task 1.6) | **1** | 2 failed (1.1 + 1.5) / 1 passed (1.2) | 5 failed / 4 passed | 26.12s |
| 修复后 (Task 3.6, 本次) | **0** | **3 passed (3)** | **9 passed (9)** | 1.09s |

> 备注：首次本次运行使用了 `python scripts/run_vitest.py run -- <files>`，wrapper 把
> `--` 视为参数分隔后将其透传给 vitest，结果触发了对 **整个仓库** test 的运行
> （Test Files 203 passed / Tests 1629 passed | 1 skipped），同样 exit 0；为得到
> 干净的"仅三个目标 spec"输出，去掉 `--` 后结果为 3 files / 9 tests / Duration 1.09s。
> 两次运行均无失败用例。

#### 三个 spec 文件的逐项 PASS 计数（修复后）

- `outline-settings-vector.property.test.tsx`: **3/3 PASS**（fast-check `outline_width ∈ [0.5, 10]` 100 个用例 + 工单 LUM-20260527-001 anchor + i18n tooltip 校验）
- `converter-vector-outline-payload.property.test.ts`: **3/3 PASS**（generate / preview payload 透传 anchor 维持）
- `feedback-advanced-params-vector-outline.property.test.tsx`: **3/3 PASS**（fireEvent.click → store.enable_outline === true → buildAdvancedParams.outline.enable_outline === true 链路打通）

### 后端

命令（与 Task 1.6 一致）：

```
.venv/bin/python -m pytest \
  tests/test_vector_outline_pipeline_properties.py \
  -v --hypothesis-show-statistics
```

| 阶段 | 退出码 | Tests | Hypothesis 通过例数 |
|---|---|---|---|
| 修复前 (Task 1.6) | **1** | 2 failed (1.3 + 1.4) | shrunk counterexample 已归档 |
| 修复后 (Task 3.6, 本次) | **0** | **4 passed (4)** | **400 passing examples (200 + 200)** + 2 anchors |

#### Hypothesis Statistics（修复后）

```
test_vector_generate_includes_outline_geometry:
  - during generate phase (2.68s):
    - Typical runtimes: ~ 9-17 ms, of which < 1ms in data generation
    - 200 passing examples, 0 failing examples, 0 invalid examples
  - Stopped because settings.max_examples=200

test_vector_preview_generate_outline_parity:
  - during generate phase (1.95s):
    - Typical runtimes: ~ 8-11 ms, of which < 1ms in data generation
    - 200 passing examples, 0 failing examples, 0 invalid examples
  - Stopped because settings.max_examples=200
```

合计 **400 passing Hypothesis examples + 2 fixed anchors = 402 个用例全部 PASS**，覆盖
`(modeling_mode=vector, enable_outline=true, outline_width ∈ [0.5, 10.0],
color_mode ∈ {BW, 4-Color RYBW, 8-Color Max}, base_channel_idx ∈ {0, 非 0})` 输入域。

## Property 1 子句翻转确认

| 子句 (`design.md` Correctness Properties — Property 1) | 翻转 |
|---|---|
| UI: vector + outline 在前端可启用、`OutlineSettings` 不再 disabled | 1.1 ✅ |
| 请求层: store 组装的 generate / preview body 保留 `enable_outline` / `outline_width` | 1.2 ✅ (anchor 维持) |
| 几何层 (generate): vector 分支输出 `Outline` mesh 与 `bambu_material_name` | 1.3 ✅ |
| 几何层 (preview ↔ generate parity): preview 与 generate 的 outline 出现状态一致 | 1.4 ✅ |
| Bug-report 复现: `AdvancedParams.outline` 在 vector + outline 启用时忠实记录用户意图 | 1.5 ✅ |

## 范围与变动审计

本次 Task 3.6 是**纯验证**任务：

- 未修改任何 `frontend/`, `core/`, `api/`, `tests/` 源码或测试。
- 仅在 `progress/` 下新增本归档（**本文件**）。
- `git status --short` 中其他 `M` / `??` 条目均来自 Task 1 / Task 2 / Task 3.1–3.5 的
  既有改动（OutlineSettings.tsx / translations.ts / converter_workers.py /
  vector_branch.py / announcements.ts / governance whitelist），与本任务无关。

## 结论

- 前端 exit code: **0**（修复前 1 → 修复后 0）；目标三个 spec 文件 9/9 PASS。
- 后端 exit code: **0**（修复前 1 → 修复后 0）；4/4 测试 PASS，Hypothesis 共 400 例通过。
- 翻转确认: **1.1 ✅ / 1.2 ✅ / 1.3 ✅ / 1.4 ✅ / 1.5 ✅**。
- Property 1 (Expected Behavior — SVG/Vector Outline Must Render) **整体满足**。

下一步：进入 Task 3.7（重跑 Task 2 preservation 测试，确认无回归）。
