"""Requested geometry must never be replaced by a successful flat retry."""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from core.heightmap_loader import HeightmapLoader
from core.pipeline import s06_voxel_building as s06


@pytest.fixture
def voxel_context() -> dict:
    return {
        "material_matrix": np.zeros((2, 2, 5), dtype=int),
        "mask_solid": np.ones((2, 2), dtype=bool),
        "matched_rgb": np.full((2, 2, 3), 255, dtype=np.uint8),
        "spacer_thick": 0.8,
        "pixel_scale": 0.1,
        "target_w": 2,
        "target_h": 2,
        "processor": SimpleNamespace(
            _extract_wireframe_mask=lambda *_: np.ones((2, 2), dtype=bool),
        ),
    }


@pytest.mark.parametrize("error_type", [ValueError, TypeError, KeyError, RuntimeError, OSError])
@pytest.mark.parametrize(
    ("settings", "builder"),
    [
        ({"enable_relief": True, "color_height_map": {"#ffffff": 2.4}}, "_build_relief_voxel_matrix"),
        ({"enable_cloisonne": True}, "_build_cloisonne_voxel_matrix"),
        ({"color_mode": "5-Color Extended"}, "_build_voxel_matrix_faceup"),
    ],
)
def test_requested_builder_failure_does_not_retry_flat(
    voxel_context: dict, monkeypatch: pytest.MonkeyPatch, settings: dict,
    builder: str, error_type: type[Exception],
) -> None:
    # Keep the real ordinary builder available: it would successfully hide the failure.
    flat = Mock(wraps=s06._build_voxel_matrix)
    monkeypatch.setattr(s06, "_build_voxel_matrix", flat)
    monkeypatch.setattr(s06, builder, Mock(side_effect=error_type("requested geometry failed")))
    voxel_context.update(settings)

    result = s06.run(voxel_context)

    assert "requested geometry failed" in result["error"]
    assert "full_matrix" not in result
    assert "backing_metadata" not in result
    assert "total_layers" not in result
    flat.assert_not_called()


@pytest.mark.parametrize("error_type", [ValueError, TypeError, KeyError, RuntimeError, OSError])
def test_cavity_failure_does_not_publish_uncarved_geometry(
    voxel_context: dict, monkeypatch: pytest.MonkeyPatch, error_type: type[Exception],
) -> None:
    flat = Mock(wraps=s06._build_voxel_matrix)
    monkeypatch.setattr(s06, "_build_voxel_matrix", flat)
    monkeypatch.setattr(
        s06, "_carve_fridge_magnet_cavities", Mock(side_effect=error_type("cavity failed")),
    )
    voxel_context["enable_fridge_magnet"] = True

    result = s06.run(voxel_context)

    assert "cavity failed" in result["error"]
    assert "full_matrix" not in result
    flat.assert_called_once()


@pytest.mark.parametrize("error_type", [ImportError, OSError, ValueError, TypeError, KeyError])
def test_heightmap_load_error_is_a_stage_failure(
    voxel_context: dict, monkeypatch: pytest.MonkeyPatch, error_type: type[Exception],
) -> None:
    voxel_context.update(enable_relief=True, height_mode="heightmap", heightmap_path="height.png")
    monkeypatch.setattr(HeightmapLoader, "load_and_process", Mock(side_effect=error_type("height unreadable")))
    flat = Mock(wraps=s06._build_voxel_matrix)
    monkeypatch.setattr(s06, "_build_voxel_matrix", flat)

    result = s06.run(voxel_context)

    assert "height unreadable" in result["error"]
    assert "full_matrix" not in result
    flat.assert_not_called()


@pytest.mark.parametrize("path", [None, "height.png"])
def test_missing_or_rejected_heightmap_does_not_succeed(
    voxel_context: dict, monkeypatch: pytest.MonkeyPatch, path: str | None,
) -> None:
    voxel_context.update(enable_relief=True, height_mode="heightmap", heightmap_path=path)
    monkeypatch.setattr(
        HeightmapLoader, "load_and_process", Mock(return_value={"success": False, "error": "invalid pixels"}),
    )
    result = s06.run(voxel_context)
    assert "heightmap" in result["error"].lower()
    if path:
        assert "invalid pixels" in result["error"]
    assert "full_matrix" not in result


@pytest.mark.parametrize(
    ("settings", "builder"),
    [
        ({}, "_build_voxel_matrix"),
        ({"enable_relief": True, "color_height_map": {}}, "_build_voxel_matrix"),
        ({"enable_relief": True, "color_height_map": {"#ffffff": 2.4}}, "_build_relief_voxel_matrix"),
        ({"enable_cloisonne": True, "enable_relief": True, "height_mode": "heightmap"}, "_build_cloisonne_voxel_matrix"),
        ({"color_mode": "5-Color Extended", "enable_cloisonne": True, "enable_relief": True, "height_mode": "heightmap"}, "_build_voxel_matrix_faceup"),
    ],
)
def test_normal_branch_priority_is_preserved(
    voxel_context: dict, monkeypatch: pytest.MonkeyPatch, settings: dict, builder: str,
) -> None:
    selected = Mock(wraps=getattr(s06, builder))
    monkeypatch.setattr(s06, builder, selected)
    voxel_context.update(settings)

    result = s06.run(voxel_context)

    assert not result.get("error")
    assert isinstance(result["full_matrix"], np.ndarray)
    selected.assert_called_once()


def test_successful_heightmap_reaches_relief_builder(
    voxel_context: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    heights = np.array([[0.8, 1.6], [2.4, 3.2]])
    stats = {"max_height": 3.2}
    monkeypatch.setattr(HeightmapLoader, "load_and_process", Mock(return_value={
        "success": True, "height_matrix": heights, "stats": stats,
    }))
    relief = Mock(wraps=s06._build_relief_voxel_matrix)
    monkeypatch.setattr(s06, "_build_relief_voxel_matrix", relief)
    voxel_context.update(enable_relief=True, height_mode="heightmap", heightmap_path="height.png")

    result = s06.run(voxel_context)

    assert not result.get("error")
    assert relief.call_args.kwargs["height_matrix"] is heights
    assert result["heightmap_stats"] is stats
    assert result["backing_metadata"]["is_relief"] is True
