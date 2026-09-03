"""Contract for complete Lumina native-SVG benchmark evidence."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import lumina_svg_core
import shapely

from scripts import benchmark_native_svg_analysis as benchmark


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "progress" / "native-svg-fast-path-benchmark.json"
SOURCE_PROXY_PATH = REPO_ROOT / "test_images" / "benchmark.svg"
SUPPORTED_FIXTURE_PATH = (
    REPO_ROOT
    / "native"
    / "lumina-svg-core"
    / "benchmarks"
    / "supported_scale_fixture.svg"
)
ALPHA_FIXTURE_PATH = (
    REPO_ROOT
    / "native"
    / "lumina-svg-core"
    / "benchmarks"
    / "alpha_compositing_fixture.svg"
)
LUT_PATH = (
    REPO_ROOT
    / "lut-preset"
    / "bambulab"
    / "bambulab_pla_basic_rybw.npy"
)
def _load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_complete_vector_analysis_benchmark_contract() -> None:
    manifest = _load_manifest()

    assert manifest["schema_version"] == 4
    assert manifest["entrypoint"] == (
        "core.vector_engine.VectorProcessor.analyze_svg"
    )

    fixture = manifest["fixture"]
    fixture_bytes = SUPPORTED_FIXTURE_PATH.read_bytes()
    assert fixture["path"] == (
        "native/lumina-svg-core/benchmarks/supported_scale_fixture.svg"
    )
    assert fixture["classification"] == "derived_supported_scale"
    assert fixture["byte_size"] == len(fixture_bytes)
    assert fixture["provenance"]["selection"][
        "overlap_policy"
    ] == "disjoint_cell_bounds"
    assert len(fixture["canvas_user_units"]) == 2
    for key in (
        "path_count",
        "stroke_count",
        "stroke_only_count",
        "transform_count",
        "clip_count",
    ):
        assert fixture[key] >= 0

    parameters = manifest["parameters"]
    assert parameters == {
        "target_width_mm": 111.0,
        "tolerance_mm": 0.02,
        "build_type": "Release",
        "openmp_enabled": False,
        "caller_threads": 1,
    }

    host = manifest["host"]
    for key in (
        "platform",
        "platform_release",
        "machine",
        "processor",
        "python",
        "cpu_count",
        "memory_bytes",
    ):
        assert host[key]

    measurement = manifest["measurement"]
    assert measurement["warmup_runs"] == 1
    assert len(measurement["warm_runs_seconds"]) >= 3
    assert measurement["cache_policy"] == {
        "memory_cache_cleared_before_each_run": True,
        "artifact_cache_disabled": True,
    }
    for key in (
        "median_seconds",
        "p95_seconds",
        "range_seconds",
        "native_recorder_seconds",
        "native_kernel_seconds",
        "native_bounds_seconds",
        "native_replay_seconds",
        "native_topology_seconds",
        "native_normalize_raw_seconds",
        "native_composite_seconds",
        "native_normalize_visible_seconds",
        "native_export_seconds",
        "native_binding_conversion_seconds",
        "native_adapter_conversion_seconds",
        "native_geometry_total_seconds",
        "color_match_seconds",
        "orchestration_seconds",
    ):
        assert measurement[key] >= 0
    assert measurement["median_seconds"] > 0
    assert measurement["p95_seconds"] >= min(
        measurement["warm_runs_seconds"]
    )
    assert measurement["peak_rss_bytes"] > 0
    assert measurement["process_isolation"] == "fresh_subprocess"
    assert measurement["process_pid"] > 0
    assert measurement["swap_delta_bytes"] >= 0
    assert measurement["median_threshold_seconds"] == 1.0
    assert measurement["p95_threshold_seconds"] == 1.25
    assert measurement["median_threshold_passed"] == (
        measurement["median_seconds"] <= 1.0
    )
    assert measurement["p95_threshold_passed"] == (
        measurement["p95_seconds"] <= 1.25
    )
    assert measurement["median_threshold_passed"] is True
    assert measurement["p95_threshold_passed"] is True

    output = manifest["output"]
    assert output["geometry_backend"] == "native"
    assert output["native_cache_hit"] is False
    assert output["raw_shape_count"] > 0
    assert output["visible_shape_count"] > 0
    assert output["matched_shape_count"] == output["visible_shape_count"]
    assert output["silhouette_component_count"] > 0
    assert output["coordinate_count"] > 0
    assert len(output["fingerprint"]) == 64
    assert output["fingerprint_contract"] == (
        "geometry-exact-rgba-paint-provenance-v2"
    )
    for key in (
        "partial_alpha_raw_shape_count",
        "partial_alpha_visible_shape_count",
        "composite_visible_shape_count",
        "visible_contributor_count",
    ):
        assert output[key] >= 0
    assert output["stable_across_runs"] is True

    alpha = manifest["alpha_compositing"]
    assert alpha["fixture"] == {
        "path": (
            "native/lumina-svg-core/benchmarks/"
            "alpha_compositing_fixture.svg"
        ),
        "classification": "alpha_compositing",
        "byte_size": ALPHA_FIXTURE_PATH.stat().st_size,
        **benchmark._fixture_structure(ALPHA_FIXTURE_PATH),
    }
    assert alpha["measurement"]["process_isolation"] == "fresh_subprocess"
    assert alpha["measurement"]["peak_rss_bytes"] > 0
    assert alpha["measurement"]["median_seconds"] > 0
    assert alpha["output"]["geometry_backend"] == "native"
    assert alpha["output"]["partial_alpha_raw_shape_count"] > 0
    assert alpha["output"]["partial_alpha_visible_shape_count"] > 0
    assert alpha["output"]["composite_visible_shape_count"] > 0
    assert alpha["output"]["visible_contributor_count"] > alpha["output"][
        "visible_shape_count"
    ]
    assert alpha["output"]["stable_across_runs"] is True


def test_real_inputs_record_current_capability_without_identity_gates() -> None:
    manifest = _load_manifest()

    source_proxy = manifest["source_proxy"]
    assert source_proxy["classification"] in {"real_proxy", "real_proxy_fallback"}
    assert source_proxy["byte_size"] == SOURCE_PROXY_PATH.stat().st_size
    assert source_proxy["status"] in {"supported", "unsupported"}
    assert source_proxy["native_by_default_ready"] == (
        source_proxy["status"] == "supported"
    )
    if source_proxy["status"] == "supported":
        assert source_proxy["reason_code"] is None
    else:
        assert source_proxy["reason_code"]

    real = manifest["real_r4c1"]
    assert real["classification"] == "real_r4c1"
    assert real["status"] in {"supported", "unsupported", "unavailable"}
    assert real["native_by_default_ready"] == (
        real["status"] == "supported"
    )
    if real["status"] == "unavailable":
        assert real["reason_code"] is None
        assert real["source"] == "not_provided"

    large = manifest["large_regression"]
    assert large["minimum_byte_size"] == 50 * 1024 * 1024
    assert large["status"] in {"measured", "unavailable"}
    assert large["classification"] == "large_regression"
    assert large["classification"] != fixture_classification(manifest)
    assert large["searched_roots"]
    if large["status"] == "measured":
        assert large["byte_size"] >= large["minimum_byte_size"]
        assert large["peak_rss_bytes"] <= 2 * 1024**3
        assert large["swap_delta_bytes"] <= 256 * 1024**2
        assert large["rss_threshold_passed"] is True
        assert large["swap_delta_threshold_passed"] is True
    else:
        assert large["matching_files"] == []


def fixture_classification(manifest: dict) -> str:
    """Return the performance-fixture classification for comparison."""

    return manifest["fixture"]["classification"]


def test_benchmark_threshold_failures_are_process_fatal() -> None:
    manifest = {
        "measurement": {
            "median_threshold_passed": False,
            "p95_threshold_passed": True,
        },
        "large_regression": {
            "status": "measured",
            "rss_threshold_passed": True,
            "swap_delta_threshold_passed": False,
        },
    }

    assert benchmark._threshold_failures(manifest) == [
        "measurement.median_threshold_passed",
        "large_regression.swap_delta_threshold_passed",
    ]


def test_analysis_fingerprint_covers_exact_rgba_and_paint_provenance() -> None:
    polygon = shapely.box(0.0, 0.0, 1.0, 1.0)
    contributor = SimpleNamespace(
        native_draw_order=0,
        native_source_index=7,
        source_kind="fill",
        weight=0.5,
        native_paint_id=(7, 0),
    )
    raw_item = {
        "color": (255, 0, 0),
        "rgba": (255, 0, 0, 128),
        "rgba_f64": (1.0, 0.0, 0.0, 0.5),
        "source_kind": "fill",
        "native_paint_id": (7, 0),
        "native_paint_contributors": (contributor,),
        "poly": polygon,
    }
    visible_item = {
        **raw_item,
        "geometry": polygon,
        "draw_order": 0,
        "native_draw_order": 0,
        "native_source_index": 7,
    }
    analysis = SimpleNamespace(
        bbox=(0.0, 0.0, 1.0, 1.0),
        scale_factor=1.0,
        num_channels=4,
        num_layers=1,
        slot_names=["red"],
        shape_data=[raw_item],
        clipped_shapes=[visible_item],
        matched_shapes=[],
        silhouette=polygon,
    )

    baseline = benchmark._analysis_fingerprint(analysis)

    rgba_changed = deepcopy(analysis)
    rgba_changed.clipped_shapes[0]["rgba_f64"] = (
        1.0,
        0.0,
        0.0,
        0.5000000000000001,
    )
    assert benchmark._analysis_fingerprint(rgba_changed) != baseline

    provenance_changed = deepcopy(analysis)
    provenance_changed.clipped_shapes[0][
        "native_paint_contributors"
    ] = (
        SimpleNamespace(
            native_draw_order=0,
            native_source_index=7,
            source_kind="fill",
            weight=0.25,
            native_paint_id=(7, 0),
        ),
    )
    assert benchmark._analysis_fingerprint(provenance_changed) != baseline

    identity_changed = deepcopy(analysis)
    identity_changed.clipped_shapes[0]["native_paint_id"] = None
    assert benchmark._analysis_fingerprint(identity_changed) != baseline


def test_public_entry_rss_measurement_runs_in_a_fresh_subprocess(
    monkeypatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        output_path = Path(command[command.index("--output") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "measurement": {
                        "process_isolation": "fresh_subprocess",
                        "process_pid": os.getpid() + 1,
                        "peak_rss_bytes": 123,
                    },
                    "output": {"geometry_backend": "native"},
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(benchmark.subprocess, "run", fake_run)
    measurement, output = benchmark._measure_complete_entry_isolated(
        SUPPORTED_FIXTURE_PATH,
        LUT_PATH,
        target_width_mm=111.0,
        tolerance_mm=0.02,
        warm_runs=3,
    )

    assert measurement["process_isolation"] == "fresh_subprocess"
    assert measurement["process_pid"] != os.getpid()
    assert measurement["peak_rss_bytes"] > 0
    assert output["geometry_backend"] == "native"
    assert "--_measurement-child" in commands[0]


def test_supported_scale_fixture_runs_directly_on_native_core() -> None:
    result = lumina_svg_core.analyze_svg(
        SUPPORTED_FIXTURE_PATH,
        target_width_mm=111.0,
        tolerance_mm=0.02,
        allow_strokes=False,
    )

    assert result.status == "supported"
    assert result.raw.geometry_count > 0
    assert result.visible.geometry_count > 0
    assert result.silhouette.component_count > 0
