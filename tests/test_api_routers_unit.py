"""Router regressions for conversion, extraction, and calibration.
转换、提取和校准 API 的行为回归测试。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.dependencies import get_session_store
from api.session_store import SessionStore

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client() -> TestClient:
    """Create a fresh TestClient for each test.
    为每个测试创建独立的 TestClient。
    """
    return TestClient(create_app())


# ===========================================================================
# Unit Tests — Specific examples for each endpoint
# ===========================================================================


class TestConverterEndpoints:
    """Unit tests for Converter domain endpoints.
    Converter 领域端点的单元测试。
    """

    def test_post_preview_missing_lut_returns_404(self, client: TestClient) -> None:
        """POST /api/convert/preview with unknown LUT returns 404."""
        import io

        # Create a minimal valid PNG image
        from PIL import Image as _PILImage

        buf = io.BytesIO()
        _PILImage.new("RGB", (4, 4), (128, 64, 32)).save(buf, format="PNG")
        buf.seek(0)
        resp = client.post(
            "/api/convert/preview",
            files={"image": ("test.png", buf, "image/png")},
            data={"lut_name": "nonexistent_lut", "color_mode": "4-Color"},
        )
        assert resp.status_code == 404
        assert "LUT not found" in resp.json()["detail"]

    def test_post_preview_missing_image_returns_422(self, client: TestClient) -> None:
        """POST /api/convert/preview without image returns 422."""
        resp = client.post(
            "/api/convert/preview",
            data={"lut_name": "test_lut", "color_mode": "4-Color"},
        )
        assert resp.status_code == 422

    def test_post_preview_rejects_unsupported_upload_before_temp_write(
        self,
        client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """POST /api/convert/preview rejects non-image uploads deterministically."""
        import io

        monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
        upload_spy = AsyncMock()

        with (
            patch(
                "api.routers.converter.preview.LUTManager.resolve_source_selection",
                return_value=(str(tmp_path / "fake.npy"), "Fake LUT"),
            ),
            patch("api.file_bridge.upload_to_tempfile", upload_spy),
        ):
            resp = client.post(
                "/api/convert/preview",
                files={
                    "image": (
                        "notes.txt",
                        io.BytesIO(b"not image data"),
                        "text/plain",
                    )
                },
                data={"lut_name": "test_lut", "color_mode": "4-Color"},
            )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "不支持的图像文件类型" in detail
        assert "cannot identify image file" not in detail
        assert str(tmp_path) not in detail
        assert upload_spy.await_count == 0
        assert list(tmp_path.iterdir()) == []

    def test_post_generate_missing_session_returns_422(self, client: TestClient) -> None:
        """POST /api/convert/generate without valid body returns 422."""
        payload = {"lut_name": "test_lut"}
        resp = client.post("/api/convert/generate", json=payload)
        assert resp.status_code == 422

    def test_post_generate_unknown_session_returns_404(self, client: TestClient) -> None:
        """POST /api/convert/generate with unknown session returns 404."""
        payload = {
            "session_id": "nonexistent-session-id",
            "params": {"lut_name": "test_lut"},
        }
        resp = client.post("/api/convert/generate", json=payload)
        assert resp.status_code == 404

    def test_post_batch(self, client: TestClient) -> None:
        """POST /api/convert/batch without required files returns 422."""
        payload = {"params": {"lut_name": "test_lut"}}
        resp = client.post("/api/convert/batch", json=payload)
        assert resp.status_code == 422

    def test_post_replace_color(self, client: TestClient) -> None:
        """POST /api/convert/replace-color with unknown session returns 404."""
        payload = {
            "session_id": "abc123",
            "selected_color": "#ff0000",
            "replacement_color": "#00ff00",
        }
        resp = client.post("/api/convert/replace-color", json=payload)
        assert resp.status_code == 404

    def test_post_merge_colors(self, client: TestClient) -> None:
        """POST /api/convert/merge-colors with unknown session returns 404."""
        payload = {"session_id": "abc123"}
        resp = client.post("/api/convert/merge-colors", json=payload)
        assert resp.status_code == 404


class TestExtractorEndpoints:
    """Unit tests for Extractor domain endpoints.
    Extractor 领域端点的单元测试。
    """

    def test_post_extract(self, client: TestClient) -> None:
        """POST /api/extractor/extract without required image returns 422."""
        payload = {
            "color_mode": "4-Color (RYBW)",
            "corner_points": [[0, 0], [100, 0], [100, 100], [0, 100]],
        }
        resp = client.post("/api/extractor/extract", json=payload)
        assert resp.status_code == 422

    @pytest.mark.parametrize(
        "corner_points",
        [
            "[[0],[100,0],[100,100],[0,100]]",
            '[[0,"x"],[100,0],[100,100],[0,100]]',
        ],
    )
    def test_post_extract_invalid_corner_point_coordinates_returns_422(
        self,
        corner_points: str,
    ) -> None:
        """Malformed corner coordinates are client errors, not server errors."""
        local_client = TestClient(create_app(), raise_server_exceptions=False)

        resp = local_client.post(
            "/api/extractor/extract",
            data={
                "color_mode": "4-Color (RYBW)",
                "corner_points": corner_points,
            },
        )

        assert resp.status_code == 422
        assert "corner_points" in resp.text

    def test_post_manual_fix_missing_lut_path_returns_404(self, client: TestClient) -> None:
        """POST /api/extractor/manual-fix with nonexistent LUT is a client-visible 404."""
        payload = {
            "lut_path": "/tmp/test.npy",
            "cell_coord": [2, 3],
            "override_color": "#aabbcc",
        }
        resp = client.post("/api/extractor/manual-fix", json=payload)
        assert resp.status_code == 404
        assert "/tmp/test.npy" not in resp.text

    def test_post_manual_fix_unknown_session_returns_404_without_core_call(self) -> None:
        """Unknown manual-fix sessions must not fall back to the default LUT."""
        test_app = create_app()
        store = SessionStore(ttl=60)
        test_app.dependency_overrides[get_session_store] = lambda: store
        local_client = TestClient(test_app, raise_server_exceptions=False)

        try:
            with patch("api.routers.extractor.manual_fix_cell") as manual_fix_mock:
                resp = local_client.post(
                    "/api/extractor/manual-fix",
                    json={
                        "session_id": "missing-session",
                        "row_index": 0,
                        "override_color": "#aabbcc",
                    },
                )
        finally:
            test_app.dependency_overrides.pop(get_session_store, None)

        assert resp.status_code == 404
        manual_fix_mock.assert_not_called()

    def test_post_manual_fix_session_without_lut_returns_409_without_core_call(self) -> None:
        """Existing sessions without a LUT path require re-extraction."""
        test_app = create_app()
        store = SessionStore(ttl=60)
        session_id = store.create("manual-empty-session")
        test_app.dependency_overrides[get_session_store] = lambda: store
        local_client = TestClient(test_app, raise_server_exceptions=False)

        try:
            with patch("api.routers.extractor.manual_fix_cell") as manual_fix_mock:
                resp = local_client.post(
                    "/api/extractor/manual-fix",
                    json={
                        "session_id": session_id,
                        "row_index": 0,
                        "override_color": "#aabbcc",
                    },
                )
        finally:
            test_app.dependency_overrides.pop(get_session_store, None)

        assert resp.status_code == 409
        manual_fix_mock.assert_not_called()

    def test_post_manual_fix_session_missing_lut_file_returns_409_without_core_call(
        self,
        tmp_path: Path,
    ) -> None:
        """A session whose LUT file was cleaned up must not call core manual fix."""
        test_app = create_app()
        store = SessionStore(ttl=60)
        session_id = store.create("manual-missing-lut-session")
        missing_lut = tmp_path / "deleted-lut.json"
        store.put(session_id, "lut_path", str(missing_lut))
        test_app.dependency_overrides[get_session_store] = lambda: store
        local_client = TestClient(test_app, raise_server_exceptions=False)

        try:
            with patch("api.routers.extractor.manual_fix_cell") as manual_fix_mock:
                resp = local_client.post(
                    "/api/extractor/manual-fix",
                    json={
                        "session_id": session_id,
                        "row_index": 0,
                        "override_color": "#aabbcc",
                    },
                )
        finally:
            test_app.dependency_overrides.pop(get_session_store, None)

        assert resp.status_code == 409
        assert str(missing_lut) not in resp.text
        manual_fix_mock.assert_not_called()

    def test_post_manual_fix_requires_session_or_lut_path(self, client: TestClient) -> None:
        """Manual fix must identify the edited LUT via session_id or lut_path."""
        resp = client.post(
            "/api/extractor/manual-fix",
            json={
                "row_index": 0,
                "override_color": "#aabbcc",
            },
        )

        assert resp.status_code == 422
        assert "session_id or lut_path" in resp.text

    def test_post_manual_fix_requires_cell_locator(self, client: TestClient) -> None:
        """POST /api/extractor/manual-fix requires row_index or cell_coord."""
        payload = {
            "lut_path": "/tmp/test.npy",
            "override_color": "#aabbcc",
        }

        resp = client.post("/api/extractor/manual-fix", json=payload)

        assert resp.status_code == 422
        assert "row_index or cell_coord" in resp.text

    def test_post_manual_fix_accepts_row_index_only(
        self,
        client: TestClient,
        tmp_path: Path,
    ) -> None:
        """POST /api/extractor/manual-fix must not require cell_coord for logging."""
        preview = np.zeros((2, 2, 3), dtype=np.uint8)
        lut_path = tmp_path / "test.json"
        lut_path.write_text("{}", encoding="utf-8")
        payload = {
            "lut_path": str(lut_path),
            "row_index": 5,
            "override_color": "#aabbcc",
        }

        with patch(
            "api.routers.extractor.LUTManager.load_lut_with_metadata",
            return_value=(np.zeros((32, 3), dtype=np.uint8), None, None),
        ), patch(
            "api.routers.extractor.manual_fix_cell",
            return_value=(preview, "[OK] Cell updated"),
        ):
            resp = client.post("/api/extractor/manual-fix", json=payload)

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["lut_preview_url"].startswith("/api/files/")

    def test_post_manual_fix_out_of_range_target_returns_422(
        self,
        client: TestClient,
        tmp_path: Path,
    ) -> None:
        """Manual-fix target misses are client validation errors, not 500s."""
        lut_path = tmp_path / "test.json"
        lut_path.write_text("{}", encoding="utf-8")
        payload = {
            "lut_path": str(lut_path),
            "row_index": 999999,
            "override_color": "#aabbcc",
        }

        with patch(
            "api.routers.extractor.LUTManager.load_lut_with_metadata",
            return_value=(np.zeros((32, 3), dtype=np.uint8), None, None),
        ), patch(
            "api.routers.extractor.manual_fix_cell",
            return_value=(None, "[WARNING] 索引超出范围"),
        ):
            resp = client.post("/api/extractor/manual-fix", json=payload)

        assert resp.status_code == 422
        assert resp.json()["detail"] == (
            "Manual correction target is outside the current LUT. "
            "Refresh the preview and try again."
        )
        assert "[WARNING]" not in resp.text

    def test_post_manual_fix_invalid_color_returns_422(
        self,
        client: TestClient,
        tmp_path: Path,
    ) -> None:
        """Manual-fix color parse failures are client validation errors."""
        lut_path = tmp_path / "test.json"
        lut_path.write_text("{}", encoding="utf-8")
        payload = {
            "lut_path": str(lut_path),
            "row_index": 0,
            "override_color": "not-a-color",
        }

        with patch(
            "api.routers.extractor.LUTManager.load_lut_with_metadata",
            return_value=(np.zeros((32, 3), dtype=np.uint8), None, None),
        ), patch(
            "api.routers.extractor.manual_fix_cell",
            return_value=(None, "[ERROR] 格式错误: not-a-color"),
        ):
            resp = client.post("/api/extractor/manual-fix", json=payload)

        assert resp.status_code == 422
        assert resp.json()["detail"] == (
            "Manual correction color is invalid. Use a valid hex or RGB color."
        )
        assert "[ERROR]" not in resp.text
        assert "not-a-color" not in resp.text

    def test_post_manual_fix_unknown_core_failure_stays_500(
        self,
        client: TestClient,
        tmp_path: Path,
    ) -> None:
        """Unknown core manual-fix misses remain server errors."""
        lut_path = tmp_path / "test.json"
        lut_path.write_text("{}", encoding="utf-8")
        payload = {
            "lut_path": str(lut_path),
            "row_index": 0,
            "override_color": "#aabbcc",
        }

        with patch(
            "api.routers.extractor.LUTManager.load_lut_with_metadata",
            return_value=(np.zeros((32, 3), dtype=np.uint8), None, None),
        ), patch(
            "api.routers.extractor.manual_fix_cell",
            return_value=(None, "unexpected manual fix failure"),
        ):
            resp = client.post("/api/extractor/manual-fix", json=payload)

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Manual fix failed"
        assert "unexpected manual fix failure" not in resp.text

    def test_post_manual_fix_accepts_session_lut_path(self, tmp_path: Path) -> None:
        """The frontend session-based manual-fix contract still succeeds."""
        test_app = create_app()
        store = SessionStore(ttl=60)
        session_id = store.create("manual-valid-session")
        lut_path = tmp_path / "session-lut.json"
        lut_path.write_text("{}", encoding="utf-8")
        store.put(session_id, "lut_path", str(lut_path))
        test_app.dependency_overrides[get_session_store] = lambda: store
        local_client = TestClient(test_app, raise_server_exceptions=False)
        preview = np.zeros((2, 2, 3), dtype=np.uint8)

        try:
            with patch(
                "api.routers.extractor.LUTManager.load_lut_with_metadata",
                return_value=(np.zeros((32, 3), dtype=np.uint8), None, None),
            ), patch(
                "api.routers.extractor.manual_fix_cell",
                return_value=(preview, "[OK] Cell updated"),
            ):
                resp = local_client.post(
                    "/api/extractor/manual-fix",
                    json={
                        "session_id": session_id,
                        "row_index": 5,
                        "override_color": "#aabbcc",
                    },
                )
        finally:
            test_app.dependency_overrides.pop(get_session_store, None)

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["lut_preview_url"].startswith("/api/files/")

    @pytest.mark.parametrize(
        "lut_path_value",
        [None, "", "   ", 123],
    )
    def test_resolve_cell_session_without_lut_returns_409(
        self,
        lut_path_value: Any,
    ) -> None:
        """Resolve-cell requires an active session LUT path before layout parsing."""
        test_app = create_app()
        store = SessionStore(ttl=60)
        session_id = store.create("resolve-missing-lut-session")
        if lut_path_value is not None:
            store.put(session_id, "lut_path", lut_path_value)
        test_app.dependency_overrides[get_session_store] = lambda: store
        local_client = TestClient(test_app, raise_server_exceptions=False)

        try:
            with patch("api.routers.extractor.LUTManager.load_lut_with_metadata") as load_mock:
                resp = local_client.post(
                    "/api/extractor/resolve-cell",
                    json={
                        "session_id": session_id,
                        "x": 0.5,
                        "y": 0.5,
                        "card_index": 0,
                    },
                )
        finally:
            test_app.dependency_overrides.pop(get_session_store, None)

        assert resp.status_code == 409
        load_mock.assert_not_called()

    def test_resolve_cell_session_missing_lut_file_returns_409_without_lut_load(
        self,
        tmp_path: Path,
    ) -> None:
        """A cleaned-up LUT file is stale session state, not an invalid click."""
        test_app = create_app()
        store = SessionStore(ttl=60)
        session_id = store.create("resolve-missing-lut-file-session")
        missing_lut = tmp_path / "deleted-lut.json"
        store.put(session_id, "lut_path", str(missing_lut))
        test_app.dependency_overrides[get_session_store] = lambda: store
        local_client = TestClient(test_app, raise_server_exceptions=False)

        try:
            with patch("api.routers.extractor.LUTManager.load_lut_with_metadata") as load_mock:
                resp = local_client.post(
                    "/api/extractor/resolve-cell",
                    json={
                        "session_id": session_id,
                        "x": 0.5,
                        "y": 0.5,
                        "card_index": 0,
                    },
                )
        finally:
            test_app.dependency_overrides.pop(get_session_store, None)

        assert resp.status_code == 409
        assert str(missing_lut) not in resp.text
        assert "Clicked cell is outside" not in resp.text
        load_mock.assert_not_called()

    def test_resolve_cell_outside_lut_area_still_returns_404(self, tmp_path: Path) -> None:
        """A real valid-LUT blank-area click keeps the existing outside-area error."""
        test_app = create_app()
        store = SessionStore(ttl=60)
        session_id = store.create("resolve-outside-lut-session")
        lut_path = tmp_path / "valid-lut.json"
        lut_path.write_text("{}", encoding="utf-8")
        store.put(session_id, "lut_path", str(lut_path))
        store.put(session_id, "color_mode", "BW")
        test_app.dependency_overrides[get_session_store] = lambda: store
        local_client = TestClient(test_app, raise_server_exceptions=False)

        try:
            with patch(
                "api.routers.extractor.LUTManager.load_lut_with_metadata",
                return_value=(np.zeros((32, 3), dtype=np.uint8), None, None),
            ):
                resp = local_client.post(
                    "/api/extractor/resolve-cell",
                    json={
                        "session_id": session_id,
                        "x": 0.99,
                        "y": 0.99,
                        "card_index": 0,
                    },
                )
        finally:
            test_app.dependency_overrides.pop(get_session_store, None)

        assert resp.status_code == 404
        assert "Clicked cell is outside the valid LUT area" in resp.text

    def test_resolve_cell_invalid_card_index_returns_422(self, tmp_path: Path) -> None:
        """POST /api/extractor/resolve-cell maps invalid card_index to 422."""
        test_app = create_app()
        store = SessionStore(ttl=60)
        session_id = store.create()
        lut_path = tmp_path / "valid-lut.json"
        lut_path.write_text("{}", encoding="utf-8")
        store.put(session_id, "lut_path", str(lut_path))
        store.put(session_id, "color_mode", "8-Color Max")
        test_app.dependency_overrides[get_session_store] = lambda: store
        local_client = TestClient(test_app, raise_server_exceptions=False)

        try:
            with patch(
                "api.routers.extractor.LUTManager.load_lut_with_metadata",
                return_value=(np.zeros((2738, 3), dtype=np.uint8), None, None),
            ):
                resp = local_client.post(
                    "/api/extractor/resolve-cell",
                    json={
                        "session_id": session_id,
                        "x": 0.5,
                        "y": 0.5,
                        "card_index": 99,
                    },
                )
        finally:
            test_app.dependency_overrides.pop(get_session_store, None)

        assert resp.status_code == 422
        assert "card_index" in resp.text


class TestCalibrationEndpoints:
    """Unit tests for Calibration domain endpoints.
    Calibration 领域端点的单元测试。
    """

    def test_post_generate(self, client: TestClient) -> None:
        """POST /api/calibration/generate returns CalibrationResponse."""
        payload = {"color_mode": "4-Color (RYBW)", "block_size": 5}
        resp = client.post("/api/calibration/generate", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "download_url" in body
        assert "preview_url" in body
        assert body["download_url"].startswith("/api/files/")
        assert body["preview_url"].startswith("/api/files/")
