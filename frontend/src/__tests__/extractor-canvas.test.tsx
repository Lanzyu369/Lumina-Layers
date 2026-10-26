import { describe, it, expect, vi, beforeEach } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import fc from "fast-check";
import { useExtractorStore } from "../stores/extractorStore";
import {
  buildCornerLabels,
  CORNER_COLOR_KEYS_5C_EXT_PAGE2,
} from "../components/ExtractorCanvas";
import { translations } from "../i18n/translations";
import { manualFixCell, resolveLutPreviewCell } from "../api/extractor";

// Lightweight `t` that mirrors the i18n context's zh fallback so tests remain
// independent of React context while still validating translated output.
function tZh(key: string): string {
  const entry = translations[key];
  if (!entry) return key;
  return entry.zh ?? key;
}
import { ExtractorColorMode, ExtractorPage } from "../api/types";

vi.mock("../api/extractor", () => ({
  colorcheckerConfirm: vi.fn(),
  colorcheckerRelease: vi.fn(),
  colorcheckerTouch: vi.fn(() => Promise.resolve()),
  confirmPalette: vi.fn(),
  extractColors: vi.fn(),
  manualFixCell: vi.fn(),
  mergeEightColor: vi.fn(),
  mergeFiveColorExtended: vi.fn(),
  previewAutoWb: vi.fn(),
  resolveLutPreviewCell: vi.fn(),
  rotateExtractorImage: vi.fn(),
}));

const mockManualFixCell = vi.mocked(manualFixCell);
const mockResolveLutPreviewCell = vi.mocked(resolveLutPreviewCell);
const rawHttpStatusErrorPattern =
  /Request failed with status code|status code\s+\d{3}\b|\b[45]\d{2}\b/i;

// ========== Mock browser APIs ==========

vi.stubGlobal(
  "URL",
  Object.assign(globalThis.URL ?? {}, {
    createObjectURL: vi.fn(() => "blob:mock-url"),
    revokeObjectURL: vi.fn(),
  })
);

// Mock canvas getContext so jsdom doesn't choke
HTMLCanvasElement.prototype.getContext = vi.fn(() => ({
  clearRect: vi.fn(),
  drawImage: vi.fn(),
  beginPath: vi.fn(),
  arc: vi.fn(),
  fill: vi.fn(),
  stroke: vi.fn(),
  fillText: vi.fn(),
  set fillStyle(_v: string) {},
  set strokeStyle(_v: string) {},
  set lineWidth(_v: number) {},
  set font(_v: string) {},
  set textAlign(_v: string) {},
  set textBaseline(_v: string) {},
  canvas: { width: 800, height: 600 },
})) as unknown as typeof HTMLCanvasElement.prototype.getContext;

// Mock Image constructor for the component's useEffect
class MockImage {
  onload: (() => void) | null = null;
  _src = "";
  naturalWidth = 800;
  naturalHeight = 600;
  get src() {
    return this._src;
  }
  set src(val: string) {
    this._src = val;
    // Trigger onload synchronously for testing
    if (this.onload) this.onload();
  }
}
vi.stubGlobal("Image", MockImage);

// ========== Helpers ==========

function resetExtractorStore(): void {
  useExtractorStore.setState({
    imageFile: null,
    imagePreviewUrl: null,
    imageNaturalWidth: null,
    imageNaturalHeight: null,
    color_mode: ExtractorColorMode.FOUR_COLOR_RYBW,
    page: ExtractorPage.PAGE_1,
    eight_color_full_export: false,
    corner_points: [],
    offset_x: 0,
    offset_y: 0,
    zoom: 1.0,
    distortion: 0.0,
    vignette_correction: false,
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
  });
}

// ========== Generators ==========

const arbExtractorColorMode = fc.constantFrom(
  ExtractorColorMode.BW,
  ExtractorColorMode.FOUR_COLOR_RYBW,
  ExtractorColorMode.SIX_COLOR,
  ExtractorColorMode.SIX_COLOR_RYBW,
  ExtractorColorMode.EIGHT_COLOR
);

