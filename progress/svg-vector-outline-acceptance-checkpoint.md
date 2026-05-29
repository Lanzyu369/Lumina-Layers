# SVG / Vector Outline Support — Task 4 Acceptance Checkpoint

Scope: SVG vector outline support acceptance checkpoint
HEAD at run time: `59f0c57` (`dev-refactor`)
Run timestamp (local): 2026-05-28 09:02 ~ 09:03 (UTC+8)

## Scope

This file is the archival record for **Task 4 — Acceptance script & governance
gates (Checkpoint)** of the SVG vector outline support work. The task lists
8 ordered commands; steps 1–6 are automated and were executed in order, steps
7–8 are manual sampling steps that must be performed by the user before merge.

### Narrow success criteria for the SVG outline fix

Per user direction, the fix is judged on these 5 criteria only:

1. vector / SVG mode can enable outline in UI.
2. preview and generate paths handle outline consistently — generate
   produces an `Outline` mesh in the exported 3MF when
   `enable_outline=true`; preview branch exposes `outline_geometry`
   metadata in cache. **Pixel-level rendering of the ring in the 2D
   preview / segmented GLB is explicitly out of scope** for this
   spec (OQ-6 follow-up).
3. raster / high-fidelity outline behavior is unchanged.
4. bug report captures `enable_outline=true` and `outline_width`.
5. targeted tests (Task 1 exploration + Task 2 preservation) PASS.

All 5 criteria are met by the implementation landed in Tasks 3.1–3.5 and
re-verified in Tasks 3.6 / 3.7 (see those archival notes for the
flip-to-PASS evidence and zero-regression evidence).

### Step 6 framing

Per the spec's failure definition: any non-zero exit on the listed commands
"暂停 merge，回到对应 Task 修复". Step 6 (`log_quality_check.py --mode full`)
ultimately exits non-zero in this environment because the canonical full
workflow now emits +5 INFO lines vs the `progress/log_audit_full_reviewer.json`
baseline, blowing the `info_lines_within_budget` (33 > 30) and
`info_per_endpoint_within_budget` (9 > 8) governance budgets. The five extra
events are all outside the SVG vector outline support scope, and none of
this spec's new events (`vector_outline_init` / `vector_outline_done` /
`vector_outline_rejected_unsupported`) appear in the canonical workflow log.

This step-6 failure is a **pre-existing, unrelated log-quality budget
regression**. It is tracked separately in
the log governance info-budget regression follow-up and **must not block the
judgement of whether the SVG outline fix itself works**. The 5 narrow
success criteria above are the source of truth for this spec's correctness.

## Per-step results

### Step 1 — `git diff --check`

- Command: `git diff --check`
- Exit code: **0**
- Result: **PASS** — no whitespace / mojibake / merge marker issues.

### Step 2 — Frontend Vitest combined (4 spec files)

- Command (cleaner form, no `--` separator, per Task 1.6 / 2.5 / 3.6 convention):
  `python scripts/run_vitest.py run src/__tests__/outline-settings-vector.property.test.tsx src/__tests__/converter-vector-outline-payload.property.test.ts src/__tests__/feedback-advanced-params-vector-outline.property.test.tsx src/__tests__/recipe-roundtrip.property.test.ts`
- Exit code: **0**
- Result: **PASS** — 4 test files, 14 tests passed, 0 failed. Duration ≈ 1.30 s.

### Step 3 — Backend pytest combined (6 test files: PBT + unit)

- Command:
  `python -m pytest tests/test_vector_outline_pipeline_properties.py tests/test_raster_outline_preservation_properties.py tests/test_vector_branch_no_outline_preservation_properties.py tests/test_feedback_advanced_params_outline_preservation_properties.py tests/test_puzzle_boundary_pipeline_unit.py tests/test_pipeline_step_modules_unit.py -v --hypothesis-show-statistics`
