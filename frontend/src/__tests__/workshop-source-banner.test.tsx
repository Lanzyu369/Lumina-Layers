import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import WorkshopSourceBanner from "../workshop/WorkshopSourceBanner";
import type {
  WorkshopColorLibrary,
  WorkshopRecipeSource,
} from "../workshop/contracts";

const SOURCE: WorkshopRecipeSource = {
  manifestSchemaVersion: 1,
  moduleId: "lumina.fuse-bead-studio",
  moduleVersion: "1.0.0",
  projectSchemaVersion: "fuse-bead-project/v1",
  renderSchemaVersion: "fuse-bead-render/v1",
  payload: {
    privateProjectState: "must-not-render",
  },
};

const LIBRARY: WorkshopColorLibrary = {
  id: "lut:fixture",
  label: "Bambu PLA RYBW",
  sourceKind: "lut",
  colors: [
    {
      id: "slot:0",
      label: "White",
      hex: "#FFFFFF",
      materialId: null,
    },
  ],
};

describe("WorkshopSourceBanner", () => {
  it("distinguishes source colors from the active print library", () => {
    render(
      <WorkshopSourceBanner
        source={SOURCE}
        colorLibrary={LIBRARY}
      />,
    );

    expect(
      screen.getByText("创意工坊图像"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("lumina.fuse-bead-studio · v1.0.0"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Bambu PLA RYBW"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "源色色块由创意工坊保留；下方 LUT 或耗材档案只负责叠色打印，不会覆盖源色。",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("must-not-render")).not.toBeInTheDocument();
  });

  it("shows an explicit unavailable state without exposing recipe payloads", () => {
    render(
      <WorkshopSourceBanner source={SOURCE} colorLibrary={null} />,
    );

    expect(
      screen.getByText("尚未选择可用色库"),
    ).toBeInTheDocument();
    expect(screen.queryByText("must-not-render")).not.toBeInTheDocument();
  });
});
