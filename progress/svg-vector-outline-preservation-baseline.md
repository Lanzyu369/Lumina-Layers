# SVG / Vector 描边支持 — Task 2.5 预防性基线汇总

- **Spec**: `.kiro/specs/svg-vector-outline-support/`
- **Task**: `2.5 汇总运行`（Wave 3，Task 2 的尾节点）
- **目的**: bug-condition methodology 下，在写修复代码（Task 3）之前固化非
  bug-condition 输入的现状，确认 spec 范围内不存在第三类 bug。
- **执行时间**: 2026-05-28 08:22 CST
- **Git**: `dev-refactor` @ `59f0c57475c4a043d6bdbdbfc878b53069ec01a7`
- **执行者**: spec-task-execution 子代理（仅运行命令，未修改任何源码或测试）

## 命令与日志

| 维度 | 命令（已 verbatim 执行） | 日志 |
| --- | --- | --- |
| 后端 | `.venv/bin/python -m pytest tests/test_raster_outline_preservation_properties.py tests/test_vector_branch_no_outline_preservation_properties.py tests/test_feedback_advanced_params_outline_preservation_properties.py tests/test_puzzle_boundary_pipeline_unit.py tests/test_pipeline_step_modules_unit.py -v --hypothesis-show-statistics` | `progress/svg-vector-outline-preservation-backend.log` |
| 前端 | `.venv/bin/python scripts/run_vitest.py run src/__tests__/recipe-roundtrip.property.test.ts src/__tests__/recipe-roundtrip-vector-outline-preservation.property.test.ts` | `progress/svg-vector-outline-preservation-frontend.log` |

> 前端命令对 `tasks.md` 文本做了两处必要调整，并且与 Task 1.6 的处理方式一致：
> 1. **去掉 `--` 分隔符**，否则 vitest 会忽略后续的文件路径并把它们留给被测进程，
>    导致整套测试套件（含 Task 1 的探索性失败用例）被加载，破坏"基线 PASS"语义。
> 2. **追加 `recipe-roundtrip-vector-outline-preservation.property.test.ts`**：
>    Task 2.4 的产物，归属 preservation 闸门。
>
> 这两点在 task 描述与 orchestrator step plan 中已明确允许；最终运行命令保持了
> `tasks.md` 第 2.5 节列出的全部目标文件，且仅追加。

## 任务 → 测试文件 → 结果映射

### 后端（pytest + Hypothesis）

| Task | 文件 | 用例数 | Hypothesis 反例 | 结果 |
| --- | --- | --- | --- | --- |
| 2.1 | `tests/test_raster_outline_preservation_properties.py` | 6 | 0 | PASS |
| 2.2 | `tests/test_vector_branch_no_outline_preservation_properties.py` | 4 | 0 | PASS |
| 2.3 | `tests/test_feedback_advanced_params_outline_preservation_properties.py` | 6 | 0 | PASS |
| —  | `tests/test_puzzle_boundary_pipeline_unit.py`（既有参考） | 3 | 0 | PASS |
| —  | `tests/test_pipeline_step_modules_unit.py`（既有参考） | 55 | 0 | PASS |
| **合计** | 5 个文件 | **74** | 0 | **74 passed** |

退出码：`0`（pytest）。运行总耗时：~ 2.45 s。

### 前端（Vitest + fast-check）

| Task | 文件 | 用例数 | 结果 |
| --- | --- | --- | --- |
| —  | `frontend/src/__tests__/recipe-roundtrip.property.test.ts`（既有 canonical） | n | PASS |
| 2.4 | `frontend/src/__tests__/recipe-roundtrip-vector-outline-preservation.property.test.ts` | n | PASS |
| **合计** | 2 个文件 | **7** | **7 passed** |

退出码：`0`（vitest 进程，run_vitest.py wrapper 透传）。运行总耗时：878 ms。

## Hypothesis 统计要点

`--hypothesis-show-statistics` 显示的 PBT 用例数（每条均"100% 通过 / 0% 无效"）：

- `test_raster_outline_structural_invariants`：100 examples
- `test_raster_outline_canonical_pixel_8color_fingerprint_stable`：20 examples
- `test_vector_no_outline_preserves_baseline`：100 examples
- `test_sanitizer_preserves_outline_for_non_vector_modes`：50 examples
- `test_sanitizer_preserves_outline_for_vector_without_outline_intent`：50 examples
- `test_round_trip_non_vector_outline_preservation`：50 examples
- `test_round_trip_vector_without_outline_preservation`：50 examples

**Hypothesis 用例累计**：约 **420 examples** 全部通过，无 shrunken counterexample。

各 PBT 的 `Typical runtimes`：< 1 ms 至 ~ 4 ms，没有性能衰退迹象，也没有 invalid
（`assume()` 拒绝率 = 0%）样本。

## 结论

- **NO third-class bug detected.** 所有 preservation gate 在当前 main 上 PASS：
  - Raster / High-Fidelity outline 路径（pixel + hifi 两种 modeling_mode、
    outline 开/关、3 种 color_mode）保持字节级稳定；指纹锚点匹配 baseline。
  - Vector + `enable_outline=false` 分支的 mesh 命名集合、几何体属性、
    `bambu_*` ctx、preview/slot 信息全部等价。
  - Bug-report `advanced_params.outline` 在非 bug-condition 工单下 round-trip
    透传，`feedback_*` 结构化事件 schema 不变。
  - Frontend recipe round-trip（含 vector + outline=false 新分支）byte-equal。
- spec 范围之外**无未发现的 regression**，可继续推进 Task 3（实施修复）。
- 与 Task 1.6 的反例归档（`progress/svg-vector-outline-counterexamples-*.log`）
  一同构成完整的 before-fix 证据：
  - Task 1 的 5 个 exploration 反例 → 证明 bug 真实存在；
  - Task 2 的 74 后端 + 7 前端 baseline → 证明 spec 范围足够窄、未漏 bug。

## 下一步（不在 2.5 范围内）

进入 Wave 4：Task 3.1–3.4 并行实施修复。Task 3.6 / 3.7 完成后，本汇总命令将
被原样重跑作为回归闸门。
