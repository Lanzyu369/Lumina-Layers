import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MaterialSolverCacheDialog from "../components/MaterialSolverCacheDialog";
import { fetchMaterialSolverCacheStatus } from "../api/materialCache";

vi.mock("../api/materialCache", () => ({
  buildMaterialSolverCache: vi.fn(),
  deleteMaterialSolverCache: vi.fn(),
  fetchMaterialSolverCacheStatus: vi.fn(),
}));

// The open-button label comes from the zh translation of
// ``basic_material_cache_open_button``; matching on the stable prefix lets us
// query by accessible name without depending on the trailing ellipsis char.
const OPEN_BUTTON_NAME = /穷举缓存/;

describe("MaterialSolverCacheDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchMaterialSolverCacheStatus).mockResolvedValue({
      status: "ok",
      message: "Cache missing",
      cached: false,
      palette_hash: "0123456789abcdef",
      layer_count: 5,
      layer_height_mm: 0.08,
      substrate: "white",
      entry: null,
    });
  });

  it("does not render the dialog content before the button is clicked", () => {
    render(
      <MaterialSolverCacheDialog
        materialDirectoryNames={["red", "white"]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );
    expect(screen.queryByTestId("material-solver-cache-dialog")).toBeNull();
    // Cache status card should not be queried while dialog is closed.
    expect(fetchMaterialSolverCacheStatus).not.toHaveBeenCalled();
  });

  it("opens the dialog and renders the cache status card when clicked", async () => {
    render(
      <MaterialSolverCacheDialog
        materialDirectoryNames={["red", "white"]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: OPEN_BUTTON_NAME }));

    expect(
      await screen.findByTestId("material-solver-cache-dialog"),
    ).toBeInTheDocument();
    // Status card inside the dialog should kick off a status fetch.
    await waitFor(() => {
      expect(fetchMaterialSolverCacheStatus).toHaveBeenCalledTimes(1);
    });
    expect(
      screen.getByTestId("material-solver-cache-status-card"),
    ).toBeInTheDocument();
  });

  it("disables the open button when no materials are selected", () => {
    render(
      <MaterialSolverCacheDialog
        materialDirectoryNames={[]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );
    const button = screen.getByRole("button", { name: OPEN_BUTTON_NAME });
    expect(button).toBeDisabled();
  });

  it("closes when the overlay is clicked", async () => {
    render(
      <MaterialSolverCacheDialog
        materialDirectoryNames={["red", "white"]}
        layerCount={5}
        layerHeightMm={0.08}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: OPEN_BUTTON_NAME }));
    expect(
      await screen.findByTestId("material-solver-cache-dialog"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("material-solver-cache-dialog-overlay"));
    await waitFor(() => {
      expect(screen.queryByTestId("material-solver-cache-dialog")).toBeNull();
    });
  });
});
