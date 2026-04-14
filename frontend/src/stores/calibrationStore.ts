import { create } from "zustand";
import type { CalibrationColorMode, BackingColor } from "../api/types";
import {
  CalibrationColorMode as CalibrationColorModeEnum,
  BackingColor as BackingColorEnum,
} from "../api/types";
import {
  calibrationGenerate,
  generateSingleStageKit,
} from "../api/calibration";
import { clampValue } from "./converter";

export type CalibrationWorkflow = "legacy" | "single-stage";

const PALETTE_PRESETS: Record<
  CalibrationColorMode,
  Array<{ color: string; hex_color: string }>
> = {
  [CalibrationColorModeEnum.BW]: [
    { color: "White", hex_color: "#FFFFFF" },
    { color: "Black", hex_color: "#000000" },
  ],
  [CalibrationColorModeEnum.FOUR_COLOR_CMYW]: [
    { color: "White", hex_color: "#FFFFFF" },
    { color: "Cyan", hex_color: "#0086D6" },
    { color: "Magenta", hex_color: "#EC008C" },
    { color: "Yellow", hex_color: "#F4EE2A" },
  ],
  [CalibrationColorModeEnum.FOUR_COLOR_RYBW]: [
    { color: "White", hex_color: "#FFFFFF" },
    { color: "Red", hex_color: "#DC143C" },
    { color: "Yellow", hex_color: "#FFE600" },
    { color: "Blue", hex_color: "#0064F0" },
  ],
  [CalibrationColorModeEnum.FIVE_COLOR_EXT]: [
    { color: "White", hex_color: "#FFFFFF" },
    { color: "Red", hex_color: "#DC143C" },
    { color: "Yellow", hex_color: "#FFE600" },
    { color: "Blue", hex_color: "#0064F0" },
    { color: "Black", hex_color: "#141414" },
  ],
  [CalibrationColorModeEnum.SIX_COLOR]: [
    { color: "White", hex_color: "#FFFFFF" },
    { color: "Cyan", hex_color: "#0086D6" },
    { color: "Magenta", hex_color: "#EC008C" },
    { color: "Green", hex_color: "#00AE42" },
    { color: "Yellow", hex_color: "#F4EE2A" },
    { color: "Black", hex_color: "#000000" },
  ],
  [CalibrationColorModeEnum.SIX_COLOR_RYBW]: [
    { color: "White", hex_color: "#FFFFFF" },
    { color: "Red", hex_color: "#DC143C" },
    { color: "Yellow", hex_color: "#FFE600" },
    { color: "Blue", hex_color: "#0064F0" },
    { color: "Green", hex_color: "#00AE42" },
    { color: "Black", hex_color: "#000000" },
  ],
  [CalibrationColorModeEnum.EIGHT_COLOR]: [
    { color: "White", hex_color: "#FFFFFF" },
    { color: "Cyan", hex_color: "#0086D6" },
    { color: "Magenta", hex_color: "#EC008C" },
    { color: "Yellow", hex_color: "#F4EE2A" },
    { color: "Black", hex_color: "#000000" },
    { color: "Red", hex_color: "#C12E1F" },
    { color: "Deep Blue", hex_color: "#0A2989" },
    { color: "Green", hex_color: "#00AE42" },
  ],
};

function buildSingleStagePalette(
  colorMode: CalibrationColorMode,
  materialDefault: string,
) {
  return (
    PALETTE_PRESETS[colorMode] ??
    PALETTE_PRESETS[CalibrationColorModeEnum.FOUR_COLOR_RYBW]
  ).map((entry) => ({
    color: entry.color,
    material: materialDefault,
    hex_color: entry.hex_color,
    color_name: entry.color,
  }));
}

export interface CalibrationState {
  workflow: CalibrationWorkflow;
  color_mode: CalibrationColorMode;
  block_size: number;
  gap: number;
  backing: BackingColor;
  eight_color_full_export: boolean;
  substrateId: string;
  substrateDisplayName: string;
  materialDefault: string;
  isLoading: boolean;
  error: string | null;
  downloadUrl: string | null;
  previewImageUrl: string | null;
  modelUrl: string | null;
  statusMessage: string | null;
  manifestUrl: string | null;
  singleStageJobs: Array<{
    color: string;
    color_name: string;
    material: string;
    substrate_id: string;
    substrate_display_name: string;
    filename: string;
  }>;
}

