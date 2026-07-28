# Vector Single-Task Multicore Implementation Plan

> Execute this plan with strict test-driven development. Optimization order is:
> eliminate repeated work, bound memory, then parallelize independent native
> blocks. Output quality is an invariant.

**Goal:** Reduce complex Material Archive SVG preview and generation time while
preserving source-fill identity, recipe/layer order, preview arrays, material
slots, and final canonical geometry exactly.

**Architecture:** Reuse deterministic inverse-refinement workspaces per material
subset, replace quadratic full-matrix neighbor discovery with an exact KD-tree
pair query, calculate top-K candidate rows in bounded blocks, and optionally
run independent subset/block work through the shared vector parallelism policy.
All results are written back by stable row index. Parsing, scene mutation, 3MF,
and GLB ownership stay serialized.

**Primary files:**

- Modify: `core/material_inverse_refinement.py`
- Modify: `core/material_cache.py`
- Modify: `core/material_candidate_cache.py`
- Modify: `core/vector_matchers.py`
- Modify: `tests/test_material_inverse_refinement_unit.py`
- Create: `tests/test_material_neighbor_coherence_unit.py`
- Modify: `tests/test_material_candidate_cache_unit.py`
- Modify: `tests/test_vector_material_matcher_unit.py`
- Reuse: `core/task_parallelism.py`
- Read/compare:
  `.scratch/converter-multicore/baseline/native-vector-*/profile.json`,
  `vector.speedscope.json`, and the cProfile reports

## Evidence and decision

The quality-locked corpus is `梵高星空款式西森猫猫.svg`: 13,496 parsed shapes,
14,010 clipped/matched shapes, 9,503 unique fill colors, 299 mm, 12 selected
Material Archive colors, 10 layers, and a 1600 × 2241 preview.

| Stage/function | Wall time | Share | Evidence | Decision |
|---|---:|---:|---|---|
| Vector preview total | 276.709 s native | 100% | Low-interference run | Quality/performance oracle |
| `analyze_svg` | 271.586 s | 98.1% | Native stage timing | Optimize internals |
| `solve_for_fills` | 286.232 s sampled | 89.6% of sampled run | Statistical stack | Primary boundary |
| `refine_material_matches` | 146.313 s sampled | 45.7% | Statistical stack | Deduplicate subset work, then thread groups |
| `_neighbor_coherence_refine` | 138.598 s sampled | 43.3% | Statistical stack | Remove full matrices, block top-K work |
| `argpartition` | 78.436 s sampled | 24.5% | Statistical stack | Exact blockwise execution |
| SVG parse | 10.463 s native | 3.8% | Native stage timing | Not first parallel boundary |
| Occlusion | 5.828 s native | 2.1% | Native stage timing | Keep serialized in this change |

Generation is 334.380 s native with `mesh_total_s=301.213`, extrusion/assembly
`43.089`, 3MF `9.544`, and GLB `17.643`. Its retained final scene has 12
material geometries and a complete canonical triangle fingerprint.

Vector root cause: `solve_for_fills` dominates because inverse refinement
regenerates the same deterministic candidate workspace for thousands of rows
and neighbor coherence allocates/sorts global distance matrices; the smallest
experiment is one exact workspace per material subset plus blockwise
row-independent top-K calculation.

## Acceptance criteria

- Preview `matched_rgb`, `material_matrix`, `mask_solid`, slot names, and layer
  recipes are byte-identical to serial.
- Generate canonical geometry snapshot is identical for all 12 material
  geometries.
- Candidate generation occurs once per unique `(subset, depth, budget, seed)`
  instead of once per color.
- Neighbor pair order and top-K candidate rows match the legacy computation
  exactly, including strict `< threshold` filtering.
- Requested parallelism one runs the optimized serial reference without an
  executor.
- Worker results are committed by stable target-row index.
- No full `C × C` neighbor distance matrix is allocated.
- No full `C × K` candidate distance matrix is retained; block size is bounded
  by a declared memory budget.
- Complex preview is at least 35% faster than the 276.709 s native baseline;
  retain changes below that threshold only if they materially reduce memory and
  do not regress wall time.
- Peak RSS does not exceed the 6.90 GiB native generation baseline.

## Task 1: Reuse inverse-refinement workspaces

**Red test**

Extend `tests/test_material_inverse_refinement_unit.py`:

- compute two different target rows independently as the serial reference;
- batch the same rows while spying on `generate_candidate_recipes`;
- assert byte-identical matched RGB/recipes and exact Delta-E;
- assert only two candidate generations for one shared subset (bottom and top),
  not two per target;
