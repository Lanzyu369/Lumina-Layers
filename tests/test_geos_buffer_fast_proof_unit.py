"""Unit tests for the lossless dense-buffer proof harness."""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import MultiPolygon, Polygon


class _FakeBufferBackend:
    def __init__(self, result_wkb: bytes) -> None:
        self.result_wkb = result_wkb
        self.calls: list[tuple[bytes, object]] = []

    def buffer_wkb(self, input_wkb: bytes, settings: object) -> bytes:
        self.calls.append((input_wkb, settings))
        return self.result_wkb


class _Readings:
    def __init__(self, values: list[float | int]) -> None:
        self._values = iter(values)

    def __call__(self) -> float | int:
        return next(self._values)


def test_geometry_fingerprint_tracks_product_semantics() -> None:
    from scripts.profile_geos_buffer_fast_proof import geometry_fingerprint

    geometry = MultiPolygon(
        [
            Polygon(
                [(0, 0), (4, 0), (4, 4), (0, 4)],
                holes=[[(1, 1), (2, 1), (2, 2), (1, 2)]],
            ),
            Polygon([(10, 0), (12, 0), (12, 2), (10, 2)]),
        ]
    )

    result = geometry_fingerprint(geometry)

    assert result["valid"] is True
    assert result["geom_type"] == "MultiPolygon"
    assert result["components"] == 2
    assert result["holes"] == 1
    assert result["area"] == 19.0
    assert result["bounds"] == [0.0, 0.0, 12.0, 4.0]
    assert len(result["normalized_wkb_sha256"]) == 64


def test_compare_geometry_rejects_equal_area_with_changed_region() -> None:
    from scripts.profile_geos_buffer_fast_proof import compare_geometry

    stock = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    shifted = Polygon([(1, 0), (3, 0), (3, 2), (1, 2)])

    result = compare_geometry(stock, shifted)

    assert result["pass"] is False
    assert result["symmetric_difference_empty"] is False
    assert result["symmetric_difference_area"] == 4.0


def test_compare_geometry_accepts_component_order_only_difference() -> None:
    from scripts.profile_geos_buffer_fast_proof import compare_geometry

    first = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    second = Polygon([(4, 0), (6, 0), (6, 2), (4, 2)])
    stock = MultiPolygon([first, second])
    reordered = MultiPolygon([second, first])

    result = compare_geometry(stock, reordered)

    assert result["pass"] is True
    assert result["symmetric_difference_empty"] is True


def test_proof_builder_is_pinned_and_scratch_only() -> None:
    from scripts.build_geos_buffer_fast_proof import (
        GEOS_COMMIT,
        GEOS_REF,
        GEOS_REPOSITORY,
        PATCH_PATH,
        PROOF_ROOT,
        ROOT,
    )

    assert GEOS_REF == "3.13.1"
    assert GEOS_COMMIT == "431568d6e311e0bbfb057b4ec3d44d0d3ba3335f"
    assert GEOS_REPOSITORY == "https://github.com/libgeos/geos.git"
    assert PROOF_ROOT == ROOT / ".scratch" / "geos_buffer_fast_proof"
    assert PATCH_PATH == (
        ROOT
        / "native"
        / "geos_buffer_fast"
        / "patches"
        / "geos-3.13.1-buffer-subgraph-index.patch"
    )


def test_proof_builder_commands_are_argument_lists() -> None:
    from scripts.build_geos_buffer_fast_proof import (
        BUILD_ROOT,
        GEOS_REF,
        PATCH_PATH,
        SOURCE_ROOT,
        apply_command,
        build_command,
        clone_command,
        configure_command,
        revision_command,
    )

    clone = clone_command()
    apply = apply_command()
    configure = configure_command()
    build = build_command(parallel=3)
    revision = revision_command()

    assert clone == [
        "git",
        "clone",
        "--depth",
        "1",
        "--branch",
        GEOS_REF,
        "https://github.com/libgeos/geos.git",
        str(SOURCE_ROOT),
    ]
    assert apply == ["git", "-C", str(SOURCE_ROOT), "apply", str(PATCH_PATH)]
    assert revision == ["git", "-C", str(SOURCE_ROOT), "rev-parse", "HEAD"]
    assert configure[:5] == ["cmake", "-S", str(SOURCE_ROOT), "-B", str(BUILD_ROOT)]
    assert "-DCMAKE_BUILD_TYPE=Release" in configure
    assert "-DBUILD_TESTING=OFF" in configure
    assert "-DBUILD_DOCUMENTATION=OFF" in configure
    assert "-DBUILD_GEOSOP=OFF" in configure
    assert "-DGEOS_BUILD_DEVELOPER=OFF" in configure
    assert build == [
        "cmake",
        "--build",
        str(BUILD_ROOT),
        "--config",
        "Release",
        "--parallel",
        "3",
    ]
    assert all(
        isinstance(command, list)
        for command in (clone, revision, apply, configure, build)
    )


