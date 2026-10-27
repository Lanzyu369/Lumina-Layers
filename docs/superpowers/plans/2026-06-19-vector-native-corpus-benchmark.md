# Vector Native Corpus Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a repeatable baseline v2 vs optional native hybrid mesh benchmark across a user-provided SVG corpus and produce quality-gated reports plus visual summaries.

**Architecture:** Add one focused corpus runner that reuses the single-SVG profiling helpers in `scripts/profile_vector_native_mesh.py`. The runner discovers SVGs, profiles each file independently, writes per-sample JSON plus corpus JSON/Markdown/CSV/PNG, and fails when any sample errors or quality gate fails unless explicitly allowed.

**Tech Stack:** Python 3.12, Pillow, Shapely/trimesh through existing `VectorProcessor`, optional `.scratch/vector_cpp_spike/clipper2_batch`, pytest.

---

### Task 1: Corpus Runner Unit Tests

**Files:**
- Create: `tests/test_vector_native_mesh_corpus_profile_unit.py`
- Create: `scripts/profile_vector_native_mesh_corpus.py`

- [x] **Step 1: Write failing tests for SVG discovery and corpus summary rows**

Create tests that assert:
- SVG discovery returns only `.svg`/`.SVG` files in sorted order.
- A successful sample summary row contains speedup, native/fallback counts, and PASS status.
- A failed sample summary row surfaces the error and FAIL status.

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_vector_native_mesh_corpus_profile_unit.py -v`

Expected: FAIL because `scripts.profile_vector_native_mesh_corpus` does not exist.

- [x] **Step 3: Implement minimal corpus helper functions**

Implement:
- `discover_svg_files(path: Path) -> list[Path]`
- `sample_summary_row(sample: dict) -> dict`
- `write_corpus_outputs(report: dict, out_dir: Path) -> dict[str, str]`

- [x] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_vector_native_mesh_corpus_profile_unit.py -v`

Expected: PASS.

### Task 2: Corpus Profiling Command

**Files:**
- Modify: `scripts/profile_vector_native_mesh_corpus.py`

- [x] **Step 1: Implement per-SVG profiling loop**

For each discovered SVG:
- instantiate `VectorProcessor`
- run `analyze_svg`
- build baseline mesh and native-enabled mesh
- compute scene metrics and quality gate with existing helpers
- write per-sample JSON under `samples/`
- continue to next file after exceptions while recording the error

- [x] **Step 2: Implement corpus-level Markdown, CSV, JSON, and PNG**

The report must include:
- sample count, pass/fail/error counts
- aggregate baseline/native build totals
- aggregate analyze time
- top slow samples
- top quality deltas
- per-sample rows with speedup and fallback counts

- [x] **Step 3: Run the corpus command with the provided SVG folder**

Run:
`PYTHONPATH=.scratch/vector_cpp_spike .venv/bin/python scripts/profile_vector_native_mesh_corpus.py /Volumes/personal_folder/新建文件夹 --repeats 1 --out-dir .scratch/vector_native_mesh_corpus/provided_svgs`

Expected: Produces corpus reports. Exit code is 0 only when all samples pass the quality gate and no sample errors.

### Task 3: Verification

**Files:**
- Existing and new tests

- [x] **Step 1: Run focused unit tests**

Run:
`.venv/bin/python -m pytest tests/test_vector_native_mesh_corpus_profile_unit.py tests/test_vector_native_mesh_unit.py -v`

Expected: PASS.

- [x] **Step 2: Run syntax and diff checks**

Run:
`.venv/bin/python -m py_compile scripts/profile_vector_native_mesh_corpus.py tests/test_vector_native_mesh_corpus_profile_unit.py`

Run:
`git diff --check -- scripts/profile_vector_native_mesh_corpus.py tests/test_vector_native_mesh_corpus_profile_unit.py docs/superpowers/plans/2026-06-19-vector-native-corpus-benchmark.md`

Expected: PASS.

- [x] **Step 3: Check local process hygiene**

Run:
`ps -axo pid,command | rg '/Users/min/CascadeProjects/Lumina-studio|api_server.py|start_all.py|vite|vitest|esbuild' | rg -v 'rg '`

Expected: no Lumina backend/frontend/test helper processes left running.

### Acceptance Gate

- Corpus runner can be rerun on any SVG directory.
- Each SVG gets an individual JSON result.
- Corpus report identifies performance hotspots and quality failures.
- Native extension absence/failure remains non-destructive and visible in the report.
- Provided SVG folder is actually profiled and summarized.

### Actual Corpus Runs

- Fast native run: `.scratch/vector_native_mesh_corpus/provided_svgs`
  - 18 samples discovered, 15 PASS, 2 FAIL, 1 ERROR.
  - Aggregate build speedup: 1.977x. Aggregate extrusion speedup: 2.254x.
  - The ERROR sample is a raster PNG embedded inside an SVG wrapper, not a parseable vector SVG.
- Surface-validated run: `.scratch/vector_native_mesh_corpus/provided_svgs_surface_validated`
  - 18 samples discovered, 17 PASS, 0 FAIL, 1 ERROR.
  - Aggregate build speedup: 0.807x. Aggregate extrusion speedup: 0.761x.
  - Surface validation catches quality-risk native groups and falls them back, but it is too expensive for the default runtime path.
