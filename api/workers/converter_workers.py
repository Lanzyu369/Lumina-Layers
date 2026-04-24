"""Top-level worker functions for converter CPU tasks.
Converter CPU 任务的顶层工作函数。

These functions run in separate processes via ProcessPoolExecutor.
All arguments must be picklable (file paths, scalars, dicts of scalars).
这些函数通过 ProcessPoolExecutor 在独立进程中运行。
所有参数必须可序列化（文件路径、标量、标量字典）。

Design rules:
- Top-level functions only (no methods) — must be picklable.
- Accept only file paths (str) and scalar parameters (int, float, bool, str, dict).
- NEVER accept numpy arrays, PIL Images, or complex objects.
- Large results (images, cache data) are written to temp files; paths are returned.
- All imports of core modules are lazy (inside function body).
"""

_HIGH_FIDELITY_PIXELS_PER_MM = 10.0


def _normalize_puzzle_piece_target_width(image_path: str, params: dict) -> dict:
    """Stabilize puzzle-piece width against float truncation artifacts.
    规整拼图块宽度，避免浮点截断导致的单像素偏差。
    """

    piece_boundary_geometry_path = params.get("piece_boundary_geometry_path")
    target_width_mm = params.get("target_width_mm")
    modeling_mode = params.get("modeling_mode")

    modeling_mode_value = modeling_mode.value if hasattr(modeling_mode, "value") else modeling_mode
    if (
        not piece_boundary_geometry_path
        or target_width_mm is None
        or modeling_mode_value != "high-fidelity"
    ):
        return params

    try:
        from PIL import Image

        with Image.open(image_path) as image:
            source_width_px = int(image.width)
    except (OSError, ValueError):
        return params

    target_width_mm_value = float(target_width_mm)
    truncated_width_px = max(1, int(target_width_mm_value * _HIGH_FIDELITY_PIXELS_PER_MM))
    rounded_width_px = max(1, int(round(target_width_mm_value * _HIGH_FIDELITY_PIXELS_PER_MM)))
    if truncated_width_px == rounded_width_px or source_width_px != rounded_width_px:
        return params

    normalized_params = dict(params)
    normalized_params["target_width_mm"] = (source_width_px + 1e-6) / _HIGH_FIDELITY_PIXELS_PER_MM
    return normalized_params


