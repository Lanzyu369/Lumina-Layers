"""Guardrails for logging and exception governance in production paths."""

from __future__ import annotations

from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ROOT / "api" / "app.py",
    ROOT / "api" / "file_bridge.py",
    ROOT / "api" / "routers" / "calibration.py",
    ROOT / "api" / "routers" / "converter",
    ROOT / "api" / "routers" / "extractor.py",
    ROOT / "api" / "routers" / "feedback.py",
    ROOT / "api" / "routers" / "five_color.py",
    ROOT / "api" / "routers" / "lut.py",
    ROOT / "api" / "routers" / "material_registry.py",
    ROOT / "api" / "routers" / "material_sync.py",
    ROOT / "api" / "material_sync_scheduler.py",
    ROOT / "api" / "routers" / "slicer.py",
    ROOT / "api" / "routers" / "system.py",
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
EXCEPT_EXCEPTION_BASELINE = 65
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}
VECTOR_STRUCTURED_EVENTS = {
    "vector_branch_init",
    "vector_branch_done",
    "vector_branch_failed",
    "vector_matched_rgb_overrides_applied",
    "vector_matched_rgb_overrides_failed",
    "vector_overrides_input_invalid",
    "vector_overrides_grid_mismatch",
    # DEBUG-level structured event kept in the inventory.
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
    "vector_generate_timings",
    "vector_preview_timings",
    "vector_lut_palette_extract_failed",
    "vector_color_replacements_load_failed",
    "vector_polygon_extrude_failed",
    "vector_recipe_region_mask_skipped",
    "vector_recipe_region_masks_missing",
    # Appearance-layer missing-color diagnostics (外观面缺色块排查日志)
    "vector_appearance_diag_run_dropped_by_channel_guard",
    "vector_appearance_diag_run_dropped_by_slot_guard",
    "vector_appearance_diag_normalize_emptied",
    "vector_appearance_diag_shape_recipe_short",
    "vector_appearance_diag_run_summary",
    # Layer-0 (appearance face) flow diagnostics — all DEBUG-level. Used to
    # track how the appearance layer's channel distribution evolves across
    # 8 instrumentation points (solver cache reindex/reversal sample,
    # _match_colors per-unique-color summary, preview material_matrix
    # layer 0 hist, generate-loaded material_matrix layer 0 hist,
    # apply_matched_rgb per-shape vote details, recipe[0] hists after both
    # overrides, build_mesh input recipe samples). Run with
    # LUMINA_LOG_LEVEL=DEBUG and grep ``vector_diag_*``.
    # 外观面 layer 0 数据流诊断（全 DEBUG）：8 个阶段的通道分布对比，
    # 用于定位"外观面缺色"的注入点。
    "vector_diag_solver_cache_layer_order",
    "vector_diag_match_colors_summary",
    "vector_diag_preview_material_matrix_layer0",
    "vector_diag_generate_loaded_material_matrix_layer0",
    "vector_diag_apply_matched_rgb_per_shape",
    "vector_diag_after_matched_rgb_overrides_recipe0",
    "vector_diag_after_recipe_overrides_recipe0",
    "vector_diag_build_mesh_input_recipes",
    "vector_diag_extrude_skipped_non_polygon",
    "vector_diag_extrude_skipped_empty",
    "vector_diag_debug_dump",
    "vector_diag_unary_union_area_loss",
    "vector_diag_normalize_area_loss",
    # Per-layer per-channel A/B/C/D matrix to localize "which (layer, channel)
    # loses how many shape blocks at which sub-stage of build_mesh".
    # 阶段 A/B/C/D 逐层逐通道矩阵：精确定位"哪一层哪个通道在 build_mesh 哪
    # 个子阶段丢失了多少个色块"。
    "vector_diag_stage_a_preview_per_layer_channel",
    "vector_diag_stage_b_before_build_mesh_per_layer_channel",
    "vector_diag_stage_c_run_groups_per_layer_channel",
    "vector_diag_stage_d_built_meshes_per_layer_channel",
    # Spec svg-vector-outline-support / Task 3.2: DEBUG-level confirmation
    # that a vector + enable_outline=True request was faithfully forwarded
    # from the worker into pipeline ctx. Listed here so the inventory
    # whitelist test recognizes the literal; not promoted to INFO and not
    # part of the per-request INFO budget.
    # 规范 svg-vector-outline-support / Task 3.2：vector + outline 请求被
    # worker 忠实写入 ctx 的 DEBUG 级确认事件；登记到事件清单白名单，但不
    # 进入每请求 INFO 预算。
    "vector_outline_normalized",
    # Spec svg-vector-outline-support / Task 3.3: vector_branch.py +
    # vector_preview_branch inject an Outline mesh derived from
    # analysis.matched_shapes. INFO double-step (init/done) stays under the
    # 8 INFO/request budget; rejected_unsupported is WARNING-only.
    # 规范 svg-vector-outline-support / Task 3.3：vector / preview 双端注入
    # Outline mesh，几何来源为 analysis.matched_shapes union；init/done 双段
    # INFO 不超出每请求 8 条预算，rejected_unsupported 为 WARNING。
    "vector_outline_init",
    "vector_outline_done",
    "vector_outline_rejected_unsupported",
    "vector_outline_polygon_extrude_failed",
}
EXTRACTOR_STRUCTURED_EVENTS = {
    "extractor_extract_done",
    "extractor_merge_8color_done",
    "extractor_merge_5color_extended_done",
    "extractor_manual_fix_done",
    "extractor_preview_wb_done",
    "extractor_rotate_done",
    "extractor_colorchecker_warp_preview_done",
    "extractor_colorchecker_source_done",
    "extractor_colorchecker_detect_chart_done",
    "extractor_colorchecker_calibrate_done",
    "extractor_colorchecker_release_done",
    "extractor_colorchecker_confirm_done",
    "extractor_colorchecker_touch_done",
    "extractor_confirm_palette_done",
    "extractor_extract_single_stage_done",
    "extractor_fit_stage_a_done",
    "extractor_extract_gradient_card_stage_a_done",
    "extractor_save_gradient_card_material_done",
    "extractor_delete_gradient_card_material_done",
    "extractor_update_gradient_card_material_done",
    "extractor_export_gradient_card_materials_done",
    "extractor_import_gradient_card_materials_done",
    "material_solver_cache_status_done",
    "material_solver_cache_build_done",
    "material_solver_cache_delete_done",
    "material_solver_cache_details_done",
    "material_solver_cache_suggest_colors_done",
    "material_solver_runtime_status_done",
    "material_solver_runtime_build_done",
    "material_solver_runtime_delete_done",
    "material_solver_runtime_details_done",
}
MATERIAL_SYNC_STRUCTURED_EVENTS = {
    "material_seed_install_done",
    "material_seed_install_failed",
    "material_sync_status_done",
    "material_sync_catalog_done",
    "material_sync_install_done",
    "material_sync_install_failed",
    "material_sync_install_from_registry_done",
    "material_sync_install_from_registry_failed",
    "material_sync_refresh_done",
    "material_sync_rollback_done",
    "material_sync_rollback_failed",
    "material_sync_status_failed",
    "material_sync_auto_refresh_scheduled",
    "material_sync_auto_refresh_done",
    "material_sync_auto_refresh_failed",
    "material_sync_auto_refresh_skipped",
}
MATERIAL_REGISTRY_STRUCTURED_EVENTS = {
    "material_registry_catalog_done",
    "material_registry_package_download_done",
    "material_registry_package_upload_done",
    "material_registry_package_approve_done",
}
CONVERTER_STRUCTURED_EVENTS = {
    "converter_region_replace_timing",
    "converter_replace_color_done",
    "converter_reset_replacements_done",
    "converter_source_color_pick_done",
    "converter_color_highlight_done",
    "converter_region_detect_done",
    "converter_region_requantize_done",
    "converter_replace_colors_batch_done",
    "converter_region_replace_batch_done",
    "converter_predict_recipe_done",
    "converter_apply_recipe_override_done",
    "converter_region_recipe_done",
    "converter_merge_colors_done",
    "converter_generate_large_format_done",
    "converter_puzzle_layout_preview_done",
    "converter_puzzle_generate_done",
    "converter_auto_detect_colors_done",
    "converter_cleanup_session_files_done",
    # Auxiliary material-archive usage tracking. The success path has no
    # dedicated event (per-archive bookkeeping piggybacks on the existing
    # ``converter_generate_*`` events); only the failure path is logged so
    # operators can see when the sidecar write fell through.
    # 耗材使用次数辅助统计：成功路径靠生成端点既有 done 事件覆盖；这里只记录
    # 边车写入失败的 WARNING 事件。
    "material_usage_record_failed",
    # Batch merge 3MF structured events (批量合并 3MF 流程日志)
    "converter_batch_item_failed",
    "batch_merge_3mf_init",
    "batch_merge_3mf_done",
    "batch_merge_plate_overflow_warning",
    "batch_merge_3mf_failed",
    "batch_merge_intermediate_cleanup_failed",
}
CALIBRATION_STRUCTURED_EVENTS = {
    "calibration_generate_done",
    "calibration_generate_single_stage_kit_done",
}
FIVE_COLOR_STRUCTURED_EVENTS = {
    "five_color_query_done",
    "five_color_generate_swatch_done",
    "five_color_base_colors_done",
}
VECTORIZER_STRUCTURED_EVENTS = {
    "vectorize_image_done",
    "vectorize_image_failed",
}
LUT_STRUCTURED_EVENTS = {
    "lut_compare_done",
    "lut_details_catalog_failed",
    "lut_details_done",
    "lut_details_failed",
    "lut_merge_done",
    "lut_recipe_color_prediction_failed",
    "lut_recipe_search_failed",
    "lut_session_info_done",
    "lut_upload_done",
    "lut_upload_failed",
    "lut_upload_validation_failed",
}
SYSTEM_STRUCTURED_EVENTS = {
    "system_image_preview_done",
    "system_save_settings_done",
    "system_preview_resource_done",
    "system_preview_artifact_done",
}
FEEDBACK_STRUCTURED_EVENTS = {
    "feedback_bug_report_rate_limited",
    "feedback_bug_report_relay_done",
    "feedback_bug_report_relay_failed",
    "feedback_bug_report_relay_unconfigured",
    "feedback_bug_report_submitted",
    "feedback_ticket_assembled_init",
    "feedback_ticket_assembled_done",
    "feedback_ticket_assembled_failed",
    "feedback_attachment_collected",
    "feedback_attachment_collection_failed",
    "feedback_attachment_lookup_failed",
    "feedback_materials_bundle_packed_done",
    "feedback_materials_bundle_packed_failed",
    "feedback_materials_bundle_timeout",
    "feedback_materials_dir_missing",
    "feedback_materials_dir_invalid",
    "feedback_screenshot_too_large",
    "feedback_screenshot_invalid",
    "feedback_dump_failed",
    "feedback_ticket_sequence_exhausted",
    "feedback_ticket_scan_failed",
    "feedback_ticket_assembly_interrupted",
    "feedback_startup_cleanup_failed",
    "feedback_config_invalid_env",
    "feedback_config_negative_env",
    "feedback_smtp_unconfigured",
    "feedback_email_attachment_skipped",
    "feedback_email_failed",
    "feedback_advanced_params_failed",
}
SLICER_STRUCTURED_EVENTS = {
    "slicer_launch_done",
}
REQUIRED_STRUCTURED_EVENTS = (
    VECTOR_STRUCTURED_EVENTS
    | EXTRACTOR_STRUCTURED_EVENTS
    | MATERIAL_SYNC_STRUCTURED_EVENTS
    | MATERIAL_REGISTRY_STRUCTURED_EVENTS
    | CONVERTER_STRUCTURED_EVENTS
    | CALIBRATION_STRUCTURED_EVENTS
    | FIVE_COLOR_STRUCTURED_EVENTS
    | VECTORIZER_STRUCTURED_EVENTS
    | LUT_STRUCTURED_EVENTS
    | SYSTEM_STRUCTURED_EVENTS
    | FEEDBACK_STRUCTURED_EVENTS
    | SLICER_STRUCTURED_EVENTS
)


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
    violations: list[str] = []
    for target in PRINT_TARGETS:
        for file_path in _iter_py_files(target):
            tree = _parse_py_file(file_path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Name) and node.func.id == "print":
                    violations.append(_relative_location(file_path, node))

    assert not violations, "Raw print() calls found: " + ", ".join(violations)


