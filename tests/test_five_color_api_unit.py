"""Unit tests for the Five-Color Query API endpoints.
五色组合查询 API 端点的单元测试。

Tests cover:
- NPZ file loading returns correct base colors (Req 1.2)
- NPY file loading returns correct base colors (Req 1.3)
- Non-existent LUT returns 404 (Req 1.4)
- Successful query returns correct result (Req 2.1)
- Query with no match returns found=false (Req 2.4)
- Swatch generation derives canonical LUT metadata server-side
- Swatch generation isolates file registry sessions per request
"""

import json
import logging
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from types import SimpleNamespace

from api.app import create_app
from api.dependencies import get_file_registry
from api.file_registry import FileRegistry
from api.routers.five_color import _engine_cache
from api.schemas.five_color import BaseColorsResponse
from config import LUTMetadata, PaletteEntry
from core.five_color_combination import ColorQueryEngine, StackLUTLoader

client = TestClient(create_app())


@pytest.fixture(autouse=True)
def _clear_engine_cache():
    """Clear the five-color engine cache before each test."""
    _engine_cache.clear()
    yield
    _engine_cache.clear()

# ---------------------------------------------------------------------------
# Synthetic data helpers
# ---------------------------------------------------------------------------

def _make_npz_data():
    """Create synthetic NPZ-style stack_lut and rgb_data arrays."""
    stack_lut = np.array(
        [[0, 1, 2, 3, 4], [1, 2, 3, 4, 0], [0, 0, 0, 0, 0]],
        dtype=np.int64,
    )
    rgb_data = np.array(
        [[255, 128, 64], [100, 200, 50], [10, 20, 30]],
        dtype=np.int64,
    )
    return stack_lut, rgb_data


def _metadata_json_for_palette(size: int) -> np.ndarray:
    metadata = LUTMetadata(
        palette=[
            PaletteEntry(color=f"Color {index}", material="PLA Basic")
            for index in range(size)
        ],
        color_mode="5-Color Extended" if size == 5 else None,
    )
    return np.array(json.dumps(metadata.to_dict(), ensure_ascii=False))


def test_base_colors_schema_documents_combinations_contract():
    """Document null and empty-list combinations semantics separately."""
    schema = BaseColorsResponse.model_json_schema()
    description = schema["properties"]["combinations"]["description"]

    assert "null" in description
    assert "空列表表示没有合法的五色组合" in description
    assert "空则所有组合合法" not in description


class _FakeSwatchEngine:
    """Test double exposing canonical LUT metadata for swatch generation."""

    def __init__(self, expected_selection_length: int = 5) -> None:
        self._expected_selection_length = expected_selection_length
        self.color_count = 6
        self._base_colors = [
            (255, 0, 0),
            (0, 255, 0),
            (0, 0, 255),
            (255, 255, 0),
            (255, 0, 255),
            (0, 255, 255),
        ]
        self._color_names = ["Red", "Green", "Blue", "Yellow", "Magenta", "Cyan"]
        self._query_results = {
            (0, 1, 2, 3, 4): SimpleNamespace(
                found=True,
                selected_indices=[0, 1, 2, 3, 4],
                result_rgb=(1, 2, 3),
                row_index=0,
                message="ok",
                source="",
            ),
            (4, 1, 2, 3, 0, 4): SimpleNamespace(
                found=True,
                selected_indices=[4, 1, 2, 3, 0, 4],
                result_rgb=(4, 5, 6),
                row_index=1,
                message="ok",
                source="",
            )
        }

    def get_base_colors(self):
        return self._base_colors

    def get_color_names(self):
        return self._color_names

    def expected_selection_length(self):
        return self._expected_selection_length

    def accepted_selection_lengths(self):
        return (self._expected_selection_length,)

    def query(self, selected_indices):
        return self._query_results.get(
            tuple(selected_indices),
            SimpleNamespace(
                found=False,
                selected_indices=list(selected_indices),
                result_rgb=None,
                row_index=-1,
                message="missing",
                source="",
            ),
        )


class _FakeRegistry:
    """Capture registry writes without touching disk."""

    def __init__(self) -> None:
        self.path_calls: list[dict[str, str | None]] = []
        self.bytes_calls: list[dict[str, str | None]] = []
        self._counter = 0

    def register_path(
        self,
        session_id: str,
        path: str,
        filename: str | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        self.path_calls.append(
            {
                "session_id": session_id,
                "path": path,
                "filename": filename,
                "ttl_seconds": None if ttl_seconds is None else str(ttl_seconds),
            }
        )
        self._counter += 1
        return f"path-{self._counter}"

    def register_bytes(
        self,
        session_id: str,
        data: bytes,
        filename: str,
        ttl_seconds: int | None = None,
    ) -> str:
        self.bytes_calls.append(
            {
                "session_id": session_id,
                "filename": filename,
                "ttl_seconds": None if ttl_seconds is None else str(ttl_seconds),
            }
        )
        self._counter += 1
        return f"bytes-{self._counter}"


class _SwatchRegisterPathFailingRegistry(FileRegistry):
    """Registry stub that records the swatch path before failing."""

    def __init__(self) -> None:
        super().__init__()
        self.generated_path: str | None = None

    def register_path(self, *args: object, **kwargs: object) -> str:
        path = kwargs.get("path")
        if path is None and len(args) >= 2:
            path = args[1]
        self.generated_path = str(path) if path is not None else None
        raise RuntimeError("registry backend unavailable")


class _SwatchRegisterBytesFailingRegistry(FileRegistry):
    """Registry stub that fails after the swatch path is registered."""

    def __init__(self) -> None:
        super().__init__()
        self.path_file_id: str | None = None

    def register_path(self, *args: object, **kwargs: object) -> str:
        self.path_file_id = super().register_path(*args, **kwargs)
        return self.path_file_id

    def register_bytes(self, *args: object, **kwargs: object) -> str:
        raise RuntimeError("registry byte storage unavailable")


# ---------------------------------------------------------------------------
# GET /api/five-color/base-colors
# ---------------------------------------------------------------------------

def test_get_base_colors_npz():
    """NPZ file loading returns correct base colors."""
    stack_lut, rgb_data = _make_npz_data()

    with (
        patch(
            "api.routers.five_color.LUTManager.get_lut_path",
            return_value="/fake/path/test.npz",
        ),
        patch(
            "api.routers.five_color.StackLUTLoader.load_npz_file",
            return_value=(True, "ok", stack_lut, rgb_data),
        ),
    ):
        resp = client.get("/api/five-color/base-colors", params={"lut_name": "test_lut"})

    assert resp.status_code == 200
    body = resp.json()
    # ColorQueryEngine infers color_count from max(stack_lut)+1 = 5
    assert body["color_count"] == 5
    assert len(body["colors"]) == 5

    first = body["colors"][0]
    assert first["index"] == 0
    assert first["rgb"] == [255, 128, 64]
    assert first["hex"] == "#FF8040"


def test_get_base_colors_npy_labels_bambulab_magenta_and_green():
    rgb_data = np.zeros((2738, 3), dtype=np.uint8)
    rgb_data[:8] = np.array(
        [
            [237, 241, 242],
            [74, 155, 243],
            [223, 96, 163],
            [243, 239, 47],
            [54, 54, 54],
            [224, 85, 79],
            [60, 89, 209],
            [110, 202, 98],
        ],
        dtype=np.uint8,
    )

    with (
        patch(
            "api.routers.five_color.LUTManager.get_lut_path",
            return_value="/fake/path/bambulab-8c.npy",
        ),
        patch(
            "api.routers.five_color.StackLUTLoader.load_lut_rgb",
            return_value=(True, "ok", rgb_data),
        ),
        patch(
            "api.routers.five_color.StackFileManager.find_stack_file",
            return_value=None,
        ),
    ):
        resp = client.get("/api/five-color/base-colors", params={"lut_name": "bambulab_8c"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["colors"][2]["hex"] == "#DF60A3"
    assert body["colors"][2]["name"] == "品红"
    assert body["colors"][7]["hex"] == "#6ECA62"
    assert body["colors"][7]["name"] == "绿"


def test_empty_stack_npz_routes_use_dynamic_matching(tmp_path):
    """Empty-column NPZ stack data is treated like a dynamic LUT."""
    rgb_data = np.zeros((1024, 3), dtype=np.uint8)
    rgb_data[0] = np.array([255, 0, 0], dtype=np.uint8)
    rgb_data[1] = np.array([0, 255, 0], dtype=np.uint8)
    rgb_data[2] = np.array([0, 0, 255], dtype=np.uint8)
    rgb_data[3] = np.array([255, 255, 255], dtype=np.uint8)
    rgb_data[27] = np.array([12, 34, 56], dtype=np.uint8)
    stack_lut = np.zeros((1024, 0), dtype=np.int64)
    lut_path = tmp_path / "empty-stack.npz"
    np.savez(lut_path, rgb=rgb_data, stacks=stack_lut)

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        base_resp = client.get("/api/five-color/base-colors", params={"lut_name": "test_lut"})
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )

    assert base_resp.status_code == 200
    base_body = base_resp.json()
    assert base_body["color_count"] == 4
    assert base_body["combinations"] is None

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is True
    assert match_body["row_index"] == 27
    assert match_body["selected_indices"] == [0, 0, 1, 2, 3]
    assert match_body["matched_hex"] == "#0C2238"


def test_stackless_npz_routes_use_dynamic_matching(tmp_path):
    """NPZ data without a stacks key falls back to dynamic row decoding."""
    rgb_data = np.zeros((1024, 3), dtype=np.uint8)
    rgb_data[0] = np.array([255, 0, 0], dtype=np.uint8)
    rgb_data[1] = np.array([0, 255, 0], dtype=np.uint8)
    rgb_data[2] = np.array([0, 0, 255], dtype=np.uint8)
    rgb_data[3] = np.array([255, 255, 255], dtype=np.uint8)
    rgb_data[27] = np.array([12, 34, 56], dtype=np.uint8)
    lut_path = tmp_path / "stackless.npz"
    np.savez(lut_path, rgb=rgb_data)

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        base_resp = client.get("/api/five-color/base-colors", params={"lut_name": "test_lut"})
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )

    assert base_resp.status_code == 200
    base_body = base_resp.json()
    assert base_body["color_count"] == 4
    assert base_body["combinations"] is None

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is True
    assert match_body["row_index"] == 27
    assert match_body["selected_indices"] == [0, 0, 1, 2, 3]
    assert match_body["matched_hex"] == "#0C2238"


def test_stackless_npz_uses_metadata_palette_for_dynamic_recipe_reliability(tmp_path):
    """A stackless NPZ with five palette colors is not a complete 5^5 table at 1024 rows."""
    rgb_data = np.zeros((1024, 3), dtype=np.uint8)
    rgb_data[27] = np.array([12, 34, 56], dtype=np.uint8)
    lut_path = tmp_path / "stackless-five-palette.npz"
    np.savez(lut_path, rgb=rgb_data, metadata_json=_metadata_json_for_palette(5))

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 27
    assert body["matched_hex"] == "#0C2238"
    assert body["reason"] == "recipe_unavailable"


def test_stackless_partial_npz_reports_no_manual_combinations(tmp_path):
    """Stackless partial LUTs cannot expose manual recipe combinations."""
    rgb_data = np.zeros((2468, 3), dtype=np.uint8)
    lut_path = tmp_path / "stackless-partial.npz"
    np.savez(lut_path, rgb=rgb_data)

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "stackless_partial"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["color_count"] == 5
    assert body["combinations"] == []


def test_npz_stack_rows_are_validated_against_metadata_palette(tmp_path):
    """Metadata palette size must bound stack recipe indices."""
    rgb_data = np.array([[12, 34, 56]], dtype=np.uint8)
    stack_lut = np.array([[0, 1, 2, 3, 7]], dtype=np.int64)
    lut_path = tmp_path / "out-of-palette-stack.npz"
    np.savez(
        lut_path,
        rgb=rgb_data,
        stacks=stack_lut,
        metadata_json=_metadata_json_for_palette(5),
    )

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 0
    assert body["matched_hex"] == "#0C2238"
    assert body["reason"] == "recipe_unavailable"


def test_npz_without_metadata_uses_row_count_for_stack_value_bounds(tmp_path):
    """Legacy NPZ stack rows must still be bounded by row-count-detected color count."""
    rgb_data = np.zeros((1024, 3), dtype=np.uint8)
    rgb_data[0] = np.array([12, 34, 56], dtype=np.uint8)
    stack_lut = np.zeros((1024, 5), dtype=np.int64)
    stack_lut[0] = np.array([0, 1, 2, 3, 4], dtype=np.int64)
    lut_path = tmp_path / "legacy-out-of-range-stack.npz"
    np.savez(lut_path, rgb=rgb_data, stacks=stack_lut)

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 0
    assert body["matched_hex"] == "#0C2238"
    assert body["reason"] == "recipe_unavailable"


def test_npz_without_metadata_rejects_stack_inferred_unsupported_color_count(tmp_path):
    """Legacy NPZ stacks must not use outlier material ids to define their own palette size."""
    rgb_data = np.array([[12, 34, 56]], dtype=np.uint8)
    stack_lut = np.array([[0, 1, 2, 3, 99]], dtype=np.int64)
    lut_path = tmp_path / "legacy-unsupported-stack-count.npz"
    np.savez(lut_path, rgb=rgb_data, stacks=stack_lut)

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "legacy_unsupported_stack_count", "target_hex": "#0C2238"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 0
    assert body["matched_hex"] == "#0C2238"
    assert body["selected_indices"] == []
    assert body["reason"] == "recipe_unavailable"


def test_npz_without_metadata_text_stack_values_do_not_fail_loading(tmp_path):
    """Text stack members in legacy NPZ files must not escape as load failures."""
    rgb_data = np.array([[12, 34, 56]], dtype=np.uint8)
    stack_lut = np.array([["Unknown", "1", "2", "3", "4"]])
    lut_path = tmp_path / "legacy-text-stack.npz"
    np.savez(lut_path, rgb=rgb_data, stacks=stack_lut)

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "legacy_text_stack", "target_hex": "#0C2238"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 0
    assert body["matched_hex"] == "#0C2238"
    assert body["selected_indices"] == []
    assert body["reason"] == "recipe_unavailable"


def test_npz_without_metadata_precise_fraction_string_is_not_rounded(tmp_path):
    """High-precision stack strings must not be rounded into recipe indices."""
    rgb_data = np.array([[12, 34, 56]], dtype=np.uint8)
    stack_lut = np.array([["0", "1.0000000000000001", "2", "3", "4"]])
    lut_path = tmp_path / "legacy-precise-fraction-stack.npz"
    np.savez(lut_path, rgb=rgb_data, stacks=stack_lut)

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "legacy_precise_fraction_stack", "target_hex": "#0C2238"},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "legacy_precise_fraction_stack"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is False
    assert match_body["row_index"] == 0
    assert match_body["matched_hex"] == "#0C2238"
    assert match_body["selected_indices"] == []
    assert match_body["reason"] == "recipe_unavailable"
    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == []


