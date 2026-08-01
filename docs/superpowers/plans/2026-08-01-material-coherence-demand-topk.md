# Material Coherence Demand Top-K Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute exact material-coherence Top-K rows only when the serial loop
demands them while retaining the current eager parallel path and every semantic
output.

**Architecture:** Add one private request-local exact row cache that delegates
to the existing one-row `cdist` plus NumPy `argpartition` primitive. Select it
only for effective parallelism one; keep the current memory-bounded blockwise
helper for multi-worker execution.

**Tech Stack:** Python 3.12, NumPy 2.4.6, SciPy, pytest, existing converter
profile and semantic-snapshot harness.

---

### Task 1: Lock demand and parallel dispatch contracts

**Files:**
- Modify: `tests/test_material_neighbor_coherence_unit.py`

- [ ] **Step 0: Move the controlled serial candidate stub**

In `test_neighbor_coherence_reuses_source_norm_for_reverse_direction`, move
the one-row candidate result from `_top_k_candidate_rows_blockwise` to
`_top_k_candidate_block`. This keeps the controlled distance at `1.0` when the
serial implementation starts requesting exact rows on demand. Before the
production change, this migration also contributes to RED because the old
serial path ignores the new stub.

- [ ] **Step 1: Write the failing serial-demand regression**

Add a test that first records the eager reference from `_coherence_fixture`,
then rejects any call to `_top_k_candidate_rows_blockwise` during a serial run
and records `_top_k_candidate_block` calls:

```python
def test_serial_coherence_computes_top_k_rows_once_on_demand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _coherence_fixture()
    expected = _neighbor_coherence_refine(**fixture, parallelism=4)
    real_block = material_cache_module._top_k_candidate_block
    observed_targets: list[bytes] = []

    def _recording_block(
        target_block: np.ndarray,
        candidate_lab: np.ndarray,
        top_k: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        assert target_block.shape == (1, 3)
        observed_targets.append(target_block.tobytes())
        return real_block(target_block, candidate_lab, top_k)

    monkeypatch.setattr(
        material_cache_module,
        "_top_k_candidate_rows_blockwise",
        lambda **_kwargs: pytest.fail("serial path must not compute every row"),
    )
    monkeypatch.setattr(
        material_cache_module,
        "_top_k_candidate_block",
        _recording_block,
    )

    actual = _neighbor_coherence_refine(**fixture, parallelism=1)

    assert len(observed_targets) == 6
    assert len(set(observed_targets)) == len(observed_targets)
    for actual_array, expected_array in zip(actual, expected, strict=True):
        np.testing.assert_array_equal(actual_array, expected_array)
```

- [ ] **Step 2: Add the eager parallel-path regression**

Wrap `_top_k_candidate_rows_blockwise`, run the same fixture with four workers,
and require the wrapper to observe `parallelism=4` exactly once while the
complete output matches a serial reference.

```python
def test_parallel_coherence_keeps_eager_blockwise_top_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _coherence_fixture()
    expected = _neighbor_coherence_refine(**fixture, parallelism=1)
    real_blockwise = material_cache_module._top_k_candidate_rows_blockwise
    observed_parallelism: list[int] = []

    def _recording_blockwise(**kwargs: Any) -> tuple[np.ndarray, np.ndarray]:
        observed_parallelism.append(int(kwargs["parallelism"]))
        return real_blockwise(**kwargs)

    monkeypatch.setattr(
        material_cache_module,
        "_top_k_candidate_rows_blockwise",
        _recording_blockwise,
    )

    actual = _neighbor_coherence_refine(**fixture, parallelism=4)

    assert observed_parallelism == [4]
    for actual_array, expected_array in zip(actual, expected, strict=True):
        np.testing.assert_array_equal(actual_array, expected_array)
```

- [ ] **Step 3: Add duplicate-candidate complete-output parity**

Copy `_coherence_fixture`, append duplicate candidate Lab, sRGB, and recipe
rows in the same order to all three candidate arrays, then compare complete
serial and four-worker results with `np.testing.assert_array_equal`.

