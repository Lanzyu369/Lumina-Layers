import type { ReactNode } from "react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { useConverterStore } from "../../stores/converter";
import { buildLayerImagesSourceKey } from "../../stores/converter/store";
import ActionBar from "../sections/ActionBar";

let capturedCanvasPreviewSurfaceProps: Record<string, unknown> | null = null;
let capturedSlicerSelectorProps: Record<string, unknown> | null = null;

// Mock child components with complex dependencies
vi.mock("../sections/BedSizeSelector", () => ({
  default: () => <div data-testid="bed-size-selector" />,
}));

vi.mock("../sections/SlicerSelector", () => ({
  default: (props: Record<string, unknown>) => {
    capturedSlicerSelectorProps = props;
    return <div data-testid="slicer-selector" />;
  },
}));

vi.mock("../ui/CanvasPreviewSurface", () => ({
  default: (props: Record<string, unknown>) => {
    capturedCanvasPreviewSurfaceProps = props;
    return (
      <div data-testid="canvas-preview-surface-mock">
        <div role="img" aria-label={String(props.alt ?? "")} data-src={String(props.src ?? "")} />
        {props.overlay ? <div data-testid="canvas-preview-overlay">{props.overlay as ReactNode}</div> : null}
        {props.floatingOverlay ? <div data-testid="canvas-preview-floating-overlay">{props.floatingOverlay as ReactNode}</div> : null}
      </div>
    );
  },
}));

function makeFile(name: string, type = "image/png"): File {
  return new File(["dummy"], name, { type });
}