def test_except_exception_count_does_not_increase() -> None:
    """Catch-all exceptions may exist but should not grow.

    Baseline last bumped from 60 -> 65 by the v2 GLB mesh kernel work in
    ``core/pipeline/s11_glb_preview.py`` (delta = +5). Note: the previous
    in-tree baseline value of 61 was a `<=` ceiling, not an exact count;
    actual pre-change total was 60. The five new ``except Exception`` sites
    in ``s11_glb_preview.py`` are all explicit boundary guards around
    third-party C-extension calls; each one logs a structured WARNING with
    actionable extras (event + error_type / error_message / value /
    import_error / components / failed_component_index / fallback_kernel
    as appropriate) rather than silently swallowing the failure. The five
    sites:

    1. ``_v2_available()`` — guards the ``import rasterio.features`` /
       ``import manifold3d`` probe; emits ``glb_kernel_v2_unavailable``.
    2. ``_build_color_extruded_mesh_v2`` import block — guards the same
       imports inside the helper hot path; emits
       ``glb_kernel_v2_import_failed``.
    3. ``_build_color_extruded_mesh_v2`` rasterio polygonize block —
       guards ``rasterio.features.shapes`` runtime exceptions; emits
       ``glb_kernel_v2_polygonize_failed``.
    4. ``_build_color_extruded_mesh_v2`` per-component
       ``CrossSection.extrude`` — guards manifold3d C-extension failures
       inside the component loop; emits ``glb_kernel_v2_no_manifolds``
       and aborts the whole color (atomic: any per-component failure
       returns None so the dispatcher transparently falls back to v1
       and rebuilds the full mesh, preserving v2 ↔ v1 volume / XY parity).
    5. ``_build_color_extruded_mesh_v2`` ``Manifold.compose`` /
       ``to_mesh`` block — guards the final aggregation call; emits
       ``glb_kernel_v2_compose_failed``.

    See ``.kiro/specs/glb-preview-mesh-kernel-optimization/design.md``
    Error Handling table for the full event catalog.
    """
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


