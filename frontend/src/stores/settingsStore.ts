import { create } from "zustand";
import { persist } from "zustand/middleware";
import { saveSettings } from "../api/system";
import type { UserSettings } from "../api/types";
import { invalidateGeneratedArtifacts } from "./generatedArtifactInvalidation";

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

export const SVG_PIXELS_PER_MM_DEFAULT = 10.0;
export const SVG_PIXELS_PER_MM_MIN = 2.0;
export const SVG_PIXELS_PER_MM_MAX = 50.0;
export const SVG_PIXELS_PER_MM_STEP = 0.1;

/**
 * Default URLs of the standalone Material-LUT Studio (MLS) service.
 * The MLS dev frontend listens on :5180 (opened via the jump entry) and the
 * MLS backend API on :8100 (called by the converter at runtime). Both can be
 * overridden in Settings for separate-server deployments.
 * 解耦后的 Material-LUT Studio 独立服务默认地址：前端默认 :5180（通过跳转入口
 * 打开），后端 API 默认 :8100（转换器运行时调用）。两者均可在设置中覆盖，
 * 以支持前后端分开部署到不同服务器。
 */
export const MLS_DEFAULT_BASE_URL = "http://localhost:5180";
export const MLS_DEFAULT_BACKEND_URL = "http://localhost:8100";

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
  customSlicerPath: string;
  customSlicerId: string;
  nozzleSize: "0.2" | "0.4";
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
   * Advanced: when true, successful previews automatically collapse every
   * gradient-banding group to its representative colour (the material with
   * the highest pixel count). Off by default so first-time users see the
   * raw banded preview and opt into the fix from the color workstation.
   * 高级设置：开启后，每次预览成功会自动把每个渐变海带纹分组统一替换为组
   * 内代表色（像素最多的那一个），一键去掉海带纹；默认关闭。
   */
  autoReplaceGradientBanding: boolean;
  /**
   * Material-LUT Studio (MLS) — the decoupled material/LUT management service.
   * ``mlsBaseUrl`` is the standalone MLS **frontend** UI (opened via the jump
   * entry); ``mlsBackendUrl`` is the MLS **backend** API the converter calls
   * at runtime (solver cache, material list, color suggestions). They are
   * separate so the frontend and backend can live on different servers. These
   * are client-only preferences (no backend sync).
   * 解耦后的耗材/LUT 管理服务。``mlsBaseUrl`` 为 MLS **前端**界面地址（跳转
   * 入口打开）；``mlsBackendUrl`` 为 MLS **后端** API 地址（转换器运行时调用：
   * 求解缓存、选材列表、取色建议）。两者分开，便于前后端部署在不同服务器。
   * 仅客户端偏好，不与后端同步。
   */
  mlsBaseUrl: string;
  mlsBackendUrl: string;
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
  setCustomSlicerPath: (path: string) => void;
  setCustomSlicerId: (id: string) => void;
  setNozzleSize: (size: "0.2" | "0.4") => void;
  setEnableBaseLayerHeightModifier: (enabled: boolean) => void;
  setEnableSolverCacheGridSelection: (enabled: boolean) => void;
  setSolverCacheGridResolution: (value: SolverCacheGridResolution) => void;
  setSvgPixelsPerMm: (value: number) => void;
  resetSvgPixelsPerMm: () => void;
  setAutoReplaceGradientBanding: (enabled: boolean) => void;
  setMlsBaseUrl: (url: string) => void;
  setMlsBackendUrl: (url: string) => void;
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
  autoReplaceGradientBanding: false,
  mlsBaseUrl: MLS_DEFAULT_BASE_URL,
  mlsBackendUrl: MLS_DEFAULT_BACKEND_URL,
};

type PersistedSettingsSnapshot = Partial<SettingsState>;

function readPersistedSettingsSnapshot(): PersistedSettingsSnapshot | null {
  try {
    const raw = localStorage.getItem("lumina-settings");
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as { state?: PersistedSettingsSnapshot };
    if (!parsed || typeof parsed !== "object" || !parsed.state) {
      return null;
    }
    return parsed.state;
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
    (settings.nozzle_size === "0.2" || settings.nozzle_size === "0.4") &&
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
        set({ printerModel: id });
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
        set({ slicerSoftware: id });
        invalidateGeneratedArtifacts();
      },

      setCustomSlicerPath: (path: string) => set({ customSlicerPath: path }),

      setCustomSlicerId: (id: string) => set({ customSlicerId: id }),

      setNozzleSize: (size: "0.2" | "0.4") => {
        set({ nozzleSize: size });
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

      setAutoReplaceGradientBanding: (enabled: boolean) =>
        set({ autoReplaceGradientBanding: enabled }),

      setMlsBaseUrl: (url: string) => set({ mlsBaseUrl: url }),

      setMlsBackendUrl: (url: string) => set({ mlsBackendUrl: url }),

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
    },
  ),
);
