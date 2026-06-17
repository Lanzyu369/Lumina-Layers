import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import FiveColorQueryPanel from "../components/FiveColorQueryPanel";
import { useFiveColorStore } from "../stores/fiveColorStore";
import { useConverterStore } from "../stores/converter";
import { translations } from "../i18n/translations";
import type { FiveColorCardCoordinate, FiveColorNeighborhoodCell } from "../api/types";

vi.mock("../components/FiveColorCanvas", () => ({
  default: () => <div data-testid="five-color-canvas" />,
}));

vi.mock("../api/fiveColor", () => ({
  fetchBaseColors: vi.fn(),
  queryFiveColor: vi.fn(),
  matchFiveColorByHex: vi.fn(),
  generateRecipeSwatch: vi.fn(),
}));

import { matchFiveColorByHex } from "../api/fiveColor";

const mockMatchFiveColorByHex = vi.mocked(matchFiveColorByHex);

function cardCoordinate(
  overrides: Partial<FiveColorCardCoordinate> = {},
): FiveColorCardCoordinate {
  const gridSize = overrides.grid_size ?? 2;
  const row = overrides.row ?? 0;
  const col = overrides.col ?? 0;
  return {
    card_index: 0,
    card_label: "1",
    page_index: 0,
    page_label: "1",
    grid_size: gridSize,
    data_rows: gridSize,
    data_cols: gridSize,
    row,
    col,
    data_row: row,
    data_col: col,
    display_row: row + 1,
    display_col: col + 1,
    physical_row: row,
    physical_col: col,
    row_index: row * gridSize + col,
    ...overrides,
  };
}

function buildNeighborhood(size: number): FiveColorNeighborhoodCell[][] {
  return Array.from({ length: size }, (_, row) =>
    Array.from({ length: size }, (_, col) => {
      const rowIndex = row * size + col;
      const isMatch = row === Math.floor(size / 2) && col === Math.floor(size / 2);
      const rgb: [number, number, number] = isMatch
        ? [240, 10, 0]
        : [rowIndex, rowIndex, rowIndex];
      return {
        card_index: 0,
        card_label: "1",
        page_index: 0,
        page_label: "1",
        grid_size: size,
        data_rows: size,
        data_cols: size,
        row,
        col,
        data_row: row,
        data_col: col,
        display_row: row + 1,
        display_col: col + 1,
        physical_row: row,
        physical_col: col,
        row_index: rowIndex,
        rgb,
        hex: isMatch ? "#F00A00" : `#${rowIndex.toString(16).padStart(2, "0").repeat(3).toUpperCase()}`,
        is_match: isMatch,
      };
    }),
  );
}

function resetFiveColorState() {
  useFiveColorStore.setState({
    lutName: "test-lut",
    baseColors: [
      { index: 0, rgb: [255, 0, 0], name: "Red", hex: "#FF0000" },
      { index: 1, rgb: [0, 255, 0], name: "Green", hex: "#00FF00" },
      { index: 2, rgb: [0, 0, 255], name: "Blue", hex: "#0000FF" },
      { index: 3, rgb: [255, 255, 0], name: "Yellow", hex: "#FFFF00" },
      { index: 4, rgb: [255, 255, 255], name: "White", hex: "#FFFFFF" },
      { index: 5, rgb: [0, 0, 0], name: "Black", hex: "#000000" },
    ],
    combinations: null,
    selectedIndices: [],
    manualSelectedIndices: [],
    selectionSource: "manual",
    queryResult: null,
    isLoading: false,
    error: null,
    collectedRecipes: [],
    swatchBlockSize: 15,
    swatchGap: 2,
    swatchCols: 0,
    swatchStructureMode: "Single-sided",
    isGeneratingSwatch: false,
    swatchDownloadUrl: null,
    swatchPreviewUrl: null,
  });
}

