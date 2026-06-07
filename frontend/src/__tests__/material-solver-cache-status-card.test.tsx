import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MaterialSolverCacheStatusCard from "../components/MaterialSolverCacheStatusCard";
import {
  buildMaterialSolverCache,
  buildMaterialSolverRuntime,
  deleteMaterialSolverCache,
  deleteMaterialSolverRuntime,
  fetchMaterialSolverCacheStatus,
  fetchMaterialSolverRuntimeStatus,
} from "../api/materialCache";
import type {
  MaterialSolverCacheEntry,
  MaterialSolverRuntimeEntry,
} from "../api/types";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";

vi.mock("../api/materialCache", () => ({
  buildMaterialSolverCache: vi.fn(),
  buildMaterialSolverRuntime: vi.fn(),
  DEFAULT_MATERIAL_SOLVER_RUNTIME_CANDIDATE_BUDGET: 4_194_304,
  deleteMaterialSolverCache: vi.fn(),
  deleteMaterialSolverRuntime: vi.fn(),
  fetchMaterialSolverCacheStatus: vi.fn(),
  fetchMaterialSolverRuntimeStatus: vi.fn(),
  MATERIAL_SOLVER_RUNTIME_CANDIDATE_BUDGETS: [
    1_048_576,
    4_194_304,
    8_388_608,
  ],
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

function buildRuntimeEntry(
  overrides: Partial<MaterialSolverRuntimeEntry> = {},
): MaterialSolverRuntimeEntry {
  return {
    palette_hash: "0123456789abcdef",
    material_directory_names: ["red", "white"],
    layer_count: 8,
    layer_height_mm: 0.04,
    substrate: "white",
    mode: "candidate_hybrid",
    candidate_budget: 4_194_304,
    candidate_count: 4_194_304,
    candidate_pool_multiplier: 8,
    build_memory_budget_bytes: 8 * 1024 * 1024 * 1024,
    batch_recipe_count: 524_288,
    lab_grid_resolution: 64,
    seed: 0,
    inverse_refinement_enabled: true,
    built_at: "2026-06-07T04:00:00Z",
    cache_file_size_bytes: 268_435_456,
    cache_file_path: "/tmp/hybrid.npz",
    ...overrides,
  };
}

describe("MaterialSolverCacheStatusCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset the opt-in settings so each test starts from the shipped default
    // (switch off, low-tier 64) unless it flips the toggle explicitly.
    useSettingsStore.setState({
      enableSolverCacheGridSelection:
        DEFAULT_SETTINGS.enableSolverCacheGridSelection,
      solverCacheGridResolution: DEFAULT_SETTINGS.solverCacheGridResolution,
    });
    vi.mocked(fetchMaterialSolverRuntimeStatus).mockResolvedValue({
      status: "ok",
      message: "No runtime found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
      candidate_budget: 4_194_304,
      entry: null,
    });
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
    expect(fetchMaterialSolverRuntimeStatus).not.toHaveBeenCalled();
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
    expect(fetchMaterialSolverCacheStatus).toHaveBeenCalledWith(
      {
        materialDirectoryNames: ["red", "white"],
        layerCount: 5,
        layerHeightMm: 0.08,
        substrate: "white",
      },
      // With the opt-in toggle off, the call omits a concrete
      // gridResolution so the backend applies its low-tier default.
      { gridResolution: undefined },
    );

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
    expect(buildMaterialSolverCache).toHaveBeenCalledWith(
      {
        materialDirectoryNames: ["red", "white"],
        layerCount: 5,
        layerHeightMm: 0.08,
        substrate: "white",
      },
      { gridResolution: undefined },
    );

    // After a successful build, pill should transition to "ok".
    await waitFor(() => {
      expect(
        screen.getByTestId("material-solver-cache-status-pill"),
      ).toHaveAttribute("data-tone", "ok");
    });
    expect(screen.getByText("缓存已就绪")).toBeInTheDocument();
  });

  it("disables cache build for issue 230 sized high-grid combinations", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "No cache found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 8,
      layer_height_mm: 0.08,
      substrate: "white",
      entry: null,
    });
    useSettingsStore.setState({
      enableSolverCacheGridSelection: true,
      solverCacheGridResolution: 2048,
    });

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={Array.from(
          { length: 12 },
          (_, idx) => `mat-${idx}`,
        )}
        layerCount={8}
        layerHeightMm={0.08}
      />,
    );

    const buildButton = await screen.findByRole("button", {
      name: "立即构建缓存",
    });
    expect(buildButton).toBeDisabled();
    expect(
      screen.getByText(/超过穷举或内存预算/),
    ).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(buildButton);
    });
    expect(buildMaterialSolverCache).not.toHaveBeenCalled();
  });

  it("lets large palettes build the bounded hybrid runtime even when exhaustive cache is unsafe", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "No cache found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 8,
      layer_height_mm: 0.08,
      substrate: "white",
      entry: null,
    });
    vi.mocked(fetchMaterialSolverRuntimeStatus).mockResolvedValue({
      status: "ok",
      message: "No runtime found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 8,
      layer_height_mm: 0.08,
      substrate: "white",
      candidate_budget: 4_194_304,
      entry: null,
    });
    vi.mocked(buildMaterialSolverRuntime).mockResolvedValue({
      status: "ok",
      message: "Built runtime",
      entry: buildRuntimeEntry({ layer_count: 8, layer_height_mm: 0.08 }),
    });

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={Array.from(
          { length: 22 },
          (_, idx) => `mat-${idx}`,
        )}
        layerCount={8}
        layerHeightMm={0.08}
      />,
    );

    const exhaustiveBuildButton = await screen.findByRole("button", {
      name: "立即构建缓存",
    });
    expect(exhaustiveBuildButton).toBeDisabled();

    const runtimeBuildButton = await screen.findByRole("button", {
      name: "构建运行时",
    });
    expect(runtimeBuildButton).not.toBeDisabled();

    await act(async () => {
      fireEvent.click(runtimeBuildButton);
    });

    await waitFor(() => {
      expect(buildMaterialSolverRuntime).toHaveBeenCalledTimes(1);
    });
    expect(buildMaterialSolverRuntime).toHaveBeenCalledWith(
      {
        materialDirectoryNames: Array.from(
          { length: 22 },
          (_, idx) => `mat-${idx}`,
        ),
        layerCount: 8,
        layerHeightMm: 0.08,
        substrate: "white",
      },
      { candidateBudget: 4_194_304 },
    );
    expect(buildMaterialSolverCache).not.toHaveBeenCalled();
    expect(screen.getByText("运行时已就绪")).toBeInTheDocument();
  });

  it("forwards selected runtime candidate budget to status build and delete calls", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "No cache found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 8,
      layer_height_mm: 0.04,
      substrate: "white",
      entry: null,
    });
    vi.mocked(fetchMaterialSolverRuntimeStatus).mockResolvedValue({
      status: "ok",
      message: "Runtime found",
      cached: true,
      palette_hash: "0123456789abcdef",
      layer_count: 8,
      layer_height_mm: 0.04,
      substrate: "white",
      candidate_budget: 8_388_608,
      entry: buildRuntimeEntry({ candidate_budget: 8_388_608 }),
    });
    vi.mocked(buildMaterialSolverRuntime).mockResolvedValue({
      status: "ok",
      message: "Built runtime",
      entry: buildRuntimeEntry({ candidate_budget: 8_388_608 }),
    });
    vi.mocked(deleteMaterialSolverRuntime).mockResolvedValue({
      status: "ok",
      message: "Runtime deleted",
      deleted: true,
      palette_hash: "0123456789abcdef",
      layer_count: 8,
      layer_height_mm: 0.04,
      substrate: "white",
      candidate_budget: 8_388_608,
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={["red", "white"]}
        layerCount={8}
        layerHeightMm={0.04}
      />,
    );

    await waitFor(() => {
      expect(fetchMaterialSolverRuntimeStatus).toHaveBeenCalledWith(
        expect.any(Object),
        { candidateBudget: 4_194_304 },
      );
    });

    fireEvent.click(screen.getByRole("combobox", { name: "候选预算" }));
    fireEvent.click(await screen.findByRole("option", { name: /8M/ }));

    await waitFor(() => {
      expect(fetchMaterialSolverRuntimeStatus).toHaveBeenLastCalledWith(
        expect.any(Object),
        { candidateBudget: 8_388_608 },
      );
    });

    const rebuildButton = await screen.findByRole("button", {
      name: "重新构建运行时",
    });
    await act(async () => {
      fireEvent.click(rebuildButton);
    });
    await waitFor(() => {
      expect(buildMaterialSolverRuntime).toHaveBeenCalledTimes(1);
    });
    expect(buildMaterialSolverRuntime).toHaveBeenLastCalledWith(
      expect.any(Object),
      { candidateBudget: 8_388_608 },
    );

    const deleteButton = await screen.findByRole("button", {
      name: "删除运行时",
    });
    await act(async () => {
      fireEvent.click(deleteButton);
    });
    await waitFor(() => {
      expect(deleteMaterialSolverRuntime).toHaveBeenCalledTimes(1);
    });
    expect(deleteMaterialSolverRuntime).toHaveBeenLastCalledWith(
      expect.any(Object),
      { candidateBudget: 8_388_608 },
    );

    confirmSpy.mockRestore();
  });

  it("disables cache build for low-grid extreme combination counts", async () => {
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "No cache found",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 8,
      layer_height_mm: 0.08,
      substrate: "white",
      entry: null,
    });

    render(
      <MaterialSolverCacheStatusCard
        materialDirectoryNames={Array.from(
          { length: 22 },
          (_, idx) => `mat-${idx}`,
        )}
        layerCount={8}
        layerHeightMm={0.08}
      />,
    );

    const buildButton = await screen.findByRole("button", {
      name: "立即构建缓存",
    });
    expect(buildButton).toBeDisabled();
    expect(
      screen.getByText(/超过穷举或内存预算/),
    ).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(buildButton);
    });
    expect(buildMaterialSolverCache).not.toHaveBeenCalled();
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

  it("forwards the chosen gridResolution to every API call when the opt-in toggle is on", async () => {
    // Flip the store into opt-in mode with medium density before the card mounts.
    useSettingsStore.setState({
      enableSolverCacheGridSelection: true,
      solverCacheGridResolution: 128,
    });

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
      entry: buildCacheEntry({ grid_resolution: 128 }),
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

    // 1) The initial status query targets grid 128.
    await waitFor(() => {
      expect(fetchMaterialSolverCacheStatus).toHaveBeenCalledTimes(1);
    });
    expect(fetchMaterialSolverCacheStatus).toHaveBeenLastCalledWith(
      expect.any(Object),
      { gridResolution: 128 },
    );

    // 2) Build also targets grid 128.
    const buildButton = await screen.findByRole("button", {
      name: "立即构建缓存",
    });
    await act(async () => {
      fireEvent.click(buildButton);
    });
    await waitFor(() => {
      expect(buildMaterialSolverCache).toHaveBeenCalledTimes(1);
    });
    expect(buildMaterialSolverCache).toHaveBeenLastCalledWith(
      expect.any(Object),
      { gridResolution: 128 },
    );

    // 3) Delete the entry and confirm the delete call also targets grid 128.
    const deleteButton = await screen.findByRole("button", {
      name: "删除缓存",
    });
    await act(async () => {
      fireEvent.click(deleteButton);
    });
    await waitFor(() => {
      expect(deleteMaterialSolverCache).toHaveBeenCalledTimes(1);
    });
    expect(deleteMaterialSolverCache).toHaveBeenLastCalledWith(
      expect.any(Object),
      { gridResolution: 128 },
    );

    confirmSpy.mockRestore();
  });
});