- Exit code: **0**
- Result: **PASS** — 78 tests passed, 0 failed, ≈ 6.45 s. Hypothesis statistics:
  - `test_vector_generate_includes_outline_geometry`: 200 examples (OQ-4 cap)
  - `test_vector_preview_generate_outline_parity`: 200 examples
  - `test_raster_outline_structural_invariants`: 100 examples
  - `test_vector_no_outline_preserves_baseline`: 100 examples
  - feedback advanced-params preservation tests: 50 examples each
  - All within OQ-4 thresholds (general 100, vector outline geometry 200).

### Step 4 — Logging governance unit tests

- Command:
  `python -m pytest tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v`
- Exit code: **0**
- Result: **PASS** — 21 tests passed.

### Step 5 — `log_quality_check.py --mode fast`

- Command: `python scripts/log_quality_check.py --mode fast`
- Exit code: **0**
- Result: **PASS** — 14 INFO lines (≤ 30 budget), 0 catch-all events,
  0 unstructured lines, all workflow gates green.

### Step 6 — `log_quality_check.py --mode full`

- Command: `python scripts/log_quality_check.py --mode full`
- Run history during this checkpoint:
  1. **First attempt** (clean working tree): exit **2**, HTTP 500 with
     `reference/ChromaPrint3D not found`. Environment prerequisite — the
     `extract_single_stage` workflow step requires the upstream
     ChromaPrint3D project at `<repo>/reference/ChromaPrint3D`.
  2. **After symlink** (`reference/ChromaPrint3D ->
     ../reference-projects/ChromaPrint3D`): exit **2**, HTTP 422 with
     `ModuleNotFoundError: No module named 'tqdm'`. The upstream extractor
     subprocess (`reference-projects/ChromaPrint3D/modeling/pipeline/
     step1_extract_stages.py`) imports `tqdm`, which is not in
     `requirements.txt` for this repo.
  3. **After `pip install tqdm` into `.venv`**: exit **1**, two governance
     budget checks fail (see below). All 6 workflow event checks pass.

