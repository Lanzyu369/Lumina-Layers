# GLB Preview Mesh Kernel: bitmap multi-size × multi-mode benchmark

Read-only matrix benchmark of `core/pipeline/s11_glb_preview.py`'s v1 (Shapely) vs v2 (rasterio + manifold3d) per-color extrusion kernel on a single bitmap. Same code path, different env (`LUMINA_GLB_KERNEL`). No production files modified by this report.

## 1. Executive Summary

- **20 mode×size cases**, geometric-mean speedup: `s11_mesh_loop_s` **3.27x**, `s11_s` **3.22x**.
- **Best case**: `5-Color-Extended` @ 300 mm — v1 loop 36.39 s → v2 7.89 s (speedup 4.61x).
- **Worst case**: `4-Color RYBW` @ 75 mm — v1 loop 13.50 s → v2 5.02 s (speedup 2.69x).
- **No v2 → v1 fallback observed across the matrix.**

## 2. Environment

- Commit SHA: `98e18df57d1e4fdd6a52d4cef4ac8a81363f57b7`
- Generated at: `2026-05-27T03:21:05+0800`
- Python: `3.12.13`
- Platform: `macOS-26.4.1-arm64-arm-64bit`
- Dependencies:
  - `rasterio` = `1.5.0`
  - `manifold3d` = `3.5.0`
  - `shapely` = `2.1.2`
  - `trimesh` = `4.12.1`
  - `cv2` = `4.13.0`
  - `numpy` = `2.4.4`
  - `scipy` = `1.17.1`
- Hard stop: per-case timeout = 900s; GLB / vertex / face SHALL NOT exceed v1 × 1.10x; v2 SHALL NOT regress to v1 (fallback would invalidate the comparison).

## 3. Input

- Image path: `/Users/min/CascadeProjects/Lumina-studio/test_images/benchmark.jpg`
- Image dimensions: `3834x2205 px`, file `6.57 MB` (JPEG)
- Modes / LUTs:
  - `4-Color RYBW` → `lut-preset/精亮/精亮&PLA4色&RYBW.npy`
  - `BW` → `lut-preset/赛纳/赛纳&2色PLA&BW-白-黑.npy`
  - `8-Color` → `lut-preset/精亮/精亮&PLA8色.npy`
  - `6-Color` → `lut-preset/精亮/精亮&PLA6色&黑 白 黄 绿 红 蓝.npy`
  - `5-Color-Extended` → `lut-preset/Aliz/PETG/5色/Aliz&PETG&5color&红-黄-蓝-白-黑-20260304.npy`
- target_width_mm list: [75.0, 150.0, 225.0, 300.0]
- modeling_mode: HIGH_FIDELITY (single mode for the matrix)

## 4. Matrix Table

