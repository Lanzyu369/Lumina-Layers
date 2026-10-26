# Vector Material Template Cache Results

**Date:** 2026-08-01
**Baseline:** `origin/dev-refactor` at `d23a0fe5`
**Branch:** `MOVIBALE/feat/vector-material-template-cache`
**Decision:** Retain the deterministic template cache; reject target-row
batching.

## What Changed

Inverse refinement previously regenerated the same deterministic bottom/top
recipe-index arrays for every material subset. The retained implementation:

1. keys an immutable recipe-index template by material count, recipe depth,
   candidate budget, and seed;
2. bounds reuse with a 16-entry LRU;
3. prewarms the request's distinct keys before worker fan-out; and
4. keeps the existing subset mapping and exact per-row refinement unchanged.

No colour formula, candidate policy, recipe order, material selection,
parallelism policy, geometry, or export path changed.

## Hotspot Evidence

Function profiling of the supplied 9,503-colour SVG observed:

- 3,279 inverse-refinement workspace groups;
- 6,558 `generate_candidate_recipes` calls;
- about 38.1 seconds cumulative in candidate generation; and
- about 24.9 seconds specifically in repeated NumPy row sorting.

The earlier dense target-row batching experiment preserved output but made the
real serial material solve slower (about 74.4 to 79.3 seconds) and increased
one peak-RSS sample (about 1.10 to 2.05 GiB). It was removed before these final
measurements.

## Test Machine and Method

- Apple M5, 10 physical/logical CPUs, 16 GiB RAM
- macOS 26.5.2 arm64
- Python 3.12.13
- `LUMINA_MAX_WORKERS=1`
- serial runs used `LUMINA_VECTOR_PARALLELISM=1`
- parallel runs used `LUMINA_VECTOR_PARALLELISM=4`
- cProfile disabled for the timing table
- every head run used `--reference-report` against a baseline semantic
  snapshot and exited successfully

Representative command:

```bash
LUMINA_VECTOR_PARALLELISM=4 LUMINA_MAX_WORKERS=1 \
  .venv/bin/python scripts/profile_converter_multicore.py \
  --kind vector --phase preview \
  --input /Users/min/Downloads/梵高星空款式西森猫猫.svg \
  --material-count 12 --runs 1 --no-cprofile \
  --reference-report <baseline-profile.json> \
  --output-dir <output-directory>
```

These are fresh paired cold snapshots on one machine, not a cross-platform or
statistical performance guarantee.

## Performance

| Sample | Materials / workers | Metric | Baseline | Head | Change |
|---|---:|---|---:|---:|---:|
| 9,503-colour SVG | 12 / 1 | material solve | 76.881 s | 37.440 s | -51.3% |
| 9,503-colour SVG | 12 / 1 | total preview | 98.699 s | 57.523 s | -41.7% |
| 9,503-colour SVG | 12 / 1 | peak RSS | 2302.09 MiB | 2206.84 MiB | -4.1% |
| 9,503-colour SVG | 12 / 4 | material solve | 61.570 s | 27.417 s | -55.5% |
| 9,503-colour SVG | 12 / 4 | total preview | 81.496 s | 47.366 s | -41.9% |
| 9,503-colour SVG | 12 / 4 | peak RSS | 3490.41 MiB | 2299.95 MiB | -34.1% |
| 143-colour SVG | 8 / 1 | material solve | 0.254 s | 0.254 s | +0.1% |
| 143-colour SVG | 8 / 1 | total preview | 7.266 s | 7.216 s | -0.7% |
| 143-colour SVG | 12 / 1 | material solve | 1.685 s | 0.480 s | -71.5% |
| 143-colour SVG | 12 / 1 | total preview | 8.884 s | 7.861 s | -11.5% |
| 143-colour SVG | 15 / 1 | material solve | 1.659 s | 0.480 s | -71.1% |
| 143-colour SVG | 15 / 1 | total preview | 9.021 s | 8.275 s | -8.3% |

The 8-material case is intentionally neutral: all materials already fit in one
refinement subset, so there is no repeated subset-template work to remove.

## Exact Semantic Evidence

The full profiler snapshot covers matched RGB, height-identity RGB, material
matrix, solid mask, slot names, geometry metadata, and artifacts. Baseline and
head hashes matched exactly:

| Sample | Materials | Semantic SHA-256 |
|---|---:|---|
| 9,503-colour SVG | 12 | `815072534bdddb985b652d685d92f61555591455f61ee4c909289615b8494f60` |
| 143-colour SVG | 8 | `5b4eeb256c7f683bf5be8c28389894d48b4b231e6b0b67ca6310b77b662da526` |
| 143-colour SVG | 12 | `541caf418a339ee73031e89132b597d79e5d7b4147a14bbf62c0f17c99d10f3d` |
| 143-colour SVG | 15 | `1eeb065ca151fde598f5801ed45750846f2c179fbee9164ca3fd052cb19a873d` |

The complex 12-material serial and four-worker runs also share the same hash,
proving worker count did not change the result.

## Automated Verification

```text
206 passed in 2.04s
9 passed in 0.43s
7 passed in 0.77s (final focused rerun)
py_compile: PASS
git diff --check origin/dev-refactor: PASS
log_quality_check.py --mode fast: PASS
  14 INFO / 0 WARNING / 0 ERROR
```

The 206-test suite covered inverse refinement, candidate/material caches,
material visualization, vector material matching, material-archive pipeline,
task parallelism, multicore profiling contracts, and timing responses. The
additional nine tests covered the vector engine integration surface.

## Residual Risk

- Measurements are from one 10-core Apple Silicon machine. Windows/Linux and
  24/32-core performance remain separate validation work.
- The cache is process-local; a fresh process still generates each distinct
  template once.
- Unusual custom depths, budgets, or seeds use separate bounded cache entries
  and may not see reuse when every key is unique.
