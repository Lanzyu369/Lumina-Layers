import { create } from "zustand";

import {
  extractGradientCardStageA,
  rotateExtractorImage,
  saveGradientCardMaterial,
} from "../api/extractor";
import type {
  GradientCardMaterialSummary,
  OrientationRanking,
  SavedMaterialSummary,
  StageAFitSummary,
} from "../api/types";
import { normalizeResourceUrl } from "../utils/resourceUrl";

export type ExtractorWorkflow = "legacy" | "single-stage";

type CornerPoint = [number, number];

interface SingleStageState {
  workflow: ExtractorWorkflow;
  datasetFile: File | null;
  whiteImageFile: File | null;
  whiteImagePreviewUrl: string | null;
  whiteImageNaturalWidth: number | null;
  whiteImageNaturalHeight: number | null;
  whiteCornerPoints: CornerPoint[];
  blackImageFile: File | null;
  blackImagePreviewUrl: string | null;
  blackImageNaturalWidth: number | null;
  blackImageNaturalHeight: number | null;
  blackCornerPoints: CornerPoint[];
  isRotatingWhite: boolean;
  isRotatingBlack: boolean;
  isExtracting: boolean;
  extractError: string | null;
  sessionId: string | null;
  warnings: string[];
  stageAParamsUrl: string | null;
  whiteWarpPreviewUrl: string | null;
  blackWarpPreviewUrl: string | null;
  fitSummary: StageAFitSummary | null;
  materialSummary: GradientCardMaterialSummary | null;
  orientationRanking: OrientationRanking | null;
  materialName: string;
  verificationTargetDirectoryName: string | null;
  verificationTargetCount: number;
  isSaving: boolean;
  saveError: string | null;
  saveSuccess: string | null;
  materialFileUrl: string | null;
  savedStageAParamsUrl: string | null;
  savedMaterialSummary: SavedMaterialSummary | null;
}

interface SingleStageActions {
  setWorkflow: (workflow: ExtractorWorkflow) => void;
  setDatasetFile: (file: File | null) => void;
  setWhiteImageFile: (file: File | null) => void;
  setBlackImageFile: (file: File | null) => void;
  setWhiteImageNaturalSize: (width: number, height: number) => void;
  setBlackImageNaturalSize: (width: number, height: number) => void;
  rotateWhiteImage: () => Promise<void>;
  rotateBlackImage: () => Promise<void>;
  addWhiteCornerPoint: (point: CornerPoint) => void;
  addBlackCornerPoint: (point: CornerPoint) => void;
  clearWhiteCornerPoints: () => void;
  clearBlackCornerPoints: () => void;
  setMaterialName: (value: string) => void;
  startMaterialVerification: (target: {
    materialName: string;
    directoryName: string;
    verificationCount?: number | null;
  }) => void;
  clearMaterialVerification: () => void;
  submitExtract: () => Promise<void>;
  submitSave: () => Promise<void>;
  clearMessages: () => void;
}

const createPreviewUrl = (file: File | null): string | null => {
  if (
    !file ||
    typeof URL === "undefined" ||
    typeof URL.createObjectURL !== "function"
  ) {
    return null;
  }
  return URL.createObjectURL(file);
};

const revokePreviewUrl = (url: string | null) => {
  if (
    url?.startsWith("blob:") &&
    typeof URL !== "undefined" &&
    typeof URL.revokeObjectURL === "function"
  ) {
    URL.revokeObjectURL(url);
  }
};

const RESULT_RESET_STATE = {
  extractError: null,
  sessionId: null,
  warnings: [],
  stageAParamsUrl: null,
  whiteWarpPreviewUrl: null,
  blackWarpPreviewUrl: null,
  fitSummary: null,
  materialSummary: null,
  orientationRanking: null,
  isSaving: false,
  saveError: null,
  saveSuccess: null,
  materialFileUrl: null,
  savedStageAParamsUrl: null,
  savedMaterialSummary: null,
};

const DEFAULT_STATE: SingleStageState = {
  workflow: "single-stage",
  datasetFile: null,
  whiteImageFile: null,
  whiteImagePreviewUrl: null,
  whiteImageNaturalWidth: null,
  whiteImageNaturalHeight: null,
  whiteCornerPoints: [],
  blackImageFile: null,
  blackImagePreviewUrl: null,
  blackImageNaturalWidth: null,
  blackImageNaturalHeight: null,
  blackCornerPoints: [],
  isRotatingWhite: false,
  isRotatingBlack: false,
  isExtracting: false,
  extractError: null,
  sessionId: null,
  warnings: [],
  stageAParamsUrl: null,
  whiteWarpPreviewUrl: null,
  blackWarpPreviewUrl: null,
  fitSummary: null,
  materialSummary: null,
  orientationRanking: null,
  materialName: "",
  verificationTargetDirectoryName: null,
  verificationTargetCount: 0,
  isSaving: false,
  saveError: null,
  saveSuccess: null,
  materialFileUrl: null,
  savedStageAParamsUrl: null,
  savedMaterialSummary: null,
};