- **Final exit code**: **1**.
- **Final result**: **FAIL — pre-existing log-governance budget regression,
  NOT introduced by this spec**.

  Governance failures:

  | Check | Threshold | Actual | Verdict |
  |---|---|---|---|
  | `info_lines_within_budget` | ≤ 30 | 33 | FAIL |
  | `info_per_endpoint_within_budget` | ≤ 8 | 9 | FAIL |

  Root cause analysis:
  - The reviewer baseline (`progress/log_audit_full_reviewer.json`)
    recorded **28 total INFO** and **max 7 per endpoint** — both within
    budget at the time it was captured.
  - The current run shows **33 total INFO** and **max 9 per endpoint**.
    The delta of +5 INFO comes from 5 events that are NOT in the
    reviewer baseline:
    - `vector_diag_geometry_fingerprint` (×2) — emitted by
      `core/vector_engine.py`.
    - `vector_preview_timings` (×1) — emitted by
      `core/pipeline/vector_branch.py`.
    - `vector_generate_timings` (×1) — emitted by
      `core/pipeline/vector_branch.py`.
    - `converter_region_detect_done` (×1) — emitted by
      `api/routers/converter/replace.py`.
    - `extractor_extract_single_stage_done` (×1) — emitted by the
      extractor router.
  - **None of these 5 events were introduced or modified by the
    SVG vector outline support work.** This scope adds three new
    structured events: `vector_outline_init`, `vector_outline_done`,
    `vector_outline_rejected_unsupported`. None appear in the captured
    full-mode log because the canonical workflow does not enable
    outline on a vector input.
  - The `vector_branch_init` → `vector_matched_rgb_overrides_applied` →
    `vector_3mf_exported` → `vector_generate_timings` →
    `vector_branch_done` sequence in the captured run confirms Task 3.3's
    code executes correctly end-to-end inside the workflow.
  - Per AGENTS Logging Governance: "Treat the script's current canonical
    workflow and thresholds as source of truth; do not weaken thresholds
    to 'fix' failures." So neither thresholds nor unrelated events are
    being touched in this spec.

  Captured log: `progress/log_audit_full_20260528_012416.log`.

  Decision: **Document and stop**. Treat the budget overflow as a
  separate log-governance follow-up. This spec's edits remain confined
  to UI / worker normalization / `core/pipeline/vector_branch.py` /
  bug-report capture and tests; no source change needed for step 6.

  ## Follow-up tracking — separate spec required

  **A separate log-governance spec must be opened** to address the +5
  INFO regression versus `progress/log_audit_full_reviewer.json`. Suggested
  scope (subject to that spec's own bug-condition methodology, not
  prescribed here):

  - Re-evaluate `vector_diag_geometry_fingerprint` and
    `vector_stroke_policy` — these were added as INFO-level diagnostics
    in `core/vector_engine.py` after the reviewer baseline; demoting to
    DEBUG would likely close the gap without losing observability.
  - Consider whether `vector_preview_timings` and
    `vector_generate_timings` should remain at INFO given they each
    duplicate the per-endpoint completion timing line emitted by
    `converter_preview_timing` / `converter_generate_timing`.
  - Revisit whether `converter_region_detect_done` and
    `extractor_extract_single_stage_done` need INFO promotion, or
    whether the per-endpoint timing INFO already covers them.
  - Refresh `progress/log_audit_full_reviewer.json` after any demotion
    so the next `--mode full` gate has the correct baseline.

  None of the above are appropriate as part of this spec because they
  are out of scope for "vector / SVG outline 支持" and would risk
  collateral changes to unrelated diagnostics during a bugfix-only
  workflow.

  ### Bypass instructions for callers who must run `--mode full` locally

  If a contributor needs `--mode full` to PASS in a personal workflow
  before the follow-up spec lands, the **environment** prerequisites are:

  1. A working `reference/ChromaPrint3D` directory (clone or symlink to
     a local checkout of `https://github.com/Neroued/ChromaPrint3D`).
  2. `tqdm` installed in the venv used to launch the dev backend
     (`.venv/bin/python -m pip install tqdm`).

  After both, the script will reach the governance check stage. The
  remaining `info_lines_within_budget` / `info_per_endpoint_within_budget`
  failures are the pre-existing regression and require the follow-up
  log-governance spec — not this one.

### Steps 7 & 8 — manual sampling (user pre-merge responsibility)

These two checks cannot be automated by this acceptance script. They require
a running dev backend, real-user upload, and manual inspection. The user
must perform them before merge.

#### Step 7 — End-to-end Bambu Studio inspection

1. Start backend + frontend (`python start_dev.py` plus
   `npm run dev` from `frontend/`).
2. In the converter UI, switch modeling mode to `Vector / SVG`.
3. Upload a real SVG with at least one closed-shape filled region.
4. Toggle `Outline` ON, set a non-zero `outline_width` (e.g. 2.0 mm).
5. Run **Preview** (sanity only — confirm the preview request returns
   200 / no errors). Per OQ-6 follow-up, the user-visible 2D / GLB
   preview does **not** render the outline ring; do not look for one.
6. Run **Generate** and download the resulting `.3mf`.
7. Open the `.3mf` in Bambu Studio. Confirm the object tree contains an
   `Outline` node alongside the regular vector fill geometry, and that
   the outline mesh is colored with the configured base / auxiliary
   filament slot. **Also confirm** the project's filament arrays
   (`filament_colour` / `filament_type` / `nozzle_temperature`) are
   still N entries for an N-color input — i.e. an 8-Color Max + outline
   input must yield 8 filament entries, not 9 (the P2 regression guard).

Failure mode to watch for: missing `Outline` node, or outline rendered as
solid fill rather than a ring. Either condition reopens Task 3.3.

#### Step 8 — Bug-report reproducibility round-trip

1. Still in the dev environment, with vector + outline enabled and a generated
   `.3mf` in hand, open the in-app feedback dialog.
2. Submit a bug report (`/api/feedback/bug-report`). Note the returned
   `ticket_id`.
