import { create } from "zustand";
import type { ExtractorColorMode, ExtractorPage, LutCardLayout } from "../api/types";
import {
  EXTRACTOR_EIGHT_COLOR_FULL_TOTAL_PAGES,
  ExtractorColorMode as ExtractorColorModeEnum,
  ExtractorPage as ExtractorPageEnum,
} from "../api/types";
import {
  confirmPalette,
  extractColors,
  manualFixCell,
  mergeEightColor,
  mergeFiveColorExtended,
  previewAutoWb,
  rotateExtractorImage,
  type ColorcheckerDisplaySummary,
} from "../api/extractor";
import type { ExtractorPaletteEntry } from "../api/types";
import { clampValue } from "./converter";
import { uploadImagePreview } from "../api/system";
import { normalizeResourceUrl } from "../utils/resourceUrl";

export const RAW_EXTENSIONS = new Set([
  ".dng",
  ".cr2",
  ".cr3",
  ".nef",
  ".arw",
  ".orf",
  ".rw2",
  ".raf",
  ".pef",
  ".srw",
  ".raw",
]);

export const ACCEPT_EXTRACTOR_FORMATS =
  "image/*," + Array.from(RAW_EXTENSIONS).join(",");

export function isRawFile(file: File): boolean {
  const ext = file.name.toLowerCase().slice(file.name.lastIndexOf("."));
  return RAW_EXTENSIONS.has(ext);
}

const COMPACT_EXTRACTOR_PAGES = new Set<ExtractorPage>([
  ExtractorPageEnum.PAGE_1,
  ExtractorPageEnum.PAGE_2,
]);

function normalizeCompactExtractorPage(page: ExtractorPage): ExtractorPage {
  return COMPACT_EXTRACTOR_PAGES.has(page) ? page : ExtractorPageEnum.PAGE_1;
}

function parseExtractorPageNumber(page: ExtractorPage): number {
  const match = /\d+/.exec(String(page));
  return match ? Number(match[0]) : 1;
}

function uniqueSortedPageNumbers(pageNumbers: number[]): number[] {
  return Array.from(
    new Set(
      pageNumbers.filter(
        (pageNumber) =>
          Number.isInteger(pageNumber) &&
          pageNumber >= 1 &&
          pageNumber <= EXTRACTOR_EIGHT_COLOR_FULL_TOTAL_PAGES,
      ),
    ),
  ).sort((a, b) => a - b);
}

// ========== State Interface ==========

export interface ExtractorState {
  // 图片
  imageFile: File | null;
  imagePreviewUrl: string | null;
  imageNaturalWidth: number | null;
  imageNaturalHeight: number | null;

  // 颜色模式与页码
  color_mode: ExtractorColorMode;
  page: ExtractorPage;
  eight_color_full_export: boolean;

  // 角点
  corner_points: Array<[number, number]>;

  // 角点微调（像素步长 1..10；当前被方向键/按钮作用的角点下标）
  nudge_step: number;
  active_corner_index: number | null;

  // 提取参数
  offset_x: number;
  offset_y: number;
  zoom: number;
  distortion: number;
  vignette_correction: boolean;
  auto_wb: boolean;
  colorchecker_enabled: boolean;
  colorchecker_phase: "calibrating" | "confirming" | "done" | null;
  calibratedImageFile: File | null;
  calibratedPreviewUrl: string | null;
  originalPreviewUrl: string | null;
  colorcheckerSummary: ColorcheckerDisplaySummary | null;

  // API 状态
  isLoading: boolean;
  error: string | null;
  session_id: string | null;

  // 提取结果
  lut_download_url: string | null;
  warp_view_url: string | null;
  lut_preview_url: string | null;
  lut_layout: LutCardLayout | null;

  // 手动修正
  manualFixLoading: boolean;
  manualFixError: string | null;

  // 8色双页状态
  page1Extracted: boolean;
  page2Extracted: boolean;
  extractedEightColorFullPages: number[];
  mergeLoading: boolean;
  mergeError: string | null;

  // 5 色扩展双页状态
  page1Extracted_5c: boolean;
  page2Extracted_5c: boolean;

