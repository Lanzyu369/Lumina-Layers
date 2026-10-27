# Pipeline Refactor Followup — Wake-Up & Intent Guide

Lumina Studio 管线重构 — 二次审视与未来唤醒指南.

> **Status (2026-05-01)**: PR #128 merged Phase 0-3 of the pipeline
> refactor. Phase 4 (consumer-side adoption + new calibration method)
> was **explicitly deferred** at PR #128 time and remains deferred
> today. Phase 0 hygiene + Phase 1 `ColorMode` registry are real
> production deliveries; Phase 2 `CalibrationMethod` Protocol and
> Phase 3 `BoardLayout` IR + `Renderer` Protocol are sketches with one
> lighthouse adopter each, kept alive only to satisfy the "lighthouse
> adoption" rule (`AGENTS.md` L42).
>
> The user's actual orthogonality concern — "any LUT source must work
> with any renderer" — lives one layer downstream of where Phase 0-3
> abstractions sit (calibration board generation), at the
> **user-image-rendering** layer (`core/image_processing.py` for voxel,
> `core/vector_engine.py` for SVG). The right preventive lever there
> is a **schema-contract test at the LUT consumer boundary**, not more
> Protocol abstractions. That contract test ships in this PR (see §6).
>
> **状态**: PR #128 已合入 管线重构 Phase 0-3. Phase 4 (消费侧迁移 + 新
> 校准方法) 在 PR #128 时已 显式延后, 至今仍延后. Phase 0 卫生整理 +
> Phase 1 `ColorMode` 注册表 为 真实生产交付; Phase 2/3 仅为草图, 各
> 配 1 个 灯塔适配器, 仅为 满足 AGENTS.md L42 规则保留.
>
> 用户真正关心的 正交性 ("任何 LUT 来源 应当能 配任何 渲染器") 位于
> Phase 0-3 抽象 下游 一层, 即 用户图像渲染层 (`core/image_processing.py`
> 体素 / `core/vector_engine.py` SVG). 该层 真正 有效的 预防杠杆 是
> LUT 消费者 边界 的 schema 契约 测试, 而非 更多 Protocol 抽象.
> 本 PR 即 落 该 契约 测试 (见 §6).

---

## 1. Why this guide exists

Pipeline refactor PR #128 landed sketches for `CalibrationMethod`,
`BoardLayout`, and `Renderer` abstractions. After it merged, the
project lead re-read the work and asked Cascade to verify whether it
actually achieves the **preventive goal** that triggered the refactor
in the first place — namely:

> "Team adds a new color recipe source (e.g. gradient card), and
> SVG / voxel renderers should both auto-work — no per-cell bespoke
> implementation."

Cascade's audit found two key facts:

1. **Phase 0-3 abstractions target the calibration board pipeline**,
   not the user-image rendering pipeline. `CalibrationMethod.generate(...)`
   produces a printable color-card 3MF. `BoardLayout.voxel_matrix` is
   the calibration board's physical voxel geometry. `VoxelMeshRenderer`
   meshes the calibration board. The user's actual concern lives one
   layer downstream — at the LUT consumer boundary — which Phase 0-3
   never touched.
2. **The right preventive lever for the user's concern is a contract
   test**, not more Protocol abstractions. Protocols are static-typing
   aids; they don't fail in CI when a new method skips an orthogonality
   check. Parametrized tests **do** fail when the parametrize list
   grows without a passing fixture.

This guide is the runbook for any future engineer or AI agent who:

1. Wants to know **what shipped in PR #128** vs what was deferred
2. Needs to decide whether to **restart Phase 4** (default answer:
   no — see §5 wake triggers)
3. Wants to understand **why this followup PR ships a contract test
   instead of more Protocol abstractions** (§3 + §9)
4. Needs to add a **new LUT source or new renderer** and is wondering
   what test to write (§6 — extend the contract test's parametrize
   matrix)

为什么有这份文档: PR #128 之后, 团队 重新审视 是否 真的 实现了 触发本
重构的 预防目标. 答案是 部分 — Phase 1 `ColorMode` 注册表 是 实打实
价值, Phase 2/3 抽象 落在 错的 层 (校准板 而非 用户图像 渲染).
真正 该 加强 的 是 LUT 消费者 边界 的 契约 测试. 本文档 + 配套 测试
即 该 结论 的 落盘.

---

## 2. What was shipped (PR #128 inventory)

