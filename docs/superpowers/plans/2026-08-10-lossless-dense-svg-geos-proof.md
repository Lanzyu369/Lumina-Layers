# Lossless Dense SVG GEOS Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that two lookup-only GEOS 3.13.1 changes reduce the `IMG_7254.svg` global positive-buffer stage to at most four seconds while preserving the stock geometry exactly.

**Architecture:** Keep production code untouched during this proof. Version a reviewable GEOS patch and two Python tools: one builds a separately named proof library under ignored `.scratch`, and one calls stock Shapely plus the proof library through isolated GEOS C contexts, compares geometry fingerprints and symmetric differences, and writes reproducible evidence. Product integration receives a separate plan only after this proof gate passes.

**Tech Stack:** Python 3.12, Shapely 2.1.2 / GEOS 3.13.1, `ctypes`, CMake, C++17, pytest, JSON/Markdown evidence.

---

## File map

- `native/geos_buffer_fast/README.md`: pinned upstream version, LGPL boundary, patch purpose, and proof commands.
- `native/geos_buffer_fast/patches/geos-3.13.1-buffer-subgraph-index.patch`: lookup-only GEOS patch under test.
- `scripts/build_geos_buffer_fast_proof.py`: safe clone/apply/configure/build orchestration into `.scratch/geos_buffer_fast_proof`.
- `scripts/profile_geos_buffer_fast_proof.py`: real/synthetic geometry preparation, isolated GEOS C API adapter, timing, and exactness report.
- `tests/test_geos_buffer_fast_proof_unit.py`: unit coverage for build metadata, fingerprints, comparisons, reporting, and failure handling.
- `docs/superpowers/specs/2026-08-10-lossless-dense-svg-geos-proof-results.md`: measured proof outcome and go/no-go decision.

### Task 1: Lock the proof contracts with failing tests

**Files:**
- Create: `tests/test_geos_buffer_fast_proof_unit.py`
- Create: `scripts/profile_geos_buffer_fast_proof.py`

- [ ] **Step 1: Write failing fingerprint and parity tests**

Add tests equivalent to:

```python
from shapely.geometry import MultiPolygon, Polygon


def test_geometry_fingerprint_tracks_product_semantics() -> None:
    from scripts.profile_geos_buffer_fast_proof import geometry_fingerprint

    geometry = MultiPolygon([
        Polygon([(0, 0), (4, 0), (4, 4), (0, 4)], holes=[
            [(1, 1), (2, 1), (2, 2), (1, 2)],
        ]),
        Polygon([(10, 0), (12, 0), (12, 2), (10, 2)]),
    ])

    result = geometry_fingerprint(geometry)

    assert result["valid"] is True
    assert result["geom_type"] == "MultiPolygon"
    assert result["components"] == 2
    assert result["holes"] == 1
    assert result["area"] == 19.0
    assert result["bounds"] == [0.0, 0.0, 12.0, 4.0]


def test_compare_geometry_rejects_equal_area_with_changed_region() -> None:
    from scripts.profile_geos_buffer_fast_proof import compare_geometry

    stock = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    shifted = Polygon([(1, 0), (3, 0), (3, 2), (1, 2)])

    result = compare_geometry(stock, shifted)

    assert result["pass"] is False
    assert result["symmetric_difference_empty"] is False
    assert result["symmetric_difference_area"] == 4.0
```

- [ ] **Step 2: Run the focused test and verify red**

Run:

```bash
/Users/min/.cache/lumina-studio/venv-py312/bin/python -m pytest tests/test_geos_buffer_fast_proof_unit.py -v
```

Expected: FAIL because the proof helpers do not exist.

- [ ] **Step 3: Implement the minimal semantic helpers**

Implement `geometry_fingerprint()` and `compare_geometry()` with these rules:

```python
def compare_geometry(stock, candidate) -> dict[str, object]:
    difference = stock.symmetric_difference(candidate)
    stock_fp = geometry_fingerprint(stock)
    candidate_fp = geometry_fingerprint(candidate)
    same_structure = all(
        stock_fp[key] == candidate_fp[key]
        for key in ("valid", "geom_type", "components", "holes", "area", "bounds")
    )
    return {
        "pass": bool(difference.is_empty and same_structure),
        "symmetric_difference_empty": bool(difference.is_empty),
        "symmetric_difference_area": float(difference.area),
        "stock": stock_fp,
        "candidate": candidate_fp,
    }
```

Use SHA-256 of normalized WKB as diagnostic evidence, but do not make WKB order the product oracle.

- [ ] **Step 4: Run the focused test and verify green**

Run the Task 1 pytest command.

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/profile_geos_buffer_fast_proof.py tests/test_geos_buffer_fast_proof_unit.py
git commit -m "test(vector): define dense GEOS proof oracle"
```

### Task 2: Add a reproducible, scratch-only GEOS proof builder

**Files:**
- Create: `scripts/build_geos_buffer_fast_proof.py`
- Modify: `tests/test_geos_buffer_fast_proof_unit.py`
- Create: `native/geos_buffer_fast/README.md`

- [ ] **Step 1: Write failing build-metadata tests**

Assert all of the following:

```python
def test_proof_builder_is_pinned_and_scratch_only() -> None:
    from scripts.build_geos_buffer_fast_proof import (
        GEOS_REF,
        GEOS_REPOSITORY,
        PATCH_PATH,
        PROOF_ROOT,
    )

    assert GEOS_REF == "3.13.1"
    assert GEOS_REPOSITORY == "https://github.com/libgeos/geos.git"
    assert ".scratch/geos_buffer_fast_proof" in PROOF_ROOT.as_posix()
    assert PATCH_PATH.as_posix().endswith(
        "native/geos_buffer_fast/patches/geos-3.13.1-buffer-subgraph-index.patch"
    )
