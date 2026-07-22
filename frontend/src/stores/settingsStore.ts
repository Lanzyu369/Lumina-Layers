import { create } from "zustand";
import { persist } from "zustand/middleware";
import { saveSettings } from "../api/system";
import type { UserSettings } from "../api/types";
import {
  invalidateGeneratedArtifacts,
  invalidatePreviewArtifacts,
} from "./generatedArtifactInvalidation";
import { invalidatePreviewRequest } from "./previewRequestCoordinator";

// ========== State Interface ==========

/**
 * User-facing grid-resolution tiers for the material-solver exhaustive
 * cache. The numeric value equals the Lab bucket count per axis and must
 * stay in sync with ``ALLOWED_GRID_RESOLUTIONS`` on the backend.
 *
 * The ladder doubles per step. The build path is sparse, so peak build
 * memory tracks the number of physically reachable recipes (~materials^
 * layers) rather than the cube of the tier — even Ultra+ stays light.
 * Higher tiers mainly reduce bucket-collision loss (more distinct
 * recipes survive into the cache); per-lookup cost scales mildly.
 *
 * 穷举数量的用户档位；数值等于 Lab 网格每轴桶数，必须与后端
 * ``ALLOWED_GRID_RESOLUTIONS`` 保持一致。每档边长翻倍，但构建采用稀疏
 * 存储，峰值内存只随实际可达配方数（~材料^层数）增长，与档位无关——
 * 极致+ 档也很轻。更高档主要减少桶碰撞损失（更多配方被保留进缓存）；
 * 单次查找时间随档位略增。
 */
export type SolverCacheGridResolution =
  | 64
  | 128
  | 256
  | 512
  | 1024
  | 2048;

export const SOLVER_CACHE_GRID_RESOLUTIONS: readonly SolverCacheGridResolution[] =
  [64, 128, 256, 512, 1024, 2048] as const;

const SOLVER_CACHE_EXACT_MODE_MAX_MATERIALS = 10;
const SOLVER_CACHE_EXACT_MODE_MAX_LAYERS = 5;
const SOLVER_CACHE_EXACT_MODE_MAX_COMBINATIONS = 100_000;
const SOLVER_CACHE_ESTIMATED_VALID_CELL_RATIO = 0.12;
const SOLVER_CACHE_ESTIMATED_BYTES_PER_VALID_CELL = 768;
const SOLVER_CACHE_ESTIMATED_BUILD_BASE_BYTES = 512 * 1024 * 1024;
export const SOLVER_CACHE_BUILD_MEMORY_LIMIT_BYTES = 8 * 1024 * 1024 * 1024;
export const SOLVER_CACHE_BUILD_MAX_COMBINATIONS = 12_000_000_000;

export interface SolverCacheBuildBudgetEstimate {
  totalCombinations: number;
  totalBucketCount: number;
  estimatedValidCellCount: number;
  estimatedPeakBytes: number;
  memoryLimitBytes: number;
  maxTotalCombinations: number;
  isAllowed: boolean;
}