describe("FiveColorQueryPanel target color match", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    resetFiveColorState();
    useConverterStore.setState({
      lutList: ["test-lut"],
      fetchLutList: vi.fn(),
    });
  });

  it("accepts a hex value, matches a recipe, and renders coordinate plus neighborhood", async () => {
    mockMatchFiveColorByHex.mockResolvedValueOnce({
      found: true,
      selected_indices: [0, 1, 2, 3, 4],
      result_rgb: [240, 10, 0],
      result_hex: "#F00A00",
      row_index: 1,
      message: "found",
      source: "test",
      target_rgb: [242, 10, 0],
      target_hex: "#F20A00",
      matched_rgb: [240, 10, 0],
      matched_hex: "#F00A00",
      delta_e: 1.25,
      coordinate: cardCoordinate({
        card_index: 0,
        card_label: "1",
        grid_size: 2,
        row: 0,
        col: 1,
        display_row: 1,
        display_col: 2,
      }),
      neighborhood: [
        ...buildNeighborhood(5),
      ],
    });

    render(<FiveColorQueryPanel />);

    fireEvent.change(screen.getByLabelText("目标色值"), {
      target: { value: "#F20A00" },
    });
    fireEvent.click(screen.getByRole("button", { name: "匹配配方" }));

    await waitFor(() => {
      expect(mockMatchFiveColorByHex).toHaveBeenCalledWith({
        lut_name: "test-lut",
        target_hex: "#F20A00",
        neighborhood_radius: 2,
      });
    });

    await waitFor(() => {
      expect(screen.getByTestId("five-color-match-neighborhood")).toBeInTheDocument();
    });
    expect(useFiveColorStore.getState().selectedIndices).toEqual([0, 1, 2, 3, 4]);
    expect(screen.getByTestId("five-color-match-coordinate")).toHaveTextContent("色卡 1");
    expect(screen.getByTestId("five-color-match-coordinate")).toHaveTextContent("第 1 行");
    expect(screen.getByTestId("five-color-match-coordinate")).toHaveTextContent("第 2 列");
    expect(screen.getByText("#F20A00")).toBeInTheDocument();
    expect(screen.getAllByText("#F00A00").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("five-color-match-cell")).toHaveLength(25);
    const labels = screen.getAllByTestId("five-color-match-cell").map((cell) => cell.getAttribute("aria-label"));
    expect(labels.join("\n")).toContain("#F00A00 · 色卡 1 · 第 3 行 · 第 3 列");
  });

  it("keeps the RGB detail label in the translation dictionary", () => {
    expect(translations.five_color_match_rgb_value.zh).toBe("RGB {value}");
    expect(translations.five_color_match_rgb_value.en).toBe("RGB {value}");
  });

  it("disables manual color choices when no valid combinations remain", () => {
    useFiveColorStore.setState({ combinations: [] });

    render(<FiveColorQueryPanel />);

    expect(screen.getByRole("button", { name: "选择颜色 Red (#FF0000)" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "选择颜色 Green (#00FF00)" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "选择颜色 White (#FFFFFF)" })).toBeDisabled();
  });

  it("does not present the zero-based LUT row as a user-facing card row", () => {
    useFiveColorStore.setState({
      selectedIndices: [0, 1, 2, 3, 4],
      queryResult: {
        found: true,
        selected_indices: [0, 1, 2, 3, 4],
        result_rgb: [255, 0, 0],
        result_hex: "#FF0000",
        row_index: 0,
        message: "found",
        source: "test",
        target_rgb: [255, 0, 0],
        target_hex: "#FF0000",
        matched_rgb: [255, 0, 0],
        matched_hex: "#FF0000",
        delta_e: 0,
        coordinate: cardCoordinate({
          card_index: 0,
          card_label: "1",
          grid_size: 2,
          row: 0,
          col: 0,
          display_row: 1,
          display_col: 1,
        }),
        neighborhood: [],
      },
    });

    render(<FiveColorQueryPanel />);

    expect(screen.getByTestId("five-color-match-coordinate")).toHaveTextContent("第 1 行");
    expect(screen.queryByText("行号: 0")).not.toBeInTheDocument();
  });

  it("keeps reverse enabled for a complete target-match recipe", () => {
    useFiveColorStore.setState({
      selectedIndices: [0, 1, 2, 3, 4],
      manualSelectedIndices: [0, 1, 2, 3],
      selectionSource: "target-match",
      queryResult: {
        found: true,
        selected_indices: [0, 1, 2, 3, 4],
        result_rgb: [255, 0, 0],
        result_hex: "#FF0000",
        row_index: 0,
        message: "found",
        source: "test",
        target_rgb: [255, 0, 0],
        target_hex: "#FF0000",
        matched_rgb: [255, 0, 0],
        matched_hex: "#FF0000",
        delta_e: 0,
        coordinate: cardCoordinate({
          card_index: 0,
          card_label: "1",
          grid_size: 2,
          row: 0,
          col: 0,
          display_row: 1,
          display_col: 1,
        }),
        neighborhood: [],
      },
    });

    render(<FiveColorQueryPanel />);

    expect(screen.getByRole("button", { name: "反序" })).toBeEnabled();
  });

  it("renders a six-layer target-match recipe", () => {
    useFiveColorStore.setState({
      selectedIndices: [4, 1, 2, 3, 0, 4],
      manualSelectedIndices: [],
      selectionSource: "target-match",
      queryResult: {
        found: true,
        selected_indices: [4, 1, 2, 3, 0, 4],
        result_rgb: [4, 5, 6],
        result_hex: "#040506",
        row_index: 1,
        message: "found",
        source: "test",
        target_rgb: [4, 5, 6],
        target_hex: "#040506",
        matched_rgb: [4, 5, 6],
        matched_hex: "#040506",
        delta_e: 0,
        coordinate: cardCoordinate({
          card_index: 0,
          card_label: "1",
          grid_size: 2,
          row: 0,
          col: 0,
          display_row: 1,
          display_col: 1,
        }),
        neighborhood: [],
      },
    });

    render(<FiveColorQueryPanel />);

    expect(screen.getAllByTestId("five-color-match-recipe-layer")).toHaveLength(6);
    expect(screen.getAllByText("#040506").length).toBeGreaterThan(0);
  });

  it("renders localized swatch structure modes for collected recipes", () => {
    useFiveColorStore.setState({
      collectedRecipes: [
        {
          id: "recipe-1",
          selectedIndices: [0, 1, 2, 3, 4],
          resultHex: "#F00A00",
          baseColorNames: ["Red", "Green", "Blue", "Yellow", "White"],
          baseColorHexes: ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FFFFFF"],
          label: "Recipe 1",
        },
      ],
    });

    render(<FiveColorQueryPanel />);

    expect(screen.getByRole("button", { name: "单面" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "双面" })).toBeInTheDocument();
    expect(screen.queryByText("five_color_swatch_single_sided")).not.toBeInTheDocument();
    expect(screen.queryByText("five_color_swatch_double_sided")).not.toBeInTheDocument();
  });

  it("shows the localized explanation when a target color has no recipe", () => {
    useFiveColorStore.setState({
      selectedIndices: [4, 3, 2, 1, 0],
      queryResult: {
        found: false,
        selected_indices: [],
        result_rgb: null,
        result_hex: null,
        row_index: 33,
        message: "Matched row 33, but no layer recipe is available for this LUT row.",
        reason: "recipe_unavailable",
        source: "test",
        target_rgb: [220, 10, 30],
        target_hex: "#DC0A1E",
        matched_rgb: [220, 10, 30],
        matched_hex: "#DC0A1E",
        delta_e: 0,
        coordinate: cardCoordinate({
          card_index: 0,
          card_label: "1",
          grid_size: 7,
          row: 4,
          col: 5,
          display_row: 5,
          display_col: 6,
        }),
        neighborhood: [],
      },
    });

    render(<FiveColorQueryPanel />);

    expect(screen.getByText("无法生成配方")).toBeInTheDocument();
    expect(screen.getByText("已找到最接近的色卡颜色，但该行无法反推出配方。")).toBeInTheDocument();
    expect(screen.queryByText("未找到匹配")).not.toBeInTheDocument();
    expect(screen.queryByText("建议操作：")).not.toBeInTheDocument();
    expect(screen.getAllByText("#DC0A1E").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("five-color-match-recipe")).not.toBeInTheDocument();
  });

  it("does not render backend free text for a standard query miss", () => {
    useFiveColorStore.setState({
      selectedIndices: [0, 1, 2, 3, 4],
      queryResult: {
        found: false,
        selected_indices: [0, 1, 2, 3, 4],
        result_rgb: null,
        result_hex: null,
        row_index: -1,
        message: "missing",
        source: "test",
      },
    });

    render(<FiveColorQueryPanel />);

    expect(screen.getByText("未找到匹配")).toBeInTheDocument();
    expect(screen.getByText("当前颜色顺序没有对应的色卡记录。")).toBeInTheDocument();
    expect(screen.queryByText("missing")).not.toBeInTheDocument();
  });

  it("renders localized guidance for invalid target hex input", async () => {
    mockMatchFiveColorByHex.mockRejectedValueOnce(new Error("Request failed with status code 422"));

    render(<FiveColorQueryPanel />);

    fireEvent.change(screen.getByLabelText("目标色值"), {
      target: { value: "bad" },
    });
    fireEvent.click(screen.getByRole("button", { name: "匹配配方" }));

    await waitFor(() => {
      expect(screen.getByText("请输入 #RRGGBB 格式的色值")).toBeInTheDocument();
    });
    expect(mockMatchFiveColorByHex).not.toHaveBeenCalled();
    expect(screen.queryByText("Request failed with status code 422")).not.toBeInTheDocument();
  });

  it("does not render raw error strings in the shared error banner", () => {
    useFiveColorStore.setState({
      error: "Request failed with status code 500",
    });

    render(<FiveColorQueryPanel />);

    expect(screen.getByText("五色操作失败")).toBeInTheDocument();
    expect(screen.queryByText("Request failed with status code 500")).not.toBeInTheDocument();
  });
});
