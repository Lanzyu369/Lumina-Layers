"""Unit tests for Converter Batch endpoint integration.

Validates:
- LUT name resolution failure returns 404 (Requirement 9)
- Partial failure continues processing remaining images (Requirement 9.3)
- All images succeed returns correct BatchResponse (Requirement 9.1, 9.2)
- Empty successful results still returns a valid ZIP (Requirement 9.3)
- asyncio.TimeoutError from pool.submit returns timeout error in results (Requirement 2.3)
- General Exception from pool.submit returns HTTP 500 error in results (Requirement 1.4)
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import tempfile
from unittest.mock import AsyncMock, patch

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from api.app import app
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager

_test_store: SessionStore = SessionStore(ttl=1800)
_test_registry: FileRegistry = FileRegistry()


class _MockWorkerPool:
    """Mock WorkerPoolManager that delegates submit to a configurable side_effect.
    模拟 WorkerPoolManager，将 submit 委托给可配置的 side_effect。
    """

    def __init__(self) -> None:
        self.submit = AsyncMock()

    @property
    def is_alive(self) -> bool:
        return True

    @property
    def max_workers(self) -> int:
        return 2


_mock_pool = _MockWorkerPool()


def setup_module(module):
    """Re-apply dependency overrides before this module's tests run.
    在本模块测试运行前重新设置依赖覆盖，确保跨文件测试隔离。
    """
    app.dependency_overrides[get_session_store] = lambda: _test_store
    app.dependency_overrides[get_file_registry] = lambda: _test_registry
    app.dependency_overrides[get_worker_pool] = lambda: _mock_pool


def teardown_module(module):
    """Remove this module's dependency overrides after all tests complete.
    本模块所有测试完成后移除依赖覆盖。
    """
    app.dependency_overrides.pop(get_session_store, None)
    app.dependency_overrides.pop(get_file_registry, None)
    app.dependency_overrides.pop(get_worker_pool, None)


# Apply overrides immediately for module-level client creation
setup_module(None)

client: TestClient = TestClient(app)


def _make_test_image_buf(name: str = "test.png") -> tuple[str, io.BytesIO, str]:
    """Create a minimal PNG image upload tuple (filename, buf, content_type)."""
    img = Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return (name, buf, "image/png")


def _make_fake_3mf(suffix: str = ".3mf") -> str:
    """Create a temporary fake 3MF file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.write(fd, b"fake-3mf-content")
    os.close(fd)
    return path


# =========================================================================
# 1. LUT not found returns 404 - Requirement 9
# =========================================================================


class TestBatchLutNotFound:
    """Verify unresolvable lut_name returns HTTP 404."""

    def test_batch_unknown_lut_returns_404(self) -> None:
        with patch(
            "api.routers.converter.generate.LUTManager.get_lut_path",
            return_value=None,
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("a.png"))],
                data={"lut_name": "nonexistent_lut"},
            )
        assert response.status_code == 404
        assert "LUT" in response.json()["detail"]


# =========================================================================
# 2. Partial failure continues processing - Requirement 9.3
# =========================================================================


class TestBatchPartialFailure:
    """Verify that if some images fail, remaining images still process."""

    def test_batch_partial_failure_continues(self) -> None:
        fake_3mf = _make_fake_3mf()
        call_count = 0

        async def _mock_submit(fn, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Simulated failure")
            return {"threemf_path": fake_3mf, "status_msg": "OK"}

        _mock_pool.submit = AsyncMock(side_effect=_mock_submit)

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[
                    ("images", _make_test_image_buf("fail.png")),
                    ("images", _make_test_image_buf("ok.png")),
                ],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert len(body["results"]) == 2

        # First image failed
        assert body["results"][0]["filename"] == "fail.png"
        assert body["results"][0]["status"] == "failed"
        assert body["results"][0]["error"] is not None

        # Second image succeeded
        assert body["results"][1]["filename"] == "ok.png"
        assert body["results"][1]["status"] == "success"

        # download_url present
        assert body["download_url"].startswith("/api/files/")


# =========================================================================
# 3. All images succeed - Requirement 9.1, 9.2
# =========================================================================


class TestBatchAllSuccess:
    """Verify all images succeed returns correct BatchResponse."""

    def test_batch_all_success(self) -> None:
        fake_3mf = _make_fake_3mf()

        _mock_pool.submit = AsyncMock(
            return_value={"threemf_path": fake_3mf, "status_msg": "OK"},
        )

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[
                    ("images", _make_test_image_buf("img1.png")),
                    ("images", _make_test_image_buf("img2.png")),
                ],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "2/2" in body["message"]
        assert len(body["results"]) == 2
        assert all(r["status"] == "success" for r in body["results"])
        assert body["download_url"].startswith("/api/files/")


# =========================================================================
# 4. All images fail returns status "failed" - Requirement 9.3
# =========================================================================


class TestBatchAllFailed:
    """Verify all images failing returns status 'failed' with valid ZIP."""

    def test_batch_all_fail(self) -> None:
        _mock_pool.submit = AsyncMock(
            side_effect=RuntimeError("boom"),
        )

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("bad.png"))],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert "0/1" in body["message"]
        assert body["results"][0]["status"] == "failed"
        assert body["download_url"].startswith("/api/files/")


# =========================================================================
# 5. Timeout returns timeout error in batch item - Requirement 2.3
# =========================================================================