def test_proof_build_verifies_commit_before_patch_and_records_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import build_geos_buffer_fast_proof as builder

    proof_root = tmp_path / "proof"
    source_root = proof_root / "geos"
    build_root = proof_root / "build"
    manifest_path = proof_root / "build_manifest.json"
    patch_path = tmp_path / "fast.patch"
    marker_path = source_root / ".lumina_patch_sha256"
    source_root.mkdir(parents=True)
    build_root.mkdir(parents=True)
    patch_path.write_text("proof patch", encoding="utf-8")
    library_path = build_root / "libgeos_c.so"
    library_path.touch()
    for name, value in (
        ("PROOF_ROOT", proof_root),
        ("SOURCE_ROOT", source_root),
        ("BUILD_ROOT", build_root),
        ("MANIFEST_PATH", manifest_path),
        ("PATCH_PATH", patch_path),
        ("PATCH_MARKER_PATH", marker_path),
    ):
        monkeypatch.setattr(builder, name, value)

    actions: list[tuple[str, list[str]]] = []

    def read_command(command: list[str]) -> str:
        actions.append(("verify", command))
        return builder.GEOS_COMMIT

    monkeypatch.setattr(builder, "_read_command_output", read_command)
    monkeypatch.setattr(
        builder,
        "_run",
        lambda command: actions.append(("run", command)),
    )
    monkeypatch.setattr(builder, "resolve_built_library", lambda: library_path)

    manifest = builder.build_proof()

    verify_index = actions.index(("verify", builder.revision_command()))
    apply_index = actions.index(("run", builder.apply_command()))
    assert verify_index < apply_index
    assert manifest["geos_commit"] == builder.GEOS_COMMIT


