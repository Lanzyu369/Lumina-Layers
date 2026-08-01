# Material Neighbor Distance Reuse Results

**Date:** 2026-08-01
**Parent:** `MOVIBALE/feat/vector-material-coherence-fastpath` at `51a4ac42`
**Implementation:** `d0634010`
**Branch:** `MOVIBALE/feat/vector-material-pair-distance-reuse`
**Decision:** Retain the exact distance reuse.

## Outcome

The neighbor discovery iterator now passes its already-computed strict-distance
value into the material-coherence loop. This removes one repeated source norm
for every accepted pair while preserving the existing KD-tree query, strict
threshold, lexicographic pair order, candidate order, mutation order, and tie
behavior.

On the supplied 9,503-colour SVG, material solve improved by 6.97% to 11.78%
across four paired parent/head samples. Total preview improved by 3.15% to
6.82%. Every complex, 8/12/15-material, and final-generate semantic comparison
matched the parent exactly.

## Implementation Scope

- Added `_iter_neighbor_pairs_with_distances`, which yields each pair with the
  distance already used by the existing strict-threshold filter.
- Kept `_iter_neighbor_pairs` as the pair-only compatibility wrapper.
- Changed only `_neighbor_coherence_refine` to consume the yielded source norm.
- Left candidate discovery, recipes, geometry, export, logging, worker policy,
  and memory budgets unchanged.
- Production diff: 28 insertions and 10 deletions in `core/material_cache.py`.

## Test Machine and Method

- Apple M5, 10 visible physical/logical CPUs, 16 GiB RAM
- macOS 26.5.2 arm64
- Python 3.12.13
- NumPy 2.4.6
- `LUMINA_MAX_WORKERS=1`
- serial: `LUMINA_VECTOR_PARALLELISM=1`
- parallel: `LUMINA_VECTOR_PARALLELISM=4`
- one cold run per recorded process; retained timing runs disabled cProfile
- every head report used its parent report through `--reference-report`
- the first serial and first two four-worker pairs also used
  `/usr/bin/time -l`; the third four-worker pair was observed with one
  `vmmap -summary` sample per process during the RSS investigation

Representative head command:

```bash
LUMINA_VECTOR_PARALLELISM=4 LUMINA_MAX_WORKERS=1 \
  /usr/bin/time -l .venv/bin/python \
  scripts/profile_converter_multicore.py \
  --kind vector --phase preview \
  --input /Users/min/Downloads/梵高星空款式西森猫猫.svg \
  --material-count 12 --runs 1 --no-cprofile \
  --reference-report <immediately-preceding-parent-profile.json> \
  --output-dir <head-output-directory>
```

The v2 profile schema does not embed a Git commit. The retained evidence
manifest records the operator-associated commits, report hashes, input hashes,
metrics, and semantic snapshots and explicitly marks that association as not
self-authenticating.

## Complex SVG Performance

| Mode / pair order | Metric | Parent | Head | Change |
|---|---|---:|---:|---:|
| serial, parent then head | material solve | 36.180 s | 32.891 s | -9.09% |
| serial, parent then head | total preview | 57.900 s | 53.970 s | -6.79% |
| 4 workers A, parent then head | material solve | 26.272 s | 24.442 s | -6.97% |
| 4 workers A, parent then head | total preview | 47.012 s | 45.529 s | -3.15% |
| 4 workers B, head then parent | material solve | 27.818 s | 25.302 s | -9.04% |
| 4 workers B, head then parent | total preview | 49.504 s | 46.639 s | -5.79% |
| 4 workers C, head then parent | material solve | 29.296 s | 25.845 s | -11.78% |
| 4 workers C, head then parent | total preview | 50.854 s | 47.383 s | -6.82% |

The direction remained positive across both execution orders and three
four-worker repetitions. These are cold single-machine samples, not an SLA or
a substitute for Windows/Linux and real high-core gray testing.

## Memory Investigation

RSS was highly variable and changed sign across repetitions:

| Mode / pair | Parent sampled peak RSS | Head sampled peak RSS |
|---|---:|---:|
| serial | 1681.52 MiB | 3704.66 MiB |
| 4 workers A | 2750.97 MiB | 3781.80 MiB |
| 4 workers B | 2187.38 MiB | 3259.11 MiB |
| 4 workers C | 3747.16 MiB | 1752.20 MiB |
| additional unpaired head diagnostic | n/a | 1357.67 MiB |

