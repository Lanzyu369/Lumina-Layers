# Material Neighbor Distance Reuse Design

**Date:** 2026-08-01
**Parent:** `MOVIBALE/feat/vector-material-coherence-fastpath` at `51a4ac42`
**Branch:** `MOVIBALE/feat/vector-material-pair-distance-reuse`
**Status:** Approved for a guarded experiment

## Outcome Sought

Reduce repeated work in the exact neighbor-coherence loop for very complex
SVGs without changing neighbor membership, pair order, candidate order,
refinement decisions, matched colours, material recipes, geometry, or export
artifacts. There is no fixed percentage target. The experiment is retained
only when it produces a useful measured improvement and all semantic gates
remain exact.

## Profile Evidence

The saved post-fast-path cProfile still recorded about 7.37 million neighbor
pairs. For every accepted pair, `_iter_neighbor_pairs` already computes the
strict-threshold Euclidean distance as part of a vectorized row calculation.
`_neighbor_coherence_refine` then recreates the same source difference and
computes its norm again through `_real_vector_norm`.

That duplicate source norm accounts for roughly half of the remaining 14.9
million exact three-vector norm calls. A local 800,000-vector microbenchmark
showed that the current vectorized-distance-plus-per-pair-dot pattern was
dominated by the per-pair Python/C dispatch. The microbenchmark is directional
evidence only; the retain decision must come from real SVG profiles.

## Considered Approaches

### A. Yield the already-computed exact distance (selected)

Add a private iterator that yields `(row, column, distance)` from the existing
strict-threshold calculation. Keep `_iter_neighbor_pairs` as a compatibility
wrapper that drops the distance. The coherence loop consumes the distance as
the source norm.

Advantages:

- removes one repeated norm dispatch per neighbor pair;
- preserves the current KD-tree query, strict threshold, row-major pair order,
  and bounded row storage;
- keeps diagnostics and existing private callers on the pair-only interface;
- adds no new cache or cross-request state.

Risk:

- the discovery distance is calculated by the existing vectorized
  `sqrt(sum(difference * difference))` path, while the parent coherence loop
  recalculates it as `sqrt(vector.dot(vector))`. They are bitwise equal for the
  current real float64 three-vector domain and NumPy 2.4.6 measurements, but
  NumPy is not pinned and other builds must not be assumed equivalent.

Mitigation:

- a bitwise regression compares yielded distances with the parent norm over
  deterministic random, edge-scale, strict-threshold, and real-Lab-shaped
  inputs;
- the complete neighbor-coherence suite remains unchanged except for the
  expected removal of the duplicate source-norm call;
- real parent/head semantic snapshots must match for the 9,503-colour SVG,
  8/12/15-material archive previews, and one final generate case containing
  geometry, scene instances, 3MF members, and GLB output;
- any mismatch rejects the optimization rather than weakening comparison.

### B. Recompute dot norms inside neighbor discovery (rejected)

The iterator could calculate `sqrt(vector.dot(vector))` once per pair and pass
that value onward. This preserves the parent's norm operation exactly, but it
still performs one Python-level dot dispatch per pair and therefore does not
remove the measured cost. Moving the same call earlier is not an optimization.

### C. Replace exact Top-K or neighbor discovery algorithms (deferred)

KD-tree Top-K, approximate nearest neighbors, pair reordering, and batching can
produce larger theoretical gains. They can also change tie selection, material
recipe order, or mutation order. Those are separate algorithm changes and do
not belong in this exact reuse experiment.

## Detailed Design

1. Introduce `_iter_neighbor_pairs_with_distances` beside the current helper.
2. Reuse the current target conversion, KD-tree query, sorted indices,
   difference array, distance calculation, and strict `< threshold` mask.
3. Zip the masked indices with the matching masked distances using
   `strict=True`; yield Python integer indices and the NumPy floating scalar.
4. Implement `_iter_neighbor_pairs` as a pair-only wrapper over the new helper.
5. Make `_neighbor_coherence_refine` consume triples and assign the yielded
   value to `d_src_norm`; keep `d_src`, cosine products, logs, comparisons,
   candidate iteration, state mutation, and tie handling unchanged.
6. Do not change public APIs, worker policy, logging, or memory budgets.

## Acceptance and Rejection

Retain only if all of these hold:

- focused tests prove bitwise distance parity and exactly two remaining norm
  calls in the controlled reverse-direction pair;
- the related material/vector suite passes;
- the complex SVG parent/head semantic snapshots are exactly equal in serial
  and four-worker modes;
- 8/12/15-material archive previews match their parent reports;
- a 12-material generate pair matches geometry, instances, 3MF, and GLB;
- paired complex-SVG timing shows a useful improvement without a stable peak
  memory regression.

If timing is neutral, rerun one immediate parent/head pair. If semantics differ
or the gain remains noise, remove the production/test experiment and retain
only the research record.

