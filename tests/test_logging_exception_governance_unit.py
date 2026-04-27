"""Guardrails for logging and exception governance in production paths."""

from __future__ import annotations

from pathlib import Path
import ast
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
PRINT_TARGETS = TARGETS + [
    ROOT / "utils",
]
GOVERNANCE_SCAN_ROOTS = [
    ROOT / "api",
    ROOT / "core",
    ROOT / "utils",
]
EXCEPT_EXCEPTION_BASELINE = 39
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}
VECTOR_STRUCTURED_EVENTS = {
    "vector_branch_init",
    "vector_branch_done",
    "vector_branch_failed",
    "vector_matched_rgb_overrides_applied",
    "vector_matched_rgb_overrides_failed",
    "vector_overrides_input_invalid",
    "vector_overrides_grid_mismatch",
    "vector_overrides_applied",
    "vector_recipe_overrides_load_failed",
    "vector_recipe_overrides_apply_failed",
    "vector_3mf_exported",
    "vector_glb_exported",
    "vector_glb_exported_skipped",
    "vector_2d_preview_skipped",
    "vector_2d_preview_done",
    "vector_2d_preview_failed",
    "vector_board_merged",
    "vector_board_kept",
    "vector_board_separate",
    "vector_geometry_skipped",
    "vector_timings",
    "vector_lut_palette_extract_failed",
    "vector_color_replacements_load_failed",
    "vector_polygon_extrude_failed",
    "vector_recipe_region_mask_skipped",
    "vector_recipe_region_masks_missing",
}


def _iter_py_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.rglob("*.py"))


def _collect_text(targets: list[Path] | None = None) -> str:
    chunks: list[str] = []
    for target in targets or TARGETS:
        for file_path in _iter_py_files(target):
            chunks.append(file_path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def _iter_governance_py_files() -> list[Path]:
    files: list[Path] = []
    for root in GOVERNANCE_SCAN_ROOTS:
        files.extend(_iter_py_files(root))
    return sorted(files)


def _parse_py_file(file_path: Path) -> ast.Module:
    return ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))


def _relative_location(file_path: Path, node: ast.AST) -> str:
    return f"{file_path.relative_to(ROOT)}:{getattr(node, 'lineno', '?')}"


def _is_logger_method_call(node: ast.Call) -> bool:
    func = node.func
    return isinstance(func, ast.Attribute) and func.attr in LOG_METHODS


def test_no_business_print_in_hot_paths() -> None:
    """Production hot paths should not use raw print()."""
    combined = _collect_text(PRINT_TARGETS)
    assert "print(" not in combined


def test_except_exception_count_does_not_increase() -> None:
    """Catch-all exceptions may exist but should not grow."""
    combined = _collect_text()
    count = len(re.findall(r"\bexcept Exception\b", combined))
    assert count <= EXCEPT_EXCEPTION_BASELINE


def test_no_default_event_logger_adapter_imports() -> None:
    """Production modules should use structured get_logger directly."""
    violations: list[str] = []
    for file_path in _iter_governance_py_files():
        tree = _parse_py_file(file_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = {alias.name for alias in node.names}
                if "DefaultEventLoggerAdapter" in names:
                    violations.append(_relative_location(file_path, node))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.endswith("pipeline_logging"):
                        violations.append(_relative_location(file_path, node))

    assert not violations, "DefaultEventLoggerAdapter imports found: " + ", ".join(violations)


def test_no_bracket_tag_in_log_messages() -> None:
    """Structured log messages should not use legacy bracket tag prefixes."""
    violations: list[str] = []
    for file_path in _iter_governance_py_files():
        tree = _parse_py_file(file_path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_logger_method_call(node):
                continue
            if not node.args:
                continue
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                if first_arg.value.lstrip().startswith("["):
                    violations.append(_relative_location(file_path, node))

    assert not violations, "Bracket-prefixed log messages found: " + ", ".join(violations)


def test_no_starlog_catchall_event_names() -> None:
    """Structured event names should describe real events, not generic log buckets."""
    violations: list[str] = []
    literal_events: set[str] = set()
    for file_path in _iter_governance_py_files():
        tree = _parse_py_file(file_path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg != "extra" or not isinstance(keyword.value, ast.Dict):
                    continue
                keys = keyword.value.keys
                values = keyword.value.values
                for key_node, value_node in zip(keys, values):
                    if not (
                        isinstance(key_node, ast.Constant)
                        and key_node.value == "event"
                        and isinstance(value_node, ast.Constant)
                        and isinstance(value_node.value, str)
                    ):
                        continue
                    event_name = value_node.value
                    literal_events.add(event_name)
                    if event_name.endswith("_log"):
                        violations.append(_relative_location(file_path, value_node))

    assert not violations, "Catch-all *_log events found: " + ", ".join(violations)
    missing = sorted(VECTOR_STRUCTURED_EVENTS - literal_events)
    assert not missing, "Vector structured events missing: " + ", ".join(missing)