export function estimateSolverCacheBuildBudget(
  materialCount: number,
  layerCount: number,
  gridResolution: SolverCacheGridResolution,
): SolverCacheBuildBudgetEstimate {
  const safeMaterialCount = Math.max(0, Math.trunc(materialCount));
  const safeLayerCount = Math.max(0, Math.trunc(layerCount));
  const safeGridResolution = Math.max(1, Math.trunc(gridResolution));
  const totalCombinations =
    safeMaterialCount > 0 && safeLayerCount > 0
      ? Math.pow(safeMaterialCount, safeLayerCount)
      : 0;
  const totalBucketCount = Math.pow(safeGridResolution, 3);
  const exactEligible =
    safeMaterialCount <= SOLVER_CACHE_EXACT_MODE_MAX_MATERIALS &&
    safeLayerCount <= SOLVER_CACHE_EXACT_MODE_MAX_LAYERS &&
    totalCombinations <= SOLVER_CACHE_EXACT_MODE_MAX_COMBINATIONS;
  const estimatedValidCellCount = exactEligible
    ? totalCombinations
    : Math.min(
        totalCombinations,
        totalBucketCount,
        Math.ceil(totalCombinations * SOLVER_CACHE_ESTIMATED_VALID_CELL_RATIO),
      );
  const estimatedPeakBytes =
    SOLVER_CACHE_ESTIMATED_BUILD_BASE_BYTES +
    estimatedValidCellCount * SOLVER_CACHE_ESTIMATED_BYTES_PER_VALID_CELL;
  return {
    totalCombinations,
    totalBucketCount,
    estimatedValidCellCount,
    estimatedPeakBytes,
    memoryLimitBytes: SOLVER_CACHE_BUILD_MEMORY_LIMIT_BYTES,
    maxTotalCombinations: SOLVER_CACHE_BUILD_MAX_COMBINATIONS,
    isAllowed:
      estimatedPeakBytes <= SOLVER_CACHE_BUILD_MEMORY_LIMIT_BYTES &&
      totalCombinations <= SOLVER_CACHE_BUILD_MAX_COMBINATIONS,
  };
}

export const SVG_PIXELS_PER_MM_DEFAULT = 10.0;
export const SVG_PIXELS_PER_MM_MIN = 2.0;
export const SVG_PIXELS_PER_MM_MAX = 50.0;
export const SVG_PIXELS_PER_MM_STEP = 0.1;
export const MATERIAL_DELTA_E00_TOLERANCE_DEFAULT = 0.5;
export const MATERIAL_DELTA_E00_TOLERANCE_MIN = 0.0;
export const MATERIAL_DELTA_E00_TOLERANCE_MAX = 5.0;
export const MATERIAL_DELTA_E00_TOLERANCE_STEP = 0.1;

export interface SettingsState {
  language: "zh" | "en";
  theme: "light" | "dark";
  lastLutName: string;
  lastColorMode: string;
  lastModelingMode: string;
  lastBedLabel: string;
  cropEnabled: boolean;
  lastSlicerId: string;
  enableBlur: boolean;
  enableFancyLoading: boolean;
  enableWittyLoading: boolean;
  paletteMode: "swatch" | "card";
  printerModel: string;
  slicerSoftware: string;
  deviceProfileId: string;
  customSlicerPath: string;
  customSlicerId: string;
  nozzleSize: "0.2" | "0.25" | "0.4";
  enableBaseLayerHeightModifier: boolean;
  /**
   * When ``false`` (default) the exhaustive-cache dialog hides its
   * density selector and builds always use the low-tier default on the
   * backend. Flipping to ``true`` reveals the dropdown, but does *not*
   * change the current value of ``solverCacheGridResolution``.
   */
  enableSolverCacheGridSelection: boolean;
  /**
   * Currently-selected grid resolution. Only consumed by the build flow
   * when ``enableSolverCacheGridSelection`` is true; otherwise callers
   * must fall through to the backend default (64).
   */
  solverCacheGridResolution: SolverCacheGridResolution;
  /**
   * High-fidelity SVG raster density in pixels per millimeter. This only
   * affects SVG files processed through High-Fidelity mode; native Vector
   * mode bypasses rasterization and ignores this value.
   */
  svgPixelsPerMm: number;
  /**
   * Maximum accepted Delta-E00 loss when choosing a shorter dynamic material
   * recipe. 动态材料配方选择更短层数时允许的最大 Delta-E00 损失。
   */
  materialDeltaE00Tolerance: number;
  /**
   * Advanced: when true, successful previews automatically collapse every
   * gradient-banding group to its representative colour (the material with
   * the highest pixel count). Off by default so first-time users see the
   * raw banded preview and opt into the fix from the color workstation.
   * 高级设置：开启后，每次预览成功会自动把每个渐变海带纹分组统一替换为组
   * 内代表色（像素最多的那一个），一键去掉海带纹；默认关闭。
   */
  autoReplaceGradientBanding: boolean;
}

