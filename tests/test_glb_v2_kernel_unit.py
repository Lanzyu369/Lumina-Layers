"""V2 mesh kernel unit tests for ``core/pipeline/s11_glb_preview.py``.

Two independent test groups live here:

* ``v2_helper`` — exercises ``_build_color_extruded_mesh_v2`` directly. These
  tests SKIP when the optional dependencies (``rasterio.features``,
  ``manifold3d``) are missing because they cannot be exercised without the
  real native code. They cover the geometric contracts: empty mask, single
  pixel, 1-px strip, hole, saddle / diagonal touch, RGBA face color.
* ``dispatcher_fallback`` — exercises ``_build_color_extruded_mesh`` through
  the dispatcher with monkeypatched flags. These ALWAYS run, even when v2
  deps are missing, because the dispatcher itself is pure Python and the
  fallback path it guards is the most important contract of this PR.

Feature: glb-preview-mesh-kernel-optimization (v2)
"""

from __future__ import annotations

import importlib.util
import json
import struct
from pathlib import Path

import numpy as np
import pytest
import trimesh

from core.pipeline import s11_glb_preview as s11


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _v2_deps_present() -> bool:
    """Return True iff both ``rasterio.features`` and ``manifold3d`` import.

    Uses ``importlib.util.find_spec`` which does NOT execute module code, so
    we don't trigger any rasterio-on-import side effects (e.g. GDAL banner).
    """
    return bool(
        importlib.util.find_spec("rasterio.features")
        and importlib.util.find_spec("manifold3d")
    )


_V2_PRESENT = _v2_deps_present()
_skip_no_v2 = pytest.mark.skipif(
    not _V2_PRESENT,
    reason="optional v2 deps (rasterio + manifold3d) not installed in this venv",
)

_RGBA = np.array([255, 0, 0, 255], dtype=np.uint8)
_RGBA_GREEN = np.array([0, 255, 128, 200], dtype=np.uint8)


def _load_glb_json(path: Path) -> dict:
    data = path.read_bytes()
    assert data[:4] == b"glTF"
    json_length, json_type = struct.unpack_from("<II", data, 12)
    assert json_type == 0x4E4F534A
    return json.loads(data[20 : 20 + json_length].decode("utf-8"))


@pytest.fixture
def s11_caplog(caplog):
    """Attach caplog.handler to the s11 structured logger.

    The lumina structured loggers have ``propagate=False`` (see
    ``api/structured_logging.py`` ``configure_structured_logging``), so
    pytest's default root caplog never sees their records. Tests that need
    to assert on ``event=...`` extras MUST hook the named logger directly.
    """
    import logging as _logging

    target = _logging.getLogger("lumina.core.pipeline.s11_glb_preview")
    target.addHandler(caplog.handler)
    caplog.set_level(_logging.WARNING, logger=target.name)
    try:
        yield caplog
    finally:
        target.removeHandler(caplog.handler)


@pytest.fixture(autouse=True)
def _reset_v2_import_cache(monkeypatch):
    """Ensure each test starts with a fresh ``_v2_available()`` cache.

    Tests that monkeypatch ``_V2_IMPORT_OK`` to simulate a missing wheel
    must not leak that state into siblings. Also resets
    ``_V2_REQUESTED_UNAVAILABLE_LOGGED`` so the dispatcher's
    once-per-process WARNING latch does not bleed across tests (added
    after PR #210 follow-up that introduced the latch).
    """
    monkeypatch.setattr(s11, "_V2_IMPORT_OK", None, raising=True)
    monkeypatch.setattr(s11, "_V2_IMPORT_ERROR", None, raising=True)
    monkeypatch.setattr(s11, "_V2_REQUESTED_UNAVAILABLE_LOGGED", False, raising=True)
    yield