def test_npz_without_metadata_integer_float_stack_is_unavailable(tmp_path):
    """Float stack members must not be accepted as strict integer recipe indices."""
    rgb_data = np.array([[12, 34, 56]], dtype=np.uint8)
    stack_lut = np.array([[0.0, 1.0, 2.0, 3.0, 4.0]], dtype=float)
    lut_path = tmp_path / "legacy-integer-float-stack.npz"
    np.savez(lut_path, rgb=rgb_data, stacks=stack_lut)

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "legacy_integer_float_stack", "target_hex": "#0C2238"},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "legacy_integer_float_stack"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is False
    assert match_body["row_index"] == 0
    assert match_body["matched_hex"] == "#0C2238"
    assert match_body["selected_indices"] == []
    assert match_body["reason"] == "recipe_unavailable"
    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == []


def test_npz_without_metadata_overlong_numeric_string_is_not_a_500(tmp_path):
    """Overlong numeric stack strings must be unavailable recipes, not API failures."""
    rgb_data = np.array([[12, 34, 56]], dtype=np.uint8)
    stack_lut = np.array([["0", "1", "2", "3", "1" * 5000]])
    lut_path = tmp_path / "legacy-overlong-numeric-string-stack.npz"
    np.savez(lut_path, rgb=rgb_data, stacks=stack_lut)

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "legacy_overlong_numeric_string_stack", "target_hex": "#0C2238"},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "legacy_overlong_numeric_string_stack"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is False
    assert match_body["row_index"] == 0
    assert match_body["matched_hex"] == "#0C2238"
    assert match_body["selected_indices"] == []
    assert match_body["reason"] == "recipe_unavailable"
    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == []


def test_npz_object_sources_do_not_enable_pickle_loading(tmp_path):
    """Object-dtype NPZ sources must be ignored instead of enabling pickle loading."""
    lut_path = tmp_path / "object-sources.npz"
    np.savez(
        lut_path,
        rgb=np.array([[12, 34, 56]], dtype=np.uint8),
        stacks=np.array([[0, 1, 2, 3, 4]], dtype=np.int64),
        sources=np.array([{"unsafe": True}], dtype=object),
    )

    assert StackLUTLoader.load_sources_from_json(str(lut_path)) == []


def test_load_stack_lut_accepts_six_column_recipes(tmp_path):
    """Standalone stack .npy files may carry 5C Extended six-layer recipes."""
    stack_path = tmp_path / "five_color_extended_stack.npy"
    np.save(stack_path, np.array([[4, 1, 2, 3, 0, 4]], dtype=np.int32))

    ok, message, stack = StackLUTLoader.load_stack_lut(str(stack_path))

    assert ok is True
    assert "成功加载 1 个组合" in message
    assert stack is not None
    assert stack.shape == (1, 6)
    assert stack[0].tolist() == [4, 1, 2, 3, 0, 4]


def test_npz_object_stack_values_do_not_fail_loading(tmp_path):
    """Object-dtype stack members must be treated as unavailable recipes, not load failures."""
    rgb_data = np.array([[12, 34, 56]], dtype=np.uint8)
    stack_lut = np.array([[{"unknown": True}, "1", "2", "3", "4"]], dtype=object)
    lut_path = tmp_path / "legacy-object-stack.npz"
    np.savez(lut_path, rgb=rgb_data, stacks=stack_lut)

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "legacy_object_stack", "target_hex": "#0C2238"},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "legacy_object_stack"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is False
    assert match_body["row_index"] == 0
    assert match_body["matched_hex"] == "#0C2238"
    assert match_body["selected_indices"] == []
    assert match_body["reason"] == "recipe_unavailable"
    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == []


def test_npz_metadata_object_stack_values_do_not_fail_loading(tmp_path):
    """Object-dtype stacks with metadata must still load RGB and palette metadata."""
    rgb_data = np.array([[12, 34, 56]], dtype=np.uint8)
    stack_lut = np.array([[{"unknown": True}, "1", "2", "3", "4"]], dtype=object)
    lut_path = tmp_path / "metadata-object-stack.npz"
    np.savez(
        lut_path,
        rgb=rgb_data,
        stacks=stack_lut,
        metadata_json=_metadata_json_for_palette(5),
    )

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "metadata_object_stack", "target_hex": "#0C2238"},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "metadata_object_stack"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is False
    assert match_body["row_index"] == 0
    assert match_body["matched_hex"] == "#0C2238"
    assert match_body["selected_indices"] == []
    assert match_body["reason"] == "recipe_unavailable"
    assert base_resp.status_code == 200
    base_body = base_resp.json()
    assert base_body["color_count"] == 5
    assert base_body["combinations"] == []


def test_npz_empty_row_stack_allows_full_cartesian_dynamic_recipes(tmp_path):
    """A real empty-row stack table remains stackless and can use full Cartesian row decoding."""
    rgb_data = np.zeros((3125, 3), dtype=np.uint8)
    rgb_data[100] = np.array([10, 20, 30], dtype=np.uint8)
    stack_lut = np.empty((0, 5), dtype=np.int64)
    lut_path = tmp_path / "full-cartesian-empty-row-stack.npz"
    np.savez(lut_path, rgb=rgb_data, stacks=stack_lut)

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "full_cartesian_empty_row_stack", "target_hex": "#0A141E"},
        )
        query_resp = client.post(
            "/api/five-color/query",
            json={"lut_name": "full_cartesian_empty_row_stack", "selected_indices": [0, 0, 4, 0, 0]},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is True
    assert match_body["row_index"] == 100
    assert match_body["selected_indices"] == [0, 0, 4, 0, 0]
    assert match_body["matched_hex"] == "#0A141E"

    assert query_resp.status_code == 200
    query_body = query_resp.json()
    assert query_body["found"] is True
    assert query_body["result_hex"] == "#0A141E"


def test_npz_empty_column_stack_allows_full_cartesian_dynamic_recipes(tmp_path):
    """A real empty-column stack table remains stackless for dynamic row decoding."""
    rgb_data = np.zeros((32, 3), dtype=np.uint8)
    rgb_data[19] = np.array([10, 20, 30], dtype=np.uint8)
    stack_lut = np.empty((0, 0), dtype=np.int64)
    lut_path = tmp_path / "full-cartesian-empty-column-stack.npz"
    np.savez(lut_path, rgb=rgb_data, stacks=stack_lut)

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "full_cartesian_empty_column_stack", "target_hex": "#0A141E"},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "full_cartesian_empty_column_stack"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is True
    assert match_body["row_index"] == 19
    assert match_body["selected_indices"] == [1, 0, 0, 1, 1]
    assert match_body["matched_hex"] == "#0A141E"
    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] is None


