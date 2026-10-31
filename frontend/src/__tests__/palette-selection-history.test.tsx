import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReplacementHistoryResponse, SelectionDocumentResponse } from "../api/types";
import { getEditorSelection, mutateEditorSelection, replacementHistory } from "../api/converter";
import PalettePanel from "../components/sections/PalettePanel";
import { useConverterStore } from "../stores/converter";

vi.mock("../api/converter", async () => ({
  ...await vi.importActual<typeof import("../api/converter")>("../api/converter"),
  getEditorSelection: vi.fn(),
  mutateEditorSelection: vi.fn(),
  replacementHistory: vi.fn(),
}));

vi.mock("../components/ui/CustomRecipeDialog", () => ({ default: () => null }));

const initialState = useConverterStore.getState();
let sessionNumber = 0;

function selection(
  revision: number,
  colors: string[],
  canUndo = true,
  canRedo = false,
): SelectionDocumentResponse {
  const components = colors.map((hex, index) => ({
    label: index + 1,
    region_id: `region-${hex}`,
    color_hex: `#${hex}`,
    pixel_count: 10,
    bbox: [index * 10, 0, 10, 1],
    anchor: [index * 10, 0],
  }));
  return {
    selection_revision: revision,
    content_revision: 1,
    editor_content_revision: 1,
    selected_pixel_count: colors.length * 10,
    selected_component_count: colors.length,
    selected_color_hexes: colors.map((hex) => `#${hex}`),
    region_ids: components.map((component) => component.region_id),
    components,
    contours: [],
    can_undo: canUndo,
    can_redo: canRedo,
  };
}

function historyResponse(
  action: "undo" | "redo",
  document: SelectionDocumentResponse,
): ReplacementHistoryResponse {
  return {
    status: "ok",
    action,
    entry_kind: "selection",
    message: "ok",
    preview_url: "/api/files/base.png",
    replacement_regions: [],
    recipe_overrides: [],
    recipe_override_count: 0,
    region_replacement_count: 0,
    editor_content_revision: 1,
    can_undo: document.can_undo,
    can_redo: document.can_redo,
    selection: document,
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  sessionNumber += 1;
  useConverterStore.setState({
    ...initialState,
    sessionId: `palette-history-${sessionNumber}`,
    palette: [
      { quantized_hex: "ee0000", matched_hex: "ee0000", pixel_count: 10, percentage: 50 },
      { quantized_hex: "00ee00", matched_hex: "00ee00", pixel_count: 10, percentage: 50 },
    ],
    selectionMode: "select-all",
    selectionTool: "same-color",
    previewBaseImageUrl: "/api/files/base.png",
    previewImageUrl: "/api/files/base.png",
  });
});

