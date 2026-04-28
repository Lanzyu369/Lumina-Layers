"""Lumina Studio API — LUT Management Router.
Lumina Studio API — LUT 管理路由。

Provides endpoints for LUT preset listing, information queries, and merge operations.
提供 LUT 预设列表、信息查询和合并操作端点。
"""

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.dependencies import get_session_store
from api.session_store import SessionStore
from api.schemas.lut import (
    CompareDiffItem,
    CompareRequest,
    CompareResponse,
    CompareStats,
    LutAxisRange,
    LutCoverageStatsResponse,
    LutDetailsCatalogGroup,
    LutDetailsCatalogItem,
    LutDetailsCatalogResponse,
    LutDetailsResponse,
    LutHullPoint,
    LutInfoResponseV2,
    LutPlotPoint,
    LutPlotPoint3D,
    LutSourceCatalogResponse,
    MergeRequest,
    MergeResponse,
    MergeStats,
    PaletteEntrySchema,
    RecipeColorPredictRequest,
    RecipeColorPredictResponse,
    RecipeSearchItem,
    RecipeSearchRequest,
    RecipeSearchResponse,
)
from api.schemas.responses import LUTListResponse, LutInfo, LutColorsResponse, LutColorEntry
from api.structured_logging import get_logger
from config import LUTMetadata, get_capabilities, get_schema_version, get_source_kind, get_supported_modes
from core.lut_details.service import get_lut_details_service
from core.lut_card_layout import resolve_lut_layout
from core.lut_merger import LUTMerger
from core.predictive_lut import opencv_lab_to_rgb_uint8, predict_recipe_color, resolve_predictive_runtime
from utils.lut_manager import LUTManager

router = APIRouter(prefix="/api/lut", tags=["LUT"])
log = get_logger(__name__)

_VALID_PRIMARY_MODES = {"6-Color", "8-Color", "8-Color Max"}
_lut_details_service = None


def _canonicalize_public_color_mode(color_mode: str | None) -> str | None:
    """Normalize legacy/internal color mode labels for public API responses.
    将旧版/内部颜色模式标签规范化为公开 API 使用的名称。
    """
    if not isinstance(color_mode, str):
        return color_mode
    if color_mode.strip() == "8-Color":
        return "8-Color Max"
    return color_mode


def _canonicalize_source_catalog_color_modes(catalog: dict) -> dict:
    legacy_groups = [
        {
            **group,
            "items": [
                {
                    **item,
                    "color_mode": _canonicalize_public_color_mode(item.get("color_mode")),
                }
                for item in group.get("items", [])
            ],
        }
        for group in catalog.get("legacy_groups", [])
    ]
    native_brand_groups = [
        {
            **group,
            "db_options": [
                {
                    **option,
                    "color_mode": _canonicalize_public_color_mode(option.get("color_mode")),
                }
                for option in group.get("db_options", [])
            ],
        }
        for group in catalog.get("native_brand_groups", [])
    ]
    return {
        **catalog,
        "legacy_groups": legacy_groups,
        "native_brand_groups": native_brand_groups,
    }


def _canonicalize_public_color_mode_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                _canonicalize_public_color_mode(item)
                if key == "color_mode"
                else _canonicalize_public_color_mode_fields(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_canonicalize_public_color_mode_fields(item) for item in value]
    return value


def _resolve_lut_details_service():
    """Lazily initialize the LUT details service.
    延迟初始化 LUT 详情服务。
    """

    global _lut_details_service
    if _lut_details_service is None:
        _lut_details_service = get_lut_details_service()
    return _lut_details_service


def _invalidate_lut_details_service_cache() -> None:
    """Drop cached LUT details service state after LUT files change.
    在 LUT 文件变更后丢弃缓存的 LUT 详情服务状态。
    """

    global _lut_details_service
    _lut_details_service = None
    get_lut_details_service.cache_clear()


def _dedupe_warnings(warnings: list[str]) -> list[str]:
    """Preserve warning order while removing duplicates.
    保持警告顺序并移除重复项。
    """
    seen: set[str] = set()
    result: list[str] = []
    for warning in warnings:
        if warning and warning not in seen:
            seen.add(warning)
            result.append(warning)
    return result


def _recipe_matches_pattern(recipe: list[int], palette_letters: list[str], pattern: str) -> bool:
    normalized = pattern.replace("-", "").strip().upper()
    if not normalized:
        return True
    letters = [palette_letters[idx] if 0 <= idx < len(palette_letters) else "?" for idx in recipe]
    i = 0
    j = 0
    while i < len(normalized) and j < len(letters):
        token = normalized[i]
        if token == "*":
            if i == len(normalized) - 1:
                return True
            next_token = normalized[i + 1]
            while j < len(letters) and next_token not in ("?", letters[j]):
                j += 1
            i += 1
            continue
        if token != "?" and token != letters[j]:
            return False
        i += 1
        j += 1
    while i < len(normalized) and normalized[i] == "*":
        i += 1
    return i == len(normalized) and j == len(letters)