```

Also assert that `clone_command()`, `apply_command()`, `configure_command()`,
and `build_command()` return argument lists rather than shell strings, never
target a path outside `PROOF_ROOT`, configure `Release`, and disable GEOS tests,
documentation, and `geosop` for the benchmark build.

- [ ] **Step 2: Run the focused test and verify red**

Expected: FAIL because the builder module does not exist.

- [ ] **Step 3: Implement safe build orchestration**

Implement constants and commands using `pathlib` and `subprocess.run(check=True)`.
The CLI must support `--print-only` and `--rebuild`. `--rebuild` may remove only
the resolved path exactly equal to `PROOF_ROOT`; refuse broad, home, workspace,
or unresolved targets.

The normal sequence is:

```text
git clone --depth 1 --branch 3.13.1 https://github.com/libgeos/geos.git SOURCE_ROOT
git -C SOURCE_ROOT apply PATCH_PATH
cmake -S SOURCE_ROOT -B BUILD_ROOT -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DBUILD_DOCUMENTATION=OFF -DBUILD_GEOSOP=OFF
cmake --build BUILD_ROOT --config Release --parallel <bounded CPU count>
```

Resolve the built `libgeos_c` using platform suffixes and write a small JSON
manifest containing source ref, patch SHA-256, library path, and build time.

- [ ] **Step 4: Add the native proof README**

Document that:

- GEOS remains LGPL-2.1-or-later;
- this directory versions a patch and instructions, not a prebuilt library;
- proof artifacts live under ignored `.scratch`;
- the patch must not replace Shapely's process-wide GEOS;
- production packaging is out of scope until the proof passes.

- [ ] **Step 5: Run tests and print the build commands**

Run:

```bash
/Users/min/.cache/lumina-studio/venv-py312/bin/python -m pytest tests/test_geos_buffer_fast_proof_unit.py -v
/Users/min/.cache/lumina-studio/venv-py312/bin/python scripts/build_geos_buffer_fast_proof.py --print-only
```

Expected: PASS; printed paths stay under `.scratch/geos_buffer_fast_proof`.

- [ ] **Step 6: Commit**

```bash
git add scripts/build_geos_buffer_fast_proof.py tests/test_geos_buffer_fast_proof_unit.py native/geos_buffer_fast/README.md
git commit -m "build(vector): add GEOS fast-buffer proof harness"
```

### Task 3: Version the lookup-only GEOS patch

**Files:**
- Create: `native/geos_buffer_fast/patches/geos-3.13.1-buffer-subgraph-index.patch`
- Modify: `tests/test_geos_buffer_fast_proof_unit.py`

- [ ] **Step 1: Write a failing patch-contract test**

Read the patch as UTF-8 and assert it changes only:

- `src/operation/buffer/BufferBuilder.cpp`;
- `src/operation/buffer/PolygonBuilder.cpp`.

Assert the patch contains `freeHoleList.empty()`, `index::bintree::Bintree`,
`index::bintree::Interval`, an original-order map, and a candidate sort. Assert
it does not modify `OffsetCurveBuilder`, `computeNodedEdges`, precision models,
buffer parameters, or coordinate sequences.

- [ ] **Step 2: Run the patch-contract test and verify red**

Expected: FAIL because the patch does not exist.

- [ ] **Step 3: Add the no-free-hole shortcut**

The `PolygonBuilder.cpp` hunk must insert exactly this semantic guard after
shell/hole classification and before locator creation:

```cpp
if (freeHoleList.empty()) {
    return;
}
```

No shell mutation or `placeFreeHoles` call is removed when free holes exist.

- [ ] **Step 4: Add the processed-subgraph Y interval index**

The `BufferBuilder.cpp` hunk must:

```cpp
index::bintree::Bintree processedGraphIndex;
std::unordered_map<BufferSubgraph*, std::size_t> processedOrder;
```

For each subgraph, query the index with a stack-owned point interval, cast
results to `BufferSubgraph*`, sort by `processedOrder`, and pass that ordered
candidate vector to the unchanged `SubgraphDepthLocater`:

```cpp
index::bintree::Interval queryInterval(p->y, p->y);
std::vector<void*> rawCandidates;
processedGraphIndex.query(&queryInterval, &rawCandidates);
std::vector<BufferSubgraph*> candidates;
candidates.reserve(rawCandidates.size());
for (void* item : rawCandidates) {
    candidates.push_back(static_cast<BufferSubgraph*>(item));
}
std::sort(candidates.begin(), candidates.end(),
    [&processedOrder](BufferSubgraph* lhs, BufferSubgraph* rhs) {
        return processedOrder.at(lhs) < processedOrder.at(rhs);
    });
