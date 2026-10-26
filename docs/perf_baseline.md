# Stage 3 Performance Baseline

- Generated at: `2026-04-01T03:44:42+08:00`
- Host: `MIN` | Platform: `nt`
- Python: `3.12.7`
- Profiling scope: `S06/S07/S11` and end-to-end `total_s`
- Thresholds: `warn=+15%`, `fail=+30%` (vs median baseline)

## Baseline Table (median)

| Dataset | total_s | S06_s | S07_s | S11_s | peak_memory_mb | io_total_mb |
|---|---:|---:|---:|---:|---:|---:|
| small | 10.807 | 0.011 | 0.294 | 4.667 | 990.82 | 137.56 |
| medium | 10.687 | 0.046 | 1.442 | 5.577 | 1382.66 | 167.42 |
| large | 23.639 | 0.180 | 6.123 | 6.225 | 3866.75 | 248.68 |

## Warm Baseline Table (run2/run3 median)

| Dataset | total_s | S06_s | S07_s | S11_s | peak_memory_mb |
|---|---:|---:|---:|---:|---:|
| small | 10.671 | 0.010 | 0.282 | 4.601 | 990.82 |
| medium | 10.601 | 0.047 | 1.474 | 5.633 | 1382.66 |
| large | 23.487 | 0.176 | 6.059 | 6.186 | 3874.35 |

## Bottleneck Ranking (cross-dataset median)

1. `s11_s`: 5.633s
2. `s07_s`: 1.474s
3. `s06_s`: 0.047s

## Warm Hotspots (Top 3 per dataset)

- small: `s11_mesh_loop_s`=3.679s, `mesh_compute_s`=0.998s, `s11_export_s`=0.836s
- medium: `mesh_compute_s`=5.342s, `s11_mesh_loop_s`=4.705s, `s11_export_s`=0.823s
- large: `mesh_compute_s`=21.384s, `s11_mesh_loop_s`=5.360s, `s11_export_s`=0.726s

## Notes

- `estimated_io_*` uses input/output file sizes as practical local proxy.
- This baseline is local-machine authoritative for now (P2 stage-3 v3).
- Cold-start (run1) is recorded separately; default regression checks use warm median.
- This round is diagnosis-first; hotspot ranking is expected to guide the next focused optimization.
- Re-run with `python scripts/profile_stage3.py` after substantial pipeline changes.