@pytest.fixture(autouse=True)
def _clear_kernel_env(monkeypatch):
    """Default to 'unset' so each test picks its mode explicitly."""
    monkeypatch.delenv("LUMINA_GLB_KERNEL", raising=False)
    yield


# ---------------------------------------------------------------------------
# Group A: v2 helper geometric contracts (skip if deps missing)
# ---------------------------------------------------------------------------


@_skip_no_v2
def test_v2_empty_mask_returns_none():
    """All-False mask must return None and not raise (R6.4)."""
    mask = np.zeros((8, 12), dtype=bool)
    out = s11._build_color_extruded_mesh_v2(mask, height=8, total_layers=3, rgba=_RGBA)
    assert out is None


@_skip_no_v2
def test_v2_single_pixel_emits_extrusion():
    """Isolated single True pixel produces an extruded box (R6.3)."""
    mask = np.zeros((10, 10), dtype=bool)
    mask[5, 5] = True
    mesh = s11._build_color_extruded_mesh_v2(mask, height=10, total_layers=3, rgba=_RGBA)
    assert mesh is not None
    assert len(mesh.vertices) >= 8
    assert len(mesh.faces) >= 12
    # Volume in pixel-space units: count_nonzero(=1) * total_layers(=3).
    expected = float(mask.sum() * 3)
    assert mesh.volume == pytest.approx(expected, rel=1e-6)


@_skip_no_v2
def test_v2_thin_1px_strip_preserved():
    """1-px strip must keep face_count >= 1 and exact area (R6.1, R11.2)."""
    mask = np.zeros((10, 30), dtype=bool)
    mask[5, 2:25] = True  # 23 px long, 1 px tall
    mesh = s11._build_color_extruded_mesh_v2(mask, height=10, total_layers=3, rgba=_RGBA)
    assert mesh is not None
    assert len(mesh.faces) >= 1
    expected_volume = float(mask.sum() * 3)
    assert mesh.volume == pytest.approx(expected_volume, rel=1e-6)


@_skip_no_v2
def test_v2_interior_hole_preserved():
    """Interior 4-connectivity hole must remain unfilled (R6.2, R11.3)."""
    mask = np.zeros((20, 20), dtype=bool)
    mask[2:18, 2:18] = True  # 16x16 outer block
    mask[8:12, 8:12] = False  # 4x4 hole
    mesh = s11._build_color_extruded_mesh_v2(mask, height=20, total_layers=3, rgba=_RGBA)
    assert mesh is not None
    expected_volume = float(mask.sum() * 3)  # outer minus hole already in mask.sum()
    assert mesh.volume == pytest.approx(expected_volume, rel=1e-6)


@_skip_no_v2
def test_v2_saddle_diagonal_touch_does_not_collapse():
    """Diagonally-touching pixels stay separate (rasterio connectivity=4)."""
    mask = np.zeros((6, 6), dtype=bool)
    mask[1, 1] = True
    mask[2, 2] = True  # touches mask[1,1] only at the corner
    mesh = s11._build_color_extruded_mesh_v2(mask, height=6, total_layers=2, rgba=_RGBA)
    assert mesh is not None
    expected_volume = 2 * 2  # 2 pixels x 2 layers
    assert mesh.volume == pytest.approx(expected_volume, rel=1e-6)


@_skip_no_v2
def test_v2_face_colors_match_rgba_input():
    """Every face SHALL be stamped with the input rgba (R3.3)."""
    mask = np.zeros((6, 6), dtype=bool)
    mask[2:4, 2:4] = True
    mesh = s11._build_color_extruded_mesh_v2(mask, height=6, total_layers=2, rgba=_RGBA_GREEN)
    assert mesh is not None
    expected = np.tile(_RGBA_GREEN, (len(mesh.faces), 1))
    assert np.array_equal(mesh.visual.face_colors, expected)


