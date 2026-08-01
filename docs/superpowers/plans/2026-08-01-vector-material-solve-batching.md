# Vector Material Solve Batching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Batch target-colour inverse refinement inside each shared material workspace without changing any matched colour, recipe, material matrix, geometry, or exported model semantics.

**Architecture:** Keep deterministic material-subset grouping and immutable workspace reuse. Add a memory-bounded block kernel that flattens exact KD-tree queries in row-major candidate order, evaluates candidates in vectorized NumPy calls, and restores stable per-row results. Split the caller's existing parallelism budget between independent workspace groups and exact KD-tree query workers so nested fan-out never exceeds the admitted budget.

**Tech Stack:** Python 3.11+, NumPy, SciPy `cKDTree`, `ThreadPoolExecutor`, pytest, existing converter profiling and semantic-hash harnesses.

---

## File Map

- Modify `core/material_inverse_refinement.py`: block sizing, exact batched row kernel, bounded worker allocation, and group integration.
- Modify `tests/test_material_inverse_refinement_unit.py`: exact oracle comparisons, mixed-result blocks, block boundaries, and worker-budget tests.
- Create `docs/superpowers/specs/2026-08-01-vector-material-solve-batching-results.md`: record fresh correctness, timing, memory, and retained/rejected decision evidence.
- Use `scripts/profile_converter_multicore.py` unchanged as the end-to-end semantic and performance harness.

### Task 1: Lock exact block semantics with a failing oracle test

**Files:**
- Modify: `tests/test_material_inverse_refinement_unit.py`
- Test: `tests/test_material_inverse_refinement_unit.py`

- [ ] **Step 1: Add a helper that creates a shared-workspace multi-row fixture**

```python
def _shared_workspace_fixture():
    target_recipes = np.asarray(
        [
            [0, 1, 1, 2],
            [3, 1, 0, 2],
            [1, 3, 2, 0],
            [2, 2, 2, 2],
            [0, 0, 0, 0],
        ],
        dtype=np.int32,
    )
    targets = np.vstack([_srgb_for_recipe(row) for row in target_recipes])
    baseline_recipes = np.zeros((len(targets), 4), dtype=np.int32)
    baseline_matched = np.vstack(
        [_srgb_for_recipe(row) for row in baseline_recipes]
    )
    baseline_delta = np.asarray(
        [
            _delta_e(targets[index], baseline_matched[index])
            for index in range(len(targets))
        ],
        dtype=np.float64,
    )
    config = MaterialInverseRefinementConfig(
        max_refine_materials=4,
        max_refine_bottom_prefixes=16,
        max_refine_top_suffixes=16,
        refine_bottom_neighbors=2,
    )
    key = inverse_refinement._workspace_key(
        subset=np.arange(4, dtype=np.int32),
        layer_count=4,
        config=config,
    )
    workspace = inverse_refinement._build_workspace(
        key=key,
        materials=PALETTE,
        layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
        substrate="white",
    )
    return targets, baseline_recipes, baseline_matched, baseline_delta, config, workspace
```

- [ ] **Step 2: Add the failing exact-oracle and mixed-result test**

