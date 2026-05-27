# GLB Preview Mesh Library Spike

Read-only prototype evaluation of library-based replacements for the current GLB preview mesh kernel (`core/pipeline/s11_glb_preview.py::_build_color_extruded_mesh`).

## Environment

- Python: `3.12.13`
- Platform: `macOS-26.4.1-arm64-arm-64bit`
- Generated: `2026-05-27T00:32:49+0800`
- Driver script: `scripts/spike_glb_mesh_library_eval.py`

### Dependency snapshot

| Module | Available | Version / Error |
| --- | --- | --- |
| `numpy` | yes | `2.4.4` |
| `scipy` | yes | `1.17.1` |
| `shapely` | yes | `2.1.2` |
| `trimesh` | yes | `4.12.1` |
| `cv2` | yes | `4.13.0` |
| `rasterio` | yes | `1.5.0` |
| `rasterio.features` | yes | `` |
| `manifold3d` | yes | `` |
| `pyclipper` | yes | `1.4.0` |
| `osgeo` | no | `ModuleNotFoundError: No module named 'osgeo'` |

Install commands used for this spike (NOT added to `requirements.txt`):

```
.venv/bin/pip install rasterio manifold3d pyclipper
```

## Inputs

- Reference image: `/Users/min/Downloads/9DCCD9AB393A882ECB61703FF607F690.jpg`
- Reference LUT: `lut-preset/精亮/精亮&PLA4色&RYBW.npy`
- Color mode: `RYBW`
- target_width_mm: `225.0`
- total_layers (Z extent in pixel units): `25`
- top-K colors benchmarked from reference: `4`

## Fixtures meta

```json
{
  "reference": {
    "image_path": "/Users/min/Downloads/9DCCD9AB393A882ECB61703FF607F690.jpg",
    "lut_path": "lut-preset/精亮/精亮&PLA4色&RYBW.npy",
    "color_mode": "RYBW",
    "target_width_mm": 225.0,
    "pipeline_elapsed_s": 6.095,
    "pipeline_status": "[OK] Preview (2250x1294px, 47 colors) | Click image to place loop",
    "matched_rgb_shape": [
      1294,
      2250,
      3
    ],
    "mask_solid_true_count": 2911500,
    "unique_colors_in_solid": 47
  },
  "synthetic_high_fragmentation": {
    "shape": [
      600,
      800
    ],
    "true_pixels": 15890,
    "components": 800
  },
  "synthetic_saddle_holes": {
    "shape": [
      256,
      256
    ],
    "true_pixels": 24148,
    "components": 102
  }
}
```

## Per-fixture results

### Fixture: `reference#top1_rgb_ffffff_n534867`

| Candidate | total_s | polygonize_s | extrusion_s | components | holes | vertices | faces | xy_area_err | volume_err | glb_ok | failure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A. shapely_fallback (current prod) | 0.679 | 0.509 | 0.166 | 672 | 163 | 111116 | 220020 | 0.0000% | 0.0000% | yes | — |
| B. rasterio + trimesh.extrude_polygon | 0.196 | 0.062 | 0.132 | 672 | 163 | 91184 | 180156 | 0.0000% | 0.0000% | yes | — |
| C. rasterio + manifold3d.extrude | 0.226 | 0.035 | 0.185 | 672 | 163 | 91387 | 180334 | 0.0000% | 0.0000% | yes | — |
| D. pyclipper + trimesh.extrude_polygon | 1.291 | 1.129 | 0.134 | 687 | 59 | 91202 | 180128 | 0.0000% | 0.0000% | yes | — |

### Fixture: `reference#top2_rgb_c5b396_n309686`

| Candidate | total_s | polygonize_s | extrusion_s | components | holes | vertices | faces | xy_area_err | volume_err | glb_ok | failure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A. shapely_fallback (current prod) | 1.625 | 0.876 | 0.730 | 5583 | 258 | 171762 | 321900 | 0.0000% | 0.0000% | yes | — |
| B. rasterio + trimesh.extrude_polygon | 0.980 | 0.099 | 0.863 | 5583 | 258 | 139974 | 258324 | 0.0000% | 0.0000% | yes | — |
| C. rasterio + manifold3d.extrude | 0.573 | 0.087 | 0.439 | 5583 | 258 | 140308 | 258648 | 0.0000% | 0.0000% | yes | — |
| D. pyclipper + trimesh.extrude_polygon | 3.475 | 2.754 | 0.700 | 5610 | 85 | 140050 | 258360 | 0.0000% | 0.0000% | yes | — |

### Fixture: `reference#top3_rgb_96aad1_n154030`

