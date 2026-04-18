import { create } from "zustand";
import type { SlicerInfo } from "../api/types";
import {
  detectSlicers as apiDetectSlicers,
  launchSlicer as apiLaunchSlicer,
} from "../api/slicer";
import { useSettingsStore } from "./settingsStore";
import {
  getDetectedSlicerIdForSoftware,
  getSoftwareIdForDetectedSlicerId,
} from "../utils/settingsOptionIds";

// ========== State Interface ==========

export interface SlicerState {
  slicers: SlicerInfo[];
  selectedSlicerId: string | null;
  isDetecting: boolean;
  isLaunching: boolean;
  launchMessage: string | null;
  error: string | null;
}

// ========== Actions Interface ==========

export interface SlicerActions {
  detectSlicers: () => Promise<void>;
  setSelectedSlicerId: (id: string | null) => void;
  launchSlicer: (filePath: string) => Promise<void>;
  clearMessage: () => void;
}

// ========== Default State ==========

const DEFAULT_STATE: SlicerState = {
  slicers: [],
  selectedSlicerId: null,
  isDetecting: false,
  isLaunching: false,
  launchMessage: null,
  error: null,
};

export function resolveSelectedSlicerId(
  slicers: SlicerInfo[],
  lastSlicerId: string | null,
  slicerSoftware: string,
): string | null {
  const preferredConfiguredId = getDetectedSlicerIdForSoftware(slicerSoftware);
  const configuredMatch = preferredConfiguredId
    ? slicers.find((slicer) => slicer.id === preferredConfiguredId)
    : null;
  if (configuredMatch) {
    return configuredMatch.id;
  }

  const restored = slicers.find((slicer) => slicer.id === lastSlicerId);
  return restored ? restored.id : (slicers[0]?.id ?? null);
}

// ========== Store ==========

export const useSlicerStore = create<SlicerState & SlicerActions>(
  (set, _get) => ({
    ...DEFAULT_STATE,

    detectSlicers: async () => {
      set({ isDetecting: true, error: null });
      try {
        const response = await apiDetectSlicers();
        const slicers = response.slicers;
        const lastId = useSettingsStore.getState().lastSlicerId;
        const slicerSoftware = useSettingsStore.getState().slicerSoftware;
        const restored = slicers.find((s) => s.id === lastId);
        set({
          slicers,
          isDetecting: false,
          selectedSlicerId: resolveSelectedSlicerId(
            slicers,
            restored ? restored.id : null,
            slicerSoftware,
          ),
        });
      } catch (err) {
        set({
          isDetecting: false,
          error: err instanceof Error ? err.message : "切片软件检测失败",
        });
      }
    },

    setSelectedSlicerId: (id: string | null) => {
      set({ selectedSlicerId: id });
      if (id) {
        const settingsState = useSettingsStore.getState();
        settingsState.setLastSlicerId(id);
        const softwareId = getSoftwareIdForDetectedSlicerId(id);
        if (softwareId && settingsState.slicerSoftware !== softwareId) {
          settingsState.setSlicerSoftware(softwareId);
        }
        void useSettingsStore.getState().syncToBackend();
      }
    },

    launchSlicer: async (filePath: string) => {
      const state = _get();
      if (!state.selectedSlicerId) {
        set({ error: "请先选择切片软件" });
        return;
      }
      set({ isLaunching: true, error: null, launchMessage: null });
      try {
        const response = await apiLaunchSlicer({
          slicer_id: state.selectedSlicerId,
          file_path: filePath,
        });
        set({
          isLaunching: false,
          launchMessage: response.message,
        });
      } catch (err) {
        set({
          isLaunching: false,
          error: err instanceof Error ? err.message : "启动切片软件失败",
        });
      }
    },

    clearMessage: () => set({ launchMessage: null, error: null }),
  })
);