export interface CalibrationActions {
  setWorkflow: (workflow: CalibrationWorkflow) => void;
  setColorMode: (mode: CalibrationColorMode) => void;
  setBlockSize: (size: number) => void;
  setGap: (gap: number) => void;
  setBacking: (color: BackingColor) => void;
  setEightColorFullExport: (enabled: boolean) => void;
  setSubstrateId: (value: string) => void;
  setSubstrateDisplayName: (value: string) => void;
  setMaterialDefault: (value: string) => void;
  submitGenerate: () => Promise<void>;
  setError: (error: string | null) => void;
  clearError: () => void;
}

const DEFAULT_STATE: CalibrationState = {
  workflow: "legacy",
  color_mode: CalibrationColorModeEnum.FOUR_COLOR_RYBW,
  block_size: 5,
  gap: 0.82,
  backing: BackingColorEnum.WHITE,
  eight_color_full_export: false,
  substrateId: "white",
  substrateDisplayName: "White",
  materialDefault: "PLA Basic",
  isLoading: false,
  error: null,
  downloadUrl: null,
  previewImageUrl: null,
  modelUrl: null,
  statusMessage: null,
  manifestUrl: null,
  singleStageJobs: [],
};

export const useCalibrationStore = create<
  CalibrationState & CalibrationActions
>((set, get) => ({
  ...DEFAULT_STATE,

  setWorkflow: (workflow: CalibrationWorkflow) =>
    set({
      workflow,
      downloadUrl: null,
      previewImageUrl: null,
      manifestUrl: null,
      singleStageJobs: [],
      statusMessage: null,
      error: null,
    }),

  setColorMode: (mode: CalibrationColorMode) =>
    set((state) => ({
      color_mode: mode,
      eight_color_full_export:
        mode === CalibrationColorModeEnum.EIGHT_COLOR
          ? state.eight_color_full_export
          : false,
    })),

  setBlockSize: (size: number) => set({ block_size: clampValue(size, 3, 10) }),

  setGap: (gap: number) => set({ gap: clampValue(gap, 0.4, 2.0) }),

  setBacking: (color: BackingColor) => set({ backing: color }),

  setEightColorFullExport: (enabled: boolean) =>
    set({ eight_color_full_export: enabled }),

  setSubstrateId: (value: string) => set({ substrateId: value }),

  setSubstrateDisplayName: (value: string) =>
    set({ substrateDisplayName: value }),

  setMaterialDefault: (value: string) => set({ materialDefault: value }),

  submitGenerate: async () => {
    const state = get();
    set({ isLoading: true, error: null });
    try {
      if (state.workflow === "single-stage") {
        const response = await generateSingleStageKit({
          palette: buildSingleStagePalette(
            state.color_mode,
            state.materialDefault,
          ),
          substrate_id: state.substrateId,
          substrate_display_name: state.substrateDisplayName,
          material_default: state.materialDefault,
        });
        set({
          downloadUrl: response.kit_download_url,
          previewImageUrl: response.preview_url ?? null,
          modelUrl: null,
          manifestUrl: response.manifest_url,
          singleStageJobs: response.jobs ?? [],
          statusMessage: response.message,
          isLoading: false,
        });
        return;
      }

      const response = await calibrationGenerate({
        color_mode: state.color_mode,
        block_size: state.block_size,
        gap: state.gap,
        backing: state.backing,
        eight_color_full_export: state.eight_color_full_export,
      });
      set({
        downloadUrl: response.download_url,
        previewImageUrl: response.preview_url ?? null,
        modelUrl: null,
        manifestUrl: null,
        singleStageJobs: [],
        statusMessage: response.message,
        isLoading: false,
      });
    } catch (err) {
      set({
        error:
          err instanceof Error ? err.message : "Calibration generation failed",
        isLoading: false,
      });
    }
  },

  setError: (error: string | null) => set({ error }),
  clearError: () => set({ error: null }),
}));