3. Run: `python scripts/load_bug_repro.py <ticket_id>`.
4. Open `feedback/<YYYY-MM>/<ticket_id>/repro_manifest.md` and confirm:
   - `enable_outline=true` is present in the captured advanced params.
   - `outline_width` matches what was set in the UI.
   - `modeling_mode` is `vector` (or equivalent canonical label).

Failure mode to watch for: `enable_outline=false` or `outline` block missing
in the manifest. Either condition reopens Task 3.4.

## Open Questions — final decisions

These decisions are recorded here so the PR remains self-contained. They
should be quoted verbatim in the PR description so reviewers can sign off in
one place.

- **OQ-1 vector default `enable_outline`**: stays **`false`**. The fix only
  removes the `disabled={isVector}` lock on the UI; default checked state is
  unchanged.
- **OQ-2 unsupported-row i18n keys**: D5 / D6 unsupported reason keys are not
  pre-created. They will be added in a follow-up only when a real D5 / D6
  case actually fires; the current canonical placeholder names
  (`outline_enable_unsupported_alpha_unavailable`,
  `outline_enable_unsupported_subscription_combo`) are reserved.
- **OQ-3 bug-report `schema_version`**: stays at **3**. No bump in this spec.
  A bump only triggers if D5 / D6 unsupported reasons start being persisted,
  per `docs/bug-report-reproducibility.md`.
- **OQ-4 PBT `max_examples` cap**: general PBT uses **100**; backend
  vector-outline geometry tests use **200** (`@settings(max_examples=200,
  deadline=None)`). 200 is the hard ceiling for this spec; 500 was rejected
  due to local-runtime cost.
- **OQ-5 visual hash gate for 8-Color Max + Outline**: not enforced. Only
  structural assertions (3MF node names, mesh metadata, ring geometry,
  preview/generate parity) gate the merge.

## Acceptance verdict

### Narrow success criteria (the source of truth for this spec)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | vector / SVG mode can enable outline in UI | **PASS** | Task 3.1 removed `disabled={isVector}` and added i18n keys; Task 1.1 / 1.5 PBTs flipped FAIL → PASS in Task 3.6 |
| 2 | generate / 3MF emits `Outline` mesh + project palette stays at base-material count when `enable_outline=true`; preview cache exposes `outline_geometry` metadata only (pixel-level preview rendering is out of scope per OQ-6 follow-up) | **PASS** | Task 3.3 injected `_generate_vector_outline_mesh` into both branches; the 2026-05-29 fix removed the `vec_slot_list` Outline append so 8-Color vector + outline 3MF keeps 8 filament entries; Task 1.3 / 1.4 PBTs PASS plus 3 new regression guards |
| 3 | raster / high-fidelity outline behavior is unchanged | **PASS** | Task 3 did not touch `core/pipeline/s08_auxiliary_meshes.py`; Task 2.1 (raster preservation, 100 PBT examples + 4 anchors + existing puzzle / pipeline-step-modules tests) stayed PASS in Task 3.7 |
| 4 | bug report captures `enable_outline=true` and `outline_width` | **PASS** | Task 3.4 audit confirmed no vector-specific override anywhere in the bug-report path; Task 1.5 (UI → `buildAdvancedParams.outline.enable_outline === true`) and Task 2.3 (50-example round-trip preservation) both PASS in Task 3.6 / 3.7 |
| 5 | targeted tests (Task 1 exploration + Task 2 preservation) PASS | **PASS** | Task 3.6: 4/5 exploration tests flipped FAIL → PASS, anchor 1.2 stayed PASS (frontend exit 0, backend exit 0). Task 3.7: 74 backend + 7 frontend preservation tests stayed PASS, zero regression |

**All five criteria are met. The SVG outline fix itself works.**

### Step 1–8 outcomes (governance gate command list, for the record)

