# Material Coherence Exact Norm Fast Path Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to
> implement this plan task-by-task.

**Goal:** Remove repeated general-purpose norm-dispatch overhead from the
neighbor-coherence hot loop while preserving every floating-point decision,
matched colour, recipe, material matrix, geometry result, and export semantic.

**Architecture:** Add one private helper for the already-proven real float64
three-vector case, using the same `dot` then `sqrt` operation sequence as
NumPy's one-dimensional fast path. Adopt it only in
`_neighbor_coherence_refine`, reuse the source norm for the negated direction,
and leave candidate discovery, pair order, thresholds, mutations, and tie
behavior untouched.

**Tech Stack:** Python 3.12, NumPy, SciPy, pytest, existing Lumina vector
profiling and semantic-snapshot harness.

---

## Scope and File Map

- Modify `tests/test_material_neighbor_coherence_unit.py` for bitwise parity
  and orchestration coverage.
- Modify `core/material_cache.py` for the private exact norm helper and its one
  production adoption site.
- Add `docs/superpowers/specs/2026-08-01-material-coherence-norm-fastpath-results.md`
  with semantic and timing evidence.
- Update `docs/superpowers/specs/2026-08-01-material-coherence-norm-fastpath-design.md`
  only to record the verified or rejected decision.
- Use `scripts/profile_converter_multicore.py` unchanged for end-to-end proof.

## Task 1: Lock the exact arithmetic and reuse contract

**Files:**

- Modify: `tests/test_material_neighbor_coherence_unit.py`
- Test: `tests/test_material_neighbor_coherence_unit.py`

### Step 1: Add the bitwise-equivalence regression

Add this test after the existing imports/helpers:

```python
def test_real_vector_norm_matches_numpy_bitwise() -> None:
    rng = np.random.default_rng(20260801)
    random_vectors = rng.normal(size=(512, 3)).astype(np.float64)
    edge_vectors = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [1.0, -2.0, 3.5],
            [-0.0, 0.0, -0.0],
            [1.0e-150, -2.0e-150, 3.0e-150],
            [1.0e150, -2.0e150, 3.0e150],
        ],
        dtype=np.float64,
    )
    vectors = np.concatenate((edge_vectors, random_vectors), axis=0)

    expected_bits = np.asarray(
        [np.linalg.norm(vector) for vector in vectors],
        dtype=np.float64,
    ).view(np.uint64)
    actual_bits = np.asarray(
        [material_cache_module._real_vector_norm(vector) for vector in vectors],
        dtype=np.float64,
    ).view(np.uint64)

    np.testing.assert_array_equal(actual_bits, expected_bits)
```

This comparison is intentionally bitwise, not tolerance-based. It proves the
helper follows the local NumPy operation sequence for the exact input domain.

### Step 2: Add the opposite-direction orchestration regression

Add a controlled two-colour test that patches neighbor discovery and Top-K
selection so the `adjust_idx == i` path is guaranteed:

```python
def test_neighbor_coherence_reuses_source_norm_for_reverse_direction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_lab = np.asarray(
        [[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]],
        dtype=np.float64,
    )
    matched_lab = np.asarray(
        [[0.0, 0.0, 0.0], [-10.0, 0.0, 0.0]],
        dtype=np.float64,
    )
    all_lab = np.asarray([[-20.0, 0.0, 0.0]], dtype=np.float64)

    monkeypatch.setattr(
        material_cache_module,
        "rgb_to_lab",
        lambda _rgb: matched_lab.copy(),
    )
    monkeypatch.setattr(
        material_cache_module,
        "_iter_neighbor_pairs",
        lambda *_args, **_kwargs: iter(((0, 1),)),
    )
    monkeypatch.setattr(
        material_cache_module,
        "_top_k_candidate_rows_blockwise",
        lambda **_kwargs: (
            np.zeros((2, 1), dtype=np.intp),
            np.asarray([[1.0], [0.0]], dtype=np.float64),
        ),
    )

    real_norm = material_cache_module._real_vector_norm
    observed_vectors: list[np.ndarray] = []

    def _recording_norm(vector: np.ndarray) -> np.floating:
        observed_vectors.append(vector.copy())
        return real_norm(vector)

    monkeypatch.setattr(
        material_cache_module,
        "_real_vector_norm",
        _recording_norm,
    )
    monkeypatch.setattr(
        material_cache_module.np.linalg,
        "norm",
        lambda *_args, **_kwargs: pytest.fail(
            "coherence hot loop must not call generic norm"
        ),
    )

    matched_rgb, _recipes, _delta_e = _neighbor_coherence_refine(
        target_lab=target_lab,
        matched_rgb=np.zeros((2, 3), dtype=np.uint8),
        recipes_user_order=np.zeros((2, 1), dtype=np.int32),
        delta_e=np.asarray([1.0, 0.0], dtype=np.float64),
        all_lab=all_lab,
        all_srgb=np.asarray([[1, 2, 3]], dtype=np.uint8),
        all_recipes=np.zeros((1, 1), dtype=np.int32),
        user_mapping=np.asarray([0], dtype=np.int32),
        coherence_weight=0.8,
        layer_count=1,
        uniform_lab=None,
        uniform_srgb=None,
        uniform_recipes=None,
    )

    assert len(observed_vectors) == 3
    np.testing.assert_array_equal(matched_rgb[0], np.asarray([1, 2, 3]))
```

Three calls are required: source direction, current matched direction, and
candidate direction. A fourth call would prove the negated source norm was
recomputed rather than reused. The generic `np.linalg.norm` guard prevents an
untracked fallback.

### Step 3: Run the new tests and confirm the red state

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_material_neighbor_coherence_unit.py \
  -k "real_vector_norm or reuses_source_norm" -v
```

Expected before production code: FAIL because `_real_vector_norm` does not
exist.

### Step 4: Commit the contract tests

```bash
git add tests/test_material_neighbor_coherence_unit.py
git commit -m "test(perf): lock exact coherence norm semantics"
```

## Task 2: Implement the narrow production fast path

**Files:**

- Modify: `core/material_cache.py`
- Test: `tests/test_material_neighbor_coherence_unit.py`

### Step 1: Add the private helper

Place the helper immediately before `_neighbor_coherence_refine`:

```python
def _real_vector_norm(vector: np.ndarray) -> np.floating:
    """Return the exact NumPy real 1-D fast-path norm for a known vector."""

    return np.sqrt(vector.dot(vector))
```

The helper remains private because it deliberately does not implement complex,
matrix, axis, object-dtype, or casting behavior.

### Step 2: Adopt the helper without changing decision order

Within `_neighbor_coherence_refine`, make only these substitutions:

```python
d_src_norm = _real_vector_norm(d_src)
...
d_matched_norm = _real_vector_norm(d_matched)
...
d_src_to_adjust_norm = d_src_norm
...
d_cand_norm = _real_vector_norm(d_cand)
```

Do not change `np.dot` cross-vector products, thresholds, logarithms,
comparisons, pair iteration, candidate iteration, mutation order, or
first-best tie handling.

### Step 3: Run focused tests

```bash
.venv/bin/python -m pytest \
  tests/test_material_neighbor_coherence_unit.py \
  -k "real_vector_norm or reuses_source_norm" -v
```

Expected: PASS.

### Step 4: Run the complete coherence unit file

```bash
.venv/bin/python -m pytest \
  tests/test_material_neighbor_coherence_unit.py -v
