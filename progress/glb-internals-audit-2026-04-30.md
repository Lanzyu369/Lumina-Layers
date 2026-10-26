# generate_segmented_glb Audit (S11 GLB Preview)

> **Verdict: LEAK FOUND** — output path collision in 3 of 4 production callers.
> **结论: 找到泄漏** — 4 个生产调用方有 3 个会落到固定路径, 跨会话覆盖.

Audit conducted on `dev-refactor` HEAD `2bb72d1` as part of A2 of the post-merge memory + 3D preview contamination plan (`~/.windsurf/plans/a1-a2-fix-plan-a5b93d.md`). This document is read-only forensic output; the recommended fix lands in a separate follow-up PR.

## Scope / 范围

- **Target file**: `core/pipeline/s11_glb_preview.py` (874 LOC)
- **Entry function**: `generate_segmented_glb` (L490-745)
- **Helpers traced** (full reads):
  - `_iter_valid_polygons` (L29-63)
  - `_create_preview_mesh` (L66-225)
  - `_merge_low_frequency_colors` (L228-262)
  - `_build_color_extruded_mesh` (L265-374)
  - `_build_backing_plate_mesh` (L377-452)
- **Path resolution**: `core/naming.py::generate_preview_filename` (L84-96)
- **Caller survey**: production code under `api/` and `core/` (test-only references excluded)

## Findings / 发现

### 1. Input cache mutation / 入参 cache 写入

**Verdict / 结论: SAFE PER-SESSION, BUT UNDOCUMENTED**

The function writes 2 keys into the input `cache` dict:

```@e:/Lumina-Layers/LL-1296/Lumina-Layers/core/pipeline/s11_glb_preview.py:714
        cache["color_contours"] = contours_data
```

```@e:/Lumina-Layers/LL-1296/Lumina-Layers/core/pipeline/s11_glb_preview.py:724-733
        cache["_segmented_glb_timings"] = {
            "downsample_s": _t_downsample,
            "unique_s": _t_unique,
            "merge_s": _t_merge,
            "mask_build_s": _t_mask_build,
            "mesh_loop_s": _t_mesh_loop,
            "backing_s": _t_backing,
            "export_s": _t_export,
            "total_s": _t_glb_total,
        }
```

These are **intentional output side effects** consumed by:
- `core/pipeline/s11_glb_preview.py::run` L865-872 (reads `_segmented_glb_timings` for `_hifi_timings`)
- `tests/test_region_3d_preview_sync_unit.py` L175-176 (asserts `color_contours` populated by replace endpoint)

Each `cache` is allocated per session (either built fresh in `s11_glb_preview.py::run::850-856`, or the session-scoped `preview_cache` from `SessionStore`), so the writes do **not** cross sessions. They are, however, not declared in the function's docstring (L491-512) — the docstring lists only inputs.

**Other potential mutations checked, all CLEAN**:
- L553-558 (`cv2.resize`): rebinds `matched_rgb` / `mask_solid` locals — does **not** touch `cache` fields
- L569 (`flat_rgb = matched_rgb.reshape(-1, 3).astype(np.uint32, copy=False)`): the dtype change uint8 → uint32 forces a copy, so `flat_rgb` is independent of cache contents
- L620 (`updated_flat = matched_rgb.reshape(-1, 3).copy()`): explicit `.copy()` before any in-place writes (L621-623)
- L624: rebinds local `matched_rgb` to the rebuilt copy — original cache `matched_rgb` reference is untouched
- L650-693 (color match build / clear): operates on a function-local `color_match_flat` allocated in scope at L650

### 2. Module-level state / 模块级状态

**Verdict / 结论: CLEAN**

Module-level identifiers in `s11_glb_preview.py`:

```@e:/Lumina-Layers/LL-1296/Lumina-Layers/core/pipeline/s11_glb_preview.py:14-26
from api.structured_logging import get_logger
import os
import time
from typing import Optional

import cv2
import numpy as np
import trimesh

from config import PrinterConfig, OUTPUT_DIR, BedManager
from core.naming import generate_preview_filename

_log = get_logger(__name__)
```

- `_log` (L26): read-only structured logger handle. No `_log =` reassignment elsewhere. **Safe**.
- `OUTPUT_DIR`, `PrinterConfig`, `BedManager`, `generate_preview_filename`: imported names; not reassigned. **Safe**.
- All other module-level symbols (L29, L66, L228, L265, L377, L455, L490, L748, L809) are pure `def` declarations. **Safe**.

`_CUBE_FACES` (L114-130) lives **inside** `_create_preview_mesh`'s function body, so it is per-call, not module-level state.

The 5 helpers are pure: each takes its inputs, performs deterministic computation, and returns a fresh `Trimesh` / `np.ndarray`. None of them mutate any module-level container. None of them mutate their inputs (verified via reads at L66-225, L228-262, L265-374, L377-452, L29-63).

### 3. Output path collision / 输出路径冲突

**Verdict / 结论: LEAK FOUND**

The function falls back to a **fixed path** when `output_path` is None:

```@e:/Lumina-Layers/LL-1296/Lumina-Layers/core/pipeline/s11_glb_preview.py:719
        glb_path = output_path if output_path else os.path.join(OUTPUT_DIR, "segmented_preview.glb")
```