```python
def test_serial_coherence_preserves_duplicate_candidate_ties() -> None:
    fixture = _coherence_fixture()
    duplicated = dict(fixture)
    for key in ("all_lab", "all_srgb", "all_recipes"):
        values = np.asarray(fixture[key])
        duplicated[key] = np.concatenate((values, values[:9]), axis=0)

    expected = _neighbor_coherence_refine(**duplicated, parallelism=4)
    actual = _neighbor_coherence_refine(**duplicated, parallelism=1)

    for actual_array, expected_array in zip(actual, expected, strict=True):
        np.testing.assert_array_equal(actual_array, expected_array)
```

- [ ] **Step 4: Run RED and confirm the intended failure**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_material_neighbor_coherence_unit.py::test_serial_coherence_computes_top_k_rows_once_on_demand \
  -q
```

Expected: FAIL because the current serial implementation invokes
`_top_k_candidate_rows_blockwise` before the pair loop.

- [ ] **Step 5: Commit the failing tests**

```bash
git add tests/test_material_neighbor_coherence_unit.py
git commit -m "test(materials): lock demand-driven exact top-k"
```

### Task 2: Implement the exact serial row cache

**Files:**
- Modify: `core/material_cache.py`
- Test: `tests/test_material_neighbor_coherence_unit.py`

- [ ] **Step 1: Add `_ExactTopKRowCache`**

Add a private dataclass beside `_top_k_candidate_rows_blockwise`. It keeps
preallocated `np.intp` indices, float64 distances, and a readiness vector. Its
`get` method must call the existing primitive exactly as follows:

```python
@dataclass
class _ExactTopKRowCache:
    """Request-local exact Top-K rows for serial coherence refinement."""

    target_lab: np.ndarray
    candidate_lab: np.ndarray
    top_k: int
    indices: np.ndarray
    distances: np.ndarray
    ready: np.ndarray

    @classmethod
    def create(
        cls,
        *,
        target_lab: np.ndarray,
        candidate_lab: np.ndarray,
        top_k: int,
    ) -> "_ExactTopKRowCache":
        targets = np.asarray(target_lab)
        candidates = np.asarray(candidate_lab)
        effective_top_k = min(max(0, int(top_k)), candidates.shape[0])
        return cls(
            target_lab=targets,
            candidate_lab=candidates,
            top_k=effective_top_k,
            indices=np.empty(
                (targets.shape[0], effective_top_k),
                dtype=np.intp,
            ),
            distances=np.empty(
                (targets.shape[0], effective_top_k),
                dtype=np.float64,
            ),
            ready=np.zeros(targets.shape[0], dtype=bool),
        )

    def get(self, row_index: int) -> tuple[np.ndarray, np.ndarray]:
        if not self.ready[row_index]:
            block_indices, block_distances = _top_k_candidate_block(
                self.target_lab[row_index : row_index + 1],
                self.candidate_lab,
                self.top_k,
            )
            self.indices[row_index] = block_indices[0]
            self.distances[row_index] = block_distances[0]
            self.ready[row_index] = True
        return self.indices[row_index], self.distances[row_index]
```

- [ ] **Step 2: Select serial cache versus eager arrays once**

In `_neighbor_coherence_refine`, replace unconditional Top-K materialization
with:

```python
topk_row_cache: _ExactTopKRowCache | None = None
topk_indices: np.ndarray | None = None
topk_distances: np.ndarray | None = None
if int(parallelism) <= 1:
    topk_row_cache = _ExactTopKRowCache.create(
        target_lab=target_lab,
        candidate_lab=all_lab,
        top_k=top_k,
    )
else:
    topk_indices, topk_distances = _top_k_candidate_rows_blockwise(
        target_lab=target_lab,
        candidate_lab=all_lab,
        top_k=top_k,
        block_size=candidate_block_size,
        parallelism=parallelism,
    )
