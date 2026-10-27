# Material Coherence Demand Top-K Design

**Date:** 2026-08-01
**Parent:** `MOVIBALE/feat/vector-material-pair-distance-reuse` at `b8cd20f9`
**Branch:** `MOVIBALE/feat/vector-material-demand-topk`
**Status:** Approved for implementation

## Outcome Sought

Avoid calculating exact Top-K material candidates for target colours that the
sequential neighbor-coherence loop never inspects. The optimization must retain
the existing `cdist` values, NumPy `argpartition` indices and ordering, mutation
order, matched colours, material recipes, geometry, and exported artifacts.

There is no fixed percentage target. Retain the change only when the real
9,503-colour SVG and the 8/12/15-material gates remain semantically exact and
the measured serial path improves without regressing the existing parallel
path.

## Profile and Research Evidence

The retained profile identified `_top_k_candidate_rows_blockwise` as the
largest isolated material-coherence hotspot:

- 9,503 target colours;
- 169,206 coherence candidates;
- 194 distance blocks under the 64 MiB temporary-matrix budget;
- 12.36 seconds for serial full-row Top-K in a fresh unprofiled measurement;
- only 5,179 target rows were read by the later coherence loop; and
- those reads touched all 194 contiguous blocks, so block-level laziness cannot
  reduce work.

Recomputing only the 5,179 demanded rows one row at a time took 5.33 seconds.
Every returned index and distance was identical to the corresponding legacy
full-matrix row. Running the complete coherence function with a throwaway lazy
row provider took 18.66 seconds and reproduced matched RGB, material recipes,
and Delta-E arrays exactly. Combining the measured 12.36-second eager Top-K
with the unchanged 13.28-second coherence loop gives a 25.64-second reference,
so the prototype reduced this stage by about 27%.

The existing eager implementation scales well when actual workers are
available: 5.97 seconds with 2 workers, 3.85 seconds with 4, and 2.71 seconds
with 8 on the same captured arrays. The design therefore does not replace the
parallel path.

## Considered Approaches

### A. Exact row-on-demand cache for one worker (selected)

When effective material parallelism is one, create a request-local cache. On
the first request for target row `i`, call the existing
`_top_k_candidate_block` with `target_lab[i:i + 1]`, store its index and
distance row, and return it. Repeated requests reuse the stored row.

NumPy partitions rows independently along `axis=1`, so this invokes the same
distance and selection operations on the same candidate order as the eager
implementation. It changes scheduling only, not selection.

Advantages:

- preserves exact duplicate-distance and K-boundary tie behavior;
- performs work only for dynamically demanded rows;
- keeps pair and mutation order sequential and unchanged;
- reduces the temporary distance matrix from a budgeted multi-row block to one
  candidate row in the serial path; and
- introduces no external dependency or persistent cache.

Risks and mitigations:

- A row can be requested many times. Cache readiness separately so each row is
  computed at most once.
- A new provider abstraction could accidentally change candidate order. Use
  `_top_k_candidate_block` directly and compare full coherence outputs against
  the eager path with duplicate candidates.
- Very small inputs may not benefit measurably. The retained implementation is
  intentionally narrow and must not add adaptive heuristics without evidence.

### B. Continue eager memory-bounded parallel blocks (selected for workers > 1)

Keep `_top_k_candidate_rows_blockwise` unchanged whenever effective
parallelism exceeds one. This preserves current scaling, worker admission, and
the 64 MiB total temporary-distance budget on higher-core machines.

The effective worker value already comes from the runtime CPU, affinity/cgroup,
memory, useful-work, and nested-parallelism policy. This design adds no fixed
CPU cap.

### C. KD-tree, FAISS, or another Top-K implementation (rejected)

A throwaway exact `cKDTree` experiment reduced Top-K discovery to about 0.07
seconds, but the final semantic snapshot differed. There were 2,136 rows tied
at the eighth/ninth candidate boundary, and even a boundary-tie fallback did
not restore exact output because order within the selected partition also
matters to later strict comparisons.

NumPy documents `argpartition` as unstable with undefined partition order;
PyTorch similarly does not guarantee tied `topk` indices. FAISS `IndexFlatL2`
uses a different float and ordering path and would add a dependency. These
approaches violate the exact recipe constraint and are not implementation
candidates.

### D. Cache larger contiguous blocks lazily (rejected)

The real demand set touched every one of the 194 current blocks. Lazy blocks
would perform the same full Top-K work while delaying parallel scheduling and
adding cache complexity.

## Detailed Design

1. Add a private `_ExactTopKRowCache` in `core/material_cache.py` beside the
   current Top-K helpers.
2. Store references to `target_lab` and `candidate_lab`, the effective Top-K,
   preallocated output arrays, and a Boolean readiness vector.
3. `get(row_index)` validates through ordinary array indexing, invokes
   `_top_k_candidate_block` for exactly one target row when not ready, copies
   both result rows into the cache, marks readiness, and returns views of the
   cached rows.
4. In `_neighbor_coherence_refine`, create `_ExactTopKRowCache` only when
   `parallelism <= 1`. For `parallelism > 1`, call the existing blockwise
   helper exactly as before.
5. At the existing candidate-consumption point, retrieve both index and
   distance rows through the serial cache or the eager arrays. Do not move any
   pair checks, candidate checks, strict comparisons, mutations, or logs.
6. Keep all public signatures, constants, worker policy, and memory budgets
   unchanged.

## Acceptance and Rejection

Retain only if all of these hold:

- a red/green regression proves serial coherence no longer invokes eager
  full-row Top-K and computes each demanded row once;
- serial and eager paths return identical complete outputs with duplicate
  candidates and accepted refinements;
- the parallel path still invokes the existing blockwise helper;
- the related material/vector suite passes;
- the 9,503-colour SVG matches the parent semantic snapshot in serial and
  four-worker modes;
- 8/12/15-material archive previews match the parent;
- a 12-material generate run matches material arrays, geometry, instances,
  canonical 3MF members, and GLB;
- serial paired timing shows a repeatable useful improvement; and
- four-worker timing does not show a repeatable regression.

Any semantic mismatch rejects the optimization. A neutral or noisy serial
result gets one immediate paired rerun before a retain/reject decision.
