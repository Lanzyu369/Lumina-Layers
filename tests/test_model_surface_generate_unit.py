from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from PIL import Image
import pytest
import trimesh

from api.app import app
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.routers.converter.generate import (
    _prepare_model_surface_overlay_worker_params,
    _should_use_model_surface_overlay,
)
from api.session_store import SessionStore
from config import ModelingMode as CoreModelingMode
from core.model_surface.assembly import OverlaySceneResult


@pytest.fixture()
def generate_state():
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    pool = type("FakePool", (), {})()
    previous = {
        get_session_store: app.dependency_overrides.get(get_session_store),
        get_file_registry: app.dependency_overrides.get(get_file_registry),
        get_worker_pool: app.dependency_overrides.get(get_worker_pool),
    }
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = lambda: pool
    try:
        yield store, registry, pool
    finally:
        store.clear_all()
        registry.clear_all()
        for dependency, old_override in previous.items():
            if old_override is None:
                app.dependency_overrides.pop(dependency, None)
            else:
                app.dependency_overrides[dependency] = old_override


def test_should_use_model_surface_overlay_requires_session_flag():
    assert _should_use_model_surface_overlay({"surface_overlay_enabled": True}) is True
    assert _should_use_model_surface_overlay({"surface_overlay_enabled": False}) is False
    assert _should_use_model_surface_overlay({}) is False


def test_generate_routes_model_surface_session_to_overlay_worker(
    tmp_path,
    generate_state,
):
    store, _registry, pool = generate_state
    image_path = tmp_path / "surface-art.png"
    lut_path = tmp_path / "lut.npy"
    model_path = tmp_path / "plate.stl"
    Image.new("RGB", (20, 10), (255, 0, 0)).save(image_path)
    lut_path.write_bytes(b"lut")
    trimesh.creation.box(extents=(20.0, 10.0, 2.0)).export(model_path)

    sid = store.create()
    store.put(
        sid,
        "preview_cache",
        {
            "target_w": 20,
            "target_h": 10,
            "target_width_mm": 20.0,
        },
    )
    store.put(sid, "image_path", str(image_path))
    store.put(sid, "lut_path", str(lut_path))
    store.put(sid, "surface_overlay_enabled", True)
    store.put(sid, "surface_model_path", str(model_path))
    store.put(
        sid,
        "surface_footprint",
        {
            "frame": {
                "origin": [0.0, 0.0, 1.0],
                "normal": [0.0, 0.0, 1.0],
                "u_axis": [1.0, 0.0, 0.0],
                "v_axis": [0.0, 1.0, 0.0],
            },
            "outer": [[-10.0, -5.0], [10.0, -5.0], [10.0, 5.0], [-10.0, 5.0], [-10.0, -5.0]],
            "holes": [],
            "bounds_width_mm": 20.0,
            "bounds_height_mm": 10.0,
        },
    )

    async def fake_submit(_fn, *_args):
        out_path = tmp_path / "surface.3mf"
        out_path.write_bytes(b"3mf")
        return {"threemf_path": str(out_path), "glb_path": None, "status_msg": "Surface OK"}

    pool.submit = AsyncMock(side_effect=fake_submit)

    response = TestClient(app).post(
        "/api/convert/generate",
        json={
            "session_id": sid,
            "params": {
                "target_width_mm": 20.0,
                "lut_name": "default",
                "add_loop": True,
                "enable_fridge_magnet": True,
                "model_enable": True,
            },
        },
    )

    assert response.status_code == 200, response.text
    from api.workers.converter_workers import worker_generate_model_surface_overlay

    worker_fn, submitted_image, submitted_lut, submitted_params = pool.submit.call_args.args
    assert worker_fn is worker_generate_model_surface_overlay
    assert submitted_image == str(image_path)
    assert submitted_lut == str(lut_path)
    assert submitted_params["surface_model_path"] == str(model_path)
    assert submitted_params["surface_pocket_depth_mm"] == pytest.approx(0.4)
    assert submitted_params["surface_footprint"]["bounds_width_mm"] == 20.0
    assert submitted_params["converter_params"]["target_width_mm"] == 20.0
    assert submitted_params["converter_params"]["add_loop"] is False
    assert submitted_params["converter_params"]["enable_fridge_magnet"] is False
    assert submitted_params["converter_params"]["model_enable"] is True
    assert "surface_model_path" not in submitted_params["converter_params"]
    assert response.json()["preview_3d_url"] is None