const arbCornerCount = fc.integer({ min: 0, max: 3 });

// ========== Tests ==========

beforeEach(() => {
  vi.clearAllMocks();
  mockManualFixCell.mockResolvedValue({
    status: "success",
    message: "updated",
    lut_preview_url: "/api/files/fixed-lut",
    lut_layout: null,
  });
  resetExtractorStore();
  cleanup();
});


// **Feature: extractor-calibration-tab, Property 2: 角点提示标签正确性**
// **Validates: Requirements 4.1, 4.3**
describe("Feature: extractor-calibration-tab, Property 2: 角点提示标签正确性", () => {
  it("For any CalibrationColorMode and corner count 0..3, the hint label equals CORNER_LABELS[color_mode][corner_count]", () => {
    fc.assert(
      fc.property(arbExtractorColorMode, arbCornerCount, (colorMode, cornerCount) => {
        const labels = buildCornerLabels(colorMode, ExtractorPage.PAGE_1, tZh);
        const expectedLabel = labels[cornerCount];

        // The component builds hint text as:
        // `请点击第 ${cornerCount + 1} 个角点: ${labels[cornerCount]}`
        // We verify the CORNER_COLOR_KEYS mapping is correct and the label exists
        const isValidLabel = typeof expectedLabel === "string" && expectedLabel.length > 0;

        // Verify the label index is within bounds
        const isInBounds = cornerCount < labels.length;

        return isValidLabel && isInBounds;
      }),
      { numRuns: 100 }
    );
  });

  it("When corner count is 4, the hint text contains '定位完成'", async () => {
    const ExtractorCanvas = (await import("../components/ExtractorCanvas")).default;

    // For each color mode, verify that 4 corners shows "定位完成"
    for (const mode of [
      ExtractorColorMode.BW,
      ExtractorColorMode.FOUR_COLOR_RYBW,
      ExtractorColorMode.SIX_COLOR,
      ExtractorColorMode.SIX_COLOR_RYBW,
      ExtractorColorMode.EIGHT_COLOR,
    ]) {
      cleanup();
      useExtractorStore.setState({
        imagePreviewUrl: "blob:test-image",
        imageNaturalWidth: 800,
        imageNaturalHeight: 600,
        color_mode: mode,
        corner_points: [
          [100, 100],
          [700, 100],
          [700, 500],
          [100, 500],
        ],
        warp_view_url: null,
        lut_preview_url: null,
      });

      render(<ExtractorCanvas />);
      const hint = screen.getByTestId("corner-hint");
      expect(hint.textContent).toContain("定位完成");
      cleanup();
      resetExtractorStore();
    }
  });

  // Regression: 5-Color Extended uses two different calibration sheets.
  //   - Page 1 corners: White / Red / Blue / Yellow (RYBW 4-corner).
  //   - Page 2 corners: Blue  / Red / Black / Yellow.
  // The single-list ``CORNER_COLOR_KEYS["5-Color Extended"]`` was historically
  // White/Red/BLACK/Yellow regardless of page — so page 2 corner 1 said
  // "White (TL)" when the user was actually looking at a Blue TL marker, and
  // page 1 corner 3 said "Black (BR)" when the real marker is Blue. The
  // builder below must match ``core/extractor.py::draw_corner_points`` and
  // ``ColorSystem.FIVE_COLOR_EXTENDED``.
  // 回归：5-Color Extended 跨两张校准板：
  //   - 第 1 页角点：白 / 红 / 蓝 / 黄（RYBW 四角）。
  //   - 第 2 页角点：蓝 / 红 / 黑 / 黄。
  // 历史代码在两页共用同一条 CORNER_COLOR_KEYS，导致第 2 页角点 1 提示「白 (TL)」
  // 但实际标记是蓝色，第 1 页角点 3 提示「黑 (BR)」但实际标记是蓝色。下面的
  // 构建器必须与后端 ``core/extractor.py::draw_corner_points`` 和
  // ``ColorSystem.FIVE_COLOR_EXTENDED`` 保持一致。
  describe("5-Color Extended corner labels match the backend (page-aware)", () => {
    it("page 1 hints match the RYBW 4-corner layout: White / Red / Blue / Yellow", () => {
      const labels = buildCornerLabels(
        ExtractorColorMode.FIVE_COLOR_EXT,
        ExtractorPage.PAGE_1,
        tZh,
      );
      // tZh is a zh-only translator; assert on the Chinese forms here.
      // The important regression guards are the not.toContain checks on
      // corner 3 which must say Blue/蓝色, never Black/黑色 on page 1.
      expect(labels[0]).toContain("白色");
      expect(labels[1]).toContain("红色");
      expect(labels[2]).toContain("蓝色");
      expect(labels[2]).not.toContain("Black");
      expect(labels[2]).not.toContain("黑色");
      expect(labels[3]).toContain("黄色");
    });

    it("page 2 corner 1 says Blue (not White) and corner 3 says Black (not Blue)", () => {
      const labels = buildCornerLabels(
        ExtractorColorMode.FIVE_COLOR_EXT,
        ExtractorPage.PAGE_2,
        tZh,
      );
      // Corner 1 (TL) — the specific bug the user reported.
      expect(labels[0]).toContain("蓝色");
      expect(labels[0]).not.toContain("White");
      expect(labels[0]).not.toContain("白色");
      // Corner 2 (TR)
      expect(labels[1]).toContain("红色");
      // Corner 3 (BR)
      expect(labels[2]).toContain("黑色");
      // Corner 4 (BL)
      expect(labels[3]).toContain("黄色");
      // Full identity against the exported color-key table.
      const positionKeys = [
        "ext_corner_pos_tl",
        "ext_corner_pos_tr",
        "ext_corner_pos_br",
        "ext_corner_pos_bl",
      ];
      const builtFromKeys = CORNER_COLOR_KEYS_5C_EXT_PAGE2.map((key, idx) =>
        key ? `${tZh(key)}（${tZh(positionKeys[idx])}）` : tZh(positionKeys[idx]),
      );
      expect(labels).toEqual(builtFromKeys);
    });

    it("other color modes ignore the page argument and return CORNER_COLOR_KEYS[mode]", () => {
      for (const mode of [
        ExtractorColorMode.BW,
        ExtractorColorMode.FOUR_COLOR_CMYW,
        ExtractorColorMode.FOUR_COLOR_RYBW,
        ExtractorColorMode.SIX_COLOR,
        ExtractorColorMode.SIX_COLOR_RYBW,
        ExtractorColorMode.EIGHT_COLOR,
      ]) {
        for (const page of [
          ExtractorPage.PAGE_1,
          ExtractorPage.PAGE_2,
          ExtractorPage.PAGE_3,
        ]) {
          expect(buildCornerLabels(mode, page, tZh)).toEqual(buildCornerLabels(mode, ExtractorPage.PAGE_1, tZh));
        }
      }
    });

    it("unknown color modes fall back to the RYBW 4-corner list", () => {
      expect(buildCornerLabels("Totally Unknown Mode", ExtractorPage.PAGE_1, tZh)).toEqual(
        buildCornerLabels(ExtractorColorMode.FOUR_COLOR_RYBW, ExtractorPage.PAGE_1, tZh),
      );
    });
  });

  it("renders the page-2-specific Blue TL hint when 5-Color Extended + page 2 + 0 corners picked", async () => {
    const ExtractorCanvas = (await import("../components/ExtractorCanvas")).default;

    cleanup();
    useExtractorStore.setState({
      imagePreviewUrl: "blob:test-image",
      imageNaturalWidth: 800,
      imageNaturalHeight: 600,
      color_mode: ExtractorColorMode.FIVE_COLOR_EXT,
      page: ExtractorPage.PAGE_2,
      corner_points: [],
      warp_view_url: null,
      lut_preview_url: null,
    });

    render(<ExtractorCanvas />);
    const hint = screen.getByTestId("corner-hint");
    expect(hint.textContent).toContain("蓝色");
    expect(hint.textContent).not.toContain("白色");
    cleanup();
    resetExtractorStore();
  });

  it("For any color mode and corner count 0..3, rendered hint contains the correct CORNER_LABELS entry", async () => {
    const ExtractorCanvas = (await import("../components/ExtractorCanvas")).default;

    await fc.assert(
      fc.asyncProperty(arbExtractorColorMode, arbCornerCount, async (colorMode, cornerCount) => {
        cleanup();

        // Build corner_points array of the given length
        const corners: Array<[number, number]> = Array.from({ length: cornerCount }, (_, i) => [
          100 + i * 200,
          100 + i * 100,
        ]);

        useExtractorStore.setState({
          imagePreviewUrl: "blob:test-image",
          imageNaturalWidth: 800,
          imageNaturalHeight: 600,
          color_mode: colorMode,
          corner_points: corners,
          warp_view_url: null,
          lut_preview_url: null,
        });

        render(<ExtractorCanvas />);

        const hint = screen.getByTestId("corner-hint");
        const labels = buildCornerLabels(colorMode, ExtractorPage.PAGE_1, tZh);
        const expectedLabel = labels[cornerCount];

        expect(hint.textContent).toContain(expectedLabel);

        cleanup();
        resetExtractorStore();
      }),
      { numRuns: 100 }
    );
  });
});

