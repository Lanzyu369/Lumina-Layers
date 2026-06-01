# Local ColorChecker Core (downstream fork)

- Upstream repo: `git@github.com:lumina-layer-studio/ColorChecker.git`
- Pinned upstream commit: see `pinned_commit` in `UPSTREAM.json` (currently `85a028a`, 2026-05-09)

> 这是 ColorChecker 上游仓库的**下游分叉**，不是逐字拷贝。请勿直接覆盖更新。

## What this directory is / 这个目录是什么

`core/colorchecker/` is a **fork** of the upstream ColorChecker project, not a
mirror. Upstream ships a standalone web app: a monolithic top-level `app.py`
plus a thin `colorchecker/` package that only exports `calibrate`,
`generate_patch_points`, and `CalibrationResult`.

For Lumina we did two things upstream does not have:

1. **Split** upstream `app.py` into focused modules (`image_io.py`,
   `pipeline.py`, `reference.py`, `sampling.py`, ...).
2. **Extended** the algorithm with features upstream lacks: automatic chart
   detection (`detection.py`), patch orientation (`orient_patch_points`),
   strict calibration pipeline + multiple calibration models
   (`strict_pipeline.py`), gray normalization (`gray_normalization.py`),
   diagnostics (`diagnostics.py`), and reference management
   (`reference.py`, `reference_import.py`).

As of the pinned commit, the fork is ~6.3k LOC versus ~2.9k LOC upstream.

Do not reintroduce the upstream web UI, iframe bridge, or proxy routes here.
All Lumina integration goes through `core/colorchecker_adapter.py`.

## File correspondence / 文件对应关系

Only three files have a same-named upstream counterpart; the rest are
fork-only (derived from upstream `app.py` or written fresh):

| Local file | Upstream source | Status |
| --- | --- | --- |
| `calibration_core.py` | `calibration_core.py` | forked (local edits: narrowed `except`, public `soft_clip_highlights`) |
| `api.py` | `colorchecker/api.py` | forked (extended `calibrate` signature) |
| `__init__.py` | `colorchecker/__init__.py` | forked (exports the full local surface) |
| `data/desc.txt` | `desc.txt` | identical at pin |
| `image_io.py`, `pipeline.py`, `reference.py`, `sampling.py`, `color_metrics.py`, `color_models.py`, `gray_normalization.py`, `raw_strict.py`, `reference_import.py` | derived from upstream `app.py` | fork-only |
| `detection.py`, `strict_pipeline.py`, `diagnostics.py` | none | Lumina-only features |

## How to update from upstream / 如何同步上游更新

Because this is a fork, "update" means **review what changed upstream and port
the relevant bits by hand** — never overwrite. The helper script automates the
review, not the merge:

```bash
# 1. See what upstream changed since the pinned commit (read-only report).
python scripts/sync_colorchecker_upstream.py --check

# 2. Inspect the unified diffs for the tracked source files.
python scripts/sync_colorchecker_upstream.py --show-diff

# 3. Manually port any relevant changes into the local modules, keeping the
#    Lumina extensions intact. Run the colorchecker tests after porting:
python -m pytest tests/test_colorchecker_adapter_unit.py \
  tests/test_colorchecker_image_io_unit.py \
  tests/test_colorchecker_resource_lifecycle_unit.py -v

# 4. Once ported and green, advance the pin to the new upstream commit.
python scripts/sync_colorchecker_upstream.py --update-pin <commit-or-HEAD>
```

The script clones upstream into a temp dir outside the package, compares the
pinned commit against the requested target, and reports per-file changes for
the `tracked_upstream_files` listed in `UPSTREAM.json`. It does not modify any
file under `core/colorchecker/` except `UPSTREAM.json` (and only with
`--update-pin`).
