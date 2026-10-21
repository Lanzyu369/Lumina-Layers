/** Preview and output stay available without duplicating the workspace canvas. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DEFAULT_STATE, useConverterStore } from "../stores/converter";

const canvasPreviewSurfaceMock = vi.hoisted(() =>
  vi.fn((props: Record<string, unknown>) => {
    void props;
    return null;
  }),
);

vi.mock("../components/ui/CanvasPreviewSurface", () => ({
  __esModule: true,
  default: (props: Record<string, unknown>) => {
    canvasPreviewSurfaceMock(props);
    return null;
  },
}));

vi.mock("../i18n/context", () => ({
  useI18n: () => ({ t: (key: string) => key, lang: "zh" as const }),
}));

vi.mock("../hooks/useWorkspaceMode", () => ({
  useWorkspaceMode: () => ({ isCompact: false }),
}));

import ActionBar from "../components/sections/ActionBar";

describe("ActionBar preview and output layout", () => {
  it("keeps preview and slicer output available without a redundant thumbnail", () => {
    canvasPreviewSurfaceMock.mockClear();

    useConverterStore.setState({
      ...DEFAULT_STATE,
      sessionId: "session-thumb-crisp",
      previewImageUrl: "/preview.png",
      previewBaseImageUrl: "/preview.png",
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      preview_width_mm: 80,
      bed_label: "256 x 256 mm",
      bedSizes: [],
      imageFile: new File(["png"], "art.png", { type: "image/png" }),
      source_version: "legacy",
      lut_name: "test-lut",
    });

    render(<ActionBar />);

    expect(screen.getByRole("button", { name: "action_preview" })).toBeEnabled();
    expect(document.querySelector('[data-tutorial="print-output"]')).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "action_generate" })).not.toBeInTheDocument();
    expect(canvasPreviewSurfaceMock).not.toHaveBeenCalled();
  });
});
