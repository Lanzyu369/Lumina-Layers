# SVG / Vector 描边支持 — Task 3.7 修复后回归汇总

- **Scope**: SVG vector outline support preservation regression after fix
- **Task**: `3.7 Verify preservation tests still pass`（Wave 6，Task 3 验证子任务）
- **目的**: bug-condition methodology 下，确认 Task 3.1–3.5 的修复落地后，
  Task 2 写下的所有非 bug-condition 输入的 preservation gate 仍然 PASS，即
  没有引入针对保留域（raster outline、vector + `enable_outline=false` 分支、
  bug-report `advanced_params.outline` 非 bug-condition round-trip、
  frontend recipe round-trip 含 vector + outline=false 分支）的回归。
- **执行时间**: 2026-05-28 08:58 CST
- **Git**: `dev-refactor` @ `59f0c57475c4a043d6bdbdbfc878b53069ec01a7`
- **工作树状态（dirty）**: Task 3.1–3.5 修复尚未提交（同 baseline 时点状态），
  3.7 仅运行命令，未触动任何源码或测试文件
- **执行者**: spec-task-execution 子代理（仅运行命令）

## 命令与日志

| 维度 | 命令（与 Task 2.5 / baseline 完全一致） | 日志 |
| --- | --- | --- |
| 后端 | `.venv/bin/python -m pytest tests/test_raster_outline_preservation_properties.py tests/test_vector_branch_no_outline_preservation_properties.py tests/test_feedback_advanced_params_outline_preservation_properties.py tests/test_puzzle_boundary_pipeline_unit.py tests/test_pipeline_step_modules_unit.py -v --hypothesis-show-statistics` | `progress/svg-vector-outline-preservation-after-fix-backend.log` |
| 前端 | `.venv/bin/python scripts/run_vitest.py run src/__tests__/recipe-roundtrip.property.test.ts src/__tests__/recipe-roundtrip-vector-outline-preservation.property.test.ts` | `progress/svg-vector-outline-preservation-after-fix-frontend.log` |

> 前端命令对 Task 2.5/3.7 文本所做的两处必要调整（去掉 `--` 分隔符、
> 追加 `recipe-roundtrip-vector-outline-preservation.property.test.ts`）保持
> 与 Task 2.5 baseline 完全一致，便于直接对比。

## 任务 → 测试文件 → 结果映射

### 后端（pytest + Hypothesis）

| Task | 文件 | 用例数 | Hypothesis 反例 | 结果 | vs baseline |
| --- | --- | --- | --- | --- | --- |
| 2.1 | `tests/test_raster_outline_preservation_properties.py` | 6 | 0 | PASS | 同 baseline ✅ |
| 2.2 | `tests/test_vector_branch_no_outline_preservation_properties.py` | 4 | 0 | PASS | 同 baseline ✅ |
| 2.3 | `tests/test_feedback_advanced_params_outline_preservation_properties.py` | 6 | 0 | PASS | 同 baseline ✅ |
| —  | `tests/test_puzzle_boundary_pipeline_unit.py`（既有参考） | 3 | 0 | PASS | 同 baseline ✅ |
| —  | `tests/test_pipeline_step_modules_unit.py`（既有参考） | 55 | 0 | PASS | 同 baseline ✅ |
| **合计** | 5 个文件 | **74** | 0 | **74 passed** | **零退化** |

退出码：`0`（pytest）。运行总耗时：~ 6.66 s（baseline ~ 2.45 s；
波动来自 Hypothesis profile + 已加载 fixture 的随机性，远低于性能闸门阈值）。

### 前端（Vitest + fast-check）

| Task | 文件 | 用例数 | 结果 | vs baseline |
| --- | --- | --- | --- | --- |
| —  | `frontend/src/__tests__/recipe-roundtrip.property.test.ts`（既有 canonical） | 6 | PASS | 同 baseline ✅ |
| 2.4 | `frontend/src/__tests__/recipe-roundtrip-vector-outline-preservation.property.test.ts` | 1 | PASS | 同 baseline ✅ |
| **合计** | 2 个文件 | **7** | **7 passed** | **零退化** |

退出码：`0`（vitest 进程，run_vitest.py wrapper 透传）。运行总耗时：764 ms
（baseline 878 ms）。

## Hypothesis 统计要点

`--hypothesis-show-statistics` 显示的 PBT 用例数（每条均"100% 通过 / 0% 无效"）：

- `test_raster_outline_structural_invariants`：100 examples（同 baseline）
- `test_raster_outline_canonical_pixel_8color_fingerprint_stable`：20 examples
- `test_vector_no_outline_preserves_baseline`：100 examples
- `test_sanitizer_preserves_outline_for_non_vector_modes`：50 examples
- `test_sanitizer_preserves_outline_for_vector_without_outline_intent`：50 examples
- `test_round_trip_non_vector_outline_preservation`：50 examples
- `test_round_trip_vector_without_outline_preservation`：50 examples

**Hypothesis 用例累计**：约 **420 examples** 全部通过，无 shrunken counterexample。
与 baseline 的 examples 总数完全一致，未触发 fallback 收缩 / 无效率上升。
各 PBT `Typical runtimes` 仍在 < 1 ms 至 ~ 20 ms 区间，无性能衰退。

## 结论

- **NO regression introduced.** Task 3.1–3.5 的修复在以下保留域上保持 byte-/
  structural-/schema-equal：
  - Raster / High-Fidelity outline 路径（pixel + hifi 两种 modeling_mode、
    outline 开 / 关、3 种 color_mode）的指纹与 baseline 完全相同。
  - Vector + `enable_outline=false` 分支的 mesh 命名集合、几何属性、
    `bambu_*` ctx 字段、preview / slot 信息全部等价。
  - Bug-report `advanced_params.outline` 在非 bug-condition（非 vector，
    或 vector + outline=false）工单下 round-trip 透传，
    `feedback_*` 结构化事件 schema 不变。
  - Frontend recipe round-trip（含 vector + outline=false 新分支）
    byte-equal。
- **2.1 ✅, 2.2 ✅, 2.3 ✅, 2.4 ✅**：全部保留闸门通过。
- 满足 Task 3.7 的 EXPECTED OUTCOME（"Task 2 全部 PASS（无 regression）"）。
- 与 Task 3.6 的 expected-behavior 验证一并构成完整的 after-fix 证据链。

## 与 baseline 的对照

| 维度 | baseline (Task 2.5) | after-fix (Task 3.7) | 差异 |
| --- | --- | --- | --- |
| 后端 exit code | 0 | 0 | 一致 |
| 后端 passed | 74 | 74 | 一致 |
| 后端 Hypothesis examples | ~420 | ~420 | 一致 |
| 前端 exit code | 0 | 0 | 一致 |
| 前端 passed | 7 | 7 | 一致 |
| 反例（counterexamples） | 0 | 0 | 一致 |

## 下一步（不在 3.7 范围内）

Wave 6 的 Task 3.6（exploration tests by FAIL→PASS 转换）+ 3.7（preservation
零退化）双双完成后，进入 Wave 7：Task 4 Acceptance script & governance gates
（含 `log_quality_check.py` fast/full、bug-report 抽样、3MF 抽样等）。