def test_proof_build_rejects_wrong_commit_before_applying_patch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import build_geos_buffer_fast_proof as builder

    proof_root = tmp_path / "proof"
    source_root = proof_root / "geos"
    patch_path = tmp_path / "fast.patch"
    source_root.mkdir(parents=True)
    patch_path.write_text("proof patch", encoding="utf-8")
    monkeypatch.setattr(builder, "PROOF_ROOT", proof_root)
    monkeypatch.setattr(builder, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(builder, "PATCH_PATH", patch_path)
    monkeypatch.setattr(
        builder,
        "PATCH_MARKER_PATH",
        source_root / ".lumina_patch_sha256",
    )
    monkeypatch.setattr(builder, "_read_command_output", lambda _command: "0" * 40)
    run_calls: list[list[str]] = []
    monkeypatch.setattr(builder, "_run", run_calls.append)

    with pytest.raises(RuntimeError, match="unexpected GEOS commit"):
        builder.build_proof()

    assert builder.apply_command() not in run_calls


def test_proof_builder_refuses_broad_rebuild_targets() -> None:
    from scripts.build_geos_buffer_fast_proof import PROOF_ROOT, ROOT, validate_rebuild_target

    assert validate_rebuild_target(PROOF_ROOT) == PROOF_ROOT.resolve()
    with pytest.raises(ValueError):
        validate_rebuild_target(Path("/"))
    with pytest.raises(ValueError):
        validate_rebuild_target(ROOT)
    with pytest.raises(ValueError):
        validate_rebuild_target(ROOT / ".scratch")


def test_geos_patch_changes_lookup_cost_only() -> None:
    from scripts.build_geos_buffer_fast_proof import PATCH_PATH

    patch = PATCH_PATH.read_text(encoding="utf-8")
    changed_paths = {
        line.removeprefix("+++ b/")
        for line in patch.splitlines()
        if line.startswith("+++ b/")
    }

    assert changed_paths == {
        "src/operation/buffer/BufferBuilder.cpp",
        "src/operation/buffer/PolygonBuilder.cpp",
    }
    assert "freeHoleList.empty()" in patch
    assert "index::bintree::Bintree" in patch
    assert "index::bintree::Interval" in patch
    assert "processedOrder" in patch
    assert "std::sort(candidates.begin(), candidates.end()" in patch

    forbidden = (
        "OffsetCurveBuilder.cpp",
        "computeNodedEdges(",
        "PrecisionModel.cpp",
        "BufferParameters.cpp",
        "CoordinateSequence.cpp",
    )
    assert all(token not in patch for token in forbidden)


def test_run_proof_times_backends_and_records_manifest() -> None:
    from scripts.profile_geos_buffer_fast_proof import run_proof

    geometry = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    stock = _FakeBufferBackend(geometry.wkb)
    candidate = _FakeBufferBackend(geometry.wkb)

    report = run_proof(
        input_wkb=geometry.wkb,
        input_sha256="a" * 64,
        build_manifest={"geos_ref": "3.13.1", "patch_sha256": "b" * 64},
        stock_backend=stock,
        candidate_backend=candidate,
        clock=_Readings([10.0, 11.25, 20.0, 22.5]),
        peak_rss_reader=_Readings([1000, 1100]),
    )

    assert len(stock.calls) == 1
    assert len(candidate.calls) == 1
    assert stock.calls[0][0] == geometry.wkb
    assert candidate.calls[0][0] == geometry.wkb
    assert report["input"]["sha256"] == "a" * 64
    assert report["build"]["geos_ref"] == "3.13.1"
    assert report["stock"]["seconds"] == 1.25
    assert report["candidate"]["seconds"] == 2.5
    assert report["stock"]["peak_rss_bytes"] == 1000
    assert report["candidate"]["peak_rss_bytes"] == 1100
    assert report["comparison"]["pass"] is True
    assert report["gates"] == {
        "geometry_exact": True,
        "candidate_seconds_at_most_4": True,
        "candidate_peak_rss_at_most_1_20x_stock": True,
    }
    assert report["pass"] is True


@pytest.mark.parametrize(
    ("candidate_geometry", "candidate_seconds", "stock_rss", "candidate_rss", "failed_gate"),
    [
        (
            Polygon([(1, 0), (3, 0), (3, 2), (1, 2)]),
            1.0,
            100,
            100,
            "geometry_exact",
        ),
        (
            Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]),
            4.000001,
            100,
            100,
            "candidate_seconds_at_most_4",
        ),
        (
            Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]),
            1.0,
            100,
            121,
            "candidate_peak_rss_at_most_1_20x_stock",
        ),
    ],
)
def test_evaluate_measurements_rejects_each_acceptance_failure(
    candidate_geometry: Polygon,
    candidate_seconds: float,
    stock_rss: int,
    candidate_rss: int,
    failed_gate: str,
) -> None:
    from scripts.profile_geos_buffer_fast_proof import (
        BufferMeasurement,
        evaluate_measurements,
    )

    stock_geometry = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    report = evaluate_measurements(
        input_sha256="c" * 64,
        build_manifest={"geos_ref": "3.13.1"},
        stock=BufferMeasurement(stock_geometry.wkb, 2.0, stock_rss),
        candidate=BufferMeasurement(
            candidate_geometry.wkb,
            candidate_seconds,
            candidate_rss,
        ),
    )

    assert report["gates"][failed_gate] is False
    assert report["pass"] is False


