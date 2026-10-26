import { describe, expect, it } from "vitest";
import { resolvePreviewLineLeft } from "../components/widget/SnapGuides";
import { WIDGET_WIDTH } from "../utils/widgetUtils";

describe("resolvePreviewLineLeft", () => {
  it("anchors right-edge highlights to the effective workspace width", () => {
    expect(resolvePreviewLineLeft("right", 1000, WIDGET_WIDTH)).toBe(650);
  });

  it("falls back to the left edge when preview targets the left dock", () => {
    expect(resolvePreviewLineLeft("left", 1000, WIDGET_WIDTH)).toBe(0);
  });

  it("clamps to zero for narrow workspaces", () => {
    expect(resolvePreviewLineLeft("right", 200, WIDGET_WIDTH)).toBe(0);
  });
});
