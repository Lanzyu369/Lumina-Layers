# Vector Analyze Hotspot Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Continue the SVG vector performance investigation after removing the raster-in-SVG sample by producing clean corpus reports and breaking down the next hotspot inside SVG analyze.

**Architecture:** Extend the existing corpus profiler instead of creating a parallel benchmark path. The profiler already records `VectorAnalysis.stage_timings`; this round promotes those timings into CSV/Markdown/JSON summaries so parse, occlusion clipping, and color matching can be compared across the corpus. Use the cleaned 17-SVG corpus to rerun fast-native and surface-validated reports, then profile the slowest analyze samples with Python's built-in profiler.

**Tech Stack:** Python 3.12, pytest, Pillow report rendering, cProfile/pstats, existing `VectorProcessor` and optional `.scratch/vector_cpp_spike/clipper2_batch`.

---

### Task 1: Remove Invalid Corpus Sample

**Files:**
- Delete external sample: `/Volumes/personal_folder/新建文件夹/1 (3).svg`

- [x] **Step 1: Confirm the fake SVG exists and is the raster wrapper sample**

Run:
`.venv/bin/python - <<'PY'
from pathlib import Path
p = Path("/Volumes/personal_folder/新建文件夹/1 (3).svg")
print(p.exists(), p.stat().st_size if p.exists() else 0)
PY`

Expected: file exists before deletion.

- [x] **Step 2: Delete the fake SVG and recount corpus SVGs**

Run:
`rm '/Volumes/personal_folder/新建文件夹/1 (3).svg' && find '/Volumes/personal_folder/新建文件夹' -maxdepth 1 -type f -iname '*.svg' | sort | wc -l`

Expected: `17`.

### Task 2: Add Analyze Stage Breakdown To Corpus Report

**Files:**
- Modify: `scripts/profile_vector_native_mesh_corpus.py`
- Modify: `tests/test_vector_native_mesh_corpus_profile_unit.py`

- [x] **Step 1: Write failing tests for analyze timing columns and aggregate totals**

Add tests that assert:
- `sample_summary_row()` exposes `parse_seconds`, `occlusion_seconds`, `color_match_seconds`, and `analyze_unaccounted_seconds`.
- `_build_corpus_report()` aggregates those timings under `summary["analyze_stage_totals_seconds"]`.

Run:
`.venv/bin/python -m pytest tests/test_vector_native_mesh_corpus_profile_unit.py -v`

Expected: FAIL until the report helper is extended.

- [x] **Step 2: Implement analyze stage row and summary fields**

Update `sample_summary_row()` to read `sample["analysis"]["stage_timings"]`.

Update `_build_corpus_report()` to sum:
- `parse_seconds`
- `occlusion_seconds`
- `color_match_seconds`
- `analyze_unaccounted_seconds`

- [x] **Step 3: Update Markdown/CSV output**

Keep CSV automatic through row fields. Add Markdown summary lines for parse, occlusion, color match, and unaccounted analyze time. Add per-sample table columns for parse, occlusion, and color match.

- [x] **Step 4: Verify focused tests pass**

Run:
`.venv/bin/python -m pytest tests/test_vector_native_mesh_corpus_profile_unit.py -v`

Expected: PASS.

### Task 3: Rerun Clean Corpus Reports

**Files:**
- Write outputs under `.scratch/vector_native_mesh_corpus/provided_svgs_clean_fast/`
- Write outputs under `.scratch/vector_native_mesh_corpus/provided_svgs_clean_surface_validated/`

- [x] **Step 1: Run fast-native corpus on the 17 valid SVGs**

Run:
`PYTHONPATH=.scratch/vector_cpp_spike .venv/bin/python scripts/profile_vector_native_mesh_corpus.py '/Volumes/personal_folder/新建文件夹' --repeats 1 --allow-failures --out-dir .scratch/vector_native_mesh_corpus/provided_svgs_clean_fast`

Expected: report writes successfully; any remaining FAIL rows are quality deltas, not invalid samples.

