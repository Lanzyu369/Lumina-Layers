import { useRef, useEffect, useMemo, useState, useCallback } from "react";
import { useShallow } from "zustand/react/shallow";
import {
  useConverterStore,
  ACCEPT_IMAGE_FORMATS,
  MATERIAL_DYNAMIC_LAYER_COUNT_MAX,
  MATERIAL_DYNAMIC_LAYER_COUNT_MIN,
  inferDefaultMaterialBackingDirName,
  isValidImageType,
  resolveConverterSourceSelection,
} from "../../stores/converter";
import {
  ColorMode,
  ModelingMode,
  StructureMode,
} from "../../api/types";
import { apiErrorToVisibleMessage } from "../../api/client";
import type { SavedMaterialLibraryItem } from "../../api/types";
import { listGradientCardMaterials } from "../../api/extractor";
import { reconcileDirectoryNames } from "../../utils/materialDirectoryMigration";
import UnifiedUploader from "../ui/UnifiedUploader";
import Checkbox from "../ui/Checkbox";
import Dropdown from "../ui/Dropdown";
import Slider from "../ui/Slider";
import RadioGroup from "../ui/RadioGroup";
import { CropModal } from "../ui/CropModal";
import type { CropData } from "../ui/CropModal";
import ImportConfirmDialog from "../ui/ImportConfirmDialog";
import MaterialPickerDialog from "../ui/MaterialPickerDialog";
import MaterialSolverCacheDialog from "../MaterialSolverCacheDialog";
import LegacyLutSelector from "./LegacyLutSelector";
import { tRuntime } from "../../i18n/runtime";
import { useI18n } from "../../i18n/context";
import { useWorkspaceMode } from "../../hooks/useWorkspaceMode";
import { prepareImport, applyImport, revokeImportCoverUrl } from "../../recipe/importFlow";
import type { ImportPreview } from "../../recipe/importFlow";
import {
  RECIPE_ASSET_CORRUPT_ERROR,
  RECIPE_IMPORT_NOT_SHARE_CARD_ERROR,
  RECIPE_INTEGRITY_ERROR,
  type RecipeFileSource,
} from "../../recipe/importRecipe";
import { StatusBanner, workstationInputClass } from "../ui/panelPrimitives";
import {
  buildLutCatalogIndex,
  getBucketDisplayColorMode,
  listBucketsForManufacturer,
  normalizeLutPath,
  type ColorModeBucket,
} from "../../stores/converter/legacyLutSelection";

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
const THICKNESS_LAYER_STEP_MM = 0.08;
const THICKNESS_SLIDER_MIN_MM = 0.24;
const THICKNESS_SLIDER_MAX_MM = 3.44;
const GENERIC_HTTP_STATUS_ERROR_RE =
  /(?:Request failed with status code|HTTP(?:\s+error)?|status(?:\s+code)?)\s*\d{3}\b/i;
const STARTUP_LUT_RETRY_DELAY_MS = 5_000;
const STARTUP_LUT_ATTEMPT_LIMIT = 2;

function hasApiErrorResponse(error: unknown): boolean {
  return Boolean(error && typeof error === "object" && "response" in error);
}

function shouldUseApiErrorLanguage(error: unknown): boolean {
  if (hasApiErrorResponse(error)) {
    return true;
  }
  const message = error instanceof Error ? error.message.trim() : "";
  return GENERIC_HTTP_STATUS_ERROR_RE.test(message);
}