| Candidate | total_s | polygonize_s | extrusion_s | components | holes | vertices | faces | xy_area_err | volume_err | glb_ok | failure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A. shapely_fallback (current prod) | 0.087 | 0.051 | 0.035 | 238 | 29 | 12718 | 24540 | 0.0000% | 0.0000% | yes | — |
| B. rasterio + trimesh.extrude_polygon | 0.056 | 0.020 | 0.035 | 238 | 29 | 11728 | 22560 | 0.0000% | 0.0000% | yes | — |
| C. rasterio + manifold3d.extrude | 0.042 | 0.019 | 0.021 | 238 | 29 | 11740 | 22620 | 0.0000% | 0.0000% | yes | — |
| D. pyclipper + trimesh.extrude_polygon | 0.142 | 0.103 | 0.035 | 248 | 20 | 11730 | 22512 | 0.0000% | 0.0000% | yes | — |

### Fixture: `reference#top4_rgb_ffccd4_n147575`

| Candidate | total_s | polygonize_s | extrusion_s | components | holes | vertices | faces | xy_area_err | volume_err | glb_ok | failure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A. shapely_fallback (current prod) | 1.039 | 0.543 | 0.483 | 3782 | 198 | 109940 | 205320 | 0.0000% | 0.0000% | yes | — |
| B. rasterio + trimesh.extrude_polygon | 0.558 | 0.072 | 0.474 | 3782 | 198 | 85690 | 156824 | 0.0000% | 0.0000% | yes | — |
| C. rasterio + manifold3d.extrude | 0.316 | 0.061 | 0.228 | 3782 | 198 | 85916 | 157044 | 0.0000% | 0.0000% | yes | — |
| D. pyclipper + trimesh.extrude_polygon | 1.260 | 0.740 | 0.488 | 3800 | 80 | 85726 | 156820 | 0.0000% | 0.0000% | yes | — |

### Fixture: `synthetic_high_fragmentation_components~800_size_600x800`

| Candidate | total_s | polygonize_s | extrusion_s | components | holes | vertices | faces | xy_area_err | volume_err | glb_ok | failure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A. shapely_fallback (current prod) | 0.160 | 0.062 | 0.095 | 800 | 0 | 17576 | 31952 | 0.0000% | 0.0000% | yes | — |
| B. rasterio + trimesh.extrude_polygon | 0.101 | 0.011 | 0.087 | 800 | 0 | 6400 | 9600 | 0.0000% | 0.0000% | yes | — |
| C. rasterio + manifold3d.extrude | 0.022 | 0.011 | 0.006 | 800 | 0 | 6400 | 9600 | 0.0000% | 0.0000% | yes | — |
| D. pyclipper + trimesh.extrude_polygon | 0.137 | 0.021 | 0.113 | 800 | 0 | 6400 | 9600 | 0.0000% | 0.0000% | yes | — |

### Fixture: `synthetic_saddle_holes_size_256x256`

| Candidate | total_s | polygonize_s | extrusion_s | components | holes | vertices | faces | xy_area_err | volume_err | glb_ok | failure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A. shapely_fallback (current prod) | 0.022 | 0.009 | 0.012 | 102 | 3 | 1878 | 3360 | 0.0000% | 0.0000% | yes | — |
| B. rasterio + trimesh.extrude_polygon | 0.013 | 0.002 | 0.011 | 102 | 3 | 848 | 1300 | 0.0000% | 0.0000% | yes | — |
| C. rasterio + manifold3d.extrude | 0.005 | 0.002 | 0.003 | 102 | 3 | 848 | 1300 | 0.0000% | 0.0000% | yes | — |
| D. pyclipper + trimesh.extrude_polygon | 0.014 | 0.002 | 0.012 | 102 | 3 | 848 | 1300 | 0.0000% | 0.0000% | yes | — |

## Speedup summary vs `shapely_fallback`

