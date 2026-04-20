import { create } from "zustand";

import {
  extractGradientCardStageA,
  rotateExtractorImage,
  saveGradientCardMaterial,
} from "../api/extractor";
import type {
  GradientCardMaterialSummary,
  ManualOrientationLabel,
  OrientationRanking,
  SavedMaterialSummary,
  StageAFitSummary,
} from "../api/types";
import { tRuntime } from "../i18n/runtime";
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
  manualWhiteOrientation: ManualOrientationLabel | null;
  manualBlackOrientation: ManualOrientationLabel | null;
  materialName: string;
  materialBrand: string;
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
  setMaterialBrand: (value: string) => void;
  setManualWhiteOrientation: (value: ManualOrientationLabel | null) => void;
  setManualBlackOrientation: (value: ManualOrientationLabel | null) => void;
  startMaterialVerification: (target: {
    materialName: string;
    directoryName: string;
    verificationCount?: number | null;
  }) => void;
  clearMaterialVerification: () => void;
  submitExtract: () => Promise<void>;
  submitSave: (saveMode?: "merge" | "override") => Promise<void>;
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

type ErrorWithResponseDetail = Error & {
  response?: {
    status?: number;
    data?: {
      detail?: unknown;
    };
  };
};

const INVALID_GRADIENT_CARD_ZIP_DETAILS = [
  "Gradient card kit must be uploaded as a ZIP file",
  "Gradient card kit zip must contain manifest.json",
  "Malformed ZIP archive",
  "manifest.json is not valid UTF-8 JSON",
];

const GRADIENT_CARD_CORNER_DETAIL_PATTERNS = [
  /^Invalid (white|black)_corner_points JSON:/,
  /^(white|black)_corner_points must contain exactly 4 points$/,
  /^corner points must contain exactly 4 \[x, y\] pairs$/,
];

const GRADIENT_CARD_ORIENTATION_DETAIL_PATTERNS = [
  /^Unable to determine gradient card orientation$/,
  /^Invalid manual orientation label /,
];

const GRADIENT_CARD_SAVE_SESSION_DETAIL_PATTERNS = [
  /^Session .+ not found$/,
  /^Session does not contain a computed gradient-card Stage A result$/,
];

const GRADIENT_CARD_SAVE_TARGET_MISSING_DETAIL_PATTERNS = [
  /^Saved material directory not found:/,
  /^Saved material archive not found:/,
];

const GRADIENT_CARD_SAVE_TARGET_INVALID_DETAILS = [
  "Existing material archive is not valid UTF-8 JSON",
];

const GRADIENT_CARD_IMAGE_DECODE_DETAIL_PREFIX = "无法解码图像文件:";
const GRADIENT_CARD_HEIC_DETAIL_FRAGMENT = "HEIC/HEIF";

function extractErrorDetail(err: unknown): string | null {
  const detail = (err as ErrorWithResponseDetail | null)?.response?.data
    ?.detail;
  return typeof detail === "string" && detail.trim().length > 0
    ? detail.trim()
    : null;
}

function matchesAnyPattern(value: string, patterns: RegExp[]): boolean {
  return patterns.some((pattern) => pattern.test(value));
}

function isInvalidGradientCardZipDetail(detail: string): boolean {
  return INVALID_GRADIENT_CARD_ZIP_DETAILS.includes(detail);
}

function resolveKnownGradientCardDetail(detail: string): string | null {
  if (isInvalidGradientCardZipDetail(detail)) {
    return tRuntime("mat_gradient_invalid_zip_error");
  }
  if (
    detail.includes(GRADIENT_CARD_HEIC_DETAIL_FRAGMENT) &&
    detail.includes("pillow-heif")
  ) {
    return tRuntime("mat_gradient_heic_unsupported_error");
  }
  if (detail.startsWith(GRADIENT_CARD_IMAGE_DECODE_DETAIL_PREFIX)) {
    return tRuntime("mat_gradient_invalid_image_error");
  }
  if (matchesAnyPattern(detail, GRADIENT_CARD_CORNER_DETAIL_PATTERNS)) {
    return tRuntime("mat_gradient_invalid_corner_error");
  }
  if (matchesAnyPattern(detail, GRADIENT_CARD_ORIENTATION_DETAIL_PATTERNS)) {
    return tRuntime("mat_gradient_invalid_orientation_error");
  }
  return null;
}