| Phase | Delivery | Status |
|---|---|---|
| 0 | Pipeline hygiene (4 sub-PRs A/B/C/D) | ✅ Real delivery — commits `a57cf7f`, `55dca9d`, `a660a71`, `6f354f4`, `93e1bbb` |
| 1 | `ColorMode` registry | ✅ Real delivery — `core/color_modes.py` (commit `79a56f3`); collapsed 6 duplicate dispatch tables into one. **The durable Phase 0-3 value lives here.** |
| 2 | `CalibrationMethod` Protocol | ⚠️ Sketch only — 1 lighthouse adopter (`Smart1296CalibrationMethod` wraps legacy `generate_smart_board`); 6 other `generate_*_board()` functions un-migrated |
| 3 | `BoardLayout` IR + `Renderer` Protocol | ⚠️ Sketch only — 1 lighthouse adopter (`VoxelMeshRenderer`); `SVGRenderer` not built; `BoardLayout.voxel_matrix` field couples IR to voxel renderer (see §9) |
| 4 | Adoption + new calibration method | ❌ Never PR'd — explicit deferral, see `progress/pipeline-refactor-status.md` §"Phase 4" for the 8-item deferral list |

Verification suite from PR #128 (still passing on `dev-refactor`):

```bash
python -m pytest \
  tests/test_color_mode_dispatch_unit.py \
  tests/test_calibration_methods_unit.py \
  tests/test_board_layout_unit.py \
  tests/test_lut_html_unit.py \
  tests/test_processing_ops_imports_unit.py \
  tests/test_input_validation_parity_unit.py \
  tests/test_vector_branch_extraction_unit.py \
  tests/test_lut_merger_properties.py \
  tests/test_backward_compat_properties.py \
  tests/test_coordinator_properties.py -q
```

For the full scope of what shipped vs deferred, read
`progress/pipeline-refactor-status.md` end-to-end. That doc was the
"PR description for human review" of PR #128 and remains the canonical
authority on what landed.

---

## 3. Critical re-evaluation — abstraction layer mismatch

This section is the **new insight** not present in either
`pipeline-refactor-design.md` or `pipeline-refactor-status.md`.

The pipeline has two distinct rendering layers:

```
                   ┌─────────────────────────────────────┐
                   │  CALIBRATION BOARD GENERATION       │
                   │  (printable color cards)            │
   user prints ──▶ │  - core/calibration.py              │ ──▶ 3MF print job
   board, then     │  - core/calibration_methods.py      │
   photographs it  │  - core/board_layout.py (sketch)    │
                   │  - VoxelMeshRenderer (sketch)       │
                   └─────────────────────────────────────┘
                                    │
                                    ▼ (LUT extracted from photo)
                   ┌─────────────────────────────────────┐
                   │  USER IMAGE RENDERING               │
                   │  (any image → 3D model)             │
   user provides ─▶│  - core/extractor.py     (LUT src)  │ ──▶ 3MF / SVG / 3D
   image + LUT,    │  - core/lut_merger.py    (LUT src)  │
   gets 3D model   │  - core/image_processing.py (voxel) │
                   │  - core/vector_engine.py    (SVG)   │
                   └─────────────────────────────────────┘
```

Phase 0-3 abstractions target the **upper** box (calibration board).
The user's actual orthogonality concern — "any LUT source × any
renderer must work" — lives in the **lower** box (user image rendering).

So the merged abstractions:

- ✅ **are valid architecture** for the calibration board side (just
  incomplete because Phase 4 deferral list never landed)
- ❌ **don't prevent the regression class the user worried about** at
  the user-image-rendering layer (a new LUT source could ship without
  any check that both renderers consume it)

The right preventive measure for the lower box is a **contract test
at the LUT consumer boundary**: parametrize across `(LUT source,
renderer)` cells, assert each cell produces a valid output today, so
adding a new source forces the author to extend the parametrize list
and prove orthogonality in CI.

That test ships in `tests/test_lut_pipeline_orthogonality_unit.py`
(see §6).

---

## 4. The orthogonality grid

Today's reality at the user-image-rendering layer:

| | voxel renderer (`core/image_processing.py`) | SVG renderer (`core/vector_engine.py`) |
|---|---|---|
| **photo-5-layer LUT** (`core/extractor.py` Stage A photo path) | ✅ canonical path, always worked | ✅ canonical path, always worked |
| **gradient card LUT** (Stage A gradient path) | ✅ works | ✅ works (recent fix per project lead) |
| **external reverse-inferred LUT** (`.npz` import / `core/lut_merger.py` Merged path) | ✅ works | ✅ works |

All 6 cells pass today. The contract test in §6 pins this.