@_skip_no_v2
def test_v2_can_skip_face_colors_for_material_only_export():
    """Material-only exporters can avoid allocating per-face preview colors."""
    mask = np.zeros((6, 6), dtype=bool)
    mask[2:4, 2:4] = True
    mesh = s11._build_color_extruded_mesh_v2(
        mask,
        height=6,
        total_layers=2,
        rgba=_RGBA_GREEN,
        assign_face_colors=False,
    )
    assert mesh is not None
    assert mesh.visual.kind is None
    assert not mesh.visual.defined


@_skip_no_v2
def test_v2_mesh_builder_caches_optional_imports(monkeypatch):
    """Repeated v2 mesh builds should not re-enter import machinery."""
    import builtins as _builtins

    s11._get_v2_mesh_kernel_modules.cache_clear()
    original_import = _builtins.__import__
    import_counts = {"rasterio.features": 0, "manifold3d": 0}

    def counted_import(name, *args, **kwargs):
        if name in import_counts:
            import_counts[name] += 1
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(_builtins, "__import__", counted_import)

    mask = np.zeros((6, 6), dtype=bool)
    mask[2:4, 2:4] = True
    first = s11._build_color_extruded_mesh_v2(mask, height=6, total_layers=2, rgba=_RGBA)
    second = s11._build_color_extruded_mesh_v2(mask, height=6, total_layers=2, rgba=_RGBA)

    assert first is not None
    assert second is not None
    assert import_counts == {"rasterio.features": 1, "manifold3d": 1}


@_skip_no_v2
def test_v2_multiple_components_extrude_once_after_cross_section_compose(
    monkeypatch,
):
    """Disjoint components should compose in 2D, then extrude once.

    This keeps geometry semantics unchanged while avoiding one native
    ``CrossSection.extrude`` call per connected component on fragmented masks.
    """
    import manifold3d as m3d  # type: ignore

    mask = np.zeros((24, 24), dtype=bool)
    mask[2:6, 2:6] = True
    mask[2:6, 12:16] = True
    mask[14:18, 8:12] = True
    real_extrude = m3d.CrossSection.extrude
    call_count = {"n": 0}

    def counted_extrude(self, *args, **kwargs):
        call_count["n"] += 1
        return real_extrude(self, *args, **kwargs)

    monkeypatch.setattr(m3d.CrossSection, "extrude", counted_extrude)

    mesh = s11._build_color_extruded_mesh_v2(
        mask, height=24, total_layers=5, rgba=_RGBA
    )

    assert mesh is not None
    assert mesh.volume == pytest.approx(float(mask.sum() * 5), rel=1e-6)
    assert call_count["n"] == 1


@_skip_no_v2
def test_v2_multiple_components_can_compose_in_chunks(monkeypatch) -> None:
    import manifold3d as m3d  # type: ignore

    mask = np.zeros((24, 24), dtype=bool)
    mask[2:6, 2:6] = True
    mask[2:6, 12:16] = True
    mask[14:18, 8:12] = True
    real_extrude = m3d.CrossSection.extrude
    call_count = {"n": 0}

    def counted_extrude(self, *args, **kwargs):
        call_count["n"] += 1
        return real_extrude(self, *args, **kwargs)

    monkeypatch.setattr(m3d.CrossSection, "extrude", counted_extrude)

    mesh = s11._build_color_extruded_mesh_v2(
        mask,
        height=24,
        total_layers=5,
        rgba=_RGBA,
        component_compose_chunk_size=2,
    )

    assert mesh is not None
    assert mesh.volume == pytest.approx(float(mask.sum() * 5), rel=1e-6)
    assert call_count["n"] == 2


