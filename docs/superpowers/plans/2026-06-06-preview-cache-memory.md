# Preview Cache Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Docker long-run memory peaks by moving preview-cache array retention out of the main-process SessionStore while preserving preview, replace, generate, GLB, layer image, heightmap, puzzle, LUT, and recipe override behavior.

**Architecture:** Implement this in staged PR-sized slices. PR 1 adds aggregate diagnostics only, with no behavior change. Later slices introduce a private session-bound artifact layer for large NumPy fields, atomic field revisions, worker-side manifest loading, and route-by-route migration so large arrays are loaded only for the request or worker that needs them.

**Tech Stack:** Python 3, FastAPI, NumPy `.npy`, pytest, structured logging, existing `SessionStore`, existing worker pool, existing `FileRegistry` only for public user-facing outputs.

---

## Current Evidence

- Issue: `https://github.com/lumina-layer-studio/Lumina-studio/issues/233`
- Root path: `E:\Lumina-Layers\LL-1296\Lumina-Layers`
- Protected base: `origin/dev-refactor`
- Working branch for this plan: `Min/fix/preview-cache-memory`
- Current main cache retention path:
  - `api/workers/converter_workers.py`: `worker_generate_preview()` writes `cache_data` to a temp pickle and already logs `cache_data_bytes`.
  - `api/routers/converter/preview.py`: `convert_preview()` loads the worker pickle with `pickle.load()`, then stores the full dict in `SessionStore`.
  - `api/routers/converter/preview.py`: `original_matched_rgb` and `original_material_matrix` are copied into top-level session fields.
  - `api/session_store.py`: `SessionStore` stores arbitrary Python objects in an in-memory dict and `get()` renews the lease.
  - `api/routers/converter/preview.py`: `layer_images_cache` stores PNG bytes in session.
- Direct preview-cache consumers to migrate explicitly:
  - `api/routers/converter/preview.py`
  - `api/routers/converter/replace.py`
  - `api/routers/converter/generate.py`
  - `api/routers/converter/async_glb.py`
  - `api/routers/converter/puzzle.py`
  - `api/routers/converter/color_card.py`
  - `api/routers/converter/common.py`
  - `api/routers/lut.py`
  - `api/routers/converter/gradient_groups.py`
  - recipe override routes inside `api/routers/converter/replace.py`
  - heightmap routes inside `api/routers/converter/preview.py`
  - tests that directly mutate `session_data["preview_cache"]`

## P0 Design Constraints From Issue Review

- PR 1 is diagnostics only and must not change preview/generate behavior.
- Cache artifact files are private internal files. Prefer `SessionStore.register_temp_file()` for cleanup. Do not expose `.npy` files through public `/api/files/<id>`.
- Artifact writes must use temp files followed by `os.replace()` for atomic replacement.
- Manifest metadata must include a schema version, manifest revision, and per-field revisions or hashes.
- Dirty saves must update only fields they own and must not overwrite unrelated metadata from concurrent GLB, replace, reset, or polling activity.
- `generate` and large-format generation must not fully hydrate cache in the main process just to pass it to a worker. Workers receive a manifest/path payload and load fields inside the worker.
- `original_*` snapshots should be reference snapshots, not in-memory copies.
- `layer-images` cache keys must use field revision/hash metadata, not `material_matrix.tobytes()`.
- Diagnostics must fit logging governance: one aggregate event, DEBUG by default, optional INFO only through an explicit env flag.

## File Structure

- Create `api/preview_cache_memory.py`
  - Aggregate cache memory profile helpers.
  - No behavior change.
  - Can be used by PR 1 immediately.
- Create `tests/test_preview_cache_memory_unit.py`
  - Unit tests for array profiling and env-controlled log level.
- Later create `api/preview_cache_artifacts.py`
  - Private `.npy` artifact manifest model.
  - Atomic field writes.
  - Field revisions and hashes.
  - Hydration and dirty-save context managers.
- Later create `tests/test_preview_cache_artifacts_unit.py`
  - Artifact save/load, atomic replace, revision, and cleanup registration tests.
- Modify `api/routers/converter/preview.py`
  - PR 1: call diagnostics after worker pickle load and before session write.
  - Later: externalize cache arrays and layer image bytes.
