import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MaterialSolverCacheStatusCard from "../components/MaterialSolverCacheStatusCard";
import {
  buildMaterialSolverCache,
  deleteMaterialSolverCache,
  fetchMaterialSolverCacheStatus,
} from "../api/materialCache";
import type { MaterialSolverCacheEntry } from "../api/types";

vi.mock("../api/materialCache", () => ({
  buildMaterialSolverCache: vi.fn(),
  deleteMaterialSolverCache: vi.fn(),
  fetchMaterialSolverCacheStatus: vi.fn(),
}));

function buildCacheEntry(
  overrides: Partial<MaterialSolverCacheEntry> = {},
): MaterialSolverCacheEntry {
  return {
    palette_hash: "0123456789abcdef",
    material_directory_names: ["red", "white"],
    layer_count: 5,
    layer_height_mm: 0.08,
    substrate: "white",
    grid_resolution: 64,
    total_combinations: 243,
    valid_cell_count: 178,
    total_cell_count: 262144,
    mean_delta_e: 1.23,
    max_delta_e: 4.56,
    build_time_seconds: 12.5,
    built_at: "2026-04-17T04:00:00Z",
    cache_file_size_bytes: 3_145_728,
    cache_file_path: "/tmp/cache.npz",
    ...overrides,
  };
}

describe("MaterialSolverCacheStatusCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the idle state when no materials are selected", async () => {
    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={[]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );
    const pill = await screen.findByTestId(
      "material-solver-cache-status-pill",
    );
    expect(pill).toHaveAttribute("data-tone", "neutral");
    // Build button is present but disabled because no materials selected.
    const buildButton = screen.getByRole("button", { name: "立即构建缓存" });
    expect(buildButton).toBeDisabled();
    expect(fetchMaterialSolverCacheStatus).not.toHaveBeenCalled();
  });

  it("queries and shows ready state when a cache is found", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "Cache found",
      cached: true,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
      entry: buildCacheEntry(),
    });

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );

    await waitFor(() => {
      expect(fetchMaterialSolverCacheStatus).toHaveBeenCalledTimes(1);
    });
    expect(fetchMaterialSolverCacheStatus).toHaveBeenCalledWith({
      materialDirectoryNames: ["red", "white"],
      layerCount: 5,
      layerHeightMm: 0.08,
      substrate: "white",
    });

    const pill = await screen.findByTestId(
      "material-solver-cache-status-pill",
    );
    await waitFor(() => {
      expect(pill).toHaveAttribute("data-tone", "ok");
    });
    expect(screen.getByText("缓存已就绪")).toBeInTheDocument();
    // Rebuild + Delete buttons appear in cached state.
    expect(
      screen.getByRole("button", { name: "重新构建" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "删除缓存" }),
    ).toBeInTheDocument();
  });

  it("shows missing state with fallback hint and build button", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "No cache found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
      entry: null,
    });

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );
    const pill = await screen.findByTestId(
      "material-solver-cache-status-pill",
    );
    await waitFor(() => {
      expect(pill).toHaveAttribute("data-tone", "warn");
    });
    expect(screen.getByText("缓存未构建")).toBeInTheDocument();
    // Fallback hint should be visible when cache is missing.
    expect(
      screen.getByText(/B&B 最优求解器/),
    ).toBeInTheDocument();
    const buildButton = screen.getByRole("button", { name: "立即构建缓存" });
    expect(buildButton).not.toBeDisabled();
  });

  it("invokes the build API and transitions to ready state on success", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "No cache found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
      entry: null,
    });
    vi.mocked(buildMaterialSolverCache).mockResolvedValue({
      status: "ok",
      message: "Built cache",
      entry: buildCacheEntry(),
    });

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );
    const buildButton = await screen.findByRole("button", {
      name: "立即构建缓存",
    });
    await act(async () => {
      fireEvent.click(buildButton);
    });

    await waitFor(() => {
      expect(buildMaterialSolverCache).toHaveBeenCalledTimes(1);
    });
    expect(buildMaterialSolverCache).toHaveBeenCalledWith({
      materialDirectoryNames: ["red", "white"],
      layerCount: 5,
      layerHeightMm: 0.08,
      substrate: "white",
    });

    // After a successful build, pill should transition to "ok".
    await waitFor(() => {
      expect(
        screen.getByTestId("material-solver-cache-status-pill"),
      ).toHaveAttribute("data-tone", "ok");
    });
    expect(screen.getByText("缓存已就绪")).toBeInTheDocument();
  });

  it("deletes a cached entry after confirmation", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "Cache found",
      cached: true,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
      entry: buildCacheEntry(),
    });
    vi.mocked(deleteMaterialSolverCache).mockResolvedValue({
      status: "ok",
      message: "Cache deleted",
      deleted: true,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );
    const deleteButton = await screen.findByRole("button", {
      name: "删除缓存",
    });
    await act(async () => {
      fireEvent.click(deleteButton);
    });

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(deleteMaterialSolverCache).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("material-solver-cache-status-pill"),
      ).toHaveAttribute("data-tone", "warn");
    });
    expect(screen.getByText("缓存未构建")).toBeInTheDocument();
    confirmSpy.mockRestore();
  });

  it("renders an error pill when the status request fails", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockRejectedValue(
      new Error("network down"),
    );

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );
    const pill = await screen.findByTestId(
      "material-solver-cache-status-pill",
    );
    await waitFor(() => {
      expect(pill).toHaveAttribute("data-tone", "error");
    });
    expect(screen.getByText(/network down/i)).toBeInTheDocument();
  });
});