  // 调色板与元数据（厂商、类型、默认板与确认状态）
  manufacturer: string;
  type: string;
  defaultPalette: ExtractorPaletteEntry[];
  paletteConfirmed: boolean;
  paletteConfirmLoading: boolean;
  paletteConfirmError: string | null;
}

// ========== Actions Interface ==========

export interface ExtractorActions {
  setImageFile: (file: File | null) => void;
  rotateImage: () => Promise<void>;
  setColorMode: (mode: ExtractorColorMode) => void;
  setPage: (page: ExtractorPage) => void;
  setEightColorFullExport: (enabled: boolean) => void;
  addCornerPoint: (point: [number, number]) => void;
  clearCornerPoints: () => void;
  setNudgeStep: (value: number) => void;
  setActiveCornerIndex: (index: number | null) => void;
  nudgeActiveCorner: (dx: number, dy: number) => void;
  setOffsetX: (value: number) => void;
  setOffsetY: (value: number) => void;
  setZoom: (value: number) => void;
  setDistortion: (value: number) => void;
  setVignetteCorrection: (value: boolean) => void;
  setAutoWb: (value: boolean) => Promise<void>;
  setColorcheckerEnabled: (value: boolean) => void;
  openColorcheckerDialog: () => void;
  receiveCalibratedFromCC: (
    imageUrl: string,
    summary?: ColorcheckerDisplaySummary | null,
  ) => void;
  confirmCalibrated: () => void;
  rejectCalibrated: () => void;
  closeColorcheckerDialog: () => void;
  setManufacturer: (value: string) => void;
  setType: (value: string) => void;
  submitExtract: () => Promise<void>;
  submitManualFix: (rowIndex: number, color: string) => Promise<void>;
  submitMerge: () => Promise<void>;
  setError: (error: string | null) => void;
  clearError: () => void;
  updatePaletteEntry: (
    index: number,
    entry: Partial<ExtractorPaletteEntry>,
  ) => void;
  submitConfirmPalette: () => Promise<void>;
}

// ========== Default State ==========

const DEFAULT_STATE: ExtractorState = {
  imageFile: null,
  imagePreviewUrl: null,
  imageNaturalWidth: null,
  imageNaturalHeight: null,
  color_mode: ExtractorColorModeEnum.FOUR_COLOR_RYBW,
  page: ExtractorPageEnum.PAGE_1,
  eight_color_full_export: false,
  corner_points: [],
  nudge_step: 3,
  active_corner_index: null,
  offset_x: 0,
  offset_y: 0,
  zoom: 1.0,
  distortion: 0.0,
  vignette_correction: false,
  auto_wb: false,
  colorchecker_enabled: false,
  colorchecker_phase: null,
  calibratedImageFile: null,
  calibratedPreviewUrl: null,
  originalPreviewUrl: null,
  colorcheckerSummary: null,
  isLoading: false,
  error: null,
  session_id: null,
  lut_download_url: null,
  warp_view_url: null,
  lut_preview_url: null,
  lut_layout: null,
  manualFixLoading: false,
  manualFixError: null,
  page1Extracted: false,
  page2Extracted: false,
  extractedEightColorFullPages: [],
  mergeLoading: false,
  mergeError: null,
  page1Extracted_5c: false,
  page2Extracted_5c: false,
  manufacturer: "",
  type: "",
  defaultPalette: [],
  paletteConfirmed: false,
  paletteConfirmLoading: false,
  paletteConfirmError: null,
};

// ========== Store ==========