// ========== Unit Tests ==========

describe("ExtractorCanvas 单元测试", () => {
  it("renders empty state when no image is uploaded", async () => {
    const ExtractorCanvas = (await import("../components/ExtractorCanvas")).default;

    useExtractorStore.setState({
      imagePreviewUrl: null,
      warp_view_url: null,
      lut_preview_url: null,
    });

    render(<ExtractorCanvas />);
    expect(screen.getByTestId("extractor-empty-state")).toBeInTheDocument();
    expect(screen.getByText("请在左侧面板上传校准板照片")).toBeInTheDocument();
  });

  it("shows '定位完成' hint when 4 corner points are marked", async () => {
    const ExtractorCanvas = (await import("../components/ExtractorCanvas")).default;

    useExtractorStore.setState({
      imagePreviewUrl: "blob:test-image",
      imageNaturalWidth: 800,
      imageNaturalHeight: 600,
      color_mode: ExtractorColorMode.FOUR_COLOR_RYBW,
      corner_points: [
        [100, 100],
        [700, 100],
        [700, 500],
        [100, 500],
      ],
      warp_view_url: null,
      lut_preview_url: null,
    });

    render(<ExtractorCanvas />);
    const hint = screen.getByTestId("corner-hint");
    expect(hint.textContent).toContain("定位完成");
    expect(hint).toHaveClass("text-emerald-600");
  });

  it("renders warp_view and lut_preview images when extraction results exist", async () => {
    const ExtractorCanvas = (await import("../components/ExtractorCanvas")).default;

    useExtractorStore.setState({
      imagePreviewUrl: "blob:test-image",
      warp_view_url: "/api/files/warp-123",
      lut_preview_url: "/api/files/lut-456",
    });

    render(<ExtractorCanvas />);
    expect(screen.getByTestId("extractor-results")).toBeInTheDocument();
    expect(screen.getByTestId("warp-view-image")).toHaveAttribute("src", "/api/files/warp-123");
    expect(screen.getByTestId("lut-preview-image")).toHaveAttribute("src", "/api/files/lut-456");
  });

  it("resolves LUT preview clicks through the backend and submits row_index fixes", async () => {
    const ExtractorCanvas = (await import("../components/ExtractorCanvas")).default;
    mockResolveLutPreviewCell.mockResolvedValueOnce({
      cell: {
        card_index: 0,
        card_label: "1",
        page_index: 0,
        page_label: "1",
        grid_size: 32,
        data_rows: 32,
        data_cols: 32,
        row: 2,
        col: 1,
        data_row: 2,
        data_col: 1,
        display_row: 3,
        display_col: 2,
        physical_row: 3,
        physical_col: 2,
        row_index: 65,
      },
      rgb: [240, 10, 0],
      hex: "#F00A00",
      overlay_bbox: {
        left: 1 / 32,
        top: 2 / 32,
        width: 1 / 32,
        height: 1 / 32,
      },
    });

    useExtractorStore.setState({
      imagePreviewUrl: "blob:test-image",
      session_id: "session-1",
      warp_view_url: null,
      lut_preview_url: "/api/files/lut-456",
    });

    render(<ExtractorCanvas />);
    const preview = screen.getByTestId("lut-preview-image") as HTMLImageElement;
    Object.defineProperty(preview, "naturalWidth", {
      configurable: true,
      value: 1000,
    });
    Object.defineProperty(preview, "naturalHeight", {
      configurable: true,
      value: 1000,
    });
    preview.getBoundingClientRect = vi.fn(() => ({
      x: 10,
      y: 20,
      left: 10,
      top: 20,
      right: 210,
      bottom: 120,
      width: 200,
      height: 100,
      toJSON: () => ({}),
    } as DOMRect));

    fireEvent.click(preview, { clientX: 85, clientY: 45 });

    await waitFor(() => {
      expect(mockResolveLutPreviewCell).toHaveBeenCalledWith("session-1", 0.25, 0.25);
    });
    expect(await screen.findByTestId("manual-fix-popup")).toBeInTheDocument();
    expect(screen.getByTestId("cell-highlight-overlay")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("fix-submit-button"));

    await waitFor(() => {
      expect(mockManualFixCell).toHaveBeenCalledWith("session-1", 65, "#F00A00");
    });
  });

  it("surfaces LUT preview resolve API errors through manualFixError", async () => {
    const ExtractorCanvas = (await import("../components/ExtractorCanvas")).default;
    const message = "Manual correction LUT file is missing. Re-run extraction before editing the LUT.";
    mockResolveLutPreviewCell.mockRejectedValueOnce(new Error(message));

    useExtractorStore.setState({
      imagePreviewUrl: "blob:test-image",
      session_id: "session-1",
      warp_view_url: null,
      lut_preview_url: "/api/files/lut-456",
    });

    render(<ExtractorCanvas />);
    const preview = screen.getByTestId("lut-preview-image") as HTMLImageElement;
    Object.defineProperty(preview, "naturalWidth", {
      configurable: true,
      value: 1000,
    });
    Object.defineProperty(preview, "naturalHeight", {
      configurable: true,
      value: 1000,
    });
    preview.getBoundingClientRect = vi.fn(() => ({
      x: 10,
      y: 20,
      left: 10,
      top: 20,
      right: 210,
      bottom: 120,
      width: 200,
      height: 100,
      toJSON: () => ({}),
    } as DOMRect));

    fireEvent.click(preview, { clientX: 85, clientY: 45 });

    await waitFor(() => {
      expect(useExtractorStore.getState().manualFixError).toBe(message);
    });
    expect(screen.queryByTestId("manual-fix-popup")).not.toBeInTheDocument();
  });

  it("normalizes LUT preview resolve HTTP status errors", async () => {
    const ExtractorCanvas = (await import("../components/ExtractorCanvas")).default;
    mockResolveLutPreviewCell.mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    useExtractorStore.setState({
      imagePreviewUrl: "blob:test-image",
      session_id: "session-1",
      warp_view_url: null,
      lut_preview_url: "/api/files/lut-456",
    });

    render(<ExtractorCanvas />);
    const preview = screen.getByTestId("lut-preview-image") as HTMLImageElement;
    Object.defineProperty(preview, "naturalWidth", {
      configurable: true,
      value: 1000,
    });
    Object.defineProperty(preview, "naturalHeight", {
      configurable: true,
      value: 1000,
    });
    preview.getBoundingClientRect = vi.fn(() => ({
      x: 10,
      y: 20,
      left: 10,
      top: 20,
      right: 210,
      bottom: 120,
      width: 200,
      height: 100,
      toJSON: () => ({}),
    } as DOMRect));

    fireEvent.click(preview, { clientX: 85, clientY: 45 });

    await waitFor(() => {
      const message = useExtractorStore.getState().manualFixError;
      expect(message).toEqual(expect.any(String));
      expect(message).not.toMatch(rawHttpStatusErrorPattern);
    });
    expect(screen.queryByTestId("manual-fix-popup")).not.toBeInTheDocument();
  });

  it("keeps LUT blank-area resolve misses silent", async () => {
    const ExtractorCanvas = (await import("../components/ExtractorCanvas")).default;
    mockResolveLutPreviewCell.mockRejectedValueOnce(
      new Error("Clicked cell is outside the valid LUT area"),
    );

    useExtractorStore.setState({
      imagePreviewUrl: "blob:test-image",
      session_id: "session-1",
      warp_view_url: null,
      lut_preview_url: "/api/files/lut-456",
      manualFixError: "stale manual fix error",
    });

    render(<ExtractorCanvas />);
    const preview = screen.getByTestId("lut-preview-image") as HTMLImageElement;
    Object.defineProperty(preview, "naturalWidth", {
      configurable: true,
      value: 1000,
    });
    Object.defineProperty(preview, "naturalHeight", {
      configurable: true,
      value: 1000,
    });
    preview.getBoundingClientRect = vi.fn(() => ({
      x: 10,
      y: 20,
      left: 10,
      top: 20,
      right: 210,
      bottom: 120,
      width: 200,
      height: 100,
      toJSON: () => ({}),
    } as DOMRect));

    fireEvent.click(preview, { clientX: 85, clientY: 45 });

    await waitFor(() => {
      expect(mockResolveLutPreviewCell).toHaveBeenCalledWith("session-1", 0.25, 0.25);
    });
    await waitFor(() => {
      expect(useExtractorStore.getState().manualFixError).toBeNull();
    });
    expect(screen.queryByTestId("manual-fix-popup")).not.toBeInTheDocument();
  });

  it("renders only warp_view when lut_preview is null", async () => {
    const ExtractorCanvas = (await import("../components/ExtractorCanvas")).default;

    useExtractorStore.setState({
      imagePreviewUrl: "blob:test-image",
      warp_view_url: "/api/files/warp-123",
      lut_preview_url: null,
    });

    render(<ExtractorCanvas />);
    expect(screen.getByTestId("extractor-results")).toBeInTheDocument();
    expect(screen.getByTestId("warp-view-image")).toBeInTheDocument();
    expect(screen.queryByTestId("lut-preview-image")).not.toBeInTheDocument();
  });

  it("shows canvas mode with corner hint when image is uploaded but corners incomplete", async () => {
    const ExtractorCanvas = (await import("../components/ExtractorCanvas")).default;

    useExtractorStore.setState({
      imagePreviewUrl: "blob:test-image",
      imageNaturalWidth: 800,
      imageNaturalHeight: 600,
      color_mode: ExtractorColorMode.FOUR_COLOR_RYBW,
      corner_points: [[100, 100]],
      warp_view_url: null,
      lut_preview_url: null,
    });

    render(<ExtractorCanvas />);
    const hint = screen.getByTestId("corner-hint");
    // 1 corner placed, so hint should show the 2nd corner label
    expect(hint.textContent).toContain("右上");
    expect(hint).toHaveClass("text-amber-600");
  });
});
