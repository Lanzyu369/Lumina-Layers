# Vector Native Batch Parallelism Results

> Deployment update (2026-10-06): Docker support and the public-test bypass
> are retired. This historical record preserves earlier implementation and
> validation evidence; use [Runtime support](../../runtime-support.md) for current behavior.
> 部署更新：Docker 支持及公网测试访问旁路已移除；本文保留历史实现与验证记录，当前运行方式以上述说明为准。

**Date:** 2026-07-31

**Status:** `ready_for_review_stacked`

**Branch:** `MOVIBALE/feat/vector-native-mesh-throughput`

**Stacked base:** PR #540 at `2a962c30`

## Verdict

The selected implementation keeps model quality exact and reduces the
repeatable native extrusion hotspot without changing geometry algorithms,
fallback decisions, material identity, recipes, layer order, GLB bytes, or
3MF member contents.

The accepted production policy is deliberately narrow:

- one or two native-batch threads only;
- small workloads remain serial;
- workloads above 3,000 source geometries remain serial;
- automatic selection still respects CPU count, outer-worker fair share,
  available memory, and 1 GiB system headroom;
- any executor, collection, or commit inconsistency discards the local
  parallel result and reruns the unchanged serial path.

The four-worker mode and unrestricted parallelism on the supplied starry SVG
were both exact but failed the 15% peak-RSS gate. They are rejected evidence,
not selectable production modes.

## Quality lock

Every accepted comparison used the external serial-reference gate. The gate
covers arrays, material slots, recipes and bottom-to-top layer order; canonical
oriented triangles and world-space scene instances; visuals; byte-exact GLB;
and every decompressed 3MF member, with only the existing generated source
filename canonicalization.

| Case | Colors | Requested / native workers | Semantic SHA-256 | Result |
|---|---:|---:|---|---|
| matched-RGB override | 8 | 2 / 2 | `9d5a9239c9de6849acf97dd42432ce9b2ebec7c7c30748524fd3551155586e38` | exact |
| requested-worker cap | 8 | 4 / 2 | same as above | exact |
| recipe override | 12 | 2 / 2 | `10ab111a1f0f7e508ad82e6ff1ed5999f4241933ba77d3d947a2cbefd0a1bcad` | exact |
| recipe override auto | 12 | auto / 2 | same as above | exact |
| combined overrides | 15 | 2 / 2 | `3921521ba029035d0893e7b77743db62bc7573c22d8115c895a4b0a7c7d918a9` | exact |
| large native/fallback mix | 12 | 2 / 2 | `1a89268d4a77c3f2a19274778b8488e8038c212f51992ff4869569df97e7137f` | exact GLB and 3MF |
| no override control | 8 | 2 / 2 | `46099120c58b9e73091e3e7369ee992ca36cae4eb93dbfdb979a721fa8fe83cb` | exact |
| 13,970-source guard | 8 | 2 / 1 | `608ebba6fa9e83c015e09632f54e04cbf8168d5fdcb23e7300e67f12f23cb677` | exact |

The large 12-color case retained 212 accepted native groups, 13 fallback
groups, and 11 `native_merged_empty` fallbacks. Raw vertex and face buffers,
surface-rejection behavior, fallback output, cache semantics, and compiled
C++ two/four-thread direct calls also have exact unit coverage.

## Performance

Each timing row below is the median of three fresh Python processes. BLAS and
OpenMP pools were fixed to one thread, cProfile was disabled, and the serial
and two-worker runs used identical quality parameters.

| Workload | Metric | Serial median | Two-worker median | Change |
|---|---|---:|---:|---:|
| 200 mm, 12 colors | end to end | 18.536 s | 15.686 s | 15.4% faster |
| 200 mm, 12 colors | build mesh | 10.657 s | 8.629 s | 19.0% faster |
| 200 mm, 12 colors | native + validation wall | 6.196 s | 3.433 s | 44.6% faster |
| 40 mm, 8 colors | end to end | 4.205 s | 3.715 s | 11.7% faster |
| 40 mm, 8 colors | build mesh | 0.983 s | 0.617 s | 37.3% faster |
| 40 mm, 8 colors | native + validation wall | 0.809 s | 0.446 s | 44.9% faster |

The conservative maximum RSS across the three fresh processes changed from
`1,611.20` to `1,513.11 MiB` on the 200 mm case (`-6.1%`) and from `722.22`
to `679.28 MiB` on the 40 mm control (`-5.9%`). Both accepted sweeps stayed
below the 15% growth gate, reported no child process, and retained the existing
bounded thread count.

## Rejected configurations and extreme-input guard

An exact four-worker diagnostic reached `849.12 MiB` versus a
`731.14 MiB` serial reference (`+16.1%`). The hard maximum is therefore two,
including when the user requests four.

On the supplied starry SVG, unrestricted two-worker native batching was exact
and reduced one run from `118.312` to `97.044` seconds, but peak RSS increased
from `1,925.55` to `2,719.95 MiB` (`+41.3%`). The final 3,000-source guard
reports 13,970 source geometries, one native worker, zero parallel native wall
time, and the exact external hash above.

Repeated whole-process RSS values for this extreme file were not used to
claim a memory improvement: the earlier material-color solve shares
`LUMINA_VECTOR_PARALLELISM`, remained independently multi-threaded, and varied
substantially with system swap pressure. The relevant safety fact for this PR
is that the new native-mesh executor is not created for that workload, so this
change adds no concurrent native batch working set there.

## Runtime and rollback

Measurements used Apple M5 arm64, 10 visible CPUs, 16 GiB RAM, macOS 26.5.2,
Python 3.12.13, NumPy 2.4.6, Shapely 2.1.2, Trimesh 4.12.2, and psutil 7.2.2.
The native extension reported `triangulation_area_guard=True`. No Docker,
Rosetta, server deployment, or child-process fallback was involved.

Operational rollback is `LUMINA_VECTOR_PARALLELISM=1`. Code rollback removes
only batch scheduling and its bounded timing fields; the existing native
surface guard and Python fallback remain unchanged.

No supplied SVG, bitmap, material archive, generated model, log, or
machine-local path is committed.

## Verification

- focused native/vector/scheduler regression: `235 passed`, `3 skipped`
  because optional external diagnosis assets were absent;
- logging governance regression: `21 passed`;
- fast structured-log workflow: `PASS`, 14 INFO lines, zero warnings/errors,
  and every budget/governance check passed;
- Python compilation and `git diff --check`: passed.

Two pre-existing stroke tests still expect an INFO message that the base
implementation emits at DEBUG. Both fail identically on stacked base
`2a962c30`; they were independently reproduced there and are not changed or
hidden by this branch.

This branch must be rebased onto the final merged commit of PR #540 before it
is pushed and opened as a follow-up PR.