@router.get("/list")
def list_luts() -> LUTListResponse:
    """Return all available LUT presets as a list of LutInfo objects.
    返回所有可用 LUT 预设，以 LutInfo 对象列表形式返回。
    """
    lut_dict: dict[str, str] = LUTManager.get_all_lut_files()
    lut_list: list[LutInfo] = []
    for display_name, file_path in lut_dict.items():
        try:
            fingerprint = LUTManager.compute_fingerprint(file_path)
        except OSError:
            fingerprint = ""
        lut_list.append(
            LutInfo(
                name=display_name,
                color_mode=_canonicalize_public_color_mode(
                    LUTManager.infer_color_mode(display_name, file_path)
                ),
                path=file_path,
                fingerprint=fingerprint,
            )
        )
    return LUTListResponse(luts=lut_list)


@router.get("/catalog", response_model=LutSourceCatalogResponse)
def get_source_catalog() -> LutSourceCatalogResponse:
    """Return legacy and native source catalog groupings.
    返回传统源与原生源的分组目录。
    """

    catalog = _canonicalize_source_catalog_color_modes(LUTManager.get_source_catalog())
    return LutSourceCatalogResponse.model_validate(catalog)


@router.get("/details/catalog", response_model=LutDetailsCatalogResponse)
def get_lut_details_catalog() -> LutDetailsCatalogResponse:
    """Return the LUT details catalog grouped by manufacturer.
    返回按厂商分组的 LUT 详情目录。
    """

    try:
        catalog = _resolve_lut_details_service().get_catalog()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"LUT details catalog unavailable: {exc}") from exc
    return LutDetailsCatalogResponse(
        groups=[
            LutDetailsCatalogGroup(
                manufacturer=group.manufacturer,
                items=[
                    LutDetailsCatalogItem(
                        name=item.name,
                        path=item.path,
                        fingerprint=item.fingerprint,
                        color_mode=_canonicalize_public_color_mode(item.color_mode),
                        source_kind=item.source_kind,
                        manufacturer=item.manufacturer,
                        material_type=item.material_type,
                        manufacturer_source=item.manufacturer_source,
                        material_source=item.material_source,
                        search_tokens=list(item.search_tokens),
                    )
                    for item in group.items
                ],
            )
            for group in catalog.groups
        ]
    )


_ALLOWED_LUT_EXTENSIONS = {".npy", ".json", ".npz", ".msgpack"}


@router.post("/upload")
async def upload_lut(file: UploadFile = File(..., description="LUT 文件 (.npy/.json/.npz)")) -> dict:
    """Upload a LUT file to the Custom preset directory.
    上传 LUT 文件到 Custom 预设目录。
    """
    filename = file.filename or "unknown"
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_LUT_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的文件类型: {ext}，仅支持 .npy/.json/.npz/.msgpack",
        )

    # Save to temp file first (chunked read with size limit)
    from config import TEMP_DIR

    MAX_LUT_SIZE = 50 * 1024 * 1024  # 50 MB
    total_read = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir=TEMP_DIR) as tmp:
        while True:
            chunk = await file.read(1024 * 1024)  # 1 MB chunks
            if not chunk:
                break
            total_read += len(chunk)
            if total_read > MAX_LUT_SIZE:
                tmp_path = tmp.name
                os.unlink(tmp_path)
                raise HTTPException(
                    status_code=413,
                    detail=f"文件过大，最大允许 {MAX_LUT_SIZE // (1024*1024)} MB",
                )
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        import numpy as np

        stem = Path(filename).stem
        custom_dir = os.path.join(LUTManager.LUT_PRESET_DIR, "Custom")
        os.makedirs(custom_dir, exist_ok=True)

        # Auto-convert .npy to Keyed JSON
        if ext == ".npy":
            dest_ext = ".json"
            rgb = np.load(tmp_path)
            if rgb.ndim == 3:
                rgb = rgb.reshape(-1, 3)
            elif rgb.ndim == 1:
                rgb = rgb.reshape(-1, 3)
            metadata = LUTManager.infer_default_metadata(stem, tmp_path, len(rgb))
            stacks = np.zeros((len(rgb), 0), dtype=np.int32)
            dest_path = os.path.join(custom_dir, f"{stem}{dest_ext}")
            counter = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(custom_dir, f"{stem}_{counter}{dest_ext}")
                counter += 1
            LUTManager.save_keyed_json(dest_path, rgb, stacks, metadata)
        else:
            dest_path = os.path.join(custom_dir, filename)
            counter = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(custom_dir, f"{stem}_{counter}{ext}")
                counter += 1
            shutil.copy2(tmp_path, dest_path)

        _invalidate_lut_details_service_cache()
        display_name = f"Custom - {Path(dest_path).stem}"
        dest_filename = Path(dest_path).name
        log.info(
            "LUT upload complete",
            extra={
                "event": "lut_upload_done",
                "original_filename": filename,
                "file_extension": ext,
                "dest_filename": dest_filename,
                "display_name": display_name,
                "file_size_bytes": int(total_read),
                "was_converted": ext == ".npy",
            },
        )
        return {"status": "ok", "message": f"LUT 已保存: {display_name}", "name": display_name}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"上传失败: {exc}") from exc
    finally:
        os.unlink(tmp_path)


