"""
LUT 文件加载与格式检测模块（LUT Loader）

从 image_processing.py 的 _load_lut 方法提取。
支持 2色/4色/6色/8色/合并 LUT 格式检测和堆叠配方重建。

LUT file loading and format detection.
Extracted from LuminaImageProcessor._load_lut.
"""

from api.structured_logging import get_logger
from dataclasses import replace
from itertools import permutations
import hashlib
import os
import numpy as np
import cv2
from scipy.spatial import KDTree

from config import PrinterConfig, ColorSystem, get_capabilities, get_source_kind, get_supported_modes, get_asset_path
from core.native_reference import SOURCE_KIND_PACKAGE, SOURCE_KIND_STAGE_MODEL
from core.predictive_lut import list_predictive_supported_modes, resolve_predictive_runtime
from core.recipe_order import convert_recipe_between_orders
from utils.lut_manager import LUTManager

_log = get_logger(__name__)


def _rgb_to_lab(rgb_array: np.ndarray) -> np.ndarray:
    """将 RGB 数组转换为 CIELAB 空间。
    Convert RGB array to CIELAB color space.

    Args:
        rgb_array: numpy array, shape (N, 3) 或 (H, W, 3), dtype uint8

    Returns:
        numpy array, 同 shape, dtype float64, Lab 值
    """
    original_shape = rgb_array.shape
    if rgb_array.ndim == 2:
        rgb_3d = rgb_array.reshape(1, -1, 3).astype(np.uint8)
    else:
        rgb_3d = rgb_array.astype(np.uint8)
    bgr = cv2.cvtColor(rgb_3d, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).astype(np.float64)
    if len(original_shape) == 2:
        return lab.reshape(original_shape)
    return lab


def _build_predictive_info(
    metadata,
    layer_count: int,
    layer_height_mm: float,
    *,
    enable_predictive_matching: bool = True,
    model_threshold: float | None = None,
    model_margin: float | None = None,
) -> dict:
    """Build predictive runtime info from LUT metadata when available.
    在可用时从 LUT 元数据构建预测式运行时信息。
    """
    predictive_modes = list_predictive_supported_modes(metadata)
    predictive_runtime = None
    if enable_predictive_matching:
        predictive_runtime = resolve_predictive_runtime(
            metadata,
            layer_height_mm,
            layer_count,
            getattr(metadata, "layer_order", "Top2Bottom"),
        )
        if predictive_runtime is not None:
            threshold = predictive_runtime.threshold
            margin = predictive_runtime.margin
            if model_threshold is not None and float(model_threshold) >= 0.0:
                threshold = float(model_threshold)
            if model_margin is not None and float(model_margin) >= 0.0:
                margin = float(model_margin)
            predictive_runtime = replace(
                predictive_runtime,
                threshold=float(threshold),
                margin=float(margin),
            )
    supported_modes = [
        dict(item)
        for item in (list_predictive_supported_modes(metadata) or get_supported_modes(metadata))
        if isinstance(item, dict)
    ]
    warnings: list[str] = []
    if enable_predictive_matching and supported_modes and predictive_runtime is None:
        warnings.append("predictive_mode_unavailable")
    capabilities = set(get_capabilities(metadata))
    return {
        "source_kind": get_source_kind(metadata),
        "native_reference_source": "native_reference" in capabilities,
        "predictive_runtime": predictive_runtime,
        "predictive_modes": [str(item.get("mode_key")) for item in supported_modes if item.get("mode_key")],
        "supported_modes": supported_modes,
        "predictive_threshold": (float(predictive_runtime.threshold) if predictive_runtime is not None else None),
        "predictive_margin": (float(predictive_runtime.margin) if predictive_runtime is not None else None),
        "requested_color_layers": int(layer_count),
        "requested_layer_height_mm": float(layer_height_mm),
        "predictive_warnings": warnings,
    }


