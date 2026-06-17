import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import readExcelFile from "read-excel-file/browser";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  colorcheckerCalibrate,
  colorcheckerDetectChart,
  colorcheckerListReferences,
  colorcheckerNormalizeReference,
  colorcheckerPrepareSource,
  colorcheckerRelease,
  colorcheckerTouch,
  colorcheckerWarpPreview,
  type ColorcheckerDisplaySummary,
} from "../api/extractor";
import ColorcheckerConfirmDialogExtractor, {
  ColorcheckerConfirmDialogInner,
} from "../components/ColorcheckerConfirmDialog";
import { I18nProvider } from "../i18n/context";
import { useExtractorStore } from "../stores/extractorStore";
import { useSettingsStore } from "../stores/settingsStore";

vi.mock("read-excel-file/browser", () => ({
  default: vi.fn(),
}));

vi.mock("../api/extractor", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/extractor")>();
  return {
    ...actual,
    colorcheckerCalibrate: vi.fn(),
    colorcheckerDetectChart: vi.fn(),
    colorcheckerListReferences: vi.fn(),
    colorcheckerNormalizeReference: vi.fn(),
    colorcheckerPrepareSource: vi.fn(),
    colorcheckerRelease: vi.fn(),
    colorcheckerTouch: vi.fn(() => Promise.resolve()),
    colorcheckerWarpPreview: vi.fn(),
  };
});

const imageFile = new File([new Uint8Array([1, 2, 3])], "chart.png", {
  type: "image/png",
});
const replacementImageFile = new File([new Uint8Array([4, 5, 6])], "replacement.png", {
  type: "image/png",
});
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

const resolvePending = <T,>(resolver: ((value: T) => void) | null, value: T) => {
  if (!resolver) {
    throw new Error("Expected a pending mocked request resolver");
  }
  resolver(value);
};

const makeTimeoutError = () =>
  Object.assign(new Error("timeout of 120000ms exceeded"), {
    code: "ECONNABORTED",
  });

const summary: ColorcheckerDisplaySummary = {
  deltaE00: {
    mean: 2.0362,
    median: 1.7912,
    p95: 3.25,
    max: 4.8,
  },
  worstPatch: {
    index: 17,
    label: "Cyan",
    deltaE00: 4.8,
    referenceSrgb: [0, 120, 160],
    correctedSrgb: [4, 118, 158],
  },
  luminanceCurve: [
    {
      index: 19,
      label: "White",
      reference: 1,
      captured: 0.92,
      normalized: 0.95,
      corrected: 0.99,
      fitUsed: true,
      grayPatch: true,
    },
    {
      index: 20,
      label: "Neutral 8",
      reference: 0.75,
      captured: 0.68,
      normalized: 0.7,
      corrected: 0.74,
      fitUsed: true,
      grayPatch: true,
    },
  ],
  reference: {
    sourceType: "built_in",
    sourceName: "大凡光学",
    serialNumber: null,
    patchCount: 24,
    labWhitePoint: "D50",
  },
  settings: {
    method: "mean",
    calibrationMode: "matrix_3x3",
    grayAffineMode: "auto",
    sampleRadius: 12,
    blurRadius: 0,
  },
  warnings: [
    "fit mean ΔE00 2.0362 exceeds suggested 2.0 threshold.",
    "fit median ΔE00 1.7912 exceeds suggested 1.5 threshold.",
  ],
};

function renderDialog(
  props: Partial<ComponentProps<typeof ColorcheckerConfirmDialogInner>> = {},
) {
  const mergedProps: ComponentProps<typeof ColorcheckerConfirmDialogInner> = {
    phase: "calibrating",
    imageFile,
    originalPreviewUrl: "/api/files/original.png",
    calibratedPreviewUrl: null,
    calibrationSummary: null,
    receiveCalibrated: vi.fn(),
    confirmCalibrated: vi.fn(),
    rejectCalibrated: vi.fn(),
    closeDialog: vi.fn(),
    ...props,
  };

  return render(
    <I18nProvider>
      <ColorcheckerConfirmDialogInner {...mergedProps} />
    </I18nProvider>,
  );
}

async function expectDafanDetectCalled(sourceId: string) {
  await waitFor(() =>
    expect(colorcheckerDetectChart).toHaveBeenCalledWith(
      sourceId,
      "4x6",
      null,
      { kind: "server", referenceId: "dafan" },
    ),
  );
}