def test_npz_full_cartesian_object_stack_does_not_fall_back_to_dynamic_recipes(tmp_path):
    """Unreadable stack tables must not be treated as genuinely stackless full Cartesian LUTs."""
    rgb_data = np.zeros((3125, 3), dtype=np.uint8)
    rgb_data[100] = np.array([10, 20, 30], dtype=np.uint8)
    stack_lut = np.empty((3125, 5), dtype=object)
    stack_lut[:] = 0
    stack_lut[100] = [{"unknown": True}, "1", "2", "3", "4"]
    lut_path = tmp_path / "full-cartesian-object-stack.npz"
    np.savez(lut_path, rgb=rgb_data, stacks=stack_lut)

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "full_cartesian_object_stack", "target_hex": "#0A141E"},
        )
        query_resp = client.post(
            "/api/five-color/query",
            json={"lut_name": "full_cartesian_object_stack", "selected_indices": [0, 0, 4, 0, 0]},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is False
    assert match_body["row_index"] == 100
    assert match_body["matched_hex"] == "#0A141E"
    assert match_body["selected_indices"] == []
    assert match_body["reason"] == "recipe_unavailable"

    assert query_resp.status_code == 200
    query_body = query_resp.json()
    assert query_body["found"] is False
    assert query_body["result_hex"] is None


def test_npz_without_metadata_mixed_invalid_stack_preserves_valid_rows(tmp_path):
    """Invalid legacy NPZ rows must not disable other valid stack recipes."""
    rgb_data = np.array([[12, 34, 56], [90, 80, 70]], dtype=np.uint8)
    stack_lut = np.array([[0, 1, 2, 3, 4], [0, 1, 2, 3, 99]], dtype=np.int64)
    lut_path = tmp_path / "legacy-mixed-invalid-stack.npz"
    np.savez(lut_path, rgb=rgb_data, stacks=stack_lut)

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "legacy_mixed_invalid_stack", "target_hex": "#0C2238"},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "legacy_mixed_invalid_stack"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is True
    assert match_body["row_index"] == 0
    assert match_body["matched_hex"] == "#0C2238"
    assert match_body["selected_indices"] == [0, 1, 2, 3, 4]
    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == [[0, 1, 2, 3, 4]]


def test_bool_stack_values_are_not_valid_recipe_indices():
    """Boolean stack values must not be accepted as numeric recipe indices."""
    rgb_data = np.array([[12, 34, 56]], dtype=np.uint8)
    stack_lut = np.array([[True, False, True, False, True]], dtype=object)
    engine = ColorQueryEngine(stack_lut=stack_lut, lut_rgb=rgb_data, color_count=5)

    assert engine.get_combinations() == []

    with patch("api.routers.five_color._load_engine", return_value=(engine, "bool_stack_lut")):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "bool_stack_lut", "target_hex": "#0C2238"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 0
    assert body["matched_hex"] == "#0C2238"
    assert body["selected_indices"] == []
    assert body["reason"] == "recipe_unavailable"


@pytest.mark.parametrize(
    "stack_lut",
    [
        np.array([["Unknown", "1", "2", "3", "4"]]),
        np.array([[0.9, 1, 2, 3, 4]], dtype=float),
    ],
)
def test_get_base_colors_filters_invalid_stack_combinations(tmp_path, stack_lut):
    """Invalid stack rows must not escape through the base-colors response model."""
    rgb_data = np.array([[12, 34, 56]], dtype=np.uint8)
    lut_path = tmp_path / "invalid-base-combinations.npz"
    np.savez(lut_path, rgb=rgb_data, stacks=stack_lut)

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "invalid_base_combinations"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["combinations"] == []


def test_query_uses_normalized_numeric_string_stack_rows():
    """Numeric-string stack rows must query the same recipe that target matching returns."""
    rgb_data = np.array([[12, 34, 56]], dtype=np.uint8)
    stack_lut = np.array([["0", "1", "2", "3", "4"]])
    engine = ColorQueryEngine(stack_lut=stack_lut, lut_rgb=rgb_data)

    assert engine.match_color((12, 34, 56)).selected_indices == [0, 1, 2, 3, 4]

    with patch("api.routers.five_color._load_engine", return_value=(engine, "numeric_text_stack_lut")):
        resp = client.post(
            "/api/five-color/query",
            json={"lut_name": "numeric_text_stack_lut", "selected_indices": [0, 1, 2, 3, 4]},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["selected_indices"] == [0, 1, 2, 3, 4]
    assert body["result_hex"] == "#0C2238"


def test_query_rejects_six_indices_for_five_layer_lut_with_422():
    """Five-layer LUTs must keep legacy request-validation semantics."""
    rgb_data = np.array([[12, 34, 56]], dtype=np.uint8)
    stack_lut = np.array([[0, 1, 2, 3, 4]], dtype=np.int64)
    engine = ColorQueryEngine(stack_lut=stack_lut, lut_rgb=rgb_data, color_count=5)

    with patch("api.routers.five_color._load_engine", return_value=(engine, "legacy_five_layer")):
        resp = client.post(
            "/api/five-color/query",
            json={"lut_name": "legacy_five_layer", "selected_indices": [0, 1, 2, 3, 4, 0]},
        )

    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"]["reason"] == "recipe_length_mismatch"
    assert body["detail"]["expected_length"] == 5
    assert body["detail"]["actual_length"] == 6


def test_native_recipe_json_precise_fraction_recipe_is_unavailable_not_500(tmp_path):
    """Native recipe JSON rows must preserve RGB context for invalid numeric strings."""
    payload = {
        "meta": {"color_layers": 5, "layer_height_mm": 0.08},
        "palette": [
            {"color": f"Color {index}", "material": "PLA Basic"}
            for index in range(5)
        ],
        "recipes": [["0", "1.0000000000000001", "2", "3", "4"]],
        "predicted_lab_opencv": [[50.0, 0.0, 0.0]],
    }
    lut_path = tmp_path / "native-precise-fraction-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "native_precise_fraction_recipe", "target_hex": "#0C2238"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 0
    assert body["selected_indices"] == []
    assert body["reason"] == "recipe_unavailable"


def test_native_recipe_json_bool_recipe_member_is_unavailable(tmp_path):
    """Native recipe JSON bool members must not be coerced into material indices."""
    payload = {
        "meta": {"color_layers": 5, "layer_height_mm": 0.08},
        "palette": [
            {"color": f"Color {index}", "material": "PLA Basic"}
            for index in range(5)
        ],
        "recipes": [[True, 1, 2, 3, 4]],
        "predicted_lab_opencv": [[50.0, 0.0, 0.0]],
    }
    lut_path = tmp_path / "native-bool-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "native_bool_recipe", "target_hex": "#0C2238"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 0
    assert body["selected_indices"] == []
    assert body["reason"] == "recipe_unavailable"


def test_native_recipe_json_float_recipe_member_is_unavailable(tmp_path):
    """Native recipe JSON float members must not be accepted as strict integer indices."""
    payload = {
        "meta": {"color_layers": 5, "layer_height_mm": 0.08},
        "palette": [
            {"color": f"Color {index}", "material": "PLA Basic"}
            for index in range(5)
        ],
        "recipes": [[0.0, 1, 2, 3, 4]],
        "predicted_lab_opencv": [[50.0, 0.0, 0.0]],
    }
    lut_path = tmp_path / "native-float-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "native_float_recipe", "target_hex": "#0C2238"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 0
    assert body["selected_indices"] == []
    assert body["reason"] == "recipe_unavailable"


def test_native_recipe_json_malformed_first_row_does_not_500(tmp_path):
    """Native recipe JSON should infer layer count from later valid rows."""
    payload = {
        "meta": {"layer_height_mm": 0.08},
        "palette": [
            {"color": f"Color {index}", "material": "PLA Basic"}
            for index in range(5)
        ],
        "recipes": [123, [0, 1, 2, 3, 4]],
        "predicted_lab_opencv": [[0.0, 0.0, 0.0], [100.0, 0.0, 0.0]],
    }
    lut_path = tmp_path / "native-malformed-first-row-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "native_malformed_first_row_recipe", "target_hex": "#FFFFFF"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["row_index"] == 1
    assert body["selected_indices"] == [0, 1, 2, 3, 4]


def test_native_recipe_json_short_first_row_does_not_disable_valid_five_layer_row(tmp_path):
    """Native recipe JSON should not let a short first row define all row semantics."""
    payload = {
        "meta": {"layer_height_mm": 0.08},
        "palette": [
            {"color": f"Color {index}", "material": "PLA Basic"}
            for index in range(5)
        ],
        "recipes": [[0, 1, 2, 3], [0, 1, 2, 3, 4]],
        "predicted_lab_opencv": [[0.0, 0.0, 0.0], [100.0, 0.0, 0.0]],
    }
    lut_path = tmp_path / "native-short-first-row-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "native_short_first_row_recipe", "target_hex": "#FFFFFF"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["row_index"] == 1
    assert body["selected_indices"] == [0, 1, 2, 3, 4]


def test_native_recipe_json_short_rows_do_not_outvote_valid_five_layer_row(tmp_path):
    """Malformed short rows must not define the native recipe table layer count."""
    payload = {
        "meta": {"layer_height_mm": 0.08},
        "palette": [
            {"color": f"Color {index}", "material": "PLA Basic"}
            for index in range(5)
        ],
        "recipes": [[0, 1, 2, 3], [1, 2, 3, 4], [0, 1, 2, 3, 4]],
        "predicted_lab_opencv": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [100.0, 0.0, 0.0]],
    }
    lut_path = tmp_path / "native-short-rows-outvote-five-row.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "native_short_rows_outvote_five_row", "target_hex": "#FFFFFF"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["row_index"] == 2
    assert body["selected_indices"] == [0, 1, 2, 3, 4]


def test_native_recipe_json_invalid_rows_without_layer_count_are_unavailable_not_500(tmp_path):
    """Native recipe JSON with only invalid rows must still expose match context."""
    payload = {
        "meta": {"layer_height_mm": 0.08},
        "palette": [
            {"color": f"Color {index}", "material": "PLA Basic"}
            for index in range(5)
        ],
        "recipes": [[True, 1, 2, 3, 4], ["0", "1.0000000000000001", "2", "3", "4"]],
        "predicted_lab_opencv": [[50.0, 0.0, 0.0], [100.0, 0.0, 0.0]],
    }
    lut_path = tmp_path / "native-invalid-rows-no-layer-count.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "native_invalid_rows_no_layer_count", "target_hex": "#FFFFFF"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 1
    assert body["selected_indices"] == []
    assert body["reason"] == "recipe_unavailable"


def test_native_recipe_json_non_sequence_rows_without_layer_count_are_unavailable_not_500(tmp_path):
    """Native recipe JSON with no sequence rows must not fail the match-color API."""
    payload = {
        "meta": {"layer_height_mm": 0.08},
        "palette": [
            {"color": f"Color {index}", "material": "PLA Basic"}
            for index in range(5)
        ],
        "recipes": ["bad-row"],
        "predicted_lab_opencv": [[100.0, 0.0, 0.0]],
    }
    lut_path = tmp_path / "native-non-sequence-rows-no-layer-count.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "native_non_sequence_rows_no_layer_count", "target_hex": "#FFFFFF"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 0
    assert body["selected_indices"] == []
    assert body["reason"] == "recipe_unavailable"


