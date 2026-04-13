import { useRef, useEffect, useMemo, useState, useCallback } from "react";
import { useShallow } from "zustand/react/shallow";
import { useConverterStore, ACCEPT_IMAGE_FORMATS, resolveConverterSourceSelection } from "../../stores/converter";
import {
  ColorMode,
  ModelingMode,
  StructureMode,
} from "../../api/types";
import UnifiedUploader from "../ui/UnifiedUploader";
import Checkbox from "../ui/Checkbox";
import Dropdown from "../ui/Dropdown";
import Slider from "../ui/Slider";
import Button from "../ui/Button";
import RadioGroup from "../ui/RadioGroup";
import { CropModal } from "../ui/CropModal";
import type { CropData } from "../ui/CropModal";
import ImportConfirmDialog from "../ui/ImportConfirmDialog";
import { useI18n } from "../../i18n/context";
import { useWorkspaceMode } from "../../hooks/useWorkspaceMode";
import { prepareImport, applyImport, revokeImportCoverUrl } from "../../recipe/importFlow";
import type { ImportPreview } from "../../recipe/importFlow";
import type { RecipeFileSource } from "../../recipe/importRecipe";

const COLOR_MODE_DOTS: Record<string, string[]> = {
  [ColorMode.BW]: ["var(--palette-black)", "var(--palette-white)"],
  [ColorMode.FOUR_COLOR_RYBW]: ["var(--palette-crimson)", "var(--palette-yellow)", "var(--palette-blue)", "var(--palette-white)"],
  [ColorMode.FOUR_COLOR_CMYW]: ["var(--palette-cyan)", "var(--palette-magenta)", "var(--palette-yellow-soft)", "var(--palette-white)"],
  [ColorMode.FIVE_COLOR_EXT]: ["var(--palette-white)", "var(--palette-crimson)", "var(--palette-yellow)", "var(--palette-blue)", "var(--palette-charcoal)"],
  [ColorMode.SIX_COLOR]: ["var(--palette-white)", "var(--palette-cyan)", "var(--palette-magenta)", "var(--palette-green)", "var(--palette-yellow-soft)", "var(--palette-black)"],
  [ColorMode.SIX_COLOR_RYBW]: ["var(--palette-white)", "var(--palette-crimson)", "var(--palette-yellow)", "var(--palette-blue)", "var(--palette-green)", "var(--palette-black)"],
  [ColorMode.EIGHT_COLOR]: [
    "var(--palette-white)", "var(--palette-cyan)", "var(--palette-magenta)", "var(--palette-yellow-soft)",
    "var(--palette-black)", "var(--palette-brick)", "var(--palette-indigo)", "var(--palette-green)",
  ],
};

const DOT_CLS = "inline-block size-2 rounded-full shrink-0 ring-1 ring-black/10 dark:ring-white/20";

function ColorModeDots({ mode }: { mode: string }) {
  if (mode === ColorMode.MERGED) {
    return (
      <span
        className={`${DOT_CLS} animate-spin [animation-duration:3s]`}
        style={{
          background:
            "conic-gradient(var(--palette-crimson), var(--palette-yellow-soft), var(--palette-green), var(--palette-cyan), var(--palette-magenta), var(--palette-crimson))",
        }}
      />
    );
  }

  const dots = COLOR_MODE_DOTS[mode];
  if (!dots) return null;

  return (
    <span className="inline-flex items-center gap-0.5">
      {dots.map((color, i) => (
        <span
          key={i}
          className={DOT_CLS}
          style={{ backgroundColor: color }}
        />
      ))}
    </span>
  );
}