The first three samples looked like a head regression, so the result was not
accepted from timing alone. A reverse-order diagnostic then produced the
opposite result: parent 3747.16 MiB versus head 1752.20 MiB. Live `vmmap`
samples also showed that resident versus swapped pages changed substantially
between processes. In the `/usr/bin/time -l` pairs, peak memory footprint was
slightly lower for the head even when maximum RSS was higher.

The implementation adds only one masked float64 row while an iterator is
suspended; it does not retain all pair distances. The available evidence shows
large process-to-process residency variance and no stable peak-memory
regression attributable to this change. Release gray testing should continue
to treat peak RSS as a distribution rather than a single cold sample.

## Semantic Evidence

| Input / phase | Materials / workers | Parent and head semantic SHA-256 |
|---|---:|---|
| 9,503-colour SVG preview | 12 / 1 | `815072534bdddb985b652d685d92f61555591455f61ee4c909289615b8494f60` |
| 9,503-colour SVG preview, all three pairs | 12 / 4 | `815072534bdddb985b652d685d92f61555591455f61ee4c909289615b8494f60` |
| 143-colour archive preview | 8 / 1 | `5b4eeb256c7f683bf5be8c28389894d48b4b231e6b0b67ca6310b77b662da526` |
| 143-colour archive preview | 12 / 1 | `541caf418a339ee73031e89132b597d79e5d7b4147a14bbf62c0f17c99d10f3d` |
| 143-colour archive preview | 15 / 1 | `1eeb065ca151fde598f5801ed45750846f2c179fbee9164ca3fd052cb19a873d` |
| 143-colour archive generate | 12 / 1 | `1bebb01962b610b522377f0de34215246a435b8dac6e73e98d2adb68cb970f7a` |

All head reports recorded `external_reference_match=true`. Direct structured
comparison also found every retained parent/head snapshot equal. The generate
case matched all 12 geometry records, all 12 scene instances, canonical
triangle and visual hashes, every one of 18 canonicalized 3MF members, and the
GLB hash `525af466f6e9da534c6d2b1a8b115869f62e28ff61868f7447609b6b1ee27091`.

## Call-Count Proof

The post-change cProfile recorded:

- `_real_vector_norm`: 7,523,245 calls, down from 14,894,428;
- exact reduction: 7,371,183 calls, one for essentially every yielded source
  pair;
- total function calls: 151,988,471, down from 165,109,930; and
- semantic reference unchanged during the profiled run.

Profiled wall time is intentionally not compared because instrumentation and
machine load differed. The call counts prove the intended duplicate work was
removed; the unprofiled paired runs provide the timing evidence.

## TDD and Verification

```text
RED focused: 2 failed because the distance iterator was absent
GREEN focused: 2 passed
Complete coherence file: 31 passed
Related material/vector suite: 230 passed
py_compile: PASS
git diff --check: PASS
log_quality_check.py --mode fast: PASS
  14 INFO / 0 WARNING / 0 ERROR
```

The new tests cover deterministic Lab-like vectors, strict pair semantics,
signed zero, very small and very large finite float64 values, bitwise equality
with the parent source norm, exact pair ordering, and the controlled removal of
one source-norm call without permitting a generic norm fallback.

## Cumulative Context

Relative to the pre-template-cache complex-SVG snapshots, the three retained
exact optimizations now show these representative results on the same machine:

| Workers | Metric | Earlier baseline | Current head | Cumulative change |
|---:|---|---:|---:|---:|
| 1 | material solve | 76.881 s | 32.891 s | -57.2% |
| 1 | total preview | 98.699 s | 53.970 s | -45.3% |
| 4 | material solve | 61.570 s | 24.442 s | -60.3% |
| 4 | total preview | 81.496 s | 45.529 s | -44.1% |

These cumulative values combine cold one-run snapshots and describe observed
progress only.

## Limitations and Next Direction

- NumPy remains unpinned. Bitwise parity is verified on NumPy 2.4.6; the unit
  and end-to-end gates must run for other supported builds.
- Windows/Linux, hybrid CPUs, and real 24/32-core 64-GiB machines remain gray
  tests, not claims made from this Apple Silicon workstation.
- `_top_k_candidate_rows_blockwise` plus NumPy `argpartition` is now the largest
  clearly isolated material-coherence hotspot in the saved profile. Replacing
  it can alter duplicate-distance tie selection and recipes, so it should be
  researched as a separate semantic-first experiment rather than folded into
  this branch.
- Recipe-workspace construction is the other remaining material hotspot and
  needs fresh allocation/call-shape analysis before any change.

Full retained evidence is in
`progress/material-neighbor-distance-reuse-evidence.json`.