function resolveGradientCardExtractError(err: unknown): string {
  const detail = extractErrorDetail(err);
  if (detail) {
    return resolveKnownGradientCardDetail(detail) ?? detail;
  }
  return tRuntime("mat_gradient_extract_failed_error");
}

function resolveGradientCardRotationError(
  err: unknown,
  substrate: "white" | "black",
): string {
  const detail = extractErrorDetail(err);
  if (detail) {
    return resolveKnownGradientCardDetail(detail) ?? detail;
  }
  return tRuntime(
    substrate === "white"
      ? "mat_gradient_rotate_white_failed"
      : "mat_gradient_rotate_black_failed",
  );
}

function resolveGradientCardSaveError(err: unknown): string {
  const detail = extractErrorDetail(err);
  if (detail) {
    if (matchesAnyPattern(detail, GRADIENT_CARD_SAVE_SESSION_DETAIL_PATTERNS)) {
      return tRuntime("mat_gradient_save_session_expired_error");
    }
    if (detail === "material_name is required") {
      return tRuntime("mat_gradient_save_name_required_error");
    }
    if (
      matchesAnyPattern(
        detail,
        GRADIENT_CARD_SAVE_TARGET_MISSING_DETAIL_PATTERNS,
      )
    ) {
      return tRuntime("mat_gradient_save_target_missing_error");
    }
    if (GRADIENT_CARD_SAVE_TARGET_INVALID_DETAILS.includes(detail)) {
      return tRuntime("mat_gradient_save_target_invalid_error");
    }
    return detail;
  }
  return tRuntime("mat_gradient_save_failed_error");
}

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
  manualWhiteOrientation: null,
  manualBlackOrientation: null,
  materialName: "",
  materialBrand: "",
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
        extractError: resolveGradientCardRotationError(err, "white"),
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
        extractError: resolveGradientCardRotationError(err, "black"),
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

  setMaterialBrand: (value: string) =>
    set({ materialBrand: value, saveError: null, saveSuccess: null }),

  setManualWhiteOrientation: (value: ManualOrientationLabel | null) =>
    set({ manualWhiteOrientation: value, extractError: null }),

  setManualBlackOrientation: (value: ManualOrientationLabel | null) =>
    set({ manualBlackOrientation: value, extractError: null }),

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
      // Re-verification keeps using the existing archive directory, so the
      // brand value cannot be changed at this stage; clear the staged input.
      materialBrand: "",
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
        extractError: tRuntime("mat_gradient_extract_inputs_required_error"),
      });
      return;
    }
    if (
      state.whiteCornerPoints.length !== 4 ||
      state.blackCornerPoints.length !== 4
    ) {
      set({
        extractError: tRuntime("mat_gradient_extract_corners_required_error"),
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
        manualWhiteOrientation: state.manualWhiteOrientation,
        manualBlackOrientation: state.manualBlackOrientation,
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
        extractError: resolveGradientCardExtractError(err),
        isExtracting: false,
      });
    }
  },

  submitSave: async (saveMode?: "merge" | "override") => {
    const state = get();
    if (!state.sessionId) {
      set({ saveError: tRuntime("mat_gradient_save_requires_extract_error") });
      return;
    }
    if (!state.materialName.trim()) {
      set({ saveError: tRuntime("mat_gradient_save_name_required_error") });
      return;
    }

    set({ isSaving: true, saveError: null, saveSuccess: null });
    try {
      const response = await saveGradientCardMaterial({
        sessionId: state.sessionId,
        materialName: state.materialName.trim(),
        targetDirectoryName: state.verificationTargetDirectoryName,
        saveMode,
        // Brand is only honored when creating a new archive; the backend
        // ignores it when targetDirectoryName is provided.
        brand: state.verificationTargetDirectoryName
          ? null
          : state.materialBrand.trim() || null,
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
        saveError: resolveGradientCardSaveError(err),
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