The **orthogonality lever** that lets all 6 cells share code is the
canonical LUT schema (see §7). Every LUT source produces it; every
renderer accepts it. Adding a new source = produce the schema. Adding
a new renderer = accept the schema. No per-cell code needed.

---

## 5. Phase 4 — what it was supposed to do (and why it stays deferred)

Per `progress/pipeline-refactor-status.md` §"🟡 Phase 4 — Adoption +
new method (NOT in this PR)", Phase 4 was supposed to:

1. Migrate `core/extractor.py::_generate_recipes` to dispatch via
   `mode.recipe_generator` (currently still a per-mode `if/elif`
   cascade).
2. Migrate `core/pipeline/processing_ops/lut_loader.py` to consume
   `ColorMode` instead of branch-keyed string matching.
3. Convert each `generate_*_board()` to a dedicated `CalibrationMethod`
   subclass (currently only Smart1296 has one).
4. Rewrite `_generate_voxel_mesh` call sites to consume `BoardLayout`
   instead of bare voxel arrays.
5. Land the team's **new calibration method** as a `CalibrationMethod`
   subclass (the original trigger of this whole refactor).
6. Delete the `ColorSystem.get()` shim and the legacy dict shape.
7. Delete the transitional re-exports in
   `core/pipeline/pipeline_utils.py` introduced in Phase 0 Sub-PR B.
8. Add the Phase 1 hash-based calibration board parity tests
   (`tests/test_calibration_board_parity_unit.py` per design doc
   §5.3.4) as the safety net that gates Phase 4 mutations.

> **DO NOT RESTART Phase 4 unless one of these wake triggers fires**:
>
> - Team brings a **real new calibration method** that needs to land
>   for production (the original Phase 4 trigger).
> - A **multi-renderer feature** ships (e.g. PNG preview, large-format
>   tiled SVG) that materially benefits from a `BoardLayout` IR and
>   would otherwise duplicate code across renderers.
> - A relevant code audit finds sketches without real callers and chooses
>   to delete them or fold them into existing code.

Without one of these triggers, Phase 4 is over-engineering for current
product needs. The project posture is **desktop-first** (per memory
`d2e13ccb-5834-4484-b84e-e2eda326f083`), and the orthogonality concern
that prompted the refactor is now covered by the §6 contract test
without restarting Phase 4.

不要 重启 Phase 4, 除非 上面 三个 触发 之一 真的 发生. 在 那之前,
Phase 0/1 已落 的 价值 已 充分, Phase 2/3 草图 + §6 契约 测试 已 形成
完整 防回归 防线.

---

## 6. The contract test

`tests/test_lut_pipeline_orthogonality_unit.py` ships in this PR.
It is a parametrized contract test with **3 LUT sources × 2 renderers
= 6 cells**, each asserting:

1. **LUT source contract** — the source produces a canonical-schema
   dict (see §7); the schema validation runs unconditionally for every
   cell.
2. **Renderer contract** — the renderer's public entry point (the
   processor `__init__` that loads the LUT from disk) accepts the
   schema and exposes the canonical fields (`ref_stacks`, `lut_lab`,
   `kdtree`, `layer_count`).
3. **Hot-loop contract** — the renderer's color-matching hot loop
   (`kdtree.query` over CIELAB-converted samples) returns valid
   indices into `ref_stacks`. This is the actual orthogonality lever
   exercised on real data.

The test is a **schema-contract** test, not an end-to-end mesh-build
test. End-to-end tests are brittle (depend on heavy fixtures, fonts,
system libs) and slow. The schema contract is the actual invariant
that keeps the user image rendering pipeline composable, so testing
it directly gives the most preventive value per second of CI time.

Adding a new LUT source or renderer:

1. **New LUT source**: extend `LUT_SOURCES` in
   `tests/test_lut_pipeline_orthogonality_unit.py`, implement
   `_lut_for_<source_name>(tmp_path)`, run the test — every renderer
   cell for the new source must pass before merging.
2. **New renderer**: extend `RENDERERS`, implement
   `_render_<renderer_name>(lut, sample, tmp_path)`, run the test —
   every LUT source × the new renderer must pass before merging.

The parametrize matrix grows lockstep with the orthogonality grid,
so CI will fail if a future PR adds a source/renderer without proving
all cells.

---

## 7. The canonical LUT schema

The implicit contract every LUT source must produce, every LUT consumer
must accept. Defined by
`core/pipeline/processing_ops/lut_loader.py::_finalize_loaded_lut`:

```python
{
    "lut_rgb": np.ndarray,          # shape (N, 3), dtype uint8
    "lut_lab": np.ndarray,          # shape (N, 3), dtype float64 (CIELAB)
    "ref_stacks": np.ndarray,       # shape (N, layer_count), dtype int32
    "kdtree": scipy.spatial.KDTree, # CIELAB-space k-d tree for matching
    "layer_count": int,             # typically 5; 6 for 5-Color Extended
    # Plus predictive-runtime fields populated by _build_predictive_info,
    # which are optional from the renderer's perspective and used only
    # by predictive matching paths.
}
```

A new LUT source must either:

- **Produce this dict shape directly** (recommended for sources that
  bypass the loader pipeline), OR
- **Feed `_finalize_loaded_lut`** with `(lut_rgb, ref_stacks,
  layer_count, metadata, layer_height_mm)` — that helper builds the
  Lab + KDTree fields canonically.

A new renderer must accept this dict shape, typically by depending on
`LuminaImageProcessor` (which calls `load_lut(...)` internally and
exposes the dict's fields as instance attributes).

This schema is **the** orthogonality lever. The §6 contract test
enforces it on both sides.

---

## 8. Operational concerns

- **Test runtime budget**: The §6 contract test targets ≤10s total for
  all 6 cells on commodity dev hardware. Each cell uses a tiny synthetic
  LUT (≤1024 rows) and exercises only the LUT-loader + kdtree-query
  hot loops, not full mesh build.
- **Fixture strategy**: Synthetic LUTs are written to `tmp_path`-scoped
  `.npz` files via `LUTManager.save_npz_with_metadata` so the renderer
  loads via the real `lut_loader.load_lut` Branch 0 (the `.npz`
  pre-stacked path). This proves the schema flows end-to-end through
  the loader without depending on production photo fixtures.
- **No new INFO log emissions**: This PR is test + doc only;
  `scripts/log_quality_check.py --mode fast` budget stays at the
  frozen `14/30 fast` / `29/30 full` / per-endpoint `7/8` ceiling.
- **Not added to `WORKFLOW_ORDER`**: Per the v2 governance frozen
  baseline, `WORKFLOW_ORDER` is reserved for **logging-governance**
  workflow gates. The §6 test is structural / contract, not log-quality;
  it runs via the default `pytest tests/` collection.
- **Not added to `scripts/run_smoke_tests.py` initially**: The default
  `pytest tests/` collection picks it up. Promote to smoke only if it
  proves to catch regressions in real PRs.
- **Lossless refactoring guarantee**: This PR adds **no** code under
  `core/`, `api/`, `frontend/`, or `config.py`. All existing public
  APIs are unchanged. The only files touched are `docs/` and `tests/`.

---

## 9. Design choice FAQ

Recorded so future engineers don't re-litigate.

### 9.1 Why a contract test, not another Protocol class?

Protocols are static-typing aids; `mypy` / `pyright` warn at
edit time but **CI doesn't fail** when a new method skips the
orthogonality check (most of the codebase isn't strictly typed).
Parametrized tests **do** fail when the parametrize list grows without
a passing fixture. For preventive value at the user-image-rendering
layer, **tests > Protocols**.

### 9.2 Why all 6 cells, not just gradient_card × SVG?

Locks in current good behaviour across the entire grid. If
`photo_5layer × voxel` silently breaks during an unrelated refactor,
the test catches it. Single-cell tests miss this.

### 9.3 Why "schema contract", not "end-to-end pipeline"?

End-to-end tests are brittle (depend on heavy fixtures, fonts, system
libs, OpenGL contexts) and slow. Schema-contract tests are fast and
focused on the actual invariant (LUT shape → renderer accepts → hot
loop works). The mesh build / 3MF write steps add many seconds per
cell without testing the orthogonality property — they test trimesh,
not the LUT contract.

### 9.4 Why is `BoardLayout.voxel_matrix` a design concern?

`BoardLayout` was introduced as a "mode-independent IR". But its core
data (`voxel_matrix: (Z, H, W) int`) is voxel-renderer-specific. SVG
renderer would need to derive vector paths from cells, which the voxel
matrix already collapses into volumetric data. A truly orthogonal IR
would carry per-cell logical info (`grid_position`, `material_id`,
`cell_size_mm`) and let each renderer expand cells in its own way.
**This is a Phase 4 fix-up; out of scope for this PR**, captured here
for the future restart.

### 9.5 Why not delete the un-migrated Phase 2/3 sketches now?

Keep shared helpers only while they have real callers. Assess unused code
during a relevant audit; there is no scheduled 30-day cleanup requirement.

### 9.6 Why is gradient_card simulated as a 4-Color RYBW LUT in tests?

The real gradient-card production code path lives behind a Stage A
flow that takes a photographed gradient card and infers a LUT. Driving
that code path inside a unit test would require fixtures (a real
photographed gradient card image + correct corner detection) outside
the scope of an orthogonality contract test. The contract is the LUT
schema, not the production source. The test simulates a 4-Color RYBW
LUT with smaller row count to exercise the same shape under a
different parametrize cell, achieving the same preventive value at
fraction of the runtime cost. The factory's docstring documents this
simplification.

---

## 10. References + AI agent quick exit guide

### 10.1 References

- **PRs**:
  - PR #128 — Pipeline refactor Phase 0-3
  - PR #138 — A4-1 scaffold wake-up doc (template for this followup)
  - PR #139 — `progress/pipeline-refactor-followup-spec.md` (Cascade's
    planning, GPT's drop)
  - PR #140 — A4-2 doc-sync + Postgres telemetry (companion governance
    PR)
- **Source planning docs**:
  - `progress/pipeline-refactor-design.md` — original master plan
    (Phase 0-4 sketches; §1 Mission, §3.3 Target architecture, §4
    Phased plan, §8 Phase 4 sketch)
  - `progress/pipeline-refactor-status.md` — PR #128 work-item ledger
    (canonical "what shipped" reference)
  - `progress/pipeline-refactor-followup-spec.md` — implementation
    spec for THIS PR (the artefact PR #139 landed)
- **Touchstone source modules**:
  - `core/color_modes.py` — Phase 1 registry (the durable Phase 0-3
    value)
  - `core/calibration_methods.py` — Phase 2 sketch +
    `Smart1296CalibrationMethod` lighthouse
  - `core/board_layout.py` — Phase 3 sketch + `VoxelMeshRenderer`
    lighthouse
  - `core/pipeline/processing_ops/lut_loader.py` — `_finalize_loaded_lut`
    defines the canonical LUT schema (§7)
  - `core/extractor.py::_generate_recipes` — LUT recipe producer
    (Phase 4 migration target)
  - `core/image_processing.py::LuminaImageProcessor` — voxel renderer
    LUT consumer
  - `core/vector_engine.py::VectorProcessor` — SVG renderer LUT
    consumer
- **Memory**: `d2e13ccb-5834-4484-b84e-e2eda326f083` — project posture
  is desktop-first; do not pre-emptively start server / large
  refactors without user-visible value
- **Companion guide**: `docs/server-mode-scaffold.md` — A4-1/A4-2/A4-3
  Postgres backend wake-up guide; this followup doc mirrors its
  template structure

### 10.2 AI agent quick exit guide

If you (a future AI agent) are dropped into this guide and asked to
"continue the pipeline refactor", read these steps **in order** before
touching any production code:

1. **Read §3 + §5 as background** — match the work to the current user's
   requested behavior. An old audit schedule does not start a new refactor
   or require a separate confirmation for work already requested.
2. **Run the §6 contract test** — confirm orthogonality still holds on
   current `dev-refactor` HEAD:
   ```bash
   python -m pytest tests/test_lut_pipeline_orthogonality_unit.py -v
   ```
   All 6 cells must pass. If any fails, the failure indicates a
   pre-existing orthogonality regression — fix that **before** any
   Phase 4 work, in a separate PR.
3. **If a wake trigger exists**, read
   `progress/pipeline-refactor-design.md` §8 (Phase 4 sketch) for the
   detailed deferral list. Do not invent new abstractions; the design
   doc already specified them.
4. **Build Phase 4 per the design doc**, gating each step on the §6
   contract test staying green. The §6 test is the safety net that
   makes Phase 4 mutations safe.
5. **Update memory `d2e13ccb-...`** if the project posture has changed
   (e.g. moved from desktop-first to server-first because B2B Elegoo
   deployment landed).

If the current task does not need Phase 4, keep the change focused on the
requested behavior. Unused sketches can be folded or deleted during a relevant
audit without restarting the larger refactor.

如果 你 是 未来 AI agent, 被 要求 "继续 管线 重构": 先 跑 §6 契约 测试
确认 现状, 再 看 §3 + §5 确认 触发 是否 存在; 没 触发 不要 自启 Phase 4.
若 真有 触发, 严 按 design doc §8 落地, 全程 以 §6 测试 为 守护 绿 灯.