def test_keyed_json_unknown_recipe_color_is_not_fabricated_as_base_index(tmp_path):
    """Unknown keyed JSON recipe names must not be coerced into a valid recipe."""
    metadata = LUTMetadata(
        palette=[
            PaletteEntry(color=name, material="PLA Basic")
            for name in ["A", "B", "C", "D", "E"]
        ],
        color_mode="5-Color Extended",
    )
    payload = metadata.to_dict()
    payload["entries"] = [
        {
            "rgb": [12, 34, 56],
            "hex": "#0C2238",
            "recipe": ["A", "B", "Unknown", "D", "E"],
        }
    ]
    lut_path = tmp_path / "unknown-recipe-color.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 0
    assert body["matched_hex"] == "#0C2238"
    assert body["reason"] == "recipe_unavailable"


def test_keyed_json_fractional_recipe_index_is_not_truncated(tmp_path):
    """Fractional numeric recipe members must remain invalid instead of truncating to int."""
    metadata = LUTMetadata(
        palette=[
            PaletteEntry(color=name, material="PLA Basic")
            for name in ["A", "B", "C", "D", "E"]
        ],
        color_mode="5-Color Extended",
    )
    payload = metadata.to_dict()
    payload["entries"] = [
        {
            "rgb": [12, 34, 56],
            "hex": "#0C2238",
            "recipe": [0.9, 1, 2, 3, 4],
        }
    ]
    lut_path = tmp_path / "fractional-recipe-index.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 0
    assert body["matched_hex"] == "#0C2238"
    assert body["reason"] == "recipe_unavailable"


def test_palette_list_json_fractional_recipe_index_is_not_truncated(tmp_path):
    """Palette-list JSON must validate recipe members before native DB loading."""
    payload = {
        "palette": [
            {"color": name, "material": "PLA Basic"}
            for name in ["A", "B", "C", "D", "E"]
        ],
        "entries": [
            {
                "lab": [0, 0, 0],
                "recipe": [0.9, 1, 2, 3, 4],
            }
        ],
        "max_color_layers": 5,
    }
    lut_path = tmp_path / "fractional-palette-list-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#000000"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 0
    assert body["matched_hex"] == "#000000"
    assert body["reason"] == "recipe_unavailable"


def test_palette_list_json_overlong_recipe_does_not_disable_valid_rows(tmp_path):
    """Malformed palette-list rows must not make valid five-layer rows unusable."""
    payload = {
        "palette": [
            {"color": name, "material": "PLA Basic"}
            for name in ["A", "B", "C", "D", "E"]
        ],
        "entries": [
            {
                "lab": [0, 0, 0],
                "recipe": [0, 1, 2, 3, 4],
            },
            {
                "lab": [100, 0, 0],
                "recipe": [0, 1, 2, 3, 4, 0],
            },
        ],
        "max_color_layers": 5,
    }
    lut_path = tmp_path / "overlong-palette-list-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#000000"},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "test_lut"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is True
    assert match_body["selected_indices"] == [0, 1, 2, 3, 4]
    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == [[0, 1, 2, 3, 4]]


def test_keyed_json_overlong_recipe_does_not_disable_valid_rows(tmp_path):
    """A malformed keyed JSON recipe row must not widen the whole stack table."""
    metadata = LUTMetadata(
        palette=[
            PaletteEntry(color=name, material="PLA Basic")
            for name in ["A", "B", "C", "D", "E"]
        ],
        color_mode="5-Color Extended",
    )
    payload = metadata.to_dict()
    payload["entries"] = [
        {
            "rgb": [12, 34, 56],
            "hex": "#0C2238",
            "recipe": [0, 1, 2, 3, 4],
        },
        {
            "rgb": [90, 80, 70],
            "hex": "#5A5046",
            "recipe": [0, 1, 2, 3, 4, 0],
        },
    ]
    lut_path = tmp_path / "overlong-keyed-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )
        query_resp = client.post(
            "/api/five-color/query",
            json={"lut_name": "test_lut", "selected_indices": [0, 1, 2, 3, 4]},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "test_lut"},
        )

    assert match_resp.status_code == 200
    assert match_resp.json()["found"] is True
    assert match_resp.json()["selected_indices"] == [0, 1, 2, 3, 4]
    assert query_resp.status_code == 200
    assert query_resp.json()["found"] is True
    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == [[0, 1, 2, 3, 4]]


def test_mixed_five_and_six_layer_keyed_json_recipes_remain_queryable(tmp_path):
    """Mixed 5C Extended keyed JSON rows must keep both legacy and six-layer recipes."""
    metadata = LUTMetadata(
        palette=[
            PaletteEntry(color="White", material="PLA Basic", hex_color="#FFFFFF"),
            PaletteEntry(color="Cyan", material="PLA Basic", hex_color="#00FFFF"),
            PaletteEntry(color="Magenta", material="PLA Basic", hex_color="#FF00FF"),
            PaletteEntry(color="Yellow", material="PLA Basic", hex_color="#FFFF00"),
            PaletteEntry(color="Black", material="PLA Basic", hex_color="#000000"),
        ],
        color_mode="5-Color Extended",
        max_color_layers=6,
    )
    payload = metadata.to_dict()
    payload["entries"] = [
        {
            "rgb": [1, 2, 3],
            "hex": "#010203",
            "recipe": ["White", "Cyan", "Magenta", "Yellow", "Black"],
        },
        {
            "rgb": [4, 5, 6],
            "hex": "#040506",
            "recipe": ["Black", "Cyan", "Magenta", "Yellow", "White", "Black"],
        },
    ]
    lut_path = tmp_path / "mixed-five-six-keyed-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_generate_recipe_swatch(*, recipes, **kwargs):
        captured["recipes"] = recipes
        return ("E:/tmp/generated_swatch.3mf", None, "ok")

    with (
        patch("api.routers.five_color.LUTManager.get_lut_path", return_value=str(lut_path)),
        patch(
            "core.recipe_swatch.generate_recipe_swatch",
            side_effect=_fake_generate_recipe_swatch,
        ),
    ):
        base_resp = client.get("/api/five-color/base-colors", params={"lut_name": "test_lut"})
        legacy_query_resp = client.post(
            "/api/five-color/query",
            json={"lut_name": "test_lut", "selected_indices": [0, 1, 2, 3, 4]},
        )
        extended_query_resp = client.post(
            "/api/five-color/query",
            json={"lut_name": "test_lut", "selected_indices": [4, 1, 2, 3, 0, 4]},
        )
        legacy_match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#010203"},
        )
        extended_match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#040506"},
        )
        swatch_resp = client.post(
            "/api/five-color/generate-swatch",
            json={
                "lut_name": "test_lut",
                "recipes": [
                    {"selected_indices": [0, 1, 2, 3, 4], "result_hex": "#010203"},
                    {"selected_indices": [4, 1, 2, 3, 0, 4], "result_hex": "#040506"},
                ],
            },
        )

    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == [
        [0, 1, 2, 3, 4],
        [4, 1, 2, 3, 0, 4],
    ]
    assert legacy_query_resp.status_code == 200
    assert legacy_query_resp.json()["found"] is True
    assert legacy_query_resp.json()["result_hex"] == "#010203"
    assert extended_query_resp.status_code == 200
    assert extended_query_resp.json()["found"] is True
    assert extended_query_resp.json()["result_hex"] == "#040506"
    assert legacy_match_resp.status_code == 200
    assert legacy_match_resp.json()["selected_indices"] == [0, 1, 2, 3, 4]
    assert extended_match_resp.status_code == 200
    assert extended_match_resp.json()["selected_indices"] == [4, 1, 2, 3, 0, 4]
    assert swatch_resp.status_code == 200
    assert [item.selected_indices for item in captured["recipes"]] == [
        [0, 1, 2, 3, 4],
        [4, 1, 2, 3, 0, 4],
    ]


def test_six_layer_keyed_json_trailing_air_is_unavailable_not_legacy_padding(tmp_path):
    """An explicit sixth Air layer must not be reinterpreted as a legacy 5-layer row."""
    metadata = LUTMetadata(
        palette=[
            PaletteEntry(color="White", material="PLA Basic", hex_color="#FFFFFF"),
            PaletteEntry(color="Cyan", material="PLA Basic", hex_color="#00FFFF"),
            PaletteEntry(color="Magenta", material="PLA Basic", hex_color="#FF00FF"),
            PaletteEntry(color="Yellow", material="PLA Basic", hex_color="#FFFF00"),
            PaletteEntry(color="Black", material="PLA Basic", hex_color="#000000"),
        ],
        color_mode="5-Color Extended",
        max_color_layers=6,
    )
    payload = metadata.to_dict()
    payload["entries"] = [
        {
            "rgb": [1, 2, 3],
            "hex": "#010203",
            "recipe": ["White", "Cyan", "Magenta", "Yellow", "Black", "Air"],
        }
    ]
    lut_path = tmp_path / "six-layer-trailing-air-keyed-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        base_resp = client.get("/api/five-color/base-colors", params={"lut_name": "test_lut"})
        legacy_query_resp = client.post(
            "/api/five-color/query",
            json={"lut_name": "test_lut", "selected_indices": [0, 1, 2, 3, 4]},
        )
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#010203"},
        )

    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == []
    assert legacy_query_resp.status_code == 422
    assert legacy_query_resp.json()["detail"]["reason"] == "recipe_length_mismatch"
    assert legacy_query_resp.json()["detail"]["expected_length"] == 6
    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is False
    assert match_body["row_index"] == 0
    assert match_body["reason"] == "recipe_unavailable"


def test_keyed_json_non_numeric_recipe_member_keeps_rgb_context(tmp_path):
    """Invalid keyed JSON recipe members must not drop the matching RGB row."""
    metadata = LUTMetadata(
        palette=[
            PaletteEntry(color=name, material="PLA Basic")
            for name in ["A", "B", "C", "D", "E"]
        ],
        color_mode="5-Color Extended",
    )
    payload = metadata.to_dict()
    payload["entries"] = [
        {
            "rgb": [12, 34, 56],
            "hex": "#0C2238",
            "recipe": [0, None, 2, 3, 4],
        }
    ]
    lut_path = tmp_path / "non-numeric-keyed-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "test_lut"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is False
    assert match_body["row_index"] == 0
    assert match_body["matched_hex"] == "#0C2238"
    assert match_body["reason"] == "recipe_unavailable"
    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == []


def test_keyed_json_non_array_recipe_keeps_rgb_context(tmp_path):
    """Non-list keyed JSON recipes must keep the row as recipe-unavailable."""
    metadata = LUTMetadata(
        palette=[
            PaletteEntry(color=name, material="PLA Basic")
            for name in ["A", "B", "C", "D", "E"]
        ],
        color_mode="5-Color Extended",
    )
    payload = metadata.to_dict()
    payload["entries"] = [
        {
            "rgb": [12, 34, 56],
            "hex": "#0C2238",
            "recipe": {"bad": True},
        }
    ]
    lut_path = tmp_path / "non-array-keyed-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )

    assert match_resp.status_code == 200
    body = match_resp.json()
    assert body["found"] is False
    assert body["row_index"] == 0
    assert body["matched_hex"] == "#0C2238"
    assert body["reason"] == "recipe_unavailable"