export default function BasicSettings() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();

  const structureModeOptions = Object.values(StructureMode).map((v) => ({
    label: t(`structure_mode.${v}`),
    value: v,
  }));

  const modelingModeOptions = Object.values(ModelingMode).map((v) => ({
    label: t(`modeling_mode.${v}`),
    value: v,
  }));
  // 状态字段使用 useShallow 分组提取，避免无关字段变化触发重渲染
  const {
    imageFile,
    imagePreviewUrl,
    source_version,
    lut_name,
    lutList,
    nativeBrandGroups,
    nativeBrandGroupsLoading,
    selectedNativeBrandKey,
    selectedNativeDbNames,
    color_mode,
    color_layers,
    layer_height_mm,
    model_enable,
    model_only,
    selectedLutInfo,
    target_width_mm,
    target_height_mm,
    spacer_thick,
    structure_mode,
    modeling_mode,
    enable_relief,
    enableCrop,
    cropModalOpen,
    isCropping,
    batchMode,
    batchFiles,
    largeFormatEnabled,
    enable_fridge_magnet,
    puzzleEnabled,
    tileWidthMm,
    tileHeightMm,
    previewImageUrl,
    setColorLayers,
    setLayerHeightMm,
    setModelEnable,
    setModelOnly,
    setSourceVersion,
    setNativeBrandKey,
    setNativeSupportedMode,
    setNativeDbNames,
  } = useConverterStore(useShallow((s) => ({
    imageFile: s.imageFile,
    imagePreviewUrl: s.imagePreviewUrl,
    source_version: s.source_version,
    lut_name: s.lut_name,
    lutList: s.lutList,
    nativeBrandGroups: s.nativeBrandGroups,
    nativeBrandGroupsLoading: s.nativeBrandGroupsLoading,
    selectedNativeBrandKey: s.selectedNativeBrandKey,
    selectedNativeDbNames: s.selectedNativeDbNames,
    color_mode: s.color_mode,
    color_layers: s.color_layers,
    layer_height_mm: s.layer_height_mm,
    model_enable: s.model_enable,
    model_only: s.model_only,
    selectedLutInfo: s.selectedLutInfo,
    target_width_mm: s.target_width_mm,
    target_height_mm: s.target_height_mm,
    spacer_thick: s.spacer_thick,
    structure_mode: s.structure_mode,
    modeling_mode: s.modeling_mode,
    enable_relief: s.enable_relief,
    enableCrop: s.enableCrop,
    cropModalOpen: s.cropModalOpen,
    isCropping: s.isCropping,
    batchMode: s.batchMode,
    batchFiles: s.batchFiles,
    largeFormatEnabled: s.largeFormatEnabled,
    enable_fridge_magnet: s.enable_fridge_magnet,
    puzzleEnabled: s.puzzleEnabled,
    tileWidthMm: s.tileWidthMm,
    tileHeightMm: s.tileHeightMm,
    previewImageUrl: s.previewImageUrl,
    setColorLayers: s.setColorLayers,
    setLayerHeightMm: s.setLayerHeightMm,
    setModelEnable: s.setModelEnable,
    setModelOnly: s.setModelOnly,
    setSourceVersion: s.setSourceVersion,
    setNativeBrandKey: s.setNativeBrandKey,
    setNativeSupportedMode: s.setNativeSupportedMode,
    setNativeDbNames: s.setNativeDbNames,
  })));

  const sourceSelection = useMemo(
    () =>
      resolveConverterSourceSelection({
        source_version,
        lut_name,
        nativeBrandGroups,
        selectedNativeBrandKey,
        selectedNativeDbNames,
        color_layers,
        layer_height_mm,
      }),
    [
      source_version,
      lut_name,
      nativeBrandGroups,
      selectedNativeBrandKey,
      selectedNativeDbNames,
      color_layers,
      layer_height_mm,
    ],
  );

  const [uploaderExpanded, setUploaderExpanded] = useState(true);

  // --- Share card import state ---
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null);
  const [importSource, setImportSource] = useState<RecipeFileSource>("png");
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [importLoading, setImportLoading] = useState(false);

  const handleShareCardDetected = useCallback(async (file: File) => {
    try {
      setImportLoading(true);
      const preview = await prepareImport(file);
      setImportPreview(preview);
      setImportSource(file.name.toLowerCase().endsWith(".lumina.json") ? "json" : "png");
      setImportDialogOpen(true);
    } catch (err) {
      useConverterStore.getState().setError(
        err instanceof Error ? err.message : "Import failed",
      );
    } finally {
      setImportLoading(false);
    }
  }, []);

  const handleImportConfirm = useCallback(() => {
    if (!importPreview) return;
    applyImport(importPreview.restoreResult);
    revokeImportCoverUrl(importPreview.coverUrl);
    setImportDialogOpen(false);
    setImportPreview(null);
  }, [importPreview]);

  const handleImportCancel = useCallback(() => {
    revokeImportCoverUrl(importPreview?.coverUrl ?? null);
    setImportDialogOpen(false);
    setImportPreview(null);
  }, [importPreview]);

  useEffect(() => {
    if (previewImageUrl) setUploaderExpanded(false);
  }, [previewImageUrl]);

  useEffect(() => {
    if (!imageFile) setUploaderExpanded(true);
  }, [imageFile]);

  // Action 函数单独提取（函数引用稳定，不需要 shallow）
  const handleFilesSelect = useConverterStore((s) => s.handleFilesSelect);
  const setLutName = useConverterStore((s) => s.setLutName);
  const setTargetWidthMm = useConverterStore((s) => s.setTargetWidthMm);
  const setTargetHeightMm = useConverterStore((s) => s.setTargetHeightMm);
  const setSpacerThick = useConverterStore((s) => s.setSpacerThick);
  const setStructureMode = useConverterStore((s) => s.setStructureMode);
  const setModelingMode = useConverterStore((s) => s.setModelingMode);
  const setEnableCrop = useConverterStore((s) => s.setEnableCrop);
  const setCropModalOpen = useConverterStore((s) => s.setCropModalOpen);
  const submitCrop = useConverterStore((s) => s.submitCrop);
  const uploadLut = useConverterStore((s) => s.uploadLut);
  const removeBatchFile = useConverterStore((s) => s.removeBatchFile);
  const setLargeFormatEnabled = useConverterStore((s) => s.setLargeFormatEnabled);
  const setTileWidthMm = useConverterStore((s) => s.setTileWidthMm);
  const setTileHeightMm = useConverterStore((s) => s.setTileHeightMm);

  const lutOptions = lutList.map((name) => ({ label: name, value: name }));
  const sourceVersionOptions = [
    { label: t("basic_source_version_legacy"), value: "legacy" },
    { label: t("basic_source_version_native"), value: "native" },
  ];
  const nativeBrandOptions = nativeBrandGroups
    .map((group) => ({
      label: group.display_name,
      value: group.brand_key,
    }));
  const selectedNativeBrand = sourceSelection.native.brand;
  const selectedNativeSupportedModes = sourceSelection.native.supported_modes;
  const selectedNativeMode = sourceSelection.native.supported_mode;
  const selectedNativePredictiveModelAvailable = sourceSelection.native.predictive_model_available;
  const selectedNativeDbSet = useMemo(() => new Set(sourceSelection.native.db_names), [sourceSelection.native.db_names]);
  const nativeLayerCount = selectedNativeMode?.color_layers ?? color_layers ?? 5;
  const nativeLayerHeightMm = layer_height_mm ?? selectedNativeMode?.layer_height_mm ?? 0.08;

  const lutFileRef = useRef<HTMLInputElement>(null);

  // 5-Color Extended 模式下强制锁定为单面（浮雕）
  const isFiveColorExt = color_mode === ColorMode.FIVE_COLOR_EXT;
  const supportsDynamicLayers = !!selectedLutInfo?.supports_dynamic_layer_count;
  const supportedModes = useMemo(
    () => selectedLutInfo?.supported_modes ?? [],
    [selectedLutInfo?.supported_modes],
  );
  const supportedLayerHeightOptions = useMemo(() => {
    const heights = Array.from(
      new Set(
        supportedModes
          .map((mode) => mode.layer_height_mm)
          .filter((value): value is number => typeof value === "number" && Number.isFinite(value)),
      ),
    ).sort((left, right) => left - right);
    const fallback = layer_height_mm ?? selectedLutInfo?.layer_height_mm ?? 0.08;
    if (heights.length === 0) {
      return [{ label: `${fallback.toFixed(2)} mm`, value: String(fallback) }];
    }
    return heights.map((value) => ({
      label: `${value.toFixed(2)} mm`,
      value: String(value),
    }));
  }, [layer_height_mm, selectedLutInfo?.layer_height_mm, supportedModes]);
  useEffect(() => {
    if (isFiveColorExt && structure_mode === StructureMode.DOUBLE_SIDED) {
      setStructureMode(StructureMode.SINGLE_SIDED);
    }
  }, [isFiveColorExt, structure_mode, setStructureMode]);

  const handleLutUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await uploadLut(file);
    // Reset so same file can be re-uploaded
    if (lutFileRef.current) lutFileRef.current.value = "";
  };

  const handleCropConfirm = (data: CropData) => {
    void submitCrop(data.x, data.y, data.width, data.height);
  };

  const handleNativeDbToggle = (dbName: string) => {
    if (!selectedNativeBrand) return;
    const nextNames = selectedNativeDbSet.has(dbName)
      ? sourceSelection.native.db_names.filter((name) => name !== dbName)
      : [...sourceSelection.native.db_names, dbName];
    const allowedNames = new Set(selectedNativeBrand.db_options.map((option) => option.name));
    const ordered = selectedNativeBrand.db_options
      .map((option) => option.name)
      .filter((name) => allowedNames.has(name) && nextNames.includes(name));
    setNativeDbNames(ordered);
  };

  const handleNativeLayerCountChange = (count: number) => {
    const mode =
      resolveNativeSupportedModeByCount(
        selectedNativeSupportedModes,
        count,
        nativeLayerHeightMm,
      ) ?? selectedNativeMode;
    if (!mode) return;
    setNativeSupportedMode({
      color_layers: mode.color_layers,
      layer_height_mm: mode.layer_height_mm,
    });
  };

  const dimMax = largeFormatEnabled ? 9999 : 400;

  const tileGrid = useMemo(() => {
    if (!largeFormatEnabled) return null;
    const cols = Math.max(1, Math.ceil(target_width_mm / tileWidthMm));
    const rows = Math.max(1, Math.ceil(target_height_mm / tileHeightMm));
    const lastW = Math.round(target_width_mm - (cols - 1) * tileWidthMm);
    const lastH = Math.round(target_height_mm - (rows - 1) * tileHeightMm);
    return { cols, rows, total: cols * rows, lastW, lastH };
  }, [largeFormatEnabled, target_width_mm, target_height_mm, tileWidthMm, tileHeightMm]);

  return (
    <div className="flex flex-col gap-4">
      {uploaderExpanded ? (
        <UnifiedUploader
          singlePreview={imagePreviewUrl ?? undefined}
          batchFiles={batchFiles}
          isBatchMode={batchMode}
          onFilesSelect={handleFilesSelect}
          onBatchFileRemove={removeBatchFile}
          accept={ACCEPT_IMAGE_FORMATS}
          onShareCardDetected={(file) => void handleShareCardDetected(file)}
        />
      ) : (
        <button
          type="button"
          onClick={() => setUploaderExpanded(true)}
          className="flex items-center gap-2 rounded-2xl border border-slate-200/80 bg-slate-100/70 px-3 py-2 text-left transition-colors hover:bg-slate-100/90 dark:border-slate-700/60 dark:bg-slate-900/50 dark:hover:bg-slate-900/80"
        >
          {imagePreviewUrl && (
            <img
              src={imagePreviewUrl}
              alt=""
              className="h-8 w-8 shrink-0 rounded-lg object-cover"
            />
          )}
          <span className="min-w-0 flex-1 truncate text-[clamp(0.65rem,0.85vw,0.75rem)] text-slate-600 dark:text-slate-300">
            {imageFile?.name ?? t("upload_unified_hint")}
          </span>
          <span className="shrink-0 text-[10px] text-slate-400 dark:text-slate-500">
            {t("upload_tap_to_change")}
          </span>
        </button>
      )}

      {batchFiles.length === 0 && imageFile !== null && (
        <>
          <Checkbox
            label={t("basic_crop_after_upload")}
            checked={enableCrop}
            onChange={setEnableCrop}
          />

          <CropModal
            open={cropModalOpen}
            imageSrc={imagePreviewUrl ?? ""}
            onConfirm={handleCropConfirm}
            onUseOriginal={() => setCropModalOpen(false)}
            onClose={() => setCropModalOpen(false)}
            isLoading={isCropping}
          />
        </>
      )}

      <RadioGroup
        label={t("basic_source_version_label")}
        value={source_version}
        options={sourceVersionOptions}
        onChange={(value) => setSourceVersion(value as "legacy" | "native")}
      />

      {source_version === "legacy" ? (
        <>
          <div className={`gap-2 ${workspace.isCompact ? "grid grid-cols-1" : "flex items-end"}`}>
            <div className="min-w-0 flex-1">
              <Dropdown
                label={t("basic_lut_label")}
                value={lut_name}
                options={lutOptions}
                onChange={setLutName}
                placeholder={t("basic_lut_placeholder")}
              />
            </div>
            <input
              ref={lutFileRef}
              type="file"
              accept=".npy,.json,.npz,.msgpack"
              className="hidden"
              onChange={(e) => void handleLutUpload(e)}
            />
            <Button
              label={`+ ${t("basic_lut_upload")}`}
              variant="secondary"
              onClick={() => lutFileRef.current?.click()}
              className={workspace.isCompact ? "w-full px-3" : "shrink-0 whitespace-nowrap px-3"}
            />
          </div>

          {lut_name && (
            <div className="-mt-2 px-1 text-xs text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
              <span>{t("basic_color_mode_label")}:</span>
              <ColorModeDots mode={color_mode} />
              <span>{color_mode}</span>
            </div>
          )}

          {lut_name && selectedLutInfo && (
            <div className="-mt-1 flex flex-col gap-3 rounded-lg border border-slate-200/60 bg-slate-100/50 p-3 dark:border-slate-700/40 dark:bg-slate-900/40">
              <div className="text-xs text-slate-500 dark:text-slate-400">
                {t("basic_source_kind_label")}: {selectedLutInfo.source_kind ?? "legacy_lookup"}
              </div>
              {supportsDynamicLayers ? (
                <>
                  <Slider
                    label={t("basic_color_layers_label")}
                    value={color_layers ?? selectedLutInfo.max_color_layers ?? 5}
                    min={1}
                    max={10}
                    step={1}
                    onChange={(value) => setColorLayers(Math.round(value))}
                  />
                  <Dropdown
                    label={t("basic_layer_height_label")}
                    value={String(layer_height_mm ?? selectedLutInfo.layer_height_mm ?? 0.08)}
                    options={supportedLayerHeightOptions}
                    onChange={(value) => setLayerHeightMm(Number(value))}
                  />
                  {supportedModes.length > 0 && (
                    <div className="text-xs text-slate-500 dark:text-slate-400">
                      {t("basic_supported_modes_label")}:{" "}
                      {supportedModes
                        .map((mode) => `${mode.color_layers}L @ ${mode.layer_height_mm.toFixed(2)}mm`)
                        .join(", ")}
                    </div>
                  )}
                </>
              ) : (
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  {t("basic_dynamic_layers_legacy_hint")}
                </div>
              )}
            </div>
          )}
        </>
      ) : (
        <>
          <div className={`gap-2 ${workspace.isCompact ? "grid grid-cols-1" : "flex items-end"}`}>
            <div className="min-w-0 flex-1">
              <Dropdown
                label={t("basic_brand_label")}
                value={selectedNativeBrand?.brand_key ?? ""}
                options={nativeBrandOptions}
                onChange={setNativeBrandKey}
                placeholder={nativeBrandGroupsLoading ? t("basic_brand_loading") : t("basic_brand_placeholder")}
                disabled={nativeBrandGroupsLoading || nativeBrandOptions.length === 0}
              />
            </div>
          </div>

          {selectedNativeBrand ? (
            <div className="-mt-1 flex flex-col gap-3 rounded-lg border border-slate-200/60 bg-slate-100/50 p-3 dark:border-slate-700/40 dark:bg-slate-900/40">
              <div className="text-xs text-slate-500 dark:text-slate-400">
                {t("basic_native_brand_summary_label")}:
                <span className="ml-1 text-slate-700 dark:text-slate-200">
                  {selectedNativeBrand.display_name}
                </span>
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400">
                {t("basic_native_material_label")}: {selectedNativeBrand.material_type}
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400">
                {t("basic_native_vendor_label")}: {selectedNativeBrand.vendor}
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400">
                {t("basic_native_db_label")}:
                <span className="ml-1 text-slate-700 dark:text-slate-200">
                  {sourceSelection.native.db_names.length > 0
                    ? sourceSelection.native.db_names.join(", ")
                    : t("basic_native_db_placeholder")}
                </span>
              </div>

              <div className="grid gap-2">
                {selectedNativeBrand.db_options.map((dbOption) => (
                  <Checkbox
                    key={dbOption.name}
                    label={dbOption.name}
                    checked={selectedNativeDbSet.has(dbOption.name)}
                    onChange={() => handleNativeDbToggle(dbOption.name)}
                  />
                ))}
              </div>

              <Slider
                label={t("basic_native_layer_count_label")}
                value={nativeLayerCount}
                min={1}
                max={15}
                step={1}
                onChange={(value) => handleNativeLayerCountChange(Math.round(value))}
                disabled={selectedNativeSupportedModes.length === 0}
              />
              {selectedNativeSupportedModes.length > 0 && (
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  {t("basic_supported_modes_label")}:{" "}
                  {selectedNativeSupportedModes
                    .map((mode) => `${mode.color_layers}L @ ${mode.layer_height_mm.toFixed(2)}mm`)
                    .join(", ")}
                </div>
              )}

              {selectedNativePredictiveModelAvailable && (
                <div className="flex flex-col gap-3 rounded-lg border border-slate-200/60 bg-slate-50/70 p-3 dark:border-slate-700/40 dark:bg-slate-950/30">
                  <div className="text-xs font-medium uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">
                    {t("basic_model_gate_label")}
                  </div>
                  <div className="grid gap-2">
                    <Checkbox
                      label={t("basic_model_enable")}
                      checked={model_enable}
                      onChange={setModelEnable}
                    />
                    <Checkbox
                      label={t("basic_model_only")}
                      checked={model_only}
                      onChange={setModelOnly}
                    />
                  </div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">
                    {t("basic_model_runtime_defaults_hint")}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="-mt-1 rounded-lg border border-dashed border-slate-300/70 bg-slate-100/35 p-3 text-xs text-slate-500 dark:border-slate-700/60 dark:bg-slate-900/25 dark:text-slate-400">
              {t("basic_native_brand_placeholder")}
            </div>
          )}
        </>
      )}

      <Slider
        label={t("basic_width")}
        value={target_width_mm}
        min={10}
        max={dimMax}
        step={1}
        unit="mm"
        onChange={setTargetWidthMm}
      />

      <Slider
        label={t("basic_height")}
        value={target_height_mm}
        min={10}
        max={dimMax}
        step={1}
        unit="mm"
        onChange={setTargetHeightMm}
      />

      <Checkbox
        label={t("basic_large_format")}
        checked={largeFormatEnabled}
        onChange={setLargeFormatEnabled}
        disabled={puzzleEnabled || enable_fridge_magnet}
        tooltip={t("basic_large_format_hint")}
      />

      {puzzleEnabled && !largeFormatEnabled && (
        <div className="-mt-2 px-1 text-xs text-slate-500 dark:text-slate-400">
          {t("puzzle_large_format_disabled_hint")}
        </div>
      )}

      {largeFormatEnabled && (
        <div className="flex flex-col gap-3 rounded-lg border border-slate-200/60 bg-slate-100/50 p-3 dark:border-slate-700/40 dark:bg-slate-900/40">
          <Slider
            label={t("basic_tile_width")}
            value={tileWidthMm}
            min={50}
            max={500}
            step={10}
            unit="mm"
            onChange={setTileWidthMm}
          />
          <Slider
            label={t("basic_tile_height")}
            value={tileHeightMm}
            min={50}
            max={500}
            step={10}
            unit="mm"
            onChange={setTileHeightMm}
          />
          {tileGrid && (
            <div className="-mt-1 px-1 text-xs text-slate-500 dark:text-slate-400">
              {tileGrid.cols}×{tileGrid.rows} = {tileGrid.total}
              {tileGrid.total > 1 && (tileGrid.lastW !== tileWidthMm || tileGrid.lastH !== tileHeightMm)
                ? ` (${tileGrid.lastW}×${tileGrid.lastH}mm)`
                : ""}
            </div>
          )}
        </div>
      )}

      <Slider
        label={t("basic_thickness")}
        value={spacer_thick}
        min={0.2}
        max={3.5}
        step={0.08}
        unit="mm"
        onChange={setSpacerThick}
      />

      <RadioGroup
        label={t("basic_structure_mode")}
        value={structure_mode}
        options={structureModeOptions}
        onChange={(v) => setStructureMode(v as StructureMode)}
        disabled={enable_relief || enable_fridge_magnet}
        disabledValues={isFiveColorExt ? [StructureMode.DOUBLE_SIDED] : []}
      />

      <RadioGroup
        label={t("basic_modeling_mode")}
        value={modeling_mode}
        options={modelingModeOptions}
        onChange={(v) => setModelingMode(v as ModelingMode)}
      />

      <ImportConfirmDialog
        open={importDialogOpen}
        preview={importPreview}
        source={importSource}
        onConfirm={handleImportConfirm}
        onCancel={handleImportCancel}
        isLoading={importLoading}
      />
    </div>
  );
}

function resolveNativeSupportedModeByCount(
  modes: { color_layers: number; layer_height_mm: number }[],
  colorLayers: number,
  preferredLayerHeightMm: number,
): { color_layers: number; layer_height_mm: number } | null {
  if (modes.length === 0) {
    return null;
  }

  const matchingLayers = modes.filter((mode) => mode.color_layers === colorLayers);
  if (matchingLayers.length === 0) {
    return null;
  }

  const exactHeight = matchingLayers.find((mode) => mode.layer_height_mm === preferredLayerHeightMm);
  if (exactHeight) {
    return exactHeight;
  }

  let preferred = matchingLayers[0];
  let smallestDistance = Math.abs(preferred.layer_height_mm - preferredLayerHeightMm);
  for (const mode of matchingLayers.slice(1)) {
    const distance = Math.abs(mode.layer_height_mm - preferredLayerHeightMm);
    if (distance < smallestDistance) {
      preferred = mode;
      smallestDistance = distance;
    }
  }

  return preferred;
}
