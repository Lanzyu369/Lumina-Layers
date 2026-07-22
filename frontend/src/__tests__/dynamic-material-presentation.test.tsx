import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

vi.mock("../api/converter", async () => {
  const actual = await vi.importActual<typeof import("../api/converter")>(
    "../api/converter",
  );
  return {
    ...actual,
    fetchLutColors: vi.fn().mockResolvedValue({ colors: [] }),
  };
});

vi.mock("../components/ui/CustomRecipeDialog", () => ({
  default: () => null,
}));

import type { PaletteEntry } from "../api/types";
import PalettePanel from "../components/sections/PalettePanel";
import { DEFAULT_STATE, useConverterStore } from "../stores/converter";

const PALETTE: PaletteEntry[] = [
  {
    quantized_hex: "112233",
    matched_hex: "abcdef",
    pixel_count: 60,
    percentage: 60,
  },
  {
    quantized_hex: "445566",
    matched_hex: "112233",
    pixel_count: 40,
    percentage: 40,
  },
];

const PERMUTED_RECIPES = [
  {
    target_srgb: [68, 85, 102],
    matched_srgb: [17, 34, 51],
    actual_layer_count: 8,
    padding_layer_count: 1,
    actual_recipe_top_to_bottom: [1, 0, 1, 0, 1, 0, 1, 0],
    print_recipe_top_to_bottom: [1, 0, 1, 0, 1, 0, 1, 0, 0],
    selected_delta_e00: 2.22,
    best_range_delta_e00: 2.11,
    fixed_max_delta_e00: 2.05,
    delta_e00_sacrifice: 0.11,
    layer_cap_options: [],
  },
  {
    target_srgb: [17, 34, 51],
    matched_srgb: [68, 85, 102],
    actual_layer_count: 5,
    padding_layer_count: 4,
    actual_recipe_top_to_bottom: [1, 2, 1, 2, 1],
    print_recipe_top_to_bottom: [1, 2, 1, 2, 1, 0, 0, 0, 0],
    selected_delta_e00: 1.23,
    best_range_delta_e00: 0.9,
    fixed_max_delta_e00: 0.98,
    delta_e00_sacrifice: 0.33,
    layer_cap_options: [],
  },
];

function resetStore(): void {
  useConverterStore.setState({
    ...DEFAULT_STATE,
    palette: PALETTE,
    enable_relief: false,
    materialDynamicRecipes: [],
    materialLayerBenefitCurve: [],
  } as never);
}

describe("dynamic material palette presentation", () => {
  beforeEach(resetStore);

  it("joins deliberately permuted recipes by target RGB and shows every exact metric", () => {
    useConverterStore.setState({
      materialDynamicRecipes: PERMUTED_RECIPES,
      materialLayerBenefitCurve: [
        {
          max_effective_layer_count: 5,
          weighted_mean_delta_e00: 3.4,
          marginal_delta_e00_reduction: 0,
        },
        {
          max_effective_layer_count: 6,
          weighted_mean_delta_e00: 3.1,
          marginal_delta_e00_reduction: 0.3,
        },
      ],
    } as never);

    render(<PalettePanel />);

    const firstTargetCard = screen.getByRole("button", {
      name: /颜色 abcdef/,
    });
    expect(firstTargetCard).toHaveAccessibleName(/实际层数 5/);
    expect(firstTargetCard).toHaveAccessibleName(/节省层数 4/);
    expect(firstTargetCard).toHaveAccessibleName(/当前 ΔE00 1\.23/);
    expect(firstTargetCard).toHaveAccessibleName(/固定最大层数 ΔE00 0\.98/);
    expect(firstTargetCard).toHaveAccessibleName(/范围最佳 ΔE00 0\.90/);
    expect(firstTargetCard).toHaveAccessibleName(/容差损失 0\.33/);
    expect(within(firstTargetCard).getByText("实际层数")).toBeInTheDocument();
    expect(within(firstTargetCard).getByText("5")).toBeInTheDocument();

    const secondTargetCard = screen.getByRole("button", {
      name: /颜色 112233/,
    });
    expect(secondTargetCard).toHaveAccessibleName(/实际层数 8/);
    expect(secondTargetCard).toHaveAccessibleName(/当前 ΔE00 2\.22/);

    expect(
      screen.getByRole("region", { name: "全图层数收益" }),
    ).toBeInTheDocument();
  });

  it("preserves the legacy compact layout when dynamic metadata is absent", () => {
    render(<PalettePanel />);

    expect(screen.queryByText("实际层数")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "全图层数收益" })).toBeNull();
    expect(screen.getByRole("listbox", { name: "调色板颜色列表" }).firstElementChild)
      .toHaveClass("grid-cols-[repeat(auto-fit,minmax(3.4rem,1fr))]");
  });

  it("labels a single first point as the baseline", () => {
    useConverterStore.setState({
      materialLayerBenefitCurve: [
        {
          max_effective_layer_count: 5,
          weighted_mean_delta_e00: 3.4,
          marginal_delta_e00_reduction: 0,
        },
      ],
    } as never);

    render(<PalettePanel />);

    const region = screen.getByRole("region", { name: "全图层数收益" });
    expect(within(region).getByText("5 层")).toBeInTheDocument();
    expect(within(region).getByText("平均 ΔE00 3.40")).toBeInTheDocument();
    expect(within(region).getByText("起始层数")).toBeInTheDocument();
  });

  it("marks a curve recalculated for only the automatic-solver pixels", () => {
    useConverterStore.setState({
      materialLayerBenefitCurve: [
        {
          max_effective_layer_count: 5,
          weighted_mean_delta_e00: 3.4,
          marginal_delta_e00_reduction: 0,
        },
      ],
      materialLayerBenefitScope: "automatic_pixels",
      materialLayerBenefitPixelCount: 42,
    } as never);

    render(<PalettePanel />);

    expect(
      screen.getByText("仅自动求解区域（42 像素）"),
    ).toBeInTheDocument();
  });

  it("distinguishes zero improvement from a positive marginal reduction", () => {
    useConverterStore.setState({
      materialLayerBenefitCurve: [
        {
          max_effective_layer_count: 5,
          weighted_mean_delta_e00: 3.4,
          marginal_delta_e00_reduction: 0,
        },
        {
          max_effective_layer_count: 6,
          weighted_mean_delta_e00: 3.4,
          marginal_delta_e00_reduction: 0,
        },
        {
          max_effective_layer_count: 7,
          weighted_mean_delta_e00: 3.15,
          marginal_delta_e00_reduction: 0.25,
        },
      ],
    } as never);

    render(<PalettePanel />);

    expect(screen.getByText("无改善")).toBeInTheDocument();
    expect(screen.getByText("边际改善 0.25")).toBeInTheDocument();
  });
});
