# Pipeline Refactor Followup — Implementation Spec

> **Audience**: GPT subagent implementing this PR.
> **Author**: Cascade (planning).
> **Status**: Ready to implement.
> **Hand-off date**: 2026-05-01.

This spec produces ONE PR delivering two artefacts:

1. `docs/pipeline-refactor-followup.md` — wake-up + intent doc for the merged Phase 0-3 sketch.
2. `tests/test_lut_pipeline_orthogonality_unit.py` — 3×2=6 contract tests pinning current LUT-source × renderer orthogonality.

**No production code changes.** Tests + documentation only.

---

## 1. Why this spec exists

PR #128 merged Phase 0-3 of the pipeline refactor. The user (project lead) re-read the work and asked Cascade to verify it actually achieves the **preventive goal** that triggered the refactor — specifically: "team adds a new color recipe source (e.g. gradient card), and SVG / voxel renderers should both auto-work, no per-cell bespoke implementation".

Cascade's audit found:

- **Phase 0-3 sketches** (`CalibrationMethod`, `BoardLayout`, `Renderer`) target the **calibration board** generation pipeline (the printable color cards in `core/calibration.py`).
- **The user's actual orthogonality concern** is at the **user image rendering** layer (`core/vector_engine.py` for SVG, `core/image_processing.py` for voxel) — a different code path that Phase 0-3 didn't touch.
- The right preventive lever for the user's concern is **contract tests at the LUT consumer boundary**, not more Protocol abstractions.
- Phase 0-3's real durable value is **Phase 1's `ColorMode` registry** (collapsed 6 duplicate dispatch tables into one); Phase 2/3 are sketches whose Phase 4 follow-through never landed.

The user's chosen path: **don't restart Phase 4**, instead **lock in current orthogonality with contract tests** + **document the conclusion** so future engineers / AI agents don't re-litigate.

This PR delivers exactly that.

---

## 2. Required reading (before starting)

Read these in order:

1. `progress/pipeline-refactor-design.md` — original master plan (long; focus on §1 Mission, §3.3 Target architecture, §4 Phased plan, §8 Phase 4 sketch).
2. `progress/pipeline-refactor-status.md` — what shipped in PR #128.
3. `docs/server-mode-scaffold.md` — A4-1 wake-up doc; **this spec's `docs/pipeline-refactor-followup.md` follows the same template structure**.
4. `core/calibration_methods.py` — the Phase 2 sketch.
5. `core/board_layout.py` — the Phase 3 sketch.
6. `core/color_modes.py` — Phase 1's real value (the unified registry).
7. `core/vector_engine.py` (head only, ~120 lines) — SVG entry point + pipeline overview.
8. `core/pipeline/processing_ops/lut_loader.py` — the LUT consumer; `_finalize_loaded_lut` defines the canonical LUT schema.
9. `core/extractor.py` (`_generate_recipes` + `extract_colors_from_image` regions) — photo-5-layer LUT producer.
10. `AGENTS.md` — engineering rules, especially Encoding & Text Safety, Frontend Rules, Tests, Logging Governance.

If any of these change before implementation starts, re-read.

---

## 3. Deliverable A — `docs/pipeline-refactor-followup.md`

Mirror the structure of `docs/server-mode-scaffold.md` (10 sections + AI-agent quick exit guide).

### §1 — Why this guide exists

- Phase 0-3 merged in PR #128; Phase 4 explicitly **NOT** in PR per `progress/pipeline-refactor-status.md` line ~103.
- Project posture: don't restart Phase 4 unless team brings a real new calibration method (per memory `d2e13ccb-...` desktop-first; see `docs/server-mode-scaffold.md` §3 for the same trigger pattern).
- This doc is the runbook for whoever decides to revisit.

### §2 — What was shipped (PR #128 inventory)

Reproduce the Phase-by-Phase table from `progress/pipeline-refactor-status.md` (lines 13-101) but condense to single-table form:

| Phase | Delivery | Status |
|---|---|---|
| 0 | Hygiene (4 sub-PRs A/B/C/D) | ✅ Real delivery — see commits `a57cf7f`, `55dca9d`, `a660a71`, `6f354f4`, `93e1bbb` |
| 1 | `ColorMode` registry | ✅ Real delivery — `core/color_modes.py`; collapsed 6 duplicate dispatch tables; **the durable Phase 0-3 value lives here** |
| 2 | `CalibrationMethod` Protocol | ⚠️ Sketch only — 1 lighthouse (`Smart1296CalibrationMethod` wraps legacy `generate_smart_board`); 6 other `generate_*_board()` functions un-migrated |
| 3 | `BoardLayout` IR + `Renderer` Protocol | ⚠️ Sketch only — 1 lighthouse (`VoxelMeshRenderer`); `SVGRenderer` not built; `BoardLayout.voxel_matrix` field couples IR to voxel renderer |
| 4 | Adoption + new method | ❌ Never PR'd — see `progress/pipeline-refactor-status.md` §"Phase 4" for the deferral list |

### §3 — Critical re-evaluation: abstraction layer mismatch

**This is the new insight not present in either previous doc.**

Phase 0-3 abstractions target the **calibration board** code path:
- `core/calibration.py` produces 3MF files of printable color squares (Smart1296, 4-Color, 8-Color, BW, 5-Color Extended boards).
- The user photographs these, then `core/extractor.py` extracts a LUT.
- The LUT then drives `core/converter.py` → `core/image_processing.py` (voxel) or `core/vector_engine.py` (SVG) for **user image rendering**.

`CalibrationMethod.generate(...)` returns the legacy 3MF tuple (calibration board). `BoardLayout.voxel_matrix` is a 3D voxel array — the calibration board's physical geometry. `VoxelMeshRenderer` consumes that to produce a calibration board mesh.

**The user's actual orthogonality concern lives one layer downstream**: any LUT (regardless of its source — photo-5-layer, gradient card, externally reverse-inferred) should be consumable by both renderers (voxel via `image_processing.py`, SVG via `vector_engine.py`). Phase 0-3 abstractions don't enforce this — they're for the calibration board itself.