def test_flat_list_json_non_numeric_recipe_member_keeps_rgb_context(tmp_path):
    """Invalid legacy flat-list recipe members must not bubble into a 500."""
    payload = [
        {
            "rgb": [12, 34, 56],
            "recipe": [{"bad": True}, 1, 2, 3, 4],
        }
    ]
    lut_path = tmp_path / "non-numeric-flat-list-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "test_lut"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is False
    assert match_body["row_index"] == 0
    assert match_body["matched_hex"] == "#0C2238"
    assert match_body["reason"] == "recipe_unavailable"
    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == []


def test_flat_list_json_overlong_recipe_member_keeps_rgb_context(tmp_path):
    """Malformed legacy flat-list recipe arity must not bubble into a 500."""
    payload = [
        {
            "rgb": [12, 34, 56],
            "recipe": [0, 1, 2, 3, 4],
        },
        {
            "rgb": [90, 80, 70],
            "recipe": [0, 1, 2, 3, 4, 0],
        },
    ]
    lut_path = tmp_path / "overlong-flat-list-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#5A5046"},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "test_lut"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is False
    assert match_body["row_index"] == 1
    assert match_body["matched_hex"] == "#5A5046"
    assert match_body["reason"] == "recipe_unavailable"
    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == [[0, 1, 2, 3, 4]]


def test_flat_list_json_non_integer_numeric_string_is_not_a_color_name(tmp_path):
    """Fractional numeric strings in flat-list recipes must not fabricate palette names."""
    payload = [
        {
            "rgb": [12, 34, 56],
            "recipe": ["0", "1.5", "0", "0", "0"],
        }
    ]
    lut_path = tmp_path / "fractional-string-flat-list-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "test_lut"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is False
    assert match_body["row_index"] == 0
    assert match_body["matched_hex"] == "#0C2238"
    assert match_body["reason"] == "recipe_unavailable"
    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == []


def test_flat_list_json_precise_fraction_string_is_not_rounded(tmp_path):
    """High-precision fractional strings must not be rounded into recipe indices."""
    payload = [
        {
            "rgb": [12, 34, 56],
            "recipe": ["0", "1.0000000000000001", "2", "3", "4"],
        }
    ]
    lut_path = tmp_path / "precise-fraction-string-flat-list-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "test_lut"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is False
    assert match_body["row_index"] == 0
    assert match_body["matched_hex"] == "#0C2238"
    assert match_body["reason"] == "recipe_unavailable"
    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == []


def test_flat_list_json_huge_recipe_index_keeps_rgb_context(tmp_path):
    """Huge integer recipe members must not overflow during stack array creation."""
    payload = [
        {
            "rgb": [12, 34, 56],
            "recipe": [0, 1, 2, 3, 2147483648],
        }
    ]
    lut_path = tmp_path / "huge-index-flat-list-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is False
    assert match_body["row_index"] == 0
    assert match_body["matched_hex"] == "#0C2238"
    assert match_body["reason"] == "recipe_unavailable"


def test_flat_list_json_overlong_numeric_string_keeps_rgb_context(tmp_path):
    """Overlong numeric strings must not escape flat-list loading as 500 errors."""
    payload = [
        {
            "rgb": [12, 34, 56],
            "recipe": ["0", "1", "2", "3", "1" * 5000],
        }
    ]
    lut_path = tmp_path / "overlong-numeric-string-flat-list-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "test_lut"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is False
    assert match_body["row_index"] == 0
    assert match_body["matched_hex"] == "#0C2238"
    assert match_body["reason"] == "recipe_unavailable"
    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == []


def test_flat_list_json_string_recipe_is_not_iterated_as_color_names(tmp_path):
    """A string flat-list recipe payload must not be split into a fake palette."""
    payload = [
        {
            "rgb": [12, 34, 56],
            "recipe": "abcde",
        }
    ]
    lut_path = tmp_path / "string-flat-list-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "test_lut"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is False
    assert match_body["row_index"] == 0
    assert match_body["matched_hex"] == "#0C2238"
    assert match_body["reason"] == "recipe_unavailable"
    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == []


def test_flat_list_json_numeric_recipe_payload_keeps_rgb_context(tmp_path):
    """A non-iterable flat-list recipe payload must not bubble into a 500."""
    payload = [
        {
            "rgb": [12, 34, 56],
            "recipe": 123,
        }
    ]
    lut_path = tmp_path / "numeric-flat-list-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is False
    assert match_body["row_index"] == 0
    assert match_body["matched_hex"] == "#0C2238"
    assert match_body["reason"] == "recipe_unavailable"


def test_flat_list_json_numeric_string_recipe_uses_numeric_indices(tmp_path):
    """Numeric-string legacy JSON recipe members must keep numeric stack semantics."""
    payload = [
        {
            "rgb": [12, 34, 56],
            "recipe": ["4", "3", "2", "1", "0"],
        }
    ]
    lut_path = tmp_path / "numeric-string-flat-list-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )
        query_resp = client.post(
            "/api/five-color/query",
            json={"lut_name": "test_lut", "selected_indices": [4, 3, 2, 1, 0]},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "test_lut"},
        )

    assert match_resp.status_code == 200
    assert match_resp.json()["selected_indices"] == [4, 3, 2, 1, 0]
    assert query_resp.status_code == 200
    query_body = query_resp.json()
    assert query_body["found"] is True
    assert query_body["result_hex"] == "#0C2238"
    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == [[4, 3, 2, 1, 0]]


def test_flat_list_json_zero_numeric_string_recipe_uses_numeric_indices(tmp_path):
    """All-zero numeric-string recipes are valid repeated single-color stacks."""
    payload = [
        {
            "rgb": [12, 34, 56],
            "recipe": ["0", "0", "0", "0", "0"],
        }
    ]
    lut_path = tmp_path / "zero-numeric-string-flat-list-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )
        query_resp = client.post(
            "/api/five-color/query",
            json={"lut_name": "test_lut", "selected_indices": [0, 0, 0, 0, 0]},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "test_lut"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is True
    assert match_body["selected_indices"] == [0, 0, 0, 0, 0]
    assert query_resp.status_code == 200
    query_body = query_resp.json()
    assert query_body["found"] is True
    assert query_body["result_hex"] == "#0C2238"
    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == [[0, 0, 0, 0, 0]]


def test_flat_list_json_outlier_recipe_does_not_disable_valid_numeric_row(tmp_path):
    """Outlier flat-list recipe rows must not disable valid five-layer recipes."""
    payload = [
        {
            "rgb": [12, 34, 56],
            "recipe": ["4", "3", "2", "1", "0"],
        },
        {
            "rgb": [90, 80, 70],
            "recipe": ["99", "0", "0", "0", "0"],
        },
    ]
    lut_path = tmp_path / "outlier-flat-list-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )
        query_resp = client.post(
            "/api/five-color/query",
            json={"lut_name": "test_lut", "selected_indices": [4, 3, 2, 1, 0]},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "test_lut"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is True
    assert match_body["selected_indices"] == [4, 3, 2, 1, 0]
    assert query_resp.status_code == 200
    assert query_resp.json()["found"] is True
    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == [[4, 3, 2, 1, 0]]


def test_flat_list_json_name_recipe_does_not_disable_valid_numeric_row(tmp_path):
    """Name-based flat-list rows must not shrink numeric-index row semantics."""
    payload = [
        {
            "rgb": [12, 34, 56],
            "recipe": ["4", "3", "2", "1", "0"],
        },
        {
            "rgb": [90, 80, 70],
            "recipe": ["Bogus", "0", "0", "0", "0"],
        },
    ]
    lut_path = tmp_path / "name-and-numeric-flat-list-recipe.json"
    lut_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=str(lut_path),
    ):
        match_resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )
        query_resp = client.post(
            "/api/five-color/query",
            json={"lut_name": "test_lut", "selected_indices": [4, 3, 2, 1, 0]},
        )
        base_resp = client.get(
            "/api/five-color/base-colors",
            params={"lut_name": "test_lut"},
        )

    assert match_resp.status_code == 200
    match_body = match_resp.json()
    assert match_body["found"] is True
    assert match_body["selected_indices"] == [4, 3, 2, 1, 0]
    assert query_resp.status_code == 200
    assert query_resp.json()["found"] is True
    assert base_resp.status_code == 200
    assert base_resp.json()["combinations"] == [[4, 3, 2, 1, 0]]