def test_v2_segmented_glb_postprocessor_sorts_triangle_indices_for_gzip() -> None:
    original = np.asarray(
        [
            [5, 4, 3],
            [0, 2, 1],
            [2, 3, 0],
        ],
        dtype="<u2",
    )
    buffer_items = {0: original.reshape(-1).tobytes()}
    tree = {
        "accessors": {
            0: {
                "componentType": s11._GLTF_UINT16_COMPONENT_TYPE,
                "count": int(original.size),
                "bufferView": 0,
                "type": "SCALAR",
            }
        },
        "meshes": [
            {
                "primitives": [
                    {
                        "indices": 0,
                        "mode": 4,
                    }
                ]
            }
        ],
    }

    s11._sort_triangle_index_buffers_for_gzip(buffer_items, tree)

    sorted_indices = np.frombuffer(buffer_items[0], dtype="<u2").reshape((-1, 3))
    expected = np.asarray(
        [
            [0, 2, 1],
            [2, 3, 0],
            [5, 4, 3],
        ],
        dtype=np.uint16,
    )
    np.testing.assert_array_equal(sorted_indices, expected)
    assert {tuple(row) for row in sorted_indices.tolist()} == {
        tuple(row) for row in original.tolist()
    }


def test_v2_spatial_vertex_sort_preserves_mesh_geometry() -> None:
    vertices = np.asarray(
        [
            [2.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [1.0, 0.0, 0.0],
        ],
        dtype=np.float64,
    )
    faces = np.asarray([[0, 2, 3], [1, 3, 2]], dtype=np.int64)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)

    sorted_mesh = s11._sort_mesh_vertices_spatially_for_gzip(mesh)

    expected_order = np.asarray([1, 3, 2, 0], dtype=np.int64)
    np.testing.assert_allclose(sorted_mesh.vertices, vertices[expected_order])
    assert {tuple(row) for row in sorted_mesh.faces.tolist()} == {
        (3, 2, 1),
        (0, 1, 2),
    }
    np.testing.assert_allclose(sorted_mesh.bounds, mesh.bounds)