```python
def test_workspace_row_block_matches_one_row_reference_exactly() -> None:
    (
        targets,
        baseline_recipes,
        _baseline_matched,
        baseline_delta,
        config,
        workspace,
    ) = _shared_workspace_fixture()
    expected = [
        inverse_refinement._best_refined_row_with_workspace(
            target_srgb=targets[index],
            materials=PALETTE,
            layer_count=4,
            layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
            substrate="white",
            baseline_recipe=baseline_recipes[index],
            baseline_delta_e=float(baseline_delta[index]),
            config=config,
            workspace=workspace,
        )
        for index in range(len(targets))
    ]

    actual = inverse_refinement._refine_workspace_row_block(
        row_indices=tuple(range(len(targets))),
        targets=targets,
        baseline_recipes=baseline_recipes,
        baseline_delta_e=baseline_delta,
        materials=PALETTE,
        layer_count=4,
        layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
        substrate="white",
        config=config,
        workspace=workspace,
        query_workers=1,
    )

    assert len(actual) == len(expected)
    for row_index, expected_row in enumerate(expected):
        actual_index, actual_rgb, actual_recipe, actual_delta, actual_improved = actual[row_index]
        assert actual_index == row_index
        np.testing.assert_array_equal(actual_rgb, expected_row[0])
        np.testing.assert_array_equal(actual_recipe, expected_row[1])
        assert actual_delta == expected_row[2]
        assert actual_improved == expected_row[3]


def test_workspace_row_block_retains_baseline_when_no_suffix_is_valid() -> None:
    (
        targets,
        baseline_recipes,
        baseline_matched,
        baseline_delta,
        config,
        workspace,
    ) = _shared_workspace_fixture()
    invalid_workspace = inverse_refinement._InverseRefinementWorkspace(
        bottom_recipes=workspace.bottom_recipes,
        top_recipes=workspace.top_recipes,
        bottom_linear=workspace.bottom_linear,
        top_alpha=np.zeros_like(workspace.top_alpha),
        top_beta=np.full_like(workspace.top_beta, 2.0),
        bottom_tree=workspace.bottom_tree,
    )

    actual = inverse_refinement._refine_workspace_row_block(
        row_indices=(0, 1),
        targets=targets,
        baseline_recipes=baseline_recipes,
        baseline_delta_e=baseline_delta,
        materials=PALETTE,
        layer_count=4,
        layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
        substrate="white",
        config=config,
        workspace=invalid_workspace,
        query_workers=1,
    )

    for position, (_row_index, rgb, recipe, delta, improved) in enumerate(actual):
        np.testing.assert_array_equal(rgb, baseline_matched[position])
        np.testing.assert_array_equal(recipe, baseline_recipes[position])
        assert delta == baseline_delta[position]
        assert not improved
```

- [ ] **Step 3: Run the test and confirm the missing block kernel fails**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_material_inverse_refinement_unit.py::test_workspace_row_block_matches_one_row_reference_exactly \
  tests/test_material_inverse_refinement_unit.py::test_workspace_row_block_retains_baseline_when_no_suffix_is_valid -v
```

Expected: FAIL with `AttributeError` for `_refine_workspace_row_block`.

- [ ] **Step 4: Commit the failing test**

```bash
git add tests/test_material_inverse_refinement_unit.py
git commit -m "test(perf): lock batched material refinement parity"
```

### Task 2: Implement the exact batched row kernel

**Files:**
- Modify: `core/material_inverse_refinement.py`
- Test: `tests/test_material_inverse_refinement_unit.py`

- [ ] **Step 1: Add the exact-query compatibility wrapper**

```python
def _query_bottom_neighbors(
    *,
    workspace: _InverseRefinementWorkspace,
    required_bottom: np.ndarray,
    neighbor_count: int,
    workers: int,
) -> np.ndarray:
    query_kwargs = {
        "k": int(neighbor_count),
        "eps": 0.0,
        "workers": max(1, int(workers)),
    }
    try:
        _distances, indices = workspace.bottom_tree.query(
            required_bottom,
            **query_kwargs,
        )
    except TypeError:
        query_kwargs.pop("workers")
        _distances, indices = workspace.bottom_tree.query(
            required_bottom,
            **query_kwargs,
        )
    result = np.asarray(indices, dtype=np.int64)
    if int(neighbor_count) == 1:
        result = result[:, None]
    return result
