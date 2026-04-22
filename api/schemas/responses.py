"""Lumina Studio API — Response Pydantic models.
Lumina Studio API — 响应 Pydantic 数据模型。

All API endpoint response schemas are defined here.
所有 API 端点的响应 Schema 均在此定义。
"""

from typing import Any, Optional

from pydantic import BaseModel, Field

from api.schemas.lut import PaletteEntrySchema


class CalibrationResponse(BaseModel):
    """校准板生成响应。"""

    status: str
    message: str
    download_url: str
    preview_url: Optional[str] = None


class SingleStageJobResponse(BaseModel):
    """Single-stage job summary."""

    color: str
    color_name: str
    material: str
    substrate_id: str
    substrate_display_name: str
    filename: str


class SingleStageCoverageResponse(BaseModel):
    """Coverage summary per substrate."""

    substrate_id: str
    colors: list[str]


class SingleStageDatasetItemResponse(BaseModel):
    """Dataset summary for a single substrate/color pair."""

    substrate_id: str
    color_name: str
    image_count: int = 0
    label_count: Optional[int] = None
    calibration: Optional[dict[str, Any]] = None


class SingleStageDatasetSummaryResponse(BaseModel):
    """Aggregate single-stage dataset summary."""

    substrate_count: int
    color_count: int
    dataset_count: int
    image_count: int
    label_count: Optional[int] = None
    substrates: list[str] = Field(default_factory=list)
    coverage: list[SingleStageCoverageResponse] = Field(default_factory=list)
    datasets: list[SingleStageDatasetItemResponse] = Field(default_factory=list)
    uploaded_dataset: Optional[dict[str, Any]] = None


class StageAFitSummaryResponse(BaseModel):
    """Summary of a completed Stage A fit."""

    substrate_count: int
    channel_count: int
    substrates: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    overall_validation: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class SingleStageKitResponse(BaseModel):
    """Single-stage kit generation response."""

    status: str
    message: str
    kit_download_url: str
    preview_url: Optional[str] = None
    manifest_url: str
    jobs: list[SingleStageJobResponse] = Field(default_factory=list)


class SingleStageExtractResponse(BaseModel):
    """Single-stage dataset extraction response."""

    session_id: str
    status: str
    message: str
    stage_json_url: str
    warnings: list[str] = Field(default_factory=list)
    dataset_summary: SingleStageDatasetSummaryResponse


class StageAFitResponse(BaseModel):
    """Stage A fitting response."""

    status: str
    message: str
    stage_a_params_url: str
    fit_summary: StageAFitSummaryResponse


class GradientCardSampleBoxResponse(BaseModel):
    """Warped sample ROI geometry for gradient-card extraction."""

    row: int
    col: int
    x: int
    y: int
    width: int
    height: int
    thickness_layers: int


class GradientCardMaterialSummaryResponse(BaseModel):
    """Summary of extracted gradient-card material data."""

    sample_count: int
    per_substrate_sample_count: int
    grid_rows: int
    grid_cols: int
    layer_height_mm: float
    warp_width_px: int | None = None
    warp_height_px: int | None = None
    thickness_layers: list[int] = Field(default_factory=list)
    sample_boxes: list[GradientCardSampleBoxResponse] = Field(default_factory=list)
    white_zero_rgb: list[int] = Field(default_factory=list)
    black_zero_rgb: list[int] = Field(default_factory=list)
    estimated_rgb: list[int] = Field(default_factory=list)
    estimated_k: list[float] = Field(default_factory=list)


class SavedMaterialSummaryResponse(BaseModel):
    """Summary of a saved material archive."""

    material_name: str
    directory_name: str
    brand: str | None = None
    archive_path: str
    stage_a_params_path: str
    verification_count: int = 1
    created_at: str | None = None
    updated_at: str | None = None


class OrientationCandidateResponse(BaseModel):
    """One orientation candidate in the ranking."""

    white_orientation: str
    black_orientation: str
    anchor_penalty: float = 0.0
    mean_delta_e: float
    rmse_linear: float
    max_delta_e: float


class SubstrateOrientationInfoResponse(BaseModel):
    """Per-substrate orientation diagnostics.
    单基底方向诊断信息。

    Surfaced to the frontend so the user can tell when the auto-detector
    fell back to ``identity`` due to a flat (low-signal) substrate, or when
    a manual override is currently in effect.
    """

    signal_strength: float = 0.0
    flat: bool = False
    manual_override: str | None = None
    locked_to: str | None = None