def _is_safe_log_call(node: ast.Call) -> bool:
    """Detect _safe_log(level, event, ...) helper pattern."""
    func = node.func
    return isinstance(func, ast.Name) and func.id == "_safe_log"


def _is_material_sync_error_helper_call(node: ast.Call) -> bool:
    """Detect _raise_material_sync_error(event=...) helper calls."""
    func = node.func
    return isinstance(func, ast.Name) and func.id == "_raise_material_sync_error"


def test_no_starlog_catchall_event_names() -> None:
    """Structured event names should describe real events, not generic log buckets."""
    violations: list[str] = []
    literal_events: set[str] = set()
    for file_path in _iter_governance_py_files():
        tree = _parse_py_file(file_path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Pattern 1: log.info(..., extra={"event": "<literal>", ...})
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
            # Pattern 2: _safe_log(level, "event_name", ...) — second positional
            # arg is the event name literal.
            if _is_safe_log_call(node) and len(node.args) >= 2:
                second_arg = node.args[1]
                if isinstance(second_arg, ast.Constant) and isinstance(
                    second_arg.value, str
                ):
                    event_name = second_arg.value
                    literal_events.add(event_name)
                    if event_name.endswith("_log"):
                        violations.append(
                            _relative_location(file_path, second_arg)
                        )
            # Pattern 3: _raise_material_sync_error(event="event_name", ...)
            # centralizes handled HTTP error logging while preserving literal
            # structured event names for governance.
            if _is_material_sync_error_helper_call(node):
                for keyword in node.keywords:
                    if keyword.arg != "event":
                        continue
                    event_arg = keyword.value
                    if isinstance(event_arg, ast.Constant) and isinstance(
                        event_arg.value, str
                    ):
                        event_name = event_arg.value
                        literal_events.add(event_name)
                        if event_name.endswith("_log"):
                            violations.append(
                                _relative_location(file_path, event_arg)
                            )

    assert not violations, "Catch-all *_log events found: " + ", ".join(violations)
    missing = sorted(REQUIRED_STRUCTURED_EVENTS - literal_events)
    assert not missing, "Required structured events missing: " + ", ".join(missing)
