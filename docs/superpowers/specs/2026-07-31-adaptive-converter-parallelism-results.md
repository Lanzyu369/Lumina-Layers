# Adaptive Converter Parallelism Results

**Date:** 2026-07-31

**Status:** `ready_for_stacked_review`

**Branch:** `MOVIBALE/feat/adaptive-converter-parallelism`

**Draft PR:** [#544](https://github.com/lumina-layer-studio/Lumina-studio/pull/544)

**Stacked base:** `MOVIBALE/feat/vector-native-mesh-throughput@f01d3044`

**Merge gate:** stacked review only. Do not merge until Draft PR #540 lands
and the parent native-mesh branch is rebased onto the resulting
`origin/dev-refactor`.

**Tested policy SHA:** `3d73eaaaaec723144fd7cda3e227f7641265b0f6`

## Verdict

The adaptive scheduler preserves exact model semantics and improves the
representative raster and vector workflows without admitting the unstable
four-worker tier.

The selected production policy is:

- raster mesh generation: one or two inner workers;
- vector material solving: one or two inner workers;
- vector native-mesh batches: one or two inner workers, with at most three
  prepared/submitted batches in flight when two workers are selected;
- automatic reduction to one worker when effective CPU capacity, current
  outer demand, useful work, nesting, or available memory requires it;
- operator values remain ceilings and cannot override any safety limit;
- any native parallel failure discards local output and reruns the unchanged
  serial path.

The implementation changes scheduling only. It does not change material
matching, recipes, layer order, geometry algorithms, tolerances, surface
validation, fallback decisions, GLB construction, or 3MF construction.

## Exact-quality gate

Every accepted non-serial report passed the profiler's external serial
reference. The reference covers matched RGB, height-identity RGB, material
matrix, solid mask, slot order, canonical oriented triangles, world-space
instances, GLB, and decompressed 3MF members with only the existing generated
source-filename canonicalization.

| Family | Input / override | Colors | Final material/native or raster workers | Semantic SHA-256 | Result |
|---|---|---:|---|---|---|
| vector | `945695877_20260622_232544_vector.svg`, matched RGB | 8 | `1 / 2` | `1f3809b6f5e47fe342f4d6dfc859e87d1c4828fb9c09f6392e1ca2f1d8f02481` | exact |
| vector | `mmexport1784271438721.svg`, recipe | 12 | `2 / 2` | `c5fe16d53aaf1a33e96cd1aa9ede3005d3e7c2e422de6bafe9268cc5009850df` | exact |
| vector | `梵高星空款式西森猫猫.svg`, combined | 15 | `2 / 2` | `df80cf2e2ded70feaa4199679a1a76cc26ae2aa23bcd3fb3f8c6a4a673e7e33d` | exact |
| raster | `145874854_p0_master1200.jpg` | 8 | `2,2,2` | `4b4307891f3857aff082fe924556c16fd10d7214c303fbb8f4db02ca8997cb84` | exact |
| raster | `145879725_p0_master1200.jpg` | 12 | `2,2,2` | `498b9c09b5aa17f0727cc230572225677dcbf502d6a662a9c03ea9db693410f3` | exact |
| raster | `145881118_p0_master1200.jpg` | 15 | `2,2,1` | `8b52ec820b4af17ada6ac591709ab87e0a50ffdb629eb5a49259e643280e2579` | exact |
| raster | `145890683_p0_master1200.jpg` | 8 | `2` in each fresh A/B process | `e5eca4a1b1b464a4080dd3131e67f91b3b064006ad37440d97566598c4acc7be` | exact |
| raster | `145883686_p0_master1200.jpg` | 12 | `2,2,2` | `492aaca2cb1dd770603ae18843b54e22f01721765906c30a0495d6bd91bc68d1` | exact |
| raster | `145877421_p0_master1200.jpg` | 15 | `2,1,1` | `c43c9f6fd480099901d7867773079a8d0f4576b8ef483f8c8ea61815f7aee019` | exact |

The final vector runs retained these per-run decisions:

- 8 colors: zero native fallbacks;
- 12 colors: 13 native fallbacks and 11 `native_merged_empty`
  fallbacks;
- 15 colors: 33 native fallbacks and 6 `native_merged_empty`
  fallbacks;
- no oversized batch was admitted to the parallel window.

## Measurement method

The converter reports used a 200 mm target, three runs, disabled cProfile, a
single outer task (`LUMINA_MAX_WORKERS=1`), and one thread for OpenMP, BLAS,
MKL, Accelerate, and NumExpr. Unless stated otherwise, the table uses the
median of runs two and three and the maximum sampled RSS across all three
runs.

The three-run profiler intentionally reuses one Python process. This exposes
retained allocator/cache pressure and verifies that later stage decisions
contract from two workers to one as available memory falls. The macOS
production worker pool independently recycles a worker after each task.

One raster case showed a misleading warm-run regression after a long matrix
sweep even though those warm runs had already contracted to the unchanged
serial path. That case received three additional fresh-process, alternating
serial/automatic A/B pairs. The A/B median is used below and all individual
pair results are retained.

Machine and library snapshot:

```text
macOS 26.5.2 arm64
Apple performance CPU capacity: 4 (10 logical CPUs visible)
RAM: 16 GiB
Python 3.12.13
NumPy 2.4.6
Numba 0.66.0
OpenCV 5.0.0
psutil 7.2.2
Shapely 2.1.2
Trimesh 4.12.2
```

## Vector performance

The conservative comparison below uses the earlier serial/requested-two
sweep. Requested two has the same effective worker shape as the final
automatic policy. The later final-auto rerun was used to verify automatic
selection and external semantics, but its already-warm caches are not used to
inflate the speed claim.

| Input | Colors | Serial warm median | Two-worker warm median | Change | Serial / two-worker peak RSS |
|---|---:|---:|---:|---:|---:|
| `945695877_20260622_232544_vector.svg` | 8 | 8.800 s | 5.699 s | 35.2% faster | 1,338 / 1,129 MiB |
| `mmexport1784271438721.svg` | 12 | 33.443 s | 18.399 s | 45.0% faster | 1,338 / 1,675 MiB |
| `梵高星空款式西森猫猫.svg` | 15 | 156.475 s | 135.330 s | 13.5% faster | 2,798 / 3,097 MiB |

The final automatic reports selected `1/2`, `2/2`, and `2/2`
material/native workers respectively. Their warm medians were `2.912`,
`14.716`, and `133.992` seconds. The first two are recorded only as final-code
diagnostics because native imports and converter caches were already warm;
the 15-color result independently confirms a conservative 14.4% improvement.

### Four-worker rejection

The 12-color starry policy sweep measured:

| Candidate | Warm median | Peak RSS | External semantics |
|---|---:|---:|---|
| serial | 213.227 s | 2,978.5 MiB | reference |
| requested two | 142.401 s | 3,009.9 MiB | exact |
| requested four | 142.999 s | 2,812.7 MiB | exact |

Four native workers were 0.4% slower than two and therefore failed the
required 10% incremental-speed gate even though semantics were exact.

The material-solver tier had the same outcome. On the 12-color corpus, four
workers were only 1.8% faster than two. On the 15-color case, one four-worker
run was 1.8% faster, while another requested-four sweep was slower and reached
4,427.7 MiB. The gain was neither large nor stable. Both vector stage ceilings
are therefore two.

## Raster performance

| Input | Colors | Serial median | Final automatic median | Change | Serial / automatic peak RSS | Final workers |
|---|---:|---:|---:|---:|---:|---|
| `145874854_p0_master1200.jpg` | 8 | 33.510 s | 27.427 s | 18.2% faster | 4,006 / 4,667 MiB | `2,2,2` |
| `145879725_p0_master1200.jpg` | 12 | 26.473 s | 22.328 s | 15.7% faster | 3,868 / 3,867 MiB | `2,2,2` |
| `145881118_p0_master1200.jpg` | 15 | 45.086 s | 37.585 s | 16.6% faster | 3,610 / 3,902 MiB | `2,2,1` |
| `145890683_p0_master1200.jpg` | 8 | 41.523 s | 35.873 s | 13.6% faster | 5,408 / 5,507 MiB | fresh `2,2,2` |
| `145883686_p0_master1200.jpg` | 12 | 14.181 s | 13.816 s | 2.6% faster | 5,815 / 4,578 MiB | `2,2,2` |
| `145877421_p0_master1200.jpg` | 15 | 38.586 s | 38.677 s | 0.2% slower | 4,336 / 5,102 MiB | `2,1,1` |

There is no repeatable raster regression above 5%. The one neutral case is
within measurement noise and automatically contracts after memory pressure.

The fresh-process A/B pairs for `145890683` were:

```text
serial 41.482 s -> automatic 35.945 s (13.3% faster)
serial 42.195 s -> automatic 35.873 s (15.0% faster)
serial 41.523 s -> automatic 35.375 s (14.8% faster)
```

The rejected four-worker raster sweep did not produce a stable extra gain.
It also exposed tails of 6,399.6 MiB on one 15-color case versus 3,610.0 MiB
for serial, and 6,088.3 MiB versus 4,336.0 MiB on another. The final
two-worker ceiling kept the worst supplied-bitmap observation at 5,506.9 MiB
on this 16 GiB machine and retained automatic one-worker contraction.

## Native corpus guard

`profile_vector_native_mesh_corpus.py` completed `1 PASS / 0 FAIL / 0 ERROR`
with native surface validation and native import warmup enabled.

For the supplied starry SVG:

- 14,005 shapes;
- zero area delta and zero volume delta;
- 55 native groups;
- 18,032 native meshes;
- 23 fallback groups, all `split_empty_native_mesh`;
- 16 split retries;
- no geometry, bounds, surface, or fallback-decision failure.

The corpus result is a quality guard rather than a speed claim:
native-enabled build was `14.420` seconds versus `14.364` seconds for its
baseline, while native extrusion itself was effectively equal
(`11.037` versus `11.075` seconds).

## Runtime controls and rollback

Operational rollback remains:

```text
LUMINA_RASTER_PARALLELISM=1
LUMINA_VECTOR_PARALLELISM=1
```

Missing or malformed CPU, demand, or memory telemetry fails closed to a
smaller worker count. The demand snapshot contains only bounded scheduler
counts and is atomically replaced. No supplied SVG, bitmap, generated model,
material archive, report under `.scratch`, log, or machine-local path is
committed.

## Reproducible report locations

Final automatic vector reports:

- `.scratch/adaptive-parallelism/vector-8-auto-final-cap2/profile.json`
- `.scratch/adaptive-parallelism/vector-corpus-12-auto-final-cap2/profile.json`
- `.scratch/adaptive-parallelism/vector-15-auto-final-cap2/profile.json`

Final automatic raster reports:

- `.scratch/adaptive-parallelism/raster-145874854-auto-cap2/profile.json`
- `.scratch/adaptive-parallelism/raster-145879725-auto-cap2/profile.json`
- `.scratch/adaptive-parallelism/raster-145881118-auto-cap2/profile.json`
- `.scratch/adaptive-parallelism/raster-145890683-auto-cap2/profile.json`
- `.scratch/adaptive-parallelism/raster-145883686-auto-cap2/profile.json`
- `.scratch/adaptive-parallelism/raster-145877421-auto-cap2/profile.json`

Fresh-process raster A/B reports:

- `.scratch/adaptive-parallelism/raster-145890683-ab1-{serial,auto-cap2}/profile.json`
- `.scratch/adaptive-parallelism/raster-145890683-ab2-{serial,auto-cap2}/profile.json`
- `.scratch/adaptive-parallelism/raster-145890683-ab3-{serial,auto-cap2}/profile.json`

Native corpus report:

- `.scratch/adaptive-parallelism/native-corpus/vector_native_mesh_corpus.json`

## Verification

- final focused backend suite after review fixes: `241 passed`;
- structured logging and exception-governance suite: `21 passed`;
- fast log-quality workflow: `PASS`, 14 INFO records, zero warnings/errors,
  and every budget/governance check passed;
- smoke backend: `131 passed`, `5,056 deselected`;
- smoke frontend: `150 passed` across 10 files;
- ESLint: zero errors and 60 pre-existing warnings;
- final vector material and native focused regression: `51 passed`;
- native corpus: `1 PASS / 0 FAIL / 0 ERROR`;
- every final raster/vector external reference: exact;
- touched-file compilation and `git diff --check f01d3044...HEAD`: passed.

The first smoke invocation inherited pnpm `11.9.0` from the desktop runtime
instead of the repository-pinned `10.33.2`. It stopped before ESLint because
pnpm 11 no longer reads the existing
`package.json.pnpm.onlyBuiltDependencies` field. The same field exists on
stacked base `f01d3044`. Re-running the complete smoke gate with cached pinned
pnpm `10.33.2` passed; the pnpm 11 placeholder file was removed and no
repository change was retained.

## 中文总结

最终结论是：保留动态调度，但所有重计算阶段最多使用 2 个任务内线程。
系统仍会根据用户机器实际可用的高性能 CPU、当前外层任务数量、工作量和
可用内存自动在 1/2 线程之间选择。用户显式配置也只是上限，不能越过安全
边界。

模型质量硬条件全部通过。8/12/15 色矢量和六张 8–15 色位图都与各自串行
参考具有相同的颜色数组、配方、材料顺序、几何语义、GLB 和 3MF 内容。
原生矢量 corpus 的面积差和体积差均为 0%，回退数量与原因不变。

位图最终结果中，四个代表样本提速约 13.6%–18.2%，一个样本提速 2.6%，
一个样本基本持平（慢 0.2%，属于测量噪声）。对曾出现假退化的样本做了
三组独立进程交错 A/B，自动模式分别快 13.3%、15.0%、14.8%。

矢量保守对比中，8/12/15 色分别提速约 35.2%、45.0%、13.5%。4 线程相对
2 线程只有 0–2% 的不稳定收益，部分运行反而更慢且峰值更高，因此位图、
矢量材质求解和矢量原生批次都拒绝 4 线程。这样得到的是可预测的 1/2
线程动态策略，而不是为了偶尔更快而放大内存尾部。

本分支只进入堆叠审核；Draft PR #540 合并、父层原生矢量分支完成变基前，
不得合并本 PR。