@router.post("/merge")
def merge_luts_endpoint(request: MergeRequest) -> MergeResponse:
    """Execute LUT merge: primary + multiple secondary LUTs.
    执行 LUT 合并：主 LUT + 多个辅助 LUT。

    Replicates the flow of ``ui/callbacks.py::on_merge_execute``:
    resolve paths → detect modes → validate compatibility →
    load data → skip Merged secondaries → merge → save to Custom dir.
    复刻 ``ui/callbacks.py::on_merge_execute`` 的完整流程：
    解析路径 → 检测模式 → 验证兼容性 → 加载数据 → 跳过 Merged Secondary → 合并 → 保存到 Custom 目录。
    """
    # 1. Validate secondary list not empty / 验证 Secondary 列表非空
    if not request.secondary_names:
        raise HTTPException(
            status_code=400,
            detail="At least one secondary LUT is required",
        )

    # 2. Resolve primary path / 解析主 LUT 路径
    primary_path: str | None = LUTManager.get_lut_path(request.primary_name)
    if primary_path is None:
        raise HTTPException(
            status_code=404,
            detail=f"LUT not found: {request.primary_name}",
        )

    try:
        # 3. Detect primary mode / 检测主 LUT 模式
        primary_mode, _ = LUTMerger.detect_color_mode(primary_path)
        if primary_mode not in _VALID_PRIMARY_MODES:
            raise HTTPException(
                status_code=400,
                detail="Primary LUT must be 6-Color or 8-Color",
            )

        # 4. Load primary data / 加载主 LUT 数据
        primary_rgb, primary_stacks = LUTMerger.load_lut_with_stacks(primary_path, primary_mode)
        entries = [(primary_rgb, primary_stacks, primary_mode)]
        all_modes: list[str] = [primary_mode]
        all_paths: list[str] = [primary_path]  # 记录所有输入路径，用于判断输出格式
        all_names: list[str] = [request.primary_name]  # 记录来源 LUT 显示名称

        # 5. Load each secondary, skip Merged / 加载辅助 LUT，跳过 Merged
        for sec_name in request.secondary_names:
            sec_path: str | None = LUTManager.get_lut_path(sec_name)
            if sec_path is None:
                continue
            sec_mode, _ = LUTMerger.detect_color_mode(sec_path)
            if sec_mode == "Merged":
                continue
            sec_rgb, sec_stacks = LUTMerger.load_lut_with_stacks(sec_path, sec_mode)
            entries.append((sec_rgb, sec_stacks, sec_mode))
            all_modes.append(sec_mode)
            all_paths.append(sec_path)
            all_names.append(sec_name)

        # 6. Need at least 2 entries / 至少需要 2 个有效条目
        if len(entries) < 2:
            raise HTTPException(
                status_code=400,
                detail="At least one secondary LUT is required",
            )

        # 7. Validate compatibility / 验证兼容性
        valid, err_msg = LUTMerger.validate_compatibility(all_modes)
        if not valid:
            raise HTTPException(status_code=400, detail=err_msg)

        # 判断输出格式：所有输入都是 .json 时输出 JSON，否则输出 .npz
        all_json = all(p.lower().endswith(".json") for p in all_paths)

        # 8. Merge / 执行合并
        # 如果输出 JSON，加载 metadata 以便保存完整的 Keyed JSON
        metadata_list: list[LUTMetadata] | None = None
        if all_json:
            metadata_list = []
            for p in all_paths:
                _, _, meta = LUTManager.load_lut_with_metadata(p)
                metadata_list.append(meta)

        merged_rgb, merged_stacks, stats = LUTMerger.merge_luts(
            entries,
            dedup_threshold=request.dedup_threshold,
            metadata_list=metadata_list,
            source_names=all_names,
        )

        # 9. Save to Custom dir / 保存到 Custom 目录
        timestamp: str = time.strftime("%Y%m%d_%H%M%S")
        mode_str: str = "+".join(all_modes)
        output_ext: str = ".json" if all_json else ".npz"
        output_name: str = f"Merged_{mode_str}_{timestamp}{output_ext}"
        custom_dir: str = os.path.join(LUTManager.LUT_PRESET_DIR, "Custom")
        os.makedirs(custom_dir, exist_ok=True)
        output_path: str = os.path.join(custom_dir, output_name)

        merged_metadata = stats.get("merged_metadata")
        if all_json:
            # 输出 Keyed JSON 格式，保留 palette 和打印参数
            if merged_metadata is None:
                # 回退：使用主 LUT 的 metadata
                _, _, merged_metadata = LUTManager.load_lut_with_metadata(primary_path)
            entry_sources = stats.get("entry_sources")
            json_stacks = LUTMerger.reindex_canonical_stacks_for_palette(
                merged_stacks,
                merged_metadata.palette,
            )
            LUTManager.save_keyed_json(
                output_path,
                merged_rgb,
                json_stacks,
                merged_metadata,
                sources=entry_sources,
            )
        else:
            LUTMerger.save_merged_lut(merged_rgb, merged_stacks, output_path)

        _invalidate_lut_details_service_cache()
        log.info(
            "LUT merge complete",
            extra={
                "event": "lut_merge_done",
                "primary_lut_name": request.primary_name,
                "secondary_count": len(request.secondary_names),
                "merged_filename": output_name,
                "total_before": int(stats["total_before"]),
                "total_after": int(stats["total_after"]),
                "exact_dupes": int(stats["exact_dupes"]),
                "similar_removed": int(stats["similar_removed"]),
                "palette_size": len(merged_metadata.palette) if merged_metadata else 0,
                "warning_count": len(stats.get("warnings") or []),
            },
        )
        # 10. Return response / 返回响应
        # 注意：validate_print_params() 和 merge_palettes() 尚未实现（任务 6），暂时使用空列表
        return MergeResponse(
            status="success",
            message=f"Merged {stats['total_before']} colors → {stats['total_after']} colors",
            filename=output_name,
            stats=MergeStats(
                total_before=stats["total_before"],
                total_after=stats["total_after"],
                exact_dupes=stats["exact_dupes"],
                similar_removed=stats["similar_removed"],
            ),
            palette=[
                PaletteEntrySchema(
                    color=entry.color,
                    material=entry.material,
                    hex_color=entry.hex_color,
                    color_name=entry.color_name,
                )
                for entry in ((stats.get("merged_metadata").palette) if stats.get("merged_metadata") else [])
            ],
            warnings=_dedupe_warnings(list(stats.get("warnings", []))),
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Merge failed: {exc}",
        ) from exc


