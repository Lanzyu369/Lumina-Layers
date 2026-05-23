import { create } from "zustand";

import {
  colorcheckerRelease,
  extractGradientCardStageA,
  rotateExtractorImage,
  saveGradientCardMaterial,
  type ColorcheckerDisplaySummary,
  type ExtractorRotationDirection,
} from "../api/extractor";
import { uploadImagePreview } from "../api/system";
import type {
  GradientCardMaterialSummary,
  OrientationRanking,
  SavedMaterialSummary,
  StageAFitSummary,
} from "../api/types";
import { tRuntime } from "../i18n/runtime";
import {
  anchorToOrientationLabel,
  type GradientCardAnchorCorner,
} from "../utils/gradientCardAnchor";
import { normalizeResourceUrl } from "../utils/resourceUrl";

export type ExtractorWorkflow = "legacy" | "single-stage";

/** Capture-origin tag forwarded to the gradient-card extractor.
 * 梯度卡输入图像来源标签：
 *   - ``raw``: camera/scanner output, no white-balance / restoration.
 *   - ``restored``: white-balanced / geometrically restored render
 *     (biases (E, k); the backend surfaces a strong warning).
 */
export type GradientCardImageSource = "raw" | "restored";

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
  activeCanvas: "white" | "black" | null;
  activeCornerIndex: number | null;
  nudgeStep: number;
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
  manualWhiteAnchor: GradientCardAnchorCorner | null;
  manualBlackAnchor: GradientCardAnchorCorner | null;
  imageSource: GradientCardImageSource;
  colorchecker_enabled: boolean;
  colorchecker_phase: "calibrating" | "confirming" | "done" | null;
  colorchecker_target: "white" | "black" | null;
  calibratedPreviewUrl: string | null;
  pendingColorcheckerFileId: string | null;
  pendingColorcheckerFullWidth: number | null;
  pendingColorcheckerFullHeight: number | null;
  pendingColorcheckerPreviewWidth: number | null;
  pendingColorcheckerPreviewHeight: number | null;
  whiteColorcheckerFileId: string | null;
  blackColorcheckerFileId: string | null;
  originalWhitePreviewUrl: string | null;
  colorcheckerSummary: ColorcheckerDisplaySummary | null;
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
  setWhiteImageFile: (file: File | null) => Promise<void>;
  setBlackImageFile: (file: File | null) => Promise<void>;
  setWhiteImageNaturalSize: (width: number, height: number) => void;
  setBlackImageNaturalSize: (width: number, height: number) => void;
  rotateWhiteImage: (direction: ExtractorRotationDirection) => Promise<void>;
  rotateBlackImage: (direction: ExtractorRotationDirection) => Promise<void>;
  addWhiteCornerPoint: (point: CornerPoint) => void;
  addBlackCornerPoint: (point: CornerPoint) => void;
  clearWhiteCornerPoints: () => void;
  clearBlackCornerPoints: () => void;
  setActiveCanvasAndCorner: (canvas: "white" | "black" | null, index: number | null) => void;
  setNudgeStep: (value: number) => void;
  nudgeActiveCorner: (dx: number, dy: number) => void;
  setMaterialName: (value: string) => void;
  setMaterialBrand: (value: string) => void;
  setManualWhiteAnchor: (value: GradientCardAnchorCorner | null) => void;
  setManualBlackAnchor: (value: GradientCardAnchorCorner | null) => void;
  setImageSource: (value: GradientCardImageSource) => void;
  setColorcheckerEnabled: (value: boolean) => void;
  openColorcheckerDialog: (target?: "white" | "black") => void;
  receiveCalibratedFromCC: (
    previewUrl: string,
    fullFileId: string,
    summary?: ColorcheckerDisplaySummary | null,
    dimensions?: {
      fullWidth: number;
      fullHeight: number;
      previewWidth: number;
      previewHeight: number;
    },
    context?: {
      imageFile: File | null;
      target?: "white" | "black" | null;
    },
  ) => void;
  confirmCalibrated: () => void;
  rejectCalibrated: () => void;
  closeColorcheckerDialog: () => void;
  startMaterialVerification: (target: {
    materialName: string;
    directoryName: string;
    verificationCount?: number | null;
  }) => void;
  clearMaterialVerification: () => void;
  submitExtract: () => Promise<void>;
  submitSave: (saveMode?: "merge" | "override") => Promise<void>;
  clearExtractError: () => void;
  clearSaveMessages: () => void;
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

function releaseColorcheckerArtifact(fileId: string | null): void {
  if (!fileId) return;
  void colorcheckerRelease(fileId).catch(() => {});
}