So the merged abstractions:
- ✅ are valid architecture for the calibration board side (just incomplete because Phase 4 didn't ship)
- ❌ don't prevent the gradient-card × SVG style of regression at the user image rendering layer

The right preventive measure is at the **LUT contract level**: a parametrized test that asserts every `(LUT source, renderer)` cell works today, so adding a new source forces the author to extend the parametrize list and prove orthogonality in CI.

### §4 — The orthogonality grid

Today's reality:

| | voxel renderer (`image_processing.py`) | SVG renderer (`vector_engine.py`) |
|---|---|---|
| **photo-5-layer LUT** (`core/extractor.py` Stage A photo path) | ✅ canonical path, always worked | ✅ canonical path, always worked |
| **gradient card LUT** (Stage A gradient path; see `extractor_extract_gradient_card_stage_a_done` event) | ✅ works | ✅ works (recent fix per user) |
| **external reverse-inferred LUT** (`.npz` import; `core/lut_merger.py` Merged path) | ✅ works | ✅ works |

The contract test in §6 verifies all 6 cells.

### §5 — What Phase 4 was supposed to do (and why it shouldn't restart now)

Reproduce the Phase 4 deferral list from `progress/pipeline-refactor-status.md` (the 8-item bulleted list under "🟡 Phase 4 — Adoption + new method (NOT in this PR)"). Add a header:

> **DO NOT RESTART Phase 4 unless**:
> - Team brings a real new calibration method that needs to land
> - OR a multi-renderer feature ships (e.g., PNG preview / large-format tiled) that benefits from `BoardLayout` IR

Without one of these triggers, Phase 4 is over-engineering for current product needs.

### §6 — The contract test (this PR's `tests/test_lut_pipeline_orthogonality_unit.py`)

Describe the test design (3×2 parametrize, schema contract, fixture strategy) at conceptual level. Implementation details live in §4 of THIS spec. Reference the test file path and what it asserts.

### §7 — The canonical LUT schema

The implicit contract every LUT source must produce, every LUT consumer must accept:

```python
# Defined by core/pipeline/processing_ops/lut_loader.py::_finalize_loaded_lut
{
    "lut_rgb": np.ndarray,          # shape (N, 3), dtype uint8
    "ref_stacks": np.ndarray,       # shape (N, layer_count), dtype int32
    "kdtree": scipy.spatial.KDTree, # CIELAB-space k-d tree for perceptual matching
    "layer_count": int,             # typically 5
}
```

A new LUT source must produce this dict shape (or feed `_finalize_loaded_lut` with `(lut_rgb, ref_stacks, layer_count)`). A new renderer must accept this dict shape.

This schema is **the** orthogonality lever. The contract test in §6 enforces it on both sides.

### §8 — Operational concerns

- Test runtime budget: ≤10s total for all 6 cells (each cell uses minimal inputs)
- Don't add to `scripts/log_quality_check.py` `WORKFLOW_ORDER` — this is a structural/contract test, not a logging-governance gate
- Don't add to `scripts/run_smoke_tests.py` initially — let it run via the default `pytest tests/` collection. Only promote if it proves to catch regressions in real PRs.
- No new INFO log events emitted (test/doc only PR)

### §9 — Design choice FAQ

Recorded so future engineers don't re-litigate.

**Why a contract test, not another Protocol class?**

Protocols are static-typing aids; they don't fail in CI when a new method skips the orthogonality check. Parametrized tests **do** fail when the parametrize list grows without a passing fixture. For preventive value, tests > Protocols.

**Why all 6 cells, not just gradient_card × SVG?**

Locks in current good behavior across the entire grid. If `photo_5layer × voxel` silently breaks during an unrelated refactor, the test catches it. Single-cell tests miss this.

**Why "schema contract", not "end-to-end pipeline"?**

End-to-end tests are brittle (depend on heavy fixtures, fonts, system libs). Schema-contract tests are fast and focused on the actual invariant (LUT shape → renderer accepts).

**Why is `BoardLayout.voxel_matrix` a design concern?**

`BoardLayout` was introduced as a "mode-independent IR". But its core data (`voxel_matrix: (Z, H, W) int`) is voxel-renderer-specific. SVG renderer would need to derive vector paths from cells, which the voxel matrix already collapses into volumetric data. A truly orthogonal IR would carry per-cell logical info (`grid_position`, `material_id`, `cell_size_mm`) and let each renderer expand cells in its own way. **This is a Phase 4 fix-up; out of scope for this PR**, captured here for the future restart.

**Why not delete the un-migrated Phase 2/3 sketches now?**

They satisfy AGENTS.md L42 ("New utilities … must land with at least one adoption site"). Deleting them is a separate audit (per AGENTS.md "Drop or fold utilities with zero adoption after 30 days"). Phase 0-3 merged on `f666612` (date X); the 30-day clock starts there. If 30 days pass with no Phase 4 trigger, audit + delete is appropriate.

### §10 — References + AI agent quick exit guide

References:
- PRs: #128 (Phase 0-3 refactor), #138 (A4-1 doc), THIS PR
- Memory: `d2e13ccb-5834-4484-b84e-e2eda326f083` (project posture: desktop-first)
- Companion doc: `docs/server-mode-scaffold.md` (the A4-1 wake-up guide; this followup follows the same template)

AI agent quick exit guide (mirror `docs/server-mode-scaffold.md` §10):

If you (a future AI agent) are dropped into this guide and asked to "continue the pipeline refactor":

1. Read §3 and §5 — confirm the wake trigger (team's new method or multi-renderer feature) actually exists; do not auto-restart Phase 4.
2. Run the §6 contract test — confirm orthogonality still holds on current `dev-refactor` HEAD.
3. If a wake trigger exists, read `progress/pipeline-refactor-design.md` §8 (Phase 4 sketch) for the deferral list.
4. Build Phase 4 per the design doc, gating each step on the §6 contract test staying green.
5. Update memory `d2e13ccb-...` if posture changed.

If the wake trigger is **not** present, do **not** start Phase 4. Tell the user the trigger is missing and ask for explicit confirmation before touching production code.

---

## 4. Deliverable B — `tests/test_lut_pipeline_orthogonality_unit.py`

### 4.1 File header

```python
"""LUT-source × renderer orthogonality contract tests.
LUT 来源 × 渲染器 正交性 契约测试。

Why this file exists:
    The user image rendering pipeline supports N LUT sources (photo-5-layer,
    gradient card, externally reverse-inferred) × M renderers (voxel via
    ``core.image_processing``, SVG via ``core.vector_engine``). Every cell
    must produce a valid output. Today all N×M cells work; this test pins
    that invariant so a future LUT source or renderer cannot silently
    regress one cell.

为什么有这个文件:
    用户图像渲染流水线支持 N 种 LUT 来源 × M 种渲染器, 每个组合必须能
    产出有效输出. 当前所有 N×M 组合都通过, 本测试将该不变量钉住, 防止
    未来新增的 LUT 来源或渲染器悄悄破坏某个组合.

When this test fails:
    1. A LUT source's output drifted from the canonical schema (see
       ``core/pipeline/processing_ops/lut_loader.py::_finalize_loaded_lut``).
    2. A renderer started rejecting a previously-working LUT shape.
    3. A new LUT source was added without extending ``LUT_SOURCES`` and
       proving orthogonality.

Adding a new LUT source:
    1. Add the source name to ``LUT_SOURCES``.
    2. Implement ``_lut_for_<source_name>(tmp_path)`` producing a canonical
       LUT dict.
    3. Run this file; all M renderer cells for the new source must pass.
"""
```

### 4.2 Imports

```python
from __future__ import annotations
from pathlib import Path
from typing import Any

import numpy as np
import pytest
```

Avoid heavy imports at module top (trimesh, shapely, scipy). Lazy-import inside the per-source/per-renderer factories so test collection stays fast.

### 4.3 Parametrize axes

```python
LUT_SOURCES = ("photo_5layer", "gradient_card", "external_reverse")
RENDERERS = ("voxel", "svg")
```

If GPT discovers a fourth source already in code (e.g. additional Stage A variant), document the discovery in the PR description and either include or explicitly exclude it with a comment.

### 4.4 Per-source LUT factories

Each factory returns the canonical LUT dict (see Spec §3 §7 for schema). Investigation pointers — GPT must confirm by reading code:

**`photo_5layer`** (canonical 1024-color 4-Color RYBW path):
- Probable entry: `core.extractor.extract_colors_from_image` or the Stage A photo flow.
- Alternative (recommended for speed): use a **fixture LUT** at `tests/fixtures/luts/photo_5layer_1024.npz` if one exists. If none exists, `_finalize_loaded_lut` can be invoked directly with a synthetic 1024-color RGB grid + reference stacks generated by `core/extractor.py::_generate_recipes("4-Color (RYBW)", 1024)`.

**`gradient_card`** (Stage A gradient path):
- Probable entry: search for the function that emits `extractor_extract_gradient_card_stage_a_done`. Likely lives in `core/extractor.py` or `core/single_stage/`.
- Alternative: synthetic gradient-card-shaped LUT (e.g., 256 colors with monotonic stacks) fed through `_finalize_loaded_lut`. Document the simplification.

**`external_reverse`** (external `.npz` import / Merged path):
- Probable entry: `core.pipeline.processing_ops.lut_loader.load_lut(lut_path, color_mode="Merged")` with a pre-built `.npz` fixture.
- Alternative: synthetic Merged-shape LUT (non-standard size, e.g. 500 colors) fed through `_finalize_loaded_lut` with `color_mode="Merged"`.

**Investigation rule**: prefer the real production entry point if it runs in <2s on tiny inputs. Otherwise fall back to synthetic fixtures and document the simplification in the factory's docstring. **Do not** mock so heavily that the test loses semantic value.

Each factory signature:

```python
def _lut_for_photo_5layer(tmp_path: Path) -> dict[str, Any]:
    """Produce a canonical photo-5-layer LUT.
    生成标准的拍照 5 层 LUT。
    """
    ...
```

### 4.5 Per-renderer entry points

Each renderer takes (LUT dict, sample input) and produces an output artefact.

**`voxel`** renderer:
- Probable entry: `core.image_processing.LuminaImageProcessor.convert(...)` or `core.converter.convert(...)`.
- GPT must read `core/converter.py` head to find the exact public function signature.
- Sample input: 8×8 RGB image (`np.random.randint(0, 256, (8, 8, 3), dtype=np.uint8)` or a fixture).
- Output: a 3MF path or `trimesh.Scene`. Assert non-None + has at least 1 geometry / non-zero file size.

**`svg`** renderer:
- Probable entry: search `core/vector_engine.py` for the public `convert_*` function (`grep "^def " core/vector_engine.py | head`).
- Sample input: minimal SVG string with 1 colored shape, e.g.:
  ```python
  SVG_FIXTURE = '''<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">
      <rect x="0" y="0" width="10" height="10" fill="#ff0000"/>
  </svg>'''
  ```
- Output: 3MF path or trimesh scene. Assert non-None + non-empty.

Each renderer signature:

```python
def _render_voxel(lut: dict[str, Any], sample_input: Any, tmp_path: Path) -> Any:
    """Run the voxel renderer with the given LUT + sample.
    使用指定 LUT 与样本输入运行体素渲染器。
    """
    ...
```

### 4.6 The test function

```python
@pytest.mark.parametrize("renderer", RENDERERS)
@pytest.mark.parametrize("lut_source", LUT_SOURCES)
def test_lut_source_x_renderer_orthogonality(
    lut_source: str,
    renderer: str,
    tmp_path: Path,
) -> None:
    """Every (LUT source, renderer) cell must produce a valid output.
    每个 (LUT 来源, 渲染器) 组合都必须能产生有效输出。

    Failure modes pinned by this test:
    - A LUT source emits an out-of-schema dict (missing keys, wrong dtypes).
    - A renderer rejects a canonical-schema LUT.
    - A future PR adds a LUT source / renderer without proving orthogonality.

    Args:
        lut_source: One of ``LUT_SOURCES``.
        renderer: One of ``RENDERERS``.
        tmp_path: pytest temp directory fixture.
    """
    lut = _LUT_FACTORIES[lut_source](tmp_path)

    # Schema contract — every LUT source must satisfy this.
    assert isinstance(lut, dict), f"{lut_source} factory must return a dict"
    assert "lut_rgb" in lut and lut["lut_rgb"].dtype == np.uint8
    assert "ref_stacks" in lut and lut["ref_stacks"].dtype == np.int32
    assert "layer_count" in lut and isinstance(lut["layer_count"], int)
    assert lut["lut_rgb"].shape[0] == lut["ref_stacks"].shape[0]

    # Renderer contract — every renderer must consume the canonical LUT.
    sample_input = _SAMPLE_INPUTS[renderer]
    output = _RENDERERS[renderer](lut, sample_input, tmp_path)

    # Output contract — non-None + format-specific shape check.
    assert output is not None, f"{renderer} produced None for {lut_source} LUT"
    _assert_output_format_valid(renderer, output)


_LUT_FACTORIES = {
    "photo_5layer": _lut_for_photo_5layer,
    "gradient_card": _lut_for_gradient_card,
    "external_reverse": _lut_for_external_reverse,
}

_RENDERERS = {
    "voxel": _render_voxel,
    "svg": _render_svg,
}

_SAMPLE_INPUTS = {
    "voxel": ...,  # 8x8 RGB image fixture
    "svg": SVG_FIXTURE,
}


def _assert_output_format_valid(renderer: str, output: Any) -> None:
    """Format-specific output validation.
    特定渲染器的输出校验。
    """
    if renderer == "voxel":
        # Either a path to a 3MF or a trimesh.Scene; assert non-empty.
        ...
    elif renderer == "svg":
        # Either a path to a 3MF/SVG or a trimesh.Scene; assert non-empty.
        ...
```

### 4.7 Cells that genuinely don't work

If GPT discovers a cell that fails today (despite the user's claim that gradient × SVG was fixed):

1. Mark it with `pytest.param(..., marks=pytest.mark.xfail(reason="...", strict=True))`.
2. Document in the PR description with the failure trace.
3. Open a follow-up issue (or note in the PR body for triage).
4. **Do not** silently `pytest.skip()`.
5. **Do not** auto-fix in this PR — fixes are separate work.

`strict=True` makes the test fail if the cell unexpectedly starts passing — the team will then know to remove the xfail.

---

## 5. Acceptance criteria

Run **all** of the following from repo root before opening the PR:

```bash
# 1. The new test file passes (or has documented xfails)
python -m pytest tests/test_lut_pipeline_orthogonality_unit.py -v

# 2. No regressions
python -m pytest tests/ -q

# 3. Logging governance gate (this PR doesn't change logging, gate must stay green)
python scripts/log_quality_check.py --mode fast

# 4. Doc renders cleanly (sanity check by reading)
cat docs/pipeline-refactor-followup.md | head -80
```

Pass criteria:

- ✅ `tests/test_lut_pipeline_orthogonality_unit.py` collects exactly 6 tests; ≥5 pass; ≤1 xfail.
- ✅ Total test count grew by exactly 6 (or 6 minus xfails) — no other tests added or removed.
- ✅ `--mode fast` log-quality gate stays at PASS (canonical INFO budget unchanged).
- ✅ `docs/pipeline-refactor-followup.md` exists with all 10 sections + AI quick-exit guide.
- ✅ Both files contain bilingual docstrings/headers per AGENTS.md.
- ✅ All non-ASCII text saved as UTF-8 (verify by re-reading the file with explicit UTF-8 encoding after save; check for `锟`, `鎷`, `鍙`, `涓` mojibake markers).
- ✅ No edits to `core/`, `api/`, `frontend/`, `config.py`, `requirements.txt`.

---

## 6. Out of scope (DO NOT do)

Hard prohibitions:

- ❌ Do **not** restart Phase 4. The Phase 4 deferral list in `progress/pipeline-refactor-status.md` stays deferred.
- ❌ Do **not** migrate any consumer to `ColorMode` (extractor.py, lut_loader.py, lut_merger.py, pipeline_utils.py keep current dispatch).
- ❌ Do **not** delete the transitional re-exports in `core/pipeline/pipeline_utils.py`.
- ❌ Do **not** add new Protocol classes, ABCs, or dataclasses to `core/`.
- ❌ Do **not** modify `CalibrationMethod`, `BoardLayout`, `Renderer`, `ColorMode`, or any existing public API.
- ❌ Do **not** touch `core/calibration.py` or `core/calibration_methods.py`.
- ❌ Do **not** change any user-visible behavior, logs, frontend strings, or persisted file formats.
- ❌ Do **not** add `gradient_group_analyzer` orthogonality concerns — that module is for image-region gradient *post-processing*, not the gradient-card calibration source. Different feature, different tests.
- ❌ Do **not** add to `scripts/log_quality_check.py` `WORKFLOW_ORDER`.

If the spec says do something but implementing it would require violating one of these prohibitions, **stop and ask the user**.

---

## 7. AGENTS.md compliance reminders

The full `AGENTS.md` is the source of truth. Highlights for this PR:

**Encoding & Text Safety**:
- Both files contain Chinese text. Save as UTF-8 explicitly. After save, re-open with explicit UTF-8 read and scan for mojibake markers (`锟`, `鎷`, `鍙`, `涓`).
- Prefer `apply_patch` over PowerShell `Set-Content`/`Out-File`/`>`/`>>`.

**Docstrings**:
- Bilingual Google-style on the test module + each LUT factory + each renderer wrapper + the test function.
- Doc headings use bilingual section titles where natural (mirror `docs/server-mode-scaffold.md` style).

**Tests**:
- File naming: `test_*_unit.py` ✅ (the spec dictates `test_lut_pipeline_orthogonality_unit.py`).
- Add focused regression tests for the orthogonality contract; no Hypothesis needed (the parametrize matrix is small + closed).
- Keep pytest collection fast (lazy heavy imports inside factories).

**Logging Governance**:
- Test-only PR; do not emit business INFO logs.
- If any helper accidentally pulls a module that runs `setup_file_logging()`, ensure the test environment doesn't fight the canonical INFO budget.

**Lossless refactoring**:
- This PR is non-refactoring (test + doc only). The "lossless" rule still applies trivially: existing public APIs unchanged.

**Frontend rules**:
- Not affected. No frontend changes.

---

## 8. Branch + commit + PR workflow

```bash
# Cut branch from current dev-refactor HEAD
git checkout dev-refactor
git pull origin dev-refactor
git checkout -b docs/pipeline-refactor-followup

# Implement the doc + test files
# (use apply_patch / your editor; do not pipe non-ASCII through PowerShell defaults)

# Run all gates from §5 — every gate must pass before commit

# Stage + commit
git add docs/pipeline-refactor-followup.md tests/test_lut_pipeline_orthogonality_unit.py
git commit -m "docs+test: pipeline refactor followup + LUT*renderer orthogonality contract"

# Push
git push -u origin docs/pipeline-refactor-followup

# Open PR
gh pr create \
  --base dev-refactor \
  --head docs/pipeline-refactor-followup \
  --title "docs+test: pipeline refactor followup + LUT*renderer orthogonality contract" \
  --body-file <(printf "%s" "$PR_BODY")
```

PR body (English; mirror `docs/server-mode-scaffold.md` PR body):

```markdown
## Summary

Companion to PR #128 (pipeline refactor Phase 0-3). Adds:

1. `docs/pipeline-refactor-followup.md` — wake-up + intent doc capturing the merged Phase 0-3 sketch state and the strategic decision NOT to restart Phase 4 without a wake trigger.
2. `tests/test_lut_pipeline_orthogonality_unit.py` — 3×2=6 contract tests pinning current LUT-source × renderer orthogonality.

**No production code changes.** Documentation + tests only.

## Why this PR exists

After PR #128 (Phase 0-3) merged, the user audited the actual delivery vs the design intent and found:

- Phase 0-3 sketches target the **calibration board** generation pipeline.
- The user's actual orthogonality concern (any LUT source works with any renderer) lives at the **user image rendering** layer, which Phase 0-3 didn't touch.
- The right preventive lever is **contract tests at the LUT consumer boundary**, not more Protocol abstractions.

This PR delivers exactly that — a parametrized contract test that locks in the current 6-cell orthogonality, plus a doc explaining the abstraction-layer mismatch so future engineers / AI agents don't re-litigate.

See `docs/pipeline-refactor-followup.md` §3 for the full re-evaluation.

## What's in the doc

10 sections + AI-agent quick exit guide (mirrors `docs/server-mode-scaffold.md` template):

- §1-2: Why + what shipped in PR #128
- §3: Critical re-evaluation — abstraction layer mismatch
- §4: The 3×2 orthogonality grid (current state)
- §5: Phase 4 deferral list (do not restart without trigger)
- §6: This PR's contract test
- §7: Canonical LUT schema (the actual orthogonality lever)
- §8-9: Operational concerns + design FAQ
- §10: References + AI agent quick exit guide

## What's in the test

`tests/test_lut_pipeline_orthogonality_unit.py` — 6 parametrized cells:

| | voxel | svg |
|---|---|---|
| photo-5-layer LUT | ✅ | ✅ |
| gradient card LUT | ✅ | ✅ |
| external reverse-inferred LUT | ✅ | ✅ |

Each cell asserts:
1. The LUT source produces a canonical-schema dict (`lut_rgb`, `ref_stacks`, `layer_count`, `kdtree`).
2. The renderer accepts the LUT and produces a non-empty output.
3. Output format is structurally valid for the renderer.

Adding a new LUT source forces the author to extend `LUT_SOURCES` and prove orthogonality in CI.

## Verification

```
python -m pytest tests/test_lut_pipeline_orthogonality_unit.py -v       # 6 passed
python -m pytest tests/ -q                                              # +6 collected
python scripts/log_quality_check.py --mode fast                         # PASS
```

## Risk

Low. Test + doc only.

## References

- PR #128 — Phase 0-3 refactor
- PR #138 — A4-1 scaffold doc (template for this followup doc)
- `progress/pipeline-refactor-design.md` — original master plan
- `progress/pipeline-refactor-status.md` — what shipped vs deferred in PR #128
- `progress/pipeline-refactor-followup-spec.md` — this PR's implementation spec
```

---

## 9. Hand-off TL;DR

You are implementing one PR with two artefacts. Read §2's reading list first. Build §3 (doc) + §4 (test) per the section-by-section spec. Run §5 acceptance gates. Honor §6 prohibitions and §7 AGENTS.md rules. Use §8 branch + PR workflow.

If anything in this spec is ambiguous or contradicts what you find in the code, **stop and ask the user** — do not guess. The user prefers narrow, lossless changes over speculative engineering.

After your PR is opened, the user will review and merge.
