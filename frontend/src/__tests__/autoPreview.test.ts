import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { DEFAULT_STATE, useConverterStore } from "../stores/converter";
import { useAutoPreview } from "../hooks/useAutoPreview";
import { ModelingMode } from "../api/types";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";

function fakeFile(name = "test.png"): File {
  return new File(["pixels"], name, { type: "image/png" });
}

describe("useAutoPreview", () => {
  const mockSubmitPreview = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);

  function establishMaterialPreviewBaseline() {
    useConverterStore.setState({
      imageFile: fakeFile("material-preview.png"),
      source_version: "material",
      lut_name: "",
      lut_names: [],
      selectedMaterialDirNames: ["profile/yellow", "profile/black"],
      materialLayerCount: 10,
      materialLayerHeightMm: 0.04,
      materialBackingMaterialDirName: "profile/black",
      target_width_mm: 148,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      quantize_colors: 48,
      high_precision_3d_preview: false,
      enable_cleanup: true,
      enable_outline: false,
      outline_width: 2,
      hue_enable: false,
      chroma_gate: 15,
      use_lut_constrained: false,
      auto_dynamic_range: false,
      largeFormatEnabled: false,
      cropModalOpen: false,
      hasManualPreview: true,
      sessionId: "material-session-old",
      previewImageUrl: "/api/files/preview-old.png",
      previewGlbUrl: "/api/files/preview-old.glb",
      palette: [
        {
          quantized_hex: "112233",
          matched_hex: "445566",
          pixel_count: 10,
          percentage: 100,
        },
      ],
      layerImages: [
        { layer_index: 0, name: "layer-1", url: "/api/files/layer-old.png" },
      ],
      submitPreview: mockSubmitPreview,
    });
  }

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    useConverterStore.setState({
      ...DEFAULT_STATE,
      imageFile: null,
      source_version: "legacy",
      lut_name: "",
      lut_names: [],
      selectedMaterialDirNames: [],
      selectedNativeBrandKey: "",
      selectedNativeDbNames: [],
      submitPreview: mockSubmitPreview,
    });
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not trigger when hasManualPreview is false", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      useConverterStore.setState({ imageFile: fakeFile(), lut_name: "my-lut" });
      vi.advanceTimersByTime(500);
    });

    expect(mockSubmitPreview).not.toHaveBeenCalled();
  });

  it("does not re-trigger immediately after manual preview baseline is established", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      useConverterStore.setState({
        imageFile: fakeFile(),
        lut_name: "my-lut",
        hasManualPreview: true,
      });
      vi.advanceTimersByTime(500);
    });

    expect(mockSubmitPreview).not.toHaveBeenCalled();
  });

  it("triggers submitPreview 300ms after a tracked param changes on an established baseline", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      useConverterStore.setState({
        imageFile: fakeFile(),
        lut_name: "my-lut",
        hasManualPreview: true,
      });
    });

    act(() => {
      useConverterStore.setState({ hue_enable: true });
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
  });

  it("does NOT trigger while cropModalOpen is true, and only triggers after baseline re-established plus a new change", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      useConverterStore.setState({
        imageFile: fakeFile(),
        lut_name: "my-lut",
        hasManualPreview: true,
        cropModalOpen: true,
      });
      vi.advanceTimersByTime(500);
    });

    expect(mockSubmitPreview).not.toHaveBeenCalled();

    act(() => {
      useConverterStore.setState({ cropModalOpen: false });
      useConverterStore.setState({ chroma_gate: 16 });
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(mockSubmitPreview).toHaveBeenCalledTimes(0);

    act(() => {
      useConverterStore.setState({ hue_enable: true });
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
  });

  it("re-triggers when a new image is uploaded after baseline and subsequent change", () => {
    renderHook(() => useAutoPreview());

    const file1 = fakeFile("img1.png");
    const file2 = fakeFile("img2.png");

    act(() => {
      useConverterStore.setState({
        imageFile: file1,
        lut_name: "my-lut",
        hasManualPreview: true,
      });
    });

    act(() => {
      useConverterStore.setState({ hue_enable: true });
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);

    act(() => {
      useConverterStore.setState({ imageFile: file2 });
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).toHaveBeenCalledTimes(2);
  });

  it("does not trigger sync-external-store loops for native bundle state", () => {
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => {
      renderHook(() => useAutoPreview());

      act(() => {
        useConverterStore.setState({
          imageFile: fakeFile(),
          source_version: "native",
          lut_name: "",
          selectedNativeBrandKey: "brand-a",
          selectedNativeDbNames: ["db-1"],
          color_layers: 5,
          layer_height_mm: 0.08,
          hasManualPreview: true,
        });
      });

      act(() => {
        vi.advanceTimersByTime(500);
      });
    }).not.toThrow();

    expect(
      consoleErrorSpy.mock.calls.some(
        ([message]) =>
          typeof message === "string" &&
          (
            message.includes("getSnapshot should be cached") ||
            message.includes("Maximum update depth exceeded")
          ),
      ),
    ).toBe(false);

    consoleErrorSpy.mockRestore();
  });

  it("invalidates a stale material preview as soon as quantize colors change", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
    });

    act(() => {
      useConverterStore.getState().setQuantizeColors(8);
    });

    const state = useConverterStore.getState();
    expect(state.sessionId).toBeNull();
    expect(state.previewImageUrl).toBeNull();
    expect(state.previewGlbUrl).toBeNull();
    expect(state.layerImages).toEqual([]);
    expect(state.hasManualPreview).toBe(true);
  });

  it("regenerates a material preview after the quantize count changes", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
    });

    act(() => {
      useConverterStore.getState().setQuantizeColors(8);
    });
    act(() => {
      vi.advanceTimersByTime(299);
    });
    expect(mockSubmitPreview).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
  });

  it("does not regenerate when a material preview response synchronizes compatibility fields", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
    });

    act(() => {
      useConverterStore.setState({
        color_layers: 10,
        layer_height_mm: 0.04,
      });
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).not.toHaveBeenCalled();
    expect(useConverterStore.getState().sessionId).toBe(
      "material-session-old",
    );
  });

  it.each([
    ["modeling mode", { modeling_mode: ModelingMode.PIXEL }],
    ["cleanup", { enable_cleanup: false }],
    ["backing material", { materialBackingMaterialDirName: "profile/yellow" }],
    ["LUT-constrained matching", { use_lut_constrained: true }],
    ["automatic dynamic range", { auto_dynamic_range: true }],
    ["high-precision 3D", { high_precision_3d_preview: true }],
    ["target width", { target_width_mm: 160 }],
    ["outline", { enable_outline: true }],
  ])("regenerates a material preview after %s changes", (_label, patch) => {
    renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
    });

    act(() => {
      useConverterStore.setState(patch);
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
  });

  it.each([
    [
      "selection",
      () =>
        useConverterStore.getState().setSelectedMaterialDirNames([
          "profile/white",
          "profile/black",
        ]),
    ],
    [
      "layer count",
      () => useConverterStore.getState().setMaterialLayerCount(8),
    ],
    [
      "layer height",
      () => useConverterStore.getState().setMaterialLayerHeightMm(0.08),
    ],
  ])(
    "regenerates after the material %s setter resets the preview session",
    (_label, change) => {
      renderHook(() => useAutoPreview());

      act(() => {
        establishMaterialPreviewBaseline();
      });
      act(() => {
        change();
      });
      act(() => {
        vi.advanceTimersByTime(300);
      });

      expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
    },
  );

  it("clears stale output without regenerating when the source becomes incomplete", () => {
    renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
    });
    act(() => {
      useConverterStore.getState().setSelectedMaterialDirNames([]);
      vi.advanceTimersByTime(300);
    });

    expect(useConverterStore.getState().previewImageUrl).toBeNull();
    expect(useConverterStore.getState().previewGlbUrl).toBeNull();
    expect(mockSubmitPreview).not.toHaveBeenCalled();
  });

  it.each([
    ["solver cache resolution", { enableSolverCacheGridSelection: true }],
    ["SVG sampling density", { svgPixelsPerMm: 12 }],
  ])("regenerates a material preview after %s changes", (_label, patch) => {
    renderHook(() => useAutoPreview());

    act(() => {
      establishMaterialPreviewBaseline();
    });

    act(() => {
      useSettingsStore.setState(patch);
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
  });
});