- include multiple subsets and verify one workspace per unique subset.

Run and verify the call-count assertion fails.

**Implementation**

In `core/material_inverse_refinement.py`:

- add a private immutable workspace containing bottom/top recipes, predicted
  bottom colors, top affines, and the bottom KD-tree;
- derive stable subset keys once;
- group target row indices without changing their output positions;
- build/discard one workspace per group in serial mode;
- add backward-compatible keyword-only `parallelism: int = 1`;
- when `parallelism > 1` and there are enough groups, execute whole groups in a
  `ThreadPoolExecutor`, then assign results by original row index;
- never mutate shared material arrays or output arrays in workers.

Run all inverse-refinement and candidate-runtime tests.

## Task 2: Replace quadratic neighbor discovery exactly

**Red tests**

Create `tests/test_material_neighbor_coherence_unit.py`:

- compare the new neighbor-pair helper with the legacy full `cdist` + nested
  loop for seeded random Lab arrays;
- include exact-threshold rows and assert strict `< 20.0`;
- assert lexicographic `(i, j)` ordering;
- compare blockwise top-K indices/distances with the legacy full-matrix
  `cdist` + `np.argpartition`;
- cover block sizes one, uneven final block, all-candidates (`K <= top_k`), and
  parallelism 1/2/4;
- compare the complete coherence output between block sizes and worker counts.

Expected red: the helpers and optional parallelism do not exist.

**Implementation**

In `core/material_cache.py`:

- use `cKDTree.query_pairs` only to find candidate pairs;
- recompute exact Euclidean distances and filter with strict `< threshold`;
- lexicographically sort pairs to preserve the legacy traversal;
- compute top-K rows in bounded target blocks;
- use the same `cdist` and `np.argpartition(..., top_k, axis=1)` operations per
  block so row semantics stay unchanged;
- retain only `(C, top_k)` indices/distances;
- optionally execute independent blocks in threads and restore slice order.

Do not change coherence scoring, tie comparisons, penalty caps, or cascading
`refined` behavior.

## Task 3: Propagate vector worker budgets

**Red tests**

In `tests/test_material_candidate_cache_unit.py` and
`tests/test_vector_material_matcher_unit.py`:

- assert candidate-runtime `lookup(..., parallelism=N)` forwards N to both
  refinement phases;
- assert the vector matcher resolves `LUMINA_VECTOR_PARALLELISM` and forwards
  the effective count only when the runtime signature accepts it;
- verify legacy/mock runtimes without the keyword remain compatible;
- verify invalid environment values fall back without changing matches.

**Implementation**

- add backward-compatible `parallelism: int = 1` to candidate-runtime lookup;
- pass it to inverse refinement and neighbor coherence;
- in `MaterialArchiveVectorMatcher.solve_for_fills`, resolve the shared vector
  policy from unique-color work items and include the keyword through the
  existing signature filter;
- record effective parallelism in DEBUG/structured metadata without logging
  per-color INFO.

## Task 4: Exact semantic and 1/2/4/8 measurements

Run focused tests:

```bash
.venv/bin/python -m pytest \
  tests/test_material_inverse_refinement_unit.py \
  tests/test_material_neighbor_coherence_unit.py \
  tests/test_material_candidate_cache_unit.py \
  tests/test_vector_material_matcher_unit.py \
  tests/test_converter_multicore_profile_unit.py -v
```

Run the complex SVG preview with requested 1/2/4/8, `LUMINA_MAX_WORKERS=1`,
BLAS/OpenMP threads fixed at one, cProfile disabled, and separate reports.
Compare each semantic snapshot byte-for-byte with the serial optimized result
and the pre-change baseline.

Run generation for the selected auto/fastest-safe worker count and compare all
12 canonical geometry summaries with the pre-change native generation.

Also run:

- `945695877_20260622_232544_vector.svg`;
- `mmexport1784271438721.svg`;
- one tiny SVG that remains serial;
- two concurrent outer tasks to verify fairness and peak RSS.

## Task 5: Regression gates and commit

Run:

```bash
.venv/bin/python -m pytest tests/test_vector_preview_timings_unit.py \
  tests/test_pipeline_vector_material_archive_unit.py \
  tests/test_vector_matched_rgb_overrides_unit.py -q
.venv/bin/python -m pytest tests/test_perf_golden.py -v
python scripts/run_vitest.py run
git diff --check
```

Scan all touched UTF-8 files for mojibake. Do not retain a parallel path that
fails to beat optimized serial at its break-even workload.