| mode | width_mm | kernel | total_s | s11_s | s11_loop_s | s11_export_s | glb_MB | vertices | faces | colors | fallback | warnings |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `4-Color RYBW` | 75 | v1 | 19.09 | 13.70 | 13.50 | 0.13 | 12.76 | 349,100 | 646,648 | 44 | no | — |
| `4-Color RYBW` | 75 | v2 | 10.70 | 5.15 | 5.02 | 0.10 | 10.37 | 286,988 | 521,188 | 44 | no | — |
| `4-Color RYBW` | 150 | v1 | 27.97 | 19.08 | 18.91 | 0.11 | 14.76 | 409,632 | 740,488 | 46 | no | — |
| `4-Color RYBW` | 150 | v2 | 15.39 | 5.79 | 5.65 | 0.10 | 12.22 | 343,275 | 607,230 | 46 | no | — |
| `4-Color RYBW` | 225 | v1 | 37.27 | 20.41 | 20.24 | 0.12 | 15.37 | 428,836 | 768,660 | 44 | no | — |
| `4-Color RYBW` | 225 | v2 | 23.33 | 5.95 | 5.82 | 0.10 | 12.77 | 360,642 | 632,084 | 44 | no | — |
| `4-Color RYBW` | 300 | v1 | 49.58 | 21.94 | 21.76 | 0.12 | 15.83 | 442,624 | 790,116 | 46 | no | — |
| `4-Color RYBW` | 300 | v2 | 33.96 | 6.35 | 6.21 | 0.10 | 13.25 | 375,256 | 654,972 | 46 | no | — |
| `BW` | 75 | v1 | 13.12 | 8.89 | 8.79 | 0.06 | 8.42 | 227,810 | 430,980 | 18 | no | — |
| `BW` | 75 | v2 | 7.51 | 3.20 | 3.12 | 0.05 | 7.20 | 195,992 | 366,408 | 18 | no | — |
| `BW` | 150 | v1 | 16.96 | 11.46 | 11.34 | 0.07 | 9.84 | 268,248 | 501,208 | 17 | no | — |
| `BW` | 150 | v2 | 8.90 | 3.71 | 3.63 | 0.06 | 8.49 | 232,835 | 430,526 | 17 | no | — |
| `BW` | 225 | v1 | 22.04 | 11.61 | 11.50 | 0.07 | 9.67 | 264,280 | 491,960 | 16 | no | — |
| `BW` | 225 | v2 | 13.30 | 3.80 | 3.71 | 0.06 | 8.38 | 230,226 | 424,100 | 16 | no | — |
| `BW` | 300 | v1 | 30.10 | 12.93 | 12.80 | 0.08 | 10.40 | 284,944 | 527,468 | 18 | no | — |
| `BW` | 300 | v2 | 21.19 | 4.24 | 4.14 | 0.08 | 9.03 | 248,918 | 456,028 | 18 | no | — |
| `8-Color` | 75 | v1 | 23.41 | 16.20 | 16.02 | 0.11 | 13.43 | 367,578 | 679,860 | 55 | no | — |
| `8-Color` | 75 | v2 | 13.16 | 5.72 | 5.58 | 0.10 | 10.85 | 300,212 | 544,364 | 55 | no | — |
| `8-Color` | 150 | v1 | 35.02 | 22.15 | 21.96 | 0.13 | 15.73 | 437,182 | 787,964 | 57 | no | — |
| `8-Color` | 150 | v2 | 20.67 | 6.77 | 6.62 | 0.12 | 12.95 | 364,434 | 642,072 | 57 | no | — |
| `8-Color` | 225 | v1 | 50.54 | 25.95 | 25.73 | 0.15 | 16.69 | 466,322 | 832,720 | 58 | no | — |
| `8-Color` | 225 | v2 | 33.47 | 7.94 | 7.76 | 0.14 | 13.74 | 389,154 | 678,112 | 58 | no | — |
| `8-Color` | 300 | v1 | 76.68 | 28.35 | 28.13 | 0.15 | 17.11 | 480,114 | 851,460 | 59 | no | — |
| `8-Color` | 300 | v2 | 48.71 | 7.41 | 7.24 | 0.13 | 14.27 | 405,636 | 702,148 | 59 | no | — |
| `6-Color` | 75 | v1 | 24.91 | 17.19 | 17.01 | 0.12 | 13.32 | 364,728 | 674,384 | 50 | no | — |
| `6-Color` | 75 | v2 | 12.90 | 6.08 | 5.95 | 0.10 | 10.76 | 298,020 | 540,112 | 50 | no | — |
| `6-Color` | 150 | v1 | 34.04 | 22.26 | 22.07 | 0.13 | 15.29 | 424,512 | 766,904 | 48 | no | — |
| `6-Color` | 150 | v2 | 19.29 | 7.11 | 6.95 | 0.12 | 12.59 | 353,930 | 625,260 | 48 | no | — |
| `6-Color` | 225 | v1 | 47.49 | 24.93 | 24.72 | 0.14 | 16.18 | 451,498 | 808,352 | 51 | no | — |
| `6-Color` | 225 | v2 | 30.06 | 7.39 | 7.23 | 0.12 | 13.39 | 378,527 | 661,958 | 51 | no | — |
| `6-Color` | 300 | v1 | 69.74 | 27.37 | 27.16 | 0.15 | 16.57 | 463,978 | 826,276 | 50 | no | — |
| `6-Color` | 300 | v2 | 45.22 | 7.55 | 7.38 | 0.13 | 13.79 | 391,152 | 680,176 | 50 | no | — |
| `5-Color-Extended` | 75 | v1 | 25.45 | 17.50 | 17.32 | 0.12 | 13.43 | 367,744 | 679,860 | 55 | no | — |
| `5-Color-Extended` | 75 | v2 | 14.32 | 6.33 | 6.19 | 0.10 | 10.86 | 300,588 | 544,728 | 55 | no | — |
| `5-Color-Extended` | 150 | v1 | 37.42 | 24.09 | 23.88 | 0.15 | 15.90 | 442,160 | 796,564 | 56 | no | — |
| `5-Color-Extended` | 150 | v2 | 20.25 | 7.39 | 7.24 | 0.12 | 13.08 | 368,463 | 648,642 | 56 | no | — |
| `5-Color-Extended` | 225 | v1 | 51.85 | 26.35 | 26.13 | 0.16 | 16.62 | 464,790 | 828,920 | 58 | no | — |
| `5-Color-Extended` | 225 | v2 | 32.83 | 7.63 | 7.45 | 0.13 | 13.72 | 388,766 | 676,688 | 58 | no | — |
| `5-Color-Extended` | 300 | v1 | 87.28 | 36.63 | 36.39 | 0.16 | 17.22 | 483,440 | 856,532 | 58 | no | — |
| `5-Color-Extended` | 300 | v2 | 46.18 | 8.07 | 7.89 | 0.13 | 14.35 | 408,412 | 706,220 | 58 | no | — |