class TestBatchTimeout:
    """Verify asyncio.TimeoutError from pool.submit is handled per-item."""

    def test_batch_timeout_per_item(self) -> None:
        _mock_pool.submit = AsyncMock(
            side_effect=asyncio.TimeoutError(),
        )

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("slow.png"))],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["results"][0]["status"] == "failed"
        assert "timed out" in body["results"][0]["error"].lower()


# =========================================================================
# 6. Worker pool receives correct function and args - Requirement 1.2, 2.1
# =========================================================================


class TestBatchWorkerPoolSubmit:
    """Verify pool.submit is called with worker_batch_convert_item and correct args."""

    def test_batch_submits_to_pool(self) -> None:
        fake_3mf = _make_fake_3mf()

        _mock_pool.submit = AsyncMock(
            return_value={"threemf_path": fake_3mf, "status_msg": "OK"},
        )

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new_callable=AsyncMock,
                return_value="/tmp/uploaded.png",
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("test.png"))],
                data={
                    "lut_name": "test_lut",
                    "target_width_mm": "80.0",
                    "spacer_thick": "1.4",
                    "structure_mode": "Single-sided",
                    "color_mode": "8-Color Max",
                    "modeling_mode": "high-fidelity",
                    "color_layers": "10",
                    "layer_height_mm": "0.08",
                    "quantize_colors": "64",
                    "enable_cleanup": "false",
                    "hue_weight": "0.5",
                    "chroma_gate": "12",
                    "enable_relief": "true",
                    "height_mode": "color",
                    "color_height_map": json.dumps(
                        {"#ff0000": 1.7, "#ffffff": 1.3}
                    ),
                    "heightmap_max_height": "4.2",
                },
            )

        assert response.status_code == 200

        # Verify pool.submit was called once (one image)
        assert _mock_pool.submit.call_count == 1

        # Verify the first argument is the worker function
        from api.workers.converter_workers import worker_batch_convert_item

        call_args = _mock_pool.submit.call_args
        assert call_args[0][0] is worker_batch_convert_item

        # Verify file path and lut_path are passed as scalars
        assert call_args[0][1] == "/tmp/uploaded.png"  # image_path
        assert call_args[0][2] == "/tmp/fake.npy"  # lut_path
        assert call_args[0][3] == 80.0  # target_width_mm
        assert call_args[0][4] == 1.4
        assert call_args[0][5] == "Single-sided"
        assert call_args[0][6] == "8-Color Max"
        assert call_args[0][7] == "high-fidelity"
        assert call_args[0][8] == 10
        assert call_args[0][9] == 0.08
        assert call_args[0][10] == 64
        assert call_args[0][11] is False
        assert call_args[0][12] == 0.5
        assert call_args[0][13] == 12
        assert call_args[0][14] is True
        assert call_args[0][15] == "color"
        assert call_args[0][16] == {"#ff0000": 1.7, "#ffffff": 1.3}
        assert call_args[0][17] == 4.2

    def test_batch_relief_requires_color_height_map(self) -> None:
        _mock_pool.submit = AsyncMock(
            return_value={"threemf_path": _make_fake_3mf(), "status_msg": "OK"},
        )

        with patch(
            "api.routers.converter.generate.LUTManager.get_lut_path",
            return_value="/tmp/fake.npy",
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("test.png"))],
                data={
                    "lut_name": "test_lut",
                    "enable_relief": "true",
                    "height_mode": "color",
                },
            )

        assert response.status_code == 422
        assert "color_height_map" in response.json()["detail"]
        assert _mock_pool.submit.call_count == 0


class TestBatchCleanup:
    """Verify batch route removes uploaded temps and packaged intermediates."""

    def test_batch_deletes_uploaded_png_temps_on_success_and_failure(self) -> None:
        temp_success = _make_fake_3mf(".png")
        temp_failure = _make_fake_3mf(".png")
        fake_3mf = _make_fake_3mf()
        temp_paths = iter([temp_success, temp_failure])
        call_count = 0

        async def _mock_submit(fn, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"threemf_path": fake_3mf, "status_msg": "OK"}
            raise RuntimeError("boom")

        _mock_pool.submit = AsyncMock(side_effect=_mock_submit)

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(side_effect=lambda _upload: next(temp_paths)),
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[
                    ("images", _make_test_image_buf("ok.png")),
                    ("images", _make_test_image_buf("fail.png")),
                ],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 200
        assert not os.path.exists(temp_success)
        assert not os.path.exists(temp_failure)
        assert not os.path.exists(fake_3mf)

    def test_batch_deletes_all_successful_3mf_files_after_zip_packaging(self) -> None:
        temp_one = _make_fake_3mf(".png")
        temp_two = _make_fake_3mf(".png")
        fake_3mf_one = _make_fake_3mf()
        fake_3mf_two = _make_fake_3mf()
        temp_paths = iter([temp_one, temp_two])
        output_paths = iter([fake_3mf_one, fake_3mf_two])

        async def _mock_submit(fn, *args, **kwargs):
            return {"threemf_path": next(output_paths), "status_msg": "OK"}

        _mock_pool.submit = AsyncMock(side_effect=_mock_submit)

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(side_effect=lambda _upload: next(temp_paths)),
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[
                    ("images", _make_test_image_buf("img1.png")),
                    ("images", _make_test_image_buf("img2.png")),
                ],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 200
        assert not os.path.exists(fake_3mf_one)
        assert not os.path.exists(fake_3mf_two)