@_skip_no_v2
def test_v2_segmented_glb_uses_material_color_without_color_attribute(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LUMINA_GLB_KERNEL", "v2")
    matched_rgb = np.zeros((6, 6, 3), dtype=np.uint8)
    matched_rgb[1:5, 1:5] = np.array([255, 0, 0], dtype=np.uint8)
    mask_solid = np.zeros((6, 6), dtype=bool)
    mask_solid[1:5, 1:5] = True
    cache = {
        "matched_rgb": matched_rgb,
        "mask_solid": mask_solid,
        "target_w": 6,
        "target_h": 6,
        "target_width_mm": 6.0,
    }

    out_path = tmp_path / "segmented-v2.glb"
    result = s11.generate_segmented_glb(cache, output_path=str(out_path))

    assert result == str(out_path)
    gltf = _load_glb_json(out_path)
    color_node = next(
        node for node in gltf["nodes"] if str(node.get("name", "")).startswith("color_ff0000")
    )
    color_mesh = gltf["meshes"][color_node["mesh"]]
    primitive = color_mesh["primitives"][0]
    assert "COLOR_0" not in primitive["attributes"]
    material = gltf["materials"][primitive["material"]]
    assert material["pbrMetallicRoughness"]["baseColorFactor"] == [
        1.0,
        0.0,
        0.0,
        1.0,
    ]


@_skip_no_v2
def test_v2_invalid_mask_shape_returns_none():
    """1-D or 3-D mask is unsupported and must return None, not raise."""
    bad = np.zeros((3, 3, 3), dtype=bool)
    assert s11._build_color_extruded_mesh_v2(bad, height=3, total_layers=2, rgba=_RGBA) is None


@_skip_no_v2
def test_v2_volume_matches_v1_on_complex_mask():
    """v2 and v1 must agree on volume for an adversarial mask (R7.2 / R11.8 spirit)."""
    mask = np.zeros((24, 24), dtype=bool)
    mask[2:20, 2:20] = True
    mask[10:14, 10:14] = False  # hole
    mask[3, 21:23] = True  # short 1-px strip
    mask[21, 5] = True  # isolated pixel
    mesh_v1 = s11._build_color_extruded_mesh_shapely_v1(
        mask, height=24, total_layers=4, rgba=_RGBA
    )
    mesh_v2 = s11._build_color_extruded_mesh_v2(
        mask, height=24, total_layers=4, rgba=_RGBA
    )
    assert mesh_v1 is not None and mesh_v2 is not None
    assert mesh_v1.volume == pytest.approx(mesh_v2.volume, rel=1e-6)


def test_v2_atomic_per_component_failure_aborts_color(
    monkeypatch, s11_caplog
):
    """Atomicity contract: any per-component CrossSection.extrude failure
    aborts the whole color and returns None; dispatcher must then fall back
    to v1 producing the FULL mesh (volume / XY parity with v1, no partial
    geometry leak).

    Mask has 3 disjoint blocks => 3 components in rasterio.features.shapes.
    We monkeypatch ``manifold3d.CrossSection.extrude`` to fail on the
    second call, simulating a single mid-loop component failure.
    """
    if not _V2_PRESENT:
        pytest.skip("optional v2 deps not installed")

    import manifold3d as m3d  # type: ignore

    # 3 disjoint 4x4 blocks -> rasterio shapes returns 3 components.
    mask = np.zeros((24, 24), dtype=bool)
    mask[2:6, 2:6] = True
    mask[2:6, 12:16] = True
    mask[14:18, 8:12] = True
    height = 24
    total_layers = 5

    # Direct v2 helper call: ensure it returns None when a mid-component
    # extrude raises.
    monkeypatch.setattr(s11, "_V2_IMPORT_OK", True)
    real_extrude = m3d.CrossSection.extrude
    monkeypatch.setattr(
        m3d.CrossSection,
        "compose",
        lambda _sections: (_ for _ in ()).throw(
            RuntimeError("simulated fast compose failure")
        ),
    )
    call_count = {"n": 0}

    def _flaky_extrude(self, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated manifold3d extrude failure")
        return real_extrude(self, *args, **kwargs)

    monkeypatch.setattr(m3d.CrossSection, "extrude", _flaky_extrude)

    direct = s11._build_color_extruded_mesh_v2(
        mask, height=height, total_layers=total_layers, rgba=_RGBA
    )
    assert direct is None, "v2 must return None when any component fails"

    # The aggregate WARNING must be emitted with actionable fields.
    matching = [
        rec for rec in s11_caplog.records
        if getattr(rec, "event", None) == "glb_kernel_v2_no_manifolds"
    ]
    assert matching, "expected glb_kernel_v2_no_manifolds WARNING"
    rec = matching[0]
    assert getattr(rec, "components", None) == 3
    assert getattr(rec, "failed_component_index", None) == 1  # 0-indexed: 2nd call
    assert getattr(rec, "error_type", None) == "RuntimeError"
    assert getattr(rec, "fallback_kernel", None) == "shapely_v1"

    # Now reset call_count and verify the dispatcher falls back to v1
    # producing a FULL mesh. Use a fresh caplog list for clarity.
    call_count["n"] = 0
    s11_caplog.records.clear()
    monkeypatch.setenv("LUMINA_GLB_KERNEL", "v2")
    fallback_mesh = s11._build_color_extruded_mesh(
        mask, height=height, total_layers=total_layers, rgba=_RGBA
    )
    assert fallback_mesh is not None, "dispatcher must fall back to v1"

    # v1 fallback volume must equal the full ground-truth volume; v2's
    # partial accumulation MUST NOT have leaked through.
    expected_volume = float(mask.sum() * total_layers)
    assert fallback_mesh.volume == pytest.approx(expected_volume, rel=1e-6), (
        f"fallback volume {fallback_mesh.volume} != expected {expected_volume}"
    )

    # Both events must have fired: glb_kernel_v2_no_manifolds (helper)
    # then glb_kernel_v2_runtime_fallback (dispatcher).
    events = [getattr(rec, "event", None) for rec in s11_caplog.records]
    assert "glb_kernel_v2_no_manifolds" in events
    assert "glb_kernel_v2_runtime_fallback" in events


# ---------------------------------------------------------------------------
# Group B: dispatcher + feature flag (no v2 deps required to run)
# ---------------------------------------------------------------------------


def _simple_mask():
    mask = np.zeros((8, 8), dtype=bool)
    mask[2:6, 2:6] = True
    return mask


def test_default_unset_resolves_to_v2(monkeypatch):
    """Empty env -> v2 path; v2 is the preview-performance baseline."""
    monkeypatch.delenv("LUMINA_GLB_KERNEL", raising=False)
    assert s11._resolve_kernel_choice() == "rasterio_manifold3d"


def test_default_unset_uses_v2_when_available(monkeypatch):
    """Default v2 mode should call the v2 builder when deps are available."""
    monkeypatch.delenv("LUMINA_GLB_KERNEL", raising=False)
    monkeypatch.setattr(s11, "_V2_IMPORT_OK", True)
    calls = {"v2": 0}

    def fake_v2(mask, height, total_layers, rgba, **_kwargs):
        calls["v2"] += 1
        mesh = trimesh.creation.box(extents=(1.0, 1.0, float(total_layers)))
        mesh.visual.face_colors = np.tile(rgba, (len(mesh.faces), 1))
        return mesh

    monkeypatch.setattr(s11, "_build_color_extruded_mesh_v2", fake_v2)

    mesh = s11._build_color_extruded_mesh(
        _simple_mask(), height=8, total_layers=3, rgba=_RGBA
    )

    assert mesh is not None
    assert calls["v2"] == 1


def test_v1_alias_resolves_to_shapely_v1(monkeypatch):
    for value in ("v1", "shapely", "shapely_v1", "  V1  ", "Shapely"):
        monkeypatch.setenv("LUMINA_GLB_KERNEL", value)
        assert s11._resolve_kernel_choice() == "shapely_v1", f"failed for {value!r}"


def test_v2_alias_resolves_to_rasterio_manifold3d(monkeypatch):
    for value in ("v2", "V2", "rasterio_manifold3d", "rasterio+manifold3d"):
        monkeypatch.setenv("LUMINA_GLB_KERNEL", value)
        assert s11._resolve_kernel_choice() == "rasterio_manifold3d", f"failed for {value!r}"


def test_auto_resolves_to_auto(monkeypatch):
    for value in ("auto", "AUTO", " Auto "):
        monkeypatch.setenv("LUMINA_GLB_KERNEL", value)
        assert s11._resolve_kernel_choice() == "auto", f"failed for {value!r}"


def test_unknown_value_logs_warning_and_falls_back(monkeypatch, s11_caplog):
    monkeypatch.setenv("LUMINA_GLB_KERNEL", "bogus")
    assert s11._resolve_kernel_choice() == "shapely_v1"
    events = [getattr(rec, "event", None) for rec in s11_caplog.records]
    assert "glb_kernel_unknown_value" in events


def test_dispatcher_v2_unavailable_warns_and_falls_back(monkeypatch, s11_caplog):
    """LUMINA_GLB_KERNEL=v2 with missing deps SHALL fall back AND warn."""
    monkeypatch.setenv("LUMINA_GLB_KERNEL", "v2")
    monkeypatch.setattr(s11, "_V2_IMPORT_OK", False)
    monkeypatch.setattr(s11, "_V2_IMPORT_ERROR", "ModuleNotFoundError: rasterio")

    mesh = s11._build_color_extruded_mesh(_simple_mask(), height=8, total_layers=3, rgba=_RGBA)
    assert mesh is not None  # fell back to v1
    events = [getattr(rec, "event", None) for rec in s11_caplog.records]
    assert "glb_kernel_v2_requested_unavailable" in events
    # Actionable fields per AGENTS.md Logging Governance.
    matching = [
        rec for rec in s11_caplog.records
        if getattr(rec, "event", None) == "glb_kernel_v2_requested_unavailable"
    ]
    assert getattr(matching[0], "import_error", None)


def test_dispatcher_v2_unavailable_warning_latched_to_once_per_process(
    monkeypatch, s11_caplog,
):
    """``glb_kernel_v2_requested_unavailable`` MUST fire at most once per
    process. Without this latch, ``generate_segmented_glb`` would emit one
    copy of this WARNING per colour (40-60 colours per preview + 1 backing
    plate = ~50 identical WARNINGs), drowning legitimate diagnostic signal
    on Windows arm64 / older-glibc Linux where v2 wheels are missing.

    Reviewer feedback on PR #210 caught this; this regression nails the
    semantic so the latch cannot silently regress.
    """
    monkeypatch.setenv("LUMINA_GLB_KERNEL", "v2")
    monkeypatch.setattr(s11, "_V2_IMPORT_OK", False)
    monkeypatch.setattr(s11, "_V2_IMPORT_ERROR", "ModuleNotFoundError: rasterio")

    # Simulate a 50-colour preview by calling the dispatcher 50 times with
    # different masks. Each call would, pre-latch, emit the WARNING.
    for _ in range(50):
        mesh = s11._build_color_extruded_mesh(
            _simple_mask(), height=8, total_layers=3, rgba=_RGBA,
        )
        assert mesh is not None  # v1 fallback succeeded every time

    requested_unavailable = [
        rec for rec in s11_caplog.records
        if getattr(rec, "event", None) == "glb_kernel_v2_requested_unavailable"
    ]
    assert len(requested_unavailable) == 1, (
        f"Expected exactly 1 glb_kernel_v2_requested_unavailable WARNING across "
        f"50 dispatcher calls, got {len(requested_unavailable)}. The latch "
        f"_V2_REQUESTED_UNAVAILABLE_LOGGED was not reset / honoured."
    )
    # Latch should also be observably True after the first emission.
    assert s11._V2_REQUESTED_UNAVAILABLE_LOGGED is True


def test_dispatcher_auto_unavailable_silent_fallback(monkeypatch, s11_caplog):
    """LUMINA_GLB_KERNEL=auto with missing deps SHALL fall back SILENTLY.

    Hard stop: this is one of the four blockers — auto must NOT emit
    glb_kernel_v2_unavailable nor glb_kernel_v2_requested_unavailable.
    """
    monkeypatch.setenv("LUMINA_GLB_KERNEL", "auto")
    monkeypatch.setattr(s11, "_V2_IMPORT_OK", None)  # force a real probe
    monkeypatch.setattr(s11, "_V2_IMPORT_ERROR", None)

    # Simulate import failure by sabotaging __import__ so any internal
    # ``import rasterio.features`` or ``import manifold3d`` raises.
    import sys
    import builtins as _builtins

    _orig_import = _builtins.__import__

    def _force_import_fail(name, *args, **kwargs):
        if name in {"rasterio", "rasterio.features", "manifold3d"}:
            raise ModuleNotFoundError(f"forced: {name}")
        return _orig_import(name, *args, **kwargs)

    monkeypatch.setattr(_builtins, "__import__", _force_import_fail)
    # Ensure cached modules don't short-circuit __import__
    for name in ("rasterio", "rasterio.features", "manifold3d"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    mesh = s11._build_color_extruded_mesh(_simple_mask(), height=8, total_layers=3, rgba=_RGBA)
    assert mesh is not None  # fell back to v1
    events = [getattr(rec, "event", None) for rec in s11_caplog.records]
    assert "glb_kernel_v2_unavailable" not in events, (
        f"auto path leaked WARNING; events={events}"
    )
    assert "glb_kernel_v2_requested_unavailable" not in events, (
        f"auto path leaked WARNING; events={events}"
    )


def test_dispatcher_v2_runtime_returns_none_falls_back_with_warning(monkeypatch, s11_caplog):
    """v2 returning None on a non-empty mask -> WARNING + v1 fallback."""
    monkeypatch.setenv("LUMINA_GLB_KERNEL", "v2")
    monkeypatch.setattr(s11, "_V2_IMPORT_OK", True)
    monkeypatch.setattr(
        s11, "_build_color_extruded_mesh_v2",
        lambda mask, height, total_layers, rgba, **_kwargs: None,
    )

    mesh = s11._build_color_extruded_mesh(_simple_mask(), height=8, total_layers=3, rgba=_RGBA)
    assert mesh is not None  # v1 fallback succeeded
    events = [getattr(rec, "event", None) for rec in s11_caplog.records]
    assert "glb_kernel_v2_runtime_fallback" in events


def test_dispatcher_v2_returns_none_on_empty_does_not_fallback(monkeypatch, s11_caplog):
    """Empty mask + v2 None must NOT trigger fallback (no infinite loop)."""
    monkeypatch.setenv("LUMINA_GLB_KERNEL", "v2")
    monkeypatch.setattr(s11, "_V2_IMPORT_OK", True)
    monkeypatch.setattr(
        s11, "_build_color_extruded_mesh_v2",
        lambda mask, height, total_layers, rgba, **_kwargs: None,
    )

    empty = np.zeros((8, 8), dtype=bool)
    mesh = s11._build_color_extruded_mesh(empty, height=8, total_layers=3, rgba=_RGBA)
    assert mesh is None
    events = [getattr(rec, "event", None) for rec in s11_caplog.records]
    assert "glb_kernel_v2_runtime_fallback" not in events


def test_v2_available_silent_does_not_warn_on_failure(monkeypatch, s11_caplog):
    """log_warning=False suppresses glb_kernel_v2_unavailable WARNING."""
    monkeypatch.setattr(s11, "_V2_IMPORT_OK", None)
    monkeypatch.setattr(s11, "_V2_IMPORT_ERROR", None)

    import sys
    import builtins as _builtins

    _orig_import = _builtins.__import__

    def _force_fail(name, *args, **kwargs):
        if name in {"rasterio", "rasterio.features", "manifold3d"}:
            raise ImportError(f"forced: {name}")
        return _orig_import(name, *args, **kwargs)

    monkeypatch.setattr(_builtins, "__import__", _force_fail)
    for name in ("rasterio", "rasterio.features", "manifold3d"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    assert s11._v2_available(log_warning=False) is False
    events = [getattr(rec, "event", None) for rec in s11_caplog.records]
    assert "glb_kernel_v2_unavailable" not in events


def test_v2_available_default_does_warn_on_failure(monkeypatch, s11_caplog):
    """log_warning=True (default) emits the structured WARNING with actionable fields."""
    monkeypatch.setattr(s11, "_V2_IMPORT_OK", None)
    monkeypatch.setattr(s11, "_V2_IMPORT_ERROR", None)

    import sys
    import builtins as _builtins

    _orig_import = _builtins.__import__

    def _force_fail(name, *args, **kwargs):
        if name in {"rasterio", "rasterio.features", "manifold3d"}:
            raise ImportError(f"forced: {name}")
        return _orig_import(name, *args, **kwargs)

    monkeypatch.setattr(_builtins, "__import__", _force_fail)
    for name in ("rasterio", "rasterio.features", "manifold3d"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    assert s11._v2_available() is False
    matching = [
        rec for rec in s11_caplog.records
        if getattr(rec, "event", None) == "glb_kernel_v2_unavailable"
    ]
    assert matching, "expected glb_kernel_v2_unavailable WARNING"
    rec = matching[0]
    # Actionable fields per AGENTS.md Logging Governance.
    assert getattr(rec, "error_type", None)
    assert getattr(rec, "error_message", None)
