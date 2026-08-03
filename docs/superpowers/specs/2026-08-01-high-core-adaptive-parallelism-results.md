# High-Core Adaptive Converter Parallelism Results

**Date:** 2026-08-01

**Status:** `development_machine_verified_high_core_speed_pending`

**Branch:** `MOVIBALE/feat/adaptive-converter-parallelism`

**Draft PR:** [#544](https://github.com/lumina-layer-studio/Lumina-studio/pull/544)

**Profiled topology implementation SHA:** `8c42b0c4`

**Post-profile compatibility review SHA:** `10de51b2`

The later SHA only restores the shared planner's legacy default; all profiled
converter stages explicitly pass `hard_max_workers=None`, so their runtime
path is unchanged. Focused, smoke, logging, compilation, and diff gates were
rerun after that compatibility correction.

## Verdict

The continuous scheduler and CPU-topology follow-up preserve exact converter
semantics on the supplied 8/12/15-material bitmap corpus and the current vector
references. The implementation no longer treats every reported CPU as an
equal-speed core and does not impose a product-wide 2-, 8-, 16-, or 32-worker
ceiling.

The platform policy is:

- Apple with a reliable performance-level probe: size the heavy-worker budget
  to the performance-core level without pinning threads;
- Windows with multiple CPU-set `EfficiencyClass` values: record the hybrid
  topology and let the Windows scheduler use all process-visible CPU sets;
- Windows with one reported class: retain all visible CPU capacity;
- Linux: retain affinity/cgroup limits and let the kernel capacity-aware
  scheduler place workers;
- every platform: take the minimum of CPU fair share, independent items,
  useful work, memory, nesting, and any explicit operator ceiling.

The shared planner retains its legacy eight-worker default for callers that do
not opt in. Only the three reviewed converter stages explicitly pass an
unbounded stage ceiling, so external or future callers do not silently change
behavior.

This follow-up changes scheduling and diagnostics only. It does not change
matched colors, material recipes, layer order, geometry algorithms, native
validation, fallbacks, GLB construction, or 3MF construction.

## Exact-quality evidence

Every row below passed the profiler's external serial-reference comparison.
That comparison covers matched RGB, height-identity RGB, material matrix, solid
mask, slot order, canonical oriented triangles, world-space instances, GLB,
and decompressed 3MF members under the existing canonicalization rules.

| Family | Supplied input | Materials | Auto workers | Limiter | Semantic SHA-256 | Result |
| --- | --- | ---: | ---: | --- | --- | --- |
| vector | `945695877_20260622_232544_vector.svg` | 8 | 1 | useful work | `d4b1ec27d2f7341193ef5a7efb9fc0d40217c6b599095c8059445aa128b85acd` | exact |
| vector | `mmexport1784271438721.svg` | 12 | 4 | CPU fair share | `d0eb56888e837b8408b817fa2c65b373e592cc07a6ca21fbb3074e37a064d87d` | exact |
| raster | `145874854_p0_master1200.jpg` | 8 | 1 | memory | `4b4307891f3857aff082fe924556c16fd10d7214c303fbb8f4db02ca8997cb84` | exact |
| raster | `145879725_p0_master1200.jpg` | 12 | 4 | CPU fair share | `498b9c09b5aa17f0727cc230572225677dcbf502d6a662a9c03ea9db693410f3` | exact |
| raster | `145881118_p0_master1200.jpg` | 15 | 3 | memory | `8b52ec820b4af17ada6ac591709ab87e0a50ffdb629eb5a49259e643280e2579` | exact |

The current Mac reports all identify:

```text
cpu_topology = heterogeneous
cpu_scheduling_policy = apple_performance_budget
visible_cpu = 10
performance_cpu = 4
effective_cpu = 4
```

The light vector input contains only 17 unique target fills, so it remains
serial even though four performance CPUs are available. The 8/12/15-material
raster runs selected 1/4/3 workers as available memory changed. This proves the
stage decisions are resource-derived rather than fixed tiers.

## Development-machine timing caveat

These runs validate exactness and live decisions; they do not establish a
high-core speed claim. During the raster sweep the 16-GiB Mac had approximately
14.4 GiB of swap in use and significant unrelated desktop load. The retained
single-run observations were:

| Input | Materials | Workers | Total | Peak RSS |
| --- | ---: | ---: | ---: | ---: |
| `945695877_20260622_232544_vector.svg` | 8 | 1 | 4.146 s | 910.9 MiB |
| `mmexport1784271438721.svg` | 12 | 4 | 18.751 s | 1,628.2 MiB |
| `145874854_p0_master1200.jpg` | 8 | 1 | 37.039 s | 2,535.8 MiB |
| `145879725_p0_master1200.jpg` | 12 | 4 | 49.603 s | 3,947.7 MiB |
| `145881118_p0_master1200.jpg` | 15 | 3 | 63.174 s | 3,611.9 MiB |

They must not be compared with earlier low-pressure runs as if they were a
controlled A/B experiment.

## Apparent four-worker regression investigation

An initial three-run serial report followed by a three-run automatic report
showed `17.452 / 20.672 s` warm medians. Stage timings did not support a
worker-caused 18% regression: the changed material solve differed by only
approximately 0.13--0.22 seconds, while unchanged extrusion, assembly, GLB,
and 3MF stages all slowed together.

Fresh-process, order-alternated investigation then observed:

| Order | Serial | Four workers | Interpretation |
| --- | ---: | ---: | --- |
| serial -> four | 17.954 s | 18.035 s | effectively equal (0.45% difference) |
| four -> serial under continued load | 20.515 s | 31.752 s | the later serial control degraded |

The second pair disproves a stable four-worker penalty and demonstrates strong
order/whole-machine effects. The run was stopped before adding more heat. Any
future speed claim must use fresh processes, alternate order, and record system
pressure; stage-local timing is required to attribute a change to a worker
policy.

## Deterministic topology and high-core matrix

Unit tests establish scheduling behavior, not speed:

| Injected topology | Process-visible CPU | Fastest class | Scheduler CPU ceiling |
| --- | ---: | ---: | ---: |
| homogeneous/unknown | 32 | unknown | 32 |
| Windows hybrid | 32 | 16 | 32 (OS-managed) |
| Apple hybrid | 10 | 4 | 4 |
| any host with affinity/quota | 32 host / 8 allowed | varies | 8 |

Separate planner tests prove that outer demand, useful work, item count, and
memory can reduce a 32-CPU plan to 16, 12, 8, 7, or 1 without a hidden stage
cap. A 12-material raster task naturally stops at 12 even on a larger host.

## Reproducible reports

- `.scratch/high-core/vector-8-topology-auto/profile.json`
- `.scratch/high-core/vector-12-topology-auto/profile.json`
- `.scratch/high-core/vector-12-serial/profile.json`
- `.scratch/high-core/vector-12-auto/profile.json`
- `.scratch/high-core/topology-ab-1-{serial,workers4}/profile.json`
- `.scratch/high-core/topology-ab-2-{workers4,serial}/profile.json`
- `.scratch/high-core/raster-8-topology-auto/profile.json`
- `.scratch/high-core/raster-12-topology-auto/profile.json`
- `.scratch/high-core/raster-15-topology-auto/profile.json`

All supplied source assets and generated reports remain ignored local evidence;
none is committed.

## Remaining release evidence

A real Windows hybrid machine and a homogeneous 24/32-core, 64-GiB-class
machine are still required before claiming high-end speedup. The acceptance run
must use 8--15 material archives, fresh alternating serial/automatic processes,
one-thread BLAS/OpenMP helper pools, external semantic references, and retained
worker/RSS/topology fields.

Until that evidence exists, the correct claim is:

```text
verified dynamic scheduling and exact semantics;
high-core performance capability enabled but not yet measured on matching hardware.
```

## Final verification

- focused backend, topology, worker-runtime, exactness, profiler, and logging
  suites: `273 passed`;
- smoke backend: `131 passed`, `5,073 deselected`;
- smoke frontend: `150 passed` across 10 files;
- ESLint: zero errors and 60 pre-existing warnings;
- fast log-quality workflow: `PASS`, 14 INFO records, zero warnings/errors;
- touched Python compilation and `git diff --check`: passed;
- first smoke attempt with ambient pnpm 11 stopped before lint because that
  version ignores the repository's `onlyBuiltDependencies` location; the
  complete gate was rerun successfully with the repository-pinned pnpm
  `10.33.2`, and the temporary pnpm 11 workspace file was removed.