- Modify `api/routers/converter/common.py`
  - Later: replace raw `_require_preview_cache()` assumptions with artifact-aware access helpers.
- Modify `api/workers/converter_workers.py`
  - Later: add worker-side artifact manifest loading for generate/model paths if needed.
- Modify `api/routers/converter/generate.py`
  - Later: pass artifact manifest to workers instead of main-process hydrated arrays.
- Modify `api/routers/converter/async_glb.py`
  - Later: use artifact-aware loading and metadata-only status writes.
- Modify `api/routers/converter/replace.py`
  - Later: use dirty field save for replace, reset, recipe override, source-color-pick, and region flows.
- Modify `api/routers/converter/puzzle.py`, `api/routers/converter/color_card.py`, and `api/routers/lut.py`
  - Later: use the same artifact-aware helper instead of direct `session_data["preview_cache"]`.

### Task 1: Aggregate Preview Cache Diagnostics

**Files:**
- Create: `api/preview_cache_memory.py`
- Modify: `api/routers/converter/preview.py`
- Test: `tests/test_preview_cache_memory_unit.py`
- Test: `tests/test_converter_preview_unit.py`

- [x] **Step 1: Write failing tests for cache profile summaries**

Add `tests/test_preview_cache_memory_unit.py` with these tests:

```python
import logging

import numpy as np

from api.preview_cache_memory import (
    build_preview_cache_memory_profile,
    should_log_preview_cache_memory_profile_at_info,
)


def test_build_preview_cache_memory_profile_summarizes_arrays() -> None:
    cache = {
        "matched_rgb": np.zeros((2, 3, 3), dtype=np.uint8),
        "material_matrix": np.ones((2, 3, 4), dtype=np.int16),
        "mask_solid": np.ones((2, 3), dtype=bool),
        "color_palette": [{"name": "white"}],
        "target_w": 3,
        "target_h": 2,
    }

    profile = build_preview_cache_memory_profile(
        cache,
        session_id="sid-1",
        modeling_mode="vector",
        cache_data_bytes=4096,
        process_rss_bytes=123456,
    )

    assert profile["event"] == "preview_cache_memory_profile"
    assert profile["session_id"] == "sid-1"
    assert profile["modeling_mode"] == "vector"
    assert profile["cache_data_bytes"] == 4096
    assert profile["process_rss_bytes"] == 123456
    assert profile["array_total_bytes"] == 72
    assert profile["array_count"] == 3
    assert profile["largest_arrays"][0] == {
        "field": "material_matrix",
        "shape": [2, 3, 4],
        "dtype": "int16",
        "nbytes": 48,
    }


def test_build_preview_cache_memory_profile_handles_missing_cache() -> None:
    profile = build_preview_cache_memory_profile(
        None,
        session_id="sid-2",
        modeling_mode="raster",
        cache_data_bytes=None,
        process_rss_bytes=None,
    )

    assert profile["array_total_bytes"] == 0
    assert profile["array_count"] == 0
    assert profile["largest_arrays"] == []


def test_preview_cache_memory_profile_info_flag(monkeypatch) -> None:
    monkeypatch.delenv("LUMINA_PREVIEW_CACHE_MEMORY_PROFILE_INFO", raising=False)
    assert should_log_preview_cache_memory_profile_at_info() is False

    monkeypatch.setenv("LUMINA_PREVIEW_CACHE_MEMORY_PROFILE_INFO", "1")
    assert should_log_preview_cache_memory_profile_at_info() is True

    monkeypatch.setenv("LUMINA_PREVIEW_CACHE_MEMORY_PROFILE_INFO", "true")
    assert should_log_preview_cache_memory_profile_at_info() is True

    monkeypatch.setenv("LUMINA_PREVIEW_CACHE_MEMORY_PROFILE_INFO", "0")
    assert should_log_preview_cache_memory_profile_at_info() is False
```