@router.post("/compare")
def compare_luts_endpoint(request: CompareRequest) -> CompareResponse:
    """Compare two LUTs by shared recipe keys.
    按共享配方键比较两个 LUT。
    """
    path_a: str | None = LUTManager.get_lut_path(request.lut_a_name)
    if path_a is None:
        raise HTTPException(status_code=404, detail=f"LUT not found: {request.lut_a_name}")

    path_b: str | None = LUTManager.get_lut_path(request.lut_b_name)
    if path_b is None:
        raise HTTPException(status_code=404, detail=f"LUT not found: {request.lut_b_name}")

    try:
        mode_a, _count_a = LUTMerger.detect_color_mode(path_a)
        mode_b, _count_b = LUTMerger.detect_color_mode(path_b)

        rgb_a, stacks_a = LUTMerger.load_lut_with_stacks(path_a, mode_a)
        rgb_b, stacks_b = LUTMerger.load_lut_with_stacks(path_b, mode_b)

        try:
            _, _, metadata_a = LUTManager.load_lut_with_metadata(path_a)
        except Exception:
            metadata_a = LUTMetadata(color_mode=mode_a)

        try:
            _, _, metadata_b = LUTManager.load_lut_with_metadata(path_b)
        except Exception:
            metadata_b = LUTMetadata(color_mode=mode_b)

        compare_result = LUTMerger.compare_luts_by_recipe(
            rgb_a,
            stacks_a,
            rgb_b,
            stacks_b,
            top_n=request.top_n,
        )

        warnings = list(compare_result.get("warnings", []))

        if mode_a != mode_b:
            warnings.append(f"color_mode 不一致: {mode_a} vs {mode_b}")

        if stacks_a.ndim == 2 and stacks_b.ndim == 2:
            if stacks_a.shape[1] != stacks_b.shape[1]:
                warnings.append(
                    f"recipe layer count differs: {stacks_a.shape[1]} vs {stacks_b.shape[1]}"
                )

        _compatible, param_warnings = LUTMerger.validate_print_params([metadata_a, metadata_b])
        warnings.extend(param_warnings)
        if get_schema_version(metadata_a) != get_schema_version(metadata_b):
            warnings.append(
                f"schema_version differs: {get_schema_version(metadata_a)} vs {get_schema_version(metadata_b)}"
            )
        if metadata_a.supports_predictive_match() != metadata_b.supports_predictive_match():
            warnings.append(
                "predictive support differs: "
                f"{metadata_a.supports_predictive_match()} vs {metadata_b.supports_predictive_match()}"
            )
        if metadata_a.supports_dynamic_layer_height() != metadata_b.supports_dynamic_layer_height():
            warnings.append(
                "dynamic_layer_height support differs: "
                f"{metadata_a.supports_dynamic_layer_height()} vs {metadata_b.supports_dynamic_layer_height()}"
            )

        stats_dict = compare_result["stats"]
        if stats_dict["matched_recipe_count"] == 0:
            warnings.append("No shared recipes found; comparison metrics are zeroed.")

        warnings = _dedupe_warnings(warnings)
        log.info(
            "LUT compare complete",
            extra={
                "event": "lut_compare_done",
                "lut_a_name": request.lut_a_name,
                "lut_b_name": request.lut_b_name,
                "lut_a_mode": mode_a,
                "lut_b_mode": mode_b,
                "matched_recipe_count": int(stats_dict["matched_recipe_count"]),
                "warning_count": len(warnings),
                "top_n": int(request.top_n),
                "worst_diffs_count": len(compare_result["worst_diffs"]),
            },
        )
        message = (
            f"Compared {stats_dict['matched_recipe_count']} shared recipes between "
            f"{request.lut_a_name} and {request.lut_b_name}"
        )

        return CompareResponse(
            status="success",
            message=message,
            lut_a_name=request.lut_a_name,
            lut_b_name=request.lut_b_name,
            lut_a_mode=mode_a,
            lut_b_mode=mode_b,
            stats=CompareStats(**stats_dict),
            warnings=warnings,
            worst_diffs=[CompareDiffItem(**item) for item in compare_result["worst_diffs"]],
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Compare failed: {exc}",
        ) from exc