class OrientationRankingResponse(BaseModel):
    """Orientation detection reliability ranking."""

    orientation_reliable: bool
    delta_e_gap: float
    top_candidates: list[OrientationCandidateResponse] = Field(default_factory=list)
    white_signal_strength: float | None = None
    black_signal_strength: float | None = None
    white_orientation_info: SubstrateOrientationInfoResponse | None = None
    black_orientation_info: SubstrateOrientationInfoResponse | None = None


class GradientCardStageAExtractResponse(BaseModel):
    """Gradient-card Stage A extraction response."""

    session_id: str
    status: str
    message: str
    stage_a_params_url: str
    white_warp_preview_url: str | None = None
    black_warp_preview_url: str | None = None
    fit_summary: StageAFitSummaryResponse
    material_summary: GradientCardMaterialSummaryResponse
    orientation_ranking: OrientationRankingResponse | None = None
    warnings: list[str] = Field(default_factory=list)


class GradientCardMaterialSaveResponse(BaseModel):
    """Gradient-card material archive save response."""

    status: str
    message: str
    material_file_url: str
    stage_a_params_url: str
    material_summary: SavedMaterialSummaryResponse


class GradientCardMaterialDeleteResponse(BaseModel):
    """Gradient-card material archive delete response."""

    status: str
    message: str
    directory_name: str
    material_name: str


class GradientCardMaterialUpdateResponse(BaseModel):
    """Gradient-card material archive metadata update response."""

    status: str
    message: str
    material: "SavedMaterialLibraryItemResponse"


class SavedMaterialVerificationHistoryItemResponse(BaseModel):
    """Summary row for a single saved material verification run."""

    verification_index: int
    captured_at: str | None = None
    mean_delta_e: float | None = None
    rmse_linear: float | None = None
    estimated_rgb: list[int] = Field(default_factory=list)
    estimated_k: list[float] = Field(default_factory=list)
    e_values: list[float] = Field(default_factory=list)
    k_values: list[float] = Field(default_factory=list)
    white_c0_values: list[float] = Field(default_factory=list)
    black_c0_values: list[float] = Field(default_factory=list)
    white_detected_orientation: str | None = None
    black_detected_orientation: str | None = None


class SavedMaterialLibraryItemResponse(BaseModel):
    """Summary row for a saved Stage A material archive."""

    material_name: str
    directory_name: str
    brand: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    archive_path: str
    stage_a_params_path: str | None = None
    material_file_url: str
    stage_a_params_url: str | None = None
    estimated_rgb: list[int] = Field(default_factory=list)
    layer_height_mm: float | None = None
    mean_delta_e: float | None = None
    verification_count: int = 1
    verification_history: list[SavedMaterialVerificationHistoryItemResponse] = Field(default_factory=list)


class GradientCardMaterialLibraryResponse(BaseModel):
    """Saved gradient-card material archive library response."""

    status: str
    message: str
    materials: list[SavedMaterialLibraryItemResponse] = Field(default_factory=list)


class GradientCardMaterialBulkExportResponse(BaseModel):
    """Saved gradient-card material archive bulk export response."""

    status: str
    message: str
    download_url: str
    filename: str
    exported_count: int
    exported_directory_names: list[str] = Field(default_factory=list)


class GradientCardMaterialBulkImportResponse(BaseModel):
    """Saved gradient-card material archive bulk import response."""

    status: str
    message: str
    imported_count: int
    imported_materials: list[SavedMaterialSummaryResponse] = Field(default_factory=list)


class MaterialSolverCacheEntryResponse(BaseModel):
    """Metadata for a single persisted material-solver cache entry.
    单个耗材求解器缓存条目的元数据。

    The ``palette_fingerprint`` identifies which saved materials were combined.
    ``total_combinations`` and ``valid_cell_count`` describe the enumeration
    coverage; ``mean_delta_e`` / ``max_delta_e`` summarise bucket-center quality.
    """

    palette_hash: str
    material_directory_names: list[str] = Field(default_factory=list)
    layer_count: int
    layer_height_mm: float
    substrate: str
    grid_resolution: int
    total_combinations: int
    valid_cell_count: int
    total_cell_count: int
    mean_delta_e: float
    max_delta_e: float
    build_time_seconds: float
    built_at: str | None = None
    cache_file_size_bytes: int = 0
    cache_file_path: str | None = None


