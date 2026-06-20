import { create } from "zustand";
import type { SlicerInfo } from "../api/types";
import { apiErrorToVisibleMessage } from "../api/client";
import {
  detectSlicers as apiDetectSlicers,
  launchSlicer as apiLaunchSlicer,
  validateCustomSlicerPath as apiValidateCustomSlicerPath,
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
  isValidatingCustomPath: boolean;
  launchMessage: string | null;
  customPathMessage: string | null;
  customPathError: string | null;
  error: string | null;
}

// ========== Actions Interface ==========

export interface SlicerActions {
  detectSlicers: () => Promise<void>;
  setSelectedSlicerId: (id: string | null) => void;
  validateAndSaveCustomSlicerPath: (path: string) => Promise<void>;
  clearCustomSlicerPath: () => void;
  launchSlicer: (filePath: string, slicerId?: string | null) => Promise<void>;
  clearMessage: () => void;
}

// ========== Default State ==========

const DEFAULT_STATE: SlicerState = {
  slicers: [],
  selectedSlicerId: null,
  isDetecting: false,
  isLaunching: false,
  isValidatingCustomPath: false,
  launchMessage: null,
  customPathMessage: null,
  customPathError: null,
  error: null,
};

function hasApiResponse(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "response" in error
  );
}

function slicerErrorToVisibleMessage(
  error: unknown,
  fallback: string,
): string {
  if (error instanceof Error || hasApiResponse(error)) {
    return apiErrorToVisibleMessage(error, fallback);
  }
  return fallback;
}

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

export function mergeCustomSlicer(
  slicers: SlicerInfo[],
  customSlicer: SlicerInfo | null,
): SlicerInfo[] {
  if (!customSlicer) {
    return slicers;
  }
  const rest = slicers.filter(
    (slicer) =>
      slicer.id !== customSlicer.id &&
      slicer.exe_path !== customSlicer.exe_path,
  );
  return [{ ...customSlicer, source: customSlicer.source ?? "custom" }, ...rest];
}

// ========== Store ==========

export const useSlicerStore = create<SlicerState & SlicerActions>(
  (set, _get) => ({
    ...DEFAULT_STATE,

    detectSlicers: async () => {
      set({ isDetecting: true, error: null });
      try {
        const response = await apiDetectSlicers();
        const settingsState = useSettingsStore.getState();
        let slicers = response.slicers;
        const customPath = settingsState.customSlicerPath.trim();
        if (customPath) {
          try {
            const customResponse = await apiValidateCustomSlicerPath({
              path: customPath,
            });
            slicers = mergeCustomSlicer(slicers, customResponse.slicer);
          } catch {
            // Saved custom paths are best-effort; auto-detection should still work.
          }
        }
        const lastId = settingsState.lastSlicerId;
        const slicerSoftware = settingsState.slicerSoftware;
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
          error: slicerErrorToVisibleMessage(err, "切片软件检测失败"),
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

    validateAndSaveCustomSlicerPath: async (path: string) => {
      const trimmed = path.trim();
      if (!trimmed) {
        set({
          customPathMessage: null,
          customPathError: "请输入切片软件 .app 路径",
        });
        return;
      }
      set({
        isValidatingCustomPath: true,
        customPathMessage: null,
        customPathError: null,
      });
      try {
        const response = await apiValidateCustomSlicerPath({ path: trimmed });
        if (!response.slicer) {
          throw new Error(response.message || "未识别到切片软件");
        }
        const settingsState = useSettingsStore.getState();
        settingsState.setCustomSlicerPath(response.slicer.exe_path);
        settingsState.setCustomSlicerId(response.slicer.id);
        settingsState.setLastSlicerId(response.slicer.id);
        const softwareId = getSoftwareIdForDetectedSlicerId(response.slicer.id);
        if (softwareId && settingsState.slicerSoftware !== softwareId) {
          settingsState.setSlicerSoftware(softwareId);
        }
        await settingsState.syncToBackend();
        set((state) => ({
          slicers: mergeCustomSlicer(state.slicers, response.slicer),
          selectedSlicerId: response.slicer?.id ?? state.selectedSlicerId,
          isValidatingCustomPath: false,
          customPathMessage: response.message,
          customPathError: null,
        }));
      } catch (err) {
        set({
          isValidatingCustomPath: false,
          customPathMessage: null,
          customPathError: slicerErrorToVisibleMessage(
            err,
            "切片软件路径校验失败",
          ),
        });
      }
    },

    clearCustomSlicerPath: () => {
      const settingsState = useSettingsStore.getState();
      settingsState.setCustomSlicerPath("");
      settingsState.setCustomSlicerId("");
      void settingsState.syncToBackend();
      set((state) => {
        const slicers = state.slicers.filter(
          (slicer) => !String(slicer.source ?? "").includes("custom"),
        );
        return {
          slicers,
          selectedSlicerId:
            state.selectedSlicerId &&
            slicers.some((slicer) => slicer.id === state.selectedSlicerId)
              ? state.selectedSlicerId
              : (slicers[0]?.id ?? null),
          customPathMessage: null,
          customPathError: null,
        };
      });
      void _get().detectSlicers();
    },

    launchSlicer: async (filePath: string, slicerId?: string | null) => {
      const state = _get();
      const targetSlicerId = slicerId ?? state.selectedSlicerId;
      if (!targetSlicerId) {
        set({ error: "请先选择切片软件" });
        return;
      }
      set({ isLaunching: true, error: null, launchMessage: null });
      try {
        const settingsState = useSettingsStore.getState();
        const selectedSlicer = state.slicers.find(
          (slicer) => slicer.id === targetSlicerId,
        );
        const slicerPath =
          settingsState.customSlicerPath &&
          settingsState.customSlicerId === targetSlicerId &&
          String(selectedSlicer?.source ?? "").includes("custom")
            ? settingsState.customSlicerPath
            : undefined;
        const response = await apiLaunchSlicer({
          slicer_id: targetSlicerId,
          file_path: filePath,
          ...(slicerPath ? { slicer_path: slicerPath } : {}),
        });
        set({
          isLaunching: false,
          launchMessage: response.message,
        });
      } catch (err) {
        set({
          isLaunching: false,
          error: slicerErrorToVisibleMessage(err, "启动切片软件失败"),
        });
      }
    },

    clearMessage: () =>
      set({
        launchMessage: null,
        customPathMessage: null,
        customPathError: null,
        error: null,
      }),
  })
);