function isColorcheckerBusy(phase: SingleStageState["colorchecker_phase"]): boolean {
  return phase === "calibrating" || phase === "confirming";
}

const BACKEND_PREVIEW_EXTENSIONS = new Set([
  ".heic", ".heif",
  ".dng", ".cr2", ".cr3", ".nef", ".arw",
  ".orf", ".rw2", ".raf", ".pef", ".srw", ".raw",
]);

function getLowerFileExtension(file: File): string {
  const index = file.name.lastIndexOf(".");
  return index >= 0 ? file.name.slice(index).toLowerCase() : "";
}

function requiresBackendPreview(file: File | null): boolean {
  if (!file) {
    return false;
  }
  const mimeType = file.type.toLowerCase();
  return (
    BACKEND_PREVIEW_EXTENSIONS.has(getLowerFileExtension(file)) ||
    mimeType === "image/heic" ||
    mimeType === "image/heif"
  );
}

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
const GRADIENT_CARD_HEIC_DECODE_DETAIL_PREFIX = "HEIC/HEIF 文件解码失败:";

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
  if (detail.startsWith(GRADIENT_CARD_HEIC_DECODE_DETAIL_PREFIX)) {
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

function resolveGradientCardPreviewError(err: unknown): string {
  const detail = extractErrorDetail(err);
  if (detail) {
    return resolveKnownGradientCardDetail(detail) ?? detail;
  }
  return tRuntime("mat_gradient_invalid_image_error");
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
  activeCanvas: null,
  activeCornerIndex: null,
  nudgeStep: 3,
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
  manualWhiteAnchor: null,
  manualBlackAnchor: null,
  imageSource: "raw",
  colorchecker_enabled: false,
  colorchecker_phase: null,
  colorchecker_target: null,
  calibratedPreviewUrl: null,
  pendingColorcheckerFileId: null,
  pendingColorcheckerFullWidth: null,
  pendingColorcheckerFullHeight: null,
  pendingColorcheckerPreviewWidth: null,
  pendingColorcheckerPreviewHeight: null,
  whiteColorcheckerFileId: null,
  blackColorcheckerFileId: null,
  originalWhitePreviewUrl: null,
  colorcheckerSummary: null,
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

  setWhiteImageFile: async (file: File | null) => {
    const previousState = get();
    const previousUrl = previousState.whiteImagePreviewUrl;
    const useBackendPreview = requiresBackendPreview(file);
    const ccEnabled = previousState.colorchecker_enabled;
    revokePreviewUrl(previousUrl);
    releaseColorcheckerArtifact(previousState.whiteColorcheckerFileId);
    releaseColorcheckerArtifact(previousState.pendingColorcheckerFileId);

    if (ccEnabled && file) {
      // CC mode: hold off on setting the active preview — let calibration
      // produce the corrected image first.
      set({
        whiteImageFile: file,
        whiteImagePreviewUrl: null,
        whiteImageNaturalWidth: null,
        whiteImageNaturalHeight: null,
        whiteCornerPoints: [],
        activeCanvas: null,
        activeCornerIndex: null,
        colorchecker_phase: "calibrating",
        colorchecker_target: "white",
        calibratedPreviewUrl: null,
        pendingColorcheckerFileId: null,
        pendingColorcheckerFullWidth: null,
        pendingColorcheckerFullHeight: null,
        pendingColorcheckerPreviewWidth: null,
        pendingColorcheckerPreviewHeight: null,
        whiteColorcheckerFileId: null,
        colorcheckerSummary: null,
        imageSource: "raw",
        ...RESULT_RESET_STATE,
      });
      uploadImagePreview(file)
        .then(({ preview_url }) => {
          if (get().whiteImageFile !== file) {
            return;
          }
          set({ originalWhitePreviewUrl: normalizeResourceUrl(preview_url) });
        })
        .catch(() => {});
      return;
    }

    set({
      whiteImageFile: file,
      whiteImagePreviewUrl: useBackendPreview ? null : createPreviewUrl(file),
      whiteImageNaturalWidth: null,
      whiteImageNaturalHeight: null,
      whiteCornerPoints: [],
      activeCanvas: null,
      activeCornerIndex: null,
      imageSource: "raw",
      whiteColorcheckerFileId: null,
      pendingColorcheckerFileId: null,
      pendingColorcheckerFullWidth: null,
      pendingColorcheckerFullHeight: null,
      pendingColorcheckerPreviewWidth: null,
      pendingColorcheckerPreviewHeight: null,
      ...RESULT_RESET_STATE,
    });
    if (!file || !useBackendPreview) {
      return;
    }
    try {
      const response = await uploadImagePreview(file);
      const previewUrl = normalizeResourceUrl(response.preview_url);
      if (!previewUrl) {
        throw new Error("Missing preview URL");
      }
      if (get().whiteImageFile !== file) {
        return;
      }
      set({
        whiteImagePreviewUrl: previewUrl,
        whiteImageNaturalWidth: response.width,
        whiteImageNaturalHeight: response.height,
        extractError: null,
      });
    } catch (err) {
      if (get().whiteImageFile !== file) {
        return;
      }
      set({
        whiteImagePreviewUrl: null,
        whiteImageNaturalWidth: null,
        whiteImageNaturalHeight: null,
        extractError: resolveGradientCardPreviewError(err),
      });
    }
  },

  setBlackImageFile: async (file: File | null) => {
    const previousState = get();
    const previousUrl = previousState.blackImagePreviewUrl;
    const useBackendPreview = requiresBackendPreview(file);
    const ccEnabled = previousState.colorchecker_enabled;
    revokePreviewUrl(previousUrl);
    releaseColorcheckerArtifact(previousState.blackColorcheckerFileId);
    releaseColorcheckerArtifact(previousState.pendingColorcheckerFileId);

    if (ccEnabled && file) {
      set({
        blackImageFile: file,
        blackImagePreviewUrl: null,
        blackImageNaturalWidth: null,
        blackImageNaturalHeight: null,
        blackCornerPoints: [],
        activeCanvas: null,
        activeCornerIndex: null,
        colorchecker_phase: "calibrating",
        colorchecker_target: "black",
        calibratedPreviewUrl: null,
        pendingColorcheckerFileId: null,
        pendingColorcheckerFullWidth: null,
        pendingColorcheckerFullHeight: null,
        pendingColorcheckerPreviewWidth: null,
        pendingColorcheckerPreviewHeight: null,
        blackColorcheckerFileId: null,
        colorcheckerSummary: null,
        imageSource: "raw",
        ...RESULT_RESET_STATE,
      });
      uploadImagePreview(file)
        .then(({ preview_url }) => {
          if (get().blackImageFile !== file) {
            return;
          }
          set({ originalWhitePreviewUrl: normalizeResourceUrl(preview_url) });
        })
        .catch(() => {});
      return;
    }

    set({
      blackImageFile: file,
      blackImagePreviewUrl: useBackendPreview ? null : createPreviewUrl(file),
      blackImageNaturalWidth: null,
      blackImageNaturalHeight: null,
      blackCornerPoints: [],
      activeCanvas: null,
      activeCornerIndex: null,
      imageSource: "raw",
      blackColorcheckerFileId: null,
      pendingColorcheckerFileId: null,
      pendingColorcheckerFullWidth: null,
      pendingColorcheckerFullHeight: null,
      pendingColorcheckerPreviewWidth: null,
      pendingColorcheckerPreviewHeight: null,
      ...RESULT_RESET_STATE,
    });
    if (!file || !useBackendPreview) {
      return;
    }
    try {
      const response = await uploadImagePreview(file);
      const previewUrl = normalizeResourceUrl(response.preview_url);
      if (!previewUrl) {
        throw new Error("Missing preview URL");
      }
      if (get().blackImageFile !== file) {
        return;
      }
      set({
        blackImagePreviewUrl: previewUrl,
        blackImageNaturalWidth: response.width,
        blackImageNaturalHeight: response.height,
        extractError: null,
      });
    } catch (err) {
      if (get().blackImageFile !== file) {
        return;
      }
      set({
        blackImagePreviewUrl: null,
        blackImageNaturalWidth: null,
        blackImageNaturalHeight: null,
        extractError: resolveGradientCardPreviewError(err),
      });
    }
  },

  setWhiteImageNaturalSize: (width: number, height: number) =>
    set({ whiteImageNaturalWidth: width, whiteImageNaturalHeight: height }),

  setBlackImageNaturalSize: (width: number, height: number) =>
    set({ blackImageNaturalWidth: width, blackImageNaturalHeight: height }),

  rotateWhiteImage: async (direction: ExtractorRotationDirection) => {
    const { whiteImageFile, whiteImagePreviewUrl } = get();
    if (!whiteImageFile) {
      return;
    }
    const initial = get();
    releaseColorcheckerArtifact(initial.whiteColorcheckerFileId);
    releaseColorcheckerArtifact(initial.pendingColorcheckerFileId);
    set({
      isRotatingWhite: true,
      extractError: null,
      saveError: null,
      saveSuccess: null,
      colorchecker_phase: null,
      colorchecker_target: null,
      calibratedPreviewUrl: null,
      pendingColorcheckerFileId: null,
      pendingColorcheckerFullWidth: null,
      pendingColorcheckerFullHeight: null,
      pendingColorcheckerPreviewWidth: null,
      pendingColorcheckerPreviewHeight: null,
      whiteColorcheckerFileId: null,
      colorcheckerSummary: null,
      imageSource: "raw",
    });
    try {
      const response = await rotateExtractorImage(
        whiteImageFile,
        whiteImageFile.name,
        direction,
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
        activeCanvas: null,
        activeCornerIndex: null,
        isRotatingWhite: false,
        whiteColorcheckerFileId: null,
        pendingColorcheckerFileId: null,
        pendingColorcheckerFullWidth: null,
        pendingColorcheckerFullHeight: null,
        pendingColorcheckerPreviewWidth: null,
        pendingColorcheckerPreviewHeight: null,
        ...RESULT_RESET_STATE,
      });
    } catch (err) {
      const current = get();
      set({
        extractError: resolveGradientCardRotationError(err, "white"),
        isRotatingWhite: false,
        colorchecker_phase: null,
        whiteColorcheckerFileId: null,
        pendingColorcheckerFileId: null,
        pendingColorcheckerFullWidth: null,
        pendingColorcheckerFullHeight: null,
        pendingColorcheckerPreviewWidth: null,
        pendingColorcheckerPreviewHeight: null,
        colorcheckerSummary: null,
        imageSource: "raw",
      });
    }
  },

  rotateBlackImage: async (direction: ExtractorRotationDirection) => {
    const { blackImageFile, blackImagePreviewUrl } = get();
    if (!blackImageFile) {
      return;
    }
    const initial = get();
    releaseColorcheckerArtifact(initial.blackColorcheckerFileId);
    releaseColorcheckerArtifact(initial.pendingColorcheckerFileId);
    set({
      isRotatingBlack: true,
      extractError: null,
      saveError: null,
      saveSuccess: null,
      colorchecker_phase: null,
      colorchecker_target: null,
      calibratedPreviewUrl: null,
      pendingColorcheckerFileId: null,
      pendingColorcheckerFullWidth: null,
      pendingColorcheckerFullHeight: null,
      pendingColorcheckerPreviewWidth: null,
      pendingColorcheckerPreviewHeight: null,
      blackColorcheckerFileId: null,
      colorcheckerSummary: null,
      imageSource: "raw",
    });
    try {
      const response = await rotateExtractorImage(
        blackImageFile,
        blackImageFile.name,
        direction,
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
        activeCanvas: null,
        activeCornerIndex: null,
        isRotatingBlack: false,
        blackColorcheckerFileId: null,
        pendingColorcheckerFileId: null,
        pendingColorcheckerFullWidth: null,
        pendingColorcheckerFullHeight: null,
        pendingColorcheckerPreviewWidth: null,
        pendingColorcheckerPreviewHeight: null,
        ...RESULT_RESET_STATE,
      });
    } catch (err) {
      const current = get();
      set({
        extractError: resolveGradientCardRotationError(err, "black"),
        isRotatingBlack: false,
        colorchecker_phase: null,
        blackColorcheckerFileId: null,
        pendingColorcheckerFileId: null,
        pendingColorcheckerFullWidth: null,
        pendingColorcheckerFullHeight: null,
        pendingColorcheckerPreviewWidth: null,
        pendingColorcheckerPreviewHeight: null,
        colorcheckerSummary: null,
        imageSource: "raw",
      });
    }
  },

  addWhiteCornerPoint: (point: CornerPoint) => {
    const { whiteCornerPoints } = get();
    if (whiteCornerPoints.length >= 4) {
      return;
    }
    const nextPoints = [...whiteCornerPoints, point];
    set({
      whiteCornerPoints: nextPoints,
      activeCanvas: "white",
      activeCornerIndex: nextPoints.length - 1,
      ...RESULT_RESET_STATE,
    });
  },

  addBlackCornerPoint: (point: CornerPoint) => {
    const { blackCornerPoints } = get();
    if (blackCornerPoints.length >= 4) {
      return;
    }
    const nextPoints = [...blackCornerPoints, point];
    set({
      blackCornerPoints: nextPoints,
      activeCanvas: "black",
      activeCornerIndex: nextPoints.length - 1,
      ...RESULT_RESET_STATE,
    });
  },

  clearWhiteCornerPoints: () =>
    set({ whiteCornerPoints: [], activeCanvas: null, activeCornerIndex: null, ...RESULT_RESET_STATE }),

  clearBlackCornerPoints: () =>
    set({ blackCornerPoints: [], activeCanvas: null, activeCornerIndex: null, ...RESULT_RESET_STATE }),

  setActiveCanvasAndCorner: (canvas: "white" | "black" | null, index: number | null) => {
    if (canvas === null || index === null) {
      set({ activeCanvas: null, activeCornerIndex: null });
      return;
    }
    const { whiteCornerPoints, blackCornerPoints } = get();
    const points = canvas === "white" ? whiteCornerPoints : blackCornerPoints;
    if (index >= 0 && index < points.length) {
      set({ activeCanvas: canvas, activeCornerIndex: index });
    }
  },

  setNudgeStep: (value: number) => {
    const clamped = Math.max(1, Math.min(10, Math.round(value)));
    set({ nudgeStep: clamped });
  },

  nudgeActiveCorner: (dx: number, dy: number) => {
    const state = get();
    if (
      state.activeCanvas === null ||
      state.activeCornerIndex === null ||
      state.activeCornerIndex < 0
    ) {
      return;
    }

    const isWhite = state.activeCanvas === "white";
    const points = isWhite ? state.whiteCornerPoints : state.blackCornerPoints;
    if (state.activeCornerIndex >= points.length) {
      return;
    }

    const [x, y] = points[state.activeCornerIndex];
    let nx = x + dx * state.nudgeStep;
    let ny = y + dy * state.nudgeStep;

    const width = isWhite ? state.whiteImageNaturalWidth : state.blackImageNaturalWidth;
    const height = isWhite ? state.whiteImageNaturalHeight : state.blackImageNaturalHeight;

    if (width && width > 0) {
      nx = Math.max(0, Math.min(width - 1, nx));
    } else {
      nx = Math.max(0, nx);
    }
    if (height && height > 0) {
      ny = Math.max(0, Math.min(height - 1, ny));
    } else {
      ny = Math.max(0, ny);
    }

    const nextPoints = points.map((pt, i) =>
      i === state.activeCornerIndex ? ([nx, ny] as CornerPoint) : pt,
    );

    if (isWhite) {
      set({ whiteCornerPoints: nextPoints, ...RESULT_RESET_STATE });
    } else {
      set({ blackCornerPoints: nextPoints, ...RESULT_RESET_STATE });
    }
  },

  setMaterialName: (value: string) =>
    set({ materialName: value, saveError: null, saveSuccess: null }),

  setMaterialBrand: (value: string) =>
    set({ materialBrand: value, saveError: null, saveSuccess: null }),

  setManualWhiteAnchor: (value: GradientCardAnchorCorner | null) =>
    set({ manualWhiteAnchor: value, extractError: null }),

  setManualBlackAnchor: (value: GradientCardAnchorCorner | null) =>
    set({ manualBlackAnchor: value, extractError: null }),

  setImageSource: (value: GradientCardImageSource) =>
    set({ imageSource: value, extractError: null }),

  setColorcheckerEnabled: (value: boolean) => {
    const state = get();
    const clearWhiteRestored = !value && Boolean(state.whiteColorcheckerFileId);
    const clearBlackRestored = !value && Boolean(state.blackColorcheckerFileId);
    const resetToRaw =
      !value &&
      state.colorchecker_phase !== "done" &&
      state.pendingColorcheckerFileId === null &&
      state.whiteColorcheckerFileId === null &&
      state.blackColorcheckerFileId === null;
    if (!value) {
      releaseColorcheckerArtifact(state.pendingColorcheckerFileId);
      releaseColorcheckerArtifact(state.whiteColorcheckerFileId);
      releaseColorcheckerArtifact(state.blackColorcheckerFileId);
    }
    const restoreWhitePreview =
      !value && state.whiteColorcheckerFileId
        ? requiresBackendPreview(state.whiteImageFile)
          ? null
          : createPreviewUrl(state.whiteImageFile)
        : state.whiteImagePreviewUrl;
    const restoreBlackPreview =
      !value && state.blackColorcheckerFileId
        ? requiresBackendPreview(state.blackImageFile)
          ? null
          : createPreviewUrl(state.blackImageFile)
        : state.blackImagePreviewUrl;
    set({
      colorchecker_enabled: value,
      colorchecker_phase: null,
      colorchecker_target: null,
      calibratedPreviewUrl: null,
      pendingColorcheckerFileId: null,
      pendingColorcheckerFullWidth: null,
      pendingColorcheckerFullHeight: null,
      pendingColorcheckerPreviewWidth: null,
      pendingColorcheckerPreviewHeight: null,
      whiteColorcheckerFileId: value ? state.whiteColorcheckerFileId : null,
      blackColorcheckerFileId: value ? state.blackColorcheckerFileId : null,
      whiteImagePreviewUrl: restoreWhitePreview,
      blackImagePreviewUrl: restoreBlackPreview,
      whiteImageNaturalWidth: !value && state.whiteColorcheckerFileId ? null : state.whiteImageNaturalWidth,
      whiteImageNaturalHeight: !value && state.whiteColorcheckerFileId ? null : state.whiteImageNaturalHeight,
      blackImageNaturalWidth: !value && state.blackColorcheckerFileId ? null : state.blackImageNaturalWidth,
      blackImageNaturalHeight: !value && state.blackColorcheckerFileId ? null : state.blackImageNaturalHeight,
      whiteCornerPoints: clearWhiteRestored ? [] : state.whiteCornerPoints,
      blackCornerPoints: clearBlackRestored ? [] : state.blackCornerPoints,
      activeCanvas: clearWhiteRestored || clearBlackRestored ? null : state.activeCanvas,
      activeCornerIndex: clearWhiteRestored || clearBlackRestored ? null : state.activeCornerIndex,
      originalWhitePreviewUrl: null,
      colorcheckerSummary: null,
      ...(!value || resetToRaw ? { imageSource: "raw" as const } : {}),
    });
    if (!value && state.whiteColorcheckerFileId && requiresBackendPreview(state.whiteImageFile) && state.whiteImageFile) {
      const sourceFile = state.whiteImageFile;
      uploadImagePreview(sourceFile)
        .then(({ preview_url, width, height }) => {
          if (get().whiteImageFile !== sourceFile || get().colorchecker_enabled) return;
          set({
            whiteImagePreviewUrl: normalizeResourceUrl(preview_url),
            whiteImageNaturalWidth: width,
            whiteImageNaturalHeight: height,
          });
        })
        .catch(() => {});
    }
    if (!value && state.blackColorcheckerFileId && requiresBackendPreview(state.blackImageFile) && state.blackImageFile) {
      const sourceFile = state.blackImageFile;
      uploadImagePreview(sourceFile)
        .then(({ preview_url, width, height }) => {
          if (get().blackImageFile !== sourceFile || get().colorchecker_enabled) return;
          set({
            blackImagePreviewUrl: normalizeResourceUrl(preview_url),
            blackImageNaturalWidth: width,
            blackImageNaturalHeight: height,
          });
        })
        .catch(() => {});
    }
  },

  openColorcheckerDialog: (target?: "white" | "black") => {
    const state = get();
    const nextTarget = target ?? state.colorchecker_target ?? "white";
    const sourceFile =
      nextTarget === "black" ? state.blackImageFile : state.whiteImageFile;
    const sourcePreview =
      nextTarget === "black"
        ? state.blackImagePreviewUrl
        : state.whiteImagePreviewUrl;
    if (!sourceFile) return;
    releaseColorcheckerArtifact(state.pendingColorcheckerFileId);
    set({
      colorchecker_phase: "calibrating",
      colorchecker_target: nextTarget,
      calibratedPreviewUrl: null,
      pendingColorcheckerFileId: null,
      pendingColorcheckerFullWidth: null,
      pendingColorcheckerFullHeight: null,
      pendingColorcheckerPreviewWidth: null,
      pendingColorcheckerPreviewHeight: null,
      colorcheckerSummary: null,
      originalWhitePreviewUrl: null,
    });
    uploadImagePreview(sourceFile)
      .then(({ preview_url }) => {
        const current = get();
        const currentSource =
          nextTarget === "black" ? current.blackImageFile : current.whiteImageFile;
        if (currentSource !== sourceFile || current.colorchecker_target !== nextTarget) {
          return;
        }
        set({ originalWhitePreviewUrl: normalizeResourceUrl(preview_url) });
      })
      .catch(() => {
        set({ originalWhitePreviewUrl: sourcePreview ?? createPreviewUrl(sourceFile) });
      });
  },

  receiveCalibratedFromCC: (
    previewUrl: string,
    fullFileId: string,
    summary?: ColorcheckerDisplaySummary | null,
    dimensions?: {
      fullWidth: number;
      fullHeight: number;
      previewWidth: number;
      previewHeight: number;
    },
    context?: {
      imageFile: File | null;
      target?: "white" | "black" | null;
    },
  ) => {
    const state = get();
    const target = context?.target ?? state.colorchecker_target;
    const targetFile =
      target === "black" ? state.blackImageFile : state.whiteImageFile;
    if (
      !state.colorchecker_enabled ||
      state.colorchecker_phase !== "calibrating" ||
      state.isRotatingWhite ||
      state.isRotatingBlack ||
      state.colorchecker_target !== target ||
      (context?.imageFile && targetFile !== context.imageFile)
    ) {
      releaseColorcheckerArtifact(fullFileId);
      return;
    }
    const previousId = state.pendingColorcheckerFileId;
    if (previousId && previousId !== fullFileId) {
      releaseColorcheckerArtifact(previousId);
    }
    const resolvedUrl = normalizeResourceUrl(previewUrl) ?? previewUrl;
    set({
      colorchecker_phase: "confirming",
      pendingColorcheckerFileId: fullFileId,
      pendingColorcheckerFullWidth: dimensions?.fullWidth ?? null,
      pendingColorcheckerFullHeight: dimensions?.fullHeight ?? null,
      pendingColorcheckerPreviewWidth: dimensions?.previewWidth ?? null,
      pendingColorcheckerPreviewHeight: dimensions?.previewHeight ?? null,
      calibratedPreviewUrl: resolvedUrl,
      colorcheckerSummary: summary ?? null,
    });
  },

  confirmCalibrated: () => {
    const {
      calibratedPreviewUrl,
      pendingColorcheckerFileId,
      pendingColorcheckerPreviewWidth,
      pendingColorcheckerPreviewHeight,
      colorchecker_target,
      whiteColorcheckerFileId,
      blackColorcheckerFileId,
    } = get();
    if (!calibratedPreviewUrl || !pendingColorcheckerFileId) return;
    const replacingId =
      colorchecker_target === "black"
        ? blackColorcheckerFileId
        : whiteColorcheckerFileId;
    if (replacingId && replacingId !== pendingColorcheckerFileId) {
      releaseColorcheckerArtifact(replacingId);
    }
    const imagePatch =
      colorchecker_target === "black"
        ? {
            blackImagePreviewUrl: calibratedPreviewUrl,
            blackCornerPoints: [],
            blackColorcheckerFileId: pendingColorcheckerFileId,
          }
        : {
            whiteImagePreviewUrl: calibratedPreviewUrl,
            whiteCornerPoints: [],
            whiteColorcheckerFileId: pendingColorcheckerFileId,
          };
    const img = new Image();
    set({ imageSource: "restored" });
    const applyAcceptedPreview = (dimensions?: { width: number; height: number }) => {
      const current = get();
      if (
        current.colorchecker_phase !== "confirming" ||
        current.colorchecker_target !== colorchecker_target ||
        current.pendingColorcheckerFileId !== pendingColorcheckerFileId ||
        current.calibratedPreviewUrl !== calibratedPreviewUrl
      ) {
        return;
      }
      set({
        colorchecker_phase: "done",
        ...(colorchecker_target === "black"
          ? {
              ...imagePatch,
              blackImageNaturalWidth: pendingColorcheckerPreviewWidth ?? dimensions?.width ?? null,
              blackImageNaturalHeight: pendingColorcheckerPreviewHeight ?? dimensions?.height ?? null,
            }
          : {
              ...imagePatch,
              whiteImageNaturalWidth: pendingColorcheckerPreviewWidth ?? dimensions?.width ?? null,
              whiteImageNaturalHeight: pendingColorcheckerPreviewHeight ?? dimensions?.height ?? null,
            }),
        pendingColorcheckerFileId: null,
        pendingColorcheckerFullWidth: null,
        pendingColorcheckerFullHeight: null,
        pendingColorcheckerPreviewWidth: null,
        pendingColorcheckerPreviewHeight: null,
        activeCanvas: null,
        activeCornerIndex: null,
      });
    };
    img.onload = () => {
      applyAcceptedPreview({
        width: img.naturalWidth,
        height: img.naturalHeight,
      });
    };
    img.onerror = () => {
      applyAcceptedPreview();
    };
    img.src = calibratedPreviewUrl;
  },

  rejectCalibrated: () => {
    releaseColorcheckerArtifact(get().pendingColorcheckerFileId);
    set({
      colorchecker_phase: "calibrating",
      calibratedPreviewUrl: null,
      pendingColorcheckerFileId: null,
      pendingColorcheckerFullWidth: null,
      pendingColorcheckerFullHeight: null,
      pendingColorcheckerPreviewWidth: null,
      pendingColorcheckerPreviewHeight: null,
      colorcheckerSummary: null,
    });
  },

  closeColorcheckerDialog: () => {
    const state = get();
    if (state.colorchecker_phase !== "done") {
      releaseColorcheckerArtifact(state.pendingColorcheckerFileId);
      set({
        colorchecker_phase: null,
        pendingColorcheckerFileId: null,
        pendingColorcheckerFullWidth: null,
        pendingColorcheckerFullHeight: null,
        pendingColorcheckerPreviewWidth: null,
        pendingColorcheckerPreviewHeight: null,
        calibratedPreviewUrl: null,
        colorcheckerSummary: null,
      });
      return;
    }
    const activeId =
      state.colorchecker_target === "black"
        ? state.blackColorcheckerFileId
        : state.whiteColorcheckerFileId;
    set({ colorchecker_phase: activeId ? "done" : null });
  },

  startMaterialVerification: ({
    materialName,
    directoryName,
    verificationCount,
  }) => {
    const {
      whiteImagePreviewUrl,
      blackImagePreviewUrl,
      whiteColorcheckerFileId,
      blackColorcheckerFileId,
      pendingColorcheckerFileId,
    } = get();
    revokePreviewUrl(whiteImagePreviewUrl);
    revokePreviewUrl(blackImagePreviewUrl);
    releaseColorcheckerArtifact(whiteColorcheckerFileId);
    releaseColorcheckerArtifact(blackColorcheckerFileId);
    releaseColorcheckerArtifact(pendingColorcheckerFileId);
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
      whiteColorcheckerFileId: null,
      blackColorcheckerFileId: null,
      pendingColorcheckerFileId: null,
      pendingColorcheckerFullWidth: null,
      pendingColorcheckerFullHeight: null,
      pendingColorcheckerPreviewWidth: null,
      pendingColorcheckerPreviewHeight: null,
      activeCanvas: null,
      activeCornerIndex: null,
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
    if (isColorcheckerBusy(state.colorchecker_phase)) {
      return;
    }
    const hasWhiteColorchecker = Boolean(state.whiteColorcheckerFileId);
    const hasBlackColorchecker = Boolean(state.blackColorcheckerFileId);
    if (hasWhiteColorchecker !== hasBlackColorchecker) {
      set({
        extractError: tRuntime(
          "mat_gradient_extract_colorchecker_pair_required_error",
        ),
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
        whiteImage: state.whiteColorcheckerFileId ? null : state.whiteImageFile,
        blackImage: state.blackColorcheckerFileId ? null : state.blackImageFile,
        whiteCornerPoints: state.whiteCornerPoints,
        blackCornerPoints: state.blackCornerPoints,
        whiteColorcheckerFileId: state.whiteColorcheckerFileId,
        blackColorcheckerFileId: state.blackColorcheckerFileId,
        whiteCornerPointsWidth: state.whiteColorcheckerFileId
          ? state.whiteImageNaturalWidth
          : null,
        whiteCornerPointsHeight: state.whiteColorcheckerFileId
          ? state.whiteImageNaturalHeight
          : null,
        blackCornerPointsWidth: state.blackColorcheckerFileId
          ? state.blackImageNaturalWidth
          : null,
        blackCornerPointsHeight: state.blackColorcheckerFileId
          ? state.blackImageNaturalHeight
          : null,
        manualWhiteOrientation: anchorToOrientationLabel(
          state.manualWhiteAnchor,
        ),
        manualBlackOrientation: anchorToOrientationLabel(
          state.manualBlackAnchor,
        ),
        imageSource: state.imageSource,
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
      const newVerificationCount = Number(response.material_summary?.verification_count ?? 0);
      const successMessage = newVerificationCount > 1
        ? tRuntime("mat_gradient_verification_saved_success", { count: newVerificationCount })
        : tRuntime("mat_gradient_material_saved_success");

      set({
        materialFileUrl: normalizeResourceUrl(response.material_file_url),
        savedStageAParamsUrl: normalizeResourceUrl(response.stage_a_params_url),
        savedMaterialSummary: response.material_summary ?? null,
        verificationTargetCount: Math.max(
          state.verificationTargetCount,
          newVerificationCount,
        ),
        saveSuccess: successMessage,
        isSaving: false,
      });
    } catch (err) {
      set({
        saveError: resolveGradientCardSaveError(err),
        isSaving: false,
      });
    }
  },

  clearExtractError: () => set({ extractError: null }),

  clearSaveMessages: () =>
    set({
      saveError: null,
      saveSuccess: null,
    }),

  clearMessages: () =>
    set({
      extractError: null,
      saveError: null,
      saveSuccess: null,
    }),
}));