def test_model_surface_vector_request_uses_raster_mode_for_rendered_artwork(tmp_path):
    image_path = tmp_path / "surface-art.png"
    model_path = tmp_path / "plate.stl"
    Image.new("RGB", (20, 10), (255, 0, 0)).save(image_path)
    trimesh.creation.box(extents=(20.0, 10.0, 2.0)).export(model_path)

    worker_params = _prepare_model_surface_overlay_worker_params(
        {
            "surface_model_path": str(model_path),
            "surface_artwork_path": str(image_path),
            "surface_footprint": {
                "frame": {
                    "origin": [0.0, 0.0, 1.0],
                    "normal": [0.0, 0.0, 1.0],
                    "u_axis": [1.0, 0.0, 0.0],
                    "v_axis": [0.0, 1.0, 0.0],
                },
                "outer": [
                    [-10.0, -5.0],
                    [10.0, -5.0],
                    [10.0, 5.0],
                    [-10.0, 5.0],
                    [-10.0, -5.0],
                ],
                "holes": [],
                "bounds_width_mm": 20.0,
                "bounds_height_mm": 10.0,
            },
        },
        {
            "target_width_mm": 20.0,
            "spacer_thick": 1.2,
            "structure_mode": "Double-sided",
            "color_mode": "4-Color (RYBW)",
            "modeling_mode": CoreModelingMode.VECTOR,
            "add_loop": True,
            "loop_pos": "top",
        },
    )

    assert worker_params["converter_params"]["modeling_mode"] == CoreModelingMode.HIGH_FIDELITY


def test_worker_generate_model_surface_overlay_exports_bambu_3mf(tmp_path):
    image_path = tmp_path / "surface-art.png"
    lut_path = tmp_path / "lut.npy"
    model_path = tmp_path / "plate.stl"
    Image.new("RGB", (20, 10), (255, 0, 0)).save(image_path)
    lut_path.write_bytes(b"lut")
    model_path.write_bytes(b"solid plate\nendsolid plate\n")

    scene = trimesh.Scene()
    scene.add_geometry(
        trimesh.creation.box(extents=(20.0, 10.0, 1.0)),
        node_name="surface_base",
        geom_name="surface_base",
    )
    overlay = OverlaySceneResult(
        scene=scene,
        slot_names=["surface_base", "red"],
        preview_colors={"surface_base": (245, 245, 245), "red": (255, 0, 0)},
    )
    captured: dict[str, object] = {}

    def fake_export_scene_with_bambu_metadata(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"3mf")
        captured.update(kwargs)
        return kwargs["output_path"]

    def fake_build_surface_overlay_scene(**kwargs):
        assert kwargs["model_path"] == str(model_path)
        assert kwargs["artwork_image_path"] == str(image_path)
        assert kwargs["lut_path"] == str(lut_path)
        assert kwargs["pocket_depth_mm"] == pytest.approx(0.35)
        assert kwargs["footprint"].bounds_width_mm == pytest.approx(20.0)
        assert kwargs["converter_params"]["target_width_mm"] == 20.0
        return overlay

    from api.workers.converter_workers import worker_generate_model_surface_overlay

    with (
        patch(
            "core.model_surface.pipeline.build_surface_overlay_scene",
            side_effect=fake_build_surface_overlay_scene,
        ),
        patch(
            "utils.bambu_3mf_writer.export_scene_with_bambu_metadata",
            side_effect=fake_export_scene_with_bambu_metadata,
        ),
    ):
        result = worker_generate_model_surface_overlay(
            str(image_path),
            str(lut_path),
            {
                "surface_model_path": str(model_path),
                "surface_footprint": {
                    "frame": {
                        "origin": [0.0, 0.0, 1.0],
                        "normal": [0.0, 0.0, 1.0],
                        "u_axis": [1.0, 0.0, 0.0],
                        "v_axis": [0.0, 1.0, 0.0],
                    },
                    "outer": [
                        [-10.0, -5.0],
                        [10.0, -5.0],
                        [10.0, 5.0],
                        [-10.0, 5.0],
                        [-10.0, -5.0],
                    ],
                    "holes": [],
                    "bounds_width_mm": 20.0,
                    "bounds_height_mm": 10.0,
                },
                "surface_pocket_depth_mm": 0.35,
                "converter_params": {
                    "target_width_mm": 20.0,
                    "spacer_thick": 1.2,
                    "structure_mode": "Double-sided",
                    "color_mode": "4-Color (RYBW)",
                    "add_loop": False,
                    "loop_width": 4.0,
                    "loop_length": 8.0,
                    "loop_hole": 2.5,
                    "loop_pos": None,
                },
                "printer_id": "orca-p1s",
                "slicer": "OrcaSlicer",
                "nozzle_size": "0.4",
                "device_profile_id": "OrcaSlicer:bbl:bambu-lab-p1s:0.4",
            },
        )

    assert Path(result["threemf_path"]).exists()
    assert result["glb_path"] is None
    assert result["status_msg"] == "Surface overlay model generated"
    assert captured["scene"] is scene
    assert captured["slot_names"] == ["surface_base", "red"]
    assert captured["project_slot_names"] == ["surface_base", "red"]
    assert captured["preview_colors"] == overlay.preview_colors
    assert captured["cover_source"] == str(image_path)
    assert captured["enable_base_layer_height_modifier"] is False
    assert captured["device_profile_id"] == "OrcaSlicer:bbl:bambu-lab-p1s:0.4"
