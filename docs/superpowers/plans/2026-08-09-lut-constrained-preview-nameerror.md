# LUT-Constrained Preview NameError Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep preview generation successful when LUT-constrained matching is combined with a positive hue-protection weight, while preserving the existing rule that disables hue protection for that mode.

**Architecture:** Fix the symbol drift at the image-processor boundary and retain the existing parameter semantics. Lock the behavior at two levels: a focused constructor test for state and structured logging, plus one API integration test whose inline pool executes the real top-level preview worker with a real temporary PNG and NPZ LUT.

**Tech Stack:** Python 3.14, pytest, FastAPI TestClient, NumPy, Pillow, structured logging.

---

### Task 1: Lock the constructor behavior and logging contract

**Files:**
- Create: `tests/test_image_processing_unit.py`
- Modify: `core/image_processing.py:142`

- [x] **Step 1: Write the failing constructor regression test**

```python
from __future__ import annotations

import logging
from unittest.mock import patch

import numpy as np

from core import image_processing


def _minimal_lut_payload() -> dict:
    return {
        "lut_rgb": np.array([[255, 255, 255]], dtype=np.uint8),
        "lut_lab": np.array([[255.0, 128.0, 128.0]], dtype=np.float64),
        "ref_stacks": np.zeros((1, 5), dtype=np.int32),
        "kdtree": None,
        "layer_count": 5,
    }


def test_lut_constrained_disables_hue_protection_with_structured_event(caplog) -> None:
    target_logger = logging.getLogger(image_processing.log.name)
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=target_logger.name)

    try:
        with patch.object(
            image_processing.LuminaImageProcessor,
            "_load_lut_data",
            return_value=_minimal_lut_payload(),
        ):
            processor = image_processing.LuminaImageProcessor(
                "unused.npz",
                "4-Color (RYBW)",
                hue_weight=0.5,
                use_lut_constrained=True,
            )
    finally:
        target_logger.removeHandler(caplog.handler)

    assert processor.use_lut_constrained is True
    assert processor.hue_weight == 0.0
    assert processor.hue_matcher is None
    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None)
        == "image_processor_hue_protection_disabled"
    ]
    assert len(records) == 1
    assert records[0].requested_hue_weight == 0.5
    assert records[0].reason == "lut_constrained"
```

- [x] **Step 2: Run the test and verify the red state**

Run: `.venv/bin/python -m pytest tests/test_image_processing_unit.py -v`

Expected: FAIL with `NameError: name '_log' is not defined` at `core/image_processing.py:143`.

- [x] **Step 3: Implement the minimal structured-logging fix**

```python
        if self.use_lut_constrained and self.hue_weight > 0:
            requested_hue_weight = self.hue_weight
            log.info(
                "Hue protection ignored for LUT-constrained matching",
                extra={
                    "event": "image_processor_hue_protection_disabled",
                    "requested_hue_weight": requested_hue_weight,
                    "reason": "lut_constrained",
                },
            )
            self.hue_weight = 0.0
```

- [x] **Step 4: Run the constructor test and verify green**

Run: `.venv/bin/python -m pytest tests/test_image_processing_unit.py -v`

Expected: PASS, one structured INFO record, final `hue_weight == 0.0`.

### Task 2: Prove the worker/API boundary no longer returns 500

**Files:**
- Modify: `tests/test_converter_preview_unit.py`

- [x] **Step 1: Add one real-worker API integration test**

Add an inline pool whose `submit_timed()` invokes the supplied top-level worker, then:

```python
class _InlineRealWorkerPool:
    async def submit_timed(self, fn, *args, timeout=None):
        return fn(*args), {}


def test_preview_lut_constrained_positive_hue_weight_succeeds_through_worker(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "input.png"
    lut_path = tmp_path / "lut.npz"
    Image.new("RGB", (8, 8), (220, 20, 60)).save(image_path)
    np.savez(
        lut_path,
        rgb=np.array([[255, 255, 255], [220, 20, 60]], dtype=np.uint8),
        stacks=np.array(
            [[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]],
            dtype=np.int32,
        ),
    )

    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    previous_overrides = {
        get_session_store: app.dependency_overrides.get(get_session_store),
        get_file_registry: app.dependency_overrides.get(get_file_registry),
        get_worker_pool: app.dependency_overrides.get(get_worker_pool),
    }
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = lambda: _InlineRealWorkerPool()

    response = None
    session_id = None
    try:
        local_client = TestClient(app, raise_server_exceptions=False)
        with (
            patch(
                "api.routers.converter.preview.LUTManager.resolve_source_selection",
                return_value=(str(lut_path), "Temporary LUT"),
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value=str(image_path)),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
            patch("config.TEMP_DIR", str(tmp_path)),
            patch("api.preview_cache_artifacts.TEMP_DIR", str(tmp_path)),
            patch("api.routers.converter.preview.TEMP_DIR", str(tmp_path)),
        ):
            response = local_client.post(
                "/api/convert/preview",
                files={
                    "image": (
                        "input.png",
                        image_path.read_bytes(),
                        "image/png",
                    )
                },
                data={
                    "lut_name": "temporary_lut",
                    "color_mode": "4-Color (RYBW)",
                    "target_width_mm": "10",
                    "quantize_colors": "8",
                    "use_lut_constrained": "true",
                    "hue_weight": "0.5",
                },
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            session_id = payload["session_id"]
            assert payload["preview_url"].startswith("/api/files/")
            assert local_client.get(payload["preview_url"]).status_code == 200
    finally:
        if session_id is not None:
            store.close(session_id)
            registry.cleanup_session(session_id)
        for dependency, previous in previous_overrides.items():
            if previous is None:
                app.dependency_overrides.pop(dependency, None)
            else:
                app.dependency_overrides[dependency] = previous
```

This restores dependency overrides in `finally`, closes the returned session,
cleans its registry entries, and keeps every generated artifact under
`tmp_path`.

- [x] **Step 2: Run the API test and verify the red state**

Run: `.venv/bin/python -m pytest tests/test_converter_preview_unit.py -k 'lut_constrained_positive_hue_weight' -v`

Expected: FAIL because the endpoint returns 500 from the worker-side `NameError`.

- [x] **Step 3: Re-run after Task 1 and verify green**

Run: `.venv/bin/python -m pytest tests/test_converter_preview_unit.py -k 'lut_constrained_positive_hue_weight' -v`

Expected: PASS with HTTP 200 and a readable preview artifact.

### Task 3: Focused verification and commit

**Files:**
- Verify: `core/image_processing.py`
- Verify: `tests/test_image_processing_unit.py`
- Verify: `tests/test_converter_preview_unit.py`

- [x] **Step 1: Run directly related tests**

Run: `.venv/bin/python -m pytest tests/test_image_processing_unit.py tests/test_converter_preview_unit.py tests/test_converter_workers_unit.py -v`

Expected: PASS with zero failures.

- [x] **Step 2: Run logging governance tests**

Run: `.venv/bin/python -m pytest tests/test_logging_exception_governance_unit.py tests/test_structured_logging_unit.py tests/test_logger_unit.py -v`

Expected: PASS with zero failures.

- [x] **Step 3: Run the fast logging workflow gate**

Run: `.venv/bin/python scripts/log_quality_check.py --mode fast`

Expected: exit 0 without weakening thresholds.

- [ ] **Step 4: Inspect scope and commit the correctness fix**

Run: `git diff --check`

Run: `git status --short`

Expected: only the plan, constructor fix, and two focused test files are changed.

Commit: `fix(converter): prevent LUT constrained preview initialization failure`