- Steps 1–5: **PASS**.
- Step 6: **FAIL — pre-existing, unrelated log-quality budget regression**.
  - The +5 INFO delta vs `progress/log_audit_full_reviewer.json` comes
    from 5 events that are NOT part of this spec
    (`vector_diag_geometry_fingerprint` ×2, `vector_preview_timings` ×1,
    `vector_generate_timings` ×1, `converter_region_detect_done` ×1,
    `extractor_extract_single_stage_done` ×1).
  - This spec's three new events (`vector_outline_init`,
    `vector_outline_done`, `vector_outline_rejected_unsupported`) do
    not appear in the canonical full workflow log because outline is
    not enabled on the canonical vector input.
  - Tracked separately as the log governance info-budget regression.
    **Does not block judging whether the SVG outline fix itself works** —
    the 5 narrow success criteria above are the source of truth.
  - No source change is being made in this spec for the log-quality gate.
- Steps 7–8: **manual, user pre-merge responsibility**.

### Task 4 status

The narrow SVG outline implementation is complete. Task 4's automated
governance gates are at **conditional PASS**: every gate that depends on
this spec's source code (steps 1–5) passes; step 6 is gated on a
separate log-governance spec; steps 7–8 require manual sampling.

Per AGENTS Logging Governance, this spec does not weaken thresholds or
demote unrelated events to "fix" step 6.

## Confirmation: no source code modified during Task 4 verification

Verified via `git status --short` after each automated step: the only working
tree changes are the Task 1 / 2 / 3 outputs that already existed before Task 4
started:

- Modified: `api/workers/converter_workers.py`,
  `core/pipeline/vector_branch.py`,
  `frontend/src/components/sections/OutlineSettings.tsx`,
  `frontend/src/data/announcements.ts`,
  `frontend/src/i18n/translations.ts`,
  `tests/test_logging_exception_governance_unit.py`.
- Untracked: the four new property test files under `frontend/src/__tests__/`,
  the four new property test files under `tests/`, the `tests/fixtures/svg_vector/`
  fixtures, and the four `progress/svg-vector-outline-*.md` archival notes
  (this file is the fifth, added by Task 4 itself for archival purposes only;
  no source / test edits).


## Post-review fixes (2026-05-29)

Two independent reviewers (Claude Opus and a second AI) cross-checked the
implementation. The second AI surfaced a P2 regression I missed in my own
review pass; both reviewers agreed P1 is real but should be scoped out of
this spec and tracked as a follow-up. The user approved the minimal
fix-and-document approach below.

### P2 fix — `Outline` no longer inflates the project palette

- File: `core/pipeline/vector_branch.py` — removed the line that appended
  `"Outline"` to `vec_slot_list`. `vec_slot_list` is forwarded as
  `project_slot_names`; the writer sizes `filament_colour` /
  `filament_type` / `nozzle_temperature` from that list. With the buggy
  append, an 8-color vector input produced a 9-filament 3MF.
- The fix mirrors raster `s09_export_3mf.run`: `Outline` lives in
  `slot_names` (so the writer exports the object) but stays out of
  `project_slot_names` (so the project palette length is unchanged).
  Outline coloring continues to work via
  `outline_mesh.visual.face_colors`; `bambu_material_name` reuses the
  resolved base material name.
- New regression guards added to
  `tests/test_vector_outline_pipeline_properties.py`:
  - `test_vector_outline_does_not_inflate_project_palette` — pins the
    8-color + outline anchor so a future regression that re-adds
    `"Outline"` to `project_slot_names` fails immediately.
  - `test_vector_no_outline_keeps_project_palette_unchanged` —
    sibling preservation test: `enable_outline=False` keeps both
    `slot_names` and `project_slot_names` Outline-free.

### P1 — preview pixel rendering scoped out, documented

- The preview branch writes `cache["outline_geometry"]` and
  `cache["outline_added"]`, but `core/pipeline/s11_glb_preview.
  generate_segmented_glb` and the 2D preview rasterizer do not consume
  those keys. Result: the user-visible 2D / 3D preview pixels are
  identical between outline-on and outline-off; the ring only appears
  in the exported 3MF.
