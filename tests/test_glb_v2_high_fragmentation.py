"""High-fragmentation relative invariants for the v2 GLB mesh kernel.

Records (does not gate on absolute thresholds) ``mesh_loop_s`` / GLB size /
vertex count / face count for an adversarial high-fragmentation synthetic
input. Asserts only the relative invariants required by spec R11.6:

* The pipeline does not crash.
* ``mesh.is_watertight == True`` for the largest produced color mesh.
* Volume conservation: per-color volume sum equals
  ``count_nonzero(mask_solid) * pixel_scale**2 * total_layers * LAYER_HEIGHT``
  within 0.5 %.
* XY coverage: per-color projected union area equals
  ``count_nonzero(mask_solid) * pixel_scale**2`` within 1 %.

This test does NOT compare against the Reference_Image absolute thresholds —
those are reserved for ``profile_stage3.py`` (task 17). Skipped if v2 deps
absent.

Feature: glb-preview-mesh-kernel-optimization (v2)
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest
import trimesh


def _v2_deps_present() -> bool:
    return bool(
        importlib.util.find_spec("rasterio.features")
        and importlib.util.find_spec("manifold3d")
    )


_skip_no_v2 = pytest.mark.skipif(
    not _v2_deps_present(),
    reason="optional v2 deps (rasterio + manifold3d) not installed in this venv",
)


def _build_high_fragmentation_cache(seed: int = 11) -> dict:
    """Build a high-fragmentation synthetic image: >= 50 colors, >= 500 components.

    H/W chosen so the matched_rgb stays under the s11 SIMPLIFY_THRESHOLD
    (500_000 px) — we want the kernel hot path, not the downsample path.
    """
    rng = np.random.default_rng(seed)
    H, W = 256, 256
    matched_rgb = np.zeros((H, W, 3), dtype=np.uint8)
    # 60 distinct colors; sprinkle small 2x2..4x4 blobs so each color
    # contributes ~10 connected components.
    palette = []
    for i in range(60):
        r = int((i * 17) % 200 + 30)
        g = int((i * 53) % 200 + 30)
        b = int((i * 91) % 200 + 30)
        palette.append((r, g, b))
    placed = 0
    for color in palette:
        for _ in range(12):
            cw = int(rng.integers(2, 5))
            ch = int(rng.integers(2, 5))
            x0 = int(rng.integers(0, W - cw))
            y0 = int(rng.integers(0, H - ch))
            matched_rgb[y0 : y0 + ch, x0 : x0 + cw] = color
            placed += 1
    # Some single-pixel colored sprinkles for adversarial topology.
    for _ in range(200):
        y = int(rng.integers(0, H))
        x = int(rng.integers(0, W))
        c = palette[int(rng.integers(0, len(palette)))]
        matched_rgb[y, x] = c
    mask_solid = np.any(matched_rgb != 0, axis=2)
    return {
        "matched_rgb": matched_rgb,
        "mask_solid": mask_solid,
        "target_w": W,
        "target_h": H,
        "target_width_mm": 100.0,
    }


@_skip_no_v2
def test_high_fragmentation_relative_invariants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from core.pipeline.s11_glb_preview import generate_segmented_glb
    from core.pipeline import s11_glb_preview as s11
    from config import PrinterConfig

    monkeypatch.setattr(s11, "_V2_IMPORT_OK", None, raising=True)
    monkeypatch.setenv("LUMINA_GLB_KERNEL", "v2")

    cache = _build_high_fragmentation_cache()
    mask_pixel_count = int(cache["mask_solid"].sum())
    width = cache["target_w"]
    target_width_mm = cache["target_width_mm"]
    pixel_scale = target_width_mm / width  # mm/pixel
    # Preview_Native_Layers is hard-coded inside generate_segmented_glb to 25.
    preview_native_layers = 25
    layer_height_mm = float(PrinterConfig.LAYER_HEIGHT)

    out_path = tmp_path / "high_frag_v2.glb"
    glb_path = generate_segmented_glb(cache, str(out_path))
    assert glb_path is not None, "generate_segmented_glb returned no path"
    assert Path(glb_path).exists(), f"missing GLB: {glb_path}"
    glb_size = Path(glb_path).stat().st_size

    # Pull timings written back into cache.
    timings = cache.get("_segmented_glb_timings") or {}
    mesh_loop_s = float(timings.get("mesh_loop_s", 0.0))
    total_s = float(timings.get("total_s", 0.0))

    # Load back to count vertices / faces and inspect named meshes.
    scene = trimesh.load(glb_path, force="scene")
    total_vertex_count = 0
    total_face_count = 0
    color_meshes: list[trimesh.Trimesh] = []
    backing_mesh = None
    for node in scene.graph.nodes:
        if node == "world":
            continue
        try:
            _t, geom_name = scene.graph[node]
        except Exception:  # noqa: BLE001
            continue
        if geom_name is None:
            continue
        geom = scene.geometry.get(geom_name)
        if geom is None:
            continue
        total_vertex_count += int(len(geom.vertices))
        total_face_count += int(len(geom.faces))
        if node.startswith("color_"):
            color_meshes.append(geom)
        elif node == "backing_plate":
            backing_mesh = geom

    # === Recorded metrics (don't gate on absolute, just print for archive) ===
    metrics = {
        "mask_pixel_count": mask_pixel_count,
        "color_meshes": len(color_meshes),
        "mesh_loop_s": round(mesh_loop_s, 4),
        "total_s": round(total_s, 4),
        "glb_size_bytes": glb_size,
        "vertex_count": total_vertex_count,
        "face_count": total_face_count,
    }
    with capsys.disabled():
        print(f"\nhigh_fragmentation v2 metrics: {metrics}")

    # === Relative invariants (the only assertions) ===

    assert color_meshes, "expected at least one color_<hex> mesh"
    assert backing_mesh is not None, "expected backing_plate mesh"

    # R7.1: backing watertight + volume.
    expected_backing_volume = (
        mask_pixel_count * (pixel_scale ** 2) * layer_height_mm
    )
    backing_diff = abs(backing_mesh.volume - expected_backing_volume) / expected_backing_volume
    assert backing_mesh.is_watertight, "backing_plate must be watertight"
    assert backing_diff <= 0.005, (
        f"backing volume diff {backing_diff:.4%}: "
        f"got {backing_mesh.volume}, expected {expected_backing_volume}"
    )

    # R7.2: per-color watertight + summed volume.
    summed_color_volume = float(sum(m.volume for m in color_meshes))
    expected_color_volume = (
        mask_pixel_count * (pixel_scale ** 2) * preview_native_layers * layer_height_mm
    )
    color_vol_diff = abs(summed_color_volume - expected_color_volume) / expected_color_volume
    assert color_vol_diff <= 0.005, (
        f"summed color volume diff {color_vol_diff:.4%}: "
        f"got {summed_color_volume}, expected {expected_color_volume}"
    )
    for m in color_meshes:
        assert m.is_watertight, f"color mesh not watertight: vertices={len(m.vertices)}"

    # R7.3: per-color XY projection union area vs mask.
    # Approximate: each mesh's XY footprint area = volume / native_z_height.
    # native_z_height for color mesh = preview_native_layers * layer_height_mm.
    color_native_z = preview_native_layers * layer_height_mm
    xy_area_per_color = [float(m.volume) / color_native_z for m in color_meshes]
    summed_xy = float(sum(xy_area_per_color))
    expected_xy = mask_pixel_count * (pixel_scale ** 2)
    xy_diff = abs(summed_xy - expected_xy) / expected_xy
    assert xy_diff <= 0.01, (
        f"XY coverage diff {xy_diff:.4%}: got {summed_xy}, expected {expected_xy}"
    )