// ========== Actions Interface ==========

export interface SettingsActions {
  setLanguage: (lang: "zh" | "en") => void;
  setTheme: (theme: "light" | "dark") => void;
  setLastLutName: (name: string) => void;
  setLastColorMode: (mode: string) => void;
  setLastModelingMode: (mode: string) => void;
  setLastBedLabel: (label: string) => void;
  setCropEnabled: (enabled: boolean) => void;
  setLastSlicerId: (id: string) => void;
  setEnableBlur: (enabled: boolean) => void;
  setEnableFancyLoading: (enabled: boolean) => void;
  setEnableWittyLoading: (enabled: boolean) => void;
  setPaletteMode: (mode: "swatch" | "card") => void;
  setPrinterModel: (id: string) => void;
  setSlicerSoftware: (id: string) => void;
  setDeviceProfileId: (id: string) => void;
  setCustomSlicerPath: (path: string) => void;
  setCustomSlicerId: (id: string) => void;
  setNozzleSize: (size: "0.2" | "0.25" | "0.4") => void;
  setEnableBaseLayerHeightModifier: (enabled: boolean) => void;
  setEnableSolverCacheGridSelection: (enabled: boolean) => void;
  setSolverCacheGridResolution: (value: SolverCacheGridResolution) => void;
  setSvgPixelsPerMm: (value: number) => void;
  resetSvgPixelsPerMm: () => void;
  setMaterialDeltaE00Tolerance: (value: number) => void;
  setAutoReplaceGradientBanding: (enabled: boolean) => void;
  hydrateDeviceSettingsFromBackend: (settings: Partial<UserSettings>) => void;
  syncToBackend: () => Promise<void>;
}

// ========== Default State ==========

export const DEFAULT_SETTINGS: SettingsState = {
  language: "zh",
  theme: "light",
  lastLutName: "",
  lastColorMode: "4-Color (RYBW)",
  lastModelingMode: "high-fidelity",
  lastBedLabel: "256×256 mm",
  cropEnabled: true,
  lastSlicerId: "",
  enableBlur: true,
  enableFancyLoading: true,
  enableWittyLoading: true,
  paletteMode: "swatch",
  printerModel: "bambu-h2d",
  slicerSoftware: "BambuStudio",
  deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.4",
  customSlicerPath: "",
  customSlicerId: "",
  nozzleSize: "0.4",
  enableBaseLayerHeightModifier: true,
  // Opt-in feature: the density dropdown is hidden by default so the
  // exhaustive-cache dialog stays focused for first-time users. When the
  // toggle is off, builds silently use the low (64) default on the backend.
  enableSolverCacheGridSelection: false,
  solverCacheGridResolution: 64,
  svgPixelsPerMm: SVG_PIXELS_PER_MM_DEFAULT,
  materialDeltaE00Tolerance: MATERIAL_DELTA_E00_TOLERANCE_DEFAULT,
  autoReplaceGradientBanding: false,
};

type PersistedSettingsSnapshot = Partial<SettingsState>;

const RETIRED_CLIENT_ONLY_SETTING_KEYS = [
  "mlsBaseUrl",
  "mlsBackendUrl",
] as const;

function stripRetiredClientOnlySettings(
  snapshot: Record<string, unknown>,
): PersistedSettingsSnapshot {
  const migrated: Record<string, unknown> = { ...snapshot };
  for (const key of RETIRED_CLIENT_ONLY_SETTING_KEYS) {
    delete migrated[key];
  }
  return migrated as PersistedSettingsSnapshot;
}

function patchLegacyPersistedDeviceProfile(
  snapshot: PersistedSettingsSnapshot,
): PersistedSettingsSnapshot {
  if (Object.prototype.hasOwnProperty.call(snapshot, "deviceProfileId")) {
    return snapshot;
  }
  if (
    Object.prototype.hasOwnProperty.call(snapshot, "printerModel") ||
    Object.prototype.hasOwnProperty.call(snapshot, "slicerSoftware") ||
    Object.prototype.hasOwnProperty.call(snapshot, "nozzleSize")
  ) {
    return { ...snapshot, deviceProfileId: "" };
  }
  return snapshot;
}