def test_get_base_colors_npy():
    """NPY file loading returns correct base colors."""
    rgb_data = np.array(
        [[200, 50, 50], [50, 200, 50], [50, 50, 200], [240, 240, 240]] * 256,
        dtype=np.uint8,
    )  # 1024 rows → detected as 4-color

    with (
        patch(
            "api.routers.five_color.LUTManager.get_lut_path",
            return_value="/fake/path/test.npy",
        ),
        patch(
            "api.routers.five_color.StackLUTLoader.load_lut_rgb",
            return_value=(True, "ok", rgb_data),
        ),
        patch(
            "api.routers.five_color.ColorCountDetector.detect_color_count",
            return_value=(4, 1024),
        ),
        patch(
            "api.routers.five_color.StackFileManager.find_stack_file",
            return_value=None,
        ),
    ):
        resp = client.get("/api/five-color/base-colors", params={"lut_name": "test_lut"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["color_count"] == 4
    assert len(body["colors"]) == 4


def test_get_base_colors_not_found():
    """Non-existent LUT returns 404."""
    with patch(
        "api.routers.five_color.LUTManager.get_lut_path",
        return_value=None,
    ):
        resp = client.get("/api/five-color/base-colors", params={"lut_name": "nonexistent"})

    assert resp.status_code == 404
    assert "LUT not found" in resp.json()["detail"]


def test_get_base_colors_lut_load_failure_uses_public_error_language():
    """Loader failure messages must not leak local paths to API clients."""
    private_path = "/Users/min/private/broken.npy"

    with (
        patch(
            "api.routers.five_color.LUTManager.get_lut_path",
            return_value=private_path,
        ),
        patch(
            "api.routers.five_color.StackLUTLoader.load_lut_rgb",
            return_value=(False, f"cannot open {private_path}: bad header", None),
        ),
    ):
        resp = client.get("/api/five-color/base-colors", params={"lut_name": "broken"})

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail == (
        "Unable to load the selected LUT. Check that the file exists and uses a "
        "supported LUT format."
    )
    assert private_path not in detail
    assert "bad header" not in detail


def test_get_base_colors_lut_loader_exception_uses_public_error_language():
    """Unexpected LUT reader exceptions must use the same client-safe detail."""
    private_path = "/Users/min/private/broken.json"

    with (
        patch(
            "api.routers.five_color.LUTManager.get_lut_path",
            return_value=private_path,
        ),
        patch(
            "api.routers.five_color.LUTManager.load_lut_with_metadata",
            side_effect=ValueError(f"cannot parse {private_path}: line 1"),
        ),
    ):
        resp = client.get("/api/five-color/base-colors", params={"lut_name": "broken"})

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail == (
        "Unable to load the selected LUT. Check that the file exists and uses a "
        "supported LUT format."
    )
    assert private_path not in detail
    assert "line 1" not in detail


# ---------------------------------------------------------------------------
# POST /api/five-color/query
# ---------------------------------------------------------------------------

def test_query_success():
    """Successful query returns correct RGB and hex."""
    stack_lut, rgb_data = _make_npz_data()

    with (
        patch(
            "api.routers.five_color.LUTManager.get_lut_path",
            return_value="/fake/path/test.npz",
        ),
        patch(
            "api.routers.five_color.StackLUTLoader.load_npz_file",
            return_value=(True, "ok", stack_lut, rgb_data),
        ),
    ):
        resp = client.post(
            "/api/five-color/query",
            json={"lut_name": "test_lut", "selected_indices": [0, 1, 2, 3, 4]},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["result_rgb"] == [255, 128, 64]
    assert body["result_hex"] == "#FF8040"


def test_query_no_match():
    """Query with non-matching indices returns found=false."""
    stack_lut, rgb_data = _make_npz_data()

    with (
        patch(
            "api.routers.five_color.LUTManager.get_lut_path",
            return_value="/fake/path/test.npz",
        ),
        patch(
            "api.routers.five_color.StackLUTLoader.load_npz_file",
            return_value=(True, "ok", stack_lut, rgb_data),
        ),
    ):
        resp = client.post(
            "/api/five-color/query",
            json={"lut_name": "test_lut", "selected_indices": [4, 4, 4, 4, 4]},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False


# ---------------------------------------------------------------------------
# POST /api/five-color/match-color
# ---------------------------------------------------------------------------

def test_match_color_returns_nearest_recipe_coordinate_and_neighborhood():
    """Hex lookup returns the nearest LUT row, its recipe, coordinate, and cells."""
    stack_lut = np.array(
        [[0, 0, 0, 0, 0], [0, 1, 2, 3, 4], [1, 1, 1, 1, 1]],
        dtype=np.int64,
    )
    rgb_data = np.array(
        [[255, 255, 255], [240, 10, 0], [0, 0, 0]],
        dtype=np.uint8,
    )
    engine = ColorQueryEngine(stack_lut=stack_lut, lut_rgb=rgb_data, color_count=5)

    with patch("api.routers.five_color._load_engine", return_value=(engine, "test_lut")):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#F20A00", "neighborhood_radius": 1},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["target_hex"] == "#F20A00"
    assert body["matched_hex"] == "#F00A00"
    assert body["selected_indices"] == [0, 1, 2, 3, 4]
    assert body["result_hex"] == "#F00A00"
    assert body["row_index"] == 1
    coordinate = body["coordinate"]
    assert {key: coordinate[key] for key in (
        "card_index",
        "card_label",
        "grid_size",
        "row",
        "col",
        "display_row",
        "display_col",
    )} == {
        "card_index": 0,
        "card_label": "1",
        "grid_size": 2,
        "row": 0,
        "col": 1,
        "display_row": 1,
        "display_col": 2,
    }
    assert coordinate["page_index"] == 0
    assert coordinate["page_label"] == "1"
    assert coordinate["data_rows"] == 2
    assert coordinate["data_cols"] == 2
    assert coordinate["data_row"] == 0
    assert coordinate["data_col"] == 1
    assert coordinate["physical_row"] == 0
    assert coordinate["physical_col"] == 1
    assert coordinate["row_index"] == 1
    assert len(body["neighborhood"]) == 3
    assert [len(row) for row in body["neighborhood"]] == [3, 3, 3]
    center = body["neighborhood"][1][1]
    assert center["is_match"] is True
    assert center["row_index"] == 1
    assert center["hex"] == "#F00A00"
    assert body["neighborhood"][0][0]["row_index"] is None
    tail_empty = body["neighborhood"][2][1]
    assert tail_empty["card_index"] is None
    assert tail_empty["card_label"] is None
    assert tail_empty["grid_size"] is None
    assert tail_empty["row"] is None
    assert tail_empty["col"] is None
    assert tail_empty["display_row"] is None
    assert tail_empty["display_col"] is None
    assert tail_empty["page_index"] is None
    assert tail_empty["page_label"] is None
    assert tail_empty["data_rows"] is None
    assert tail_empty["data_cols"] is None
    assert tail_empty["data_row"] is None
    assert tail_empty["data_col"] is None
    assert tail_empty["physical_row"] is None
    assert tail_empty["physical_col"] is None
    assert tail_empty["row_index"] is None


def test_match_color_preserves_six_layer_extended_stack_recipe():
    """5C Extended stack rows keep their sixth layer instead of being dropped."""
    stack_lut = np.array([[4, 1, 2, 3, 0, 4]], dtype=np.int64)
    rgb_data = np.array([[10, 20, 30]], dtype=np.uint8)
    engine = ColorQueryEngine(stack_lut=stack_lut, lut_rgb=rgb_data, color_count=5)

    with patch("api.routers.five_color._load_engine", return_value=(engine, "extended_lut")):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "extended_lut", "target_hex": "#0A141E"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["matched_hex"] == "#0A141E"
    assert body["selected_indices"] == [4, 1, 2, 3, 0, 4]


def test_match_color_reports_second_2738_card_coordinates():
    """A 2738-row LUT is displayed as two 37x37 cards matching legacy layout."""
    stack_lut = np.tile(np.array([[0, 1, 2, 3, 4]], dtype=np.int64), (2738, 1))
    rgb_data = np.zeros((2738, 3), dtype=np.uint8)
    rgb_data[1369] = np.array([10, 20, 30], dtype=np.uint8)
    engine = ColorQueryEngine(stack_lut=stack_lut, lut_rgb=rgb_data, color_count=5)

    with patch("api.routers.five_color._load_engine", return_value=(engine, "test_lut")):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0A141E"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["row_index"] == 1369
    assert body["coordinate"]["card_index"] == 1
    assert body["coordinate"]["card_label"] == "B"
    assert body["coordinate"]["grid_size"] == 37
    assert body["coordinate"]["page_index"] == 1
    assert body["coordinate"]["page_label"] == "B"
    assert body["coordinate"]["data_rows"] == 37
    assert body["coordinate"]["data_cols"] == 37
    assert body["coordinate"]["data_row"] == 0
    assert body["coordinate"]["data_col"] == 0
    assert body["coordinate"]["physical_row"] == 1
    assert body["coordinate"]["physical_col"] == 1
    assert body["coordinate"]["display_row"] == 1
    assert body["coordinate"]["display_col"] == 1


def test_match_color_rejects_invalid_hex():
    """Invalid target hex values fail schema validation before matching."""
    with patch("api.routers.five_color._load_engine") as load_engine:
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "not-a-hex"},
        )

    assert resp.status_code == 422
    load_engine.assert_not_called()


def test_match_color_reports_missing_layer_recipe():
    """If the matched row cannot map to a layer recipe, the response explains it."""
    rgb_data = np.zeros((40, 3), dtype=np.uint8)
    rgb_data[33] = np.array([220, 10, 30], dtype=np.uint8)
    engine = ColorQueryEngine(stack_lut=None, lut_rgb=rgb_data, color_count=2)

    with patch("api.routers.five_color._load_engine", return_value=(engine, "test_lut")):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#DC0A1E"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 33
    assert body["matched_hex"] == "#DC0A1E"
    assert body["selected_indices"] == []
    assert body["reason"] == "recipe_unavailable"
    assert "recipe" in body["message"]


def test_match_color_reports_invalid_stack_recipe_as_unavailable():
    """Stack rows containing air or out-of-range material ids are not valid five-layer recipes."""
    rgb_data = np.array([[10, 20, 30]], dtype=np.uint8)
    stack_lut = np.array([[0, 1, 2, 3, -1]], dtype=np.int64)
    engine = ColorQueryEngine(stack_lut=stack_lut, lut_rgb=rgb_data, color_count=5)

    with patch("api.routers.five_color._load_engine", return_value=(engine, "invalid_stack_lut")):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "invalid_stack_lut", "target_hex": "#0A141E"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 0
    assert body["matched_hex"] == "#0A141E"
    assert body["selected_indices"] == []
    assert body["reason"] == "recipe_unavailable"


def test_match_color_reports_fractional_stack_recipe_as_unavailable():
    """Non-integer stack row values must not be truncated into valid material ids."""
    rgb_data = np.array([[12, 34, 56]], dtype=np.uint8)
    stack_lut = np.array([[0.9, 1, 2, 3, 4]], dtype=float)
    engine = ColorQueryEngine(stack_lut=stack_lut, lut_rgb=rgb_data, color_count=5)

    with patch("api.routers.five_color._load_engine", return_value=(engine, "fractional_stack_lut")):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "fractional_stack_lut", "target_hex": "#0C2238"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 0
    assert body["matched_hex"] == "#0C2238"
    assert body["selected_indices"] == []
    assert body["reason"] == "recipe_unavailable"


def test_match_color_reports_non_numeric_stack_recipe_as_unavailable():
    """Non-numeric stack row values must not escape as API failures."""
    rgb_data = np.array([[12, 34, 56]], dtype=np.uint8)
    stack_lut = np.array([["Unknown", "1", "2", "3", "4"]], dtype=object)
    engine = ColorQueryEngine(stack_lut=stack_lut, lut_rgb=rgb_data, color_count=5)

    with patch("api.routers.five_color._load_engine", return_value=(engine, "text_stack_lut")):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "text_stack_lut", "target_hex": "#0C2238"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 0
    assert body["matched_hex"] == "#0C2238"
    assert body["selected_indices"] == []
    assert body["reason"] == "recipe_unavailable"


def test_match_color_rejects_stackless_2468_extended_rows_as_five_layer_recipe():
    """2468-row extended LUTs without stacks must not fabricate five-layer recipes."""
    rgb_data = np.zeros((2468, 3), dtype=np.uint8)
    rgb_data[1500] = np.array([163, 109, 72], dtype=np.uint8)
    engine = ColorQueryEngine(stack_lut=None, lut_rgb=rgb_data, color_count=5)

    with patch("api.routers.five_color._load_engine", return_value=(engine, "extended_lut")):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "extended_lut", "target_hex": "#A36D48"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 1500
    assert body["matched_hex"] == "#A36D48"
    assert body["selected_indices"] == []
    assert body["reason"] == "recipe_unavailable"


def test_match_color_derives_recipe_for_stackless_full_five_color_cartesian_lut():
    """A full 5^5 stackless LUT can reliably decode recipe digits from row index."""
    rgb_data = np.zeros((3125, 3), dtype=np.uint8)
    rgb_data[100] = np.array([10, 20, 30], dtype=np.uint8)
    engine = ColorQueryEngine(stack_lut=None, lut_rgb=rgb_data)

    with patch("api.routers.five_color._load_engine", return_value=(engine, "full_5color_lut")):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "full_5color_lut", "target_hex": "#0A141E"},
        )

    assert engine.color_count == 5
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["row_index"] == 100
    assert body["selected_indices"] == [0, 0, 4, 0, 0]
    assert body["matched_hex"] == "#0A141E"


