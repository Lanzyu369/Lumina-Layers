import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  colorcheckerCalibrate,
  colorcheckerDetectChart,
  colorcheckerWarpPreview,
  type ColorcheckerDisplaySummary,
} from "../api/extractor";
import { ColorcheckerConfirmDialogInner } from "../components/ColorcheckerConfirmDialog";
import { I18nProvider } from "../i18n/context";
import { useSettingsStore } from "../stores/settingsStore";

vi.mock("../api/extractor", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/extractor")>();
  return {
    ...actual,
    colorcheckerCalibrate: vi.fn(),
    colorcheckerDetectChart: vi.fn(),
    colorcheckerWarpPreview: vi.fn(),
  };
});

const imageFile = new File([new Uint8Array([1, 2, 3])], "chart.png", {
  type: "image/png",
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

describe("ColorcheckerConfirmDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSettingsStore.setState({ language: "zh" });
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
    expect(screen.getAllByText("校色质量提示")).toHaveLength(2);
    expect(screen.getByText(/平均 ΔE00 为 2.0362/)).toBeInTheDocument();
  });

  it("submits advanced algorithm options and dragged corner coordinates", async () => {
    renderDialog();

    await waitFor(() => expect(colorcheckerDetectChart).toHaveBeenCalledWith(imageFile, "4x6"));

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
    expect(call[1][0]).toEqual([30, 35]);
    expect(call[4]).toEqual({
      calibrationMode: "root_polynomial",
      method: "mean",
      grayAffineMode: "auto",
      sampleRadius: 12,
      blurRadius: 0,
    });
  });
});
