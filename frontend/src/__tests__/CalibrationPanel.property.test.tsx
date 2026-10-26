/**
 * Property 2: Block_Size and Gap sliders follow mode-specific enable rules.
 *
 * Tag: Feature: calibration-swatch-config, Property 2: Block_Size and Gap sliders follow mode rules
 *
 * **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 5.1**
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import * as fc from "fast-check";
import CalibrationPanel from "../components/CalibrationPanel";
import { useCalibrationStore } from "../stores/calibrationStore";
import { CalibrationColorMode } from "../api/types";

vi.mock("../api/calibration", () => ({
  calibrationGenerate: vi.fn(),
  generateSingleStageKit: vi.fn(),
}));

beforeEach(() => {
  useCalibrationStore.setState({
    workflow: "legacy",
    color_mode: CalibrationColorMode.FOUR_COLOR_CMYW,
    block_size: 5,
    gap: 0.84,
    backing_thickness: 1.2,
    eight_color_full_export: false,
    singleStageLayerHeightMm: 0.08,
    isLoading: false,
    error: null,
    downloadUrl: null,
    previewImageUrl: null,
    modelUrl: null,
    statusMessage: null,
  });
});

afterEach(() => {
  cleanup();
});

// Generator: enumerate all CalibrationColorMode values
const arbCalibrationColorMode = fc.constantFrom(
  ...Object.values(CalibrationColorMode)
);

describe("Feature: calibration-swatch-config, Property 2: Block_Size, Gap, and Backing Thickness sliders follow mode rules", () => {
  it("All sliders are always enabled regardless of color mode", () => {
    fc.assert(
      fc.property(arbCalibrationColorMode, (mode) => {
        useCalibrationStore.setState({ color_mode: mode });

        const { unmount } = render(<CalibrationPanel />);

        const sliders = screen.getAllByRole("slider");

        expect(sliders.length).toBeGreaterThanOrEqual(3);

        sliders.forEach((slider) => expect(slider).not.toBeDisabled());

        unmount();
      }),
      { numRuns: 100 }
    );
  }, 15000);
});
