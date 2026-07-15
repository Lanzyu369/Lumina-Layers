import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ModelingMode } from "../api/types";
import ReliefSettings from "../components/sections/ReliefSettings";
import { useConverterStore } from "../stores/converter";

describe("ReliefSettings", () => {
  beforeEach(() => {
    useConverterStore.setState({
      modeling_mode: ModelingMode.VECTOR,
      enable_relief: false,
      autoHeightMode: "darker-higher",
      heightmapFile: null,
      heightmapThumbnailUrl: null,
      source_version: "legacy",
    });
  });

  it("allows vector mode to enable the existing relief controls", () => {
    render(<ReliefSettings />);

    const checkbox = screen.getByRole("checkbox", { name: "启用浮雕" });
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
});