def test_match_color_rejects_partial_stackless_lut_rows_as_five_layer_recipe():
    """Partial stackless LUTs have no reliable row-to-recipe semantics."""
    rgb_data = np.zeros((40, 3), dtype=np.uint8)
    rgb_data[33] = np.array([12, 34, 56], dtype=np.uint8)
    engine = ColorQueryEngine(stack_lut=None, lut_rgb=rgb_data, color_count=3)

    with patch("api.routers.five_color._load_engine", return_value=(engine, "partial_lut")):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "partial_lut", "target_hex": "#0C2238"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["row_index"] == 33
    assert body["matched_hex"] == "#0C2238"
    assert body["selected_indices"] == []
    assert body["reason"] == "recipe_unavailable"


def test_match_color_derives_recipe_without_stack_lut():
    """Dynamic LUT matching derives five-layer recipe digits from the matched row."""
    rgb_data = np.zeros((243, 3), dtype=np.uint8)
    rgb_data[33] = np.array([12, 34, 56], dtype=np.uint8)
    engine = ColorQueryEngine(stack_lut=None, lut_rgb=rgb_data, color_count=3)

    with patch("api.routers.five_color._load_engine", return_value=(engine, "test_lut")):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["row_index"] == 33
    assert body["selected_indices"] == [0, 1, 0, 2, 0]
    assert body["matched_hex"] == "#0C2238"
    assert len(body["neighborhood"]) == 5
    assert [len(row) for row in body["neighborhood"]] == [5, 5, 5, 5, 5]