class MaterialSolverCacheStatusResponse(BaseModel):
    """Status check for a specific ``(palette, N, t, substrate)`` combination.
    针对指定 ``(调色板, 层数, 层厚, 基底)`` 组合的缓存状态。

    ``cached`` is ``True`` when a compatible cache exists on disk; in that
    case ``entry`` carries the loaded metadata. Otherwise ``entry`` is ``None``
    and the caller should call the build endpoint to create it.
    """

    status: str
    message: str
    cached: bool
    palette_hash: str
    layer_count: int
    layer_height_mm: float
    substrate: str
    entry: MaterialSolverCacheEntryResponse | None = None


class MaterialSolverCacheBuildResponse(BaseModel):
    """Response after an explicit cache build.
    显式构建缓存后的响应。
    """

    status: str
    message: str
    entry: MaterialSolverCacheEntryResponse


class MaterialSolverCacheListResponse(BaseModel):
    """Listing response for all persisted solver caches.
    所有已持久化求解器缓存的列表响应。
    """

    status: str
    message: str
    entries: list[MaterialSolverCacheEntryResponse] = Field(default_factory=list)


class MaterialColorSuggestionItem(BaseModel):
    """One achievable-color candidate returned by the suggester.
    颜色建议器返回的一个可达色候选。

    ``hex`` / ``rgb`` describe the predicted sRGB of the candidate; ``recipe``
    is the per-layer material index array (bottom-to-top), using the same
    ``material_directory_names`` order the caller submitted. ``recipe_display``
    is a short human-readable representation (e.g. ``"[0,2,1,2,0]"``) suitable
    for tooltips.
    """

    hex: str
    rgb: list[int]
    delta_e: float
    recipe: list[int]
    recipe_display: str


class MaterialColorSuggestionsResponse(BaseModel):
    """Response for the "suggest achievable colors near target" endpoint.
    "为目标色推荐可达近似色" 接口的响应。

    ``source`` is ``"cache"`` when a persisted ``MaterialSolverCache`` served
    the query, ``"mitm"`` when the MITM fallback ran in-process. The frontend
    uses this to decide whether to nudge the user to build a cache.
    """

    status: str
    message: str
    source: str
    palette_hash: str
    layer_count: int
    layer_height_mm: float
    substrate: str
    target_hex: str
    target_rgb: list[int]
    suggestions: list[MaterialColorSuggestionItem] = Field(default_factory=list)


class MaterialSolverCacheDeleteResponse(BaseModel):
    """Delete response for a solver cache entry.
    求解器缓存条目的删除响应。
    """

    status: str
    message: str
    deleted: bool
    palette_hash: str
    layer_count: int
    layer_height_mm: float
    substrate: str


class RecipePredictResponse(BaseModel):
    """Recipe color prediction response."""

    status: str
    message: str
    rgb: list[int] = Field(default_factory=list)
    lab: list[float] = Field(default_factory=list)
    source: str
    runtime_mode_key: str | None = None


class RecipeOverrideApplyResponse(BaseModel):
    """Recipe override apply response."""

    status: str
    message: str
    preview_url: str
    preview_glb_url: str | None = None
    rgb: list[int] = Field(default_factory=list)
    lab: list[float] = Field(default_factory=list)
    source: str
    runtime_mode_key: str | None = None
    override_count: int = 0


class RegionRecipeEntry(BaseModel):
    """Per-region current recipe payload.
    单个区域的当前 recipe 返回体。
    """

    region_id: str
    recipe: list[int] = Field(default_factory=list)
    color_layers: int = 0
    layer_height_mm: float = 0.08
    layer_order: str = "Top2Bottom"


class RegionRecipeResponse(BaseModel):
    """Response for ``POST /api/convert/region-recipe``.

    Carries the current per-layer material indices that the pipeline has
    already matched for each requested region, so the Custom Recipe dialog
    can pre-populate its per-layer dropdowns instead of defaulting to White.

    每个请求区域当前已匹配到的逐层材料索引，供自定义配方对话框把下拉框
    预设成该区域的真实配方，而不是默认的全白。
    """

    status: str
    message: str
    recipes: list[RegionRecipeEntry] = Field(default_factory=list)


class PreviewResponse(BaseModel):
    """预览生成响应。"""

    session_id: str
    status: str
    message: str
    preview_url: str
    preview_glb_url: Optional[str] = None
    lut_match_mode: Optional[str] = None
    lut_match_info: Optional[dict[str, Any]] = None
    palette: list[dict]
    dimensions: dict
    contours: Optional[dict[str, list[list[list[float]]]]] = None
    warnings: list[str] = Field(default_factory=list)


