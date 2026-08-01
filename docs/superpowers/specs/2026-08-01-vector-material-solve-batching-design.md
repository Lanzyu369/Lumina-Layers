# Vector Material Solve Batching Design

**Date:** 2026-08-01  
**Status:** Approved direction, implementation pending  
**Branch:** `MOVIBALE/feat/vector-material-solve-batching`

## Goal

Reduce material-solve time for SVGs with thousands of unique fill colours while
preserving the existing colour model and producing exactly the same matched
RGB values, recipes, material matrices, geometry, GLB, and 3MF semantics.
Performance results guide whether the change is retained; this work has no
pre-declared percentage target.

## Context

PR #533 already removed major repeated work: it deduplicates SVG fills, reuses
one immutable inverse-refinement workspace per material subset, streams exact
neighbour discovery, bounds top-K memory, and processes independent workspaces
in parallel. The remaining inverse-refinement loop still processes target rows
one at a time inside each shared workspace. When thousands of colours collapse
into only a few material-subset groups, the group count also limits useful
parallelism even on a high-core machine.

## Considered Approaches

### 1. Batch target rows inside each workspace — selected

Process a memory-bounded block of target colours through the existing affine
inverse search together. Reuse the same candidate arrays and KD-tree, submit
the block's exact nearest-neighbour queries together, and restore results in
the original row and candidate order.

This improves cold preview and cold generation, directly addresses the current
hot loop, and requires no public API or colour-model change. It also remains
useful when preview-analysis reuse is unavailable.

### 2. Persist preview solve results for generation — follow-up

Serialize the exact target-to-recipe table from preview and hydrate it during
generation when every material and solver key matches. This can remove a
second solve from preview-then-generate workflows, but it does not improve the
first solve and expands cache lifecycle and invalidation responsibilities.
It should remain a separate change after the single-solve algorithm is clear.

### 3. Move the row kernel to C++ or another native runtime — deferred

A native kernel may eventually reduce Python overhead, but it adds packaging,
platform, and numerical-reproducibility risk. It is justified only if fresh
profiling shows the batched NumPy/SciPy path still spends material time in the
Python row loop.

## Design

### Data flow

`refine_material_matches` keeps its current public signature and deterministic
material-subset grouping. For each group:

1. Build the immutable bottom/top candidate workspace once.
2. Derive a row-block size from a fixed temporary-memory budget, the top
   candidate count, recipe depth, and bottom-neighbour count.
3. Convert the block of target sRGB rows to linear RGB and Lab in one call.
4. Compute required bottom colours for all block rows and top suffixes.
5. Preserve each row's valid-top ordering, flatten only valid queries, and call
   `cKDTree.query` with `eps=0`.
6. Evaluate the same candidate combinations in the same per-row order.
7. Choose the first minimum exactly as the existing `np.argmin` path does,
   forward-verify the selected recipe, and retain the baseline unless the
   verified Delta-E is strictly better under the existing tolerance.
8. Return immutable row results; the owner writes them back in original input
   order.

No approximate index, reduced precision, changed candidate budget, or changed
colour formula is allowed.

### Parallelism

The caller-provided `parallelism` remains the total budget. Independent groups
continue to use outer threads. When there are fewer groups than the available
budget, each active group may give its exact batched KD-tree query an integer
share of the unused budget. The product of active group workers and per-query
workers must not exceed the caller's budget.

There is only one effective fan-out budget. NumPy/SciPy work must not create an
unbounded second layer of application threads, and `parallelism=1` remains a
fully serial reference path.

### Memory bounds

Batch size is derived rather than hard-coded. The estimate covers required
bottom colours, validity masks, neighbour indices, predicted linear RGB,
sRGB/Lab conversion, distances, and recipe-index bookkeeping. It is clamped to
at least one row, so unusually large candidate workspaces fall back to the
existing one-row memory shape instead of allocating an unbounded dense tensor.

Temporary arrays are released block by block. Candidate workspaces stay
read-only and are never copied per row.

### Determinism and failure behaviour

- All optical and distance calculations remain `float64` where they are
  currently `float64`.
- KD-tree queries stay exact (`eps=0`) and keep the current `k`.
- Valid suffixes and bottom neighbours retain their existing order.
- Ties keep the first candidate selected by the current row-local ordering.
- Every selected recipe still passes the same forward-model verification.
- Empty/invalid candidate sets retain the original baseline result.
- A block-size calculation failure or unsupported query-worker argument falls
  back to one-row, one-query-worker behaviour rather than changing output.

## Test Strategy

Implementation follows test-driven development.

1. Add a regression test that compares a multi-row batched group with the
   existing one-row reference for matched RGB, recipe, Delta-E, and improved
   mask using exact array equality.
2. Cover mixed rows: improved, baseline-retained, and no-valid-suffix results
   in the same block.
3. Cover block boundaries and prove stable row order when the final block is
   partial.
4. Compare `parallelism=1` with a larger budget for exact equality and verify
   that the allocated group/query worker product stays within the budget.
5. Run the existing inverse-refinement, material-cache, vector-matcher, vector
   pipeline, and converter profiler tests.
6. Profile the supplied complex SVG with 8, 12, and 15 material archives where
   practical. Compare semantic hashes first, then warm timing and peak RSS.
   Retain the optimization only when measured results show a useful trade-off.

## Scope Boundaries

This change does not alter preview-to-generate cache schemas, material optical
parameters, candidate generation, neighbour-coherence semantics, public API
schemas, UI settings, or model/export code. Any exact solve-result handoff or
native-kernel experiment will use a separate design and branch.
