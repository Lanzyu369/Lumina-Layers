# Vector Material Template Cache Design

**Date:** 2026-08-01
**Status:** Implemented and verified
**Branch:** `MOVIBALE/feat/vector-material-template-cache`

## Goal

Reduce material-solve time for SVGs with many unique fill colours while
preserving the existing matched RGB values, recipes, material matrices,
geometry, GLB, and 3MF semantics exactly. The change is retained only when
fresh semantic, timing, and memory evidence supports it; there is no fixed
percentage target.

## Measured Hotspot

The supplied 9,503-colour SVG produced 3,279 inverse-refinement workspace
groups. A function-level profile showed 6,558 calls to
`generate_candidate_recipes` (bottom and top for every group). Those calls
spent about 38 seconds regenerating, deduplicating, and sorting recipe-index
arrays.

The generated recipe indices do not depend on the identities or optical
properties of the materials. They depend only on:

- material-subset size;
- recipe depth;
- candidate budget; and
- deterministic seed.

Different eight-material subsets therefore regenerate the same index template
and only apply a different `subset[template]` mapping afterward.

## Selected Design

Cache the deterministic recipe-index template by the four inputs above, mark
the cached NumPy array read-only, and keep the existing subset mapping in
`_bounded_subset_recipes`.

Before any workspace threads start, `refine_material_matches` deterministically
prewarms every distinct bottom/top template key used by the current request.
This avoids duplicate cold computations when several worker threads miss the
same cache entry simultaneously. The existing workspace grouping, candidate
order, KD-tree construction, exact search, tie order, forward verification,
and write-back order remain unchanged.

The process-wide LRU is bounded to 16 templates. Default ten-layer,
eight-material refinement retains only the bottom and top templates, totaling
roughly 2.5 MiB with native integer indices. Evicted entries can always be
regenerated from their complete deterministic key.

## Quality Invariants

- Candidate count and candidate row order are unchanged.
- Subset mapping is still applied with the original material order.
- Seeds, budgets, layer depth, and material count are all part of the cache
  key; incompatible templates cannot alias.
- Cached templates are read-only; each workspace receives a newly mapped
  recipe array.
- Optical calculations remain `float64` where previously used.
- KD-tree queries, tie handling, baseline fallback, and forward verification
  are untouched.
- Public APIs, cache schemas, UI settings, and export formats are untouched.

## Rejected Experiment

The first implementation batched multiple target colours into dense
row-by-suffix arrays and split the worker budget between groups and KD-tree
queries. Exact semantic tests passed, but the real 9,503-colour serial run
regressed from about 74.4 to 79.3 seconds and one peak-RSS sample increased
from about 1.10 to 2.05 GiB. Function profiling then showed the batched row
kernel was not the dominant cost. That implementation and its tests were
removed before retaining this design.

## Verification Strategy

1. Unit-test that two different material subsets with the same generation key
   invoke candidate generation once and map to the expected material indices.
2. Preserve existing exact serial/parallel refinement equality tests.
3. Compare end-to-end semantic hashes against `origin/dev-refactor` for the
   supplied ordinary and 9,503-colour SVGs.
4. Cover 8-, 12-, and 15-material archives.
5. Compare serial and four-worker timing and peak RSS on the complex SVG.
6. Run focused material/vector tests, the log-quality gate, compile checks, and
   `git diff --check` before completion.

## Scope Boundaries

This change does not alter colour science, sampling policy, candidate budgets,
material selection, neighbour coherence, preview-to-generate caching,
parallelism policy, geometry, or export code. Further workspace-construction
or exact-query optimization requires a separate measured change.
