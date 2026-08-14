"""Unit test for the batch worker output contract.
批量 worker 输出契约的单元测试。

This test exercises the new ``worker_batch_convert_item`` contract
defined by ``batch-mode-merged-3mf`` task 7. It calls the worker once
with a tiny real input (one small PNG plus a mocked
``core.converter.convert_image_to_3d`` that emits a real Bambu 3MF and a
real GLB), then asserts:

1. The returned dict contains exactly the 5 expected keys.
2. ``threemf_path``, ``preview_glb_path``, ``metadata_sidecar_path`` all
   point to distinct files whose basenames start with the supplied
   ``artifact_prefix``.
3. The sidecar JSON deserialises as ``PerImageMetadataSidecar``,
   ``slots`` has length >= 1 and every ``MaterialSlot`` 4-tuple
   (``slot_id`` / ``slot_name`` / ``preview_color`` / ``material_id``)
   is non-empty.
4. ``xy_bbox_mm`` in the returned dict matches the sidecar's
   ``xy_bbox_mm``.
5. The returned dict does not carry a ``trimesh.Scene`` instance or
   raw bytes payload (the worker boundary stays at "file paths +
   scalars" only).

**Validates: Requirements 1.3, 6.1, 6.2**
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import trimesh
from PIL import Image

from api.schemas.batch_sidecar import PerImageMetadataSidecar
from api.workers.converter_workers import (
    _batch_compute_xy_bbox_mm,
    worker_batch_convert_item,
)
from config import MODELS_DIR, OUTPUT_DIR, TEMP_DIR
from utils.bambu_3mf_writer import export_scene_with_bambu_metadata


# ---------------------------------------------------------------------------
# Fixtures: tiny real artifacts the mocked convert_image_to_3d will return
# ---------------------------------------------------------------------------


def _make_test_image(tmp_dir: str) -> Path:
    """Write a tiny PNG that the worker can use to compute xy_bbox_mm.

    在 ``tmp_dir`` 下写一张极小 PNG，worker 用它计算 xy_bbox_mm。
    """
    img = Image.new("RGB", (40, 30), (200, 100, 50))
    fd, path = tempfile.mkstemp(prefix="batch_worker_unit_image_", suffix=".png", dir=tmp_dir)
    os.close(fd)
    img.save(path)
    return Path(path)


def _make_real_bambu_3mf(out_path: Path) -> None:
    """Write a small real Bambu 3MF with two named slots.

    用 trimesh + ``export_scene_with_bambu_metadata`` 写出一个最小但真实的
    Bambu 3MF；该文件的 ``Metadata/model_settings.config`` /
    ``Metadata/project_settings.config`` 可被 worker 的
    ``_batch_extract_slots_from_3mf`` 解出 2 个 slot。
    """
    scene = trimesh.Scene()

    box1 = trimesh.creation.box(extents=[10.0, 10.0, 2.0])
    box1.metadata["bambu_material_name"] = "Bambu PLA Black"
    scene.add_geometry(box1, geom_name="Bambu PLA Black")

    box2 = trimesh.creation.box(extents=[8.0, 8.0, 2.0])
    box2.apply_translation([12.0, 0.0, 0.0])
    box2.metadata["bambu_material_name"] = "Bambu PLA White"
    scene.add_geometry(box2, geom_name="Bambu PLA White")

    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=str(out_path),
        slot_names=["Bambu PLA Black", "Bambu PLA White"],
        preview_colors={
            "Bambu PLA Black": (16, 16, 16, 255),
            "Bambu PLA White": (240, 240, 240, 255),
        },
        settings={},
        color_mode="4-Color",
    )


def _make_real_glb(out_path: Path) -> None:
    """Write a small real GLB so the worker can rename it as preview."""
    box = trimesh.creation.box(extents=[10.0, 10.0, 2.0])
    scene = trimesh.Scene()
    scene.add_geometry(box, geom_name="preview")
    scene.export(str(out_path))


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_batch_compute_xy_bbox_ignores_transparent_padding(tmp_path) -> None:
    """Transparent image padding must not inflate batch layout spacing.

    透明留白不应放大批量排布间距；否则用户设置的 2mm 间距在预览和切片
    软件里会看起来明显偏大。
    """
    image = Image.new("RGBA", (100, 50), (0, 0, 0, 0))
    for x in range(20, 80):
        for y in range(10, 30):
            image.putpixel((x, y), (255, 0, 0, 255))
    image_path = tmp_path / "transparent-padding.png"
    image.save(image_path)

    width_mm, depth_mm = _batch_compute_xy_bbox_mm(
        str(image_path),
        target_width_mm=50.0,
    )

    assert width_mm == 30.0
    assert depth_mm == 10.0


def test_batch_compute_xy_bbox_supports_svg_alpha_bbox(tmp_path) -> None:
    """SVG inputs should not fail batch layout footprint calculation.

    批量 SVG 不应在排布占位尺寸计算阶段被 PIL 误判为无法打开。
    """
    svg_path = tmp_path / "sprite.svg"
    svg_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10" '
        'viewBox="0 0 20 10"><rect x="5" y="2" width="10" height="4" '
        'fill="#ff0000"/></svg>',
        encoding="utf-8",
    )
    raster = np.zeros((10, 20, 4), dtype=np.uint8)
    raster[2:6, 5:15, 3] = 255

    with patch(
        "core.pipeline.processing_ops.svg_rasterizer.rasterize_svg",
        return_value=raster,
    ) as rasterize_svg_mock:
        width_mm, depth_mm = _batch_compute_xy_bbox_mm(
            str(svg_path),
            target_width_mm=40.0,
            svg_pixels_per_mm=3.0,
        )

    assert width_mm == 20.0
    assert depth_mm == 8.0
    rasterize_svg_mock.assert_called_once_with(
        svg_path=str(svg_path),
        target_width_mm=40.0,
        pixels_per_mm=3.0,
        crop_to_content=False,
    )


@pytest.fixture
def batch_worker_artifacts(tmp_path):
    """Create source 3MF / GLB / image and yield the worker result.

    The worker moves the source 3MF / GLB into ``TEMP_DIR`` under the
    prefixed name; this fixture tracks every path produced so cleanup
    runs even on assertion failure.

    在 fixture teardown 中清理 worker 输出 + 任何残留的源文件，避免
    污染 ``TEMP_DIR`` / ``MODELS_DIR`` / ``OUTPUT_DIR``。
    """
    artifact_prefix = "batch-test1234-"

    image_path = _make_test_image(str(tmp_path))

    fd, threemf_path = tempfile.mkstemp(
        prefix="batch_worker_unit_pre_", suffix=".3mf", dir=MODELS_DIR
    )
    os.close(fd)
    _make_real_bambu_3mf(Path(threemf_path))

    fd, glb_path = tempfile.mkstemp(
        prefix="batch_worker_unit_pre_", suffix=".glb", dir=OUTPUT_DIR
    )
    os.close(fd)
    _make_real_glb(Path(glb_path))

    fake_return = (
        threemf_path,
        glb_path,
        np.zeros((1, 1, 4), dtype=np.uint8),
        "OK",
        None,
    )

    result: dict | None = None
    try:
        with patch(
            "core.converter.convert_image_to_3d",
            return_value=fake_return,
        ) as convert_mock:
            result = worker_batch_convert_item(
                image_path=str(image_path),
                lut_path="dummy_lut.npy",
                target_width_mm=80.0,
                spacer_thick=1.2,
                structure_mode="Single-sided",
                color_mode="4-Color (RYBW)",
                modeling_mode_value="high-fidelity",
                color_layers=5,
                layer_height_mm=0.08,
                quantize_colors=64,
                enable_cleanup=True,
                artifact_prefix=artifact_prefix,
                printer_id="bambu-p1s",
                slicer="OrcaSlicer",
                nozzle_size="0.2",
                enable_base_layer_height_modifier=False,
                backing_infill_density_percent=25,
            )
            forwarded = convert_mock.call_args.kwargs
            assert forwarded["printer_id"] == "bambu-p1s"
            assert forwarded["slicer"] == "OrcaSlicer"
            assert forwarded["nozzle_size"] == "0.2"
            assert forwarded["enable_base_layer_height_modifier"] is False
            assert forwarded["backing_infill_density_percent"] == 25

        yield artifact_prefix, image_path, result
    finally:
        # Best-effort cleanup. The worker should have moved the source
        # 3MF / GLB into TEMP_DIR; if it did not (e.g. error path), unlink
        # the leftovers so reruns stay idempotent.
        for cleanup in (image_path, Path(threemf_path), Path(glb_path)):
            try:
                if cleanup.exists():
                    cleanup.unlink()
            except OSError:
                pass
        # Worker outputs.
        for key in ("threemf_path", "preview_glb_path", "metadata_sidecar_path"):
            value = (result or {}).get(key)
            if isinstance(value, str):
                try:
                    Path(value).unlink(missing_ok=True)
                except OSError:
                    pass


def test_worker_batch_convert_item_returns_full_five_key_contract(
    batch_worker_artifacts,
) -> None:
    """Returned dict contains exactly the 5 documented keys (R1.3, R6.1)."""
    _, _, result = batch_worker_artifacts

    expected_keys = {
        "threemf_path",
        "preview_glb_path",
        "metadata_sidecar_path",
        "xy_bbox_mm",
        "status_msg",
    }
    assert set(result.keys()) == expected_keys, (
        f"worker result keys {sorted(result.keys())!r} != "
        f"expected {sorted(expected_keys)!r}"
    )


def test_worker_batch_convert_item_three_paths_distinct_and_prefixed(
    batch_worker_artifacts,
) -> None:
    """3MF / preview GLB / sidecar paths are distinct and prefixed (R1.3, R6.1)."""
    artifact_prefix, _, result = batch_worker_artifacts

    threemf_out = result["threemf_path"]
    glb_out = result["preview_glb_path"]
    sidecar_out = result["metadata_sidecar_path"]

    # All three are real on-disk files.
    for path_value, label in (
        (threemf_out, "threemf_path"),
        (glb_out, "preview_glb_path"),
        (sidecar_out, "metadata_sidecar_path"),
    ):
        assert isinstance(path_value, str) and path_value, f"{label} is empty"
        assert os.path.exists(path_value), (
            f"{label} missing on disk: {path_value!r}"
        )
        base = os.path.basename(path_value)
        assert base.startswith(artifact_prefix), (
            f"{label} basename {base!r} does not start with "
            f"{artifact_prefix!r}"
        )

    # Pairwise distinct (both lexically and after realpath resolution).
    paths = [threemf_out, glb_out, sidecar_out]
    assert len(set(paths)) == 3, (
        f"expected 3 distinct artifact paths, got {paths!r}"
    )
    real_paths = [os.path.realpath(p) for p in paths]
    assert len(set(real_paths)) == 3, (
        f"artifact paths collide after realpath resolution: {real_paths!r}"
    )


def test_worker_batch_convert_item_sidecar_validates_with_full_slots(
    batch_worker_artifacts,
) -> None:
    """Sidecar JSON validates as PerImageMetadataSidecar with non-empty slots (R1.3, R6.2)."""
    _, image_path, result = batch_worker_artifacts

    sidecar_out = result["metadata_sidecar_path"]
    with open(sidecar_out, "r", encoding="utf-8") as fh:
        sidecar_payload = json.load(fh)

    sidecar_model = PerImageMetadataSidecar.model_validate(sidecar_payload)

    # source_filename round-trips the original image basename.
    assert sidecar_model.source_filename == os.path.basename(image_path)

    # At least 1 slot present, with every MaterialSlot 4-tuple field
    # non-empty (slot_id is an int >=0, slot_name / preview_color /
    # material_id are non-empty strings — the Pydantic model already
    # enforces these via min_length / pattern, but assert explicitly so
    # the test fails loudly if the schema is loosened).
    assert len(sidecar_model.slots) >= 1, (
        f"sidecar must contain at least one MaterialSlot; got "
        f"{sidecar_model.slots!r}"
    )
    for slot in sidecar_model.slots:
        assert isinstance(slot.slot_id, int) and slot.slot_id >= 0, (
            f"slot_id must be a non-negative int; got {slot.slot_id!r}"
        )
        assert isinstance(slot.slot_name, str) and slot.slot_name, (
            f"slot_name must be a non-empty string; got {slot.slot_name!r}"
        )
        assert isinstance(slot.preview_color, str) and slot.preview_color, (
            f"preview_color must be a non-empty hex string; got "
            f"{slot.preview_color!r}"
        )
        assert isinstance(slot.material_id, str) and slot.material_id, (
            f"material_id must be a non-empty string; got "
            f"{slot.material_id!r}"
        )


def test_worker_batch_convert_item_xy_bbox_matches_sidecar(
    batch_worker_artifacts,
) -> None:
    """Returned ``xy_bbox_mm`` matches the sidecar's xy_bbox_mm (R1.3)."""
    _, _, result = batch_worker_artifacts

    sidecar_out = result["metadata_sidecar_path"]
    with open(sidecar_out, "r", encoding="utf-8") as fh:
        sidecar_payload = json.load(fh)

    bbox_tuple = result["xy_bbox_mm"]
    assert isinstance(bbox_tuple, tuple), (
        f"xy_bbox_mm must be a tuple; got {type(bbox_tuple).__name__}"
    )
    assert len(bbox_tuple) == 2, (
        f"xy_bbox_mm must be a 2-tuple (width_mm, depth_mm); got "
        f"{bbox_tuple!r}"
    )

    width_mm, depth_mm = bbox_tuple
    assert width_mm == sidecar_payload["xy_bbox_mm"]["width_mm"], (
        f"width_mm mismatch: tuple={width_mm!r} sidecar="
        f"{sidecar_payload['xy_bbox_mm']['width_mm']!r}"
    )
    assert depth_mm == sidecar_payload["xy_bbox_mm"]["depth_mm"], (
        f"depth_mm mismatch: tuple={depth_mm!r} sidecar="
        f"{sidecar_payload['xy_bbox_mm']['depth_mm']!r}"
    )


def test_worker_batch_convert_item_no_scene_or_bytes_payload(
    batch_worker_artifacts,
) -> None:
    """Returned dict carries no ``trimesh.Scene`` / bytes payload (R6.1).

    The worker boundary is "file paths + scalars". A regression here
    means a future change accidentally pickled a heavy Scene / bytes
    blob across the process boundary, breaking the picklability +
    minimal-boundary contract that the spec calls out explicitly
    (design.md §Components 5).
    """
    _, _, result = batch_worker_artifacts

    for key, value in result.items():
        # No trimesh Scene anywhere in the result.
        assert not isinstance(value, trimesh.Scene), (
            f"result[{key!r}] is a trimesh.Scene; the worker must only "
            "return file paths + scalars"
        )
        # No bytes / bytearray / memoryview payload anywhere either.
        assert not isinstance(value, (bytes, bytearray, memoryview)), (
            f"result[{key!r}] is a {type(value).__name__} payload; the "
            "worker must only return file paths + scalars"
        )