def test_match_color_derives_recipe_when_stack_lut_has_no_recipe_columns():
    """Empty-column stack data is treated as unavailable and falls back to row digits."""
    rgb_data = np.zeros((243, 3), dtype=np.uint8)
    rgb_data[33] = np.array([12, 34, 56], dtype=np.uint8)
    stack_lut = np.zeros((243, 0), dtype=np.int64)
    engine = ColorQueryEngine(stack_lut=stack_lut, lut_rgb=rgb_data, color_count=3)

    with patch("api.routers.five_color._load_engine", return_value=(engine, "test_lut")):
        resp = client.post(
            "/api/five-color/match-color",
            json={"lut_name": "test_lut", "target_hex": "#0C2238"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["row_index"] == 33
    assert body["selected_indices"] == [0, 1, 0, 2, 0]
    assert body["matched_hex"] == "#0C2238"


# ---------------------------------------------------------------------------
# POST /api/five-color/generate-swatch
# ---------------------------------------------------------------------------

def test_generate_swatch_uses_canonical_lut_metadata_instead_of_client_payload():
    """Swatch generation must derive base color metadata and result hex from the LUT."""
    engine = _FakeSwatchEngine()
    captured: dict[str, object] = {}

    def _fake_generate_recipe_swatch(*, recipes, **kwargs):
        captured["recipes"] = recipes
        captured["kwargs"] = kwargs
        return ("E:/tmp/generated_swatch.3mf", None, "ok")

    with (
        patch("api.routers.five_color._load_engine", return_value=(engine, "test_lut")),
        patch(
            "core.recipe_swatch.generate_recipe_swatch",
            side_effect=_fake_generate_recipe_swatch,
        ),
    ):
        resp = client.post(
            "/api/five-color/generate-swatch",
            json={
                "lut_name": "test_lut",
                "recipes": [
                    {
                        "selected_indices": [0, 1, 2, 3, 4],
                        "result_hex": "#123456",
                        "base_color_names": ["tampered"] * 6,
                        "base_color_hexes": ["#000000"] * 6,
                    }
                ],
                "printer_id": "bambu-p1s",
                "slicer": "OrcaSlicer",
                "nozzle_size": "0.2",
                "device_profile_id": "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
            },
        )

    assert resp.status_code == 200
    swatch_item = captured["recipes"][0]
    assert swatch_item.selected_indices == [0, 1, 2, 3, 4]
    assert swatch_item.result_hex == "#010203"
    assert swatch_item.base_color_names == ["Red", "Green", "Blue", "Yellow", "Magenta", "Cyan"]
    assert swatch_item.base_color_hexes == [
        "#FF0000",
        "#00FF00",
        "#0000FF",
        "#FFFF00",
        "#FF00FF",
        "#00FFFF",
    ]
    assert captured["kwargs"]["printer_id"] == "bambu-p1s"
    assert captured["kwargs"]["slicer"] == "OrcaSlicer"
    assert captured["kwargs"]["nozzle_size"] == "0.2"
    assert captured["kwargs"]["device_profile_id"] == "OrcaSlicer:bbl:bambu-lab-p1s:0.2"


def test_generate_swatch_preserves_six_layer_extended_recipe():
    """Swatch generation passes 5C Extended six-layer recipes through intact."""
    engine = _FakeSwatchEngine(expected_selection_length=6)
    captured: dict[str, object] = {}

    def _fake_generate_recipe_swatch(*, recipes, **kwargs):
        captured["recipes"] = recipes
        captured["kwargs"] = kwargs
        return ("E:/tmp/generated_swatch.3mf", None, "ok")

    with (
        patch("api.routers.five_color._load_engine", return_value=(engine, "extended_lut")),
        patch(
            "core.recipe_swatch.generate_recipe_swatch",
            side_effect=_fake_generate_recipe_swatch,
        ),
    ):
        resp = client.post(
            "/api/five-color/generate-swatch",
            json={
                "lut_name": "extended_lut",
                "recipes": [
                    {
                        "selected_indices": [4, 1, 2, 3, 0, 4],
                        "result_hex": "#123456",
                        "base_color_names": ["tampered"] * 6,
                        "base_color_hexes": ["#000000"] * 6,
                    }
                ],
            },
        )

    assert resp.status_code == 200
    swatch_item = captured["recipes"][0]
    assert swatch_item.selected_indices == [4, 1, 2, 3, 0, 4]
    assert swatch_item.result_hex == "#040506"


def test_generate_swatch_rejects_six_indices_for_five_layer_lut_with_422():
    """Five-layer swatch requests must reject six indices before query/generation."""
    engine = _FakeSwatchEngine()

    with (
        patch("api.routers.five_color._load_engine", return_value=(engine, "legacy_five_layer")),
        patch("core.recipe_swatch.generate_recipe_swatch") as generate_mock,
    ):
        resp = client.post(
            "/api/five-color/generate-swatch",
            json={
                "lut_name": "legacy_five_layer",
                "recipes": [
                    {
                        "selected_indices": [0, 1, 2, 3, 4, 0],
                        "result_hex": "#123456",
                    }
                ],
            },
        )

    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"]["reason"] == "recipe_length_mismatch"
    assert body["detail"]["expected_length"] == 5
    assert body["detail"]["actual_length"] == 6
    generate_mock.assert_not_called()


def test_recipe_swatch_uses_six_layer_height_for_extended_recipe():
    """A six-layer recipe must lift the backing above the sixth optical layer."""
    from core.recipe_swatch import RecipeSwatchItem, generate_recipe_swatch

    captured: dict[str, object] = {}
    recipe = RecipeSwatchItem(
        selected_indices=[4, 1, 2, 3, 0, 4],
        result_hex="#040506",
        base_color_names=["White", "Cyan", "Magenta", "Yellow", "Black"],
        base_color_hexes=["#FFFFFF", "#00FFFF", "#FF00FF", "#FFFF00", "#000000"],
    )

    def _capture_export(**kwargs):
        captured.update(kwargs)

    with patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata", side_effect=_capture_export):
        output_path, legend_img, status_msg = generate_recipe_swatch([recipe], structure_mode="Single-sided")

    assert output_path is not None
    assert legend_img is not None
    assert status_msg == "Generated 1 recipe swatch(es)"
    assert "Black" in captured["slot_names"]
    assert captured["scene"].bounds[1][2] == pytest.approx(1.68)


def test_generate_swatch_rejects_selected_indices_out_of_range():
    """Swatch generation should reject recipe indices outside the LUT range."""
    engine = _FakeSwatchEngine()

    with (
        patch("api.routers.five_color._load_engine", return_value=(engine, "test_lut")),
        patch("core.recipe_swatch.generate_recipe_swatch") as generate_mock,
    ):
        resp = client.post(
            "/api/five-color/generate-swatch",
            json={
                "lut_name": "test_lut",
                "recipes": [
                    {
                        "selected_indices": [0, 1, 2, 3, 6],
                        "result_hex": "#123456",
                        "base_color_names": ["ignored"] * 6,
                        "base_color_hexes": ["#000000"] * 6,
                    }
                ],
            },
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Index 6 out of range [0, 6)"
    generate_mock.assert_not_called()


def test_generate_swatch_rejects_recipe_without_matching_lut_result():
    """Swatch generation should reject recipes not found in the LUT."""
    engine = _FakeSwatchEngine()

    with (
        patch("api.routers.five_color._load_engine", return_value=(engine, "test_lut")),
        patch("core.recipe_swatch.generate_recipe_swatch") as generate_mock,
    ):
        resp = client.post(
            "/api/five-color/generate-swatch",
            json={
                "lut_name": "test_lut",
                "recipes": [
                    {
                        "selected_indices": [4, 4, 4, 4, 4],
                        "result_hex": "#ABCDEF",
                        "base_color_names": ["ignored"] * 6,
                        "base_color_hexes": ["#000000"] * 6,
                    }
                ],
            },
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "No LUT match for selected indices: [4, 4, 4, 4, 4]"
    generate_mock.assert_not_called()


def test_generate_swatch_uses_request_scoped_registry_session_id():
    """Swatch output registrations must be isolated per request lifecycle."""
    engine = _FakeSwatchEngine()
    fake_registry = _FakeRegistry()

    def _fake_generate_recipe_swatch(*, recipes, **kwargs):
        return (
            "E:/tmp/generated_swatch.3mf",
            Image.new("RGB", (1, 1), (255, 255, 255)),
            "ok",
        )

    client.app.dependency_overrides[get_file_registry] = lambda: fake_registry
    try:
        with (
            patch("api.routers.five_color._load_engine", return_value=(engine, "test_lut")),
            patch(
                "core.recipe_swatch.generate_recipe_swatch",
                side_effect=_fake_generate_recipe_swatch,
            ),
            patch("api.file_bridge.pil_to_png_bytes", return_value=b"png-bytes"),
        ):
            request_body = {
                "lut_name": "test_lut",
                "recipes": [
                    {
                        "selected_indices": [0, 1, 2, 3, 4],
                        "result_hex": "#123456",
                        "base_color_names": ["ignored"] * 6,
                        "base_color_hexes": ["#000000"] * 6,
                    }
                ],
            }
            resp_one = client.post(
                "/api/five-color/generate-swatch",
                headers={"X-Request-ID": "req-one"},
                json=request_body,
            )
            resp_two = client.post(
                "/api/five-color/generate-swatch",
                headers={"X-Request-ID": "req-two"},
                json=request_body,
            )
    finally:
        client.app.dependency_overrides.clear()

    assert resp_one.status_code == 200
    assert resp_two.status_code == 200
    path_session_ids = [call["session_id"] for call in fake_registry.path_calls]
    bytes_session_ids = [call["session_id"] for call in fake_registry.bytes_calls]
    assert len(set(path_session_ids)) == 2
    assert len(set(bytes_session_ids)) == 2
    assert path_session_ids[0].startswith("recipe-swatch:req-one:")
    assert path_session_ids[1].startswith("recipe-swatch:req-two:")
    assert bytes_session_ids[0].startswith("recipe-swatch:req-one:")
    assert bytes_session_ids[1].startswith("recipe-swatch:req-two:")


def test_generate_swatch_registry_session_id_is_unique_even_with_same_request_id():
    """Swatch registry session ids must not collide when the same request header is reused."""
    engine = _FakeSwatchEngine()
    fake_registry = _FakeRegistry()

    def _fake_generate_recipe_swatch(*, recipes, **kwargs):
        return (
            "E:/tmp/generated_swatch.3mf",
            Image.new("RGB", (1, 1), (255, 255, 255)),
            "ok",
        )

    client.app.dependency_overrides[get_file_registry] = lambda: fake_registry
    try:
        with (
            patch("api.routers.five_color._load_engine", return_value=(engine, "test_lut")),
            patch(
                "core.recipe_swatch.generate_recipe_swatch",
                side_effect=_fake_generate_recipe_swatch,
            ),
            patch("api.file_bridge.pil_to_png_bytes", return_value=b"png-bytes"),
        ):
            request_body = {
                "lut_name": "test_lut",
                "recipes": [
                    {
                        "selected_indices": [0, 1, 2, 3, 4],
                        "result_hex": "#123456",
                        "base_color_names": ["ignored"] * 6,
                        "base_color_hexes": ["#000000"] * 6,
                    }
                ],
            }
            resp_one = client.post(
                "/api/five-color/generate-swatch",
                headers={"X-Request-ID": "req-repeat"},
                json=request_body,
            )
            resp_two = client.post(
                "/api/five-color/generate-swatch",
                headers={"X-Request-ID": "req-repeat"},
                json=request_body,
            )
    finally:
        client.app.dependency_overrides.clear()

    assert resp_one.status_code == 200
    assert resp_two.status_code == 200
    path_session_ids = [call["session_id"] for call in fake_registry.path_calls]
    bytes_session_ids = [call["session_id"] for call in fake_registry.bytes_calls]
    assert len(set(path_session_ids)) == 2
    assert len(set(bytes_session_ids)) == 2
    assert all(session_id.startswith("recipe-swatch:req-repeat:") for session_id in path_session_ids)
    assert all(session_id.startswith("recipe-swatch:req-repeat:") for session_id in bytes_session_ids)


def test_generate_swatch_registers_ttl_entries_and_cleanup_expired(tmp_path, monkeypatch):
    """Swatch exports should be TTL-backed and cleaned by registry expiry."""
    engine = _FakeSwatchEngine()
    registry = FileRegistry()
    clock = {"now": 30_000.0}
    swatch_path = tmp_path / "swatch.3mf"
    swatch_path.write_bytes(b"3mf")

    monkeypatch.setattr("api.file_registry.time.time", lambda: clock["now"])

    def _fake_generate_recipe_swatch(*, recipes, **kwargs):
        return (
            str(swatch_path),
            Image.new("RGB", (1, 1), (255, 255, 255)),
            "ok",
        )

    client.app.dependency_overrides[get_file_registry] = lambda: registry
    try:
        with (
            patch("api.routers.five_color._load_engine", return_value=(engine, "test_lut")),
            patch(
                "core.recipe_swatch.generate_recipe_swatch",
                side_effect=_fake_generate_recipe_swatch,
            ),
            patch("api.file_bridge.pil_to_png_bytes", return_value=b"png-bytes"),
        ):
            response = client.post(
                "/api/five-color/generate-swatch",
                json={
                    "lut_name": "test_lut",
                    "recipes": [
                        {
                            "selected_indices": [0, 1, 2, 3, 4],
                            "result_hex": "#123456",
                            "base_color_names": ["ignored"] * 6,
                            "base_color_hexes": ["#000000"] * 6,
                        }
                    ],
                },
            )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    download_id = body["download_url"].rsplit("/", 1)[-1]
    preview_id = body["preview_url"].rsplit("/", 1)[-1]

    download_entry = registry.get_entry(download_id)
    preview_entry = registry.get_entry(preview_id)
    assert download_entry is not None
    assert preview_entry is not None
    assert download_entry["ttl_seconds"] == 8 * 60 * 60
    assert preview_entry["ttl_seconds"] == 8 * 60 * 60

    clock["now"] += (8 * 60 * 60) + 1
    removed = registry.cleanup_expired()

    assert removed == 2
    assert registry.resolve(download_id) is None
    assert registry.resolve(preview_id) is None
    assert not swatch_path.exists()


def test_generate_swatch_cleans_output_when_registry_fails(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Swatch output should not leak when FileRegistry registration fails."""
    engine = _FakeSwatchEngine()
    registry = _SwatchRegisterPathFailingRegistry()
    swatch_path = tmp_path / "swatch.3mf"
    swatch_path.write_bytes(b"3mf")
    app = create_app()
    app.dependency_overrides[get_file_registry] = lambda: registry
    failing_client = TestClient(app, raise_server_exceptions=False)

    def _fake_generate_recipe_swatch(*, recipes, **kwargs):
        return str(swatch_path), None, "ok"

    target_logger = logging.getLogger("lumina.api.routers.five_color")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.ERROR, logger=target_logger.name)
    try:
        with (
            patch("api.routers.five_color._load_engine", return_value=(engine, "test_lut")),
            patch(
                "core.recipe_swatch.generate_recipe_swatch",
                side_effect=_fake_generate_recipe_swatch,
            ),
        ):
            response = failing_client.post(
                "/api/five-color/generate-swatch",
                json={
                    "lut_name": "test_lut",
                    "recipes": [
                        {
                            "selected_indices": [0, 1, 2, 3, 4],
                            "result_hex": "#123456",
                            "base_color_names": ["ignored"] * 6,
                            "base_color_hexes": ["#000000"] * 6,
                        }
                    ],
                },
            )
    finally:
        target_logger.removeHandler(caplog.handler)

    safe_detail = (
        "Five-color swatch download could not be prepared. "
        "Try generating the swatch again."
    )

    assert response.status_code == 500
    assert response.json()["detail"] == safe_detail
    assert "registry backend unavailable" not in response.text
    assert "Internal server error" not in response.text
    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None)
        == "five_color_generate_swatch_registration_failed"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.levelname == "ERROR"
    assert record.error_type == "RuntimeError"
    assert record.error_message == "registry backend unavailable"
    assert record.registration_stage == "download"
    assert record.lut_name == "test_lut"
    assert record.recipe_count == 1
    assert all(
        getattr(record, "event", None) != "api_unhandled_exception"
        for record in caplog.records
    )
    assert registry.generated_path == str(swatch_path)
    assert not swatch_path.exists()


def test_generate_swatch_hides_export_failure_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Swatch export failures should not return raw exporter paths."""
    engine = _FakeSwatchEngine()
    private_path = "/Users/min/private/RecipeSwatch.3mf"
    status_msg = (
        f"3MF export failed: cannot write {private_path}: permission denied"
    )
    safe_detail = (
        "Five-color swatch export failed. Check the selected recipes and "
        "export settings, then try again."
    )

    def _fake_generate_recipe_swatch(*, recipes, **kwargs):
        return None, None, status_msg

    target_logger = logging.getLogger("lumina.api.routers.five_color")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger=target_logger.name)
    try:
        with (
            patch("api.routers.five_color._load_engine", return_value=(engine, "test_lut")),
            patch(
                "core.recipe_swatch.generate_recipe_swatch",
                side_effect=_fake_generate_recipe_swatch,
            ),
        ):
            response = client.post(
                "/api/five-color/generate-swatch",
                json={
                    "lut_name": "test_lut",
                    "recipes": [
                        {
                            "selected_indices": [0, 1, 2, 3, 4],
                            "result_hex": "#123456",
                            "base_color_names": ["ignored"] * 6,
                            "base_color_hexes": ["#000000"] * 6,
                        }
                    ],
                },
            )
    finally:
        target_logger.removeHandler(caplog.handler)

    assert response.status_code == 500
    assert response.json()["detail"] == safe_detail
    assert private_path not in response.text
    assert "3MF export failed" not in response.text

    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "five_color_generate_swatch_failed"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.levelname == "WARNING"
    assert record.status_code == 500
    assert record.error_type == "SwatchGenerationFailed"
    assert record.error_message == status_msg
    assert record.lut_name == "test_lut"
    assert record.recipe_count == 1


def test_generate_swatch_rolls_back_download_when_preview_registration_fails(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Swatch download should be rolled back if preview registration fails."""
    engine = _FakeSwatchEngine()
    registry = _SwatchRegisterBytesFailingRegistry()
    swatch_path = tmp_path / "swatch.3mf"
    swatch_path.write_bytes(b"3mf")
    app = create_app()
    app.dependency_overrides[get_file_registry] = lambda: registry
    failing_client = TestClient(app, raise_server_exceptions=False)

    def _fake_generate_recipe_swatch(*, recipes, **kwargs):
        return (
            str(swatch_path),
            Image.new("RGB", (1, 1), (255, 255, 255)),
            "ok",
        )

    target_logger = logging.getLogger("lumina.api.routers.five_color")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.ERROR, logger=target_logger.name)
    try:
        with (
            patch("api.routers.five_color._load_engine", return_value=(engine, "test_lut")),
            patch(
                "core.recipe_swatch.generate_recipe_swatch",
                side_effect=_fake_generate_recipe_swatch,
            ),
        ):
            response = failing_client.post(
                "/api/five-color/generate-swatch",
                json={
                    "lut_name": "test_lut",
                    "recipes": [
                        {
                            "selected_indices": [0, 1, 2, 3, 4],
                            "result_hex": "#123456",
                            "base_color_names": ["ignored"] * 6,
                            "base_color_hexes": ["#000000"] * 6,
                        }
                    ],
                },
            )
    finally:
        target_logger.removeHandler(caplog.handler)

    safe_detail = (
        "Five-color swatch download could not be prepared. "
        "Try generating the swatch again."
    )

    assert response.status_code == 500
    assert response.json()["detail"] == safe_detail
    assert "registry byte storage unavailable" not in response.text
    assert "Internal server error" not in response.text
    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None)
        == "five_color_generate_swatch_registration_failed"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.levelname == "ERROR"
    assert record.error_type == "RuntimeError"
    assert record.error_message == "registry byte storage unavailable"
    assert record.registration_stage == "preview"
    assert record.lut_name == "test_lut"
    assert record.recipe_count == 1
    assert all(
        getattr(record, "event", None) != "api_unhandled_exception"
        for record in caplog.records
    )
    assert registry.path_file_id is not None
    assert registry.get_entry(registry.path_file_id) is None
    assert registry.resolve(registry.path_file_id) is None
    assert not swatch_path.exists()