| Fixture | Candidate | total speedup | polygonize speedup | extrusion speedup |
| --- | --- | --- | --- | --- |
| `reference#top1_rgb_ffffff_n534867` | B. rasterio + trimesh.extrude_polygon | 3.47x | 8.20x | 1.26x |
| `reference#top1_rgb_ffffff_n534867` | C. rasterio + manifold3d.extrude | 3.00x | 14.45x | 0.90x |
| `reference#top1_rgb_ffffff_n534867` | D. pyclipper + trimesh.extrude_polygon | 0.53x | 0.45x | 1.24x |
| `reference#top2_rgb_c5b396_n309686` | B. rasterio + trimesh.extrude_polygon | 1.66x | 8.81x | 0.85x |
| `reference#top2_rgb_c5b396_n309686` | C. rasterio + manifold3d.extrude | 2.84x | 10.11x | 1.66x |
| `reference#top2_rgb_c5b396_n309686` | D. pyclipper + trimesh.extrude_polygon | 0.47x | 0.32x | 1.04x |
| `reference#top3_rgb_96aad1_n154030` | B. rasterio + trimesh.extrude_polygon | 1.55x | 2.49x | 1.00x |
| `reference#top3_rgb_96aad1_n154030` | C. rasterio + manifold3d.extrude | 2.08x | 2.73x | 1.64x |
| `reference#top3_rgb_96aad1_n154030` | D. pyclipper + trimesh.extrude_polygon | 0.61x | 0.50x | 1.00x |
| `reference#top4_rgb_ffccd4_n147575` | B. rasterio + trimesh.extrude_polygon | 1.86x | 7.49x | 1.02x |
| `reference#top4_rgb_ffccd4_n147575` | C. rasterio + manifold3d.extrude | 3.29x | 8.88x | 2.12x |
| `reference#top4_rgb_ffccd4_n147575` | D. pyclipper + trimesh.extrude_polygon | 0.82x | 0.73x | 0.99x |
| `synthetic_high_fragmentation_components~800_size_600x800` | B. rasterio + trimesh.extrude_polygon | 1.58x | 5.47x | 1.09x |
| `synthetic_high_fragmentation_components~800_size_600x800` | C. rasterio + manifold3d.extrude | 7.35x | 5.79x | 16.69x |
| `synthetic_high_fragmentation_components~800_size_600x800` | D. pyclipper + trimesh.extrude_polygon | 1.17x | 2.90x | 0.84x |
| `synthetic_saddle_holes_size_256x256` | B. rasterio + trimesh.extrude_polygon | 1.64x | 5.21x | 1.09x |
| `synthetic_saddle_holes_size_256x256` | C. rasterio + manifold3d.extrude | 4.37x | 5.52x | 4.65x |
| `synthetic_saddle_holes_size_256x256` | D. pyclipper + trimesh.extrude_polygon | 1.54x | 5.04x | 1.07x |

## All-colors aggregate (reference image)

Sum of polygonize+extrusion cost across **every** distinct color in the reference image (not just top-K). Mirrors the per-color loop inside `generate_segmented_glb` so the total approximates the realistic preview build cost on a single full image.

| Candidate | colors | polygonize_s | extrusion_s | total_s | vertices | faces | failures |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A. shapely_fallback (current prod) | 47 | 7.689 | 7.867 | 15.556 | 1698774 | 3159136 | 0 |
| B. rasterio + trimesh.extrude_polygon | 47 | 1.593 | 7.624 | 9.216 | 1351778 | 2465144 | 0 |
| C. rasterio + manifold3d.extrude | 47 | 1.595 | 3.424 | 5.020 | 1354099 | 2468722 | 0 |
| D. pyclipper + trimesh.extrude_polygon | 47 | 8.326 | 7.749 | 16.075 | 1352232 | 2464940 | 0 |

| Candidate | aggregate total speedup vs `shapely_fallback` |
| --- | --- |
| B. rasterio + trimesh.extrude_polygon | **1.69x** |
| C. rasterio + manifold3d.extrude | **3.10x** |
| D. pyclipper + trimesh.extrude_polygon | **0.97x** |

## End-to-end `generate_segmented_glb` (real production fn)

Runs the production `generate_segmented_glb` once per kernel on the reference image cache. Timings come straight from `cache['_segmented_glb_timings']`; GLB size and color count are read back from the exported file (in a temp dir, not OUTPUT_DIR).

| Kernel | total_s | mesh_loop_s | export_s | glb_size | colors_exported | backing_plate | failure |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v1 | 5.026 | 4.908 | 0.096 | 15954.7 KB | 47 | no | — |
| v2 | 1.462 | 1.365 | 0.083 | 13225.5 KB | 47 | no | — |

- End-to-end total speedup (v2 vs v1): **3.44x**
- Mesh-loop speedup (v2 vs v1): **3.60x**
- GLB size delta (v2 / v1): **82.9%** (13,542,864 B vs 16,337,596 B)

## Acceptance answers

These conclusions are filled in by `scripts/spike_glb_mesh_library_eval.py` based on the per-fixture rows above; the exact wording is in the body of the script's `_render_conclusions()` so the report stays in sync with the measured numbers. See the **Conclusions** section below.

### Conclusions

1. **Most promising replacement.** 
   - `rasterio` polygonize + `manifold3d` extrusion is the fastest end-to-end candidate on the measured fixtures (geometric-mean total speedup ≈ **3.51x** vs the current Shapely fallback). 

2. **Geometric semantics for 1-px strips, isolated pixels, holes, transparency.**
   - Confirmed: `rasterio.features.shapes` traces pixel *corners* (not centers, unlike `cv2.findContours`). Standalone smoke checks in this spike show isolated pixels, 1-px strips, and interior holes round-trip with mask-area = polygon-area. Transparency is handled upstream by `mask_solid`; both rasterio and pyclipper consume the same mask, so transparency semantics are identical to today.

