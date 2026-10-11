"""Dual-kernel equivalence: ``LUMINA_GLB_KERNEL=shapely_v1`` vs ``=v2`` produce
equivalent GLB scenes on the same input.

Skipped if optional v2 deps are absent (rasterio + manifold3d). The test
runs the real production ``generate_segmented_glb`` once per kernel against
a small synthetic cache (the same shape used by
``TestContourExtrusionSizeRegression``) and compares:

* node name set including ``backing_plate``
* per-color mesh ``volume`` (relative diff <= 0.5 %)
* per-color mesh world-space AABB extent on each axis (relative diff <= 0.1 %)
* GLB file is loadable and re-exportable through trimesh

Feature: glb-preview-mesh-kernel-optimization (v2)
"""

from __future__ import annotations

import copy
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


def _build_synthetic_cache(seed: int = 7) -> dict:
    """Small 6-color image that exercises the per-color mesh loop."""
    rng = np.random.default_rng(seed)
    H, W = 64, 64
    matched_rgb = np.zeros((H, W, 3), dtype=np.uint8)
    palette = np.array(
        [
            [200, 30, 30],
            [30, 200, 30],
            [30, 30, 200],
            [200, 200, 30],
            [200, 30, 200],
            [30, 200, 200],
        ],
        dtype=np.uint8,
    )
    # Stripe the canvas with random palette indices so each color gets a
    # connected blob plus a few isolated pixels.
    block = 8
    for y in range(0, H, block):
        for x in range(0, W, block):
            color_idx = int(rng.integers(0, len(palette)))
            matched_rgb[y : y + block, x : x + block] = palette[color_idx]
    # Sprinkle a few isolated pixels to test 1-px features.
    for _ in range(40):
        y = int(rng.integers(0, H))
        x = int(rng.integers(0, W))
        matched_rgb[y, x] = palette[int(rng.integers(0, len(palette)))]
    mask_solid = np.ones((H, W), dtype=bool)
    return {
        "matched_rgb": matched_rgb,
        "mask_solid": mask_solid,
        "target_w": W,
        "target_h": H,
        "target_width_mm": 100.0,
    }


@_skip_no_v2
def test_dual_kernel_equivalence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.pipeline.s11_glb_preview import generate_segmented_glb
    from core.pipeline import s11_glb_preview as s11

    # Reset the import cache between modes so each call resolves freshly.
    monkeypatch.setattr(s11, "_V2_IMPORT_OK", None, raising=True)
    monkeypatch.setattr(s11, "_V2_IMPORT_ERROR", None, raising=True)

    cache_template = _build_synthetic_cache()

    def _run(kernel: str) -> tuple[Path, dict]:
        monkeypatch.setenv("LUMINA_GLB_KERNEL", kernel)
        local_cache = copy.deepcopy(cache_template)
        out = tmp_path / f"dual_{kernel}.glb"
        path = generate_segmented_glb(local_cache, str(out))
        assert path is not None and Path(path).exists(), (
            f"generate_segmented_glb returned no path for {kernel}"
        )
        return Path(path), local_cache

    glb_v1, cache_v1 = _run("shapely_v1")
    glb_v2, cache_v2 = _run("v2")

    scene_v1 = trimesh.load(glb_v1, force="scene")
    scene_v2 = trimesh.load(glb_v2, force="scene")

    # After GLB round-trip, ``scene.geometry`` is keyed by anonymized
    # ``geometry_N`` ids; the *node* names ``color_<hex>`` /
    # ``backing_plate`` survive on ``scene.graph.nodes``. Build a
    # node_name -> Trimesh map from graph edges to make them comparable.
    def _named_meshes(scene: trimesh.Scene) -> dict[str, trimesh.Trimesh]:
        out: dict[str, trimesh.Trimesh] = {}
        for node in scene.graph.nodes:
            if node == "world":
                continue
            try:
                _transform, geom_name = scene.graph[node]
            except Exception:  # noqa: BLE001 — leaf nodes without geom
                continue
            if geom_name is None:
                continue
            geom = scene.geometry.get(geom_name)
            if geom is None:
                continue
            out[node] = geom
        return out

    meshes_v1 = _named_meshes(scene_v1)
    meshes_v2 = _named_meshes(scene_v2)

    names_v1 = set(meshes_v1.keys())
    names_v2 = set(meshes_v2.keys())
    assert names_v1 == names_v2, (
        f"node sets differ\n  only_in_v1={names_v1 - names_v2}\n"
        f"  only_in_v2={names_v2 - names_v1}"
    )
    assert "backing_plate" in names_v1
    color_nodes = {n for n in names_v1 if n.startswith("color_")}
    assert color_nodes, "scene must have at least one color_<hex> node"

    # color_<hex> regex
    import re
    color_re = re.compile(r"^color_[0-9a-f]{6}$")
    for name in color_nodes:
        assert color_re.match(name), f"bad node name: {name!r}"

    # Per-mesh volume + AABB equivalence.
    for name in names_v1:
        m1 = meshes_v1[name]
        m2 = meshes_v2[name]
        # Volume tolerance
        v1, v2 = float(m1.volume), float(m2.volume)
        denom = max(abs(v1), abs(v2), 1e-9)
        rel_vol_diff = abs(v1 - v2) / denom
        assert rel_vol_diff <= 0.005, (
            f"{name}: volume v1={v1} v2={v2} rel_diff={rel_vol_diff:.4%}"
        )
        # AABB extent per axis
        b1 = m1.bounds  # (2, 3)
        b2 = m2.bounds
        for axis, label in enumerate("xyz"):
            ext1 = float(b1[1, axis] - b1[0, axis])
            ext2 = float(b2[1, axis] - b2[0, axis])
            denom = max(abs(ext1), abs(ext2), 1e-9)
            rel_ext_diff = abs(ext1 - ext2) / denom
            assert rel_ext_diff <= 0.001, (
                f"{name}: {label}-extent v1={ext1} v2={ext2} rel_diff={rel_ext_diff:.4%}"
            )

    # GLB must round-trip through trimesh export (R3 / R9.2).
    re_glb_v1 = scene_v1.export(file_type="glb")
    re_glb_v2 = scene_v2.export(file_type="glb")
    assert re_glb_v1 and len(re_glb_v1) > 0
    assert re_glb_v2 and len(re_glb_v2) > 0

    # color_contours hex set must equal node hex set for both runs.
    contour_keys_v1 = set((cache_v1.get("color_contours") or {}).keys())
    contour_keys_v2 = set((cache_v2.get("color_contours") or {}).keys())
    expected_hex = {n[len("color_"):] for n in color_nodes}
    assert contour_keys_v1 == expected_hex, (
        f"v1 color_contours keys mismatch: contours={contour_keys_v1} expected={expected_hex}"
    )
    assert contour_keys_v2 == expected_hex, (
        f"v2 color_contours keys mismatch: contours={contour_keys_v2} expected={expected_hex}"
    )
    # And v1 / v2 keys equal each other (R3.5 cv2.findContours independent of kernel).
    assert contour_keys_v1 == contour_keys_v2