```

Expected: PASS with exact block/worker output tests unchanged.

### Step 5: Commit the implementation

```bash
git add core/material_cache.py
git commit -m "perf(material): streamline exact coherence norms"
```

## Task 3: Prove the surrounding material and vector contracts

**Files:**

- Test: `tests/test_material_neighbor_coherence_unit.py`
- Test: `tests/test_material_candidate_cache_unit.py`
- Test: `tests/test_material_inverse_refinement_unit.py`
- Test: `tests/test_material_cache_unit.py`
- Test: `tests/test_vector_material_matcher_unit.py`
- Test: `tests/test_material_archive_pipeline_unit.py`
- Test: `tests/test_task_parallelism_unit.py`
- Test: `tests/test_converter_multicore_profile_unit.py`
- Test: `tests/test_timing_responses_unit.py`

### Step 1: Run the related regression suite

```bash
.venv/bin/python -m pytest \
  tests/test_material_neighbor_coherence_unit.py \
  tests/test_material_candidate_cache_unit.py \
  tests/test_material_inverse_refinement_unit.py \
  tests/test_material_cache_unit.py \
  tests/test_vector_material_matcher_unit.py \
  tests/test_material_archive_pipeline_unit.py \
  tests/test_task_parallelism_unit.py \
  tests/test_converter_multicore_profile_unit.py \
  tests/test_timing_responses_unit.py -q
```

Expected: PASS; do not rely on a fixed count because parameterized coverage may
change on the parent stack.

### Step 2: Run static quality checks

```bash
.venv/bin/python -m py_compile \
  core/material_cache.py \
  tests/test_material_neighbor_coherence_unit.py
git diff --check MOVIBALE/feat/vector-material-template-cache...HEAD
```

Expected: both commands exit 0.

## Task 4: Run semantic-first real SVG measurements

**Files:**

- Read: `/Users/min/Downloads/梵高星空款式西森猫猫.svg`
- Read: `/Users/min/Downloads/mmexport1784271438721.svg`
- Read: `/tmp/lumina-material-template-cache-head-serial-repeat.QKclwi/profile.json`
- Read: `/tmp/lumina-material-template-cache-head-parallel4.mwhwVM/profile.json`
- Read: `/tmp/lumina-material-template-cache-mmexport8-head.EDjy0r/profile.json`
- Read: `/tmp/lumina-material-template-cache-mmexport12-head.rXak0D/profile.json`
- Read: `/tmp/lumina-material-template-cache-mmexport15-head.Fqertu/profile.json`
- Add: `docs/superpowers/specs/2026-08-01-material-coherence-norm-fastpath-results.md`

The saved parent reports were produced immediately before this branch from
`554e7e97`. First verify each report exists and records the expected input
hash, material count, and external-reference match. If any is missing or has
unexpected metadata, rerun that parent case from a detached temporary
worktree rather than inventing a comparison.

### Step 1: Run the complex serial head case

```bash
LUMINA_VECTOR_PARALLELISM=1 LUMINA_MAX_WORKERS=1 \
  .venv/bin/python scripts/profile_converter_multicore.py \
  --kind vector --phase preview \
  --input /Users/min/Downloads/梵高星空款式西森猫猫.svg \
  --material-count 12 --runs 1 --no-cprofile \
  --reference-report \
    /tmp/lumina-material-template-cache-head-serial-repeat.QKclwi/profile.json \
  --output-dir /tmp/lumina-material-coherence-norm-head-serial
```

Expected: `reference_match=true` and semantic SHA-256 unchanged.

### Step 2: Run the complex four-worker head case

```bash
LUMINA_VECTOR_PARALLELISM=4 LUMINA_MAX_WORKERS=1 \
  .venv/bin/python scripts/profile_converter_multicore.py \
  --kind vector --phase preview \
  --input /Users/min/Downloads/梵高星空款式西森猫猫.svg \
  --material-count 12 --runs 1 --no-cprofile \
  --reference-report \
    /tmp/lumina-material-template-cache-head-parallel4.mwhwVM/profile.json \
  --output-dir /tmp/lumina-material-coherence-norm-head-parallel4