def _finalize_loaded_lut(
    lut_rgb: np.ndarray,
    ref_stacks: np.ndarray,
    layer_count: int,
    metadata,
    layer_height_mm: float,
    *,
    enable_predictive_matching: bool = True,
    model_threshold: float | None = None,
    model_margin: float | None = None,
) -> dict:
    """Finalize loaded LUT data into the shared runtime payload.
    将已加载的 LUT 数据整理成统一运行时载荷。
    """
    if lut_rgb.size == 0:
        lut_lab = np.zeros((0, 3), dtype=np.float64)
        kdtree = None
        lut_fingerprint = ""
    else:
        lut_lab = _rgb_to_lab(lut_rgb)
        kdtree = KDTree(lut_lab)
        lut_fingerprint = hashlib.sha1(lut_lab.tobytes()).hexdigest()[:12]
    result = {
        "lut_rgb": lut_rgb,
        "lut_lab": lut_lab,
        "ref_stacks": ref_stacks,
        "kdtree": kdtree,
        "layer_count": layer_count,
        "lut_fingerprint": lut_fingerprint,
    }
    result.update(
        _build_predictive_info(
            metadata,
            layer_count,
            layer_height_mm,
            enable_predictive_matching=enable_predictive_matching,
            model_threshold=model_threshold,
            model_margin=model_margin,
        )
    )
    return result


def _maybe_use_native_bundle_exact_lookup(
    lut_rgb: np.ndarray,
    ref_stacks: np.ndarray | None,
    metadata,
    layer_count: int,
    layer_height_mm: float,
) -> tuple[np.ndarray, np.ndarray | None, bool]:
    """Replace native package/stage synthetic lookup with matching bundle ColorDB data."""
    source_kind = get_source_kind(metadata)
    if source_kind not in (SOURCE_KIND_PACKAGE, SOURCE_KIND_STAGE_MODEL):
        return lut_rgb, ref_stacks, False

    bundle_lookup = LUTManager.load_native_bundle_exact_lookup(
        metadata,
        color_layers=layer_count,
        layer_height_mm=layer_height_mm,
        layer_order=getattr(metadata, "layer_order", "Top2Bottom"),
    )
    if bundle_lookup is None:
        return lut_rgb, ref_stacks, False

    bundle_rgb, bundle_stacks = bundle_lookup
    return bundle_rgb, bundle_stacks, True


def _legacy_pure_stack_row_index(
    channel_idx: int,
    base_count: int,
    layer_count: int,
) -> int:
    row_index = 0
    place_value = 1
    for _ in range(layer_count):
        row_index += int(channel_idx) * place_value
        place_value *= int(base_count)
    return row_index


def _infer_legacy_4color_channel_remap(
    measured_colors: np.ndarray,
    color_mode: str,
) -> np.ndarray:
    """Infer raw legacy NPY channel ids from pure-channel measured rows."""
    identity = np.arange(4, dtype=np.int32)
    color_conf = ColorSystem.get(color_mode)
    slots = list(color_conf.get("slots") or [])
    preview = color_conf.get("preview") or {}
    if len(slots) != 4:
        return identity

    canonical_rgb: list[list[int]] = []
    for slot_idx in range(4):
        rgba = preview.get(slot_idx)
        if not rgba or len(rgba) < 3:
            return identity
        canonical_rgb.append([int(rgba[0]), int(rgba[1]), int(rgba[2])])

    pure_rows = [
        _legacy_pure_stack_row_index(channel_idx, 4, PrinterConfig.COLOR_LAYERS)
        for channel_idx in range(4)
    ]
    if measured_colors.shape[0] <= max(pure_rows):
        return identity

    pure_rgb = measured_colors[pure_rows].astype(np.float64, copy=False)
    canonical = np.asarray(canonical_rgb, dtype=np.float64)
    distances = np.linalg.norm(pure_rgb[:, None, :] - canonical[None, :, :], axis=2)
    best_perm = min(
        permutations(range(4)),
        key=lambda perm: float(
            sum(
                distances[raw_idx, slot_idx]
                for raw_idx, slot_idx in enumerate(perm)
            )
        ),
    )
    remap = np.asarray(best_perm, dtype=np.int32)
    if np.array_equal(remap, identity):
        return identity

    _log.debug(
        "Legacy 4-color NPY channel order remapped",
        extra={
            "event": "legacy_4color_npy_channel_remapped",
            "color_mode": str(color_mode),
            "channel_remap": remap.tolist(),
        },
    )
    return remap