def worker_generate_preview(
    image_path: str,
    lut_path: str,
    target_width_mm: float,
    auto_bg: bool,
    bg_tol: int,
    color_mode: str,
    modeling_mode: str,
    color_layers: int | None,
    layer_height_mm: float | None,
    quantize_colors: int,
    enable_cleanup: bool,
    is_dark: bool = True,
    model_enable: bool = False,
    model_only: bool = False,
    model_threshold: float | None = None,
    model_margin: float | None = None,
    hue_weight: float = 0.0,
    chroma_gate: float = 15.0,
    material_source: str = "lut",
    selected_materials: list[str] | None = None,
    material_layer_count: int | None = None,
    material_layer_height_mm: float | None = None,
    material_grid_resolution: int | None = None,
) -> dict:
    """Execute preview generation in a worker process.
    在工作进程中执行预览生成。

    Calls ``core.converter.generate_preview_cached`` with the supplied
    scalar parameters, serialises the resulting preview image and cache
    data to temporary files, and returns a dict of file paths.

    Args:
        image_path (str): Path to the input image file. (输入图像文件路径)
        lut_path (str): Path to the LUT calibration file (.npy/.npz). (LUT 校准文件路径)
        target_width_mm (float): Target physical width in mm. (目标物理宽度，毫米)
        auto_bg (bool): Enable automatic background removal. (启用自动背景移除)
        bg_tol (int): Background tolerance value. (背景容差值)
        color_mode (str): Color system mode, e.g. "CMYW". (色彩系统模式)
        modeling_mode (str): Modeling mode string value, e.g. "high-fidelity". (建模模式字符串)
        quantize_colors (int): Number of K-Means quantization colors. (K-Means 量化颜色数)
        enable_cleanup (bool): Enable isolated-pixel cleanup. (启用孤立像素清理)
        is_dark (bool): Dark theme flag for 2D preview bed colors. (深色主题标志)

    Returns:
        dict: Result dictionary with keys: (结果字典，包含以下键)
            - preview_png_path (str | None): Path to saved preview PNG.
            - cache_data_path (str | None): Path to pickled cache data.
            - status_msg (str): Status message from the converter.
    """
    # Lazy imports — executed inside the worker process
    import os
    import pickle
    import tempfile
    import time as _time

    import numpy as np
    from PIL import Image

    from config import ModelingMode
    from core.converter import generate_preview_cached
    from api.structured_logging import get_logger

    log = get_logger(__name__)

    # Convert string modeling_mode to enum
    mode_enum = ModelingMode(modeling_mode)
    _t_worker_start = _time.perf_counter()

    log.info(
        "Worker preview started",
        extra={
            "event": "worker_preview_started",
            "hue_weight": hue_weight,
            "chroma_gate": chroma_gate,
            "lut_path": lut_path,
            "image_name": os.path.basename(image_path),
            "target_width_mm": target_width_mm,
            "color_mode": color_mode,
            "modeling_mode": modeling_mode,
            "color_layers": color_layers,
            "layer_height_mm": layer_height_mm,
            "quantize_colors": quantize_colors,
            "enable_cleanup": enable_cleanup,
            "material_source": material_source,
            "selected_material_count": len(selected_materials or []),
            "material_grid_resolution": material_grid_resolution,
            "model_enable": model_enable,
            "model_only": model_only,
        },
    )
    try:
        preview_img, cache_data, status_msg = generate_preview_cached(
            image_path=image_path,
            lut_path=lut_path,
            target_width_mm=target_width_mm,
            auto_bg=auto_bg,
            bg_tol=bg_tol,
            color_mode=color_mode,
            modeling_mode=mode_enum,
            color_layers=color_layers,
            layer_height_mm=layer_height_mm,
            model_enable=model_enable,
            model_only=model_only,
            model_threshold=model_threshold,
            model_margin=model_margin,
            quantize_colors=quantize_colors,
            enable_cleanup=enable_cleanup,
            is_dark=is_dark,
            hue_weight=hue_weight,
            chroma_gate=chroma_gate,
            material_source=material_source,
            selected_materials=selected_materials,
            material_layer_count=material_layer_count,
            material_layer_height_mm=material_layer_height_mm,
            material_grid_resolution=material_grid_resolution,
        )
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as e:
        log.exception(
            "Worker preview failed",
            extra={
                "event": "worker_preview_failed",
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        raise

    preview_array_shape = list(preview_img.shape) if isinstance(preview_img, np.ndarray) else None
    if isinstance(preview_img, np.ndarray):
        if preview_img.ndim >= 2:
            preview_image_size = [int(preview_img.shape[1]), int(preview_img.shape[0])]
        else:
            preview_image_size = [int(preview_img.shape[0])]
    else:
        preview_image_size = list(preview_img.size) if hasattr(preview_img, "size") else None

    log.info(
        "Worker preview core conversion complete",
        extra={
            "event": "worker_preview_core_done",
            "duration_ms": round((_time.perf_counter() - _t_worker_start) * 1000, 3),
            "status_msg": status_msg,
            "cache_data_ready": cache_data is not None,
            "preview_array_shape": preview_array_shape,
            "preview_image_size": preview_image_size,
        },
    )

    result: dict = {
        "status_msg": status_msg,
        "preview_png_path": None,
        "cache_data_path": None,
    }

    if preview_img is None:
        log.warning(
            "Worker preview returned no image",
            extra={
                "event": "worker_preview_no_image",
                "status_msg": status_msg,
            },
        )
        # Surface the domain error to the API layer so the 500 response
        # includes the actual pipeline error instead of an opaque fallback.
        raise RuntimeError(status_msg or "Preview generation failed")

    _t_serial_start = _time.perf_counter()

    # Write preview image to a temp PNG file
    from config import TEMP_DIR

    _t = _time.perf_counter()
    if preview_img is not None:
        fd, png_path = tempfile.mkstemp(suffix=".png", dir=TEMP_DIR)
        os.close(fd)
        if isinstance(preview_img, np.ndarray):
            Image.fromarray(preview_img).save(png_path)
        else:
            preview_img.save(png_path)
        result["preview_png_path"] = png_path
    _t_png = _time.perf_counter() - _t

    # Pickle cache data to a temp file
    _t = _time.perf_counter()
    if cache_data is not None:
        fd, cache_path = tempfile.mkstemp(suffix=".pkl", dir=TEMP_DIR)
        os.close(fd)
        with open(cache_path, "wb") as f:
            pickle.dump(cache_data, f)
        result["cache_data_path"] = cache_path
    _t_pkl = _time.perf_counter() - _t

    log.info(
        "Worker preview serialization complete",
        extra={
            "event": "worker_preview_serialization_done",
            "png_save_ms": round(_t_png * 1000, 3),
            "pickle_dump_ms": round(_t_pkl * 1000, 3),
            "duration_ms": round((_time.perf_counter() - _t_serial_start) * 1000, 3),
            "worker_total_ms": round((_time.perf_counter() - _t_worker_start) * 1000, 3),
            "preview_png_bytes": os.path.getsize(result["preview_png_path"]) if result["preview_png_path"] else None,
            "cache_data_bytes": os.path.getsize(result["cache_data_path"]) if result["cache_data_path"] else None,
        },
    )

    return result


def worker_batch_convert_item(
    image_path: str,
    lut_path: str,
    target_width_mm: float,
    spacer_thick: float,
    structure_mode: str,
    auto_bg: bool,
    bg_tol: int,
    color_mode: str,
    modeling_mode_value: str,
    color_layers: int | None,
    layer_height_mm: float | None,
    quantize_colors: int,
    enable_cleanup: bool,
    hue_weight: float = 0.0,
    chroma_gate: float = 15.0,
) -> dict:
    """Execute a single batch conversion item in a worker process.
    在工作进程中执行单个批量转换项。

    Calls ``core.converter.convert_image_to_3d`` with the supplied
    scalar parameters and returns a dict containing the output file path
    and status message.

    Args:
        image_path (str): Path to the input image file. (输入图像文件路径)
        lut_path (str): Path to the LUT calibration file. (LUT 校准文件路径)
        target_width_mm (float): Target physical width in mm. (目标物理宽度，毫米)
        spacer_thick (float): Backing plate thickness in mm. (底板厚度，毫米)
        structure_mode (str): Print structure mode, e.g. "Double-sided". (打印结构模式)
        auto_bg (bool): Enable automatic background removal. (启用自动背景移除)
        bg_tol (int): Background tolerance value. (背景容差值)
        color_mode (str): Color system mode, e.g. "4-Color". (色彩系统模式)
        modeling_mode_value (str): Modeling mode string, e.g. "high-fidelity". (建模模式字符串)
        quantize_colors (int): Number of K-Means quantization colors. (K-Means 量化颜色数)
        enable_cleanup (bool): Enable isolated-pixel cleanup. (启用孤立像素清理)

    Returns:
        dict: Result dictionary with keys: (结果字典，包含以下键)
            - threemf_path (str | None): Path to the generated .3mf file.
            - status_msg (str): Status message from the converter.
    """
    # Lazy imports — executed inside the worker process
    from config import ModelingMode
    from core.converter import convert_image_to_3d

    core_modeling_mode = ModelingMode(modeling_mode_value)

    threemf_path, _glb_path, _preview_img, status_msg, _recipe = convert_image_to_3d(
        image_path=image_path,
        lut_path=lut_path,
        target_width_mm=target_width_mm,
        spacer_thick=spacer_thick,
        structure_mode=structure_mode,
        auto_bg=auto_bg,
        bg_tol=bg_tol,
        color_mode=color_mode,
        color_layers=color_layers,
        layer_height_mm=layer_height_mm,
        add_loop=False,
        loop_width=4.0,
        loop_length=8.0,
        loop_hole=2.5,
        loop_pos=None,
        modeling_mode=core_modeling_mode,
        quantize_colors=quantize_colors,
        enable_cleanup=enable_cleanup,
        hue_weight=hue_weight,
        chroma_gate=chroma_gate,
    )

    return {
        "threemf_path": threemf_path,
        "status_msg": status_msg,
    }


def worker_generate_model(
    image_path: str,
    lut_path: str,
    params: dict,
) -> dict:
    """Execute 3MF model generation in a worker process.
    在工作进程中执行 3MF 模型生成。

    Calls ``core.converter.generate_final_model`` with the supplied
    parameters and returns a dict containing the output file paths.

    Args:
        image_path (str): Path to the input image file. (输入图像文件路径)
        lut_path (str): Path to the LUT calibration file (.npy/.npz). (LUT 校准文件路径)
        params (dict): Dict of scalar parameters forwarded to
            ``generate_final_model`` via **kwargs. Keys must match the
            function signature (e.g. target_width_mm, spacer_thick,
            color_mode, modeling_mode, fridge-magnet metadata, etc.).
            (标量参数字典，通过 **kwargs 转发给 generate_final_model，
            包括冰箱贴磁铁槽元数据等字段)

    Returns:
        dict: Result dictionary with keys: (结果字典，包含以下键)
            - threemf_path (str | None): Path to the generated .3mf file.
            - glb_path (str | None): Path to the generated .glb preview file.
            - status_msg (str): Status message from the converter.
    """
    # Lazy imports — executed inside the worker process
    import os
    import time as _time

    from api.structured_logging import get_logger
    from core.converter import generate_final_model

    log = get_logger(__name__)
    normalized_params = _normalize_puzzle_piece_target_width(image_path, params)
    _t_worker_start = _time.perf_counter()
    log.info(
        "Worker model generation started",
        extra={
            "event": "worker_model_started",
            "image_name": os.path.basename(image_path),
            "lut_path": lut_path,
            "target_width_mm": normalized_params.get("target_width_mm"),
            "color_mode": normalized_params.get("color_mode"),
            "modeling_mode": normalized_params.get("modeling_mode"),
            "quantize_colors": normalized_params.get("quantize_colors"),
            "enable_cleanup": normalized_params.get("enable_cleanup"),
            "replacement_count": len(normalized_params.get("replacement_regions") or []),
            "recipe_override_count": len(normalized_params.get("recipe_overrides") or []),
            "free_color_count": len(normalized_params.get("free_color_set") or []),
            "fridge_magnet_count": len(normalized_params.get("fridge_magnets") or []),
            "enable_relief": normalized_params.get("enable_relief"),
            "enable_outline": normalized_params.get("enable_outline"),
            "enable_cloisonne": normalized_params.get("enable_cloisonne"),
        },
    )
    try:
        result_tuple = generate_final_model(
            image_path=image_path,
            lut_path=lut_path,
            **normalized_params,
        )
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as e:
        log.exception(
            "Worker model generation failed",
            extra={
                "event": "worker_model_failed",
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        raise

    # generate_final_model returns:
    # (3mf_path, glb_path, preview_image, status_message, recipe)
    threemf_path, glb_path, _preview, status_msg, _recipe = result_tuple

    log.info(
        "Worker model generation complete",
        extra={
            "event": "worker_model_done",
            "duration_ms": round((_time.perf_counter() - _t_worker_start) * 1000, 3),
            "status_msg": status_msg,
            "threemf_path": threemf_path,
            "threemf_bytes": os.path.getsize(threemf_path) if threemf_path and os.path.exists(threemf_path) else None,
            "glb_path": glb_path,
            "glb_bytes": os.path.getsize(glb_path) if glb_path and os.path.exists(glb_path) else None,
        },
    )

    return {
        "threemf_path": threemf_path,
        "glb_path": glb_path,
        "status_msg": status_msg,
    }


def worker_generate_large_format_svg_native(
    image_path: str,
    lut_path: str,
    params: dict,
) -> dict:
    """Generate a large-format ZIP from one globally analyzed SVG in a worker."""
    import math
    import os
    import tempfile
    import zipfile

    import trimesh

    from config import TEMP_DIR
    from core.pipeline.s03_color_replacement import _normalize_color_replacements_input
    from core.vector_engine import VectorProcessor
    from core.vector_large_format import format_large_format_tile_label, slice_vector_analysis_into_tiles
    from utils.bambu_3mf_writer import export_scene_with_bambu_metadata

    tile_name_prefix = params.get("tile_name_prefix")
    total_width_mm = float(params["total_width_mm"])
    total_height_mm = float(params["total_height_mm"])
    tile_width_mm = float(params["tile_width_mm"])
    tile_height_mm = float(params["tile_height_mm"])
    replacement_regions = params.get("replacement_regions")
    vector_replacements = _normalize_color_replacements_input(replacement_regions)

    vector_processor = VectorProcessor(lut_path, params["color_mode"])
    analysis = vector_processor.analyze_svg(
        svg_path=image_path,
        target_width_mm=total_width_mm,
        color_replacements=vector_replacements,
    )
    tile_analyses = slice_vector_analysis_into_tiles(
        analysis=analysis,
        total_width_mm=total_width_mm,
        total_height_mm=total_height_mm,
        tile_width_mm=tile_width_mm,
        tile_height_mm=tile_height_mm,
    )

    successful_paths: list[tuple[str, str]] = []
    tile_cleanup_paths: set[str] = set()
    zip_path: str | None = None
    zip_ready = False
    try:
        for tile in tile_analyses:
            tile_processor = VectorProcessor(lut_path, params["color_mode"])
            scene = tile_processor.build_mesh(
                analysis=tile.analysis,
                thickness_mm=float(params["spacer_thick"]),
                structure_mode=params["structure_mode"],
            )
            if len(scene.geometry) == 0:
                continue

            preview_colors = dict(tile.analysis.preview_colors)
            slot_names = list(tile.analysis.slot_names)
            for material_id, rgba in list(preview_colors.items()):
                if isinstance(material_id, int) and material_id < len(slot_names):
                    preview_colors[slot_names[material_id]] = rgba

            separate_backing = bool(params.get("separate_backing", False))
            board_geom = scene.geometry.get("Board")
            if board_geom is not None and not separate_backing:
                first_slot = slot_names[0] if slot_names else None
                first_geom = scene.geometry.get(first_slot) if first_slot else None
                if first_geom is not None:
                    merged = trimesh.util.concatenate([first_geom, board_geom])
                    merged.visual.face_colors = first_geom.visual.face_colors
                    merged.metadata["name"] = first_slot
                    scene.geometry[first_slot] = merged
                    del scene.geometry["Board"]
            elif board_geom is not None and separate_backing:
                preview_colors["Board"] = preview_colors.get(0, [255, 255, 255, 255])

            slot_export_names: list[str] = []
            for geom_name, geom in scene.geometry.items():
                vertices = getattr(geom, "vertices", None)
                faces = getattr(geom, "faces", None)
                if vertices is None or faces is None or len(vertices) == 0 or len(faces) == 0:
                    continue
                slot_export_names.append(geom_name)
            if not slot_export_names:
                continue

            fd, tile_3mf_path = tempfile.mkstemp(suffix=".3mf", dir=TEMP_DIR)
            os.close(fd)
            tile_cleanup_paths.add(tile_3mf_path)
            export_scene_with_bambu_metadata(
                scene=scene,
                output_path=tile_3mf_path,
                slot_names=slot_export_names,
                preview_colors=preview_colors,
                settings={
                    "layer_height": "0.08",
                    "initial_layer_height": "0.08",
                    "wall_loops": "1",
                    "top_shell_layers": "0",
                    "bottom_shell_layers": "0",
                    "sparse_infill_density": "100%",
                    "sparse_infill_pattern": "zig-zag",
                    "nozzle_temperature": ["220"] * 8,
                    "bed_temperature": ["60"] * 8,
                    "filament_type": ["PLA"] * 8,
                    "print_speed": "100",
                    "travel_speed": "150",
                    "enable_support": "0",
                    "brim_width": "5",
                    "brim_type": "auto_brim",
                },
                color_mode=tile_processor.color_mode,
                printer_id=params.get("printer_id", "bambu-h2d"),
                slicer=params.get("slicer", "BambuStudio"),
                nozzle_size=params.get("nozzle_size", "0.4"),
            )
            successful_paths.append(
                (
                    format_large_format_tile_label(source_basename=tile_name_prefix, tile_label=tile.label),
                    tile_3mf_path,
                )
            )

        if not successful_paths:
            raise ValueError("All SVG large-format tiles were empty after slicing.")

        fd, zip_path = tempfile.mkstemp(suffix=".zip", dir=TEMP_DIR)
        os.close(fd)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for label, path_3mf in successful_paths:
                zf.write(path_3mf, f"{label}.3mf")
        zip_ready = True

        grid_cols = max(1, math.ceil(total_width_mm / tile_width_mm))
        grid_rows = max(1, math.ceil(total_height_mm / tile_height_mm))

        return {
            "zip_path": zip_path,
            "tile_count": len(successful_paths),
            "grid_cols": grid_cols,
            "grid_rows": grid_rows,
            "warnings": [],
        }
    finally:
        for path_3mf in tile_cleanup_paths:
            if os.path.exists(path_3mf):
                os.unlink(path_3mf)
        if zip_path is not None and not zip_ready and os.path.exists(zip_path):
            os.unlink(zip_path)