@router.get("/{lut_name}/colors")
def get_lut_colors(lut_name: str) -> LutColorsResponse:
    """Return all unique colors available in a LUT file.
    返回 LUT 文件中所有可用的唯一颜色。
    """
    path: str | None = LUTManager.get_lut_path(lut_name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"LUT not found: {lut_name}")

    from core.converter import extract_lut_available_colors

    raw_colors: list[dict] = extract_lut_available_colors(path)
    entries: list[LutColorEntry] = [LutColorEntry(hex=c["hex"], rgb=c["color"]) for c in raw_colors]

    layout = None
    cards = []
    try:
        rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(path)
        mode = _canonicalize_public_color_mode(getattr(metadata, "color_mode", None)) or ""
        layout = resolve_lut_layout(mode, int(len(rgb)))
        row_entries = [
            LutColorEntry(
                hex=f"#{int(color[0]):02x}{int(color[1]):02x}{int(color[2]):02x}",
                rgb=(int(color[0]), int(color[1]), int(color[2])),
            )
            for color in rgb.reshape(-1, 3)
        ]
        cards = [
            {
                "page": page.to_dict(),
                "colors": row_entries[page.start_index : page.start_index + page.item_count],
            }
            for page in layout.pages
        ]
    except (ValueError, OSError, KeyError, TypeError, RuntimeError):
        layout = None
        cards = []

    return LutColorsResponse(
        lut_name=lut_name,
        total=len(entries),
        colors=entries,
        layout=layout.to_dict() if layout is not None else None,
        cards=cards,
    )


# Canonical hex for the well-known primary / secondary channel names used by
# ChromaPrint-style palettes. Applied as a last-resort fallback when neither
# ``palette[c].hex_color`` nor the LUT's pure-stack recipe yields a colour,
# so the custom recipe dialog's swatches never degrade to a neutral grey for
# standard primaries like Cyan / Magenta / Yellow / Black / White / RGB.
# 用于 ChromaPrint 风格调色板的通道规范色：当 palette 元数据没有 hex_color、
# 且 LUT 没有纯通道堆叠配方可供反查时作为兜底，保证对话框色块对常见原色
# （Cyan / Magenta / Yellow / Black / White / RGB）永远不是灰色。
_CANONICAL_PRIMARY_HEX: dict[str, str] = {
    "cyan": "#00B7EB",
    "magenta": "#E6007E",
    "yellow": "#FFD400",
    "black": "#111111",
    "white": "#F5F5F5",
    "red": "#E53935",
    "green": "#43A047",
    "blue": "#1E88E5",
    "orange": "#FB8C00",
    "purple": "#8E24AA",
    "pink": "#EC407A",
    "gray": "#9E9E9E",
    "grey": "#9E9E9E",
    "brown": "#795548",
}


def _canonical_primary_hex(color_name: str | None) -> str | None:
    """Return the canonical ``#RRGGBB`` for well-known primary channel names.

    返回常见原色通道名对应的规范 ``#RRGGBB``（大小写不敏感，找不到返回 ``None``）。
    """
    if not color_name:
        return None
    return _CANONICAL_PRIMARY_HEX.get(color_name.strip().lower())


def _pure_channel_hex(
    rgb: np.ndarray | None,
    stacks: np.ndarray | None,
    channel_idx: int,
) -> str | None:
    """Derive ``#RRGGBB`` for a palette channel from its pure-stack recipe.

    从"纯通道"配方（每一层都是同一通道）反查 LUT 得到该通道的代表色 hex。

    Many LUT bundles ship without explicit ``hex_color`` in their palette
    metadata (notably material archives and native bundles). The LUT itself
    still carries an authoritative RGB for the pure stack ``[c, c, ..., c]``,
    which is the natural visual representative of channel ``c``. This helper
    looks that up so the frontend does not have to fall back to a neutral gray
    swatch.

    Args:
        rgb: ``(N, 3)`` uint8 array of per-recipe RGB values, or ``None``.
        stacks: ``(N, layers)`` int array of per-recipe channel indices, or ``None``.
        channel_idx: Palette channel index to resolve. 调色板通道索引。

    Returns:
        ``"#RRGGBB"`` when a pure-stack recipe exists, otherwise ``None``.
    """
    if rgb is None or stacks is None:
        return None
    rgb_arr = np.asarray(rgb)
    stacks_arr = np.asarray(stacks)
    if rgb_arr.ndim != 2 or stacks_arr.ndim != 2:
        return None
    if stacks_arr.shape[0] != rgb_arr.shape[0] or stacks_arr.shape[1] == 0:
        return None
    target = np.full(stacks_arr.shape[1], channel_idx, dtype=stacks_arr.dtype)
    matches = np.where(np.all(stacks_arr == target, axis=1))[0]
    if matches.size == 0:
        return None
    row = rgb_arr[int(matches[0])]
    if row.shape[-1] < 3:
        return None
    r, g, b = (int(row[0]), int(row[1]), int(row[2]))
    return f"#{r:02X}{g:02X}{b:02X}"


