import { fireEvent, render, waitFor } from "@testing-library/react";
import readExcelFile from "read-excel-file/browser";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  colorcheckerDetectChart,
  colorcheckerListReferences,
  colorcheckerNormalizeReference,
  colorcheckerPrepareSource,
  colorcheckerRelease,
  colorcheckerTouch,
  confirmPalette,
  extractColors,
  manualFixCell,
  mergeFiveColorExtended,
  previewAutoWb,
  rotateExtractorImage,
} from "../api/extractor";
import { uploadImagePreview } from "../api/system";
import { ExtractorColorMode, ExtractorPage } from "../api/types";
import type { ExtractorState } from "../stores/extractorStore";
import { useExtractorStore } from "../stores/extractorStore";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import { I18nProvider } from "../i18n/context";
import { ColorcheckerConfirmDialogInner } from "../components/ColorcheckerConfirmDialog";

vi.mock("read-excel-file/browser", () => ({
  default: vi.fn(),
}));

vi.mock("../api/system", () => ({
  uploadImagePreview: vi.fn(),
}));

vi.mock("../api/extractor", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/extractor")>();
  return {
    ...actual,
    colorcheckerDetectChart: vi.fn(),
    colorcheckerListReferences: vi.fn(),
    colorcheckerNormalizeReference: vi.fn(),
    colorcheckerPrepareSource: vi.fn(),
    colorcheckerRelease: vi.fn(),
    colorcheckerTouch: vi.fn(() => Promise.resolve()),
    confirmPalette: vi.fn(),
    extractColors: vi.fn(),
    manualFixCell: vi.fn(),
    mergeFiveColorExtended: vi.fn(),
    previewAutoWb: vi.fn(),
    rotateExtractorImage: vi.fn(),
  };
});

const rawHttpStatusErrorPattern =
  /Request failed with status code|status code\s+\d{3}\b|\b[45]\d{2}\b/i;
const readableApiErrorPattern =
  /server hit an internal error|API request failed|服务器发生内部错误|接口请求失败/i;
const rawUnsupportedDetail =
  "当前环境暂不支持 RAW 图片，请先转换为 PNG/JPEG 后再上传。";
const optionalDependencyLeakPattern = /pip install|pillow-heif|rawpy/i;

const sampleReferenceRows = [
  ["Company", "SN:SN-TEST"],
  [null],
  ["No", "Number", "sRGB", null, null, "CIE L*a*b*(d50)", null, null],
  [null, null, "R", "G", "B", "L*", "a*", "b*"],
  ...Array.from({ length: 24 }, (_item, index) => [
    index + 1,
    `Patch ${index + 1}`,
    index + 1,
    index + 2,
    index + 3,
    50,
    0,
    0,
  ]),
];