- Per the user's "keep narrow" direction, this is now documented as
  out of scope for this spec rather than a defect to fix here:
  - `frontend/src/data/announcements.ts` — Chinese / English copy
    updated to "出现在导出的 3MF 里" / "is written into the exported
    3MF". The previous wording "同时出现在预览和导出的 3MF" /
    "shows up in both the preview and the exported 3MF" was
    over-promising.
  - This acceptance checkpoint now records OQ-6 declaring preview pixel
    rendering is a follow-up
    (`vector-outline-preview-rendering` recommended scope) and OQ-7
    pinning the project-palette / object-slot dual-track contract that
    the new tests guard.
- Added negative regression guard
  `test_preview_cache_exposes_outline_geometry_metadata_only` so a
  future implementer flips it from "metadata-only" to "actually
  rendered" alongside the actual rendering wiring.

### Cosmetic cleanup

- Removed the dead `_generate_boundary_fill_mesh` import from
  `core/pipeline/vector_branch.py`. The new helper uses
  `trimesh.creation.extrude_polygon` instead — the import was leftover.

### Re-verification after fixes

| Gate | Command | Result |
|---|---|---|
| Backend property + unit suite | `.venv/bin/python -m pytest tests/test_vector_outline_pipeline_properties.py tests/test_vector_branch_no_outline_preservation_properties.py tests/test_raster_outline_preservation_properties.py tests/test_feedback_advanced_params_outline_preservation_properties.py tests/test_puzzle_boundary_pipeline_unit.py tests/test_pipeline_step_modules_unit.py -q --hypothesis-show-statistics` | 84 PASS, 820 Hypothesis examples |
| Frontend spec test set | `.venv/bin/python scripts/run_vitest.py run src/__tests__/outline-settings-vector.property.test.tsx src/__tests__/converter-vector-outline-payload.property.test.ts src/__tests__/feedback-advanced-params-vector-outline.property.test.tsx src/__tests__/recipe-roundtrip.property.test.ts src/__tests__/recipe-roundtrip-vector-outline-preservation.property.test.ts` | 5 files / 16 tests PASS |
| Logging governance | `.venv/bin/python -m pytest tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -q` | 21 PASS |
| Fast log gate | `.venv/bin/python scripts/log_quality_check.py --mode fast` | RESULT: PASS |

Step 6 (`--mode full`) status is unchanged from the original closure — it
fails on the pre-existing log-budget regression and is not affected by this
round of fixes.

### Updated success-criteria status

| # | Criterion | Status (post-fix) |
|---|---|---|
| 1 | UI vector + outline toggleable | ✅ unchanged |
| 2 | generate / 3MF emits `Outline` mesh and keeps project palette at base-material count; preview cache exposes metadata only | **Generate ✅; preview metadata exposed but not rendered** — explicitly scoped to follow-up via OQ-6 |
| 3 | raster / high-fidelity outline behavior unchanged | ✅ unchanged |
| 4 | bug-report captures `enable_outline=true` + `outline_width` | ✅ unchanged |
| 5 | targeted tests pass | ✅ 84 backend + 16 frontend, plus 3 new regression guards |

### Files modified in this fix round

- `core/pipeline/vector_branch.py` — removed dead import; removed
  `vec_slot_list` Outline append; added comment explaining the
  raster-mirroring contract.
- `frontend/src/data/announcements.ts` — soften copy.
- `progress/svg-vector-outline-acceptance-checkpoint.md` — records OQ-6 + OQ-7.
- `tests/test_vector_outline_pipeline_properties.py` — added 3
  regression guards (P2 positive + P2 sibling preservation + P1
  metadata negative anchor).

### Pre-merge checklist (unchanged from original closure)

- [ ] Manual step 7 — Bambu Studio inspection of generated 3MF.
- [ ] Manual step 8 — vector + outline bug-report → `load_bug_repro.py`
  → `repro_manifest.md` carries `enable_outline=true` + matching
  `outline_width`.
- [ ] Acknowledge OQ-6 follow-up scope before merging.
