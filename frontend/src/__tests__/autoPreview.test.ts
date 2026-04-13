import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useConverterStore } from "../stores/converter";
import { useAutoPreview } from "../hooks/useAutoPreview";

function fakeFile(name = "test.png"): File {
  return new File(["pixels"], name, { type: "image/png" });
}

describe("useAutoPreview", () => {
  const mockSubmitPreview = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    useConverterStore.setState({
      imageFile: null,
      source_version: "legacy",
      lut_name: "",
      selectedNativeBrandKey: "",
      selectedNativeDbNames: [],
      color_layers: null,
      layer_height_mm: null,
      cropModalOpen: false,
      hasManualPreview: false,
      hue_enable: false,
      chroma_gate: 15,
      submitPreview: mockSubmitPreview,
    });
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
});