function migratePersistedSettings(
  persistedState: unknown,
): PersistedSettingsSnapshot {
  if (!persistedState || typeof persistedState !== "object") {
    return {};
  }
  return patchLegacyPersistedDeviceProfile(
    stripRetiredClientOnlySettings(persistedState as Record<string, unknown>),
  );
}

function readPersistedSettingsSnapshot(): PersistedSettingsSnapshot | null {
  try {
    const raw = localStorage.getItem("lumina-settings");
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as { state?: Record<string, unknown> };
    if (
      !parsed ||
      typeof parsed !== "object" ||
      !parsed.state ||
      typeof parsed.state !== "object"
    ) {
      return null;
    }
    return stripRetiredClientOnlySettings(parsed.state);
  } catch {
    return null;
  }
}

const INITIAL_PERSISTED_SETTINGS_SNAPSHOT = readPersistedSettingsSnapshot();

function hasOwnSetting(
  snapshot: PersistedSettingsSnapshot | null,
  key: keyof SettingsState,
): boolean {
  return !!snapshot && Object.prototype.hasOwnProperty.call(snapshot, key);
}

function normalizeSvgPixelsPerMm(value: number): number {
  if (!Number.isFinite(value)) {
    return SVG_PIXELS_PER_MM_DEFAULT;
  }
  const clamped = Math.min(
    SVG_PIXELS_PER_MM_MAX,
    Math.max(SVG_PIXELS_PER_MM_MIN, value),
  );
  return Number(clamped.toFixed(1));
}

function normalizeMaterialDeltaE00Tolerance(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return MATERIAL_DELTA_E00_TOLERANCE_DEFAULT;
  }
  const clamped = Math.min(
    MATERIAL_DELTA_E00_TOLERANCE_MAX,
    Math.max(MATERIAL_DELTA_E00_TOLERANCE_MIN, value),
  );
  return Number(clamped.toFixed(1));
}

export function deriveBackendDeviceSettingsPatch(
  current: SettingsState,
  settings: Partial<UserSettings>,
  persistedSnapshot: PersistedSettingsSnapshot | null,
): Partial<SettingsState> {
  const patch: Partial<SettingsState> = {};

  if (
    typeof settings.printer_model === "string" &&
    settings.printer_model.trim() &&
    current.printerModel === DEFAULT_SETTINGS.printerModel &&
    !hasOwnSetting(persistedSnapshot, "printerModel")
  ) {
    patch.printerModel = settings.printer_model.trim();
  }

  if (
    typeof settings.slicer_software === "string" &&
    settings.slicer_software.trim() &&
    current.slicerSoftware === DEFAULT_SETTINGS.slicerSoftware &&
    !hasOwnSetting(persistedSnapshot, "slicerSoftware")
  ) {
    patch.slicerSoftware = settings.slicer_software.trim();
  }

  if (
    typeof settings.device_profile_id === "string" &&
    settings.device_profile_id.trim() &&
    current.deviceProfileId === DEFAULT_SETTINGS.deviceProfileId &&
    !hasOwnSetting(persistedSnapshot, "deviceProfileId")
  ) {
    patch.deviceProfileId = settings.device_profile_id.trim();
  }

  if (
    typeof settings.custom_slicer_path === "string" &&
    settings.custom_slicer_path.trim() &&
    current.customSlicerPath === DEFAULT_SETTINGS.customSlicerPath &&
    !hasOwnSetting(persistedSnapshot, "customSlicerPath")
  ) {
    patch.customSlicerPath = settings.custom_slicer_path.trim();
  }

  if (
    typeof settings.custom_slicer_id === "string" &&
    settings.custom_slicer_id.trim() &&
    current.customSlicerId === DEFAULT_SETTINGS.customSlicerId &&
    !hasOwnSetting(persistedSnapshot, "customSlicerId")
  ) {
    patch.customSlicerId = settings.custom_slicer_id.trim();
  }

  if (
    (settings.nozzle_size === "0.2" ||
      settings.nozzle_size === "0.25" ||
      settings.nozzle_size === "0.4") &&
    current.nozzleSize === DEFAULT_SETTINGS.nozzleSize &&
    !hasOwnSetting(persistedSnapshot, "nozzleSize")
  ) {
    patch.nozzleSize = settings.nozzle_size;
  }

  if (
    typeof settings.enable_base_layer_height_modifier === "boolean" &&
    current.enableBaseLayerHeightModifier ===
      DEFAULT_SETTINGS.enableBaseLayerHeightModifier &&
    !hasOwnSetting(persistedSnapshot, "enableBaseLayerHeightModifier")
  ) {
    patch.enableBaseLayerHeightModifier =
      settings.enable_base_layer_height_modifier;
  }

  return patch;
}