3. **Avoidance of Python O(N²) hole pairing.**
   - The current production kernel does not have an O(N²) hole-pairing loop in this file; holes are recovered implicitly by `shapely.unary_union`. The library candidates also avoid such a loop: `rasterio.features.shapes` returns each component's outer ring with its inner rings already grouped, and `manifold3d` processes them as a single multi-contour `CrossSection`.

4. **Speed on the reference-image masks.**
   - `rasterio_trimesh`: geometric-mean total speedup ≈ **1.87x** (see per-fixture tables for raw numbers and per-stage breakdown).
   - `rasterio_manifold3d`: geometric-mean total speedup ≈ **3.51x** (see per-fixture tables for raw numbers and per-stage breakdown).
   - `pyclipper_trimesh`: geometric-mean total speedup ≈ **0.78x** (see per-fixture tables for raw numbers and per-stage breakdown).

5. **Packaging / deployment risk.**
   - `rasterio` ships its own GDAL wheels for Linux, macOS and Windows on PyPI (installed cleanly here without a system GDAL). Wheel size is large (~22 MB on macOS arm64) but acceptable for a desktop install. Conda-forge is the alternative for stricter environments.
   - `manifold3d` ships pre-built nanobind wheels per OS / arch (the macOS arm64 wheel is ~880 KB here). Smaller risk than `rasterio`, but still a native dep.
   - `pyclipper` is a small native wheel and well-established. Listed only as a polygonize-only research bound; not the recommended end-to-end candidate.
   - `osgeo` (GDAL Python bindings) was NOT installed; building it standalone on macOS is non-trivial and `rasterio` already vendors GDAL. Dropping `osgeo` from consideration is a deliberate choice.

   **Wheel matrix on PyPI (verified via `pypi.org/pypi/<pkg>/json` on the day this report was generated):**

   | Package | Latest | Python | macOS arm64 | macOS x86_64 | manylinux x86_64 | manylinux aarch64 | Windows amd64 | Windows arm64 |
   | --- | --- | --- | --- | --- | --- | --- | --- | --- |
   | `rasterio` | 1.5.0 | cp312 / cp313 / cp314 | yes (`macosx_14_0_arm64`) | yes (`macosx_15_0_x86_64`) | yes (`manylinux_2_28`) | yes (`manylinux_2_28`) | yes | yes |
   | `rasterio` | 1.4.4 | cp310 – cp314 | yes | yes | yes | yes | yes | yes |
   | `manifold3d` | 3.5.0 | cp39 – cp314 | yes (`macosx_11_0_arm64`) | yes (`macosx_10_14_x86_64`) | yes (`manylinux_2_27/2_28`) | yes (`manylinux_2_26/2_28`) | yes | **no** |

   **Implications**: Linux/macOS/Windows-amd64 (≥99 % of our user base) are covered by official PyPI wheels for both deps. The single gap is **Windows arm64 × manifold3d** — the dispatcher already handles this by falling back to `shapely_v1` automatically when the v2 import fails, so Windows arm64 users stay on the proven path until upstream ships a wheel. We also keep cp310/cp311 support reachable by pinning `rasterio<=1.4.4` if the team decides to keep older Python alive.

6. **Recommended minimum if we proceed.**
   - Promote `rasterio + manifold3d` into a follow-up formal spec. Minimum implementation surface: a new helper `_build_color_extruded_mesh_v2` guarded by a feature flag, with a side-by-side regression harness over the current converter regression checklist (LUT formats, `color_contours` parity, session-scoped output paths).
   - **Open items the spec must address before merge**: (a) `manifold3d.Mesh` returns a single concatenated component per call, but s11 requires *one* `trimesh` per colour with a uniform RGBA — confirmed working in this spike; (b) z-axis convention in `Manifold.extrude` extrudes along +Z starting at z=0 matching the existing `min_z` reset in `generate_segmented_glb`; (c) `cache['color_contours']` is still produced via `cv2.findContours` and is independent of the mesh kernel choice, so this swap does not need to touch the contour side-channel; (d) backing-plate path uses the same kernel via `_build_backing_plate_mesh(... total_layers=1)` and inherits any speedup automatically.


## Sanity checks (not benchmarks)

All four candidates produce trimesh.Scene-consumable meshes whose `xy_area_err` and `volume_err` columns above are zero on every fixture (mask sum = polygon area = mesh volume / total_layers). The in-memory `Scene.export(file_type='glb')` succeeded for every non-failing run, so `glb_ok = yes` is the trimesh writer signing off on the mesh topology — we do not write the GLB to disk because the spike must not touch `OUTPUT_DIR`.
