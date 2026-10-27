import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

import { ColorMode, ModelingMode, StructureMode } from "../api/types";
import ReliefSettings from "../components/sections/ReliefSettings";
import { useConverterStore } from "../stores/converter";

vi.mock("../api/lut", async () => {
  const actual = await vi.importActual<typeof import("../api/lut")>(
    "../api/lut",
  );
  return {
    ...actual,
    fetchLutInfo: vi.fn(() => new Promise(() => {})),
  };
});

describe("ReliefSettings", () => {
  beforeEach(() => {
    useConverterStore.setState({
      modeling_mode: ModelingMode.VECTOR,
      color_mode: ColorMode.FOUR_COLOR_RYBW,
      structure_mode: StructureMode.SINGLE_SIDED,
      enable_relief: false,
      autoHeightMode: "darker-higher",
      heightmapFile: null,
      heightmapThumbnailUrl: null,
      source_version: "legacy",
    });
  });

  it("allows vector mode to enable the existing relief controls", () => {
    render(<ReliefSettings />);

    const checkbox = screen.getByRole("switch", { name: "启用浮雕" });
    expect(checkbox).toBeEnabled();
    const label = checkbox.closest("label");
    if (!label) throw new Error("Relief checkbox label is missing");

    fireEvent.click(label);

    expect(useConverterStore.getState().enable_relief).toBe(true);
    expect(
      screen.getByRole("slider", { name: "最大高度" }),
    ).toBeInTheDocument();
  });

  it("shows the existing heightmap upload in vector relief mode", () => {
    useConverterStore.setState({
      enable_relief: true,
      autoHeightMode: "use-heightmap",
    });

    render(<ReliefSettings />);

    expect(screen.getByText("高度图")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "拖拽图片或点击上传" }),
    ).toBeInTheDocument();
  });

  it("disables relief controls for 5-Color Extended vector mode", () => {
    useConverterStore.setState({ color_mode: ColorMode.FIVE_COLOR_EXT });

    render(<ReliefSettings />);

    expect(
      screen.getByRole("switch", { name: /启用浮雕/ }),
    ).toBeDisabled();
  });

  it("disables relief controls for double-sided vector mode", () => {
    useConverterStore.setState({
      modeling_mode: ModelingMode.VECTOR,
      structure_mode: StructureMode.DOUBLE_SIDED,
    });

    render(<ReliefSettings />);

    expect(
      screen.getByRole("switch", { name: /启用浮雕/ }),
    ).toBeDisabled();
  });

  it("clears and hides relief controls after selecting a 5-color LUT", () => {
    useConverterStore.setState({
      lutListFull: [
        {
          name: "legacy-five",
          color_mode: ColorMode.FIVE_COLOR_EXT,
          path: "/legacy-five.npy",
        },
      ],
      lutColorsLutName: "legacy-five",
    } as never);
    render(<ReliefSettings />);
    fireEvent.click(screen.getByRole("switch", { name: "启用浮雕" }));
    expect(screen.getByRole("slider", { name: "最大高度" })).toBeInTheDocument();

    act(() => {
      useConverterStore.getState().setLutName("legacy-five");
    });

    const checkbox = screen.getByRole("switch", { name: /启用浮雕/ });
    expect(checkbox).toBeDisabled();
    expect(checkbox).not.toBeChecked();
    expect(screen.queryByRole("slider", { name: "最大高度" })).toBeNull();
  });
});