- [x] **Step 2: Run surface-validated corpus on the 17 valid SVGs**

Run:
`PYTHONPATH=.scratch/vector_cpp_spike .venv/bin/python scripts/profile_vector_native_mesh_corpus.py '/Volumes/personal_folder/新建文件夹' --repeats 1 --validate-native-surface --out-dir .scratch/vector_native_mesh_corpus/provided_svgs_clean_surface_validated`

Expected: all 17 vector samples pass quality gate.

### Task 4: Deep Profile Analyze Hotspots

**Files:**
- Write profiler output under `.scratch/vector_native_mesh_corpus/analyze_hotspots/`

- [x] **Step 1: Identify top analyze samples from the clean fast report**

Use the clean JSON report to sort rows by `analyze_seconds`.

- [x] **Step 2: Run cProfile against the top slow analyze samples**

For each selected SVG, run `VectorProcessor.analyze_svg()` under cProfile and write pstats text sorted by cumulative time.

- [x] **Step 3: Summarize the bottleneck**

Record whether parse, occlusion clipping, color matching, or another function family dominates the slowest samples.

Result: parse and occlusion clipping dominate the cleaned corpus. The slowest files are path-heavy SVGs with many `fill-rule="evenodd"` paths and arc commands. A bulk evenodd symmetric-difference helper reduced corpus analyze time from 53.627s to 48.540s (-9.49%) with zero geometry deltas across the 17 valid SVGs.

Additional native mesh finding: the remaining fast-native quality failures are not primarily 2D union/close errors. Native 2D surface formulas match Python reference within roughly 0.02% on inspected failing groups, while mesh top/bottom triangle area accounts for the full surface-area overage. See `.scratch/vector_native_mesh_corpus/round2_summary.md`.

### Task 5: Verification And Process Hygiene

**Files:**
- Existing tests and scripts

- [x] **Step 1: Run focused tests**

Run:
`.venv/bin/python -m pytest tests/test_vector_native_mesh_corpus_profile_unit.py tests/test_vector_native_mesh_unit.py -v`

Expected: PASS.

- [x] **Step 2: Run vector/native/GLB related regression subset**

Run:
`.venv/bin/python -m pytest tests/test_vector_native_mesh_corpus_profile_unit.py tests/test_vector_native_mesh_unit.py tests/test_vector_engine_unit.py tests/test_vector_engine_stroke_unit.py tests/test_vector_glb_v2_kernel_unit.py tests/test_vector_glb_v2_parity_unit.py tests/test_glb_v2_kernel_unit.py -q`

Expected: PASS, with known external-asset skips allowed.

- [x] **Step 3: Run syntax, diff, encoding, and process checks**

Run:
`.venv/bin/python -m py_compile core/vector_native_mesh.py scripts/profile_vector_native_mesh.py scripts/profile_vector_native_mesh_corpus.py tests/test_vector_native_mesh_corpus_profile_unit.py tests/test_vector_native_mesh_unit.py`

Run:
`git diff --check -- core/vector_native_mesh.py core/vector_engine.py scripts/profile_vector_native_mesh.py scripts/profile_vector_native_mesh_corpus.py tests/test_vector_native_mesh_corpus_profile_unit.py tests/test_vector_native_mesh_unit.py docs/superpowers/plans/2026-06-19-vector-analyze-hotspot-round2.md`

Run:
Run a common mojibake-marker scan across the touched files.

Run:
`ps -axo pid,command | rg '/Users/min/CascadeProjects/Lumina-studio|api_server.py|start_all.py|vite|vitest|esbuild' | rg -v 'rg '`

Expected: checks pass and no local Lumina processes remain.

### Acceptance Gate

- The invalid SVG is removed from the user's sample directory.
- Clean corpus reports contain exactly 17 samples.
- Corpus CSV/JSON/Markdown expose analyze stage breakdown.
- Fast-native report still surfaces quality failures instead of hiding them.
- Surface-validated report passes the valid vector corpus.
- The next performance hotspot is backed by stage totals and cProfile evidence.