export const useSingleStageStore = create<
  SingleStageState & SingleStageActions
>((set, get) => ({
  ...DEFAULT_STATE,

  setWorkflow: (workflow: ExtractorWorkflow) =>
    set({
      workflow,
      extractError: null,
      saveError: null,
      saveSuccess: null,
    }),

  setDatasetFile: (file: File | null) =>
    set({
      datasetFile: file,
      ...RESULT_RESET_STATE,
    }),

  setWhiteImageFile: (file: File | null) => {
    const previousUrl = get().whiteImagePreviewUrl;
    revokePreviewUrl(previousUrl);
    set({
      whiteImageFile: file,
      whiteImagePreviewUrl: createPreviewUrl(file),
      whiteImageNaturalWidth: null,
      whiteImageNaturalHeight: null,
      whiteCornerPoints: [],
      ...RESULT_RESET_STATE,
    });
  },

  setBlackImageFile: (file: File | null) => {
    const previousUrl = get().blackImagePreviewUrl;
    revokePreviewUrl(previousUrl);
    set({
      blackImageFile: file,
      blackImagePreviewUrl: createPreviewUrl(file),
      blackImageNaturalWidth: null,
      blackImageNaturalHeight: null,
      blackCornerPoints: [],
      ...RESULT_RESET_STATE,
    });
  },

  setWhiteImageNaturalSize: (width: number, height: number) =>
    set({ whiteImageNaturalWidth: width, whiteImageNaturalHeight: height }),

  setBlackImageNaturalSize: (width: number, height: number) =>
    set({ blackImageNaturalWidth: width, blackImageNaturalHeight: height }),

  rotateWhiteImage: async () => {
    const { whiteImageFile, whiteImagePreviewUrl } = get();
    if (!whiteImageFile) {
      return;
    }
    set({
      isRotatingWhite: true,
      extractError: null,
      saveError: null,
      saveSuccess: null,
    });
    try {
      const response = await rotateExtractorImage(
        whiteImageFile,
        whiteImageFile.name,
      );
      const previewUrl = normalizeResourceUrl(response.preview_url);
      if (!previewUrl) {
        throw new Error(
          "White gradient card rotation did not return a preview URL",
        );
      }
      const res = await fetch(previewUrl);
      const blob = await res.blob();
      const baseName = whiteImageFile.name.replace(/\.[^.]+$/, "");
      const rotatedFile = new File([blob], `${baseName}.png`, {
        type: "image/png",
      });
      revokePreviewUrl(whiteImagePreviewUrl);
      set({
        whiteImageFile: rotatedFile,
        whiteImagePreviewUrl: previewUrl,
        whiteImageNaturalWidth: response.width,
        whiteImageNaturalHeight: response.height,
        whiteCornerPoints: [],
        isRotatingWhite: false,
        ...RESULT_RESET_STATE,
      });
    } catch (err) {
      set({
        extractError:
          err instanceof Error
            ? err.message
            : "White gradient card rotation failed",
        isRotatingWhite: false,
      });
    }
  },

  rotateBlackImage: async () => {
    const { blackImageFile, blackImagePreviewUrl } = get();
    if (!blackImageFile) {
      return;
    }
    set({
      isRotatingBlack: true,
      extractError: null,
      saveError: null,
      saveSuccess: null,
    });
    try {
      const response = await rotateExtractorImage(
        blackImageFile,
        blackImageFile.name,
      );
      const previewUrl = normalizeResourceUrl(response.preview_url);
      if (!previewUrl) {
        throw new Error(
          "Black gradient card rotation did not return a preview URL",
        );
      }
      const res = await fetch(previewUrl);
      const blob = await res.blob();
      const baseName = blackImageFile.name.replace(/\.[^.]+$/, "");
      const rotatedFile = new File([blob], `${baseName}.png`, {
        type: "image/png",
      });
      revokePreviewUrl(blackImagePreviewUrl);
      set({
        blackImageFile: rotatedFile,
        blackImagePreviewUrl: previewUrl,
        blackImageNaturalWidth: response.width,
        blackImageNaturalHeight: response.height,
        blackCornerPoints: [],
        isRotatingBlack: false,
        ...RESULT_RESET_STATE,
      });
    } catch (err) {
      set({
        extractError:
          err instanceof Error
            ? err.message
            : "Black gradient card rotation failed",
        isRotatingBlack: false,
      });
    }
  },

  addWhiteCornerPoint: (point: CornerPoint) => {
    const { whiteCornerPoints } = get();
    if (whiteCornerPoints.length >= 4) {
      return;
    }
    set({
      whiteCornerPoints: [...whiteCornerPoints, point],
      ...RESULT_RESET_STATE,
    });
  },

  addBlackCornerPoint: (point: CornerPoint) => {
    const { blackCornerPoints } = get();
    if (blackCornerPoints.length >= 4) {
      return;
    }
    set({
      blackCornerPoints: [...blackCornerPoints, point],
      ...RESULT_RESET_STATE,
    });
  },

  clearWhiteCornerPoints: () =>
    set({ whiteCornerPoints: [], ...RESULT_RESET_STATE }),

  clearBlackCornerPoints: () =>
    set({ blackCornerPoints: [], ...RESULT_RESET_STATE }),

  setMaterialName: (value: string) =>
    set({ materialName: value, saveError: null, saveSuccess: null }),

  startMaterialVerification: ({
    materialName,
    directoryName,
    verificationCount,
  }) => {
    const { whiteImagePreviewUrl, blackImagePreviewUrl } = get();
    revokePreviewUrl(whiteImagePreviewUrl);
    revokePreviewUrl(blackImagePreviewUrl);
    set({
      datasetFile: null,
      whiteImageFile: null,
      whiteImagePreviewUrl: null,
      whiteImageNaturalWidth: null,
      whiteImageNaturalHeight: null,
      whiteCornerPoints: [],
      blackImageFile: null,
      blackImagePreviewUrl: null,
      blackImageNaturalWidth: null,
      blackImageNaturalHeight: null,
      blackCornerPoints: [],
      materialName,
      verificationTargetDirectoryName: directoryName,
      verificationTargetCount: Math.max(1, verificationCount ?? 1),
      ...RESULT_RESET_STATE,
    });
  },

  clearMaterialVerification: () =>
    set({
      verificationTargetDirectoryName: null,
      verificationTargetCount: 0,
      saveError: null,
      saveSuccess: null,
    }),

  submitExtract: async () => {
    const state = get();
    if (!state.datasetFile || !state.whiteImageFile || !state.blackImageFile) {
      set({
        extractError: "Select the kit ZIP and both gradient card images first.",
      });
      return;
    }
    if (
      state.whiteCornerPoints.length !== 4 ||
      state.blackCornerPoints.length !== 4
    ) {
      set({
        extractError:
          "Mark 4 corners on both the white and black gradient cards.",
      });
      return;
    }

    set({
      isExtracting: true,
      extractError: null,
      saveError: null,
      saveSuccess: null,
    });
    try {
      const response = await extractGradientCardStageA({
        datasetZip: state.datasetFile,
        whiteImage: state.whiteImageFile,
        blackImage: state.blackImageFile,
        whiteCornerPoints: state.whiteCornerPoints,
        blackCornerPoints: state.blackCornerPoints,
      });
      set({
        sessionId: response.session_id,
        warnings: response.warnings ?? [],
        stageAParamsUrl: normalizeResourceUrl(response.stage_a_params_url),
        whiteWarpPreviewUrl: normalizeResourceUrl(
          response.white_warp_preview_url ?? null,
        ),
        blackWarpPreviewUrl: normalizeResourceUrl(
          response.black_warp_preview_url ?? null,
        ),
        fitSummary: response.fit_summary ?? null,
        materialSummary: response.material_summary ?? null,
        orientationRanking: response.orientation_ranking ?? null,
        materialFileUrl: null,
        savedStageAParamsUrl: null,
        savedMaterialSummary: null,
        isExtracting: false,
      });
    } catch (err) {
      set({
        extractError:
          err instanceof Error
            ? err.message
            : "Gradient card extraction failed",
        isExtracting: false,
      });
    }
  },

  submitSave: async () => {
    const state = get();
    if (!state.sessionId) {
      set({ saveError: "Compute Stage A material data before saving." });
      return;
    }
    if (!state.materialName.trim()) {
      set({ saveError: "Enter a material name before saving." });
      return;
    }

    set({ isSaving: true, saveError: null, saveSuccess: null });
    try {
      const response = await saveGradientCardMaterial({
        sessionId: state.sessionId,
        materialName: state.materialName.trim(),
        targetDirectoryName: state.verificationTargetDirectoryName,
      });
      set({
        materialFileUrl: normalizeResourceUrl(response.material_file_url),
        savedStageAParamsUrl: normalizeResourceUrl(response.stage_a_params_url),
        savedMaterialSummary: response.material_summary ?? null,
        verificationTargetCount: Math.max(
          state.verificationTargetCount,
          Number(response.material_summary?.verification_count ?? 0),
        ),
        saveSuccess: response.message,
        isSaving: false,
      });
    } catch (err) {
      set({
        saveError:
          err instanceof Error
            ? err.message
            : "Saving gradient card material failed",
        isSaving: false,
      });
    }
  },

  clearMessages: () =>
    set({
      extractError: null,
      saveError: null,
      saveSuccess: null,
    }),
}));
