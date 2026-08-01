# Material Coherence Exact Norm Fast Path Design

**Date:** 2026-08-01
**Status:** Approved for implementation
**Parent:** `MOVIBALE/feat/vector-material-template-cache` at `554e7e97`
**Branch:** `MOVIBALE/feat/vector-material-coherence-fastpath`

## Goal

Reduce the next measured material-solve hotspot for SVGs with millions of
nearby colour pairs while preserving matched RGB, recipes, material matrices,
geometry, and exported-model semantics exactly. Performance remains
evidence-driven; no fixed percentage target is required.

## Fresh Profile Evidence

After deterministic recipe-template reuse, the supplied 9,503-colour SVG
still generated about 7.37 million neighbour-pair iterations. The profile
recorded about 14.95 million calls to `numpy.linalg.norm`, with about 18.6
seconds cumulative in that wrapper path.

Every affected call receives a real, finite, one-dimensional float64 vector of
length three. NumPy's fast path for this case performs:

1. `asarray` and dtype/type checks;
2. a `ravel(order="K")` operation;
3. `vector.dot(vector)`; and
4. `sqrt` of the scalar result.

The first three checks are repeated millions of times even though the caller
already constructs the required array shape and dtype.

## Considered Approaches

### 1. Exact real-vector norm fast path — selected

Add a private helper for the known float64 one-dimensional case that performs
the same `dot` then `sqrt` operations as NumPy's current fast path. Use it only
inside neighbour-coherence processing, and reuse the already computed source
norm when the same vector is negated for the opposite direction.

This removes generic dispatch and one redundant norm without changing any
algorithmic choice, candidate set, pair order, or floating-point operation
order.

### 2. Replace blockwise Top-K with `cKDTree.query` — deferred

An exact KD-tree could avoid the large `cdist` plus `argpartition` path, but
equal-distance candidates are common and SciPy may choose a different recipe
among ties. Equal colours with different recipes are not semantically
equivalent for Lumina, so this requires a separate deterministic tie design.

### 3. Vectorize or reorder neighbour pairs — deferred

Batching pair calculations could remove more Python overhead, but accepted
refinements update `matched_lab`, `new_de`, and the refined mask in
lexicographic pair order. Reordering or snapshotting those decisions can
change later recipes and would require substantially broader proof.

## Design

Add one private helper in `core/material_cache.py`:

```python
def _real_vector_norm(vector: np.ndarray) -> np.floating:
    return np.sqrt(vector.dot(vector))
```

The helper is deliberately narrow: callers already provide real float64 1-D
vectors, so it does not reproduce NumPy's general matrix, complex, axis,
object-dtype, or casting behavior.

Within `_neighbor_coherence_refine`:

- replace the source, matched, and candidate three-vector `np.linalg.norm`
  calls with `_real_vector_norm`;
- set `d_src_to_adjust_norm = d_src_norm`, because negation does not change the
  dot product or square root;
- retain existing `np.dot` calls for cross-vector cosine products;
- retain all thresholds, logarithms, comparisons, loop order, mutations, and
  first-best tie behavior unchanged.

No public API, configuration, serialization, parallelism, logging, or cache
schema changes are introduced.

## Exactness Contract

- The helper uses the same real 1-D `dot` then `sqrt` operations as the local
  NumPy implementation.
- The input vectors are produced by float64 Lab subtraction and remain shape
  `(3,)`.
- Positive and negated vectors have the same elementwise squares, dot result,
  and norm.
- Tests compare the uint64 bit pattern of the helper result with
  `np.linalg.norm` for deterministic random vectors and edge cases.
- Existing serial/parallel neighbour-coherence tests must remain exactly equal.
- The full 9,503-colour semantic snapshot must match the parent reference.

## Verification

1. Add a failing unit test for the missing helper and bitwise parity.
2. Add an orchestration test proving the opposite-direction branch reuses the
   source norm rather than calling the helper again.
3. Run material-cache, candidate-cache, inverse-refinement, vector-matcher, and
   material-archive pipeline regressions.
4. Run the 9,503-colour SVG in serial and four-worker modes against the parent
   semantic report.
5. Compare material-solve time and peak RSS with fresh paired parent runs.
6. Retain the change only if exact semantic checks pass and timing shows a
   useful trade-off; otherwise revert it while keeping this research record.

## Scope Boundary

This change does not optimize Top-K selection, change neighbour discovery,
alter pair ordering, batch decision updates, or touch geometry parsing. Those
remain independent measured follow-ups.
