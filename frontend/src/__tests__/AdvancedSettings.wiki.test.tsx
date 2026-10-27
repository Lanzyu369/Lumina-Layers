import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../components/ui/HelpDot", () => ({
  default: ({
    title,
    wikiPath,
  }: {
    title: string;
    wikiPath?: string;
  }) => <span data-testid={`help-${title}`} data-wiki-path={wikiPath} />,
}));

import AdvancedSettings from "../components/sections/AdvancedSettings";
import { useConverterStore } from "../stores/converter";

beforeEach(() => {
  useConverterStore.setState({
    enable_cleanup: true,
    separate_backing: false,
    hue_enable: true,
    use_lut_constrained: false,
    auto_dynamic_range: false,
    high_precision_3d_preview: false,
    chroma_gate: 15,
    quantize_colors_unlocked: false,
    source_version: "legacy",
    materialDynamicLayerCountEnabled: false,
  } as never);
});

describe("AdvancedSettings contextual Wiki links", () => {
  it.each([
    ["孤立像素清理", "/docs/reference/color-matching/isolated-pixel-cleanup/"],
    ["分离底板", "/docs/reference/model-features/separate-backing/"],
    ["高精度颜色匹配（实验性功能）", "/docs/reference/color-matching/precise-color-matching/"],
    ["自动动态范围（实验性功能）", "/docs/reference/color-matching/auto-dynamic-range/"],
    ["3D高精度颜色预览", "/docs/reference/preview-and-palette/high-precision-3d-preview/"],
    ["色相保护", "/docs/reference/color-matching/hue-protection/"],
    ["暗色彩度门槛", "/docs/reference/color-matching/dark-chroma-gate/"],
    ["解锁量化颜色数", "/docs/reference/color-matching/unlock-quantize-ceiling/"],
  ])("links %s to its matching Wiki article", (title, expectedPath) => {
    render(<AdvancedSettings />);

    expect(screen.getByTestId(`help-${title}`)).toHaveAttribute(
      "data-wiki-path",
      expectedPath,
    );
  });
});