## 5. Speedup Table (v1 → v2, warm median)

| mode | width_mm | s11_loop speedup | s11_s speedup | total_s speedup | glb ratio | vertex ratio | face ratio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `4-Color RYBW` | 75 | 2.69x | 2.66x | 1.78x | 81.32% | 82.21% | 80.60% |
| `4-Color RYBW` | 150 | 3.34x | 3.30x | 1.82x | 82.80% | 83.80% | 82.00% |
| `4-Color RYBW` | 225 | 3.48x | 3.43x | 1.60x | 83.06% | 84.10% | 82.23% |
| `4-Color RYBW` | 300 | 3.50x | 3.46x | 1.46x | 83.73% | 84.78% | 82.90% |
| `BW` | 75 | 2.81x | 2.78x | 1.75x | 85.46% | 86.03% | 85.02% |
| `BW` | 150 | 3.12x | 3.09x | 1.90x | 86.29% | 86.80% | 85.90% |
| `BW` | 225 | 3.10x | 3.06x | 1.66x | 86.60% | 87.11% | 86.21% |
| `BW` | 300 | 3.10x | 3.05x | 1.42x | 86.85% | 87.36% | 86.46% |
| `8-Color` | 75 | 2.87x | 2.83x | 1.78x | 80.80% | 81.67% | 80.07% |
| `8-Color` | 150 | 3.32x | 3.27x | 1.69x | 82.33% | 83.36% | 81.48% |
| `8-Color` | 225 | 3.31x | 3.27x | 1.51x | 82.34% | 83.45% | 81.43% |
| `8-Color` | 300 | 3.89x | 3.83x | 1.57x | 83.37% | 84.49% | 82.46% |
| `6-Color` | 75 | 2.86x | 2.83x | 1.93x | 80.82% | 81.71% | 80.09% |
| `6-Color` | 150 | 3.17x | 3.13x | 1.76x | 82.35% | 83.37% | 81.53% |
| `6-Color` | 225 | 3.42x | 3.37x | 1.58x | 82.76% | 83.84% | 81.89% |
| `6-Color` | 300 | 3.68x | 3.63x | 1.54x | 83.20% | 84.30% | 82.32% |
| `5-Color-Extended` | 75 | 2.80x | 2.76x | 1.78x | 80.85% | 81.74% | 80.12% |
| `5-Color-Extended` | 150 | 3.30x | 3.26x | 1.85x | 82.28% | 83.33% | 81.43% |
| `5-Color-Extended` | 225 | 3.50x | 3.46x | 1.58x | 82.54% | 83.64% | 81.63% |
| `5-Color-Extended` | 300 | 4.61x | 4.54x | 1.89x | 83.36% | 84.48% | 82.45% |

