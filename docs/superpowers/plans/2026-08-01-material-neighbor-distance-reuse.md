# Material Neighbor Distance Reuse Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to
> implement this plan task-by-task.

**Goal:** Reuse the exact distance already computed during strict neighbor
discovery so the coherence loop does not recalculate one source norm for each
of millions of pairs.

**Architecture:** Add one private distance-yielding iterator, retain the
pair-only iterator as a compatibility wrapper, and adopt the distance only in
the coherence loop. Preserve all query, ordering, threshold, candidate, and
mutation semantics.

**Tech Stack:** Python 3.12, NumPy 2.4.6, SciPy, pytest, existing converter
profile and semantic-snapshot harness.

---

## Task 1: Lock the distance and orchestration contracts

**Files:**

- Modify: `tests/test_material_neighbor_coherence_unit.py`

1. Add a test for `_iter_neighbor_pairs_with_distances` using deterministic
   random Lab-like values, exact-threshold examples, zeros, and edge scales.
   Compare pair indices with the legacy implementation and compare every
   yielded distance bitwise with `_real_vector_norm(target[j] - target[i])`.
2. Update the controlled reverse-direction test to patch the new triple
   iterator and require exactly two norm-helper calls: matched direction and
   candidate direction. The supplied source distance must not be recomputed.
3. Run the focused tests before production code and confirm failure because
   the new helper is absent or unused.
4. Commit the failing contract tests.

## Task 2: Implement the narrow reuse path

**Files:**

- Modify: `core/material_cache.py`
- Test: `tests/test_material_neighbor_coherence_unit.py`

1. Move the current neighbor-discovery body to
   `_iter_neighbor_pairs_with_distances` and yield each valid distance with its
   indices.
2. Rebuild `_iter_neighbor_pairs` as a wrapper that yields only `(i, j)`.
3. Switch `_neighbor_coherence_refine` to the triple iterator and reuse the
   yielded source norm. Change no other arithmetic or decision order.
4. Run focused tests, then the complete coherence test file.
5. Commit the implementation.

## Task 3: Prove surrounding contracts

Run:

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

.venv/bin/python -m py_compile \
  core/material_cache.py tests/test_material_neighbor_coherence_unit.py
git diff --check MOVIBALE/feat/vector-material-coherence-fastpath...HEAD
```

Expected: all commands pass. Do not rely on a fixed test count.

## Task 4: Run real semantic and performance gates

1. From parent `51a4ac42`, record fresh complex SVG serial and four-worker
   preview profiles with `/usr/bin/time -l` for the four-worker pair.
2. Run the head against each parent report through `--reference-report`.
3. Run head previews for the supplied archive SVG at 8, 12, and 15 materials
   against the retained parent reports.
4. Run one 12-material generate case and compare its full canonical snapshot,
   including geometry, instances, 3MF members, and GLB.
5. Profile the retained head once with cProfile to confirm the source-norm call
   count was actually removed and identify the next hotspot without changing
   it in this branch.

## Task 5: Decide, record, and checkpoint

1. Apply the design's semantic-first retain/reject rule.
2. Add a results document with exact commits, environment, commands, timings,
   memory, semantic hashes, and limitations.
3. Retain a compact evidence manifest with report hashes and semantic
   snapshots; state that v2 reports do not self-authenticate Git commits.
4. Run `scripts/log_quality_check.py --mode fast` and final diff checks.
5. Request independent code review.
6. If Ready, create a local backup branch at the verified tip. Do not push or
   open a PR unless the user asks.