```

- [ ] **Step 3: Retrieve both candidate rows without changing decisions**

At the current `adjust_idx` access point, call `topk_row_cache.get(adjust_idx)`
for serial execution; otherwise index the non-optional eager arrays. Keep the
candidate loop and every comparison below it byte-for-byte unchanged.

```python
if topk_row_cache is not None:
    cand_indices, cand_des = topk_row_cache.get(adjust_idx)
else:
    assert topk_indices is not None
    assert topk_distances is not None
    cand_indices = topk_indices[adjust_idx]
    cand_des = topk_distances[adjust_idx]
cand_labs = all_lab[cand_indices]
```

- [ ] **Step 4: Run GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_material_neighbor_coherence_unit.py -q
```

Expected: all coherence tests pass, including the new demand, parallel, and
duplicate-tie regressions.

- [ ] **Step 5: Commit the implementation**

```bash
git add core/material_cache.py tests/test_material_neighbor_coherence_unit.py
git commit -m "perf(materials): compute serial coherence top-k on demand"
```

### Task 3: Prove surrounding contracts

**Files:**
- Verify: `core/material_cache.py`
- Verify: `tests/test_material_neighbor_coherence_unit.py`

- [ ] **Step 1: Run the related backend suite**

```bash
.venv/bin/python -m pytest \
  tests/test_material_neighbor_coherence_unit.py \
  tests/test_material_candidate_cache_unit.py \
  tests/test_material_inverse_refinement_unit.py \
  tests/test_material_cache_unit.py \
  tests/test_vector_material_matcher_unit.py \
  tests/test_pipeline_vector_material_archive_unit.py \
  tests/test_task_parallelism_unit.py \
  tests/test_converter_multicore_profile_unit.py \
  tests/test_performance_timing_response_unit.py -q
```

Expected: PASS with no fixed test-count assumption.

- [ ] **Step 2: Run syntax and whitespace checks**

```bash
.venv/bin/python -m py_compile \
  core/material_cache.py tests/test_material_neighbor_coherence_unit.py
git diff --check b8cd20f9...HEAD
```

Expected: both commands exit zero.

### Task 4: Run real semantic and performance gates

**Files:**
- Create: `docs/superpowers/specs/2026-08-01-material-coherence-demand-topk-results.md`
- Create: `progress/material-coherence-demand-topk-evidence.json`

- [ ] **Step 1: Profile the 9,503-colour SVG in serial**

Run immediate parent/head pairs with `LUMINA_VECTOR_PARALLELISM=1`, one run per
fresh process, and require the head to accept the parent `profile.json` through
`--reference-report`.

- [ ] **Step 2: Profile the same SVG with four workers**

Repeat with `LUMINA_VECTOR_PARALLELISM=4` to prove the retained eager path and
semantic reference. Reverse one pair's order if timings are close.

- [ ] **Step 3: Verify the supplied 8/12/15-material archive cases**

Run `mmexport1784271438721.svg` previews at 8, 12, and 15 materials against
parent semantic reports.

- [ ] **Step 4: Verify final generation**

Run one 12-material generate pair and compare the full canonical snapshot,
including material arrays, all geometry and scene instances, decompressed 3MF
members, and GLB.

- [ ] **Step 5: Record evidence without overstating it**

Write exact commits, commands, timing distributions, memory observations,
semantic hashes, dependency versions, and unsupported-machine limitations to
the result document and compact JSON manifest.

### Task 5: Final verification and checkpoint

**Files:**
- Verify all changed files

- [ ] **Step 1: Run logging and final diff gates**

```bash
.venv/bin/python scripts/log_quality_check.py --mode fast
git diff --check b8cd20f9...HEAD
git status --short
```

- [ ] **Step 2: Request independent code review**

Use the repository review workflow on the exact final SHA. Resolve only
Critical or Important findings within this scope.

- [ ] **Step 3: Create a local rollback pointer**

After every verification command passes and review is Ready, create
`backup/2026-08-01-material-demand-topk-reviewed` at the verified tip. Do not
push or open a PR unless the user asks.
