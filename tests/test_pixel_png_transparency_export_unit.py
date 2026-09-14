"""Verify PNG alpha survives the complete pixel-mode 3MF export path."""

from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
from PIL import Image
import pytest
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
import trimesh

from config import ModelingMode, PrinterConfig
from core.converter import generate_final_model


def _read_3mf_meshes(path: str) -> list[trimesh.Trimesh]:
    # Read each production-extension object separately; generic scene loaders
    # can concatenate multiple objects from the same .model ZIP member.
    meshes = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.endswith(".model"):
                continue
            root = ET.fromstring(archive.read(name))
            for mesh in root.findall(".//{*}mesh"):
                vertices = np.array([
                    [float(vertex.attrib[axis]) for axis in ("x", "y", "z")]
                    for vertex in mesh.findall("{*}vertices/{*}vertex")
                ])
                faces = np.array([
                    [int(face.attrib[key]) for key in ("v1", "v2", "v3")]
                    for face in mesh.findall("{*}triangles/{*}triangle")
                ])
                meshes.append(trimesh.Trimesh(vertices, faces, process=False))
    return meshes


@pytest.mark.parametrize("structure_mode", ["Single-sided", "Double-sided"])
@pytest.mark.parametrize("opaque", [False, True])
def test_pixel_png_alpha_survives_exported_3mf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structure_mode: str, opaque: bool
) -> None:
    for module, field in (
        ("core.pipeline.s09_export_3mf", "MODELS_DIR"),
        ("core.pipeline.s10_color_recipe", "OUTPUT_DIR"),
        ("core.pipeline.s11_glb_preview", "OUTPUT_DIR"),
    ):
        monkeypatch.setattr(f"{module}.{field}", str(tmp_path))
    monkeypatch.setenv("LUMINA_COLOR_RECIPE_POLICY", "off")

    mask = np.ones((16, 16), dtype=bool)
    if not opaque:
        mask[:] = False
        mask[3:13, 3:13] = True
        mask[6:10, 6:10] = False
    rgba = np.full((16, 16, 4), 255, dtype=np.uint8)
    rgba[..., 3] = mask.astype(np.uint8) * 255
    image_path = tmp_path / "alpha.png"
    Image.fromarray(rgba).save(image_path)
    lut_path = tmp_path / "white.npy"
    np.save(lut_path, np.full((1024, 3), 255, dtype=np.uint8))

    scale = PrinterConfig.NOZZLE_WIDTH
    path, _, _, status, _ = generate_final_model(
        image_path=str(image_path), lut_path=str(lut_path),
        target_width_mm=16 * scale, spacer_thick=0.16,
        structure_mode=structure_mode, color_mode="4-Color (RYBW)",
        add_loop=False, loop_width=4.0, loop_length=8.0, loop_hole=2.5,
        loop_pos=None, modeling_mode=ModelingMode.PIXEL,
        center_on_bed=False,
    )
    assert path is not None, status
    meshes = _read_3mf_meshes(path)
    assert meshes
    projected = []
    for mesh in meshes:
        for triangle in mesh.triangles:
            polygon = Polygon(triangle[:, :2])
            if polygon.area > 1e-10:
                projected.append(polygon)
    actual = unary_union(projected)
    expected = unary_union([
        box(x * scale, (15 - y) * scale, (x + 1) * scale, (16 - y) * scale)
        for y, x in zip(*np.where(mask))
    ])
    assert actual.symmetric_difference(expected).area < 1e-4
    color_faces = 2 if structure_mode == "Double-sided" else 1
    thickness = 0.16 + color_faces * 5 * PrinterConfig.LAYER_HEIGHT
    assert sum(mesh.volume for mesh in meshes) == pytest.approx(
        expected.area * thickness, rel=1e-5
    )
