import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import LutComparePanel from "../components/LutComparePanel";
import { ColorMode } from "../api/types";
import { useLutCompareStore } from "../stores/lutCompareStore";

const mockFetchLutInfo = vi.fn();
const mockCompareLuts = vi.fn();
const mockFetchLutList = vi.fn();

vi.mock("../api/lut", () => ({
  fetchLutInfo: (...args: unknown[]) => mockFetchLutInfo(...args),
  compareLuts: (...args: unknown[]) => mockCompareLuts(...args),
}));

vi.mock("../api/converter", () => ({
  fetchLutList: (...args: unknown[]) => mockFetchLutList(...args),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  mockFetchLutList.mockResolvedValue({
    luts: [
      { name: "LUT A", color_mode: "4-Color (RYBW)", path: "/fake/a.json", fingerprint: "fp-a" },
      { name: "LUT B", color_mode: "4-Color (RYBW)", path: "/fake/b.json", fingerprint: "fp-b" },
    ],
  });

  useLutCompareStore.setState({
    lutList: [
      { name: "LUT A", color_mode: ColorMode.FOUR_COLOR_RYBW, path: "/fake/a.json", fingerprint: "fp-a" },
      { name: "LUT B", color_mode: ColorMode.FOUR_COLOR_RYBW, path: "/fake/b.json", fingerprint: "fp-b" },
    ],
    lutListLoading: false,
    lutAName: "",
    lutBName: "",
    lutAInfo: null,
    lutBInfo: null,
    lutAInfoLoading: false,
    lutBInfoLoading: false,
    comparing: false,
    compareResult: null,
    error: null,
  });
});

describe("LutComparePanel", () => {
  it("renders all compare controls", () => {
    render(<LutComparePanel />);

    expect(screen.getByTestId("lut-compare-panel")).toBeInTheDocument();
    expect(screen.getByText("LUT 对比工具")).toBeInTheDocument();
    expect(screen.getByTestId("lut-compare-lut-a-dropdown")).toBeInTheDocument();
    expect(screen.getByTestId("lut-compare-lut-b-dropdown")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始对比" })).toBeInTheDocument();
  });

  it("shows compare result and warnings when compareResult is set", () => {
    useLutCompareStore.setState({
      lutAName: "LUT A",
      lutBName: "LUT B",
      compareResult: {
        status: "success",
        message: "Compared 2 shared recipes between LUT A and LUT B",
        lut_a_name: "LUT A",
        lut_b_name: "LUT B",
        lut_a_mode: "4-Color",
        lut_b_mode: "4-Color",
        stats: {
          matched_recipe_count: 2,
          recipe_coverage_a: 1,
          recipe_coverage_b: 1,
          mean_delta_e00: 1.2,
          median_delta_e00: 1.1,
          p95_delta_e00: 2.4,
          max_delta_e00: 2.8,
          identical_rgb_count: 1,
          recipes_only_in_a: 0,
          recipes_only_in_b: 0,
        },
        warnings: ["layer_height_mm 不一致: 0.0800, 0.1000"],
        worst_diffs: [
          {
            recipe: ["White", "Red", "Yellow", "Blue", "White"],
            rgb_a: [255, 0, 0],
            rgb_b: [250, 10, 0],
            hex_a: "#FF0000",
            hex_b: "#FA0A00",
            delta_e00: 2.8,
          },
        ],
      },
    });

    render(<LutComparePanel />);

    expect(screen.getByTestId("compare-result")).toBeInTheDocument();
    expect(screen.getByTestId("compare-result")).toHaveTextContent(
      "已比较 LUT A 与 LUT B 的 2 个共享配方。"
    );
    expect(screen.queryByText("Compared 2 shared recipes between LUT A and LUT B")).not.toBeInTheDocument();
    expect(screen.getByTestId("compare-warnings")).toHaveTextContent(
      "层高不一致：0.0800, 0.1000"
    );
    expect(screen.queryByText("layer_height_mm 不一致: 0.0800, 0.1000")).not.toBeInTheDocument();
    expect(screen.getByTestId("worst-diffs")).toHaveTextContent("White / Red / Yellow / Blue / White");
    expect(screen.getByTestId("worst-diffs")).toHaveTextContent("2.80");
  });

  it("disables compare button when one LUT is missing", () => {
    useLutCompareStore.setState({
      lutAName: "LUT A",
      lutBName: "",
    });

    render(<LutComparePanel />);

    expect(screen.getByRole("button", { name: "开始对比" })).toBeDisabled();
  });
});
