import { describe, it, expect, beforeEach, vi } from "vitest";
import { useConverterStore } from "../stores/converter";
import type { SelectionDocumentResponse } from "../api/types";

// Mock the selection API so applySelectionMutation / hydrateSelectionDocument
// resolve without hitting the network.
// Mock 选区 API，让 mutation / hydration 不发真实请求。
vi.mock("../api/converter", async () => {
  const actual =
    await vi.importActual<typeof import("../api/converter")>(
      "../api/converter",
    );
  return {
    ...actual,
    getEditorSelection: vi.fn(),
    mutateEditorSelection: vi.fn(),
  };
});

import {
  getEditorSelection,
  mutateEditorSelection,
} from "../api/converter";

const mockedGet = vi.mocked(getEditorSelection);
const mockedMutate = vi.mocked(mutateEditorSelection);

function document(rev: number, contentRev = 1): SelectionDocumentResponse {
  return {
    selection_revision: rev,
    content_revision: contentRev,
    selected_pixel_count: rev > 0 ? 10 : 0,
    selected_component_count: rev > 0 ? 1 : 0,
    selected_color_hexes: rev > 0 ? ["aabbcc"] : [],
    region_ids: rev > 0 ? [`__editor_selection__:${rev}`] : [],
    components: rev > 0
      ? [{
          label: 0,
          region_id: `__editor_selection__:${rev}`,
          color_hex: "aabbcc",
          pixel_count: 10,
          bbox: [0, 0, 10, 10],
          anchor: [5, 5],
        }]
      : [],
    contours: [],
    can_undo: rev > 0,
    can_redo: false,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  useConverterStore.setState({
    sessionId: "session-a",
    selectionDocument: null,
    selectionTool: "point",
    selectionMode: "multi-select",
    selectedRegions: [],
    selectedColors: new Set<string>(),
    selectedColor: null,
    regionData: null,
    previewImageUrl: null,
    previewBaseImageUrl: null,
    error: null,
    replacePreviewLoading: false,
  });
});

describe("selection optimistic reconciliation", () => {
  it("hydration never regresses an already-confirmed revision", async () => {
    // 1) A mutation confirms rev=2.
    mockedMutate.mockResolvedValueOnce(document(2));
    const mutate = useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle",
      x: 5,
      y: 5,
      optimisticDocument: document(2),
    });
    await mutate;

    expect(useConverterStore.getState().selectionDocument?.selection_revision)
      .toBe(2);

    // 2) A slow GET returns the older rev=1; it must NOT overwrite rev=2
    //    (otherwise the next click sends base=1 and 409s against the server).
    mockedGet.mockResolvedValueOnce(document(1));
    await useConverterStore.getState().hydrateSelectionDocument();

    expect(useConverterStore.getState().selectionDocument?.selection_revision)
      .toBe(2);
  });

  it("rolls a failed mutation back to the confirmed state, not an optimistic one", async () => {
    // Seed a confirmed rev=1 via a successful mutation.
    mockedMutate.mockResolvedValueOnce(document(1));
    await useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle",
      x: 5,
      y: 5,
      optimisticDocument: document(1),
    });
    expect(useConverterStore.getState().selectionDocument?.selection_revision)
      .toBe(1);

    // Second click fails (network / 409): the optimistic doc (rev=2) was
    // applied optimistically, then the server rejects. The store must roll
    // back to the confirmed rev=1 — not keep the phantom rev=2. The rollback
    // re-hydrates from the server, which still reports the confirmed rev=1.
    mockedMutate.mockRejectedValueOnce(new Error("network"));
    mockedGet.mockResolvedValueOnce(document(1));
    await useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle",
      x: 6,
      y: 6,
      optimisticDocument: document(2),
    });

    const state = useConverterStore.getState();
    expect(state.selectionDocument?.selection_revision).toBe(1);
    expect(state.error).not.toBeNull();
  });

  it("fast successive toggles converge to the same terminal state as the server", async () => {
    // Click component A twice rapidly. The optimistic chain says:
    //   none → A (rev1) → none (rev2, toggle-off).
    // The server, replaying the same operations, must agree. The rev2
    // documents (both optimistic and confirmed) are therefore empty.
    const emptyDoc = (rev: number): SelectionDocumentResponse => ({
      selection_revision: rev,
      content_revision: 1,
      selected_pixel_count: 0,
      selected_component_count: 0,
      selected_color_hexes: [],
      region_ids: [],
      components: [],
      contours: [],
      can_undo: true,
      can_redo: false,
    });
    const serverSequence = [document(1), emptyDoc(2)];
    mockedMutate.mockImplementationOnce(() =>
      Promise.resolve(serverSequence[0]),
    );
    mockedMutate.mockImplementationOnce(() =>
      Promise.resolve(serverSequence[1]),
    );

    // Click 1 (optimistic rev1, confirmed rev1).
    const first = useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle",
      x: 5,
      y: 5,
      optimisticDocument: document(1),
    });
    // Click 2 fires while click 1 is still in flight (queued serially).
    const second = useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle",
      x: 5,
      y: 5,
      optimisticDocument: emptyDoc(2),
    });
    await Promise.all([first, second]);

    // Terminal state: empty selection (rev2), matching the server's chain.
    const state = useConverterStore.getState();
    expect(state.selectionDocument?.selection_revision).toBe(2);
    expect(state.selectionDocument?.selected_component_count).toBe(0);
  });
});
