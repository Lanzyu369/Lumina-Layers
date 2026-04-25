"""Guardrails for logging and exception governance in production paths."""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ROOT / "api" / "app.py",
    ROOT / "api" / "file_bridge.py",
    ROOT / "api" / "routers" / "converter",
    ROOT / "api" / "routers" / "extractor.py",
    ROOT / "api" / "routers" / "vectorizer.py",
    ROOT / "api" / "workers" / "converter_workers.py",
    ROOT / "api" / "workers" / "vectorizer_workers.py",
    ROOT / "core" / "converter.py",
    ROOT / "core" / "extractor.py",
    ROOT / "core" / "image_processing.py",
    ROOT / "core" / "heightmap_loader.py",
    ROOT / "core" / "mesh_generators.py",
    ROOT / "core" / "image_preprocessor.py",
    ROOT / "core" / "pipeline" / "s01_input_validation.py",
    ROOT / "core" / "pipeline" / "s03_color_replacement.py",
    ROOT / "core" / "pipeline" / "s04_debug_preview.py",
    ROOT / "core" / "pipeline" / "s06_voxel_building.py",
    ROOT / "core" / "pipeline" / "s07_mesh_generation.py",
    ROOT / "core" / "pipeline" / "s08_auxiliary_meshes.py",
    ROOT / "core" / "pipeline" / "s09_export_3mf.py",
    ROOT / "core" / "pipeline" / "s11_glb_preview.py",
    ROOT / "core" / "pipeline" / "coordinator.py",
    ROOT / "core" / "pipeline" / "p01_preview_validation.py",
    ROOT / "core" / "pipeline" / "pipeline_utils.py",
    ROOT / "core" / "pipeline" / "processing_ops" / "bilateral_filter.py",
    ROOT / "core" / "pipeline" / "processing_ops" / "median_filter.py",
    ROOT / "core" / "pipeline" / "processing_ops" / "image_scaler.py",
    ROOT / "core" / "pipeline" / "processing_ops" / "lut_color_matcher.py",
    ROOT / "core" / "pipeline" / "processing_ops" / "kmeans_quantizer.py",
    ROOT / "core" / "pipeline" / "processing_ops" / "svg_rasterizer.py",
    ROOT / "core" / "pipeline" / "processing_ops" / "lut_loader.py",
    ROOT / "core" / "vector_engine.py",
    ROOT / "core" / "calibration.py",
]
EXCEPT_EXCEPTION_BASELINE = 39


def _iter_py_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.rglob("*.py"))


def _collect_text() -> str:
    chunks: list[str] = []
    for target in TARGETS:
        for file_path in _iter_py_files(target):
            chunks.append(file_path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def test_no_business_print_in_hot_paths() -> None:
    """Production hot paths should not use raw print()."""
    combined = _collect_text()
    assert "print(" not in combined


def test_except_exception_count_does_not_increase() -> None:
    """Catch-all exceptions may exist but should not grow."""
    combined = _collect_text()
    count = len(re.findall(r"\bexcept Exception\b", combined))
    assert count <= EXCEPT_EXCEPTION_BASELINE