describe("ActionBar — auto batch mode", () => {
  beforeEach(() => {
    capturedCanvasPreviewSurfaceProps = null;
    capturedSlicerSelectorProps = null;
    useConverterStore.setState({
      batchMode: false,
      batchFiles: [],
      batchLoading: false,
      batchResult: null,
      imageFile: null,
      source_version: "legacy",
      lut_name: "",
      nativeBrandGroups: [],
      nativeBrandGroupsLoading: false,
      selectedNativeBrandKey: "",
      selectedNativeDbNames: [],
      isLoading: false,
      error: null,
      previewImageUrl: null,
      previewBaseImageUrl: null,
      sessionId: null,
      layerImages: [],
      layerImagesLoading: false,
      layerImagesSourceKey: null,
      fetchLayerImages: vi.fn(),
      modelUrl: null,
      threemfDiskPath: null,
      downloadUrl: null,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  // --- SingleMode (batchFiles empty → batchMode false) ---

  it("shows preview and generate buttons in SingleMode (no batchFiles)", () => {
    useConverterStore.setState({ batchMode: false, batchFiles: [] });
    render(<ActionBar />);
    expect(screen.getByText("预览")).toBeInTheDocument();
    expect(screen.getByText("生成")).toBeInTheDocument();
    expect(screen.queryByText("批量生成")).not.toBeInTheDocument();
  });

  // --- BatchMode (batchFiles has items → batchMode true) ---

  it("shows batch generate button and hides preview/generate when batchFiles has items", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png"), makeFile("b.png")],
      lut_name: "test_lut",
    });
    render(<ActionBar />);
    expect(screen.getByText("批量生成")).toBeInTheDocument();
    expect(screen.queryByText("预览")).not.toBeInTheDocument();
    expect(screen.queryByText("生成")).not.toBeInTheDocument();
  });

  // --- Auto-maintained batchMode via handleFilesSelect ---

  it("auto-enters BatchMode via handleFilesSelect with multiple files", () => {
    // Start from empty state
    useConverterStore.setState({ batchMode: false, batchFiles: [], imageFile: null });

    // Use handleFilesSelect to add multiple files (auto-sets batchMode)
    useConverterStore.getState().handleFilesSelect([makeFile("a.png"), makeFile("b.png")]);

    const state = useConverterStore.getState();
    expect(state.batchMode).toBe(true);
    expect(state.batchFiles).toHaveLength(2);

    render(<ActionBar />);
    expect(screen.getByText("批量生成")).toBeInTheDocument();
    expect(screen.queryByText("预览")).not.toBeInTheDocument();
  });

  // --- Disabled conditions ---

  it("disables batch generate button when batchFiles is empty", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [],
      lut_name: "test_lut",
    });
    render(<ActionBar />);
    const btn = screen.getByText("批量生成").closest("button")!;
    expect(btn).toBeDisabled();
  });

  it("disables batch generate button when lut_name is empty", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      lut_name: "",
    });
    render(<ActionBar />);
    const btn = screen.getByText("批量生成").closest("button")!;
    expect(btn).toBeDisabled();
  });

  it("disables batch generate button when batchLoading is true", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      lut_name: "test_lut",
      batchLoading: true,
    });
    render(<ActionBar />);
    const btn = screen.getByText("批量生成").closest("button")!;
    expect(btn).toBeDisabled();
  });

  // --- Enabled condition ---

  it("enables batch generate button when files exist and lut_name is set", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      lut_name: "test_lut",
      batchLoading: false,
    });
    render(<ActionBar />);
    const btn = screen.getByText("批量生成").closest("button")!;
    expect(btn).not.toBeDisabled();
  });

  it("enables batch generate button for material archive source without a legacy LUT", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      source_version: "material",
      lut_name: "",
      selectedMaterialDirNames: ["brand/red", "brand/white"],
      materialLayerCount: 7,
      materialLayerHeightMm: 0.06,
      batchLoading: false,
    });

    render(<ActionBar />);

    const btn = screen.getByText("批量生成").closest("button")!;
    expect(btn).not.toBeDisabled();
  });

  it("enables batch generate button for native reverse LUT source without a legacy LUT", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      source_version: "native",
      lut_name: "",
      selectedNativeBrandKey: "bambulab_pla",
      selectedNativeDbNames: ["DB-A", "DB-B"],
      color_layers: 5,
      layer_height_mm: 0.08,
      nativeBrandGroups: [
        {
          brand_key: "bambulab_pla",
          material_type: "PLA",
          vendor: "Bambu Lab",
          display_name: "Bambu PLA",
          db_options: [
            { name: "DB-A", path: "/DB-A.json", color_mode: "8-Color Max", fingerprint: "fp-DB-A" },
            { name: "DB-B", path: "/DB-B.json", color_mode: "8-Color Max", fingerprint: "fp-DB-B" },
          ],
          default_db_names: ["DB-A", "DB-B"],
          supported_modes: [{ color_layers: 5, layer_height_mm: 0.08 }],
        },
      ],
      batchLoading: false,
    } as never);

    render(<ActionBar />);

    const btn = screen.getByText("批量生成").closest("button")!;
    expect(btn).not.toBeDisabled();
  });

  it("shows source-specific batch hints when material or native source is incomplete", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      source_version: "material",
      lut_name: "",
      selectedMaterialDirNames: [],
    });
    const { rerender } = render(<ActionBar />);
    expect(screen.getByText("请先添加图片并选择耗材")).toBeInTheDocument();

    useConverterStore.setState({
      source_version: "native",
      selectedNativeBrandKey: "",
      selectedNativeDbNames: [],
      nativeBrandGroups: [],
    });
    rerender(<ActionBar />);
    expect(screen.getByText("请先添加图片并选择品牌和数据库")).toBeInTheDocument();
  });

  it("reuses the slicer-open action for batch merged 3MF generation", async () => {
    const submitBatch = vi.fn(async () => {
      useConverterStore.setState({ threemfDiskPath: "/tmp/batch-merged.3mf" });
    });
    const submitFullPipeline = vi.fn();
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png"), makeFile("b.png")],
      lut_name: "test_lut",
      batchLoading: false,
      largeFormatEnabled: true,
      submitBatch,
      submitFullPipeline,
    });

    render(<ActionBar />);

    expect(capturedSlicerSelectorProps?.canSubmit).toBe(true);
    expect(capturedSlicerSelectorProps?.largeFormat).toBe(false);
    const onAutoGenerate = capturedSlicerSelectorProps?.onAutoGenerate as
      | (() => Promise<string | null>)
      | undefined;
    expect(onAutoGenerate).toBeTypeOf("function");

    await expect(onAutoGenerate!()).resolves.toBe("/tmp/batch-merged.3mf");
    expect(submitBatch).toHaveBeenCalledOnce();
    expect(submitFullPipeline).not.toHaveBeenCalled();
  });

  it("enables preview but keeps generate disabled before a native bundle session exists even when lut_name is empty", () => {
    useConverterStore.setState({
      batchMode: false,
      batchFiles: [],
      imageFile: makeFile("native.png"),
      source_version: "native",
      lut_name: "",
      selectedNativeBrandKey: "bambulab_pla",
      selectedNativeDbNames: ["DB-A", "DB-B"],
      nativeBrandGroups: [
        {
          brand_key: "bambulab_pla",
          material_type: "PLA",
          vendor: "Bambu Lab",
          display_name: "Bambu PLA",
          db_options: [
            { name: "DB-A", path: "/DB-A.json", color_mode: "8-Color Max", fingerprint: "fp-DB-A" },
            { name: "DB-B", path: "/DB-B.json", color_mode: "8-Color Max", fingerprint: "fp-DB-B" },
          ],
          default_db_names: ["DB-A", "DB-B"],
          supported_modes: [{ color_layers: 5, layer_height_mm: 0.08 }],
        },
      ],
    } as never);

    render(<ActionBar />);

    const previewBtn = screen.getByText("预览").closest("button")!;
    const generateBtn = screen.getByText("生成").closest("button")!;
    expect(previewBtn).not.toBeDisabled();
    expect(generateBtn).toBeDisabled();
  });

  // --- BatchResultSummary ---

  it("shows BatchResultSummary when batchResult is not null", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      lut_name: "test_lut",
      batchResult: {
        status: "ok",
        message: "done",
        download_url: "/output/batch.3mf",
        preview_3d_url: null,
        preview_items: [],
        results: [{ filename: "a.png", status: "success" }],
        warnings: [],
      },
    });
    const { container } = render(<ActionBar />);
    // BatchResultSummary renders — text is split across child elements
    const text = container.textContent ?? "";
    expect(text).toContain("成功");
    expect(text).toContain("总计");
    expect(screen.getByLabelText("下载批量 3MF")).toBeInTheDocument();
  });

  it("does not show BatchResultSummary when batchResult is null", () => {
    useConverterStore.setState({
      batchMode: true,
      batchFiles: [makeFile("a.png")],
      lut_name: "test_lut",
      batchResult: null,
    });
    render(<ActionBar />);
    expect(screen.queryByText(/成功.*总计/)).not.toBeInTheDocument();
  });

  it("renders cumulative multi-select overlay on top of the current highlighted preview image", () => {
    useConverterStore.setState({
      selectionMode: "multi-select",
      sessionId: "session-1",
      previewImageUrl: "/api/files/highlight-last-region",
      previewBaseImageUrl: "/api/files/base-preview",
      preview_width_mm: 60,
      previewPixelWidth: 600,
      previewPixelHeight: 400,
      selectedRegions: [
        {
          regionId: "region-a",
          colorHex: "#ff0000",
          pixelCount: 10,
          previewUrl: "/api/files/highlight-region-a",
          contours: [[[10, 10], [20, 10], [20, 20], [10, 20]]],
        },
        {
          regionId: "region-b",
          colorHex: "#00ff00",
          pixelCount: 20,
          previewUrl: "/api/files/highlight-region-b",
          contours: [[[30, 5], [40, 5], [40, 15], [30, 15]]],
        },
      ],
    });

    render(<ActionBar />);

    const previewImage = screen.getByRole("img", { name: "预览结果" });
    expect(previewImage).toHaveAttribute("data-src", "/api/files/highlight-last-region");
    expect(screen.getByTestId("preview-multi-select-overlay")).toBeInTheDocument();
    expect(screen.getAllByTestId("preview-multi-select-polygon")).toHaveLength(1);
  });

  it("redraws the 2D hover magnifier after the preview buffer image loads asynchronously", async () => {
    vi.useFakeTimers();

    const drawImageMock = vi.fn();
    const context2d = {
      clearRect: vi.fn(),
      drawImage: drawImageMock,
      getImageData: vi.fn(() => ({ data: new Uint8ClampedArray([255, 0, 0, 255]) })),
      beginPath: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      stroke: vi.fn(),
      canvas: { width: 152, height: 152 },
      set imageSmoothingEnabled(_value: boolean) {},
      set strokeStyle(_value: string) {},
      set lineWidth(_value: number) {},
    } as unknown as CanvasRenderingContext2D;
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
      ((contextId: string) => (contextId === "2d" ? context2d : null)) as typeof HTMLCanvasElement.prototype.getContext,
    );

    useConverterStore.setState({
      batchMode: false,
      imageFile: makeFile("preview.png"),
      lut_name: "test_lut",
      sessionId: null,
      previewImageUrl: "/api/files/preview.png",
      previewBaseImageUrl: "/api/files/preview.png",
      previewPixelWidth: 300,
      previewPixelHeight: 200,
      layerImages: [],
      layerImagesLoading: true,
    });

    render(<ActionBar />);

    const hoverHandler = capturedCanvasPreviewSurfaceProps?.onHoverSample as
      | ((sample: {
        containerX: number;
        containerY: number;
        containerWidth: number;
        containerHeight: number;
        containerLeft: number;
        containerTop: number;
        pixelX: number;
        pixelY: number;
        naturalWidth: number;
        naturalHeight: number;
      } | null) => void)
      | undefined;
    const surfaceReadyHandler = capturedCanvasPreviewSurfaceProps?.onSurfaceReady as
      | ((payload: {
        image: HTMLImageElement;
        previewBuffer: {
          width: number;
          height: number;
          context: CanvasRenderingContext2D;
        } | null;
      } | null) => void)
      | undefined;

    expect(hoverHandler).toBeTypeOf("function");
    expect(surfaceReadyHandler).toBeTypeOf("function");

    act(() => {
      hoverHandler?.({
        containerX: 96,
        containerY: 72,
        containerWidth: 320,
        containerHeight: 220,
        containerLeft: 40,
        containerTop: 60,
        pixelX: 200,
        pixelY: 120,
        naturalWidth: 600,
        naturalHeight: 400,
      });
      vi.advanceTimersByTime(180);
    });

    expect(screen.getByTestId("action-hover-inspector")).toBeInTheDocument();
    expect(drawImageMock.mock.calls.some((call) => call.length >= 9)).toBe(false);

    const previewImage = document.createElement("img");
    Object.defineProperty(previewImage, "naturalWidth", { value: 600, configurable: true });
    Object.defineProperty(previewImage, "naturalHeight", { value: 400, configurable: true });
    Object.defineProperty(previewImage, "width", { value: 600, configurable: true });
    Object.defineProperty(previewImage, "height", { value: 400, configurable: true });

    act(() => {
      surfaceReadyHandler?.({
        image: previewImage,
        previewBuffer: {
          width: 600,
          height: 400,
          context: context2d,
        },
      });
    });

    await act(async () => {
      await Promise.resolve();
    });

    expect(drawImageMock.mock.calls.some((call) => call.length >= 9)).toBe(true);

    const magnifierDrawCall = [...drawImageMock.mock.calls].reverse().find((call) => call.length >= 9);
    expect(magnifierDrawCall).toBeDefined();
    expect(magnifierDrawCall?.[1]).toBeCloseTo(174.6667, 3);
    expect(magnifierDrawCall?.[2]).toBeCloseTo(94.6667, 3);
  });

  it("uses previewBaseImageUrl when puzzle overlay is active", () => {
    useConverterStore.setState({
      batchMode: false,
      imageFile: makeFile("preview.png"),
      lut_name: "test_lut",
      sessionId: "session-1",
      previewImageUrl: "/api/files/preview-bed.png",
      previewBaseImageUrl: "/api/files/preview-raw.png",
      puzzleOverlayUrl: "/api/files/puzzle-overlay.png",
      layerImages: [],
      layerImagesLoading: false,
    });

    render(<ActionBar />);

    expect(capturedCanvasPreviewSurfaceProps?.src).toBe("/api/files/preview-raw.png");
  });

  it("refetches layer images when the 2D preview changes within the same session", async () => {
    const fetchLayerImages = vi.fn();

    useConverterStore.setState({
      batchMode: false,
      imageFile: makeFile("preview.png"),
      lut_name: "test_lut",
      sessionId: "session-1",
      previewImageUrl: "/api/files/preview-a.png",
      previewBaseImageUrl: "/api/files/preview-a.png",
      layerImages: [{ layer_index: 0, name: "Layer 1", url: "/api/files/layer-a" }],
      layerImagesLoading: false,
      layerImagesOpen: true,
      fetchLayerImages,
    });
    useConverterStore.setState({
      layerImagesSourceKey: buildLayerImagesSourceKey(useConverterStore.getState()),
    });

    render(<ActionBar />);

    expect(fetchLayerImages).not.toHaveBeenCalled();

    act(() => {
      useConverterStore.setState({
        previewImageUrl: "/api/files/preview-b.png",
        previewBaseImageUrl: "/api/files/preview-b.png",
      });
    });

    await waitFor(() => {
      expect(fetchLayerImages).toHaveBeenCalledWith(
        buildLayerImagesSourceKey(useConverterStore.getState()),
      );
    });
  });

  it("does not refetch layer images for highlight-only preview churn when the base preview is unchanged", async () => {
    const fetchLayerImages = vi.fn();

    useConverterStore.setState({
      batchMode: false,
      imageFile: makeFile("preview.png"),
      lut_name: "test_lut",
      sessionId: "session-1",
      previewImageUrl: "/api/files/highlight-a.png",
      previewBaseImageUrl: "/api/files/preview-base.png",
      layerImages: [{ layer_index: 0, name: "Layer 1", url: "/api/files/layer-a" }],
      layerImagesLoading: false,
      layerImagesOpen: true,
      fetchLayerImages,
    });
    useConverterStore.setState({
      layerImagesSourceKey: buildLayerImagesSourceKey(useConverterStore.getState()),
    });

    render(<ActionBar />);

    act(() => {
      useConverterStore.setState({
        previewImageUrl: "/api/files/highlight-b.png",
      });
    });

    await act(async () => {
      await Promise.resolve();
    });

    expect(fetchLayerImages).not.toHaveBeenCalled();
  });
});