`OUTPUT_DIR` is a process-global path constant (from `config.py`). The default fallback `OUTPUT_DIR/segmented_preview.glb` is **not session-scoped, not request-scoped, not even job-scoped**.

#### Production caller survey

Searched `api/` and `core/` for `generate_segmented_glb(`, excluding test files:

| Caller | Line | Passes `output_path`? | Path used |
|---|---|---|---|
| `core/pipeline/s11_glb_preview.py::run` | L857 | **YES** (`out_path` from `generate_preview_filename` with `YYYYMMDD_HHmmss` timestamp) | unique per call |
| `api/routers/converter/replace.py` | L129 | **NO** | `OUTPUT_DIR/segmented_preview.glb` (fixed) |
| `api/routers/converter/async_glb.py` | L176 | **NO** | `OUTPUT_DIR/segmented_preview.glb` (fixed) |
| `api/routers/converter/preview.py` | L607 | **NO** | `OUTPUT_DIR/segmented_preview.glb` (fixed) |

**3 of 4 production callers** end up writing to the same physical path. The pipeline-stage `run()` is the only one that produces a unique filename, because it builds `out_path = OUTPUT_DIR / generate_preview_filename(base_name)` (L848) which embeds a timestamp.

#### Why this is the 3D preview contamination root cause

Each request flow ends up registering the GLB through `FileRegistry`:

```@e:/Lumina-Layers/LL-1296/Lumina-Layers/api/routers/converter/preview.py:607-610
        glb_path = generate_segmented_glb(cache_data)
        if glb_path and os.path.exists(glb_path):
            glb_id = registry.register_path(session_id, glb_path)
            preview_glb_url = f"/api/files/{glb_id}"
```

`FileRegistry.register_path` stores the **path string** under a session-scoped `glb_id`. When the frontend later fetches `/api/files/{glb_id}`, the server reads from disk **at fetch time**.

Concurrent timeline that reproduces the bug:

```
t0  Session A runs preview → writes bytes_A to OUTPUT_DIR/segmented_preview.glb
    Registry: glb_id_A → OUTPUT_DIR/segmented_preview.glb

t1  Session B runs preview → writes bytes_B to OUTPUT_DIR/segmented_preview.glb (OVERWRITES)
    Registry: glb_id_B → OUTPUT_DIR/segmented_preview.glb

t2  Session A's frontend fetches /api/files/{glb_id_A}
    Server reads OUTPUT_DIR/segmented_preview.glb on disk → returns bytes_B
    User of session A sees session B's GLB ← THIS IS THE "3D 预览串联" BUG
```

The job-token guard in `async_glb.py` (L178-180) only protects against **stale writes within the same session**, not against cross-session path collisions.

#### Why we did not see this in the segmented GLB unit tests

`tests/test_segmented_glb_unit.py` and `tests/test_segmented_glb_properties.py` call `generate_segmented_glb(cache)` (no `output_path`) but run **single-threaded sequentially** — each test asserts the file exists immediately after the call, so there is no concurrent overwriter. The tests cannot catch this contamination class.

## Conclusion / 结论

| Risk class | Verdict | Evidence |
|---|---|---|
| Backend cross-session contamination | **CONFIRMED, 1 spot** | L719 fixed-path fallback + 3 callers passing None |
| Memory leak contribution | **None directly** | Function does not retain references; module has no caches |
| Cache mutation | **Safe per-session, undocumented** | L714 + L724 |
| Module-level mutable state | **None** | L26 logger only |

### Action items / 行动项

1. **Open follow-up PR `fix/glb-output-path-session-scope-a2`** that does ONE of:
   - **Option A (preferred, minimal)**: change L719 to require `output_path` and update the 3 callers (`replace.py:129`, `async_glb.py:176`, `preview.py:607`) to pass a unique path. The most natural source is `FileRegistry.allocate_path(session_id, suffix="_segmented_preview.glb")` or `OUTPUT_DIR / generate_preview_filename(f"session_{session_id[:8]}")`. The pipeline `run()` already does the right thing and serves as the model.
   - **Option B (defensive, larger)**: change L719 fallback to embed `os.urandom(8).hex()` or `uuid.uuid4().hex` so accidental None-passing future callers stay isolated. Less explicit than A but eliminates the entire class of bug.
2. **Document the cache write contract** (`color_contours`, `_segmented_glb_timings`) in the `generate_segmented_glb` docstring so future callers do not assume input-only semantics.
3. **Audit `generate_realtime_glb` (L748-806)** — same pattern: hard-coded `OUTPUT_DIR/realtime_preview.glb` at L799 with **no `output_path` parameter at all**. Currently no production caller (verified by grep), but if it gets reintroduced it carries the same bug.

The follow-up code-level PR is **out of scope** for this audit per the A2 plan; it should be opened separately under a new mini-plan once the design choice between Option A / B is made.

## Open follow-ups / 待跟进

- Confirm `generate_realtime_glb` is genuinely dead code or restore-and-fix it (no production caller in current grep across `api/` and `core/`).
- Inspect `_build_backing_plate_mesh` for backing plate path collisions if it ever exports independently — currently it returns a `Trimesh` only, so no path concern, but worth re-checking after the upcoming Phase 0 sub-PR D (vector branch extraction) lands.
- Cross-reference with the parallel pipeline-refactor AI's Phase 0 sub-PR D which may extract vector-rendering paths; the fix in action item 1 should land first to avoid merge churn.
