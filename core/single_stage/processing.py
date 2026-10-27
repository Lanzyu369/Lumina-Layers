"""Single-stage dataset extraction and Stage A fitting adapters."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from config import TEMP_DIR

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


@dataclass(frozen=True)
class SingleStageExtractResult:
    """Result for extracted single-stage data."""

    stage_json_path: str
    dataset_summary: dict[str, object]
    warnings: list[str]
    extracted_root: str


@dataclass(frozen=True)
class StageAFitResult:
    """Result for fitted Stage A parameters."""

    params_path: str
    fit_summary: dict[str, object]


def _reference_root() -> Path:
    root = Path("reference/ChromaPrint3D").resolve()
    if not root.exists():
        raise FileNotFoundError(
            "reference/ChromaPrint3D not found. Clone the reference project first."
        )
    return root


def resolve_single_stage_colorchecker_assets() -> tuple[str, str | None]:
    """Resolve ColorChecker reference files used by the reference extractor."""
    candidates = [
        _reference_root() / "modeling" / "data" / "ColorChecker",
        Path("assets/ColorChecker").resolve(),
    ]
    for root in candidates:
        ref_json = root / "ColorCheckerjson.json"
        if ref_json.exists():
            ref_desc = root / "desc.txt"
            return str(ref_json), str(ref_desc) if ref_desc.exists() else None
    raise FileNotFoundError("ColorCheckerjson.json not found in reference or assets.")


def _safe_extract_zip(zip_path: str, dest_dir: Path) -> Path:
    resolved_dest_dir = dest_dir.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            for member in archive.infolist():
                member_name = Path(member.filename)
                if member_name.is_absolute() or ".." in member_name.parts:
                    raise ValueError(f"Unsafe zip entry: {member.filename}")
                member_path = (resolved_dest_dir / member_name).resolve()
                try:
                    member_path.relative_to(resolved_dest_dir)
                except ValueError as exc:
                    raise ValueError(f"Unsafe zip entry: {member.filename}") from exc
            archive.extractall(resolved_dest_dir)
    except zipfile.BadZipFile as exc:
        raise ValueError("Malformed ZIP archive") from exc

    children = [p for p in resolved_dest_dir.iterdir() if p.is_dir()]
    if len(children) == 1 and not any(p.is_dir() for p in resolved_dest_dir.iterdir() if p != children[0]):
        return children[0]
    return resolved_dest_dir


def _list_dataset_directories(root: Path) -> list[tuple[Path, Path]]:
    dataset_dirs: list[tuple[Path, Path]] = []
    for substrate_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for color_dir in sorted(p for p in substrate_dir.iterdir() if p.is_dir()):
            dataset_dirs.append((substrate_dir, color_dir))
    return dataset_dirs


def _validate_dataset_root(root: Path) -> dict[str, object]:
    if not root.exists():
        raise FileNotFoundError(f"Dataset root not found: {root}")

    dataset_dirs = _list_dataset_directories(root)
    if not dataset_dirs:
        raise ValueError(
            "Dataset zip must contain {substrate_id}/{color_name}/ directories."
        )

    coverage: dict[str, list[str]] = {}
    image_count = 0
    label_count = 0
    dataset_entries: list[dict[str, object]] = []

    for substrate_dir, color_dir in dataset_dirs:
        label_files = sorted(p for p in color_dir.glob("*.json") if p.is_file())
        image_files = sorted(
            p for p in color_dir.iterdir()
            if p.is_file() and p.suffix.lower() in _IMAGE_EXTENSIONS
        )
        if not label_files:
            try:
                dataset_dir = color_dir.relative_to(root).as_posix()
            except ValueError:
                dataset_dir = color_dir.name
            raise ValueError(
                f"Missing LabelMe JSON files in dataset directory: {dataset_dir}"
            )

        coverage.setdefault(substrate_dir.name, []).append(color_dir.name)
        image_count += len(image_files)
        label_count += len(label_files)
        dataset_entries.append(
            {
                "substrate_id": substrate_dir.name,
                "color_name": color_dir.name,
                "image_count": len(image_files),
                "label_count": len(label_files),
            }
        )

    return {
        "substrate_count": len(coverage),
        "color_count": sum(len(colors) for colors in coverage.values()),
        "dataset_count": len(dataset_entries),
        "image_count": image_count,
        "label_count": label_count,
        "substrates": sorted(coverage.keys()),
        "coverage": [
            {
                "substrate_id": substrate_id,
                "colors": sorted(colors),
            }
            for substrate_id, colors in sorted(coverage.items())
        ],
        "datasets": dataset_entries,
    }


def _run_reference_module(module_name: str, args: list[str]) -> None:
    reference_root = _reference_root()
    command = [sys.executable, "-m", module_name, *args]
    result = subprocess.run(
        command,
        cwd=str(reference_root),
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr or stdout or f"{module_name} failed"
        raise RuntimeError(detail)


def _build_stage_summary(stage_payload: dict[str, object]) -> tuple[dict[str, object], list[str]]:
    datasets = stage_payload.get("datasets") or []
    warnings = list((stage_payload.get("meta") or {}).get("warnings") or [])
    coverage: dict[str, list[str]] = {}
    image_count = 0
    dataset_rows: list[dict[str, object]] = []

    for dataset in datasets:
        substrate_id = str(dataset.get("substrate_id", "unknown"))
        color_name = str(dataset.get("color_name", "unknown"))
        coverage.setdefault(substrate_id, []).append(color_name)
        images = int(dataset.get("image_count") or 0)
        image_count += images
        dataset_rows.append(
            {
                "substrate_id": substrate_id,
                "color_name": color_name,
                "image_count": images,
                "calibration": dataset.get("calibration"),
            }
        )

    summary = {
        "substrate_count": len(coverage),
        "color_count": sum(len(colors) for colors in coverage.values()),
        "dataset_count": len(dataset_rows),
        "image_count": image_count,
        "substrates": sorted(coverage.keys()),
        "coverage": [
            {
                "substrate_id": substrate_id,
                "colors": sorted(colors),
            }
            for substrate_id, colors in sorted(coverage.items())
        ],
        "datasets": dataset_rows,
    }
    return summary, warnings


def extract_single_stage_dataset(
    zip_path: str,
    output_path: str | None = None,
) -> SingleStageExtractResult:
    """Extract a single-stage dataset zip into reference-aligned stage JSON."""
    extract_dir = Path(tempfile.mkdtemp(prefix="single_stage_dataset_", dir=TEMP_DIR))
    try:
        dataset_root = _safe_extract_zip(zip_path, extract_dir)
        validation_summary = _validate_dataset_root(dataset_root)

        if output_path is None:
            output_path = str(Path(TEMP_DIR) / f"single_stage_{uuid.uuid4().hex}.json")

        ref_json, ref_desc = resolve_single_stage_colorchecker_assets()
        args = [
            "--input-root",
            str(dataset_root),
            "--output",
            str(output_path),
            "--ref-json",
            ref_json,
        ]
        if ref_desc:
            args.extend(["--ref-desc", ref_desc])

        _run_reference_module("modeling.pipeline.step1_extract_stages", args)
        payload = json.loads(Path(output_path).read_text(encoding="utf-8"))
        dataset_summary, warnings = _build_stage_summary(payload)
        dataset_summary["uploaded_dataset"] = validation_summary
        return SingleStageExtractResult(
            stage_json_path=str(output_path),
            dataset_summary=dataset_summary,
            warnings=warnings,
            extracted_root=str(extract_dir),
        )
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)


def fit_stage_a_from_stage_json(
    stage_json_path: str,
    output_path: str | None = None,
) -> StageAFitResult:
    """Fit Stage A parameters from extracted single-stage JSON."""
    input_path = Path(stage_json_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Stage JSON not found: {input_path}")

    if output_path is None:
        output_path = str(Path(TEMP_DIR) / f"stage_a_{uuid.uuid4().hex}.json")

    _run_reference_module(
        "modeling.pipeline.step2_fit_stage_a",
        [
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
    )

    payload = json.loads(Path(output_path).read_text(encoding="utf-8"))
    fitted_substrates = payload.get("fitted_substrates") or {}
    channels = (payload.get("parameters") or {}).get("channels") or []
    fit_summary = {
        "substrate_count": len(fitted_substrates),
        "channel_count": len(channels),
        "substrates": sorted(fitted_substrates.keys()),
        "colors": [str(channel.get("color_name", "")) for channel in channels],
        "overall_validation": (payload.get("validation") or {}).get("overall") or {},
        "warnings": list((payload.get("meta") or {}).get("warnings") or []),
    }
    return StageAFitResult(
        params_path=str(output_path),
        fit_summary=fit_summary,
    )


def cleanup_single_stage_extract_root(path: str | None) -> None:
    """Best-effort cleanup for extracted dataset roots."""
    if not path:
        return
    shutil.rmtree(path, ignore_errors=True)
