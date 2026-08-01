# Material Coherence Demand Top-K Results

- **Date:** 2026-08-01
- **Parent:** `b8cd20f96bf71ca5eba229e213c604c8388f30ff`
- **Measured code:** `760e30e32c9f91e4bc43a3c8b55d0f8ed5a3a718`
- **Decision:** Retain

## Result

The serial material-coherence path now computes an exact Top-K candidate row
only when the refinement loop first requests that target colour. Repeated
requests reuse the request-local row. The multi-worker path still uses the
existing eager, memory-bounded block scheduler.

The retained implementation changes scheduling only. Parent/head semantic
snapshots matched for the 9,503-colour complex SVG, 8/12/15-material archive
previews, and a 12-material complete generation. The complete generation
comparison covered all 12 geometry records, scene instances, 18 canonical 3MF
members, and the GLB preview.

## Quality Gates

- Focused coherence suite: `34 passed`.
- Related material, vector, scheduler, profiling, and timing suite:
  `233 passed`.
- Serial demand regression rejects eager full-row calculation and proves every
  requested row is calculated at most once.
- Duplicate-candidate regression compares every returned output against the
  eager path, including tie-sensitive candidate ordering.
- Four-worker regression proves the existing blockwise helper remains the
  selected implementation.
- Python compilation and `git diff --check` passed before real profiling.
- Final fast log-quality gate passed with 14 INFO, 0 WARNING, 0 ERROR, and all
  governance checks passing.

## Complex SVG Timing

Input: `梵高星空款式西森猫猫.svg`

Input SHA-256:
`ba6d44586c4c9903091ade81ed331c09308ec6a6f684c72f1b8cc15aad42f717`

Each value below is one fresh-process cold run. The serial pair was repeated in
reverse order because whole-request parse and occlusion time varied. Negative
deltas are faster.

| Mode and order | Parent total | Head total | Total delta | Parent material solve | Head material solve | Solve delta | Semantic snapshot |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 worker, parent then head | 54.116 s | 55.563 s | +2.67% | 32.561 s | 30.143 s | -7.43% | exact |
| 1 worker, head then parent | 68.121 s | 59.268 s | -13.00% | 41.522 s | 29.113 s | -29.89% | exact |
| 4 workers, parent then head | 47.528 s | 47.420 s | -0.23% | 25.701 s | 25.380 s | -1.25% | exact |
| 4 workers, head then parent | 44.214 s | 43.209 s | -2.27% | 23.609 s | 22.808 s | -3.39% | exact |

The serial material stage improved in both process orders. The magnitude is not
treated as a stable percentage because the machine showed substantial load and
memory variability. Total time in the first pair was masked by unrelated parse
and occlusion variance. The four-worker measurements are evidence that the
unchanged high-core path was exercised and did not regress in these samples;
they are not a 24/32-core performance claim.

All eight complex-SVG reports used semantic reference SHA-256
`815072534bdddb985b652d685d92f61555591455f61ee4c909289615b8494f60`.

## Material Archive Matrix

Input: `mmexport1784271438721.svg`

Input SHA-256:
`88f9a92690e765e48533b344ff1b313cf2168d7952ecb96253e036fb54a07788`

| Materials | Parent total | Head total | Parent material solve | Head material solve | Semantic snapshot |
| ---: | ---: | ---: | ---: | ---: | --- |
| 8 | 7.831 s | 8.649 s | 0.286 s | 0.291 s | exact |
| 12 | 8.558 s | 8.369 s | 0.505 s | 0.574 s | exact |
| 15 | 8.379 s | 7.967 s | 0.491 s | 0.458 s | exact |

The archive material stage is only about 0.3-0.6 seconds in these cold runs,
so the timing differences are considered noise. These cases are retained as
semantic coverage for the requested 8-15 material range, not as performance
claims.

## Complete Generation

The 12-material generate pair produced the same canonical semantic reference:
`1bebb01962b610b522377f0de34215246a435b8dac6e73e98d2adb68cb970f7a`.

| Measurement | Parent | Head |
| --- | ---: | ---: |
| Total | 17.852 s | 17.645 s |
| Material solve | 0.481 s | 0.463 s |
| Geometry records | 12 | 12 |
| Canonical 3MF members | 18 | 18 |
| GLB SHA-256 | `525af466...7091` | `525af466...7091` |

The head report accepted the parent through `--reference-report`, which
compares the full canonical snapshot rather than only the abbreviated values
shown in this table.

## Reproduction

The profiles used the repository harness with one fresh process per run:

```bash
LUMINA_VECTOR_PARALLELISM=<1-or-4> LUMINA_MAX_WORKERS=1 \
  .venv/bin/python scripts/profile_converter_multicore.py \
  --kind vector --phase <preview-or-generate> \
  --input <svg> --material-count <8-or-12-or-15> \
  --runs 1 --no-cprofile \
  --reference-report <parent-profile.json> \
  --output-dir <output-directory>
```

The parent command ran in a detached worktree at `b8cd20f9`; the head command
ran at `760e30e3`. Profile schema v2 does not embed the Git commit, so this
parent/head association is operator-recorded. SHA-256 hashes of every raw
report are stored in
`progress/material-coherence-demand-topk-evidence.json`.

## Environment and Claim Boundary

- macOS 26.5.2, arm64
- Python 3.12.13
- NumPy 2.4.6
- 10 visible CPUs
- 16 GiB physical memory
- no BLAS/OpenMP thread override was set

No real 24/32-core or 64-GiB host was available in this run. The implementation
does not add a worker cap or alter capacity detection, but high-end scaling
still needs gray-test evidence from such a host before making a release claim.
Peak RSS samples varied too widely between fresh processes to attribute a
stable memory percentage to this change.