```

- [ ] **Step 2: Add `_refine_workspace_row_block`**

Implement the function with this exact body after `_query_bottom_neighbors`:

```python
def _refine_workspace_row_block(
    *,
    row_indices: tuple[int, ...],
    targets: np.ndarray,
    baseline_recipes: np.ndarray,
    baseline_delta_e: np.ndarray,
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
    config: MaterialInverseRefinementConfig,
    workspace: _InverseRefinementWorkspace,
    query_workers: int,
) -> list[tuple[int, np.ndarray, np.ndarray, float, bool]]:
    if not row_indices:
        return []

    block_indices = np.asarray(row_indices, dtype=np.intp)
    block_targets = targets[block_indices]
    block_baseline_recipes = baseline_recipes[block_indices]
    block_baseline_delta = baseline_delta_e[block_indices]
    baseline_linear = _predict_linear_for_recipes(
        recipes=block_baseline_recipes,
        materials=materials,
        layer_height_mm=float(layer_height_mm),
        substrate=substrate,
    )
    baseline_srgb = linear_to_srgb_uint8(baseline_linear)
    results = [
        (
            int(row_index),
            baseline_srgb[position],
            block_baseline_recipes[position].copy(),
            float(block_baseline_delta[position]),
            False,
        )
        for position, row_index in enumerate(row_indices)
    ]

    target_linear = srgb_to_linear(block_targets)
    target_lab = rgb_to_lab(block_targets).astype(np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        required = (
            target_linear[:, None, :] - workspace.top_beta[None, :, :]
        ) / workspace.top_alpha[None, :, :]
    valid_mask = (
        np.isfinite(required).all(axis=2)
        & (required >= -float(config.required_color_tolerance)).all(axis=2)
        & (required <= 1.0 + float(config.required_color_tolerance)).all(axis=2)
    )
    valid_rows, valid_top_indices = np.nonzero(valid_mask)
    if valid_rows.size == 0:
        return results

    neighbor_count = min(
        max(1, int(config.refine_bottom_neighbors)),
        workspace.bottom_linear.shape[0],
    )
    bottom_indices = _query_bottom_neighbors(
        workspace=workspace,
        required_bottom=required[valid_rows, valid_top_indices],
        neighbor_count=neighbor_count,
        workers=query_workers,
    )
    final_linear = (
        workspace.top_alpha[valid_top_indices, None, :]
        * workspace.bottom_linear[bottom_indices]
        + workspace.top_beta[valid_top_indices, None, :]
    )
    flat_srgb = linear_to_srgb_uint8(final_linear.reshape(-1, 3))
    flat_lab = rgb_to_lab(flat_srgb).astype(np.float64)
    candidate_targets = np.repeat(
        target_lab[valid_rows],
        neighbor_count,
        axis=0,
    )
    candidate_delta = np.linalg.norm(flat_lab - candidate_targets, axis=1)
    valid_counts = np.bincount(valid_rows, minlength=len(row_indices))
    candidate_offsets = np.concatenate(
        [
            np.zeros((1,), dtype=np.int64),
            np.cumsum(valid_counts * neighbor_count, dtype=np.int64),
        ]
    )

    provisional_positions: list[int] = []
    provisional_recipes: list[np.ndarray] = []
    for position in range(len(row_indices)):
        start = int(candidate_offsets[position])
        stop = int(candidate_offsets[position + 1])
        if start == stop:
            continue
        best_flat = start + int(np.argmin(candidate_delta[start:stop]))
        if float(candidate_delta[best_flat]) >= float(block_baseline_delta[position]) - 1e-12:
            continue
        query_index, neighbor_index = divmod(best_flat, neighbor_count)
        bottom_index = int(bottom_indices[query_index, neighbor_index])
        top_index = int(valid_top_indices[query_index])
        provisional_positions.append(position)
        provisional_recipes.append(
            np.concatenate(
                [
                    workspace.bottom_recipes[bottom_index],
                    workspace.top_recipes[top_index],
                ]
            ).astype(np.int32, copy=False)
        )

    if not provisional_recipes:
        return results
    recipe_batch = np.stack(provisional_recipes).astype(np.int32, copy=False)
    verified_linear = _predict_linear_for_recipes(
        recipes=recipe_batch,
        materials=materials,
        layer_height_mm=float(layer_height_mm),
        substrate=substrate,
    )
    verified_srgb = linear_to_srgb_uint8(verified_linear)
    verified_lab = rgb_to_lab(verified_srgb).astype(np.float64)
    verified_delta = np.linalg.norm(
        verified_lab - target_lab[provisional_positions],
        axis=1,
    )
    for candidate_index, position in enumerate(provisional_positions):
        row_delta = float(verified_delta[candidate_index])
        if row_delta >= float(block_baseline_delta[position]) - 1e-12:
            continue
        results[position] = (
            int(row_indices[position]),
            verified_srgb[candidate_index],
            recipe_batch[candidate_index],
            row_delta,
            True,
        )
    return results
```

- [ ] **Step 3: Run the new exact-oracle test**

Run:

```bash
.venv/bin/python -m pytest tests/test_material_inverse_refinement_unit.py::test_workspace_row_block_matches_one_row_reference_exactly -v
```

Expected: PASS with exact RGB, recipe, float64 Delta-E, and improved flag.

- [ ] **Step 4: Run the full inverse-refinement suite**

Run:

```bash
.venv/bin/python -m pytest tests/test_material_inverse_refinement_unit.py -v
```

Expected: all tests PASS with no warning or error output.

- [ ] **Step 5: Commit the block kernel**

```bash
git add core/material_inverse_refinement.py tests/test_material_inverse_refinement_unit.py
git commit -m "perf(material): batch exact inverse refinement rows"
```

### Task 3: Add memory-bounded blocks and integrate the group path

**Files:**
- Modify: `core/material_inverse_refinement.py`
- Modify: `tests/test_material_inverse_refinement_unit.py`

- [ ] **Step 1: Add failing block-boundary coverage**

```python
def test_workspace_group_preserves_exact_rows_across_partial_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _shared_workspace_fixture()
    targets, baseline_recipes, _matched, baseline_delta, config, _workspace = fixture
    observed_blocks: list[tuple[int, ...]] = []
    original = inverse_refinement._refine_workspace_row_block

    def _record_block(**kwargs):
        observed_blocks.append(tuple(kwargs["row_indices"]))
        return original(**kwargs)

    monkeypatch.setattr(inverse_refinement, "_refinement_row_block_size", lambda **_kwargs: 2)
    monkeypatch.setattr(inverse_refinement, "_refine_workspace_row_block", _record_block)

    result = inverse_refinement._refine_workspace_group(
        key=inverse_refinement._workspace_key(
            subset=np.arange(4, dtype=np.int32), layer_count=4, config=config
        ),
        row_indices=tuple(range(len(targets))),
        targets=targets,
        baseline_recipes=baseline_recipes,
        baseline_delta_e=baseline_delta,
        materials=PALETTE,
        layer_count=4,
        layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
        substrate="white",
        config=config,
        query_workers=1,
    )

    assert observed_blocks == [(0, 1), (2, 3), (4,)]
    assert [row[0] for row in result] == [0, 1, 2, 3, 4]
```

- [ ] **Step 2: Run the boundary test and confirm it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_material_inverse_refinement_unit.py::test_workspace_group_preserves_exact_rows_across_partial_blocks -v
```

Expected: FAIL because `_refinement_row_block_size` and `query_workers` group integration do not exist.

- [ ] **Step 3: Implement derived block sizing**

Add `_REFINEMENT_TEMP_MEMORY_BUDGET_BYTES = 64 * 1024 * 1024` and:

```python
def _refinement_row_block_size(
    *,
    workspace: _InverseRefinementWorkspace,
    config: MaterialInverseRefinementConfig,
    row_count: int,
    memory_budget_bytes: int = _REFINEMENT_TEMP_MEMORY_BUDGET_BYTES,
) -> int:
    top_count = max(1, int(workspace.top_recipes.shape[0]))
    top_depth = int(workspace.top_recipes.shape[1])
    neighbors = min(
        max(1, int(config.refine_bottom_neighbors)),
        max(1, int(workspace.bottom_linear.shape[0])),
    )
    bytes_per_top = 97 + 4 * top_depth + 67 * neighbors
    estimated_row_bytes = max(1, top_count * bytes_per_top)
    return min(
        max(1, int(row_count)),
        max(1, int(memory_budget_bytes) // estimated_row_bytes),
    )
```

Update `_refine_workspace_group` to build the workspace once, derive the block
size, slice `row_indices` in order, and extend results with
`_refine_workspace_row_block(..., query_workers=query_workers)`.

- [ ] **Step 4: Run boundary and inverse-refinement tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_material_inverse_refinement_unit.py -v
```

Expected: all tests PASS and observed blocks equal `[(0, 1), (2, 3), (4,)]`.

- [ ] **Step 5: Commit memory-bounded integration**

```bash
git add core/material_inverse_refinement.py tests/test_material_inverse_refinement_unit.py
git commit -m "perf(material): bound inverse refinement row batches"
```

### Task 4: Share one parallelism budget across groups and queries

**Files:**
- Modify: `core/material_inverse_refinement.py`
- Modify: `tests/test_material_inverse_refinement_unit.py`

- [ ] **Step 1: Add failing worker-allocation coverage**

```python
@pytest.mark.parametrize(
    ("parallelism", "group_count", "expected"),
    [
        (1, 1, (1, 1)),
        (8, 1, (1, 8)),
        (8, 2, (2, 4)),
        (8, 3, (3, 2)),
        (4, 8, (4, 1)),
    ],
)
def test_refinement_worker_allocation_stays_within_budget(
    parallelism: int,
    group_count: int,
    expected: tuple[int, int],
) -> None:
    allocation = inverse_refinement._refinement_worker_allocation(
        parallelism=parallelism,
        group_count=group_count,
    )
    assert allocation == expected
    assert allocation[0] * allocation[1] <= max(1, parallelism)
```

- [ ] **Step 2: Run the allocation test and confirm it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_material_inverse_refinement_unit.py::test_refinement_worker_allocation_stays_within_budget -v
```

Expected: FAIL with `AttributeError` for `_refinement_worker_allocation`.

- [ ] **Step 3: Implement and adopt the allocation helper**

```python
def _refinement_worker_allocation(
    *,
    parallelism: int,
    group_count: int,
) -> tuple[int, int]:
    budget = max(1, int(parallelism))
    active_groups = min(budget, max(1, int(group_count)))
    query_workers = max(1, budget // active_groups)
    return active_groups, query_workers
```

Replace the current `worker_count` calculation with this helper. Pass the
returned `query_workers` through both threaded and serial group calls. Preserve
future submission order and owner-thread writeback order exactly.

- [ ] **Step 4: Add and run serial-versus-budget exact-parity coverage**

```python
def test_single_workspace_query_workers_preserve_serial_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets, baseline_recipes, baseline_matched, baseline_delta, config, _workspace = (
        _shared_workspace_fixture()
    )
    serial = refine_material_matches(
        target_srgb=targets,
        baseline_matched_srgb=baseline_matched,
        baseline_recipes=baseline_recipes,
        baseline_delta_e=baseline_delta,
        materials=PALETTE,
        layer_count=4,
        layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
        substrate="white",
        config=config,
        parallelism=1,
    )
    observed_workers: list[int] = []
    original_query = inverse_refinement._query_bottom_neighbors

    def _record_query_workers(**kwargs):
        observed_workers.append(int(kwargs["workers"]))
        return original_query(**kwargs)

    monkeypatch.setattr(
        inverse_refinement,
        "_query_bottom_neighbors",
        _record_query_workers,
    )
    parallel = refine_material_matches(
        target_srgb=targets,
        baseline_matched_srgb=baseline_matched,
        baseline_recipes=baseline_recipes,
        baseline_delta_e=baseline_delta,
        materials=PALETTE,
        layer_count=4,
        layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
        substrate="white",
        config=config,
        parallelism=4,
    )

    assert observed_workers and set(observed_workers) == {4}
    np.testing.assert_array_equal(parallel.matched_srgb, serial.matched_srgb)
    np.testing.assert_array_equal(parallel.recipes, serial.recipes)
    np.testing.assert_array_equal(parallel.delta_e, serial.delta_e)
    np.testing.assert_array_equal(parallel.improved_mask, serial.improved_mask)
```

Run:

```bash
.venv/bin/python -m pytest tests/test_material_inverse_refinement_unit.py -v
```

Expected: all tests PASS; worker allocation never exceeds its input budget.

- [ ] **Step 5: Commit bounded worker sharing**

```bash
git add core/material_inverse_refinement.py tests/test_material_inverse_refinement_unit.py
git commit -m "perf(material): share refinement worker budget"
```

### Task 5: Verify integration, quality, and measured value

**Files:**
- Create: `docs/superpowers/specs/2026-08-01-vector-material-solve-batching-results.md`
- Verify: `core/material_inverse_refinement.py`
- Verify: `tests/test_material_inverse_refinement_unit.py`

- [ ] **Step 1: Run focused material and vector regression suites**

```bash
.venv/bin/python -m pytest \
  tests/test_material_inverse_refinement_unit.py \
  tests/test_material_cache_unit.py \
  tests/test_material_candidate_cache_unit.py \
  tests/test_vector_material_matcher_unit.py \
  tests/test_pipeline_vector_material_archive_unit.py -v
```

Expected: zero failures, warnings, or errors.

- [ ] **Step 2: Run broader converter and profiler contract coverage**

```bash
.venv/bin/python -m pytest \
  tests/test_converter_multicore_profile_unit.py \
  tests/test_vector_engine_part2_5_unit.py \
  tests/test_performance_timing_response_unit.py -v
```

Expected: zero failures, warnings, or errors.

- [ ] **Step 3: Establish the serial semantic reference**

```bash
LUMINA_VECTOR_INNER_WORKERS=1 .venv/bin/python scripts/profile_converter_multicore.py \
  --kind vector \
  --phase preview \
  --input "/Users/min/Downloads/mmexport1784271438721.svg" \
  --material-count 12 \
  --runs 1 \
  --output-dir /tmp/lumina-material-batching-serial
```

Expected: a successful `profile.json` containing semantic hashes,
`material_solve_s`, and peak RSS.

- [ ] **Step 4: Run the admitted parallel comparison against the reference**

```bash
LUMINA_VECTOR_INNER_WORKERS=4 .venv/bin/python scripts/profile_converter_multicore.py \
  --kind vector \
  --phase preview \
  --input "/Users/min/Downloads/mmexport1784271438721.svg" \
  --material-count 12 \
  --runs 3 \
  --reference-report /tmp/lumina-material-batching-serial/profile.json \
  --output-dir /tmp/lumina-material-batching-parallel
```

Expected: all semantic hashes match the serial reference. Timing and memory
are evidence to record, not pass/fail thresholds.

- [ ] **Step 5: Run quality and repository hygiene gates**

```bash
.venv/bin/python scripts/log_quality_check.py --mode fast
git diff --check origin/dev-refactor...HEAD
git status --short
```

Expected: log-quality PASS, no whitespace errors, and only intentional files.

- [ ] **Step 6: Record the evidence and retain or revert the optimization**

Create the result document with exact commands, hardware/runtime context,
serial and parallel semantic hashes, material-solve timing samples, peak RSS,
test counts, and a plain decision:

- retain when exactness is proven and timing/memory show a useful trade-off;
- revert production code when the measured trade-off is neutral or worse,
  while retaining the design/results evidence explaining the rejection.

- [ ] **Step 7: Commit final evidence**

```bash
git add docs/superpowers/specs/2026-08-01-vector-material-solve-batching-results.md
git commit -m "docs(perf): record batched material solve evidence"
```
