import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import PuzzleSettings from "../components/sections/PuzzleSettings";
import { useConverterStore } from "../stores/converter";

describe("PuzzleSettings", () => {
  beforeEach(() => {
    useConverterStore.setState({
      puzzleEnabled: true,
      puzzleStyle: "regular",
      puzzleSizingMode: "grid",
      pieceWidthMm: 20,
      pieceHeightMm: 20,
      puzzleRows: 4,
      puzzleCols: 5,
      targetPieceCount: 24,
      connectorStyle: "classic",
      labelsEnabled: false,
      engraveBackLabels: false,
      irregularityStrength: 0.35,
      minNeckWidthMm: 1.2,
      puzzleWarnings: [],
      puzzleResolvedRows: 4,
      puzzleResolvedCols: 5,
      puzzleResolvedPieceCount: 18,
      puzzleDerivedPieceWidthMm: 16.5,
      puzzleDerivedPieceHeightMm: 18.2,
      batchMode: false,
    });
  });

  it("renders translated labels and does not leak raw puzzle keys", () => {
    render(<PuzzleSettings />);

    expect(
      screen.getByRole("switch", { name: "启用拼图模式" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "拼图风格" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "尺寸控制方式" }),
    ).toBeInTheDocument();
    expect(screen.getByText("目标网格")).toBeInTheDocument();
    expect(screen.getByText("解析网格")).toBeInTheDocument();
    expect(screen.getByText("背面刻号尚未写入导出几何，当前版本暂不可用。")).toBeInTheDocument();
    expect(screen.queryByText("puzzle_enable")).not.toBeInTheDocument();
    expect(screen.queryByText("puzzle_summary_requested_grid")).not.toBeInTheDocument();
    expect(screen.queryByText("puzzle_back_engrave_unavailable_hint")).not.toBeInTheDocument();
  });

  it("localizes the final wipe-tower warning instead of showing its code", () => {
    useConverterStore.setState({
      puzzleWarnings: ["wipe_tower_manual_adjustment_required"],
    });

    render(<PuzzleSettings />);

    expect(screen.getByText("打印前请手动检查摆放")).toBeInTheDocument();
    expect(
      screen.queryByText("wipe_tower_manual_adjustment_required"),
    ).not.toBeInTheDocument();
  });
});