describe("ColorcheckerConfirmDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    useSettingsStore.setState({ language: "zh" });
    vi.mocked(readExcelFile).mockResolvedValue([
      { sheet: "Sheet1", data: sampleReferenceRows },
    ]);
    vi.mocked(colorcheckerListReferences).mockResolvedValue({
      defaultReferenceId: "dafan",
      references: [
        {
          id: "dafan",
          name: "大凡光学",
          patchCount: 24,
          labWhitePoint: "D50",
          serialNumber: null,
          referenceHash: "dafan-hash",
          source: {
            sourceType: "built_in",
            sourceName: "大凡光学",
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
    vi.mocked(colorcheckerWarpPreview).mockResolvedValue({
      preview_url: "/api/files/warp.png",
      preview_width: 720,
      preview_height: 480,
      auto_patch_points: [],
    });
    vi.mocked(colorcheckerCalibrate).mockResolvedValue({
      calibrated_preview_url: "/api/files/calibrated-preview.jpg",
      calibrated_full_file_id: "full-id",
      overlay_url: "/api/files/overlay.png",
      full_width: 800,
      full_height: 600,
      preview_width: 400,
      preview_height: 300,
      patch_points: [],
      display_summary: summary,
    });
    vi.mocked(colorcheckerPrepareSource).mockImplementation(async (file: File) => ({
      colorchecker_source_file_id: `source-${file.name}`,
      source_preview_url: `/api/files/source-${file.name}.jpg`,
      full_width: 800,
      full_height: 600,
      preview_width: 100,
      preview_height: 80,
    }));
    vi.mocked(colorcheckerRelease).mockResolvedValue(undefined);
    vi.mocked(colorcheckerTouch).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("collapses when inactive and renders localized result cards when confirming", () => {
    const { rerender } = renderDialog({ phase: null });

    expect(screen.queryByTestId("colorchecker-inline-tool")).not.toBeInTheDocument();

    rerender(
      <I18nProvider>
        <ColorcheckerConfirmDialogInner
          phase="confirming"
          imageFile={imageFile}
          originalPreviewUrl="/api/files/original.png"
          calibratedPreviewUrl="/api/files/calibrated.png"
          calibrationSummary={summary}
          receiveCalibrated={vi.fn()}
          confirmCalibrated={vi.fn()}
          rejectCalibrated={vi.fn()}
          closeDialog={vi.fn()}
        />
      </I18nProvider>,
    );

    expect(screen.getByText("校色结果确认")).toBeInTheDocument();
    expect(screen.getByText("当前基准")).toBeInTheDocument();
    expect(screen.getByText("大凡光学")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "亮度曲线" })).toBeInTheDocument();
    expect(screen.queryByText("校色质量提示")).not.toBeInTheDocument();
    expect(screen.queryByText(/平均 ΔE00 为 2.0362/)).not.toBeInTheDocument();
    expect(screen.getByText("校色完成，请检查结果后确认使用。")).toBeInTheDocument();
    expect(screen.getAllByText("可接受").length).toBeGreaterThan(0);
  });

  it("renders fit DeltaE warnings only when they are check-level", () => {
    renderDialog({
      phase: "confirming",
      calibratedPreviewUrl: "/api/files/calibrated.png",
      calibrationSummary: {
        ...summary,
        deltaE00: {
          ...summary.deltaE00,
          mean: 3.2,
        },
        warnings: [
          "fit median ΔE00 1.7912 exceeds suggested 1.5 threshold.",
          "fit mean ΔE00 3.2 exceeds suggested 3.0 threshold.",
        ],
      },
    });

    expect(screen.getAllByText("校色质量提示")).toHaveLength(1);
    expect(screen.queryByText(/中位 ΔE00 为 1\.7912/)).not.toBeInTheDocument();
    expect(screen.getByText(/平均 ΔE00 为 3\.2/)).toBeInTheDocument();
  });

  it("renders gray reference delta warnings, gamut boundary copy, and delta status labels", () => {
    renderDialog({
      phase: "confirming",
      calibratedPreviewUrl: "/api/files/calibrated.png",
      calibrationSummary: {
        ...summary,
        deltaE00: {
          mean: 1.2,
          median: 1.0,
          p95: 6.2,
          max: 6.5,
        },
        worstPatch: {
          ...summary.worstPatch!,
          deltaE00: 6.5,
        },
        warnings: [
          "Neutral gray Δb* patch 23 (N3.5/) is -1.6300 (corrected -3.2000 vs reference -1.5700), exceeds suggested 1.5 threshold.",
          "Corrected image gamut clipping ratio is 1.6484%.",
        ],
      },
    });

    expect(screen.getByText(/23\. N3\.5\/ 灰块的 Δb\* 为 -1\.6300/)).toBeInTheDocument();
    expect(screen.getByText(/线性 RGB 通道样本超过 1\.0/)).toBeInTheDocument();
    expect(screen.getAllByText("高精度").length).toBeGreaterThan(0);
    expect(screen.getAllByText("需检查").length).toBeGreaterThan(0);
  });

  it("shows source upload progress while preparing the ColorChecker preview", async () => {
    let reportProgress:
      | NonNullable<
          NonNullable<Parameters<typeof colorcheckerPrepareSource>[1]>["onUploadProgress"]
        >
      | undefined;
    vi.mocked(colorcheckerPrepareSource).mockImplementationOnce((_file, options) => {
      reportProgress = options?.onUploadProgress;
      return new Promise(() => undefined);
    });

    renderDialog();

    await waitFor(() => expect(reportProgress).toBeDefined());
    act(() => {
      reportProgress?.({ loaded: 45, total: 100, percent: 45 });
    });

    expect(screen.getByText("正在上传原图 45%")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "原图上传进度" })).toHaveAttribute(
      "aria-valuenow",
      "45",
    );
  });

  it("uses stage-specific timeout copy while preparing the source preview", async () => {
    vi.mocked(colorcheckerPrepareSource).mockRejectedValueOnce(makeTimeoutError());

    renderDialog();

    expect(
      await screen.findByText(
        "校色器原图上传或预览生成超时。图片较大或网络较慢时可能发生，请重试或使用更快网络。",
      ),
    ).toBeInTheDocument();
  });

  it("falls back to the default reference when localStorage cannot read the saved selection", async () => {
    const originalLocalStorage = window.localStorage;
    const blockedStorage = {
      ...originalLocalStorage,
      getItem: vi.fn(() => {
        throw new DOMException("storage is blocked", "SecurityError");
      }),
      setItem: vi.fn(),
      removeItem: vi.fn(),
      clear: vi.fn(),
      key: vi.fn(),
      length: 0,
    } as Storage;
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: blockedStorage,
    });

    try {
      renderDialog();
      await expectDafanDetectCalled("source-chart.png");
      expect(screen.getByText("大凡光学")).toBeInTheDocument();
    } finally {
      Object.defineProperty(window, "localStorage", {
        configurable: true,
        value: originalLocalStorage,
      });
    }
  });

  it("uses stage-specific timeout copy during auto detection", async () => {
    vi.mocked(colorcheckerDetectChart).mockRejectedValueOnce(makeTimeoutError());

    renderDialog();

    expect(
      await screen.findByText("ColorChecker 自动识别超时。请重试，或手动点选四个色卡角点。"),
    ).toBeInTheDocument();
  });

  it("uses stage-specific timeout copy during warp preview generation", async () => {
    vi.mocked(colorcheckerWarpPreview).mockRejectedValueOnce(makeTimeoutError());
    renderDialog();

    await expectDafanDetectCalled("source-chart.png");
    const warpButton = await screen.findByRole("button", { name: "生成预览" });
    await waitFor(() => expect(warpButton).not.toBeDisabled());
    fireEvent.click(warpButton);

    expect(
      await screen.findByText("ColorChecker 透视预览生成超时。请重试，或检查角点是否框住完整色卡。"),
    ).toBeInTheDocument();
  });

  it("uses stage-specific timeout copy during calibration", async () => {
    vi.mocked(colorcheckerCalibrate).mockRejectedValueOnce(makeTimeoutError());
    renderDialog();

    await expectDafanDetectCalled("source-chart.png");
    const calibrateButton = await screen.findByRole("button", { name: "执行校色" });
    await waitFor(() => expect(calibrateButton).not.toBeDisabled());
    fireEvent.click(calibrateButton);

    expect(
      await screen.findByText("ColorChecker 校色计算超时。请重试；大 RAW/DNG 图片可能需要更长处理时间。"),
    ).toBeInTheDocument();
  });

  it("submits advanced algorithm options and dragged corner coordinates", async () => {
    renderDialog();

    await waitFor(() =>
      expect(colorcheckerPrepareSource).toHaveBeenCalledWith(
        imageFile,
        expect.objectContaining({ onUploadProgress: expect.any(Function) }),
      ),
    );
    await expectDafanDetectCalled("source-chart.png");

    const image = screen.getByAltText("ColorChecker 色卡校色") as HTMLImageElement;
    Object.defineProperty(image, "naturalWidth", { configurable: true, value: 100 });
    Object.defineProperty(image, "naturalHeight", { configurable: true, value: 80 });
    image.getBoundingClientRect = vi.fn(() => ({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 100,
      bottom: 80,
      width: 100,
      height: 80,
      toJSON: () => ({}),
    }));
    fireEvent.load(image);

    const topLeftCorner = await screen.findByRole("button", { name: "色卡角点 1" });
    fireEvent.pointerDown(topLeftCorner, { clientX: 10, clientY: 10 });
    fireEvent.pointerMove(window, { clientX: 30, clientY: 35 });
    fireEvent.pointerUp(window);

    fireEvent.click(screen.getByRole("checkbox", { name: /高级选项/ }));
    fireEvent.click(await screen.findByRole("combobox", { name: "校色算法" }));
    fireEvent.click(screen.getByRole("option", { name: "二阶 Root-Polynomial" }));
    fireEvent.click(screen.getByRole("button", { name: "执行校色" }));

    await waitFor(() => expect(colorcheckerCalibrate).toHaveBeenCalled());
    const call = vi.mocked(colorcheckerCalibrate).mock.calls[0];
    expect(call[0]).toBe("source-chart.png");
    expect(call[1][0]).toEqual([30, 35]);
    expect(call[2]).toEqual({ width: 100, height: 80 });
    expect(call[5]).toEqual({
      calibrationMode: "root_polynomial",
      method: "mean",
      grayAffineMode: "auto",
      sampleRadius: 12,
      blurRadius: 0,
    });
  });

  it("uploads, persists, selects, deletes, and forwards a custom reference", async () => {
    const { container } = renderDialog();

    await expectDafanDetectCalled("source-chart.png");
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

    await waitFor(() => expect(colorcheckerNormalizeReference).toHaveBeenCalled());
    await screen.findByText("custom-reference (SN-TEST)");
    await waitFor(() =>
      expect(colorcheckerDetectChart).toHaveBeenLastCalledWith(
        "source-chart.png",
        "4x6",
        null,
        expect.objectContaining({
          kind: "custom",
          referenceSource: expect.objectContaining({
            sourceName: "custom-reference",
            referenceHash: "custom-hash",
          }),
        }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "执行校色" }));
    await waitFor(() => expect(colorcheckerCalibrate).toHaveBeenCalled());
    const calibrateCalls = vi.mocked(colorcheckerCalibrate).mock.calls;
    const calibrateCall = calibrateCalls[calibrateCalls.length - 1]!;
    expect(calibrateCall[7]).toEqual(
      expect.objectContaining({
        kind: "custom",
        referenceSource: expect.objectContaining({
          referenceHash: "custom-hash",
        }),
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "删除自定义" }));
    await waitFor(() =>
      expect(colorcheckerDetectChart).toHaveBeenLastCalledWith(
        "source-chart.png",
        "4x6",
        null,
        { kind: "server", referenceId: "dafan" },
      ),
    );
    expect(window.localStorage.getItem("lumina.colorchecker.references.v1")).toBe("[]");
  });

  it("keeps an uploaded custom reference usable when localStorage cannot persist it", async () => {
    const originalLocalStorage = window.localStorage;
    const blockedStorage = {
      getItem: vi.fn((key: string) => originalLocalStorage.getItem(key)),
      setItem: vi.fn(() => {
        throw new DOMException("storage quota exceeded", "QuotaExceededError");
      }),
      removeItem: vi.fn((key: string) => originalLocalStorage.removeItem(key)),
      clear: vi.fn(() => originalLocalStorage.clear()),
      key: vi.fn((index: number) => originalLocalStorage.key(index)),
      get length() {
        return originalLocalStorage.length;
      },
    } as Storage;
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: blockedStorage,
    });
    try {
      const { container } = renderDialog();

      await expectDafanDetectCalled("source-chart.png");
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

      await waitFor(() => expect(colorcheckerNormalizeReference).toHaveBeenCalled());
      await screen.findByText("custom-reference (SN-TEST)");
      expect(screen.queryByText(/storage quota exceeded/)).not.toBeInTheDocument();
      expect(screen.queryByText("校色基准上传失败")).not.toBeInTheDocument();
      expect(
        screen.getByText(/刷新页面后需要重新上传|refresh/),
      ).toBeInTheDocument();
      await waitFor(() =>
        expect(colorcheckerDetectChart).toHaveBeenLastCalledWith(
          "source-chart.png",
          "4x6",
          null,
          expect.objectContaining({
            kind: "custom",
            referenceSource: expect.objectContaining({
              referenceHash: "custom-hash",
            }),
          }),
        ),
      );

      fireEvent.click(screen.getByRole("button", { name: "执行校色" }));
      await waitFor(() => expect(colorcheckerCalibrate).toHaveBeenCalled());
      const calibrateCall = vi.mocked(colorcheckerCalibrate).mock.calls.at(-1)!;
      expect(calibrateCall[7]).toEqual(
        expect.objectContaining({
          kind: "custom",
          referenceSource: expect.objectContaining({
            referenceHash: "custom-hash",
          }),
        }),
      );
    } finally {
      Object.defineProperty(window, "localStorage", {
        configurable: true,
        value: originalLocalStorage,
      });
    }
  });

  it("uses localized upload warning copy without hard-coded suffixes", async () => {
    useSettingsStore.setState({ language: "en" });
    vi.mocked(colorcheckerNormalizeReference).mockResolvedValueOnce({
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
      warnings: ["warn 1", "warn 2"],
    });
    const { container } = renderDialog();

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

    expect(
      await screen.findByText("Reference uploaded and selected with 2 warnings"),
    ).toBeInTheDocument();
  });

  it("falls back when a persisted server reference no longer exists", async () => {
    window.localStorage.setItem(
      "lumina.colorchecker.selectedReference.v1",
      "server:retired-reference",
    );

    renderDialog();

    await expectDafanDetectCalled("source-chart.png");
    const submittedReferenceIds = vi
      .mocked(colorcheckerDetectChart)
      .mock.calls.map((call) => call[3])
      .filter((reference) => reference?.kind === "server")
      .map((reference) => reference.referenceId);
    expect(submittedReferenceIds).not.toContain("retired-reference");
  });

  it("forwards auto-detected patch orientation to warp and calibration requests", async () => {
    vi.mocked(colorcheckerDetectChart).mockResolvedValueOnce({
      detected: true,
      corners: [
        { x: 10, y: 10 },
        { x: 90, y: 10 },
        { x: 90, y: 60 },
        { x: 10, y: 60 },
      ],
      patchOrientation: "flip_horizontal",
      confidence: 0.92,
      score: 0.88,
      mode: "auto",
      reason: "",
      candidateCount: 1,
    });
    renderDialog();

    await expectDafanDetectCalled("source-chart.png");
    const warpButton = await screen.findByRole("button", { name: "生成预览" });
    await waitFor(() => expect(warpButton).not.toBeDisabled());
    fireEvent.click(warpButton);

    await waitFor(() =>
      expect(colorcheckerWarpPreview).toHaveBeenCalledWith(
        "source-chart.png",
        [[10, 10], [90, 10], [90, 60], [10, 60]],
        { width: 100, height: 80 },
        "4x6",
        "flip_horizontal",
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "执行校色" }));

    await waitFor(() => expect(colorcheckerCalibrate).toHaveBeenCalled());
    const call = vi.mocked(colorcheckerCalibrate).mock.calls[0];
    expect(call[6]).toBe("flip_horizontal");
  });

  it("forwards manually selected patch orientation when auto-detect fails", async () => {
    vi.mocked(colorcheckerDetectChart).mockResolvedValueOnce({
      detected: false,
      corners: [],
      patchOrientation: "normal",
      confidence: 0,
      score: null,
      mode: "auto",
      reason: "not found",
      candidateCount: 0,
    });
    renderDialog();

    await expectDafanDetectCalled("source-chart.png");
    const image = await screen.findByAltText("ColorChecker 色卡校色") as HTMLImageElement;
    Object.defineProperty(image, "naturalWidth", { configurable: true, value: 100 });
    Object.defineProperty(image, "naturalHeight", { configurable: true, value: 80 });
    image.getBoundingClientRect = vi.fn(() => ({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 100,
      bottom: 80,
      width: 100,
      height: 80,
      toJSON: () => ({}),
    }));
    fireEvent.load(image);
    fireEvent.pointerDown(image, { clientX: 10, clientY: 10 });
    fireEvent.pointerDown(image, { clientX: 90, clientY: 10 });
    fireEvent.pointerDown(image, { clientX: 90, clientY: 60 });
    fireEvent.pointerDown(image, { clientX: 10, clientY: 60 });

    fireEvent.click(screen.getByRole("combobox", { name: "色块方向" }));
    fireEvent.click(screen.getByRole("option", { name: "旋转 180°" }));

    const warpButton = await screen.findByRole("button", { name: "生成预览" });
    await waitFor(() => expect(warpButton).not.toBeDisabled());
    fireEvent.click(warpButton);

    await waitFor(() =>
      expect(colorcheckerWarpPreview).toHaveBeenCalledWith(
        "source-chart.png",
        [[10, 10], [90, 10], [90, 60], [10, 60]],
        { width: 100, height: 80 },
        "4x6",
        "rotate_180",
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "执行校色" }));

    await waitFor(() => expect(colorcheckerCalibrate).toHaveBeenCalled());
    const call = vi.mocked(colorcheckerCalibrate).mock.calls[0];
    expect(call[6]).toBe("rotate_180");
  });

  it("releases stale calibration responses after the source image changes", async () => {
    let resolveCalibration:
      | ((value: Awaited<ReturnType<typeof colorcheckerCalibrate>>) => void)
      | null = null;
    vi.mocked(colorcheckerCalibrate).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveCalibration = resolve;
      }),
    );
    const receiveCalibrated = vi.fn();
    const { rerender } = renderDialog({ receiveCalibrated });

    await expectDafanDetectCalled("source-chart.png");
    const calibrateButton = screen.getByRole("button", { name: "执行校色" });
    await waitFor(() => expect(calibrateButton).not.toBeDisabled());
    fireEvent.click(calibrateButton);
    expect(calibrateButton.querySelector(".animate-spin")).not.toBeNull();

    rerender(
      <I18nProvider>
        <ColorcheckerConfirmDialogInner
          phase="calibrating"
          imageFile={replacementImageFile}
          originalPreviewUrl="/api/files/replacement.png"
          calibratedPreviewUrl={null}
          calibrationSummary={null}
          receiveCalibrated={receiveCalibrated}
          confirmCalibrated={vi.fn()}
          rejectCalibrated={vi.fn()}
          closeDialog={vi.fn()}
        />
      </I18nProvider>,
    );
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "执行校色" }).querySelector(".animate-spin"),
      ).toBeNull();
    });

    resolvePending(resolveCalibration, {
      calibrated_preview_url: "/api/files/stale-preview.jpg",
      calibrated_full_file_id: "stale-full-id",
      overlay_url: "/api/files/stale-overlay.jpg",
      full_width: 800,
      full_height: 600,
      preview_width: 400,
      preview_height: 300,
      patch_points: [],
      display_summary: summary,
    });

    await waitFor(() => {
      expect(colorcheckerRelease).toHaveBeenCalledWith("stale-full-id");
    });
    expect(receiveCalibrated).not.toHaveBeenCalled();
  });

  it("ignores stale auto-detect responses after the source image changes", async () => {
    let resolveDetect:
      | ((value: Awaited<ReturnType<typeof colorcheckerDetectChart>>) => void)
      | null = null;
    vi.mocked(colorcheckerDetectChart).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveDetect = resolve;
      }),
    );
    const { rerender } = renderDialog();
    await expectDafanDetectCalled("source-chart.png");
    vi.mocked(colorcheckerDetectChart).mockResolvedValueOnce({
      detected: false,
      corners: [],
      patchOrientation: "normal",
      confidence: 0,
      score: null,
      mode: "auto",
      reason: "not found",
      candidateCount: 0,
    });

    rerender(
      <I18nProvider>
        <ColorcheckerConfirmDialogInner
          phase="calibrating"
          imageFile={replacementImageFile}
          originalPreviewUrl="/api/files/replacement.png"
          calibratedPreviewUrl={null}
          calibrationSummary={null}
          receiveCalibrated={vi.fn()}
          confirmCalibrated={vi.fn()}
          rejectCalibrated={vi.fn()}
          closeDialog={vi.fn()}
        />
      </I18nProvider>,
    );

    resolvePending(resolveDetect, {
      detected: true,
      corners: [
        { x: 11, y: 12 },
        { x: 91, y: 12 },
        { x: 91, y: 62 },
        { x: 11, y: 62 },
      ],
      patchOrientation: "normal",
      confidence: 0.95,
      score: 0.9,
      mode: "auto",
      reason: "",
      candidateCount: 1,
    });

    await expectDafanDetectCalled("source-replacement.png");
    expect(screen.queryByRole("button", { name: "色卡角点 1" })).not.toBeInTheDocument();
  });

  it("keeps manually selected corners when auto-detect resolves late", async () => {
    let resolveDetect:
      | ((value: Awaited<ReturnType<typeof colorcheckerDetectChart>>) => void)
      | null = null;
    vi.mocked(colorcheckerDetectChart).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveDetect = resolve;
      }),
    );
    renderDialog();

    const image = await screen.findByAltText("ColorChecker 色卡校色") as HTMLImageElement;
    Object.defineProperty(image, "naturalWidth", { configurable: true, value: 100 });
    Object.defineProperty(image, "naturalHeight", { configurable: true, value: 80 });
    image.getBoundingClientRect = vi.fn(() => ({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 100,
      bottom: 80,
      width: 100,
      height: 80,
      toJSON: () => ({}),
    }));
    fireEvent.load(image);
    fireEvent.pointerDown(image, { clientX: 25, clientY: 30 });

    await act(async () => {
      resolvePending(resolveDetect, {
        detected: true,
        corners: [
          { x: 11, y: 12 },
          { x: 91, y: 12 },
          { x: 91, y: 62 },
          { x: 11, y: 62 },
        ],
        patchOrientation: "normal",
        confidence: 0.95,
        score: 0.9,
        mode: "auto",
        reason: "",
        candidateCount: 1,
      });
    });

    expect(screen.getByRole("button", { name: "色卡角点 1" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "色卡角点 2" })).not.toBeInTheDocument();
  });

  it("ignores stale warp responses after the source image changes", async () => {
    let resolveWarp:
      | ((value: Awaited<ReturnType<typeof colorcheckerWarpPreview>>) => void)
      | null = null;
    vi.mocked(colorcheckerWarpPreview).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveWarp = resolve;
      }),
    );
    const { rerender } = renderDialog();

    await expectDafanDetectCalled("source-chart.png");
    await screen.findByRole("button", { name: "色卡角点 1" });
    const warpButton = await screen.findByRole("button", { name: "生成预览" });
    await waitFor(() => expect(warpButton).not.toBeDisabled());
    fireEvent.click(warpButton);

    rerender(
      <I18nProvider>
        <ColorcheckerConfirmDialogInner
          phase="calibrating"
          imageFile={replacementImageFile}
          originalPreviewUrl="/api/files/replacement.png"
          calibratedPreviewUrl={null}
          calibrationSummary={null}
          receiveCalibrated={vi.fn()}
          confirmCalibrated={vi.fn()}
          rejectCalibrated={vi.fn()}
          closeDialog={vi.fn()}
        />
      </I18nProvider>,
    );

    resolvePending(resolveWarp, {
      preview_url: "/api/files/stale-warp.png",
      preview_width: 720,
      preview_height: 480,
      auto_patch_points: [{ x: 1, y: 2 }],
    });

    await waitFor(() => expect(colorcheckerWarpPreview).toHaveBeenCalled());
    expect(screen.queryByText("透视预览已生成，可执行校色")).not.toBeInTheDocument();
  });

  it("drops warp patch points after a corner is dragged", async () => {
    vi.mocked(colorcheckerWarpPreview).mockResolvedValueOnce({
      preview_url: "/api/files/warp-with-points.png",
      preview_width: 720,
      preview_height: 480,
      auto_patch_points: [{ x: 12, y: 18 }],
    });
    renderDialog();

    await expectDafanDetectCalled("source-chart.png");
    await screen.findByRole("button", { name: "色卡角点 1" });
    const image = screen.getByAltText("ColorChecker 色卡校色") as HTMLImageElement;
    Object.defineProperty(image, "naturalWidth", { configurable: true, value: 100 });
    Object.defineProperty(image, "naturalHeight", { configurable: true, value: 80 });
    image.getBoundingClientRect = vi.fn(() => ({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 100,
      bottom: 80,
      width: 100,
      height: 80,
      toJSON: () => ({}),
    }));
    fireEvent.load(image);

    const warpButton = await screen.findByRole("button", { name: "生成预览" });
    await waitFor(() => expect(warpButton).not.toBeDisabled());
    fireEvent.click(warpButton);
    await screen.findByText("透视预览已生成，可执行校色");

    const topLeftCorner = await screen.findByRole("button", { name: "色卡角点 1" });
    fireEvent.pointerDown(topLeftCorner, { clientX: 10, clientY: 10 });
    fireEvent.pointerMove(window, { clientX: 30, clientY: 35 });
    fireEvent.pointerUp(window);

    expect(screen.queryByText("透视预览已生成，可执行校色")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "执行校色" }));

    await waitFor(() => expect(colorcheckerCalibrate).toHaveBeenCalled());
    const call = vi.mocked(colorcheckerCalibrate).mock.calls[0];
    expect(call[3]).toBeNull();
  });

  it("releases stale calibration when corners change during the request", async () => {
    let resolveCalibration:
      | ((value: Awaited<ReturnType<typeof colorcheckerCalibrate>>) => void)
      | null = null;
    vi.mocked(colorcheckerCalibrate).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveCalibration = resolve;
      }),
    );
    const receiveCalibrated = vi.fn();
    renderDialog({ receiveCalibrated });

    await expectDafanDetectCalled("source-chart.png");
    const image = screen.getByAltText("ColorChecker 色卡校色") as HTMLImageElement;
    Object.defineProperty(image, "naturalWidth", { configurable: true, value: 100 });
    Object.defineProperty(image, "naturalHeight", { configurable: true, value: 80 });
    image.getBoundingClientRect = vi.fn(() => ({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 100,
      bottom: 80,
      width: 100,
      height: 80,
      toJSON: () => ({}),
    }));
    fireEvent.load(image);

    const calibrateButton = screen.getByRole("button", { name: "执行校色" });
    await waitFor(() => expect(calibrateButton).not.toBeDisabled());
    fireEvent.click(calibrateButton);

    const topLeftCorner = await screen.findByRole("button", { name: "色卡角点 1" });
    fireEvent.pointerDown(topLeftCorner, { clientX: 10, clientY: 10 });
    fireEvent.pointerMove(window, { clientX: 35, clientY: 40 });
    fireEvent.pointerUp(window);

    await act(async () => {
      resolvePending(resolveCalibration, {
        calibrated_preview_url: "/api/files/stale-preview.jpg",
        calibrated_full_file_id: "stale-full-id",
        overlay_url: "/api/files/stale-overlay.jpg",
        full_width: 800,
        full_height: 600,
        preview_width: 400,
        preview_height: 300,
        patch_points: [],
        display_summary: summary,
      });
    });

    await waitFor(() => expect(colorcheckerRelease).toHaveBeenCalledWith("stale-full-id"));
    expect(receiveCalibrated).not.toHaveBeenCalled();
  });

  it("renews a pending full artifact while showing confirmation", async () => {
    renderDialog({
      phase: "confirming",
      calibratedPreviewUrl: "/api/files/calibrated-preview.jpg",
      colorcheckerFullFileId: "pending-full-id",
      calibrationSummary: summary,
    });

    await waitFor(() => expect(colorcheckerTouch).toHaveBeenCalledWith("pending-full-id"));
  });

  it("passes source preview context when accepting a confirmed calibration", async () => {
    const confirmCalibrated = vi.fn();
    renderDialog({
      phase: "confirming",
      calibratedPreviewUrl: "/api/files/calibrated-preview.jpg",
      colorcheckerFullFileId: "pending-full-id",
      calibrationSummary: summary,
      confirmCalibrated,
    });

    const originalImage = await screen.findByAltText("原图");
    expect(originalImage).toHaveAttribute("src", "/api/files/source-chart.png.jpg");

    fireEvent.click(screen.getByRole("button", { name: "确认使用" }));

    expect(confirmCalibrated).toHaveBeenCalledWith({
      sourceFileId: "source-chart.png",
      sourcePreviewUrl: "/api/files/source-chart.png.jpg",
    });
  });

  it("renews displayed warp and overlay preview URLs while mounted", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);

    renderDialog();

    await expectDafanDetectCalled("source-chart.png");
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/files/source-chart.png.jpg", {
        cache: "no-store",
      }),
    );
    const warpButton = await screen.findByRole("button", { name: "生成预览" });
    await waitFor(() => expect(warpButton).not.toBeDisabled());
    fireEvent.click(warpButton);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/files/warp.png", {
        cache: "no-store",
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "执行校色" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/files/overlay.png", {
        cache: "no-store",
      }),
    );
  });

  it("keeps the extractor modal closed after closeDialog clears the phase", () => {
    useExtractorStore.setState({
      imageFile,
      colorchecker_enabled: true,
      colorchecker_phase: null,
    });

    render(
      <I18nProvider>
        <ColorcheckerConfirmDialogExtractor />
      </I18nProvider>,
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens the extractor modal only for active calibration phases", () => {
    useExtractorStore.setState({
      imageFile,
      colorchecker_enabled: true,
      colorchecker_phase: "calibrating",
    });

    render(
      <I18nProvider>
        <ColorcheckerConfirmDialogExtractor />
      </I18nProvider>,
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("closes the store dialog when the inline tool unmounts", async () => {
    const closeDialog = vi.fn();
    const { unmount } = renderDialog({
      phase: "confirming",
      calibratedPreviewUrl: "/api/files/calibrated-preview.jpg",
      colorcheckerFullFileId: "pending-full-id",
      calibrationSummary: summary,
      closeDialog,
    });

    unmount();

    await waitFor(() => expect(closeDialog).toHaveBeenCalledTimes(1));
  });

  it("does not cancel one dialog cleanup when another instance mounts", async () => {
    const firstClose = vi.fn();
    const secondClose = vi.fn();
    const first = renderDialog({
      phase: "confirming",
      calibratedPreviewUrl: "/api/files/first-preview.jpg",
      colorcheckerFullFileId: "first-full-id",
      calibrationSummary: summary,
      closeDialog: firstClose,
    });

    first.unmount();
    renderDialog({
      phase: "confirming",
      calibratedPreviewUrl: "/api/files/second-preview.jpg",
      colorcheckerFullFileId: "second-full-id",
      calibrationSummary: summary,
      closeDialog: secondClose,
    });

    await waitFor(() => expect(firstClose).toHaveBeenCalledTimes(1));
    expect(secondClose).not.toHaveBeenCalled();
  });
});