def test_report_rendering_and_files_are_deterministic(tmp_path: Path) -> None:
    from scripts.profile_geos_buffer_fast_proof import (
        BufferMeasurement,
        evaluate_measurements,
        render_report_json,
        render_report_markdown,
        write_report,
    )

    geometry = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    report = evaluate_measurements(
        input_sha256="d" * 64,
        build_manifest={"geos_ref": "3.13.1", "patch_sha256": "e" * 64},
        stock=BufferMeasurement(geometry.wkb, 8.0, 1000),
        candidate=BufferMeasurement(geometry.wkb, 1.5, 1100),
    )

    first_json = render_report_json(report)
    second_json = render_report_json(report)
    first_markdown = render_report_markdown(report)
    second_markdown = render_report_markdown(report)
    json_path, markdown_path = write_report(report, tmp_path, "dense-case")

    assert first_json == second_json == json_path.read_text(encoding="utf-8")
    assert first_markdown == second_markdown == markdown_path.read_text(encoding="utf-8")
    assert "PASS" in first_markdown
    assert "1.500000 s" in first_markdown
    assert "symmetric difference" in first_markdown.lower()


def test_geos_c_backend_uses_only_wkb_and_reentrant_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ctypes

    from core import geos_buffer_fast
    from scripts import profile_geos_buffer_fast_proof as proof

    class FakeFunction:
        def __init__(self, implementation):
            self.implementation = implementation
            self.calls: list[tuple[object, ...]] = []
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            self.calls.append(args)
            return self.implementation(*args)

    output_wkb = Polygon([(0, 0), (3, 0), (3, 3), (0, 3)]).wkb
    output_buffer = ctypes.create_string_buffer(output_wkb)
    fake = type("FakeLibrary", (), {})()
    fake.GEOS_init_r = FakeFunction(lambda: 1)
    fake.GEOS_finish_r = FakeFunction(lambda _context: None)
    fake.GEOSWKBReader_create_r = FakeFunction(lambda _context: 2)
    fake.GEOSWKBReader_destroy_r = FakeFunction(lambda _context, _reader: None)
    fake.GEOSWKBReader_read_r = FakeFunction(
        lambda _context, _reader, _input, _size: 3
    )
    fake.GEOSWKBWriter_create_r = FakeFunction(lambda _context: 4)
    fake.GEOSWKBWriter_destroy_r = FakeFunction(lambda _context, _writer: None)

    def write_wkb(_context, _writer, _geometry, size_pointer):
        size_pointer._obj.value = len(output_wkb)
        return ctypes.addressof(output_buffer)

    fake.GEOSWKBWriter_write_r = FakeFunction(write_wkb)
    fake.GEOSBufferParams_create_r = FakeFunction(lambda _context: 5)
    fake.GEOSBufferParams_destroy_r = FakeFunction(lambda _context, _params: None)
    fake.GEOSBufferParams_setJoinStyle_r = FakeFunction(
        lambda _context, _params, _value: 1
    )
    fake.GEOSBufferParams_setMitreLimit_r = FakeFunction(
        lambda _context, _params, _value: 1
    )
    fake.GEOSBufferParams_setQuadrantSegments_r = FakeFunction(
        lambda _context, _params, _value: 1
    )
    fake.GEOSBufferWithParams_r = FakeFunction(
        lambda _context, _geometry, _params, _distance: 6
    )
    fake.GEOSGeom_destroy_r = FakeFunction(lambda _context, _geometry: None)
    fake.GEOSFree_r = FakeFunction(lambda _context, _buffer: None)

    library_path = tmp_path / "libgeos_c.dylib"
    library_path.touch()
    monkeypatch.setattr(
        geos_buffer_fast.ctypes,
        "CDLL",
        lambda *_args, **_kwargs: fake,
    )

    backend = proof.GEOSCBufferBackend(library_path)
    result = backend.buffer_wkb(b"input-wkb", proof.BufferSettings())

    assert result == output_wkb
    assert len(fake.GEOSWKBReader_read_r.calls) == 1
    assert len(fake.GEOSBufferWithParams_r.calls) == 1
    assert len(fake.GEOSGeom_destroy_r.calls) == 2
    assert len(fake.GEOSFree_r.calls) == 1
    assert len(fake.GEOS_finish_r.calls) == 1
    assert not any(name.endswith("_r") is False for name in vars(fake))


def test_geos_c_backend_rejects_relative_library_path() -> None:
    from scripts.profile_geos_buffer_fast_proof import (
        GEOSCBufferBackend,
        ProofLibraryError,
    )

    with pytest.raises(ProofLibraryError, match="absolute"):
        GEOSCBufferBackend(Path("relative/libgeos_c.dylib"))


