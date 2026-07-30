import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import WorkshopSourceBanner from "../workshop/WorkshopSourceBanner";
import type {
  WorkshopColorLibrary,
  WorkshopRecipeSource,
} from "../workshop/contracts";
import { rememberWorkshopHandoffColorLibraryId } from "../workshop/handoffMetadata";

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

  it.each([
    {
      handoffColorLibraryId: null,
      caseName: "an unbound module handoff",
    },
    {
      handoffColorLibraryId: "lut:stale",
      caseName: "a stale module color library",
    },
  ])(
    "shows a non-blocking notice for $caseName",
    ({ handoffColorLibraryId }) => {
      const source = structuredClone(SOURCE);
      rememberWorkshopHandoffColorLibraryId(
        source,
        handoffColorLibraryId,
      );

      render(
        <WorkshopSourceBanner
          source={source}
          colorLibrary={LIBRARY}
        />,
      );

      expect(
        screen.getByRole("status"),
      ).toHaveTextContent(
        "打印色库已变化；图纸原色不受影响，将按当前色库重新叠色。",
      );
    },
  );

  it("does not warn when the module and converter color libraries match", () => {
    const source = structuredClone(SOURCE);
    rememberWorkshopHandoffColorLibraryId(source, LIBRARY.id);

    render(
      <WorkshopSourceBanner
        source={source}
        colorLibrary={LIBRARY}
      />,
    );

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