const defaultExtractorState: Partial<ExtractorState> = {
  imageFile: null,
  imagePreviewUrl: null,
  imageNaturalWidth: null,
  imageNaturalHeight: null,
  color_mode: ExtractorColorMode.FOUR_COLOR_RYBW,
  page: ExtractorPage.PAGE_1,
  eight_color_full_export: false,
  corner_points: [],
  nudge_step: 1,
  active_corner_index: null,
  offset_x: 0,
  offset_y: 0,
  zoom: 1.0,
  distortion: 0.0,
  vignette_correction: false,
  auto_wb: false,
  colorchecker_enabled: false,
  colorchecker_phase: null,
  calibratedPreviewUrl: null,
  calibratedFullFileId: null,
  previousCalibratedFullFileId: null,
  calibratedFullWidth: null,
  calibratedFullHeight: null,
  calibratedPreviewWidth: null,
  calibratedPreviewHeight: null,
  originalPreviewUrl: null,
  originalPreviewWidth: null,
  originalPreviewHeight: null,
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

function makeHttpStatusError(status: number): Error {
  return new Error(`Request failed with status code ${status}`);
}

function expectReadableError(message: string | null | undefined): void {
  expect(message).toEqual(expect.any(String));
  expect(message).not.toMatch(rawHttpStatusErrorPattern);
}

function expectReadableErrorInDocument(): void {
  const text = document.body.textContent ?? "";
  expect(text).toMatch(readableApiErrorPattern);
  expect(text).not.toMatch(rawHttpStatusErrorPattern);
}

function resetStores(): void {
  useSettingsStore.setState({ ...DEFAULT_SETTINGS, language: "en" });
  useExtractorStore.setState(defaultExtractorState);
}

function renderColorcheckerDialog() {
  return render(
    <I18nProvider>
      <ColorcheckerConfirmDialogInner
        phase="calibrating"
        imageFile={new File([new Uint8Array([1, 2, 3])], "chart.png", {
          type: "image/png",
        })}
        originalPreviewUrl="/api/files/original.png"
        calibratedPreviewUrl={null}
        calibrationSummary={null}
        receiveCalibrated={vi.fn()}
        confirmCalibrated={vi.fn()}
        rejectCalibrated={vi.fn()}
        closeDialog={vi.fn()}
      />
    </I18nProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  resetStores();
  vi.mocked(readExcelFile).mockResolvedValue([
    { sheet: "Sheet1", data: sampleReferenceRows },
  ]);
  vi.mocked(colorcheckerListReferences).mockResolvedValue({
    defaultReferenceId: "dafan",
    references: [
      {
        id: "dafan",
        name: "Dafan",
        patchCount: 24,
        labWhitePoint: "D50",
        serialNumber: null,
        referenceHash: "dafan-hash",
        source: {
          sourceType: "built_in",
          sourceName: "Dafan",
          serialNumber: null,
          patchCount: 24,
          labWhitePoint: "D50",
          referenceHash: "dafan-hash",
        },
      },
    ],
  });
  vi.mocked(colorcheckerNormalizeReference).mockResolvedValue({
    patches: Array.from({ length: 24 }, (_item, index) => ({
      index: index + 1,
      label: `Patch ${index + 1}`,
      sRGB: [index + 1, index + 2, index + 3],
      Lab_d50: [50, 0, 0],
      Lab_d65: [50, 0, 0],
    })),
    source: {
      sourceType: "user_upload",
      sourceName: "custom-reference",
      serialNumber: "SN-TEST",
      patchCount: 24,
      labWhitePoint: "D50",
      referenceHash: "custom-hash",
    },
    referenceHash: "custom-hash",
    warnings: [],
  });
  vi.mocked(colorcheckerDetectChart).mockResolvedValue({
    detected: true,
    corners: [
      { x: 10, y: 10 },
      { x: 90, y: 10 },
      { x: 90, y: 60 },
      { x: 10, y: 60 },
    ],
    patchOrientation: "normal",
    confidence: 0.92,
    score: 0.88,
    mode: "auto",
    reason: "",
    candidateCount: 1,
  });
  vi.mocked(colorcheckerPrepareSource).mockResolvedValue({
    colorchecker_source_file_id: "source-chart.png",
    source_preview_url: "/api/files/source-chart.jpg",
    full_width: 800,
    full_height: 600,
    preview_width: 100,
    preview_height: 80,
  });
  vi.mocked(colorcheckerRelease).mockResolvedValue(undefined);
  vi.mocked(colorcheckerTouch).mockResolvedValue(undefined);
  vi.mocked(uploadImagePreview).mockResolvedValue({
    preview_url: "/api/files/raw-preview.png",
    width: 400,
    height: 300,
  });
});

describe("extractor visible API error language", () => {
  it("normalizes extraction API HTTP status errors", async () => {
    useExtractorStore.setState({
      imageFile: new File(["image"], "calibration.png", { type: "image/png" }),
      corner_points: [
        [0, 0],
        [100, 0],
        [100, 100],
        [0, 100],
      ],
    });
    vi.mocked(extractColors).mockRejectedValueOnce(makeHttpStatusError(500));

    await useExtractorStore.getState().submitExtract();

    expectReadableError(useExtractorStore.getState().error);
  });

  it("preserves concrete non-generic extraction errors", async () => {
    const message = "Color chart corners are outside the uploaded image.";
    useExtractorStore.setState({
      imageFile: new File(["raw"], "calibration.dng", {
        type: "image/x-adobe-dng",
      }),
      corner_points: [
        [0, 0],
        [100, 0],
        [100, 100],
        [0, 100],
      ],
    });
    vi.mocked(extractColors).mockRejectedValueOnce(new Error(message));

    await useExtractorStore.getState().submitExtract();

    expect(useExtractorStore.getState().error).toBe(message);
  });

  it("normalizes manual correction HTTP status errors", async () => {
    useExtractorStore.setState({ session_id: "session-1" });
    vi.mocked(manualFixCell).mockRejectedValueOnce(makeHttpStatusError(402));

    await useExtractorStore.getState().submitManualFix(1, "#FFFFFF");

    expectReadableError(useExtractorStore.getState().manualFixError);
  });

  it("normalizes merge HTTP status errors", async () => {
    useExtractorStore.setState({
      color_mode: ExtractorColorMode.FIVE_COLOR_EXT,
      page1Extracted_5c: true,
      page2Extracted_5c: true,
    });
    vi.mocked(mergeFiveColorExtended).mockRejectedValueOnce(makeHttpStatusError(500));

    await useExtractorStore.getState().submitMerge();

    expectReadableError(useExtractorStore.getState().mergeError);
  });

  it("normalizes palette confirmation HTTP status errors", async () => {
    useExtractorStore.setState({
      session_id: "session-1",
      manufacturer: "Bambu Lab",
      type: "PLA Basic",
      defaultPalette: [
        {
          color: "White",
          material: "PLA",
          hex_color: "#FFFFFF",
          color_name: "Jade White",
        },
      ],
    });
    vi.mocked(confirmPalette).mockRejectedValueOnce(makeHttpStatusError(500));

    await useExtractorStore.getState().submitConfirmPalette();

    expectReadableError(useExtractorStore.getState().paletteConfirmError);
  });

  it("normalizes image rotation HTTP status errors", async () => {
    const imageFile = new File(["image"], "source.png", { type: "image/png" });
    useExtractorStore.setState({
      imageFile,
      imagePreviewUrl: "/api/files/source.png",
    });
    vi.mocked(rotateExtractorImage).mockRejectedValueOnce(makeHttpStatusError(500));

    await useExtractorStore.getState().rotateImage();

    expect(useExtractorStore.getState().imageFile).toBe(imageFile);
    expectReadableError(useExtractorStore.getState().error);
  });

  it("normalizes auto white-balance preview HTTP status errors", async () => {
    useExtractorStore.setState({
      imageFile: new File(["image"], "source.png", { type: "image/png" }),
      imagePreviewUrl: "/api/files/source.png",
      imageNaturalWidth: 800,
      imageNaturalHeight: 600,
    });
    vi.mocked(previewAutoWb).mockRejectedValueOnce(makeHttpStatusError(500));

    await useExtractorStore.getState().setAutoWb(true);

    const state = useExtractorStore.getState();
    expect(state.auto_wb).toBe(false);
    expect(state.isLoading).toBe(false);
    expectReadableError(state.error);
  });

  it("normalizes RAW preview restore HTTP status errors", async () => {
    const rawFile = new File(["raw"], "source.dng", {
      type: "image/x-adobe-dng",
    });
    useExtractorStore.setState({
      imageFile: rawFile,
      colorchecker_enabled: true,
      colorchecker_phase: "calibrating",
    });
    vi.mocked(uploadImagePreview).mockRejectedValueOnce(makeHttpStatusError(500));

    useExtractorStore.getState().setColorcheckerEnabled(false);

    await waitFor(() => expect(uploadImagePreview).toHaveBeenCalledWith(rawFile));
    await waitFor(() => expectReadableError(useExtractorStore.getState().error));
  });

  it("uses user-facing RAW preview upload errors without dependency names", async () => {
    const rawFile = new File(["raw"], "source.dng", {
      type: "image/x-adobe-dng",
    });
    vi.mocked(uploadImagePreview).mockRejectedValueOnce(
      new Error(rawUnsupportedDetail),
    );

    useExtractorStore.getState().setImageFile(rawFile);

    await waitFor(() => expect(uploadImagePreview).toHaveBeenCalledWith(rawFile));
    await waitFor(() => {
      const message = useExtractorStore.getState().error;
      expect(message).toEqual(expect.any(String));
      expect(message).toContain("RAW");
      expect(message).toMatch(/PNG\/JPEG|PNG\/JPG|PNG or JPG/);
      expect(message).not.toMatch(optionalDependencyLeakPattern);
    });
  });
});

describe("ColorChecker reference visible API error language", () => {
  it("normalizes reference list HTTP status errors", async () => {
    vi.mocked(colorcheckerListReferences).mockRejectedValueOnce(
      makeHttpStatusError(500),
    );

    renderColorcheckerDialog();

    await waitFor(expectReadableErrorInDocument);
  });

  it("normalizes custom reference upload HTTP status errors", async () => {
    vi.mocked(colorcheckerNormalizeReference).mockRejectedValueOnce(
      makeHttpStatusError(500),
    );
    const { container } = renderColorcheckerDialog();

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, {
      target: {
        files: [
          new File([new Uint8Array([7, 8, 9])], "custom-reference.xlsx", {
            type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          }),
        ],
      },
    });

    await waitFor(expectReadableErrorInDocument);
  });
});
