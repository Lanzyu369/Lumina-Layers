import { create } from "zustand";
import { persist } from "zustand/middleware";
import { saveSettings } from "../api/system";
import type { UserSettings } from "../api/types";
import { invalidateGeneratedArtifacts } from "./generatedArtifactInvalidation";

// ========== State Interface ==========

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
  nozzleSize: "0.2" | "0.4";
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
  setNozzleSize: (size: "0.2" | "0.4") => void;
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
  nozzleSize: "0.4",
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
    (settings.nozzle_size === "0.2" || settings.nozzle_size === "0.4") &&
    current.nozzleSize === DEFAULT_SETTINGS.nozzleSize &&
    !hasOwnSetting(persistedSnapshot, "nozzleSize")
  ) {
    patch.nozzleSize = settings.nozzle_size;
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

      setEnableFancyLoading: (enabled: boolean) => set({ enableFancyLoading: enabled }),

      setEnableWittyLoading: (enabled: boolean) => set({ enableWittyLoading: enabled }),

      setPaletteMode: (mode: "swatch" | "card") => set({ paletteMode: mode }),

      setPrinterModel: (id: string) => {
        set({ printerModel: id });
        invalidateGeneratedArtifacts();
        
        // 延迟导入避免循环依赖
        import("./converter").then(({ useConverterStore }) => {
          const { bedSizes, setBedLabel } = useConverterStore.getState();
          const printerBed = bedSizes.find(bed => bed.printer_id === id);
          if (printerBed) {
            setBedLabel(printerBed.label);
          }
        });
      },

      setSlicerSoftware: (id: string) => {
        set({ slicerSoftware: id });
        invalidateGeneratedArtifacts();
      },

      setNozzleSize: (size: "0.2" | "0.4") => {
        set({ nozzleSize: size });
        invalidateGeneratedArtifacts();
      },

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
        if (patch.nozzleSize) {
          actions.setNozzleSize(patch.nozzleSize);
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
            nozzle_size: state.nozzleSize,
          });
        } catch {
          // best-effort sync — settings are already persisted in localStorage
        }
      },
    }),
    {
      name: "lumina-settings",
    }
  )
);