SubgraphDepthLocater locater(&candidates);
```

After depth and polygon work, insert the processed subgraph with:

```cpp
const Envelope* env = subgraph->getEnvelope();
index::bintree::Interval yInterval(env->getMinY(), env->getMaxY());
processedOrder.emplace(subgraph, i);
processedGraphIndex.insert(&yInterval, subgraph);
```

`SubgraphDepthLocater` retains its existing exact X/Y envelope filters, segment
tests, comparator, and depth return.

- [ ] **Step 5: Run patch-contract and hygiene tests**

Run the focused pytest command and:

```bash
git diff --check -- native/geos_buffer_fast scripts/build_geos_buffer_fast_proof.py tests/test_geos_buffer_fast_proof_unit.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add native/geos_buffer_fast/patches/geos-3.13.1-buffer-subgraph-index.patch tests/test_geos_buffer_fast_proof_unit.py
git commit -m "perf(vector): index GEOS buffer subgraph lookup"
```

### Task 4: Add the isolated GEOS C API profiler

**Files:**
- Modify: `scripts/profile_geos_buffer_fast_proof.py`
- Modify: `tests/test_geos_buffer_fast_proof_unit.py`

- [ ] **Step 1: Write failing backend/report tests**

Use a fake backend returning WKB and assert the runner:

- times stock and candidate separately;
- compares decoded Shapely geometries with `compare_geometry()`;
- includes library manifest and input SHA-256;
- marks the run failed when symmetric difference is non-empty, candidate time
  exceeds four seconds, or peak RSS exceeds `1.20x` stock;
- writes deterministic JSON and a concise Markdown summary.

- [ ] **Step 2: Run the focused test and verify red**

Expected: FAIL because the backend and report runner do not exist.

- [ ] **Step 3: Implement an isolated re-entrant GEOS C adapter**

Load the proof `libgeos_c` by absolute path with `ctypes.CDLL`. Bind only
re-entrant `_r` functions for context creation/destruction, WKB read/write,
buffer-parameter creation/destruction, parameter setters,
`GEOSBufferWithParams_r`, geometry destruction, and `GEOSFree_r`.

Each call must:

```text
create context
create WKB reader and buffer parameters
read input WKB
set quadrant segments, join style, and mitre limit
call positive GEOSBufferWithParams_r
write result WKB
destroy result/input/parameters/reader/context in finally blocks
```

Raise a typed `ProofLibraryError` for a null pointer or non-zero setter result.
Never pass Shapely geometry pointers into the proof library.

- [ ] **Step 4: Implement production-policy geometry extraction**

For an SVG input:

```python
processor = VectorProcessor(str(lut_path), color_mode)
processor._parse_expand_stroke_to_fill = False
shape_data, _, _ = processor._parse_svg(str(svg_path), target_width_mm)
clipped, _ = processor._clip_occlusion(shape_data, return_silhouette=True)
dense_geometry = max(
    (item["geometry"] for item in clipped),
    key=lambda geom: len(geom.geoms) if geom.geom_type == "MultiPolygon" else 1,
)
```

Record source-shape count, clipped-shape count, dense component count, and
coordinate count. Refuse a real proof unless the dense component count is at
least `2,048`.

- [ ] **Step 5: Implement CLI and report output**

Support:

```text
--input SVG
--target-width-mm 300
--lut PATH
--library PATH (defaults from build manifest)
--out-dir .scratch/geos_buffer_fast_proof/results
--skip-stock-timing only for diagnostics, never acceptance
```

Acceptance mode always runs stock and candidate from the same prepared WKB.

- [ ] **Step 6: Run unit tests and Python compilation**

```bash
/Users/min/.cache/lumina-studio/venv-py312/bin/python -m pytest tests/test_geos_buffer_fast_proof_unit.py -v
/Users/min/.cache/lumina-studio/venv-py312/bin/python -m py_compile scripts/build_geos_buffer_fast_proof.py scripts/profile_geos_buffer_fast_proof.py tests/test_geos_buffer_fast_proof_unit.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/profile_geos_buffer_fast_proof.py tests/test_geos_buffer_fast_proof_unit.py
git commit -m "perf(vector): profile patched GEOS buffer parity"
```

### Task 5: Build and verify the patched GEOS library

**Files:**
- No tracked build outputs
- Modify only tracked tests or patch if a proven defect is found

- [ ] **Step 1: Build from a clean proof root**

Run:

```bash
/Users/min/.cache/lumina-studio/venv-py312/bin/python scripts/build_geos_buffer_fast_proof.py --rebuild
```

Expected: manifest names GEOS `3.13.1`, the current patch SHA-256, and an
existing platform `libgeos_c` under `.scratch/geos_buffer_fast_proof`.

- [ ] **Step 2: Run focused upstream buffer tests**

Configure a second test build with `BUILD_TESTING=ON` and run GEOS buffer test
targets plus `ctest --output-on-failure -R "buffer|Buffer"`.

Expected: PASS. If the upstream target names differ, list them with
`ctest -N`, select every buffer-named test, and record the exact selected names
in the proof-results document.

- [ ] **Step 3: Run synthetic differential cases**

Run the profiler's synthetic mode against at least:

- 4,096 widely disjoint squares;
- interacting square chains;
- polygons with holes and nested shells;
- sharp mitres;
- tiny valid components;
- positive buffers that merge disconnected inputs.

Expected for every case: valid polygonal output, empty symmetric difference,
equal component/hole counts, equal area/bounds, and deterministic repeated
fingerprints.

- [ ] **Step 4: Stop on any semantic mismatch**

Do not proceed to the real acceptance run if any synthetic case fails. Preserve
the report, identify the first failing case, and return to the patch while
keeping global noding and geometry code unchanged.

### Task 6: Run the 300 mm real-sample proof and record the decision

**Files:**
- Create: `docs/superpowers/specs/2026-08-10-lossless-dense-svg-geos-proof-results.md`

- [ ] **Step 1: Run `IMG_7254.svg` acceptance**

```bash
/Users/min/.cache/lumina-studio/venv-py312/bin/python scripts/profile_geos_buffer_fast_proof.py \
  --input /Volumes/personal_folder/IMG_7254.svg \
  --target-width-mm 300 \
  --out-dir .scratch/geos_buffer_fast_proof/results/img_7254_300mm
