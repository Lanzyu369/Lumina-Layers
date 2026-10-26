import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { ModelingMode } from "../api/types";
import ReliefSettings from "../components/sections/ReliefSettings";
import { DEFAULT_STATE, useConverterStore } from "../stores/converter";

describe("ReliefSettings dynamic material depth", () => {
  beforeEach(() => {
    useConverterStore.setState({
      ...DEFAULT_STATE,
      source_version: "material",
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      enable_relief: true,
      spacer_thick: 0.2,
      heightmap_max_height: 1,
      materialLayerCount: 5,
      materialDynamicLayerCountEnabled: false,
      materialMaxLayerCount: 9,
    } as never);
  });

  it("keeps the fixed layer count as the relief minimum when dynamic mode is off", () => {
    render(<ReliefSettings />);

    const slider = screen.getByRole("slider", { name: "最大高度" });
    expect(Number(slider.getAttribute("min"))).toBeCloseTo(0.2, 10);
  });

  it("uses the configured dynamic maximum as the relief minimum", () => {
    useConverterStore.setState({
      materialDynamicLayerCountEnabled: true,
      materialMaxLayerCount: 9,
    } as never);

    render(<ReliefSettings />);

    const slider = screen.getByRole("slider", { name: "最大高度" });
    expect(Number(slider.getAttribute("min"))).toBeCloseTo(0.52, 10);
  });
});