def _preview_color_to_hex(raw: object) -> str | None:
    """Convert a cached preview RGBA/RGB row to ``#RRGGBB``.

    将缓存中的 RGB/RGBA 行转换为 ``#RRGGBB``。
    """
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return None
    try:
        r, g, b = (int(raw[0]), int(raw[1]), int(raw[2]))
    except (TypeError, ValueError):
        return None
    if not all(0 <= value <= 255 for value in (r, g, b)):
        return None
    return f"#{r:02X}{g:02X}{b:02X}"


def _cached_preview_color_hex(preview_colors: object, idx: int) -> str | None:
    """Read channel ``idx`` from ``preview_colors`` with int/string keys."""
    if not isinstance(preview_colors, dict):
        return None
    raw = preview_colors.get(idx)
    if raw is None:
        raw = preview_colors.get(str(idx))
    return _preview_color_to_hex(raw)


def _build_material_archive_lut_info(session_data: dict) -> LutInfoResponseV2:
    """Build session-scoped LUT info for material-archive sources.

    耗材档案没有真实 LUT 文件；这里从 session 的耗材顺序和 preview cache
    组装与 LUT info 相同形状的通道 palette，供自定义配方编辑器使用。
    """
    selected_materials = session_data.get("selected_materials") or []
    if not isinstance(selected_materials, list) or not selected_materials:
        raise HTTPException(
            status_code=409,
            detail=(
                "Material archive session is missing selected materials. "
                "Run preview again first."
            ),
        )

    cache = session_data.get("preview_cache") or {}
    if not isinstance(cache, dict):
        cache = {}
    raw_slot_names = cache.get("slot_names") or []
    slot_names = raw_slot_names if isinstance(raw_slot_names, list) else []
    preview_colors = cache.get("preview_colors") or {}

    palette_schema: list[PaletteEntrySchema] = []
    for idx, dir_name in enumerate(selected_materials):
        raw_slot = slot_names[idx] if idx < len(slot_names) else None
        label = str(raw_slot) if raw_slot else str(dir_name)
        palette_schema.append(
            PaletteEntrySchema(
                color=label,
                material=str(dir_name),
                hex_color=_cached_preview_color_hex(preview_colors, idx),
                color_name=label,
            )
        )

    color_layers = int(
        session_data.get("material_layer_count")
        or cache.get("color_layers")
        or len(palette_schema)
        or 5
    )
    layer_height_mm = float(
        session_data.get("material_layer_height_mm")
        or cache.get("layer_height_mm")
        or 0.08
    )
    metadata = LUTMetadata(
        max_color_layers=color_layers,
        layer_height_mm=layer_height_mm,
        color_mode="Material Archive",
        capabilities=["custom_recipe"],
        extensions={
            "source_kind": "material_archive",
            "custom_recipe_supported": True,
            "supported_modes": [
                {
                    "color_layers": color_layers,
                    "layer_height_mm": layer_height_mm,
                }
            ],
        },
    )
    display_name = str(session_data.get("lut_name") or "__material_archive__")
    return LutInfoResponseV2(
        name=display_name,
        color_mode="Material Archive",
        color_count=len(palette_schema),
        palette=palette_schema,
        max_color_layers=metadata.max_color_layers,
        layer_height_mm=metadata.layer_height_mm,
        line_width_mm=metadata.line_width_mm,
        base_layers=metadata.base_layers,
        base_channel_idx=metadata.base_channel_idx,
        layer_order=metadata.layer_order,
        schema_version=get_schema_version(metadata),
        capabilities=get_capabilities(metadata),
        supports_predictive_match=metadata.supports_predictive_match(),
        supports_dynamic_layer_height=metadata.supports_dynamic_layer_height(),
        supports_dynamic_layer_count=metadata.supports_dynamic_layer_count(),
        supports_custom_recipe=metadata.supports_custom_recipe(),
        source_kind=metadata.get_source_kind(),
        supported_modes=metadata.get_supported_modes(),
    )


