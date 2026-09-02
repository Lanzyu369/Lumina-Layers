"""Contract for checked-in standalone performance evidence."""

from __future__ import annotations

import json
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PACKAGE_ROOT / "benchmarks" / "proxy_manifest.json"

def test_proxy_manifest_contains_reproducible_full_entrypoint_evidence() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 2
    assert manifest["fixture"]["classification"] == (
        "derived_supported_scale"
    )
    assert {
        "sha256",
        "real_r4c1_sha256",
        "source_proxy_sha256",
    }.isdisjoint(manifest["fixture"])
    assert manifest["fixture"]["byte_size"] > 0
    assert len(manifest["fixture"]["canvas_user_units"]) == 2
    for key in ("path_count", "stroke_count", "transform_count", "clip_count"):
        assert manifest["fixture"][key] >= 0

    host = manifest["host"]
    for key in ("platform", "machine", "processor", "python", "cpu_count"):
        assert host[key]

    measurement = manifest["measurement"]
    assert measurement["warmup_runs"] >= 1
    assert len(measurement["warm_runs_seconds"]) >= 3
    assert measurement["median_seconds"] > 0
    assert measurement["range_seconds"] >= 0
    assert measurement["peak_rss_bytes"] > 0
    assert measurement["swap_delta_bytes"] >= 0
    assert measurement["recorder_seconds"] >= 0
    assert measurement["kernel_seconds"] >= 0
    assert measurement["result_conversion_seconds"] >= 0
    assert measurement["public_entrypoint_seconds"] >= (
        measurement["recorder_seconds"]
        + measurement["kernel_seconds"]
        + measurement["result_conversion_seconds"]
    ) * 0.95

    output = manifest["output"]
    assert output["status"] == "supported"
    assert output["region_count"] > 0
    assert output["coordinate_count"] > 0
    assert len(output["fingerprint"]) == 64