## 6. Bottleneck Breakdown (warm median, seconds)

Of the four pipeline stages whose timing s11 reports — S06 (voxel build), S07 (mesh gen), S11 (GLB preview), and the rest (image processing / S02) — only **S11** is changed by this PR. The table below shows where the v1→v2 saving lands; everything else should be flat (within run-to-run noise).

| mode | width_mm | kernel | image_proc | s06 | s07 | s11_loop | s11_export | total |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `4-Color RYBW` | 75 | v1 | 4.82 | 0.01 | 0.57 | 13.50 | 0.13 | 19.09 |
| `4-Color RYBW` | 75 | v2 | 4.90 | 0.00 | 0.65 | 5.02 | 0.10 | 10.70 |
| `4-Color RYBW` | 150 | v1 | 7.12 | 0.05 | 1.72 | 18.91 | 0.11 | 27.97 |
| `4-Color RYBW` | 150 | v2 | 7.72 | 0.05 | 1.84 | 5.65 | 0.10 | 15.39 |
| `4-Color RYBW` | 225 | v1 | 12.41 | 0.13 | 4.32 | 20.24 | 0.12 | 37.27 |
| `4-Color RYBW` | 225 | v2 | 12.67 | 0.13 | 4.58 | 5.82 | 0.10 | 23.33 |
| `4-Color RYBW` | 300 | v1 | 20.00 | 0.26 | 7.37 | 21.76 | 0.12 | 49.58 |
| `4-Color RYBW` | 300 | v2 | 19.69 | 0.19 | 7.73 | 6.21 | 0.10 | 33.96 |
| `BW` | 75 | v1 | 3.84 | 0.00 | 0.39 | 8.79 | 0.06 | 13.12 |
| `BW` | 75 | v2 | 3.94 | 0.00 | 0.38 | 3.12 | 0.05 | 7.51 |
| `BW` | 150 | v1 | 4.31 | 0.05 | 1.14 | 11.34 | 0.07 | 16.96 |
| `BW` | 150 | v2 | 4.14 | 0.01 | 1.04 | 3.63 | 0.06 | 8.90 |
| `BW` | 225 | v1 | 8.30 | 0.06 | 2.07 | 11.50 | 0.07 | 22.04 |
| `BW` | 225 | v2 | 7.37 | 0.04 | 2.09 | 3.71 | 0.06 | 13.30 |
| `BW` | 300 | v1 | 12.00 | 0.23 | 4.95 | 12.80 | 0.08 | 30.10 |
| `BW` | 300 | v2 | 11.88 | 0.23 | 4.84 | 4.14 | 0.08 | 21.19 |
| `8-Color` | 75 | v1 | 6.34 | 0.00 | 0.87 | 16.02 | 0.11 | 23.41 |
| `8-Color` | 75 | v2 | 6.59 | 0.00 | 0.84 | 5.58 | 0.10 | 13.16 |
| `8-Color` | 150 | v1 | 10.02 | 0.05 | 2.80 | 21.96 | 0.13 | 35.02 |
| `8-Color` | 150 | v2 | 10.64 | 0.03 | 3.22 | 6.62 | 0.12 | 20.67 |
| `8-Color` | 225 | v1 | 18.84 | 0.13 | 5.61 | 25.73 | 0.15 | 50.54 |
| `8-Color` | 225 | v2 | 19.81 | 0.10 | 5.62 | 7.76 | 0.14 | 33.47 |
| `8-Color` | 300 | v1 | 33.93 | 0.44 | 13.96 | 28.13 | 0.15 | 76.68 |
| `8-Color` | 300 | v2 | 28.13 | 0.14 | 13.03 | 7.24 | 0.13 | 48.71 |
| `6-Color` | 75 | v1 | 6.77 | 0.00 | 0.95 | 17.01 | 0.12 | 24.91 |
| `6-Color` | 75 | v2 | 5.95 | 0.00 | 0.87 | 5.95 | 0.10 | 12.90 |
| `6-Color` | 150 | v1 | 9.23 | 0.03 | 2.53 | 22.07 | 0.13 | 34.04 |
| `6-Color` | 150 | v2 | 9.46 | 0.02 | 2.71 | 6.95 | 0.12 | 19.29 |
| `6-Color` | 225 | v1 | 16.60 | 0.14 | 5.81 | 24.72 | 0.14 | 47.49 |
| `6-Color` | 225 | v2 | 16.81 | 0.09 | 5.77 | 7.23 | 0.12 | 30.06 |
| `6-Color` | 300 | v1 | 30.30 | 0.40 | 11.66 | 27.16 | 0.15 | 69.74 |
| `6-Color` | 300 | v2 | 26.94 | 0.39 | 10.35 | 7.38 | 0.13 | 45.22 |
| `5-Color-Extended` | 75 | v1 | 7.06 | 0.00 | 0.88 | 17.32 | 0.12 | 25.45 |
| `5-Color-Extended` | 75 | v2 | 7.11 | 0.00 | 0.87 | 6.19 | 0.10 | 14.32 |
| `5-Color-Extended` | 150 | v1 | 10.30 | 0.06 | 2.97 | 23.88 | 0.15 | 37.42 |
| `5-Color-Extended` | 150 | v2 | 10.05 | 0.02 | 2.79 | 7.24 | 0.12 | 20.25 |
| `5-Color-Extended` | 225 | v1 | 18.06 | 0.12 | 7.31 | 26.13 | 0.16 | 51.85 |
| `5-Color-Extended` | 225 | v2 | 17.87 | 0.11 | 7.23 | 7.45 | 0.13 | 32.83 |
| `5-Color-Extended` | 300 | v1 | 34.81 | 0.26 | 15.58 | 36.39 | 0.16 | 87.28 |
| `5-Color-Extended` | 300 | v2 | 26.86 | 0.18 | 11.08 | 7.89 | 0.13 | 46.18 |

