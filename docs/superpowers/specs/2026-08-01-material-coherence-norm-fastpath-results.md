# Material Coherence Exact Norm Fast Path Results

**Date:** 2026-08-01
**Parent:** `MOVIBALE/feat/vector-material-template-cache` at `554e7e97`
**Implementation:** `bdfc747b`
**Branch:** `MOVIBALE/feat/vector-material-coherence-fastpath`
**Decision:** Retain the exact norm fast path.

## Outcome

The supplied 9,503-colour SVG retained the same complete semantic SHA-256 in
serial and four-worker modes while the material solve became about 11.6% to
13.2% faster in paired samples. The change does not alter candidate discovery,
recipe order, pair order, thresholds, tie handling, geometry, or export logic.

The implementation replaces three generic `np.linalg.norm` wrapper calls in
the neighbor-coherence loop with the exact real one-dimensional NumPy fast
path, `sqrt(vector.dot(vector))`. It also reuses the source norm when the same
direction vector is negated. The production diff is 10 insertions and 4
deletions in `core/material_cache.py`.

## Why This Was the Next Hotspot

After deterministic recipe-template reuse, cProfile still observed:

- about 7.37 million neighbor-pair iterations;
- about 14.95 million `np.linalg.norm` calls;
- about 18.6 seconds cumulative in the generic norm wrapper path; and
- about 9.3 seconds self time in that wrapper.

For these call sites the values are already real, finite, contiguous float64
vectors with shape `(3,)`. The local NumPy implementation dispatches to the
same `dot` then `sqrt` calculation after general-purpose checks. The retained
helper skips only those repeated checks.

## Test Machine and Method

- Apple M5, 10 visible physical/logical CPUs, 16 GiB RAM
- macOS 26.5.2 arm64
- Python 3.12.13
- NumPy 2.4.6
- `LUMINA_MAX_WORKERS=1`
- serial runs used `LUMINA_VECTOR_PARALLELISM=1`
- parallel runs used `LUMINA_VECTOR_PARALLELISM=4`
- cProfile disabled in retained timing samples
- every head run used a parent semantic report through `--reference-report`
- the final four-worker memory pair also used `/usr/bin/time -l`

Representative serial command:

```bash
LUMINA_VECTOR_PARALLELISM=1 LUMINA_MAX_WORKERS=1 \
  .venv/bin/python scripts/profile_converter_multicore.py \
  --kind vector --phase preview \
  --input /Users/min/Downloads/梵高星空款式西森猫猫.svg \
  --material-count 12 --runs 1 --no-cprofile \
  --reference-report \
    /tmp/lumina-material-template-cache-head-serial-repeat.QKclwi/profile.json \
  --output-dir /tmp/lumina-material-coherence-norm-head-serial.uRIJph
```

The four-worker parent was rerun from a detached worktree at `554e7e97`, then
the head was rerun immediately with the same environment and reference. These
are single-machine cold snapshots, not cross-platform guarantees.

The v2 profile schema does not embed a Git commit. Commit-to-report association
was recorded by the benchmark operator and is therefore not self-authenticating.
The retained evidence manifest records the measured commits, report SHA-256
values, exact input hashes, environment, metrics, and semantic snapshots so the
association is reviewable instead of existing only in temporary directories.

## Complex SVG Performance

| Workers | Metric | Parent | Head | Change |
|---:|---|---:|---:|---:|
| 1 | material solve | 37.440 s | 33.095 s | -11.6% |
| 1 | total preview | 57.523 s | 53.709 s | -6.6% |
| 1 | sampled peak RSS | 2206.84 MiB | 1486.17 MiB | -32.7% |
| 4 | material solve | 29.066 s | 25.240 s | -13.2% |
| 4 | total preview | 49.624 s | 45.830 s | -7.6% |
| 4 | sampled peak RSS | 2880.11 MiB | 2366.14 MiB | -17.8% |
| 4 | kernel maximum RSS | 3011.33 MiB | 2432.09 MiB | -19.2% |

The serial parent is the saved parent report produced immediately before this
branch. The four-worker values are the fresh kernel-instrumented parent/head
pair, which avoids comparing samples taken under different allocator and
scheduling conditions.

## Memory Anomaly Investigation

Two earlier four-worker head samples reported about 3944 to 3973 MiB through
the profiler's 0.25-second RSS polling. That looked like a regression and was
not ignored. A fresh parent rerun under the same poller then reported 3481 MiB,
well above its earlier 2300 MiB sample, proving substantial run-to-run peak
sampling variance.

The final immediate parent/head pair used the operating system's process
high-water measurement in addition to the existing poller:

- parent maximum resident set size: 3,157,606,400 bytes;
- head maximum resident set size: 2,550,235,136 bytes; and
- both semantic references matched.

The retained change therefore has no demonstrated peak-RSS regression. The
earlier high samples remain documented rather than being discarded silently.

## Exact Semantic Evidence

The five preview pairs matched RGB, height-identity RGB, material matrix, solid
mask, and slot names. Preview reports do not populate geometry, scene-instance,
or artifact fields, so those five pairs are not presented as final model/export
proof.

| Input | Materials / workers | Parent and head semantic SHA-256 |
|---|---:|---|
| 9,503-colour complex SVG | 12 / 1 | `815072534bdddb985b652d685d92f61555591455f61ee4c909289615b8494f60` |
| 9,503-colour complex SVG | 12 / 4 | `815072534bdddb985b652d685d92f61555591455f61ee4c909289615b8494f60` |
| 143-colour archive SVG | 8 / 1 | `5b4eeb256c7f683bf5be8c28389894d48b4b231e6b0b67ca6310b77b662da526` |
| 143-colour archive SVG | 12 / 1 | `541caf418a339ee73031e89132b597d79e5d7b4147a14bbf62c0f17c99d10f3d` |
| 143-colour archive SVG | 15 / 1 | `1eeb065ca151fde598f5801ed45750846f2c179fbee9164ca3fd052cb19a873d` |
| 143-colour archive SVG, generate | 12 / 1 | `1bebb01962b610b522377f0de34215246a435b8dac6e73e98d2adb68cb970f7a` |

All six head cases exited successfully with `external_reference_match=true`,
and direct canonical-JSON comparison found each parent/head semantic snapshot
identical. Small 8/12/15-material preview timing changes ranged
from minor regressions to minor improvements and are treated as noise; those
cases exist to prove semantic coverage rather than claim speed.

The separate 12-material generate pair populated and matched all 12 geometry
records, all 12 scene instances, canonical triangle and visual hashes, world
bounds/area/volume, every canonicalized 3MF member, and the generated GLB hash.
Its parent/head total times were 20.112 s and 17.871 s respectively, but this
small archive input is retained primarily as final-output semantic evidence.

The complete retained evidence is in
`progress/material-coherence-norm-fastpath-evidence.json`. It includes the full
head semantic snapshot for every pair plus both report hashes and explicit
parent/head equality results.

## TDD and Automated Verification

The implementation was written after two new tests failed because the helper
was absent. The tests then proved:

- bitwise equality with `np.linalg.norm` for 512 deterministic random vectors
  and five edge vectors;
- exactly three norm-helper calls on a controlled reverse-direction pair;
- no fallback to generic `np.linalg.norm` inside the coherence hot loop; and
- an accepted reverse-direction refinement still chooses the expected RGB.

```text
RED: 2 failed for missing _real_vector_norm
GREEN focused: 2 passed, 28 deselected
Complete coherence file: 30 passed
Related material/vector suite: 229 passed
py_compile: PASS
git diff --check: PASS
log_quality_check.py --mode fast: PASS
  14 INFO / 0 WARNING / 0 ERROR
```

## Cumulative Context

Relative to the pre-template-cache complex-SVG snapshots recorded in the
parent optimization report, the combined retained work now shows:

| Workers | Metric | Earlier baseline | Current head | Cumulative change |
|---:|---|---:|---:|---:|
| 1 | material solve | 76.881 s | 33.095 s | -57.0% |
| 1 | total preview | 98.699 s | 53.709 s | -45.6% |
| 4 | material solve | 61.570 s | 25.240 s | -59.0% |
| 4 | total preview | 81.496 s | 45.830 s | -43.8% |

These cumulative values combine separate cold one-run snapshots on the same
machine. They describe observed progress, not a release SLA.

## Deferred Work

- Replacing `cdist` plus `argpartition` with a KD-tree remains deferred because
  equal-distance candidates can map to different material recipes.
- Reordering or batching neighbor pairs remains deferred because each accepted
  refinement mutates state used by later pairs.
- Cross-vector dot wrappers and scalar logarithms remain candidates only after
  fresh profiling; they must receive their own bitwise and end-to-end semantic
  proof rather than being folded into this change.
- Windows/Linux and real 24/32-core 64-GiB behavior remain separate gray-test
  work and are not claimed by these Apple Silicon samples.
- NumPy is not currently pinned by the runtime requirements. Bitwise norm
  equality was verified on NumPy 2.4.6; other supported NumPy versions still
  require the regression test and end-to-end semantic checks rather than being
  assumed equivalent.
