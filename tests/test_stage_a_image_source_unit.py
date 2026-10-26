"""Regression for the gradient-card ``image_source`` capture-origin tag.

The tag flows through:

  - ``extract_stage_a_material_from_gradient_cards(image_source=...)``
    accepts ``"raw"`` (default) or ``"restored"``; ``"restored"`` adds a
    strong, separate warning beyond the C0_white-overbright detector.
  - The tag is persisted in ``params_payload['meta']['image_source']``
    *and* ``source_summary['image_source']`` so audits and downstream
    aggregation can read it from either side.
  - ``save_stage_a_material_archive`` records a normalized aggregation
    label at ``archive['aggregation']['image_source']`` and refuses to
    merge a new capture whose tag disagrees with stored verification
    runs (raw vs restored mixing). Legacy archives without the tag are
    treated as "unknown" and never block the merge.

Test coverage matches each of these contract points one-to-one.

``image_source`` 标签从 extract 入口贯穿到 save，本测试覆盖每个契约点。
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

from core.single_stage import (
    extract_stage_a_material_from_gradient_cards,
    save_stage_a_material_archive,
)
from core.single_stage.kit import SingleStageSpec


_RESTORED_WARNING_FRAGMENT = "ColorChecker 校正/还原"


def _linear_to_srgb_uint8(arr: np.ndarray) -> np.ndarray:
    clipped = np.clip(arr.astype(np.float64), 0.0, 1.0)
    srgb = np.where(
        clipped <= 0.0031308,
        12.92 * clipped,
        1.055 * np.power(clipped, 1.0 / 2.4) - 0.055,
    )
    return np.clip(np.round(srgb * 255.0), 0, 255).astype(np.uint8)


def _write_gradient_card_manifest(zip_path: Path, spec: SingleStageSpec) -> None:
    manifest = {
        "schema_version": "1.0",
        "workflow": "single-stage-kit",
        "material_default": "PLA Basic",
        "substrate_id": "white",
        "substrate_display_name": "White",
        "spec": {
            "grid_cols": spec.grid_cols,
            "grid_rows": spec.grid_rows,
            "block_mm": spec.block_mm,
            "gap_mm": spec.gap_mm,
            "margin_mm": spec.margin_mm,
            "pixel_mm": spec.pixel_mm,
            "layer_height_mm": spec.layer_height_mm,
            "base_mm": spec.base_mm,
            "max_step_layers": spec.max_step_layers,
            "step_layers": list(spec.step_layers),
            "shrink_xy_mm": spec.shrink_xy_mm,
        },
    }
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )


def _build_gradient_card_capture(
    spec: SingleStageSpec,
    substrate_linear: np.ndarray,
    e_linear: np.ndarray,
    k_linear: np.ndarray,
) -> np.ndarray:
    pixels_per_mm = 20
    width = int(round(spec.board_width_mm * pixels_per_mm))
    height = int(round(spec.board_height_mm * pixels_per_mm))
    image = np.tile(
        _linear_to_srgb_uint8(substrate_linear.reshape(1, 3)),
        (height, width, 1),
    )
    step_matrix = np.asarray(spec.step_layers, dtype=np.float64).reshape(
        spec.grid_rows,
        spec.grid_cols,
    )
    for row in range(spec.grid_rows):
        for col in range(spec.grid_cols):
            step_layers = step_matrix[row, col]
            thickness_mm = step_layers * spec.layer_height_mm
            linear_rgb = e_linear + (substrate_linear - e_linear) * np.exp(
                -k_linear * thickness_mm,
            )
            srgb = _linear_to_srgb_uint8(linear_rgb.reshape(1, 3))[0]
            x0 = int(round((spec.margin_mm + col * (spec.block_mm + spec.gap_mm)) * pixels_per_mm))
            y0 = int(round((spec.margin_mm + row * (spec.block_mm + spec.gap_mm)) * pixels_per_mm))
            x1 = int(round((spec.margin_mm + col * (spec.block_mm + spec.gap_mm) + spec.block_mm) * pixels_per_mm))
            y1 = int(round((spec.margin_mm + row * (spec.block_mm + spec.gap_mm) + spec.block_mm) * pixels_per_mm))
            image[y0:y1, x0:x1] = srgb
    return image


def _make_spec() -> SingleStageSpec:
    return SingleStageSpec(
        grid_cols=3,
        grid_rows=2,
        block_mm=10.0,
        gap_mm=0.0,
        margin_mm=0.0,
        pixel_mm=1.0,
        layer_height_mm=0.1,
        base_mm=1.0,
        max_step_layers=6,
        step_layers=(0, 1, 2, 3, 4, 6),
        shrink_xy_mm=0.0,
    )


def _run_extract(
    tmp_path: Path,
    *,
    image_source: str | None,
    suffix: str = "run",
):
    spec = _make_spec()
    zip_path = tmp_path / f"kit_{suffix}.zip"
    _write_gradient_card_manifest(zip_path, spec)
    white_substrate = np.array([0.86, 0.88, 0.9], dtype=np.float64)
    black_substrate = np.array([0.08, 0.09, 0.1], dtype=np.float64)
    expected_e = np.array([0.22, 0.18, 0.15], dtype=np.float64)
    expected_k = np.array([1.7, 1.4, 1.2], dtype=np.float64)
    white_capture = _build_gradient_card_capture(
        spec, white_substrate, expected_e, expected_k,
    )
    black_capture = _build_gradient_card_capture(
        spec, black_substrate, expected_e, expected_k,
    )
    corners = [
        [0, 0],
        [white_capture.shape[1] - 1, 0],
        [white_capture.shape[1] - 1, white_capture.shape[0] - 1],
        [0, white_capture.shape[0] - 1],
    ]
    return extract_stage_a_material_from_gradient_cards(
        white_capture, black_capture,
        corners, corners, str(zip_path),
        output_path=str(tmp_path / f"stage_a_{suffix}.json"),
        image_source=image_source,
    )


def test_extract_defaults_to_raw_image_source(tmp_path: Path) -> None:
    """When no ``image_source`` is provided the tag must default to ``raw``,
    persisted in both the params meta and the source summary."""
    result = _run_extract(tmp_path, image_source=None, suffix="default")
    assert result.params_payload["meta"]["image_source"] == "raw"
    assert result.source_summary["image_source"] == "raw"
    assert not any(
        _RESTORED_WARNING_FRAGMENT in w for w in (result.warnings or [])
    )


def test_extract_explicit_raw_persists_tag_and_no_warning(tmp_path: Path) -> None:
    result = _run_extract(tmp_path, image_source="raw", suffix="raw")
    assert result.params_payload["meta"]["image_source"] == "raw"
    assert result.source_summary["image_source"] == "raw"
    assert not any(
        _RESTORED_WARNING_FRAGMENT in w for w in (result.warnings or [])
    )


def test_extract_restored_emits_warning_and_persists_tag(tmp_path: Path) -> None:
    result = _run_extract(tmp_path, image_source="restored", suffix="restored")
    assert result.params_payload["meta"]["image_source"] == "restored"
    assert result.source_summary["image_source"] == "restored"
    warnings = list(result.warnings or [])
    restored_msgs = [w for w in warnings if _RESTORED_WARNING_FRAGMENT in w]
    assert len(restored_msgs) == 1, warnings
    assert "零厚度白底采样接近纯白" in restored_msgs[0]
    assert "裁切" in restored_msgs[0]


def test_extract_rejects_unknown_image_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="image_source must be one of"):
        _run_extract(tmp_path, image_source="totally-unknown", suffix="bad")


def test_save_records_image_source_in_aggregation(tmp_path: Path) -> None:
    """A single-run save must surface the canonical image_source in the
    archive's aggregation block so audits can rely on a single source-of-
    truth field instead of digging into per-run source dicts."""
    materials_root = tmp_path / "materials"
    result = _run_extract(tmp_path, image_source="raw", suffix="agg-raw")
    save_result = save_stage_a_material_archive(
        material_name="PLA Basic",
        params_payload=result.params_payload,
        fit_summary=result.fit_summary,
        source_summary=result.source_summary,
        material_summary=result.material_summary,
        materials_dir=str(materials_root),
    )
    archive_payload = json.loads(
        Path(save_result.archive_path).read_text(encoding="utf-8")
    )
    assert archive_payload["aggregation"]["image_source"] == "raw"
    runs = archive_payload["verification_runs"]
    assert len(runs) == 1
    assert runs[0]["source"]["image_source"] == "raw"


def test_save_merges_consistent_raw_to_raw(tmp_path: Path) -> None:
    """Two raw captures must merge cleanly and keep ``image_source='raw'``
    in the aggregation block; this is the happy path for re-verification."""
    materials_root = tmp_path / "materials"
    first = _run_extract(tmp_path, image_source="raw", suffix="merge-raw1")
    save_first = save_stage_a_material_archive(
        material_name="PLA Basic",
        params_payload=first.params_payload,
        fit_summary=first.fit_summary,
        source_summary=first.source_summary,
        material_summary=first.material_summary,
        materials_dir=str(materials_root),
    )
    second = _run_extract(tmp_path, image_source="raw", suffix="merge-raw2")
    save_second = save_stage_a_material_archive(
        material_name="PLA Basic",
        params_payload=second.params_payload,
        fit_summary=second.fit_summary,
        source_summary=second.source_summary,
        material_summary=second.material_summary,
        materials_dir=str(materials_root),
        existing_directory_name=save_first.material_summary["directory_name"],
    )
    archive_payload = json.loads(
        Path(save_second.archive_path).read_text(encoding="utf-8")
    )
    assert archive_payload["verification_count"] == 2
    assert archive_payload["aggregation"]["image_source"] == "raw"
    for run in archive_payload["verification_runs"]:
        assert run["source"]["image_source"] == "raw"


def test_save_rejects_raw_after_restored(tmp_path: Path) -> None:
    """A restored capture followed by a raw capture in merge mode must be
    rejected with an actionable ValueError mentioning both sources, so the
    user can either re-shoot or use override."""
    materials_root = tmp_path / "materials"
    first = _run_extract(tmp_path, image_source="restored", suffix="mix-rest")
    save_first = save_stage_a_material_archive(
        material_name="PLA Basic",
        params_payload=first.params_payload,
        fit_summary=first.fit_summary,
        source_summary=first.source_summary,
        material_summary=first.material_summary,
        materials_dir=str(materials_root),
    )
    second = _run_extract(tmp_path, image_source="raw", suffix="mix-raw")
    with pytest.raises(ValueError) as exc:
        save_stage_a_material_archive(
            material_name="PLA Basic",
            params_payload=second.params_payload,
            fit_summary=second.fit_summary,
            source_summary=second.source_summary,
            material_summary=second.material_summary,
            materials_dir=str(materials_root),
            existing_directory_name=save_first.material_summary["directory_name"],
        )
    msg = str(exc.value)
    assert "raw" in msg and "restored" in msg
    assert "save_mode='override'" in msg


def test_save_override_mode_replaces_restored_with_raw(tmp_path: Path) -> None:
    """``save_mode='override'`` must drop existing verification runs and
    bypass the consistency check, allowing a clean switch from restored
    to raw without manual deletion."""
    materials_root = tmp_path / "materials"
    first = _run_extract(tmp_path, image_source="restored", suffix="ov-rest")
    save_first = save_stage_a_material_archive(
        material_name="PLA Basic",
        params_payload=first.params_payload,
        fit_summary=first.fit_summary,
        source_summary=first.source_summary,
        material_summary=first.material_summary,
        materials_dir=str(materials_root),
    )
    second = _run_extract(tmp_path, image_source="raw", suffix="ov-raw")
    save_second = save_stage_a_material_archive(
        material_name="PLA Basic",
        params_payload=second.params_payload,
        fit_summary=second.fit_summary,
        source_summary=second.source_summary,
        material_summary=second.material_summary,
        materials_dir=str(materials_root),
        existing_directory_name=save_first.material_summary["directory_name"],
        save_mode="override",
    )
    archive_payload = json.loads(
        Path(save_second.archive_path).read_text(encoding="utf-8")
    )
    assert archive_payload["verification_count"] == 1
    assert archive_payload["aggregation"]["image_source"] == "raw"
    assert archive_payload["verification_runs"][0]["source"]["image_source"] == "raw"


def test_save_legacy_archive_without_tag_does_not_block_merge(tmp_path: Path) -> None:
    """A legacy archive whose verification run has no ``image_source`` (or
    a malformed value) must be treated as 'unknown' and accept a tagged
    new run without blocking. This is the backwards-compatibility path."""
    materials_root = tmp_path / "materials"
    first = _run_extract(tmp_path, image_source="raw", suffix="leg-first")
    legacy_source = dict(first.source_summary)
    legacy_source.pop("image_source", None)
    save_first = save_stage_a_material_archive(
        material_name="PLA Basic",
        params_payload=first.params_payload,
        fit_summary=first.fit_summary,
        source_summary=legacy_source,
        material_summary=first.material_summary,
        materials_dir=str(materials_root),
    )
    second = _run_extract(tmp_path, image_source="raw", suffix="leg-second")
    save_second = save_stage_a_material_archive(
        material_name="PLA Basic",
        params_payload=second.params_payload,
        fit_summary=second.fit_summary,
        source_summary=second.source_summary,
        material_summary=second.material_summary,
        materials_dir=str(materials_root),
        existing_directory_name=save_first.material_summary["directory_name"],
    )
    archive_payload = json.loads(
        Path(save_second.archive_path).read_text(encoding="utf-8")
    )
    assert archive_payload["verification_count"] == 2
    # The legacy run contributes no tag; the only known tag is the new
    # run's ``raw`` so the aggregation label is ``raw``.
    assert archive_payload["aggregation"]["image_source"] == "raw"
