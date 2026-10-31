import { waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SelectionDocumentResponse } from "../api/types";

const apiMocks = vi.hoisted(() => ({
  colorHighlight: vi.fn(),
  getEditorSelection: vi.fn(),
  mutateEditorSelection: vi.fn(),
}));

vi.mock("../api/converter", async () => ({
  ...await vi.importActual<typeof import("../api/converter")>("../api/converter"),
  ...apiMocks,
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => { resolve = res; });
  return { promise, resolve };
}

function selection(revision: number, colors: string[]): SelectionDocumentResponse {
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
    selected_pixel_count: colors.length * 10,
    selected_component_count: colors.length,
    selected_color_hexes: colors.map((hex) => `#${hex}`),
    region_ids: components.map((component) => component.region_id),
    components,
    contours: [],
    can_undo: revision > 0,
    can_redo: false,
  };
}

async function loadStore() {
  const { useConverterStore } = await import("../stores/converter");
  useConverterStore.setState({
    sessionId: "session-highlight",
    selectionMode: "select-all",
    selectionTool: "same-color",
    previewImageUrl: "/api/files/base.png",
    previewBaseImageUrl: "/api/files/base.png",
    originalPreviewUrl: "/api/files/base.png",
  });
  return useConverterStore;
}

describe("converter store palette selection", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.resetModules();
  });

  it("hydrates a new session and serializes rapid palette clicks into its selection history", async () => {
    const firstSelection = deferred<SelectionDocumentResponse>();
    apiMocks.getEditorSelection.mockResolvedValueOnce(selection(0, []));
    apiMocks.mutateEditorSelection
      .mockReturnValueOnce(firstSelection.promise)
      .mockResolvedValueOnce(selection(2, ["555555", "666666"]));
    const useConverterStore = await loadStore();

    useConverterStore.getState().toggleColorInSelection("555555");
    useConverterStore.getState().toggleColorInSelection("666666");
    await waitFor(() => expect(apiMocks.mutateEditorSelection).toHaveBeenCalledTimes(1));
    expect(apiMocks.mutateEditorSelection).toHaveBeenNthCalledWith(1, expect.objectContaining({
      operation: "same-color-toggle",
      color_hex: "555555",
      base_selection_revision: 0,
      content_revision: 1,
    }));

    firstSelection.resolve(selection(1, ["555555"]));
    await waitFor(() => expect(useConverterStore.getState().selectionDocument?.selection_revision).toBe(2));
    expect(apiMocks.mutateEditorSelection).toHaveBeenNthCalledWith(2, expect.objectContaining({
      color_hex: "666666",
      base_selection_revision: 1,
      content_revision: 1,
    }));
    expect(useConverterStore.getState().selectedColors).toEqual(new Set(["555555", "666666"]));
    expect(useConverterStore.getState().historyCanUndo).toBe(true);
    expect(apiMocks.colorHighlight).not.toHaveBeenCalled();
    expect(useConverterStore.getState().previewImageUrl).toBe("/api/files/base.png");
  });

  it("drops an old palette selection response after switching sessions", async () => {
    const response = deferred<SelectionDocumentResponse>();
    apiMocks.mutateEditorSelection.mockReturnValueOnce(response.promise);
    const useConverterStore = await loadStore();
    useConverterStore.setState({ selectionDocument: selection(0, []) });

    useConverterStore.getState().toggleColorInSelection("555555");
    await waitFor(() => expect(apiMocks.mutateEditorSelection).toHaveBeenCalledTimes(1));
    useConverterStore.setState({ sessionId: "session-after", selectionDocument: selection(0, []) });
    response.resolve(selection(1, ["555555"]));
    await response.promise;
    await Promise.resolve();

    expect(useConverterStore.getState().sessionId).toBe("session-after");
    expect(useConverterStore.getState().selectionDocument?.selection_revision).toBe(0);
    expect(useConverterStore.getState().selectedColors.size).toBe(0);
    expect(useConverterStore.getState().previewImageUrl).toBe("/api/files/base.png");
  });

  it("keeps a pending palette selection when the user switches tools", async () => {
    const response = deferred<SelectionDocumentResponse>();
    apiMocks.mutateEditorSelection.mockReturnValueOnce(response.promise);
    const useConverterStore = await loadStore();
    useConverterStore.setState({ selectionDocument: selection(0, []) });

    useConverterStore.getState().toggleColorInSelection("555555");
    await waitFor(() => expect(apiMocks.mutateEditorSelection).toHaveBeenCalledTimes(1));
    useConverterStore.getState().setSelectionTool("point");
    response.resolve(selection(1, ["555555"]));
    await waitFor(() => expect(useConverterStore.getState().selectionDocument?.selection_revision).toBe(1));

    expect(useConverterStore.getState().selectionTool).toBe("point");
    expect(useConverterStore.getState().selectedColors).toEqual(new Set(["555555"]));
    expect(useConverterStore.getState().historyCanUndo).toBe(true);
  });

  it("preserves local palette toggles when no session exists", async () => {
    const useConverterStore = await loadStore();
    useConverterStore.setState({ sessionId: null });
    useConverterStore.getState().toggleColorInSelection("555555");
    expect(useConverterStore.getState().selectedColors).toEqual(new Set(["555555"]));
    useConverterStore.getState().toggleColorInSelection("555555");
    expect(useConverterStore.getState().selectedColors.size).toBe(0);
    expect(apiMocks.mutateEditorSelection).not.toHaveBeenCalled();
    expect(apiMocks.colorHighlight).not.toHaveBeenCalled();
  });
});