def _build_lut_info_from_path(path: str, display_name: str) -> LutInfoResponseV2:
    """Assemble :class:`LutInfoResponseV2` from a LUT file on disk.

    从磁盘上的 LUT 文件组装 ``LutInfoResponseV2``。

    Shared by the named-LUT endpoint and the session-scoped endpoint so that
    material-archive / native bundle sessions expose the same channel palette
    shape as legacy LUTs.

    Args:
        path: Absolute path of a LUT file. LUT 文件绝对路径。
        display_name: Name returned in the response ``name`` field.
            响应 ``name`` 字段中的显示名称。

    Returns:
        LutInfoResponseV2: Channel palette + capability flags for the LUT.
            LUT 的通道调色板与能力标志。
    """
    detected_mode, color_count = LUTMerger.detect_color_mode(path)
    inferred_mode = LUTManager.infer_color_mode(Path(path).name, path)
    color_mode = inferred_mode if detected_mode in {"4-Color", "6-Color"} else detected_mode
    color_mode = _canonicalize_public_color_mode(color_mode)

    # 加载元数据（如果 load_lut_with_metadata 可用）
    metadata = LUTMetadata()
    _rgb: np.ndarray | None = None
    _stacks: np.ndarray | None = None
    try:
        _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(path)
    except (AttributeError, NotImplementedError, Exception):
        # load_lut_with_metadata() 尚未实现（任务 4.2），回退使用默认空元数据
        pass

    palette_schema = [
        PaletteEntrySchema(
            color=e.color,
            material=e.material,
            hex_color=(
                e.hex_color
                or _pure_channel_hex(_rgb, _stacks, channel_idx)
                or _canonical_primary_hex(e.color_name)
                or _canonical_primary_hex(e.color)
            ),
            color_name=e.color_name,
        )
        for channel_idx, e in enumerate(metadata.palette)
    ]

    return LutInfoResponseV2(
        name=display_name,
        color_mode=color_mode,
        color_count=color_count,
        palette=palette_schema,
        max_color_layers=metadata.max_color_layers,
        layer_height_mm=metadata.layer_height_mm,
        line_width_mm=metadata.line_width_mm,
        base_layers=metadata.base_layers,
        base_channel_idx=metadata.base_channel_idx,
        layer_order=metadata.layer_order,
        schema_version=get_schema_version(metadata),
        capabilities=get_capabilities(metadata),
        supports_predictive_match=metadata.supports_predictive_match(),
        supports_dynamic_layer_height=metadata.supports_dynamic_layer_height(),
        supports_dynamic_layer_count=metadata.supports_dynamic_layer_count(),
        supports_custom_recipe=metadata.supports_custom_recipe(),
        source_kind=metadata.get_source_kind(),
        supported_modes=metadata.get_supported_modes(),
    )


@router.get("/{lut_name}/info")
def get_lut_info(lut_name: str) -> LutInfoResponseV2:
    """Return color mode and color count for a specific LUT.
    返回指定 LUT 的颜色模式和颜色数量。
    """
    path: str | None = LUTManager.get_lut_path(lut_name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"LUT not found: {lut_name}")
    return _build_lut_info_from_path(path, lut_name)