def _legacy_4color_blue_like_raw_channels(
    channel_remap: np.ndarray,
    color_mode: str,
) -> frozenset[int]:
    """Return raw channels that map to the mode's blue/cyan-like slot."""
    color_conf = ColorSystem.get(color_mode)
    slots = list(color_conf.get("slots") or [])
    blue_like_slot_ids = {
        slot_idx
        for slot_idx, slot_name in enumerate(slots)
        if str(slot_name).strip().lower() in {"blue", "cyan", "deep blue"}
    }
    if not blue_like_slot_ids:
        return frozenset({3})

    raw_channels = {
        raw_idx
        for raw_idx, slot_idx in enumerate(channel_remap.tolist())
        if int(slot_idx) in blue_like_slot_ids
    }
    return frozenset(raw_channels or {3})


def load_lut(
    lut_path: str,
    color_mode: str,
    *,
    color_layers: int | None = None,
    layer_height_mm: float | None = None,
    model_enable: bool = False,
    model_only: bool = False,
    model_threshold: float | None = None,
    model_margin: float | None = None,
) -> dict:
    """加载 LUT 文件并返回处理后的数据。
    Load and validate LUT file. Supports 2-Color, 4-Color, 6-Color, 8-Color, and Merged.

    统一通过 LUTManager.load_lut_with_metadata() 加载，支持 .npy/.json/.npz 三种格式。
    自动检测 LUT 类型并重建堆叠配方。

    Args:
        lut_path: LUT 文件路径 (.npy/.npz/.json)
        color_mode: 颜色模式字符串 (CMYW/RYBW/6-Color/8-Color/BW/Merged 等)

    Returns:
        dict: 包含以下键的字典
            - lut_rgb: (N, 3) uint8 LUT RGB 数组
            - lut_lab: (N, 3) float64 LUT CIELAB 数组
            - ref_stacks: (N, L) int 材料堆叠配方数组
            - kdtree: scipy.spatial.KDTree 基于 CIELAB 的 KDTree
            - layer_count: int 材料层数
    """
    default_layer_count = ColorSystem.get(color_mode).get("layer_count", PrinterConfig.COLOR_LAYERS)
    layer_count = int(color_layers) if color_layers is not None else int(default_layer_count)
    requested_layer_height_mm = float(layer_height_mm) if layer_height_mm is not None else float(PrinterConfig.LAYER_HEIGHT)

    # ── 统一加载入口 ──────────────────────────────────────────────
    try:
        rgb, stacks, metadata = LUTManager.load_lut_with_metadata(lut_path)
    except (OSError, ValueError, TypeError, KeyError) as e:
        raise ValueError(f"LUT file corrupted: {e}")

    rgb, stacks, native_exact_lookup_active = _maybe_use_native_bundle_exact_lookup(
        rgb,
        stacks,
        metadata,
        layer_count,
        requested_layer_height_mm,
    )
    source_kind = get_source_kind(metadata)
    capabilities = set(get_capabilities(metadata))
    is_native_reference_source = "native_reference" in capabilities
    native_predictive_source = source_kind in (SOURCE_KIND_PACKAGE, SOURCE_KIND_STAGE_MODEL)
    enable_predictive_matching = bool(
        model_only
        or (native_predictive_source and (model_enable or not native_exact_lookup_active))
        or (not is_native_reference_source and source_kind != "legacy_lookup")
    )

    if rgb is None or len(rgb) == 0:
        predictive_runtime = resolve_predictive_runtime(
            metadata,
            requested_layer_height_mm,
            layer_count,
            getattr(metadata, "layer_order", "Top2Bottom"),
        )
        if predictive_runtime is None:
            raise ValueError(f"LUT file is empty or corrupted: {lut_path}")
        lut_rgb = np.zeros((0, 3), dtype=np.uint8)
        ref_stacks = np.zeros((0, layer_count), dtype=np.int32)
        return _finalize_loaded_lut(
            lut_rgb,
            ref_stacks,
            layer_count,
            metadata,
            requested_layer_height_mm,
            enable_predictive_matching=enable_predictive_matching,
            model_threshold=model_threshold,
            model_margin=model_margin,
        )

    # Flatten to (N, 3) if loaded as grid (e.g. old .npy with shape (rows, cols, 3))
    measured_colors = rgb.reshape(-1, 3)
    total_colors = measured_colors.shape[0]

    # Determine if stacks data is usable (non-None, non-empty, has columns)
    has_stacks = (
        stacks is not None
        and isinstance(stacks, np.ndarray)
        and stacks.ndim == 2
        and stacks.shape[0] > 0
        and stacks.shape[1] > 0
    )

    _log.debug(f"Loading LUT with {total_colors} points (has_stacks={has_stacks})...")

    # ── .npz 合并 LUT：直接使用 rgb + stacks ─────────────────────
    if lut_path.endswith(".npz"):
        if has_stacks:
            lut_rgb = measured_colors
            ref_stacks = stacks
            if ref_stacks.ndim == 2 and not (
                color_layers is not None and getattr(metadata, "supports_dynamic_layer_count", lambda: False)()
            ):
                layer_count = int(ref_stacks.shape[1])
            _log.debug(f"Merged LUT loaded: {len(lut_rgb)} colors (.npz format, Lab KDTree)")
            return _finalize_loaded_lut(
                lut_rgb,
                ref_stacks,
                layer_count,
                metadata,
                requested_layer_height_mm,
                enable_predictive_matching=enable_predictive_matching,
                model_threshold=model_threshold,
                model_margin=model_margin,
            )
        else:
            raise ValueError(f"Merged LUT file missing stacks: {lut_path}")

    # ── 如果 stacks 有数据（来自 JSON recipe 或其他格式），直接使用 ──
    if has_stacks and stacks.shape[0] == total_colors:
        lut_rgb = measured_colors
        ref_stacks = stacks
        if ref_stacks.ndim == 2 and not (
            color_layers is not None and getattr(metadata, "supports_dynamic_layer_count", lambda: False)()
        ):
            layer_count = int(ref_stacks.shape[1])
        _log.debug(f"LUT loaded: {len(lut_rgb)} colors (stacks from file, {layer_count} layers)")
        return _finalize_loaded_lut(
            lut_rgb,
            ref_stacks,
            layer_count,
            metadata,
            requested_layer_height_mm,
            enable_predictive_matching=enable_predictive_matching,
            model_threshold=model_threshold,
            model_margin=model_margin,
        )

    # ── 回退：stacks 为空（旧 .npy 文件），从索引重建堆叠配方 ──────
    valid_rgb = []
    valid_stacks = []
    lut_rgb = None
    ref_stacks = None

    # Branch 0: 2-Color BW (32)
    if color_mode == "BW (Black & White)" or color_mode == "BW" or total_colors == 32:
        _log.debug("Detected 2-Color BW mode")

        # Generate all 32 combinations (2^5 = 32)
        for i in range(32):
            if i >= total_colors:
                break

            # Rebuild 2-base stacking (0..31)
            digits = []
            temp = i
            for _ in range(5):
                digits.append(temp % 2)
                temp //= 2
            stack = convert_recipe_between_orders(digits, "Bottom2Top", "Top2Bottom")

            valid_rgb.append(measured_colors[i])
            valid_stacks.append(stack)

        lut_rgb = np.array(valid_rgb)
        ref_stacks = np.array(valid_stacks)
        if isinstance(ref_stacks, np.ndarray) and ref_stacks.ndim == 2:
            layer_count = int(ref_stacks.shape[1])

        _log.debug(f"LUT loaded: {len(lut_rgb)} colors (2-Color BW mode)")

    # Branch 1: 8-Color Max (2738)
    elif "8-Color" in color_mode or total_colors == 2738:
        _log.debug("Detected 8-Color Max mode")

        # Load pre-generated 8-color stacks (预计算资产豁免，保持 np.load)
        stacks_path = get_asset_path("smart_8color_stacks.npy")

        smart_stacks = np.load(stacks_path).tolist()

        # 约定转换：smart_8color_stacks.npy 存储底到顶约定（stack[0]=背面），
        # 转换为顶到底约定（stack[0]=观赏面, stack[4]=背面），与 4 色模式统一
        smart_stacks = [
            tuple(convert_recipe_between_orders(s, "Bottom2Top", "Top2Bottom"))
            for s in smart_stacks
        ]
        _log.debug(
            "Stacks converted from bottom-to-top to top-to-bottom convention (matching 4-color mode)."
        )

        if len(smart_stacks) != total_colors:
            _log.warning(f"Stacks count ({len(smart_stacks)}) != LUT count ({total_colors})")
            min_len = min(len(smart_stacks), total_colors)
            smart_stacks = smart_stacks[:min_len]
            measured_colors = measured_colors[:min_len]

        lut_rgb = measured_colors
        ref_stacks = np.array(smart_stacks)
        if isinstance(ref_stacks, np.ndarray) and ref_stacks.ndim == 2:
            layer_count = int(ref_stacks.shape[1])

        _log.debug(f"LUT loaded: {len(lut_rgb)} colors (8-Color mode)")

    # Branch 2: 6-Color Smart 1296
    elif "6-Color" in color_mode or total_colors == 1296:
        _log.debug("Detected 6-Color Smart 1296 mode")

        from core.calibration import get_top_1296_colors

        smart_stacks = get_top_1296_colors()
        # 约定转换：get_top_1296_colors() 返回底到顶约定（stack[0]=背面），
        # 转换为顶到底约定（stack[0]=观赏面, stack[4]=背面），与 4 色模式统一
        smart_stacks = [
            tuple(convert_recipe_between_orders(s, "Bottom2Top", "Top2Bottom"))
            for s in smart_stacks
        ]
        _log.debug(
            "Stacks converted from bottom-to-top to top-to-bottom convention (matching 4-color mode)."
        )

        if len(smart_stacks) != total_colors:
            _log.warning(f"Stacks count ({len(smart_stacks)}) != LUT count ({total_colors})")
            min_len = min(len(smart_stacks), total_colors)
            smart_stacks = smart_stacks[:min_len]
            measured_colors = measured_colors[:min_len]

        lut_rgb = measured_colors
        ref_stacks = np.array(smart_stacks)
        if isinstance(ref_stacks, np.ndarray) and ref_stacks.ndim == 2:
            layer_count = int(ref_stacks.shape[1])

        _log.debug(f"LUT loaded: {len(lut_rgb)} colors (6-Color mode)")

    # Branch 3: 5-Color Extended (2468)
    elif "5-Color Extended" in color_mode or total_colors == 2468:
        _log.debug("Detected 5-Color Extended (2468) mode")

        # Fallback: generate stacks from index
        # First 1024: base 5-layer (4^5 combinations), pad to 6 layers
        # Next 1444: extended 6-layer from select_extended_1444_colors()
        _ref_stacks = []

        # Generate base 1024 stacks (5-layer, pad with air(-1) at viewing end)
        # Air at index 0 offsets the base viewing surface by 1 Z level
        # so it doesn't share the same Z as extended viewing surfaces.
        for i in range(min(1024, total_colors)):
            digits = []
            temp = i
            for _ in range(5):
                digits.append(temp % 4)
                temp //= 4
            stack = (-1,) + tuple(convert_recipe_between_orders(digits, "Bottom2Top", "Top2Bottom"))
            _ref_stacks.append(stack)

        # Generate extended 1444 stacks using select_extended_1444_colors
        if total_colors > 1024:
            from core.calibration import select_extended_1444_colors

            base_5layer = [
                tuple(convert_recipe_between_orders([i // 4**j % 4 for j in range(5)], "Bottom2Top", "Top2Bottom"))
                for i in range(1024)
            ]
            extended_stacks = select_extended_1444_colors(base_5layer)

            # Add extended stacks (already in correct 6-layer format)
            for i in range(min(len(extended_stacks), total_colors - 1024)):
                _ref_stacks.append(extended_stacks[i])

        lut_rgb = measured_colors
        ref_stacks = np.array(_ref_stacks)
        if isinstance(ref_stacks, np.ndarray) and ref_stacks.ndim == 2:
            layer_count = int(ref_stacks.shape[1])

        _log.debug(f"LUT loaded: {len(lut_rgb)} colors (5-Color Extended)")

    # Branch 4: Merged LUT (non-standard size or "Merged" mode)
    elif color_mode == "Merged" or total_colors not in (32, 1024, 1296, 2468, 2738):
        _log.debug(f"Detected non-standard LUT size ({total_colors}), trying companion .npz...")

        # 尝试查找同名 .npz 文件
        npz_path = lut_path.rsplit(".", 1)[0] + ".npz"
        if os.path.exists(npz_path):
            try:
                npz_rgb, npz_stacks, npz_meta = LUTManager.load_lut_with_metadata(npz_path)
                lut_rgb = npz_rgb
                ref_stacks = npz_stacks
                if isinstance(ref_stacks, np.ndarray) and ref_stacks.ndim == 2:
                    layer_count = int(ref_stacks.shape[1])
                _log.debug(f"Merged LUT loaded from companion .npz: {len(lut_rgb)} colors (Lab KDTree)")
                return _finalize_loaded_lut(
                    lut_rgb,
                    ref_stacks,
                    layer_count,
                    npz_meta,
                    requested_layer_height_mm,
                    enable_predictive_matching=enable_predictive_matching,
                    model_threshold=model_threshold,
                    model_margin=model_margin,
                )
            except (OSError, ValueError, TypeError, KeyError) as e:
                _log.warning(f"Failed to load companion .npz: {e}")

        # 无 .npz 伴随文件，使用 RGB 数据但无堆叠信息
        # 生成占位堆叠（全0）
        _log.debug(f"No companion .npz found, using placeholder stacks")
        lut_rgb = measured_colors
        ref_stacks = np.zeros((total_colors, layer_count), dtype=np.int32)

        _log.debug(f"LUT loaded: {len(lut_rgb)} colors (Merged mode, placeholder stacks)")

    # Branch 5: 4-Color Standard (1024)
    else:
        _log.debug("Detected 4-Color Standard mode")

        # Keep original outlier filtering logic (Blue Check)
        base_blue = np.array([30, 100, 200])
        dropped = 0
        channel_remap = _infer_legacy_4color_channel_remap(
            measured_colors,
            color_mode,
        )
        blue_like_raw_channels = _legacy_4color_blue_like_raw_channels(
            channel_remap,
            color_mode,
        )

        for i in range(1024):
            if i >= total_colors:
                break

            # Rebuild 4-base stacking (0..1023)
            digits = []
            temp = i
            for _ in range(5):
                digits.append(temp % 4)
                temp //= 4
            raw_stack = convert_recipe_between_orders(digits, "Bottom2Top", "Top2Bottom")

            real_rgb = measured_colors[i]

            # Filter outliers against the legacy raw recipe. Some CMYW-family
            # NPY files need raw channel IDs remapped to canonical slots below,
            # and their raw blue/cyan-like corner is not always channel 3.
            dist = np.linalg.norm(real_rgb - base_blue)
            if dist < 60 and not any(
                channel in blue_like_raw_channels for channel in raw_stack
            ):
                dropped += 1
                continue
            stack = tuple(int(channel_remap[int(channel)]) for channel in raw_stack)

            valid_rgb.append(real_rgb)
            valid_stacks.append(stack)

        lut_rgb = np.array(valid_rgb)
        ref_stacks = np.array(valid_stacks)
        if isinstance(ref_stacks, np.ndarray) and ref_stacks.ndim == 2:
            layer_count = int(ref_stacks.shape[1])

        _log.debug(f"LUT loaded: {len(lut_rgb)} colors (filtered {dropped} outliers)")

    # Build KD-Tree in CIELAB space for perceptually accurate color matching
    return _finalize_loaded_lut(
        lut_rgb,
        ref_stacks,
        layer_count,
        metadata,
        requested_layer_height_mm,
        enable_predictive_matching=enable_predictive_matching,
        model_threshold=model_threshold,
        model_margin=model_margin,
    )