- [x] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests/test_preview_cache_memory_unit.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'api.preview_cache_memory'`.

- [x] **Step 3: Implement memory profile helper**

Create `api/preview_cache_memory.py`:

```python
"""Preview-cache memory diagnostics.

预览缓存内存诊断工具。
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np


_INFO_FLAG = "LUMINA_PREVIEW_CACHE_MEMORY_PROFILE_INFO"
_MAX_ARRAYS_REPORTED = 12


def should_log_preview_cache_memory_profile_at_info() -> bool:
    """Return whether preview cache memory profiles should be INFO logs.

    返回预览缓存内存画像是否应以 INFO 级别输出。
    """
    raw = os.getenv(_INFO_FLAG, "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_process_rss_bytes() -> int | None:
    """Return current process RSS when available.

    返回当前进程 RSS；平台不支持时返回 None。
    """
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        return int(psutil.Process(os.getpid()).memory_info().rss)
    except (OSError, RuntimeError):
        return None


def build_preview_cache_memory_profile(
    cache_data: dict[str, Any] | None,
    *,
    session_id: str,
    modeling_mode: str | None,
    cache_data_bytes: int | None,
    process_rss_bytes: int | None,
) -> dict[str, Any]:
    """Build one aggregate structured-log payload for preview cache memory.

    为 preview cache 构建单条聚合结构化日志负载。
    """
    arrays: list[dict[str, Any]] = []
    if cache_data:
        for key, value in cache_data.items():
            if isinstance(value, np.ndarray):
                arrays.append(
                    {
                        "field": key,
                        "shape": [int(dim) for dim in value.shape],
                        "dtype": str(value.dtype),
                        "nbytes": int(value.nbytes),
                    }
                )

    arrays.sort(key=lambda item: int(item["nbytes"]), reverse=True)
    return {
        "event": "preview_cache_memory_profile",
        "session_id": session_id,
        "modeling_mode": modeling_mode,
        "cache_data_bytes": cache_data_bytes,
        "process_rss_bytes": process_rss_bytes,
        "array_count": len(arrays),
        "array_total_bytes": sum(int(item["nbytes"]) for item in arrays),
        "largest_arrays": arrays[:_MAX_ARRAYS_REPORTED],
    }
```

- [x] **Step 4: Run unit tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_preview_cache_memory_unit.py -v
```

Expected: PASS.

- [x] **Step 5: Add preview endpoint integration test for the aggregate event**

In `tests/test_converter_preview_unit.py`, add a test near the existing preview response tests. The test should patch `api.routers.converter.preview.log` with an object that records `.debug()` and `.info()` calls, run the existing mocked preview endpoint path, and assert that one `preview_cache_memory_profile` event is emitted with aggregate fields. Use the existing preview endpoint test fixtures rather than starting a real worker.

Expected assertion shape:

```python
profile = next(
    call.kwargs["extra"]
    for call in logger_mock.debug.call_args_list
    if call.kwargs["extra"]["event"] == "preview_cache_memory_profile"
)
assert profile["array_count"] >= 1
assert profile["array_total_bytes"] > 0
assert profile["cache_data_bytes"] is not None
```

- [x] **Step 6: Run the integration test and verify RED**

Run:

```powershell
python -m pytest tests/test_converter_preview_unit.py -k preview_cache_memory_profile -v
```

Expected: FAIL because `convert_preview()` does not emit the event yet.

- [x] **Step 7: Wire diagnostics into `convert_preview()`**

In `api/routers/converter/preview.py`, import the helper:

```python
from api.preview_cache_memory import (
    build_preview_cache_memory_profile,
    get_process_rss_bytes,
    should_log_preview_cache_memory_profile_at_info,
)
```

After `store.put(session_id, "preview_cache", cache_data)` and before `recompute_gradient_groups_into_session(...)`, add:

```python
    memory_profile = build_preview_cache_memory_profile(
        cache_data,
        session_id=session_id,
        modeling_mode=modeling_mode,
        cache_data_bytes=(
            os.path.getsize(worker_cache_data_path)
            if worker_cache_data_path and os.path.exists(worker_cache_data_path)
            else None
        ),
        process_rss_bytes=get_process_rss_bytes(),
    )
    if should_log_preview_cache_memory_profile_at_info():
        log.info("Preview cache memory profile", extra=memory_profile)
    else:
        log.debug("Preview cache memory profile", extra=memory_profile)
```

This preserves behavior and keeps INFO budget unchanged unless `LUMINA_PREVIEW_CACHE_MEMORY_PROFILE_INFO` is explicitly enabled.

- [x] **Step 8: Run diagnostics tests and targeted preview tests**

Run:

```powershell
python -m pytest tests/test_preview_cache_memory_unit.py tests/test_converter_preview_unit.py -k "preview_cache_memory_profile or Session contains preview_cache or ResponseContainsPaletteAndDimensions" -v
```

Expected: PASS.

### Task 2: Private Preview Cache Artifact Core

**Files:**
- Create: `api/preview_cache_artifacts.py`
- Test: `tests/test_preview_cache_artifacts_unit.py`

- [x] **Step 1: Write failing tests for private artifact storage**

Create tests that assert:

```python
def test_externalize_preview_cache_writes_arrays_and_manifest(tmp_path):
    ...
    ref = externalize_preview_cache(session_id, store, cache, root_dir=tmp_path)
    assert ref["schema"] == "preview_cache_artifact_v1"
    assert ref["manifest_revision"] == 1
    assert "matched_rgb" in ref["fields"]
    assert store.get_temp_file_paths(session_id)
    assert np.load(ref["fields"]["matched_rgb"]["path"]).shape == (2, 2, 3)
    assert "matched_rgb" not in ref["metadata"]
```

```python
def test_save_preview_cache_fields_updates_only_dirty_field(tmp_path):
    ...
    updated = save_preview_cache_fields(session_id, store, ref, {"matched_rgb": new_rgb})
    assert updated["fields"]["matched_rgb"]["revision"] == 2
    assert updated["fields"]["material_matrix"]["revision"] == 1
```

```python
def test_hydrate_preview_cache_loads_requested_fields_only(tmp_path):
    ...
    hydrated = hydrate_preview_cache(ref, fields={"matched_rgb"})
    assert "matched_rgb" in hydrated
    assert "material_matrix" not in hydrated
```

- [x] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest tests/test_preview_cache_artifacts_unit.py -v
```

Expected: FAIL with missing module.

- [x] **Step 3: Implement artifact module API**

Implement these public functions and constants:

```python
ARTIFACT_SCHEMA = "preview_cache_artifact_v1"
LARGE_ARRAY_FIELDS = {
    "matched_rgb",
    "material_matrix",
    "mask_solid",
    "preview_rgba",
    "quantized_image",
}
ORIGINAL_ARRAY_FIELDS = {
    "original_matched_rgb",
    "original_material_matrix",
}

def externalize_preview_cache(session_id, store, cache, *, root_dir=None) -> dict: ...
def is_preview_cache_artifact_ref(value: object) -> bool: ...
def hydrate_preview_cache(ref: dict, *, fields: set[str] | None = None) -> dict: ...
def save_preview_cache_fields(session_id, store, ref, dirty_fields: dict[str, np.ndarray]) -> dict: ...
def merge_preview_cache_metadata(ref: dict, metadata: dict[str, object]) -> dict: ...
```

Rules:

- Use `tempfile.mkstemp(suffix=".npy", dir=root_dir or TEMP_DIR)`.
- Write arrays to `path + ".tmp"` or a separate temp file, then `os.replace(temp_path, final_path)`.
- Register final paths with `SessionStore.register_temp_file(session_id, path)`.
- Store metadata and array field records in plain dicts.
- Field record shape:

```python
{
    "path": path,
    "shape": [int(dim) for dim in arr.shape],
    "dtype": str(arr.dtype),
    "nbytes": int(arr.nbytes),
    "revision": 1,
    "sha256": sha256_of_array_bytes,
}
```

- Manifest shape:

```python
{
    "schema": ARTIFACT_SCHEMA,
    "manifest_revision": 1,
    "fields": {...},
    "metadata": {...},
}
```

- [x] **Step 4: Run artifact tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_preview_cache_artifacts_unit.py -v
```

Expected: PASS.

### Task 3: Externalize `/preview` Without Changing Public Response

**Files:**
- Modify: `api/routers/converter/preview.py`
- Modify: `api/routers/converter/common.py`
- Test: `tests/test_converter_preview_unit.py`

- [x] **Step 1: Write failing tests**

Add tests asserting that after a successful preview:

- `session_data["preview_cache"]` is an artifact ref.
- The ref has no top-level `np.ndarray`.
- `original_matched_rgb` and `original_material_matrix` are not top-level arrays in session.
- `preview_url`, `preview_raw_url`, `session_id`, palette, dimensions, and GLB polling response stay unchanged.

- [x] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest tests/test_converter_preview_unit.py -k "preview externalizes cache or Session contains preview_cache" -v
```

Expected: FAIL because preview still stores arrays in session.

- [x] **Step 3: Update preview endpoint**

Replace:

```python
store.put(session_id, "preview_cache", cache_data)
...
store.put(session_id, "original_matched_rgb", cache_data["matched_rgb"].copy())
store.put(session_id, "original_material_matrix", cache_data["material_matrix"].copy())
```

With:

```python
cache_with_originals = dict(cache_data)
if "matched_rgb" in cache_data:
    cache_with_originals["original_matched_rgb"] = cache_data["matched_rgb"]
if "material_matrix" in cache_data:
    cache_with_originals["original_material_matrix"] = cache_data["material_matrix"]
cache_ref = externalize_preview_cache(session_id, store, cache_with_originals)
store.put(session_id, "preview_cache", cache_ref)
```

Keep local `cache_data` alive only for the response-building code in the same request. Do not write `original_*` top-level arrays.

- [x] **Step 4: Add artifact-aware `_require_preview_cache()` compatibility**

Update `api/routers/converter/common.py`:

```python
def _require_preview_cache(session_data: dict) -> dict:
    cache = session_data.get("preview_cache")
    if cache is None:
        raise HTTPException(status_code=409, detail="No preview cache. Call POST /api/convert/preview first.")
    if is_preview_cache_artifact_ref(cache):
        return hydrate_preview_cache(cache)
    return cache
```

This is a compatibility bridge only. Later tasks replace broad hydrate calls with field-scoped contexts.

- [x] **Step 5: Run preview tests**

Run:

```powershell
python -m pytest tests/test_preview_cache_memory_unit.py tests/test_preview_cache_artifacts_unit.py tests/test_converter_preview_unit.py -v
```

Expected: PASS.

### Task 4: Field-Scoped Access For Replace, Reset, Source Pick, Heightmap, Gradient Groups

**Files:**
- Modify: `api/preview_cache_artifacts.py`
- Modify: `api/routers/converter/replace.py`
- Modify: `api/routers/converter/preview.py`
- Modify: `api/routers/converter/common.py`
- Modify: `api/routers/converter/gradient_groups.py`
- Test: `tests/test_converter_replace_integration_unit.py`
- Test: `tests/test_source_color_pick_unit.py`
- Test: `tests/test_heightmap_upload_unit.py`
- Test: `tests/test_gradient_groups_api_unit.py`

- [x] **Step 1: Add dirty context tests**

Add tests that use `preview_cache_transaction(session_id, store, session_data, fields={...})` and verify:

- Requested fields hydrate.
- `commit({"matched_rgb"})` saves only `matched_rgb`.
- Concurrent metadata added to the session ref is preserved.
- Revision mismatch raises a deterministic domain exception.

- [x] **Step 2: Implement transaction helper**

Add:

```python
class PreviewCacheRevisionConflict(RuntimeError): ...

@contextmanager
def preview_cache_transaction(session_id, store, session_data, *, fields):
    ...
```

The context manager loads requested arrays, exposes a dict-like cache, and writes dirty arrays through `save_preview_cache_fields()` using the latest ref from `store.get(session_id)`.

- [x] **Step 3: Migrate reset/source-color-pick**

Use requested fields:

- reset: `matched_rgb`, `material_matrix`, `original_matched_rgb`, `original_material_matrix`, `mask_solid`, `quantized_image`
- source-color-pick: `original_matched_rgb`, `matched_rgb`, `quantized_image`, `mask_solid`

Top-level `session_data.get("original_matched_rgb")` should be kept only as legacy fallback.

- [x] **Step 4: Migrate replace and region routes**

For each route currently calling `_require_preview_cache()` in `replace.py`, define the minimum field set and write only dirty fields. After each mutation, call a helper that updates small metadata without overwriting the artifact manifest.

- [x] **Step 5: Migrate heightmap and gradient group paths**

Heightmap should load only fields it reads. Gradient group recomputation should save `gradient_groups` and `region_id_map` as metadata or dedicated artifact fields according to payload size.

- [x] **Step 6: Run tests**

Run:

```powershell
python -m pytest tests/test_converter_replace_integration_unit.py tests/test_source_color_pick_unit.py tests/test_heightmap_upload_unit.py tests/test_gradient_groups_api_unit.py -v
```

Expected: PASS.

### Task 5: Worker-Side Manifest Loading For Generate And Async GLB

**Files:**
- Modify: `api/preview_cache_artifacts.py`
- Modify: `api/routers/converter/generate.py`
- Modify: `api/routers/converter/async_glb.py`
- Modify: `api/workers/converter_workers.py`
- Test: `tests/test_converter_generate_unit.py`
- Test: `tests/test_async_glb_unit.py`

- [x] **Step 1: Add worker payload tests**

Assert generate routes pass an artifact ref or manifest path to workers, not a fully hydrated dict containing arrays in the main process.

- [x] **Step 2: Add worker-side loader**

Add:

```python
def hydrate_preview_cache_for_worker(cache_or_ref: dict, *, mmap: bool = True) -> dict:
    if is_preview_cache_artifact_ref(cache_or_ref):
        return hydrate_preview_cache(cache_or_ref, mmap_mode="r" if mmap else None)
    return cache_or_ref
```

- [x] **Step 3: Migrate generate routes**

Pass the artifact ref through the worker payload. Inside worker entry points, call `hydrate_preview_cache_for_worker()` before invoking core model generation.

- [x] **Step 4: Migrate async GLB**

Keep `glb_job_token`, `glb_url`, `glb_error`, `glb_started_at`, and `glb_completed_at` as manifest metadata. The GLB worker hydrates only while building and then merges metadata back with revision checks.

- [x] **Step 5: Run tests**

Run:

```powershell
python -m pytest tests/test_converter_generate_unit.py tests/test_async_glb_unit.py -v
```

Expected: PASS.

### Task 6: Layer Images Cache Without Session PNG Bytes

**Files:**
- Modify: `api/routers/converter/preview.py`
- Test: `tests/test_reference_layer_images_unit.py`
- Test: `tests/test_converter_preview_unit.py`

- [x] **Step 1: Add failing tests**

Assert `layer_images_cache` stores:

```python
{
    "key": "<revision-based-key>",
    "layers": [{"name": "...", "path": "..."}],
}
```

and does not store `png_bytes`.

- [x] **Step 2: Replace key calculation**

Use material matrix field revision/hash from the artifact manifest plus palette/slot metadata. Do not call `material_matrix.tobytes()` for artifact-backed cache.

- [x] **Step 3: Store layer PNG files privately**

Write PNG bytes to temp files, register paths with `SessionStore.register_temp_file()`, and register bytes/path with FileRegistry only when returning a public URL for the current response.

- [x] **Step 4: Run tests**

Run:

```powershell
python -m pytest tests/test_reference_layer_images_unit.py tests/test_converter_preview_unit.py -k layer_images -v
```

Expected: PASS.

### Task 7: Remaining Consumers And Direct Test Fixtures

**Files:**
- Modify: `api/routers/converter/puzzle.py`
- Modify: `api/routers/converter/color_card.py`
- Modify: `api/routers/lut.py`
- Modify: `tests/*preview_cache*` fixtures as needed
- Test: `tests/test_converter_puzzle_unit.py`
- Test: `tests/test_converter_recipe_override_unit.py`
- Test: `tests/test_lut_api_unit.py`

- [x] **Step 1: Migrate puzzle and color-card reads**

Replace broad direct access with field-scoped helper calls. Puzzle routes should request only `matched_rgb`, `preview_rgba`, `mask_solid`, and dimensions they need.

- [x] **Step 2: Migrate LUT and recipe override reads/writes**

Read palette/slot metadata from manifest metadata. Dirty saves for material matrix changes must update only `material_matrix`.

- [x] **Step 3: Update test fixtures**

Add a fixture helper that creates either legacy in-memory cache or artifact-backed cache. Keep legacy tests where the endpoint promises backward compatibility.

- [x] **Step 4: Run tests**

Run:

```powershell
python -m pytest tests/test_converter_puzzle_unit.py tests/test_converter_recipe_override_unit.py tests/test_lut_api_unit.py -v
```

Expected: PASS.

### Task 8: Size Guardrails And Docker Production Follow-Up

**Files:**
- Modify: `api/preview_cache_artifacts.py`
- Modify: `api/routers/converter/preview.py`
- Modify: Docker/startup files after confirming current deployment path
- Test: targeted preview validation tests

- [x] **Step 1: Add estimated cache size helper**

Add:

```python
def estimate_preview_cache_bytes(width: int, height: int, layers: int, *, include_original: bool) -> int:
    matched = width * height * 3
    rgba = width * height * 4
    mask = width * height
    matrix = width * height * max(1, layers) * 2
    original = matched + matrix if include_original else 0
    return matched + rgba + mask + matrix + original
```

- [x] **Step 2: Add explicit limit behavior**

Read `LUMINA_PREVIEW_CACHE_MAX_BYTES`, defaulting to a conservative value documented in the test. Return deterministic 422 with dimensions and estimate if exceeded.

- [x] **Step 3: Docker production mode**

Confirm current Docker entrypoint first. Replace Vite dev server in production Docker mode with built static frontend only if the deployment path uses this container for external testing. Keep this as a separate commit because it is not the main root cause.

Confirmed `Dockerfile` currently runs `start_all.py`, which launches Vite dev server and relies on its `/api` proxy. A direct switch to `vite preview` would break the frontend's default relative `/api` calls because preview mode does not provide the dev proxy. Static Docker production mode needs a separate same-origin/static-serving or runtime API-base design and is intentionally not mixed into this cache-memory fix PR.

- [x] **Step 4: Run guardrail tests**

Run:

```powershell
python -m pytest tests/test_converter_preview_unit.py -k "cache size or large format or vector" -v
```

Expected: PASS.

### Task 9: Verification And Publish

**Files:**
- Review all modified files.

- [x] **Step 1: Run targeted backend tests**

Run:

```powershell
python -m pytest tests/test_preview_cache_memory_unit.py tests/test_preview_cache_artifacts_unit.py tests/test_converter_preview_unit.py tests/test_converter_replace_integration_unit.py tests/test_source_color_pick_unit.py tests/test_heightmap_upload_unit.py tests/test_gradient_groups_api_unit.py tests/test_converter_generate_unit.py tests/test_async_glb_unit.py tests/test_reference_layer_images_unit.py tests/test_converter_puzzle_unit.py tests/test_converter_recipe_override_unit.py tests/test_lut_api_unit.py -v
```

Expected: PASS.

- [x] **Step 2: Run logging governance tests**

Run:

```powershell
python -m pytest tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v
```

Expected: PASS.

- [x] **Step 3: Run smoke gate**

Run:

```powershell
python scripts/run_smoke_tests.py
```

Expected: PASS or only clearly documented pre-existing failures reproduced on `origin/dev-refactor`.

- [x] **Step 4: Diff review**

Run:

```powershell
git diff --check
git diff --stat
```

Expected: no whitespace errors and only files in this plan plus focused tests changed by this branch.

- [ ] **Step 5: Publish**

Commit with:

```powershell
git add api/preview_cache_memory.py api/preview_cache_artifacts.py api/routers/converter/preview.py api/routers/converter/common.py api/routers/converter/replace.py api/routers/converter/generate.py api/routers/converter/async_glb.py api/routers/converter/puzzle.py api/routers/converter/color_card.py api/routers/lut.py tests docs/superpowers/plans/2026-06-06-preview-cache-memory.md
git commit -m "fix(converter): externalize preview cache arrays"
git push -u origin Min/fix/preview-cache-memory
```

Open a PR to `dev-refactor` with English first, Chinese second, and include:

- Issue: `Fixes #233`
- Tests run
- Memory behavior before/after from `preview_cache_memory_profile`
- Note that `.npy` artifacts are private session-bound temp files
- Note that Docker production mode is included only if Task 8 actually changed it

## Self-Review

- Spec coverage: The plan covers issue #233 and the later review comment: PR split, private artifacts, revisions, worker-side loading, original snapshots, layer-image keys, all known consumers, and logging budget.
- Placeholder scan: No `TBD`, `TODO`, or "implement later" placeholders remain. Future tasks have concrete files, API names, invariants, and test commands.
- Type consistency: The manifest shape, field records, helper names, and route migration terms stay consistent across tasks.