// ========== Store ==========

export const useSettingsStore = create<SettingsState & SettingsActions>()(
  persist(
    (set, get) => ({
      ...DEFAULT_SETTINGS,

      setLanguage: (lang: "zh" | "en") => set({ language: lang }),

      setTheme: (theme: "light" | "dark") => set({ theme }),

      setLastLutName: (name: string) => set({ lastLutName: name }),

      setLastColorMode: (mode: string) => set({ lastColorMode: mode }),

      setLastModelingMode: (mode: string) => set({ lastModelingMode: mode }),

      setLastBedLabel: (label: string) => set({ lastBedLabel: label }),

      setCropEnabled: (enabled: boolean) => set({ cropEnabled: enabled }),

      setLastSlicerId: (id: string) => set({ lastSlicerId: id }),

      setEnableBlur: (enabled: boolean) => set({ enableBlur: enabled }),

      setEnableFancyLoading: (enabled: boolean) =>
        set({ enableFancyLoading: enabled }),

      setEnableWittyLoading: (enabled: boolean) =>
        set({ enableWittyLoading: enabled }),

      setPaletteMode: (mode: "swatch" | "card") => set({ paletteMode: mode }),

      setPrinterModel: (id: string) => {
        set((state) => ({
          printerModel: id,
          deviceProfileId:
            state.printerModel === id ? state.deviceProfileId : "",
        }));
        invalidateGeneratedArtifacts();

        // 延迟导入避免循环依赖
        import("./converter").then(({ useConverterStore }) => {
          const { bedSizes, setBedLabel } = useConverterStore.getState();
          const printerBed = bedSizes.find((bed) => bed.printer_id === id);
          if (printerBed) {
            setBedLabel(printerBed.label);
          }
        });
      },

      setSlicerSoftware: (id: string) => {
        set((state) => ({
          slicerSoftware: id,
          deviceProfileId:
            state.slicerSoftware === id ? state.deviceProfileId : "",
        }));
        invalidateGeneratedArtifacts();
      },

      setDeviceProfileId: (id: string) => {
        set({ deviceProfileId: id });
        invalidateGeneratedArtifacts();
      },

      setCustomSlicerPath: (path: string) => set({ customSlicerPath: path }),

      setCustomSlicerId: (id: string) => set({ customSlicerId: id }),

      setNozzleSize: (size: "0.2" | "0.25" | "0.4") => {
        set((state) => ({
          nozzleSize: size,
          deviceProfileId:
            state.nozzleSize === size ? state.deviceProfileId : "",
        }));
        invalidateGeneratedArtifacts();
      },

      setEnableBaseLayerHeightModifier: (enabled: boolean) => {
        set({ enableBaseLayerHeightModifier: enabled });
        invalidateGeneratedArtifacts();
      },

      setEnableSolverCacheGridSelection: (enabled: boolean) =>
        set({ enableSolverCacheGridSelection: enabled }),

      setSolverCacheGridResolution: (value: SolverCacheGridResolution) => {
        if (!SOLVER_CACHE_GRID_RESOLUTIONS.includes(value)) {
          // Defensive guard: callers should only pass whitelisted values,
          // but a stale persisted snapshot or an external caller could
          // still slip through; treat unknown inputs as a no-op rather
          // than corrupting the store.
          return;
        }
        set({ solverCacheGridResolution: value });
      },

      setSvgPixelsPerMm: (value: number) => {
        set({ svgPixelsPerMm: normalizeSvgPixelsPerMm(value) });
        invalidateGeneratedArtifacts();
      },

      resetSvgPixelsPerMm: () => {
        set({ svgPixelsPerMm: SVG_PIXELS_PER_MM_DEFAULT });
        invalidateGeneratedArtifacts();
      },

      setMaterialDeltaE00Tolerance: (value: number) => {
        invalidatePreviewRequest();
        set({
          materialDeltaE00Tolerance:
            normalizeMaterialDeltaE00Tolerance(value),
        });
        invalidatePreviewArtifacts();
      },

      setAutoReplaceGradientBanding: (enabled: boolean) =>
        set({ autoReplaceGradientBanding: enabled }),

      hydrateDeviceSettingsFromBackend: (settings: Partial<UserSettings>) => {
        const current = get();
        const patch = deriveBackendDeviceSettingsPatch(
          current,
          settings,
          INITIAL_PERSISTED_SETTINGS_SNAPSHOT,
        );
        const actions = get();
        if (patch.printerModel) {
          actions.setPrinterModel(patch.printerModel);
        }
        if (patch.slicerSoftware) {
          actions.setSlicerSoftware(patch.slicerSoftware);
        }
        if (typeof patch.customSlicerPath === "string") {
          actions.setCustomSlicerPath(patch.customSlicerPath);
        }
        if (typeof patch.customSlicerId === "string") {
          actions.setCustomSlicerId(patch.customSlicerId);
        }
        if (patch.nozzleSize) {
          actions.setNozzleSize(patch.nozzleSize);
        }
        if (typeof patch.enableBaseLayerHeightModifier === "boolean") {
          actions.setEnableBaseLayerHeightModifier(
            patch.enableBaseLayerHeightModifier,
          );
        }
        if (typeof patch.deviceProfileId === "string") {
          actions.setDeviceProfileId(patch.deviceProfileId);
        }
      },

      syncToBackend: async () => {
        const state = get();
        try {
          await saveSettings({
            last_lut: state.lastLutName,
            last_modeling_mode: state.lastModelingMode,
            last_color_mode: state.lastColorMode,
            last_slicer: state.lastSlicerId,
            palette_mode: state.paletteMode,
            enable_crop_modal: state.cropEnabled,
            printer_model: state.printerModel,
            slicer_software: state.slicerSoftware,
            device_profile_id: state.deviceProfileId,
            custom_slicer_path: state.customSlicerPath,
            custom_slicer_id: state.customSlicerId,
            nozzle_size: state.nozzleSize,
            enable_base_layer_height_modifier:
              state.enableBaseLayerHeightModifier,
          });
        } catch {
          // best-effort sync — settings are already persisted in localStorage
        }
      },
    }),
    {
      name: "lumina-settings",
      version: 1,
      migrate: migratePersistedSettings,
      merge: (persistedState, currentState) => {
        const persistedSettings = patchLegacyPersistedDeviceProfile(
          stripRetiredClientOnlySettings(
            persistedState && typeof persistedState === "object"
              ? (persistedState as Record<string, unknown>)
              : {},
          ),
        );
        return {
          ...currentState,
          ...persistedSettings,
          materialDeltaE00Tolerance: normalizeMaterialDeltaE00Tolerance(
            persistedSettings.materialDeltaE00Tolerance ??
              currentState.materialDeltaE00Tolerance,
          ),
        };
      },
    },
  ),
);