function resolveRecipeImportError(
  error: unknown,
  t: (key: string) => string,
): string {
  if (shouldUseApiErrorLanguage(error)) {
    return apiErrorToVisibleMessage(error, t("recipe_import_error_unreadable"));
  }
  const message = error instanceof Error ? error.message.trim() : "";
  if (message === RECIPE_IMPORT_NOT_SHARE_CARD_ERROR) {
    return t("recipe_import_not_share_card");
  }
  if (message === RECIPE_INTEGRITY_ERROR) {
    return t("recipe_import_integrity_fail");
  }
  if (message === RECIPE_ASSET_CORRUPT_ERROR) {
    return t("recipe_import_asset_corrupt");
  }
  return t("recipe_import_error_unreadable");
}
const LEGACY_BUCKET_I18N_KEY: Partial<Record<ColorModeBucket, string>> = {
  [ColorMode.BW]: "basic_lut_color_mode_bw",
  [ColorMode.FOUR_COLOR_CMYW]: "basic_lut_color_mode_4color_cmyw",
  [ColorMode.FOUR_COLOR_RYBW]: "basic_lut_color_mode_4color_rybw",
  [ColorMode.FIVE_COLOR_EXT]: "basic_lut_color_mode_5color_ext",
  "5-Color Extended (1444)": "basic_lut_color_mode_5color_ext_1444",
  [ColorMode.SIX_COLOR]: "basic_lut_color_mode_6color_cmywgk",
  [ColorMode.SIX_COLOR_RYBW]: "basic_lut_color_mode_6color_rybwgk",
  [ColorMode.EIGHT_COLOR]: "basic_lut_color_mode_8color_max",
  [ColorMode.MERGED]: "basic_lut_color_mode_merged",
  "4-Color": "basic_lut_color_mode_4color",
  "6-Color": "basic_lut_color_mode_6color",
  "8-Color": "basic_lut_color_mode_8color",
};

