/**
 * Regression: ActionBar's preview thumbnail must downsample with nearest-
 * neighbor (renderingQuality="crisp") so each quantized colour block keeps
 * its identity in the small operation-bar thumbnail. Bilinear smoothing
 * makes a small bright cell blend with neighbouring pixels of a different
 * colour, producing a visible 2D-vs-3D mismatch (e.g. an orange square
 * looks dull/pinkish in the 2D thumb while staying vivid in the 3D viewer
 * where each pixel is its own mesh face).
 *
 * 操作栏缩略图必须使用最近邻缩放，否则量化后的小色块会被周围异色像素
 * 「污染」，导致 2D 缩略图色感与 3D 预览/实物打印不一致。
 */

import { render } from "@testing-library/react";
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

describe("ActionBar preview thumbnail rendering quality", () => {
  it("passes renderingQuality='crisp' so quantized colour blocks stay faithful", () => {
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
    });

    render(<ActionBar />);

    expect(canvasPreviewSurfaceMock).toHaveBeenCalled();
    const calls = canvasPreviewSurfaceMock.mock.calls;
    const previewCall = calls.find(([props]) => {
      if (!props || typeof props !== "object") return false;
      return (props as { src?: string }).src === "/preview.png";
    });
    expect(previewCall, "ActionBar must render the preview thumbnail").toBeDefined();
    const [props] = previewCall!;
    expect((props as { renderingQuality?: string }).renderingQuality).toBe("crisp");
  });
});