class ColorReplaceResponse(BaseModel):
    """颜色替换响应。"""

    status: str
    message: str
    preview_url: str
    preview_3d_url: str | None = None
    replacement_count: int


class MergePreviewResponse(BaseModel):
    """颜色合并预览响应。"""

    status: str
    message: str
    preview_url: str
    merge_map: dict[str, str]
    quality_metric: float
    colors_before: int
    colors_after: int


class GenerateResponse(BaseModel):
    """3MF 生成响应。"""

    status: str
    message: str
    download_url: str
    preview_3d_url: Optional[str] = None
    threemf_disk_path: Optional[str] = None


class RecipePredictionResponse(BaseModel):
    """Predictive custom recipe color response."""

    status: str
    message: str
    rgb: list[int] = Field(default_factory=list)
    hex: str = ""
    lab: list[float] = Field(default_factory=list)
    source: str = ""
    runtime_mode_key: Optional[str] = None


class PuzzleLayoutPreviewResponse(BaseModel):
    """拼图布局预览响应。"""

    status: str
    message: str
    overlay_url: str
    piece_count: int
    grid_cols: int
    grid_rows: int
    derived_piece_width_mm: float | None = None
    derived_piece_height_mm: float | None = None
    warnings: list[str] = Field(default_factory=list)
    piece_areas_mm2: list[float] = Field(default_factory=list)


class PuzzleGenerateResponse(BaseModel):
    """拼图生成响应。"""

    status: str
    message: str
    download_url: str
    threemf_disk_path: Optional[str] = None
    piece_count: int
    grid_cols: int
    grid_rows: int
    warnings: list[str] = Field(default_factory=list)


class LargeFormatGenerateResponse(BaseModel):
    """大画幅切片生成响应。"""

    status: str
    message: str
    download_url: str
    tile_count: int
    grid_cols: int
    grid_rows: int
    warnings: list[str] = Field(default_factory=list)


class BatchItemResult(BaseModel):
    """批量转换单项结果。"""

    filename: str
    status: str
    error: Optional[str] = None


class BatchResponse(BaseModel):
    """批量转换响应。"""

    status: str
    message: str
    download_url: str
    results: list[BatchItemResult]


class LutInfo(BaseModel):
    """单个 LUT 预设信息。"""

    name: str
    color_mode: str
    path: str
    fingerprint: str = ""


class LUTListResponse(BaseModel):
    """LUT 列表响应。"""

    luts: list[LutInfo]


class WorkerPoolStatus(BaseModel):
    """Worker Pool 状态信息。"""

    healthy: bool
    max_workers: int


class HealthResponse(BaseModel):
    """健康检查响应（含 Worker Pool 状态）。"""

    status: str
    version: str
    uptime_seconds: float
    worker_pool: WorkerPoolStatus


class ExtractResponse(BaseModel):
    """颜色提取响应。"""

    session_id: str
    status: str
    message: str
    lut_download_url: str
    warp_view_url: str
    lut_preview_url: str
    default_palette: list[PaletteEntrySchema] = Field(
        default_factory=list,
        description="默认调色板数组，每项含 color、material、hex_color、color_name",
    )


class ManualFixResponse(BaseModel):
    """手动修正响应。"""

    status: str
    message: str
    lut_preview_url: str


class HeightmapUploadResponse(BaseModel):
    """高度图上传响应。"""

    status: str
    message: str
    thumbnail_url: str
    original_size: tuple[int, int]
    color_height_map: dict[str, float]
    warnings: list[str]


class LutColorEntry(BaseModel):
    """单个 LUT 颜色条目。"""

    hex: str
    rgb: tuple[int, int, int]


class LutColorsResponse(BaseModel):
    """LUT 颜色列表响应。"""

    lut_name: str
    total: int
    colors: list[LutColorEntry]


class CropResponse(BaseModel):
    """裁剪响应。"""

    status: str
    message: str
    cropped_url: str
    width: int
    height: int


class AutoDetectColorsResponse(BaseModel):
    """自动检测推荐量化颜色数响应。"""

    recommended: int
    max_safe: int
    unique_colors: int
    complexity_score: int


class ResetReplacementsResponse(BaseModel):
    """颜色替换重置响应。"""

    status: str
    message: str
    preview_url: str
    preview_glb_url: str | None = None