```

Expected gate: candidate positive buffer `<= 4 s`, empty symmetric difference,
matching structure, and candidate peak RSS `<= 1.20x` stock.

- [ ] **Step 2: Repeat the patched candidate three times**

Reuse the same extracted input WKB, create a fresh GEOS context per run, and
record all three wall times plus median. Do not rerun the 78-88 second stock
buffer merely to calculate repeat timing.

Expected: all candidate fingerprints identical; median `<= 4 s`.

- [ ] **Step 3: Run the second supplied SVG**

Run the same acceptance command for:

```text
/Volumes/personal_folder/person_bd9869970839c02b0d0ac82e3756ccf1_20260725_074417_vector.svg
```

Expected: zero geometry difference and no performance regression against stock.

- [ ] **Step 4: Write the proof-results document**

Record machine/runtime versions, source hashes, component/coordinate counts,
stock and candidate timings, peak RSS, exactness fields, upstream/synthetic
test results, and one unambiguous decision:

- `GO`: all semantic, `4 s`, and memory gates pass; write the product-integration plan next.
- `NO-GO`: preserve reports, state the failed gate, and do not wire production code.

- [ ] **Step 5: Run proof hygiene checks**

```bash
git diff --check -- native/geos_buffer_fast scripts/build_geos_buffer_fast_proof.py scripts/profile_geos_buffer_fast_proof.py tests/test_geos_buffer_fast_proof_unit.py docs/superpowers/specs/2026-08-10-lossless-dense-svg-geos-proof-results.md
/Users/min/.cache/lumina-studio/venv-py312/bin/python -m pytest tests/test_geos_buffer_fast_proof_unit.py -v
```

Confirm no `api_server.py`, `start_all.py`, Vite, Vitest, or proof benchmark
process remains.

- [ ] **Step 6: Commit the evidence**

```bash
git add native/geos_buffer_fast scripts/build_geos_buffer_fast_proof.py scripts/profile_geos_buffer_fast_proof.py tests/test_geos_buffer_fast_proof_unit.py docs/superpowers/specs/2026-08-10-lossless-dense-svg-geos-proof-results.md
git commit -m "perf(vector): prove lossless indexed GEOS buffer"
```

## Proof acceptance gate

- Global positive-buffer candidate is `<= 4 s` cold and repeated median.
- Symmetric difference is empty on all synthetic and both real inputs.
- Area, bounds, validity, component count, and hole count match stock.
- Peak RSS is `<= 1.20x` stock.
- Upstream GEOS buffer tests and focused repository tests pass.
- Proof artifacts stay in ignored `.scratch`; tracked files contain only source,
  patch, tests, documentation, and reports.
- No production route is enabled by this plan.

On `GO`, immediately create the separate product-integration implementation
plan covering the optional module, fallback adapter, three-platform builds,
packaging, and full per-material/Z verification.