def test_dense_real_geometry_gate_rejects_small_input() -> None:
    from scripts.profile_geos_buffer_fast_proof import dense_geometry_metadata

    with pytest.raises(ValueError, match="2,048"):
        dense_geometry_metadata(
            Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]),
            require_real_density=True,
        )


def test_shapely_backend_matches_production_positive_buffer_policy() -> None:
    from shapely import from_wkb

    from scripts.profile_geos_buffer_fast_proof import (
        BufferSettings,
        ShapelyBufferBackend,
    )

    source = Polygon([(0, 0), (5, 0), (5, 1), (1, 1), (1, 5), (0, 5)])
    settings = BufferSettings()

    actual = from_wkb(ShapelyBufferBackend().buffer_wkb(source.wkb, settings))
    expected = source.buffer(
        0.03,
        quad_segs=1,
        join_style="mitre",
        mitre_limit=2.0,
    )

    assert actual.equals_exact(expected, 0.0)


def test_extract_dense_geometry_uses_production_parse_policy() -> None:
    from scripts.profile_geos_buffer_fast_proof import extract_dense_geometry

    components = [
        Polygon([(x, 0), (x + 0.5, 0), (x + 0.5, 0.5), (x, 0.5)])
        for x in (0.0, 2.0, 4.0)
    ]
    dense = MultiPolygon(components)

    class FakeProcessor:
        def _parse_svg(self, svg_path: str, target_width_mm: float):
            assert self._parse_expand_stroke_to_fill is False
            assert svg_path == str(Path("/tmp/dense.svg"))
            assert target_width_mm == 300.0
            return ([{"poly": components[0]}] * 5, 1.0, (0, 0, 5, 1))

        def _clip_occlusion(self, shape_data, return_silhouette=False):
            assert len(shape_data) == 5
            assert return_silhouette is True
            return (
                [
                    {"geometry": components[0]},
                    {"geometry": dense},
                ],
                dense,
            )

    geometry, metadata = extract_dense_geometry(
        FakeProcessor(),
        Path("/tmp/dense.svg"),
        300.0,
        require_real_density=False,
    )

    assert geometry.equals(dense)
    assert metadata == {
        "source_shape_count": 5,
        "clipped_shape_count": 2,
        "dense_component_count": 3,
        "dense_coordinate_count": 15,
    }


def test_profiler_cli_defaults_to_300mm_acceptance_mode(tmp_path: Path) -> None:
    from scripts.profile_geos_buffer_fast_proof import parse_args

    args = parse_args(
        [
            "--input",
            str(tmp_path / "dense.svg"),
            "--lut",
            str(tmp_path / "lut.npy"),
        ]
    )

    assert args.target_width_mm == 300.0
    assert args.color_mode == "4-Color RYBW"
    assert args.library is None
    assert args.skip_stock_timing is False
    assert args.out_dir.name == "results"


def test_synthetic_cases_cover_dense_and_topology_edges() -> None:
    from scripts.profile_geos_buffer_fast_proof import build_synthetic_cases

    cases = build_synthetic_cases()

    assert set(cases) == {
        "disjoint_4096",
        "interacting_square_chain",
        "holes_and_nested_shells",
        "sharp_mitres",
        "tiny_valid_components",
        "positive_buffer_merges_inputs",
    }
    assert len(cases["disjoint_4096"].geoms) == 4096
    assert all(geometry.is_valid for geometry in cases.values())


def test_profiler_cli_accepts_synthetic_mode_without_svg() -> None:
    from scripts.profile_geos_buffer_fast_proof import parse_args

    args = parse_args(["--synthetic"])

    assert args.synthetic is True
    assert args.input is None
    assert args.lut is None


def test_profiler_cli_can_mark_second_sample_as_non_dense() -> None:
    from scripts.profile_geos_buffer_fast_proof import parse_args

    args = parse_args(
        [
            "--input",
            "/tmp/small.svg",
            "--lut",
            "/tmp/lut.npy",
            "--allow-small-real-case",
        ]
    )

    assert args.allow_small_real_case is True
