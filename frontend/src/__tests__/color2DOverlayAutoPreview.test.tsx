import type { HTMLAttributes, ReactNode } from "react";
import { act, render, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ModelingMode } from "../api/types";
import Color2DOverlay from "../components/widget/Color2DOverlay";
import { useAutoPreview } from "../hooks/useAutoPreview";
import { DEFAULT_STATE, useConverterStore } from "../stores/converter";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: HTMLAttributes<HTMLDivElement> & { children?: ReactNode }) => (
      <div {...props}>{children}</div>
    ),
  },
}));

vi.mock("../components/sections/ColorPreview2D", () => ({
  default: () => <div data-testid="color-preview-2d" />,
}));
vi.mock("../components/sections/PalettePanel", () => ({
  default: () => <div data-testid="palette-panel" />,
}));
vi.mock("../components/sections/LutColorGrid", () => ({
  default: () => <div data-testid="lut-color-grid" />,
}));

describe("Color2DOverlay auto-preview ownership", () => {
  const submitPreview = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    useConverterStore.setState({
      ...DEFAULT_STATE,
      imageFile: new File(["pixels"], "material.png", { type: "image/png" }),
      source_version: "material",
      selectedMaterialDirNames: ["profile/yellow", "profile/black"],
      materialLayerCount: 10,
      materialLayerHeightMm: 0.04,
      materialBackingMaterialDirName: "profile/black",
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      quantize_colors: 48,
      cropModalOpen: false,
      hasManualPreview: true,
      sessionId: "material-session",
      previewImageUrl: "/api/files/preview.png",
      previewGlbUrl: "/api/files/preview.glb",
      submitPreview,
    });
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("lets the debounced refresh submit exactly once while the overlay is open", () => {
    renderHook(() => useAutoPreview());
    render(<Color2DOverlay />);

    act(() => {
      vi.advanceTimersByTime(20);
    });
    expect(submitPreview).not.toHaveBeenCalled();

    act(() => {
      useConverterStore.getState().setQuantizeColors(8);
    });
    expect(submitPreview).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(299);
    });
    expect(submitPreview).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(1);
    });

    expect(submitPreview).toHaveBeenCalledTimes(1);
  });
});