function legacyBucketLabel(bucket: ColorModeBucket, t: (key: string) => string): string {
  const key = LEGACY_BUCKET_I18N_KEY[bucket];
  return key ? t(key) : bucket;
}

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
    lut_names,
    lutListFull,
    lutListLoading,
    legacyCatalogGroups,
    legacyCatalogLoading,
    selectedLegacyManufacturer,
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
    previewWarnings,
    generatedLargeFormatWarnings,
    selectedMaterialDirNames,
    materialLayerCount,
    materialDynamicLayerCountEnabled,
    materialMinLayerCount,
    materialMaxLayerCount,
    materialLayerHeightMm,
    materialBackingMaterialDirName,
    setColorLayers,
    setLayerHeightMm,
    setModelEnable,
    setModelOnly,
    setSourceVersion,
    setSelectedMaterialDirNames,
    setMaterialLayerCount,
    setMaterialDynamicLayerCountEnabled,
    setMaterialMinLayerCount,
    setMaterialMaxLayerCount,
    setMaterialLayerHeightMm,
    setMaterialBackingMaterialDirName,
    setNativeBrandKey,
    setNativeSupportedMode,
    setNativeDbNames,
    setLegacyManufacturer,
    setLegacyLutNames,
    fetchLutList,
    fetchLegacyCatalog,
  } = useConverterStore(useShallow((s) => ({
    imageFile: s.imageFile,
    imagePreviewUrl: s.imagePreviewUrl,
    source_version: s.source_version,
    lut_name: s.lut_name,
    lut_names: s.lut_names,
    lutListFull: s.lutListFull,
    lutListLoading: s.lutListLoading,
    legacyCatalogGroups: s.legacyCatalogGroups,
    legacyCatalogLoading: s.legacyCatalogLoading,
    selectedLegacyManufacturer: s.selectedLegacyManufacturer,
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
    previewWarnings: s.previewWarnings,
    generatedLargeFormatWarnings: s.largeFormatWarnings,
    selectedMaterialDirNames: s.selectedMaterialDirNames,
    materialLayerCount: s.materialLayerCount,
    materialDynamicLayerCountEnabled: s.materialDynamicLayerCountEnabled,
    materialMinLayerCount: s.materialMinLayerCount,
    materialMaxLayerCount: s.materialMaxLayerCount,
    materialLayerHeightMm: s.materialLayerHeightMm,
    materialBackingMaterialDirName: s.materialBackingMaterialDirName,
    setColorLayers: s.setColorLayers,
    setLayerHeightMm: s.setLayerHeightMm,
    setModelEnable: s.setModelEnable,
    setModelOnly: s.setModelOnly,
    setSourceVersion: s.setSourceVersion,
    setSelectedMaterialDirNames: s.setSelectedMaterialDirNames,
    setMaterialLayerCount: s.setMaterialLayerCount,
    setMaterialDynamicLayerCountEnabled: s.setMaterialDynamicLayerCountEnabled,
    setMaterialMinLayerCount: s.setMaterialMinLayerCount,
    setMaterialMaxLayerCount: s.setMaterialMaxLayerCount,
    setMaterialLayerHeightMm: s.setMaterialLayerHeightMm,
    setMaterialBackingMaterialDirName: s.setMaterialBackingMaterialDirName,
    setNativeBrandKey: s.setNativeBrandKey,
    setNativeSupportedMode: s.setNativeSupportedMode,
    setNativeDbNames: s.setNativeDbNames,
    setLegacyManufacturer: s.setLegacyManufacturer,
    setLegacyLutNames: s.setLegacyLutNames,
    fetchLutList: s.fetchLutList,
    fetchLegacyCatalog: s.fetchLegacyCatalog,
  })));

  const sourceSelection = useMemo(
    () =>
      resolveConverterSourceSelection({
        source_version,
        lut_name,
        lut_names,
        nativeBrandGroups,
        selectedNativeBrandKey,
        selectedNativeDbNames,
        color_layers,
        layer_height_mm,
        selectedMaterialDirNames,
        materialLayerCount,
        materialLayerHeightMm,
        lutListFull,
        legacyCatalogGroups,
      }),
    [
      source_version,
      lut_name,
      lut_names,
      nativeBrandGroups,
      selectedNativeBrandKey,
      selectedNativeDbNames,
      color_layers,
      layer_height_mm,
      selectedMaterialDirNames,
      materialLayerCount,
      materialLayerHeightMm,
      lutListFull,
      legacyCatalogGroups,
    ],
  );

  const [uploaderExpanded, setUploaderExpanded] = useState(true);
  const startupRetryMountedRef = useRef(false);
  const legacyCatalogRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const legacyCatalogStartupAttemptRef = useRef(0);
  const legacyCatalogLoadPendingRef = useRef(false);
  const lutListRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lutListStartupAttemptRef = useRef(0);
  const lutListLoadPendingRef = useRef(false);

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
      const visibleError = resolveRecipeImportError(err, t);
      useConverterStore.getState().setError(
        t("recipe_import_error").replace("{error}", visibleError),
      );
    } finally {
      setImportLoading(false);
    }
  }, [t]);

  const handleImportConfirm = useCallback(() => {
    if (!importPreview) return;
    applyImport(importPreview.restoreResult, importPreview.printerOptions ?? []);
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
  const setImageFile = useConverterStore((s) => s.setImageFile);
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
  const fetchLutCatalog = useConverterStore((s) => s.fetchLutCatalog);
  const removeBatchFile = useConverterStore((s) => s.removeBatchFile);
  const setLargeFormatEnabled = useConverterStore((s) => s.setLargeFormatEnabled);
  const setTileWidthMm = useConverterStore((s) => s.setTileWidthMm);
  const setTileHeightMm = useConverterStore((s) => s.setTileHeightMm);

  const handleFileReplace = useCallback(
    (file: File) => {
      if (!isValidImageType(file.type, file.name)) return;
      setImageFile(file);
    },
    [setImageFile],
  );

  const sourceVersionOptions = [
    { label: t("basic_source_version_legacy"), value: "legacy" },
    { label: t("basic_source_version_native"), value: "native" },
    { label: t("basic_source_version_material"), value: "material" },
  ];

  const clearLegacyCatalogRetry = useCallback(() => {
    if (legacyCatalogRetryTimerRef.current === null) return;
    clearTimeout(legacyCatalogRetryTimerRef.current);
    legacyCatalogRetryTimerRef.current = null;
  }, []);

  const clearLutListRetry = useCallback(() => {
    if (lutListRetryTimerRef.current === null) return;
    clearTimeout(lutListRetryTimerRef.current);
    lutListRetryTimerRef.current = null;
  }, []);

  useEffect(() => {
    startupRetryMountedRef.current = true;
    return () => {
      startupRetryMountedRef.current = false;
      clearLegacyCatalogRetry();
      clearLutListRetry();
    };
  }, [clearLegacyCatalogRetry, clearLutListRetry]);

  const startLegacyCatalogLoad = useCallback(() => {
    if (legacyCatalogLoadPendingRef.current) return;
    legacyCatalogLoadPendingRef.current = true;
    legacyCatalogStartupAttemptRef.current += 1;

    void fetchLegacyCatalog({ suppressClientLog: true })
      .catch(() => undefined)
      .then(() => {
        legacyCatalogLoadPendingRef.current = false;
        if (!startupRetryMountedRef.current) return;

        const state = useConverterStore.getState();
        if (state.source_version !== "legacy" || state.legacyCatalogGroups.length > 0) {
          legacyCatalogStartupAttemptRef.current = 0;
          return;
        }
        if (
          !state.legacyCatalogLoading &&
          legacyCatalogRetryTimerRef.current === null &&
          legacyCatalogStartupAttemptRef.current < STARTUP_LUT_ATTEMPT_LIMIT
        ) {
          legacyCatalogRetryTimerRef.current = setTimeout(() => {
            legacyCatalogRetryTimerRef.current = null;
            startLegacyCatalogLoad();
          }, STARTUP_LUT_RETRY_DELAY_MS);
        }
      });
  }, [fetchLegacyCatalog]);

  const startLutListLoad = useCallback(() => {
    if (lutListLoadPendingRef.current) return;
    lutListLoadPendingRef.current = true;
    lutListStartupAttemptRef.current += 1;

    void fetchLutList({ suppressClientLog: true })
      .catch(() => undefined)
      .then(() => {
        lutListLoadPendingRef.current = false;
        if (!startupRetryMountedRef.current) return;

        const state = useConverterStore.getState();
        if (state.source_version !== "legacy" || state.lutListFull.length > 0) {
          lutListStartupAttemptRef.current = 0;
          return;
        }
        if (
          !state.lutListLoading &&
          lutListRetryTimerRef.current === null &&
          lutListStartupAttemptRef.current < STARTUP_LUT_ATTEMPT_LIMIT
        ) {
          lutListRetryTimerRef.current = setTimeout(() => {
            lutListRetryTimerRef.current = null;
            startLutListLoad();
          }, STARTUP_LUT_RETRY_DELAY_MS);
        }
      });
  }, [fetchLutList]);

  useEffect(() => {
    if (source_version !== "legacy" || legacyCatalogGroups.length > 0) {
      clearLegacyCatalogRetry();
      legacyCatalogStartupAttemptRef.current = 0;
      return;
    }
    if (legacyCatalogStartupAttemptRef.current >= STARTUP_LUT_ATTEMPT_LIMIT) {
      return;
    }
    if (
      legacyCatalogLoading ||
      legacyCatalogRetryTimerRef.current !== null ||
      legacyCatalogLoadPendingRef.current
    ) {
      return;
    }

    startLegacyCatalogLoad();
  }, [
    source_version,
    legacyCatalogGroups.length,
    legacyCatalogLoading,
    clearLegacyCatalogRetry,
    startLegacyCatalogLoad,
  ]);

  useEffect(() => {
    if (source_version !== "legacy" || lutListFull.length > 0) {
      clearLutListRetry();
      lutListStartupAttemptRef.current = 0;
      return;
    }
    if (lutListStartupAttemptRef.current >= STARTUP_LUT_ATTEMPT_LIMIT) {
      return;
    }
    if (
      lutListLoading ||
      lutListRetryTimerRef.current !== null ||
      lutListLoadPendingRef.current
    ) {
      return;
    }

    startLutListLoad();
  }, [
    source_version,
    lutListFull.length,
    lutListLoading,
    clearLutListRetry,
    startLutListLoad,
  ]);

  const lutIndex = useMemo(
    () => buildLutCatalogIndex(legacyCatalogGroups),
    [legacyCatalogGroups],
  );
  const manufacturerOptions = useMemo(
    () =>
      Object.keys(lutIndex.byManufacturer)
        .sort((a, b) => a.localeCompare(b))
        .map((name) => ({
          label: name === "Unlabeled" ? t("basic_lut_unlabeled_brand") : name,
          value: name,
        })),
    [lutIndex, t],
  );
  const lutNameByPath = useMemo(() => {
    const map = new Map<string, string>();
    for (const entry of lutListFull) {
      map.set(normalizeLutPath(entry.path), entry.name);
    }
    return map;
  }, [lutListFull]);
  const groupedLutOptions = useMemo(() => {
    if (!selectedLegacyManufacturer) {
      return [];
    }
    const buckets = listBucketsForManufacturer(lutIndex, selectedLegacyManufacturer);
    const bucketModes = new Map(
      buckets.map((bucket) => [
        bucket,
        getBucketDisplayColorMode(lutIndex, selectedLegacyManufacturer, bucket),
      ]),
    );
    const visibleGroups = buckets
      .map((bucket) => {
        const displayMode = bucketModes.get(bucket) ?? bucket;
        const baseLabel = legacyBucketLabel(displayMode, t);
        return {
          displayMode,
          baseLabel,
          options:
            lutIndex.byManufacturerAndBucket[selectedLegacyManufacturer]?.[
              bucket
            ]?.map((item) => {
              const legacyName = lutNameByPath.get(normalizeLutPath(item.path));
              if (!legacyName) {
                return null;
              }
              return {
                label: item.name,
                value: legacyName,
              };
            }).filter((option) => option !== null) ?? [],
        };
      })
      .filter((group) => group.options.length > 0);
    const modeCounts = new Map<string, number>();
    for (const group of visibleGroups) {
      modeCounts.set(group.displayMode, (modeCounts.get(group.displayMode) ?? 0) + 1);
    }
    const modePositions = new Map<string, number>();
    return visibleGroups.map((group) => {
      const position = (modePositions.get(group.displayMode) ?? 0) + 1;
      modePositions.set(group.displayMode, position);
      return {
        label:
          (modeCounts.get(group.displayMode) ?? 0) > 1
            ? `${group.baseLabel} #${position}`
            : group.baseLabel,
        options: group.options,
      };
    });
  }, [lutIndex, selectedLegacyManufacturer, t, lutNameByPath]);
  const selectedLegacyBrandInfo = useMemo(() => {
    if (!selectedLegacyManufacturer) {
      return null;
    }
    const group = legacyCatalogGroups.find(
      (candidate) => candidate.manufacturer === selectedLegacyManufacturer,
    );
    const materialTypes = Array.from(
      new Set(
        (group?.items ?? [])
          .map((item) => item.material_type.trim())
          .filter(Boolean),
      ),
    ).sort((a, b) => a.localeCompare(b));
    return {
      displayName:
        selectedLegacyManufacturer === "Unlabeled"
          ? t("basic_lut_unlabeled_brand")
          : selectedLegacyManufacturer,
      materialTypes,
      vendor:
        selectedLegacyManufacturer === "Unlabeled"
          ? t("basic_lut_unlabeled_brand")
          : selectedLegacyManufacturer,
    };
  }, [legacyCatalogGroups, selectedLegacyManufacturer, t]);

  // --- Material library for material-archive mode ---
  const [materialLibrary, setMaterialLibrary] = useState<SavedMaterialLibraryItem[]>([]);
  const [materialLibraryLoading, setMaterialLibraryLoading] = useState(false);
  useEffect(() => {
    if (source_version !== "material") return;
    let cancelled = false;
    setMaterialLibraryLoading(true);
    listGradientCardMaterials()
      .then((res) => {
        if (cancelled) return;
        const materials = res.materials ?? [];
        setMaterialLibrary(materials);
        // One-shot migration: legacy selections (flat directory_names stored
        // in localStorage before the brand-subdirectory feature) are remapped
        // to the current nested directory_name so cache/status/build calls
        // don't 404. Unresolvable entries are dropped.
        // 一次性迁移：把 localStorage 里的旧扁平 directory_name 映射到新的
        // 嵌套名，避免求解器缓存接口 404。
        const { names: reconciled, changed } = reconcileDirectoryNames(
          selectedMaterialDirNames,
          materials,
        );
        if (changed) {
          setSelectedMaterialDirNames(reconciled);
        }
        if (materialBackingMaterialDirName) {
          const backing = reconcileDirectoryNames(
            [materialBackingMaterialDirName],
            materials,
          );
          if (backing.changed) {
            setMaterialBackingMaterialDirName(backing.names[0] ?? null);
          }
        }
      })
      .catch(() => {
        if (!cancelled) setMaterialLibrary([]);
      })
      .finally(() => {
        if (!cancelled) setMaterialLibraryLoading(false);
      });
    return () => { cancelled = true; };
    // selectedMaterialDirNames intentionally omitted: the migration must run
    // after the fresh library arrives, not on every selection change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source_version]);

  const [materialPickerOpen, setMaterialPickerOpen] = useState(false);
  const handleMaterialPickerConfirm = useCallback(
    (next: string[]) => {
      setSelectedMaterialDirNames(next);
      setMaterialPickerOpen(false);
    },
    [setSelectedMaterialDirNames],
  );

  // Compact summary for the trigger button: shows the first few material names
  // plus a "+N more" suffix when truncated.
  const MATERIAL_SUMMARY_LIMIT = 2;
  const materialSummary = useMemo(() => {
    if (selectedMaterialDirNames.length === 0) {
      return null;
    }
    const lookup = new Map(materialLibrary.map((mat) => [mat.directory_name, mat.material_name]));
    const visible = selectedMaterialDirNames
      .slice(0, MATERIAL_SUMMARY_LIMIT)
      .map((dirName) => lookup.get(dirName) ?? dirName);
    const remaining = selectedMaterialDirNames.length - visible.length;
    const more = remaining > 0
      ? tRuntime("basic_material_picker_summary_more", { count: remaining })
      : null;
    return { visible, more };
  }, [selectedMaterialDirNames, materialLibrary]);
  const materialNameLookup = useMemo(
    () => new Map(materialLibrary.map((mat) => [mat.directory_name, mat.material_name])),
    [materialLibrary],
  );
  const materialBackingOptions = useMemo(
    () =>
      selectedMaterialDirNames.map((dirName, index) => ({
        label: `${index + 1}. ${materialNameLookup.get(dirName) ?? dirName}`,
        value: dirName,
      })),
    [selectedMaterialDirNames, materialNameLookup],
  );
  const resolvedMaterialBackingDirName =
    materialBackingMaterialDirName &&
    selectedMaterialDirNames.includes(materialBackingMaterialDirName)
      ? materialBackingMaterialDirName
      : (inferDefaultMaterialBackingDirName(selectedMaterialDirNames) ?? "");

  const materialLayerHeightOptions = [
    { label: "0.04 mm", value: "0.04" },
    { label: "0.08 mm", value: "0.08" },
    { label: "0.10 mm", value: "0.1" },
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

  const [isRefreshingLut, setIsRefreshingLut] = useState(false);
  const handleRefreshLut = useCallback(async () => {
    if (isRefreshingLut) return;
    setIsRefreshingLut(true);
    try {
      await Promise.all([fetchLutCatalog(), fetchLegacyCatalog()]);
    } finally {
      setIsRefreshingLut(false);
    }
  }, [fetchLegacyCatalog, fetchLutCatalog, isRefreshingLut]);

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

  const mergedLargeFormatWarnings = useMemo(
    () => Array.from(new Set([...(previewWarnings ?? []), ...(generatedLargeFormatWarnings ?? [])])),
    [previewWarnings, generatedLargeFormatWarnings],
  );

  return (
    <div className="flex flex-col gap-4">
      {uploaderExpanded ? (
        <UnifiedUploader
          singlePreview={imagePreviewUrl ?? undefined}
          batchFiles={batchFiles}
          isBatchMode={batchMode}
          onFilesSelect={handleFilesSelect}
          onFileReplace={handleFileReplace}
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
        onChange={(value) => setSourceVersion(value as "legacy" | "native" | "material")}
      />

      {source_version === "material" ? (
        <div className="-mt-1 flex flex-col gap-3 rounded-lg border border-slate-200/60 bg-slate-100/50 p-3 dark:border-slate-700/40 dark:bg-slate-900/40">
          <div className="text-xs font-medium uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">
            {t("basic_material_select_label")}
          </div>

          <button
            type="button"
            onClick={() => setMaterialPickerOpen(true)}
            data-testid="material-picker-trigger"
            className={`${workstationInputClass} flex items-center justify-between gap-3 text-left`}
          >
            <span className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
              {materialSummary === null ? (
                <span className="text-slate-400 dark:text-slate-500">
                  {t("basic_material_picker_open")}
                </span>
              ) : (
                <>
                  {materialSummary.visible.map((name) => (
                    <span
                      key={name}
                      className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200"
                    >
                      {name}
                    </span>
                  ))}
                  {materialSummary.more && (
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                      {materialSummary.more}
                    </span>
                  )}
                </>
              )}
            </span>
            <span className="shrink-0 text-xs text-slate-400 dark:text-slate-500">
              {t("basic_material_selected_count")}: {selectedMaterialDirNames.length}
            </span>
          </button>

          <MaterialPickerDialog
            open={materialPickerOpen}
            materials={materialLibrary}
            loading={materialLibraryLoading}
            initialSelected={selectedMaterialDirNames}
            onConfirm={handleMaterialPickerConfirm}
            onCancel={() => setMaterialPickerOpen(false)}
          />

          <Checkbox
            label={t("basic_material_dynamic_layer_count_label")}
            tooltip={t("basic_material_dynamic_layer_count_hint")}
            checked={materialDynamicLayerCountEnabled}
            onChange={setMaterialDynamicLayerCountEnabled}
          />

          {materialDynamicLayerCountEnabled ? (
            <>
              <Slider
                label={t("basic_material_min_layer_count_label")}
                tooltip={t("basic_material_min_layer_count_hint")}
                value={materialMinLayerCount}
                min={MATERIAL_DYNAMIC_LAYER_COUNT_MIN}
                max={MATERIAL_DYNAMIC_LAYER_COUNT_MAX}
                step={1}
                onChange={(v) => setMaterialMinLayerCount(Math.round(v))}
              />
              <Slider
                label={t("basic_material_max_layer_count_label")}
                tooltip={t("basic_material_max_layer_count_hint")}
                value={materialMaxLayerCount}
                min={MATERIAL_DYNAMIC_LAYER_COUNT_MIN}
                max={MATERIAL_DYNAMIC_LAYER_COUNT_MAX}
                step={1}
                onChange={(v) => setMaterialMaxLayerCount(Math.round(v))}
              />
              <StatusBanner tone="info">
                {t("basic_material_dynamic_range_hint")}
              </StatusBanner>
            </>
          ) : (
            <Slider
              label={t("basic_material_layer_count_label")}
              tooltip={t("basic_material_layer_count_hint")}
              value={materialLayerCount}
              min={5}
              max={10}
              step={1}
              onChange={(v) => setMaterialLayerCount(Math.round(v))}
            />
          )}

          <Dropdown
            label={t("basic_material_layer_height_label")}
            value={String(materialLayerHeightMm)}
            options={materialLayerHeightOptions}
            onChange={(v) => setMaterialLayerHeightMm(Number(v))}
          />

          <Dropdown
            label={t("basic_material_backing_label")}
            value={resolvedMaterialBackingDirName}
            options={materialBackingOptions}
            onChange={(v) => setMaterialBackingMaterialDirName(v || null)}
            disabled={selectedMaterialDirNames.length === 0}
            placeholder={t("basic_material_backing_placeholder")}
          />

          {!materialDynamicLayerCountEnabled && (
            <MaterialSolverCacheDialog
              materialDirectoryNames={selectedMaterialDirNames}
              layerCount={materialLayerCount}
              layerHeightMm={materialLayerHeightMm}
            />
          )}
        </div>
      ) : source_version === "legacy" ? (
        <>
          <LegacyLutSelector
            manufacturer={selectedLegacyManufacturer}
            lutName={lut_name}
            selectedLutNames={lut_names.length > 0 ? lut_names : (lut_name ? [lut_name] : [])}
            manufacturerOptions={manufacturerOptions}
            groupedLutOptions={groupedLutOptions}
            brandInfo={selectedLegacyBrandInfo}
            onManufacturerChange={setLegacyManufacturer}
            onLutChange={setLutName}
            onLutSelectionChange={setLegacyLutNames}
            onRefresh={() => void handleRefreshLut()}
            onUploadClick={() => lutFileRef.current?.click()}
            loading={legacyCatalogLoading}
            lutLoading={lutListLoading}
            refreshing={isRefreshingLut}
            compact={workspace.isCompact}
            labels={{
              manufacturer: t("basic_lut_manufacturer_label"),
              manufacturerPlaceholder: t("basic_lut_manufacturer_placeholder"),
              lut: t("basic_lut_label"),
              lutPlaceholder: t("basic_lut_lut_placeholder"),
              refreshTooltip: t("basic_lut_refresh_tooltip"),
              upload: `+ ${t("basic_lut_upload")}`,
              loadingHint: t("basic_brand_loading"),
              noBrandHint: t("basic_lut_no_brand_hint"),
              multiSelect: t("basic_lut_multi_select"),
              selectedCount: t("basic_lut_selected_count"),
              brandInfo: t("basic_native_brand_summary_label"),
              materialType: t("basic_native_material_label"),
              vendor: t("basic_native_vendor_label"),
              database: t("basic_native_db_label"),
              databasePlaceholder: t("basic_native_db_placeholder"),
            }}
          />
          <input
            ref={lutFileRef}
            type="file"
            accept=".npy,.json,.npz,.msgpack"
            className="hidden"
            onChange={(e) => void handleLutUpload(e)}
          />

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
                    tooltip={t("basic_color_layers_hint")}
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
      ) : source_version === "native" ? (
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
      ) : null}

      <Slider
        label={t("basic_width")}
        tooltip={t("basic_width_hint")}
        value={target_width_mm}
        min={10}
        max={dimMax}
        step={1}
        unit="mm"
        onChange={setTargetWidthMm}
      />

      <Slider
        label={t("basic_height")}
        tooltip={t("basic_height_hint")}
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

      {mergedLargeFormatWarnings.length > 0 ? (
        <StatusBanner tone="warning">
          <div className="flex flex-col gap-1">
            {mergedLargeFormatWarnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
          </div>
        </StatusBanner>
      ) : null}

      {largeFormatEnabled && (
        <div className="flex flex-col gap-3 rounded-lg border border-slate-200/60 bg-slate-100/50 p-3 dark:border-slate-700/40 dark:bg-slate-900/40">
          <Slider
            label={t("basic_tile_width")}
            tooltip={t("basic_tile_width_hint")}
            value={tileWidthMm}
            min={50}
            max={500}
            step={10}
            unit="mm"
            onChange={setTileWidthMm}
          />
          <Slider
            label={t("basic_tile_height")}
            tooltip={t("basic_tile_height_hint")}
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
        tooltip={t("basic_thickness_hint")}
        value={spacer_thick}
        min={THICKNESS_SLIDER_MIN_MM}
        max={THICKNESS_SLIDER_MAX_MM}
        step={THICKNESS_LAYER_STEP_MM}
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

      <QuantizeColorsControl />

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

function QuantizeColorsControl() {
  const { t } = useI18n();
  const quantize_colors = useConverterStore((s) => s.quantize_colors);
  const quantize_colors_unlocked = useConverterStore((s) => s.quantize_colors_unlocked);
  const imageFile = useConverterStore((s) => s.imageFile);
  const autoDetectLoading = useConverterStore((s) => s.autoDetectColorsLoading);
  const setQuantizeColors = useConverterStore((s) => s.setQuantizeColors);
  const autoDetectColors = useConverterStore((s) => s.autoDetectColors);
  const upperBound = quantize_colors_unlocked ? 8192 : 256;
  // Step must divide (upperBound - min=8) so the slider can reach the
  // declared ceiling. (8192 - 8) is divisible by 8 but not by 32, hence
  // step=8 even in unlocked mode to keep 8192 reachable; otherwise the
  // slider would max out at 8168.
  // 步长必须能整除 (upperBound - min=8)，否则滑条到不了声明的上限。
  // (8192 - 8) 能被 8 整除但不能被 32 整除，所以解锁后仍用 step=8，
  // 不然滑条只能停在 8168。
  const step = 8;

  return (
    <div className="flex flex-col gap-1">
      <Slider
        label={t("adv_quantize_colors")}
        tooltip={t("adv_quantize_colors_hint")}
        value={quantize_colors}
        min={8}
        max={upperBound}
        step={step}
        onChange={setQuantizeColors}
      />
      <button
        type="button"
        disabled={!imageFile || autoDetectLoading}
        onClick={autoDetectColors}
        className="self-end px-3 py-1 text-xs rounded-md bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        {autoDetectLoading ? t("conv_auto_color_calculating") : t("conv_auto_color_btn")}
      </button>
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