## 7. Mode-specific Notes

### `4-Color RYBW`

- runs collected: 8 (4 v1 ok / 4 v2 ok)
- unique colors: [44, 46], color_<hex> nodes: [44, 46]
- s11_mesh_loop speedup range across widths: min=2.69x, max=3.50x

### `5-Color-Extended`

- runs collected: 8 (4 v1 ok / 4 v2 ok)
- unique colors: [55, 56, 58], color_<hex> nodes: [55, 56, 58]
- s11_mesh_loop speedup range across widths: min=2.80x, max=4.61x

### `6-Color`

- runs collected: 8 (4 v1 ok / 4 v2 ok)
- unique colors: [48, 50, 51], color_<hex> nodes: [48, 50, 51]
- s11_mesh_loop speedup range across widths: min=2.86x, max=3.68x

### `8-Color`

- runs collected: 8 (4 v1 ok / 4 v2 ok)
- unique colors: [55, 57, 58, 59], color_<hex> nodes: [55, 57, 58, 59]
- s11_mesh_loop speedup range across widths: min=2.87x, max=3.89x

### `BW`

- runs collected: 8 (4 v1 ok / 4 v2 ok)
- unique colors: [16, 17, 18], color_<hex> nodes: [16, 17, 18]
- s11_mesh_loop speedup range across widths: min=2.81x, max=3.12x

## 8. Recommendation

- **Continue with v2.** Geometric-mean s11_mesh_loop speedup ≈ **3.27x** across 20 bitmap matrix cases; no fallback, no GLB / vertex inflation, no geometry failure.
- **Default kernel** SHALL remain `shapely_v1`. v2 stays opt-in via `LUMINA_GLB_KERNEL=v2` / `auto`. Phase-2 default switch is a separate PR.
- **SVG / vector pipeline is out of scope** for this benchmark; the matrix above only covers the raster / bitmap path through `run_raster_pipeline`.
- If a specific mode shows a regression here, do not introduce new heuristics in s11; either `LUMINA_GLB_KERNEL=shapely_v1` keeps that mode on the proven path, or open a separate spec to investigate.