export const useExtractorStore = create<ExtractorState & ExtractorActions>(
  (set, get) => ({
    ...DEFAULT_STATE,

    setImageFile: (file: File | null) => {
      // Revoke previous blob URL to avoid memory leaks
      const prev = get().imagePreviewUrl;
      if (prev && prev.startsWith("blob:")) {
        URL.revokeObjectURL(prev);
      }

      const correctionDefaults = {
        offset_x: DEFAULT_STATE.offset_x,
        offset_y: DEFAULT_STATE.offset_y,
        zoom: DEFAULT_STATE.zoom,
        distortion: DEFAULT_STATE.distortion,
        vignette_correction: DEFAULT_STATE.vignette_correction,
      } as const;

      if (!file) {
        set({
          imageFile: null,
          imagePreviewUrl: null,
          imageNaturalWidth: null,
          imageNaturalHeight: null,
          corner_points: [],
          active_corner_index: null,
          session_id: null,
          lut_download_url: null,
          warp_view_url: null,
          lut_preview_url: null,
          lut_layout: null,
          defaultPalette: [],
          paletteConfirmed: false,
          paletteConfirmError: null,
          auto_wb: false,
          colorchecker_enabled: false,
          colorchecker_phase: null,
          calibratedImageFile: null,
          calibratedPreviewUrl: null,
          originalPreviewUrl: null,
          colorcheckerSummary: null,
          ...correctionDefaults,
        });
        return;
      }

      const ccEnabled = get().colorchecker_enabled;

      // Shared reset fields for both CC-on and CC-off paths
      const resetFields = {
        corner_points: [] as Array<[number, number]>,
        active_corner_index: null,
        session_id: null,
        lut_download_url: null,
        warp_view_url: null,
        lut_preview_url: null,
        lut_layout: null,
        defaultPalette: [] as ExtractorPaletteEntry[],
        paletteConfirmed: false,
        paletteConfirmError: null,
        auto_wb: false,
        colorchecker_enabled: ccEnabled,
        calibratedImageFile: null,
        calibratedPreviewUrl: null,
        originalPreviewUrl: null,
        colorcheckerSummary: null,
        ...correctionDefaults,
      } as const;

      // --- CC enabled: store file, skip active preview, open dialog ---
      // We still generate a preview in the background for the before/after
      // comparison shown after calibration completes.
      if (ccEnabled) {
        set({
          imageFile: file,
          imagePreviewUrl: null,
          imageNaturalWidth: null,
          imageNaturalHeight: null,
          colorchecker_phase: "calibrating",
          ...resetFields,
        });
        if (isRawFile(file)) {
          uploadImagePreview(file)
            .then(({ preview_url }) => {
              set({ originalPreviewUrl: preview_url });
            })
            .catch(() => {});
        } else {
          set({ originalPreviewUrl: URL.createObjectURL(file) });
        }
        return;
      }

      // --- Normal flow (CC off) ---
      if (isRawFile(file)) {
        set({
          imageFile: file,
          imagePreviewUrl: null,
          imageNaturalWidth: null,
          imageNaturalHeight: null,
          colorchecker_phase: null,
          ...resetFields,
        });
        uploadImagePreview(file)
          .then(({ preview_url, width, height }) => {
            set({
              imagePreviewUrl: preview_url,
              imageNaturalWidth: width,
              imageNaturalHeight: height,
            });
          })
          .catch(() => {
            set({ error: "RAW 图片预览失败，请检查后端是否安装 rawpy" });
          });
        return;
      }

      const previewUrl = URL.createObjectURL(file);

      // Load image to get natural dimensions
      const img = new Image();
      img.onload = () => {
        set({
          imageNaturalWidth: img.naturalWidth,
          imageNaturalHeight: img.naturalHeight,
        });
      };
      img.src = previewUrl;

      set({
        imageFile: file,
        imagePreviewUrl: previewUrl,
        imageNaturalWidth: null,
        imageNaturalHeight: null,
        colorchecker_phase: null,
        ...resetFields,
      });
    },

    rotateImage: async () => {
      const { imageFile, imagePreviewUrl } = get();
      if (!imageFile) return;

      set({ isLoading: true, error: null });
      try {
        const { preview_url, width, height } = await rotateExtractorImage(
          imageFile,
          imageFile.name,
        );

        // Fetch rotated image as blob to create a new File for subsequent extract calls
        const res = await fetch(preview_url);
        const blob = await res.blob();
        const baseName = imageFile.name.replace(/\.[^.]+$/, "");
        const rotatedFile = new File([blob], `${baseName}.png`, {
          type: "image/png",
        });

        // Revoke previous blob URL
        if (imagePreviewUrl && imagePreviewUrl.startsWith("blob:")) {
          URL.revokeObjectURL(imagePreviewUrl);
        }

        set({
          imageFile: rotatedFile,
          imagePreviewUrl: preview_url,
          imageNaturalWidth: width,
          imageNaturalHeight: height,
          corner_points: [],
          active_corner_index: null,
          isLoading: false,
          auto_wb: false,
          colorchecker_enabled: false,
          colorchecker_phase: null,
          calibratedImageFile: null,
          calibratedPreviewUrl: null,
          originalPreviewUrl: null,
          colorcheckerSummary: null,
        });
      } catch (err) {
        set({
          error: err instanceof Error ? err.message : "图片旋转失败",
          isLoading: false,
        });
      }
    },

    setColorMode: (mode: ExtractorColorMode) =>
      set((state) => ({
        color_mode: mode,
        page:
          mode === ExtractorColorModeEnum.EIGHT_COLOR
            ? state.page
            : normalizeCompactExtractorPage(state.page),
        eight_color_full_export:
          mode === ExtractorColorModeEnum.EIGHT_COLOR
            ? state.eight_color_full_export
            : false,
        page1Extracted: false,
        page2Extracted: false,
        extractedEightColorFullPages: [],
        page1Extracted_5c: false,
        page2Extracted_5c: false,
        mergeError: null,
        defaultPalette: [],
        paletteConfirmed: false,
        paletteConfirmError: null,
      })),

    setPage: (page: ExtractorPage) =>
      set((state) => ({
        page:
          state.color_mode === ExtractorColorModeEnum.EIGHT_COLOR &&
          state.eight_color_full_export
            ? page
            : normalizeCompactExtractorPage(page),
      })),

    setEightColorFullExport: (enabled: boolean) =>
      set((state) => ({
        eight_color_full_export:
          state.color_mode === ExtractorColorModeEnum.EIGHT_COLOR
            ? enabled
            : false,
        page: enabled ? state.page : normalizeCompactExtractorPage(state.page),
        page1Extracted: false,
        page2Extracted: false,
        extractedEightColorFullPages: [],
        mergeError: null,
        defaultPalette: [],
        paletteConfirmed: false,
        paletteConfirmError: null,
      })),

    addCornerPoint: (point: [number, number]) => {
      const { corner_points } = get();
      if (corner_points.length >= 4) return;
      const next = [...corner_points, point];
      set({
        corner_points: next,
        active_corner_index: next.length - 1,
      });
    },

    clearCornerPoints: () =>
      // Clearing corners implies the user wants to re-pick them, so we must
      // also drop the previous extraction preview URLs. Otherwise
      // ``ExtractorCanvas`` stays in Result mode (gated on
      // ``warp_view_url || lut_preview_url``) and the user cannot return to
      // the corner-picking canvas without refreshing the page.
      // 清除角点意味着用户想重新定位，必须同时清掉上一次提取的预览 URL。
      // 否则 ``ExtractorCanvas`` 会一直处于结果模式（由
      // ``warp_view_url || lut_preview_url`` 决定），用户只能刷新页面才能
      // 回到角点标定画布。
      set({
        corner_points: [],
        active_corner_index: null,
        warp_view_url: null,
        lut_preview_url: null,
        lut_layout: null,
        lut_download_url: null,
        session_id: null,
        error: null,
        manualFixError: null,
        defaultPalette: [],
        paletteConfirmed: false,
        paletteConfirmError: null,
      }),

    setNudgeStep: (value: number) => {
      const clamped = Math.max(1, Math.min(10, Math.round(value)));
      set({ nudge_step: clamped });
    },

    setActiveCornerIndex: (index: number | null) => {
      const { corner_points } = get();
      if (index === null) {
        set({ active_corner_index: null });
        return;
      }
      if (
        !Number.isInteger(index) ||
        index < 0 ||
        index >= corner_points.length
      ) {
        return;
      }
      set({ active_corner_index: index });
    },

    nudgeActiveCorner: (dx: number, dy: number) => {
      const {
        corner_points,
        active_corner_index,
        nudge_step,
        imageNaturalWidth,
        imageNaturalHeight,
      } = get();
      if (
        active_corner_index === null ||
        active_corner_index < 0 ||
        active_corner_index >= corner_points.length
      ) {
        return;
      }
      const [x, y] = corner_points[active_corner_index];
      let nx = x + dx * nudge_step;
      let ny = y + dy * nudge_step;
      if (imageNaturalWidth && imageNaturalWidth > 0) {
        nx = Math.max(0, Math.min(imageNaturalWidth - 1, nx));
      } else {
        nx = Math.max(0, nx);
      }
      if (imageNaturalHeight && imageNaturalHeight > 0) {
        ny = Math.max(0, Math.min(imageNaturalHeight - 1, ny));
      } else {
        ny = Math.max(0, ny);
      }
      const next = corner_points.map((pt, i) =>
        i === active_corner_index ? ([nx, ny] as [number, number]) : pt,
      );
      set({ corner_points: next });
    },

    setOffsetX: (value: number) =>
      set({ offset_x: clampValue(value, -30, 30) }),

    setOffsetY: (value: number) =>
      set({ offset_y: clampValue(value, -30, 30) }),

    setZoom: (value: number) => set({ zoom: clampValue(value, 0.8, 1.2) }),

    setDistortion: (value: number) =>
      set({ distortion: clampValue(value, -0.2, 0.2) }),

    setVignetteCorrection: (value: boolean) =>
      set({ vignette_correction: value }),

    setColorcheckerEnabled: (value: boolean) => {
      if (value) {
        const state = get();
        const fallbackPreview =
          state.originalPreviewUrl ??
          state.imagePreviewUrl ??
          (state.imageFile && !isRawFile(state.imageFile)
            ? URL.createObjectURL(state.imageFile)
            : null);
        set({
          colorchecker_enabled: true,
          colorchecker_phase: "calibrating",
          originalPreviewUrl: fallbackPreview,
          calibratedImageFile: null,
          calibratedPreviewUrl: null,
          colorcheckerSummary: null,
        });
        if (state.imageFile && isRawFile(state.imageFile) && !fallbackPreview) {
          uploadImagePreview(state.imageFile)
            .then(({ preview_url }) => {
              set({ originalPreviewUrl: preview_url });
            })
            .catch(() => {});
        }
      } else {
        set({
          colorchecker_enabled: false,
          colorchecker_phase: null,
          calibratedImageFile: null,
          calibratedPreviewUrl: null,
          originalPreviewUrl: null,
          colorcheckerSummary: null,
        });
      }
    },

    openColorcheckerDialog: () => {
      const state = get();
      if (!state.imageFile) return;
      const fallbackPreview =
        state.originalPreviewUrl ??
        state.imagePreviewUrl ??
        (isRawFile(state.imageFile) ? null : URL.createObjectURL(state.imageFile));
      set({
        colorchecker_phase: "calibrating",
        originalPreviewUrl: fallbackPreview,
      });
    },

    receiveCalibratedFromCC: (
      imageUrl: string,
      summary?: ColorcheckerDisplaySummary | null,
    ) => {
      // Convert calibrated URL to File, then enter "confirming" phase.
      // originalPreviewUrl was already set during image upload.
      const resolvedUrl = normalizeResourceUrl(imageUrl) ?? imageUrl;
      fetch(resolvedUrl)
        .then((r) => r.blob())
        .then((blob) => {
          const calibratedFile = new File([blob], "colorchecker_calibrated.png", {
            type: "image/png",
          });
          const previewUrl = URL.createObjectURL(calibratedFile);
          set({
            colorchecker_phase: "confirming",
            calibratedImageFile: calibratedFile,
            calibratedPreviewUrl: previewUrl,
            colorcheckerSummary: summary ?? null,
          });
        })
        .catch(() => {
          set({ error: "Failed to process calibrated image" });
        });
    },

    confirmCalibrated: () => {
      // User accepts the calibrated image — apply it as the active preview
      const { calibratedPreviewUrl } = get();
      if (!calibratedPreviewUrl) return;
      const img = new Image();
      img.onload = () => {
        set({
          colorchecker_phase: "done",
          imagePreviewUrl: calibratedPreviewUrl,
          imageNaturalWidth: img.naturalWidth,
          imageNaturalHeight: img.naturalHeight,
          corner_points: [],
          active_corner_index: null,
        });
      };
      img.onerror = () => {
        set({
          colorchecker_phase: "done",
          imagePreviewUrl: calibratedPreviewUrl,
          corner_points: [],
          active_corner_index: null,
        });
      };
      img.src = calibratedPreviewUrl;
    },

    rejectCalibrated: () => {
      // User rejects — discard calibrated image, go back to calibrating
      const { calibratedPreviewUrl } = get();
      if (calibratedPreviewUrl?.startsWith("blob:")) {
        URL.revokeObjectURL(calibratedPreviewUrl);
      }
      set({
        colorchecker_phase: "calibrating",
        calibratedImageFile: null,
        calibratedPreviewUrl: null,
        colorcheckerSummary: null,
      });
    },

    closeColorcheckerDialog: () => {
      set({ colorchecker_phase: get().calibratedImageFile ? "done" : null });
    },

    setAutoWb: async (value: boolean) => {
      const { imageFile, imagePreviewUrl, originalPreviewUrl } = get();
      if (!imageFile) {
        set({ auto_wb: value });
        return;
      }

      if (value) {
        // Enable auto white-balance: save original preview and fetch adjusted preview
        set({ isLoading: true, error: null, auto_wb: true });
        try {
          const saved = originalPreviewUrl ?? imagePreviewUrl;
          const { preview_url, width, height } = await previewAutoWb(
            imageFile,
            imageFile.name,
          );
          set({
            originalPreviewUrl: saved,
            imagePreviewUrl: preview_url,
            imageNaturalWidth: width,
            imageNaturalHeight: height,
            isLoading: false,
          });
        } catch (err) {
          set({
            auto_wb: false,
            error:
              err instanceof Error
                ? err.message
                : "White balance preview failed",
            isLoading: false,
          });
        }
      } else {
        // 关闭白平衡：恢复原始预览
        if (originalPreviewUrl) {
          set({
            auto_wb: false,
            imagePreviewUrl: originalPreviewUrl,
            originalPreviewUrl: null,
          });
        } else {
          set({ auto_wb: false });
        }
      }
    },

    setManufacturer: (value: string) => set({ manufacturer: value }),

    setType: (value: string) => set({ type: value }),

    submitExtract: async () => {
      const state = get();
      // Use calibrated image if colorchecker was applied, otherwise original
      const fileToExtract = state.calibratedImageFile ?? state.imageFile;
      if (!fileToExtract || state.corner_points.length < 4) return;

      set({ isLoading: true, error: null });
      try {
        const response = await extractColors(fileToExtract, {
          corner_points: state.corner_points,
          color_mode: state.color_mode,
          page: state.page,
          eight_color_full_export: state.eight_color_full_export,
          offset_x: state.offset_x,
          offset_y: state.offset_y,
          zoom: state.zoom,
          distortion: state.distortion,
          vignette_correction: state.vignette_correction,
          auto_wb: state.auto_wb,
        });

        const pageUpdate: Partial<ExtractorState> = {};
        if (state.color_mode === ExtractorColorModeEnum.EIGHT_COLOR) {
          if (state.eight_color_full_export) {
            pageUpdate.extractedEightColorFullPages = uniqueSortedPageNumbers([
              ...state.extractedEightColorFullPages,
              parseExtractorPageNumber(state.page),
            ]);
          } else if (state.page === ExtractorPageEnum.PAGE_1) {
            pageUpdate.page1Extracted = true;
          } else {
            pageUpdate.page2Extracted = true;
          }
        }
        if (state.color_mode === ExtractorColorModeEnum.FIVE_COLOR_EXT) {
          if (state.page === ExtractorPageEnum.PAGE_1) {
            pageUpdate.page1Extracted_5c = true;
          } else {
            pageUpdate.page2Extracted_5c = true;
          }
        }

        set({
          session_id: response.session_id,
          lut_download_url: response.lut_download_url
            ? normalizeResourceUrl(response.lut_download_url)
            : null,
          warp_view_url: response.warp_view_url
            ? normalizeResourceUrl(response.warp_view_url)
            : null,
          lut_preview_url: response.lut_preview_url
            ? normalizeResourceUrl(response.lut_preview_url)
            : null,
          lut_layout: response.lut_layout ?? null,
          isLoading: false,
          defaultPalette: response.default_palette ?? [],
          paletteConfirmed: false,
          paletteConfirmError: null,
          ...pageUpdate,
        });
      } catch (err) {
        set({
          error: err instanceof Error ? err.message : "颜色提取失败，请重试",
          isLoading: false,
        });
      }
    },

    submitManualFix: async (rowIndex: number, color: string) => {
      const state = get();
      if (!state.session_id) return;

      set({ manualFixLoading: true, manualFixError: null });
      try {
        const response = await manualFixCell(
          state.session_id,
          rowIndex,
          color,
        );
        set({
          lut_preview_url: response.lut_preview_url
            ? normalizeResourceUrl(response.lut_preview_url)
            : null,
          lut_layout: response.lut_layout ?? state.lut_layout,
          manualFixLoading: false,
        });
      } catch (err) {
        set({
          manualFixError:
            err instanceof Error ? err.message : "手动修正失败，请重试",
          manualFixLoading: false,
        });
      }
    },

    submitMerge: async () => {
      const state = get();
      const is5c = state.color_mode === ExtractorColorModeEnum.FIVE_COLOR_EXT;
      const isEightColorFull =
        state.color_mode === ExtractorColorModeEnum.EIGHT_COLOR &&
        state.eight_color_full_export;
      const allRequiredExtracted = is5c
        ? state.page1Extracted_5c && state.page2Extracted_5c
        : isEightColorFull
          ? state.extractedEightColorFullPages.length ===
            EXTRACTOR_EIGHT_COLOR_FULL_TOTAL_PAGES
          : state.page1Extracted && state.page2Extracted;

      if (!allRequiredExtracted) return;

      set({ mergeLoading: true, mergeError: null });
      try {
        const response = is5c
          ? await mergeFiveColorExtended()
          : await mergeEightColor(state.eight_color_full_export);
        set({
          session_id: response.session_id,
          lut_download_url: response.lut_download_url
            ? normalizeResourceUrl(response.lut_download_url)
            : null,
          warp_view_url: response.warp_view_url
            ? normalizeResourceUrl(response.warp_view_url)
            : null,
          lut_preview_url: response.lut_preview_url
            ? normalizeResourceUrl(response.lut_preview_url)
            : null,
          lut_layout: response.lut_layout ?? null,
          defaultPalette: response.default_palette ?? [],
          paletteConfirmed: false,
          paletteConfirmError: null,
          mergeLoading: false,
        });
      } catch (err) {
        set({
          mergeError: err instanceof Error ? err.message : "合并失败，请重试",
          mergeLoading: false,
        });
      }
    },

    setError: (error: string | null) => set({ error }),
    clearError: () => set({ error: null }),

    updatePaletteEntry: (
      index: number,
      entry: Partial<ExtractorPaletteEntry>,
    ) => {
      const palette = [...get().defaultPalette];
      if (index >= 0 && index < palette.length) {
        palette[index] = { ...palette[index], ...entry };
        set({ defaultPalette: palette });
      }
    },

    submitConfirmPalette: async () => {
      const state = get();
      if (!state.session_id || state.defaultPalette.length === 0) return;

      set({ paletteConfirmLoading: true, paletteConfirmError: null });
      try {
        await confirmPalette({
          session_id: state.session_id,
          manufacturer: state.manufacturer.trim(),
          type: state.type.trim(),
          palette: state.defaultPalette.map((entry) => ({
            ...entry,
            color_name: entry.color_name?.trim() || null,
          })),
        });
        set({ paletteConfirmed: true, paletteConfirmLoading: false });
      } catch (err) {
        set({
          paletteConfirmError:
            err instanceof Error ? err.message : "Palette confirmation failed",
          paletteConfirmLoading: false,
        });
      }
    },
  }),
);