```

Expected: `reference_match=true` and the same semantic hash as serial.

### Step 3: Run 8-, 12-, and 15-material archive cases

Run:

```bash
LUMINA_VECTOR_PARALLELISM=1 LUMINA_MAX_WORKERS=1 \
  .venv/bin/python scripts/profile_converter_multicore.py \
  --kind vector --phase preview \
  --input /Users/min/Downloads/mmexport1784271438721.svg \
  --material-count 8 --runs 1 --no-cprofile \
  --reference-report \
    /tmp/lumina-material-template-cache-mmexport8-head.EDjy0r/profile.json \
  --output-dir /tmp/lumina-material-coherence-norm-mmexport8

LUMINA_VECTOR_PARALLELISM=1 LUMINA_MAX_WORKERS=1 \
  .venv/bin/python scripts/profile_converter_multicore.py \
  --kind vector --phase preview \
  --input /Users/min/Downloads/mmexport1784271438721.svg \
  --material-count 12 --runs 1 --no-cprofile \
  --reference-report \
    /tmp/lumina-material-template-cache-mmexport12-head.rXak0D/profile.json \
  --output-dir /tmp/lumina-material-coherence-norm-mmexport12

LUMINA_VECTOR_PARALLELISM=1 LUMINA_MAX_WORKERS=1 \
  .venv/bin/python scripts/profile_converter_multicore.py \
  --kind vector --phase preview \
  --input /Users/min/Downloads/mmexport1784271438721.svg \
  --material-count 15 --runs 1 --no-cprofile \
  --reference-report \
    /tmp/lumina-material-template-cache-mmexport15-head.Fqertu/profile.json \
  --output-dir /tmp/lumina-material-coherence-norm-mmexport15
```

Every run must exit 0 with `reference_match=true`.

### Step 4: Apply the retain/reject rule

Retain the implementation only when all of the following are true:

1. all semantic hashes match the parent exactly;
2. serial and four-worker results match each other;
3. focused and related tests pass;
4. the paired complex-SVG samples show a useful runtime trade-off without a
   material peak-RSS regression.

If semantics differ, revert the production/test commits and record rejection.
If timings are neutral or noisy, rerun one paired sample before deciding. Do
not weaken semantic checks to keep a speedup.

### Step 5: Write the results record

Record:

- baseline and head commits;
- exact commands and environment;
- material-solve, total preview, and peak-RSS values;
- semantic hashes for complex serial/four-worker and 8/12/15 materials;
- tests and quality gates;
- retained and deferred ideas;
- machine-specific limitations.

## Task 5: Final governance and checkpoint

**Files:**

- Modify: `docs/superpowers/specs/2026-08-01-material-coherence-norm-fastpath-design.md`
- Add: `docs/superpowers/specs/2026-08-01-material-coherence-norm-fastpath-results.md`

### Step 1: Run the logging smoke gate

```bash
.venv/bin/python scripts/log_quality_check.py --mode fast
```

Expected: PASS under the current script thresholds. Do not weaken the INFO,
warning, or error budgets.

### Step 2: Run final diff checks

```bash
git status --short
git diff --check MOVIBALE/feat/vector-material-template-cache...HEAD
git diff --stat MOVIBALE/feat/vector-material-template-cache...HEAD
```

Review the complete child-branch diff and confirm no unrelated files are
present.

### Step 3: Mark the design decision and commit evidence

If retained:

```bash
git add \
  docs/superpowers/specs/2026-08-01-material-coherence-norm-fastpath-design.md \
  docs/superpowers/specs/2026-08-01-material-coherence-norm-fastpath-results.md
git commit -m "docs(perf): verify exact coherence norm fast path"
```

If rejected, retain only the design/results research record and explicitly
state why the production experiment was removed.

### Step 4: Request independent review before any PR action

Use the repository's verification-before-completion and requesting-code-review
skills. Do not push, open a PR, or alter an existing PR until the user asks.
