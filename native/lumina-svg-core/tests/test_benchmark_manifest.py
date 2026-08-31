"""Contract for checked-in standalone performance evidence."""

from __future__ import annotations

import json
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PACKAGE_ROOT / "benchmarks" / "proxy_manifest.json"
REAL_CAPABILITY_PATH = (
    PACKAGE_ROOT / "benchmarks" / "real_r4c1_capability.json"
)
REAL_R4C1_SHA256 = (
    "da52ef12bdd37a0bd47970649a70582862331a606c151bff05bfb2f6e265f160"
)


def test_proxy_manifest_contains_reproducible_full_entrypoint_evidence() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 2
    assert manifest["fixture"]["classification"] == (
        "derived_supported_scale"
    )
    assert manifest["fixture"]["sha256"] != REAL_R4C1_SHA256
    assert manifest["fixture"]["real_r4c1_sha256"] == REAL_R4C1_SHA256
    assert manifest["fixture"]["source_proxy_sha256"] == (
        "d078cf4293623d934759c2688e13a00491e525055e7595069a0ecc4f078842fb"
    )
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


def test_real_r4c1_evidence_never_masquerades_fallback_as_native_success() -> None:
    evidence = json.loads(REAL_CAPABILITY_PATH.read_text(encoding="utf-8"))

    assert evidence["fixture"]["classification"] == "real_r4c1"
    assert evidence["fixture"]["sha256"] == REAL_R4C1_SHA256
    assert evidence["fixture"]["byte_size"] == 14_467_678
    assert evidence["output"] == {
        "status": "unsupported",
        "reason_code": "unsupported_vector_effect",
    }
    assert evidence["acceptance"]["native_by_default_ready"] is False