describe("palette shared selection and history", () => {
  it("records palette selection and chip removal in the shared selection history", async () => {
    vi.mocked(getEditorSelection).mockResolvedValueOnce(selection(0, [], false));
    await useConverterStore.getState().hydrateSelectionDocument();
    vi.mocked(mutateEditorSelection)
      .mockResolvedValueOnce(selection(1, ["ee0000"]))
      .mockResolvedValueOnce(selection(2, ["ee0000", "00ee00"]))
      .mockResolvedValueOnce(selection(3, ["00ee00"]));
    render(<PalettePanel />);

    expect(screen.getByRole("button", { name: "撤销" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /颜色 ee0000/ }));
    await waitFor(() => expect(useConverterStore.getState().selectionDocument?.region_ids)
      .toEqual(["region-ee0000"]));
    expect(screen.getByRole("button", { name: "撤销" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /颜色 ee0000/ })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: /颜色 00ee00/ }));
    await waitFor(() => expect(useConverterStore.getState().selectionDocument?.region_ids)
      .toEqual(["region-ee0000", "region-00ee00"]));
    fireEvent.click(screen.getByTitle("#ee0000 — 点击取消选择"));
    await waitFor(() => expect(useConverterStore.getState().selectionDocument?.region_ids)
      .toEqual(["region-00ee00"]));

    expect(vi.mocked(mutateEditorSelection).mock.calls.map(([request]) => ({
      operation: request.operation,
      color: request.color_hex,
      revision: request.base_selection_revision,
    }))).toEqual([
      { operation: "same-color-toggle", color: "ee0000", revision: 0 },
      { operation: "same-color-toggle", color: "00ee00", revision: 1 },
      { operation: "same-color-remove", color: "ee0000", revision: 2 },
    ]);
    expect(screen.getByRole("button", { name: /颜色 ee0000/ })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: /颜色 00ee00/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "撤销" })).toBeEnabled();
  });

  it("repeated removal clicks never toggle a selected color back on", async () => {
    vi.mocked(getEditorSelection).mockResolvedValueOnce(selection(1, ["ee0000", "00ee00"]));
    await useConverterStore.getState().hydrateSelectionDocument();
    let resolveRemoval!: (document: SelectionDocumentResponse) => void;
    vi.mocked(mutateEditorSelection)
      .mockReturnValueOnce(new Promise((resolve) => { resolveRemoval = resolve; }))
      .mockResolvedValueOnce(selection(2, ["00ee00"]));
    render(<PalettePanel />);

    const removeRed = screen.getByTitle("#ee0000 — 点击取消选择");
    fireEvent.click(removeRed);
    fireEvent.click(removeRed);
    await waitFor(() => expect(mutateEditorSelection).toHaveBeenCalledTimes(1));
    await act(async () => { resolveRemoval(selection(2, ["00ee00"])); });
    await waitFor(() => expect(mutateEditorSelection).toHaveBeenCalledTimes(2));

    expect(vi.mocked(mutateEditorSelection).mock.calls.map(([request]) => request.operation))
      .toEqual(["same-color-remove", "same-color-remove"]);
    expect(useConverterStore.getState().selectedColors).toEqual(new Set(["00ee00"]));
    expect(screen.getByRole("button", { name: /颜色 ee0000/ })).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByTitle("#ee0000 — 点击取消选择")).not.toBeInTheDocument();
  });

  it("keeps clear selection and history buttons usable after undo and redo", async () => {
    vi.mocked(getEditorSelection).mockResolvedValueOnce(selection(1, ["ee0000"]));
    await useConverterStore.getState().hydrateSelectionDocument();
    vi.mocked(replacementHistory)
      .mockResolvedValueOnce(historyResponse("undo", selection(2, [], false, true)))
      .mockResolvedValueOnce(historyResponse("redo", selection(3, ["ee0000"])))
      .mockResolvedValueOnce(historyResponse("undo", selection(5, ["ee0000"], true, true)));
    vi.mocked(mutateEditorSelection).mockResolvedValueOnce(selection(4, []));
    render(<PalettePanel />);

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "撤销" })); });
    expect(screen.getByRole("button", { name: "撤销" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重做" })).toBeEnabled();
    expect(useConverterStore.getState().selectedColors.size).toBe(0);

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "重做" })); });
    expect(screen.getByRole("button", { name: "撤销" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "重做" })).toBeDisabled();
    expect(useConverterStore.getState().selectedColors).toEqual(new Set(["ee0000"]));

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "全不选" })); });
    expect(mutateEditorSelection).toHaveBeenCalledWith(expect.objectContaining({
      operation: "clear",
      base_selection_revision: 3,
      content_revision: 1,
    }));
    expect(useConverterStore.getState().selectedColors.size).toBe(0);
    expect(useConverterStore.getState().selectedColor).toBeNull();
    expect(screen.getByRole("button", { name: "撤销" })).toBeEnabled();

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "撤销" })); });
    expect(useConverterStore.getState().selectedColors).toEqual(new Set(["ee0000"]));
    expect(screen.getByRole("button", { name: "重做" })).toBeEnabled();
  });
});