@router.get("/session/{session_id}/info")
def get_session_lut_info(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> LutInfoResponseV2:
    """Return channel palette and capabilities for the LUT bound to a session.

    返回当前会话所绑定 LUT 的通道调色板与能力标志。

    Unlike :func:`get_lut_info`, this endpoint works for material-archive and
    native-bundle sessions that don't have a globally-known LUT name, letting
    the UI surface channel-ordered materials for custom recipe editing.

    Args:
        session_id: Active converter session id. 当前转换会话 id。
        store: Injected :class:`SessionStore`. 会话存储依赖。

    Returns:
        LutInfoResponseV2: Same shape as :func:`get_lut_info`.
            与 ``get_lut_info`` 相同的响应结构。

    Raises:
        HTTPException(404): Session not found. 会话不存在。
        HTTPException(409): Session has no LUT bound yet or the file is
            missing. 会话未绑定 LUT 或文件缺失。
    """
    session_data = store.get(session_id)
    if session_data is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    if str(session_data.get("material_source") or "lut") == "material_archive":
        info = _build_material_archive_lut_info(session_data)
        source_kind = "material_archive"
    else:
        lut_path = session_data.get("lut_path")
        if not isinstance(lut_path, str) or not lut_path or not os.path.exists(lut_path):
            raise HTTPException(
                status_code=409,
                detail="Session has no LUT bound yet. Run preview/generate first.",
            )
        display_name = session_data.get("lut_name") or Path(lut_path).stem
        info = _build_lut_info_from_path(lut_path, str(display_name))
        source_kind = info.source_kind

    log.info(
        "Session LUT info returned",
        extra={
            "event": "lut_session_info_done",
            "session_id": session_id,
            "lut_name": info.name,
            "color_mode": info.color_mode,
            "color_count": int(info.color_count),
            "source_kind": source_kind,
            "palette_size": len(info.palette),
        },
    )
    return info


@router.get("/{lut_name}/details", response_model=LutDetailsResponse)
def get_lut_details(lut_name: str) -> LutDetailsResponse:
    """Return the detailed LUT metadata and visualization payload.
    返回 LUT 的详细元数据和可视化载荷。
    """

    try:
        detail = _resolve_lut_details_service().get_lut_details(lut_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"LUT not found: {lut_name}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"LUT details unavailable: {exc}") from exc

    log.info(
        "LUT details returned",
        extra={
            "event": "lut_details_done",
            "lut_name": detail.name,
            "color_mode": detail.color_mode,
            "color_count": int(detail.color_count),
            "entry_count": int(detail.coverage_stats.entry_count),
            "lab_points_count": len(detail.lab_points),
            "rgb_points_count": len(detail.rgb_points),
            "manufacturer": detail.manufacturer or "",
            "source_kind": detail.source_kind,
        },
    )
    return LutDetailsResponse(
        name=detail.name,
        path=detail.path,
        fingerprint=detail.fingerprint,
        manufacturer=detail.manufacturer,
        manufacturer_source=detail.manufacturer_source,
        material_type=detail.material_type,
        material_source=detail.material_source,
        color_mode=_canonicalize_public_color_mode(detail.color_mode),
        color_count=detail.color_count,
        source_kind=detail.source_kind,
        schema_version=detail.schema_version,
        capabilities=list(detail.capabilities),
        supported_modes=list(detail.supported_modes),
        raw_metadata=_canonicalize_public_color_mode_fields(detail.raw_metadata),
        palette=[
            PaletteEntrySchema(
                color=str(entry["color"]),
                material=str(entry["material"]),
                hex_color=entry.get("hex_color"),
                color_name=entry.get("color_name"),
            )
            for entry in detail.palette
        ],
        coverage_stats=LutCoverageStatsResponse(
            entry_count=detail.coverage_stats.entry_count,
            plotted_point_count=detail.coverage_stats.plotted_point_count,
            l_range=LutAxisRange(min=detail.coverage_stats.l_range.min, max=detail.coverage_stats.l_range.max),
            a_range=LutAxisRange(min=detail.coverage_stats.a_range.min, max=detail.coverage_stats.a_range.max),
            b_range=LutAxisRange(min=detail.coverage_stats.b_range.min, max=detail.coverage_stats.b_range.max),
            r_range=LutAxisRange(min=detail.coverage_stats.r_range.min, max=detail.coverage_stats.r_range.max),
            g_range=LutAxisRange(min=detail.coverage_stats.g_range.min, max=detail.coverage_stats.g_range.max),
            b_rgb_range=LutAxisRange(min=detail.coverage_stats.b_rgb_range.min, max=detail.coverage_stats.b_rgb_range.max),
        ),
        lab_points=[
            LutPlotPoint(
                x=point.x,
                y=point.y,
                hex_color=point.hex_color,
                rgb=list(point.rgb),
                label=point.label,
            )
            for point in detail.lab_points
        ],
        lab_points_3d=[
            LutPlotPoint3D(
                l=point.l,
                a=point.a,
                b=point.b,
                hex_color=point.hex_color,
                rgb=list(point.rgb),
                label=point.label,
            )
            for point in detail.lab_points_3d
        ],
        lab_hull=[LutHullPoint(x=point[0], y=point[1]) for point in detail.lab_hull],
        rgb_points=[
            LutPlotPoint(
                x=point.x,
                y=point.y,
                hex_color=point.hex_color,
                rgb=list(point.rgb),
                label=point.label,
            )
            for point in detail.rgb_points
        ],
        max_color_layers=detail.max_color_layers,
        layer_height_mm=detail.layer_height_mm,
        line_width_mm=detail.line_width_mm,
        base_layers=detail.base_layers,
        base_channel_idx=detail.base_channel_idx,
        layer_order=detail.layer_order,
    )


@router.post("/{lut_name}/predict-recipe-color")
def predict_recipe_color_endpoint(
    lut_name: str,
    request: RecipeColorPredictRequest,
) -> RecipeColorPredictResponse:
    """Predict a custom recipe color for the selected source."""
    path: str | None = LUTManager.get_lut_path(lut_name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"LUT not found: {lut_name}")

    try:
        _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(path)
        payload = predict_recipe_color(
            metadata,
            recipe=list(request.recipe),
            layer_height_mm=float(request.layer_height_mm),
            color_layers=int(request.color_layers),
            layer_order=str(request.layer_order),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Recipe color prediction failed: {exc}",
        ) from exc

    return RecipeColorPredictResponse(
        status="ok",
        rgb=[int(v) for v in payload["rgb"]],
        lab=[float(v) for v in payload["lab"]],
        runtime_mode_key=str(payload["runtime_mode_key"]),
        source=str(payload["source"]),
    )


@router.post("/{lut_name}/search-recipes")
def search_recipes_endpoint(
    lut_name: str,
    request: RecipeSearchRequest,
) -> RecipeSearchResponse:
    """Search predictive candidate recipes by a simple layer pattern."""
    path: str | None = LUTManager.get_lut_path(lut_name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"LUT not found: {lut_name}")

    try:
        _rgb, _stacks, metadata = LUTManager.load_lut_with_metadata(path)
        runtime = resolve_predictive_runtime(
            metadata,
            float(request.layer_height_mm),
            int(request.color_layers),
            str(request.layer_order),
        )
        if runtime is None:
            raise ValueError("No predictive runtime available for the requested mode")

        palette_letters = [
            (entry.color_name or entry.color or "?")[:1].upper()
            for entry in metadata.palette
        ]
        matches: list[RecipeSearchItem] = []
        for idx, recipe in enumerate(runtime.candidate_recipes.tolist()):
            if not _recipe_matches_pattern(recipe, palette_letters, request.pattern):
                continue
            rgb = opencv_lab_to_rgb_uint8(runtime.pred_lab[idx : idx + 1])[0].astype(int).tolist()
            lab = runtime.pred_lab[idx].astype(float).tolist()
            matches.append(RecipeSearchItem(recipe=[int(v) for v in recipe], rgb=rgb, lab=lab))
            if len(matches) >= int(request.limit):
                break
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Recipe search failed: {exc}") from exc

    return RecipeSearchResponse(
        status="ok",
        runtime_mode_key=runtime.mode_key,
        items=matches,
    )
