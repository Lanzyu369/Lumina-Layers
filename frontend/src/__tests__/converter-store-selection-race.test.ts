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
    replaceColorsBatch: vi.fn(),
    regionReplace: vi.fn(),
    mutateFreeColors: vi.fn(),
    getEditorCommitStatus: vi.fn(),
    replacementHistory: vi.fn(),
  };
});

import {
  getEditorSelection,
  mutateEditorSelection,
  replaceColorsBatch,
  regionReplace,
  mutateFreeColors,
  getEditorCommitStatus,
  replacementHistory,
} from "../api/converter";

const mockedGet = vi.mocked(getEditorSelection);
const mockedMutate = vi.mocked(mutateEditorSelection);
const mockedReplaceColorsBatch = vi.mocked(replaceColorsBatch);
const mockedRegionReplace = vi.mocked(regionReplace);
const mockedMutateFreeColors = vi.mocked(mutateFreeColors);
const mockedGetEditorCommitStatus = vi.mocked(getEditorCommitStatus);
const mockedHistory = vi.mocked(replacementHistory);
let sessionCounter = 0;

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

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
  sessionCounter += 1;
  useConverterStore.setState({
    sessionId: `session-a-${sessionCounter}`,
    selectionDocument: null,
    pendingSelectionMutations: [],
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
    pendingReplacement: null,
    contentCommitStatus: "idle",
    contentCommitOperationId: null,
    historyCanUndo: false,
    historyCanRedo: false,
    historyBusy: false,
    gradientSelection: null,
    selectedGradientRegions: [],
  });
});

describe("selection confirmation and ordering", () => {
  it.each(["select-all", "multi-select", "current", "region"] as const)(
    "replaces the shared pixels regardless of the picker's %s mode",
    async (mode) => {
      const selected = document(1);
      useConverterStore.setState({
        selectionDocument: selected,
        pendingReplacement: { sourceHex: "aabbcc", targetHex: "ff0000", mode },
      });
      mockedRegionReplace.mockResolvedValueOnce({
        preview_url: "/api/files/replaced.png", message: "ok", selection: document(2, 2),
      });
      await useConverterStore.getState().confirmReplacement();
      expect(mockedRegionReplace).toHaveBeenCalledWith(
        useConverterStore.getState().sessionId, "#ff0000", undefined, 1, expect.any(String),
      );
      expect(mockedReplaceColorsBatch).not.toHaveBeenCalled();
      expect(useConverterStore.getState().selectedColors).toEqual(new Set(["aabbcc"]));
      expect(useConverterStore.getState().historyCanUndo).toBe(true);
    },
  );

  it("submits repeated region removal as idempotent removal commands", async () => {
    useConverterStore.setState({ selectionDocument: document(1) });
    const removal = deferred<SelectionDocumentResponse>();
    const empty = { ...document(0), selection_revision: 2, can_undo: true };
    mockedMutate.mockReturnValueOnce(removal.promise).mockResolvedValueOnce(empty);
    useConverterStore.getState().removeRegionFromSelection("__editor_selection__:1");
    useConverterStore.getState().removeRegionFromSelection("__editor_selection__:1");
    await vi.waitFor(() => expect(mockedMutate).toHaveBeenCalledOnce());
    expect(useConverterStore.getState().selectionDocument?.selected_pixel_count).toBe(10);
    removal.resolve(empty);
    await vi.waitFor(() => expect(mockedMutate).toHaveBeenCalledTimes(2));
    expect(mockedMutate.mock.calls.map(([request]) => request.operation)).toEqual(["point-remove", "point-remove"]);
    await vi.waitFor(() => expect(useConverterStore.getState().selectionDocument?.selected_pixel_count).toBe(0));
  });

  it("records clear even when the first selection is still being initialized", async () => {
    const firstSelection = deferred<SelectionDocumentResponse>();
    mockedGet.mockResolvedValueOnce(document(0));
    mockedMutate.mockReturnValueOnce(firstSelection.promise);
    mockedMutate.mockResolvedValueOnce({ ...document(0), selection_revision: 2, can_undo: true });
    const first = useConverterStore.getState().applySelectionMutation({ operation: "point-toggle", x: 5, y: 5 });
    const clear = useConverterStore.getState().clearSelection();
    expect(useConverterStore.getState().pendingSelectionMutations.map((item) => item.input.operation))
      .toEqual(["point-toggle", "clear"]);
    await vi.waitFor(() => expect(mockedMutate).toHaveBeenCalledOnce());
    expect(useConverterStore.getState().selectionDocument?.selection_revision).toBe(0);
    firstSelection.resolve(document(1));
    await Promise.all([first, clear]);
    expect(mockedMutate.mock.calls[1][0]).toMatchObject({ operation: "clear", base_selection_revision: 1 });
    expect(useConverterStore.getState().selectionDocument?.selected_pixel_count).toBe(0);
    expect(useConverterStore.getState().historyCanUndo).toBe(true);
    expect(useConverterStore.getState().pendingSelectionMutations).toEqual([]);
  });

  it("publishes a confirmed document and removes its visual intent atomically", async () => {
    const firstResponse = deferred<SelectionDocumentResponse>();
    const secondResponse = deferred<SelectionDocumentResponse>();
    useConverterStore.setState({ selectionDocument: document(0) });
    mockedMutate.mockReturnValueOnce(firstResponse.promise).mockReturnValueOnce(secondResponse.promise);
    const first = useConverterStore.getState().applySelectionMutation({ operation: "point-toggle", x: 5, y: 5 });
    const firstId = useConverterStore.getState().pendingSelectionMutations[0].id;
    const second = useConverterStore.getState().applySelectionMutation({ operation: "point-toggle", x: 15, y: 5 });
    expect(useConverterStore.getState().selectionDocument?.selection_revision).toBe(0);
    expect(useConverterStore.getState().historyCanUndo).toBe(false);
    const publications: Array<{ revision: number | undefined; ids: number[] }> = [];
    const unsubscribe = useConverterStore.subscribe((state) => publications.push({
      revision: state.selectionDocument?.selection_revision,
      ids: state.pendingSelectionMutations.map((item) => item.id),
    }));
    firstResponse.resolve(document(1));
    await first;
    expect(useConverterStore.getState().pendingSelectionMutations).toHaveLength(1);
    expect(publications.some((state) => state.revision === 1 && state.ids.includes(firstId))).toBe(false);
    secondResponse.resolve(document(2));
    await second;
    unsubscribe();
    expect(useConverterStore.getState().pendingSelectionMutations).toEqual([]);
  });

  it("waits for the first selection to enable undo, then orders the next click after undo", async () => {
    const firstSelection = deferred<SelectionDocumentResponse>();
    const undoResponse = deferred<Awaited<ReturnType<typeof replacementHistory>>>();
    useConverterStore.setState({ selectionDocument: document(0) });
    mockedMutate.mockReturnValueOnce(firstSelection.promise);
    mockedMutate.mockResolvedValueOnce(document(3));
    mockedHistory.mockReturnValueOnce(undoResponse.promise);
    const first = useConverterStore.getState().applySelectionMutation({ operation: "point-toggle", x: 5, y: 5 });
    const undo = useConverterStore.getState().undoColorRemap();
    const next = useConverterStore.getState().applySelectionMutation({ operation: "point-toggle", x: 15, y: 5 });
    await vi.waitFor(() => expect(mockedMutate).toHaveBeenCalledOnce());
    firstSelection.resolve(document(1));
    await vi.waitFor(() => expect(mockedHistory).toHaveBeenCalledOnce());
    expect(mockedMutate).toHaveBeenCalledTimes(1);
    undoResponse.resolve({
      status: "ok", action: "undo", entry_kind: "selection", message: "ok",
      preview_url: "/api/files/preview.png", can_undo: false, can_redo: true,
      replacement_regions: [], recipe_overrides: [], recipe_override_count: 0,
      selection: { ...document(0), selection_revision: 2, can_redo: true },
    });
    await Promise.all([first, undo, next]);
    expect(mockedMutate.mock.calls[1][0]).toMatchObject({
      operation: "point-toggle", base_selection_revision: 2, x: 15,
    });
    expect(useConverterStore.getState().selectionDocument?.selection_revision).toBe(3);
    expect(useConverterStore.getState().historyCanRedo).toBe(false);
  });

  it("hydration never regresses an already-confirmed revision", async () => {
    // 1) A mutation confirms rev=2.
    mockedMutate.mockResolvedValueOnce(document(2));
    const mutate = useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle",
      x: 5,
      y: 5,
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

  it("keeps confirmed selection visible when a mutation fails", async () => {
    // Seed a confirmed rev=1 via a successful mutation.
    mockedMutate.mockResolvedValueOnce(document(1));
    await useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle",
      x: 5,
      y: 5,
    });
    expect(useConverterStore.getState().selectionDocument?.selection_revision)
      .toBe(1);

    // A failed click keeps the last confirmed selection and reconciles it
    // before allowing another queued gesture to run.
    mockedMutate.mockRejectedValueOnce(new Error("network"));
    mockedGet.mockResolvedValueOnce(document(1));
    await useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle",
      x: 6,
      y: 6,
    });

    const state = useConverterStore.getState();
    expect(state.selectionDocument?.selection_revision).toBe(1);
    expect(state.error).not.toBeNull();
  });

  it("fast successive toggles converge to the same terminal state as the server", async () => {
    // Click component A twice rapidly: none → A → none. Each gesture must
    // use the preceding server confirmation as its base revision.
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

    // Click 1, confirmed rev1.
    const first = useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle",
      x: 5,
      y: 5,
    });
    // Click 2 fires while click 1 is still in flight (queued serially).
    const second = useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle",
      x: 5,
      y: 5,
    });
    await Promise.all([first, second]);

    // Terminal state: empty selection (rev2), matching the server's chain.
    const state = useConverterStore.getState();
    expect(state.selectionDocument?.selection_revision).toBe(2);
    expect(state.selectionDocument?.selected_component_count).toBe(0);
  });

  it("adopts the authoritative selection content revision after a global replacement", async () => {
    const sessionId = "global-replace-content-sync";
    useConverterStore.setState({
      sessionId,
      selectionDocument: document(1, 1),
      colorRemapMap: { aabbcc: "ffffff" },
      palette: [
        {
          quantized_hex: "aabbcc",
          matched_hex: "aabbcc",
          pixel_count: 10,
          percentage: 1,
        },
      ],
    });
    mockedReplaceColorsBatch.mockResolvedValueOnce({
      status: "ok",
      message: "ok",
      preview_url: "/api/files/replaced.png",
      replacement_count: 1,
      selection: document(2, 7),
    } as never);

    await useConverterStore.getState().submitReplacePreview();

    expect(useConverterStore.getState().selectionDocument).toMatchObject({
      selection_revision: 2,
      content_revision: 7,
    });
  });

  it("queries the operation receipt when a replacement response is lost", async () => {
    const sessionId = "lost-replacement-response";
    useConverterStore.setState({
      sessionId,
      selectionDocument: document(1, 1),
      colorRemapMap: { aabbcc: "ffffff" },
      palette: [
        {
          quantized_hex: "aabbcc",
          matched_hex: "aabbcc",
          pixel_count: 10,
          percentage: 1,
        },
      ],
    });
    mockedReplaceColorsBatch.mockRejectedValueOnce(new Error("response lost"));
    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "committed",
      operation_id: "replace-op-1",
      editor_content_revision: 7,
      selection_revision: 1,
    });
    mockedGet.mockResolvedValueOnce(document(1, 7));

    await useConverterStore.getState().submitReplacePreview();

    const state = useConverterStore.getState();
    expect(mockedGetEditorCommitStatus).toHaveBeenCalledWith(
      sessionId,
      expect.any(String),
    );
    expect(mockedGet).toHaveBeenCalledWith(sessionId);
    expect(state.selectionDocument).toMatchObject({
      selection_revision: 1,
      content_revision: 7,
    });
    expect(state.colorRemapMap).toEqual({ aabbcc: "ffffff" });
    expect(state.replacePreviewLoading).toBe(false);
    expect(state.error).toContain("已确认本次编辑已提交");
  });

  it("keeps the confirmed selection revision when receipt hydration is unavailable", async () => {
    const sessionId = "lost-selection-hydration";
    useConverterStore.setState({
      sessionId,
      selectionDocument: document(3, 1),
      colorRemapMap: { aabbcc: "ffffff" },
      palette: [
        {
          quantized_hex: "aabbcc",
          matched_hex: "aabbcc",
          pixel_count: 10,
          percentage: 1,
        },
      ],
    });
    mockedReplaceColorsBatch.mockRejectedValueOnce(new Error("response lost"));
    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "committed",
      operation_id: "replace-op-hydration-lost",
      editor_content_revision: 7,
      selection_revision: 3,
    });
    mockedGet.mockRejectedValueOnce(new Error("selection read unavailable"));

    await useConverterStore.getState().submitReplacePreview();

    expect(useConverterStore.getState().selectionDocument?.editor_content_revision)
      .toBe(7);

    mockedMutate.mockResolvedValueOnce(document(4, 7));
    await useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle",
      x: 5,
      y: 5,
    });

    expect(mockedMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        session_id: sessionId,
        base_selection_revision: 3,
        content_revision: 7,
      }),
    );
  });

  it("serializes same-class content edits before capturing a new preview epoch", async () => {
    const sessionId = "serial-content-edits";
    const firstCommit = deferred<unknown>();
    useConverterStore.setState({
      sessionId,
      selectionDocument: document(1, 1),
      selectedColors: new Set(["aabbcc"]),
      selectedColor: "aabbcc",
      palette: [
        {
          quantized_hex: "aabbcc",
          matched_hex: "aabbcc",
          pixel_count: 10,
          percentage: 1,
        },
      ],
    });
    mockedReplaceColorsBatch
      .mockReturnValueOnce(firstCommit.promise as never)
      .mockResolvedValueOnce({
        status: "ok",
        message: "ok",
        preview_url: "/api/files/replaced-2.png",
        replacement_count: 1,
        selection: document(1, 3),
      } as never);

    const firstRequest = useConverterStore
      .getState()
      .applyBatchColorRemap("ff0000");
    await Promise.resolve();
    await Promise.resolve();
    expect(mockedReplaceColorsBatch).toHaveBeenCalledTimes(1);

    const secondRequest = useConverterStore
      .getState()
      .applyBatchColorRemap("00ff00");
    await Promise.resolve();
    await Promise.resolve();
    expect(mockedReplaceColorsBatch).toHaveBeenCalledTimes(1);

    firstCommit.resolve({
      status: "ok",
      message: "ok",
      preview_url: "/api/files/replaced-1.png",
      replacement_count: 1,
      selection: document(1, 2),
    });
    await Promise.all([firstRequest, secondRequest]);

    expect(mockedReplaceColorsBatch).toHaveBeenCalledTimes(2);
    expect(
      mockedReplaceColorsBatch.mock.calls[0]?.[2],
    ).not.toBe(mockedReplaceColorsBatch.mock.calls[1]?.[2]);
  });

  it("allows a new content edit after a confirmed pre-commit failure", async () => {
    const sessionId = "failed-edit-can-retry";
    useConverterStore.setState({
      sessionId,
      selectionDocument: document(1, 1),
      colorRemapMap: { aabbcc: "ffffff" },
      palette: [
        {
          quantized_hex: "aabbcc",
          matched_hex: "aabbcc",
          pixel_count: 10,
          percentage: 1,
        },
      ],
    });
    mockedReplaceColorsBatch
      .mockRejectedValueOnce(new Error("pre-commit failure"))
      .mockResolvedValueOnce({
        status: "ok",
        message: "ok",
        preview_url: "/api/files/retry-success.png",
        replacement_count: 1,
      } as never);
    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "failed",
      operation_id: "failed-operation",
      editor_content_revision: 1,
      selection_revision: 1,
    });

    await useConverterStore.getState().submitReplacePreview();
    expect(useConverterStore.getState().contentCommitStatus).toBe("failed");

    await useConverterStore.getState().submitReplacePreview();

    expect(mockedReplaceColorsBatch).toHaveBeenCalledTimes(2);
    expect(useConverterStore.getState().previewImageUrl).toBe(
      "/api/files/retry-success.png",
    );
  });

  it("queries a stale same-session response before releasing the content barrier", async () => {
    const sessionId = "stale-response-receipt-barrier";
    const replacementResponse = deferred<unknown>();
    const receiptResponse = deferred<Awaited<ReturnType<typeof getEditorCommitStatus>>>();
    useConverterStore.setState({
      sessionId,
      selectionDocument: document(1, 1),
      colorRemapMap: { aabbcc: "ffffff" },
      palette: [
        {
          quantized_hex: "aabbcc",
          matched_hex: "aabbcc",
          pixel_count: 10,
          percentage: 1,
        },
      ],
    });
    mockedReplaceColorsBatch.mockReturnValueOnce(
      replacementResponse.promise as never,
    );
    mockedGetEditorCommitStatus.mockReturnValueOnce(
      receiptResponse.promise as never,
    );

    const replacementRequest = useConverterStore.getState().submitReplacePreview();
    await vi.waitFor(() => {
      expect(mockedReplaceColorsBatch).toHaveBeenCalledTimes(1);
    });
    // Make the response stale without switching sessions. The operation must
    // still be reconciled before a dependent selection mutation is sent.
    useConverterStore.setState((state) => ({
      previewRequestRevision: state.previewRequestRevision + 1,
    }));
    replacementResponse.resolve({
      status: "ok",
      message: "ok",
      preview_url: "/api/files/stale.png",
      replacement_count: 1,
      selection: document(1, 7),
    });

    const selectionRequest = useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle",
      x: 5,
      y: 5,
    });
    await Promise.resolve();
    await Promise.resolve();
    expect(mockedGetEditorCommitStatus).toHaveBeenCalledWith(
      sessionId,
      expect.any(String),
    );
    expect(mockedMutate).not.toHaveBeenCalled();

    receiptResponse.resolve({
      status: "committed",
      operation_id: "stale-op",
      editor_content_revision: 7,
      visible_content_revision: 7,
      selection_revision: 1,
    });
    mockedMutate.mockResolvedValueOnce(document(2, 7));
    await Promise.all([replacementRequest, selectionRequest]);

    expect(mockedMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        session_id: sessionId,
        content_revision: 7,
      }),
    );
  });

  it("queries a stale same-session error before releasing the content barrier", async () => {
    const sessionId = "stale-error-receipt-barrier";
    const replacementResponse = deferred<unknown>();
    const receiptResponse = deferred<Awaited<ReturnType<typeof getEditorCommitStatus>>>();
    useConverterStore.setState({
      sessionId,
      selectionDocument: document(1, 1),
      colorRemapMap: { aabbcc: "ffffff" },
      palette: [
        {
          quantized_hex: "aabbcc",
          matched_hex: "aabbcc",
          pixel_count: 10,
          percentage: 1,
        },
      ],
    });
    mockedReplaceColorsBatch.mockReturnValueOnce(
      replacementResponse.promise as never,
    );
    mockedGetEditorCommitStatus.mockReturnValueOnce(
      receiptResponse.promise as never,
    );

    const replacementRequest = useConverterStore.getState().submitReplacePreview();
    await vi.waitFor(() => {
      expect(mockedReplaceColorsBatch).toHaveBeenCalledTimes(1);
    });
    useConverterStore.setState((state) => ({
      previewRequestRevision: state.previewRequestRevision + 1,
    }));
    replacementResponse.reject(new Error("late response error"));

    const selectionRequest = useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle",
      x: 5,
      y: 5,
    });
    await Promise.resolve();
    await Promise.resolve();
    expect(mockedGetEditorCommitStatus).toHaveBeenCalledWith(
      sessionId,
      expect.any(String),
    );
    expect(mockedMutate).not.toHaveBeenCalled();

    receiptResponse.resolve({
      status: "committed",
      operation_id: "stale-error-op",
      editor_content_revision: 7,
      visible_content_revision: 7,
      selection_revision: 1,
    });
    mockedMutate.mockResolvedValueOnce(document(2, 7));
    await Promise.all([replacementRequest, selectionRequest]);

    expect(mockedMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        session_id: sessionId,
        content_revision: 7,
      }),
    );
  });

  it("advances the generation revision after a free-colour commit", async () => {
    const sessionId = "free-color-content-sync";
    useConverterStore.setState({
      sessionId,
      selectionDocument: document(1, 1),
    });
    mockedMutateFreeColors.mockResolvedValueOnce({
      status: "ok",
      free_color_set: ["ff0000"],
      can_undo: true,
      can_redo: false,
      editor_content_revision: 4,
    });

    useConverterStore.getState().toggleFreeColor("#ff0000");
    await vi.waitFor(() => {
      expect(mockedMutateFreeColors).toHaveBeenCalled();
    });

    expect(useConverterStore.getState().selectionDocument).toMatchObject({
      editor_content_revision: 4,
    });
    expect(useConverterStore.getState().contentCommitStatus).toBe("committed");

    mockedMutate.mockResolvedValueOnce(document(2, 1));
    await useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle",
      x: 5,
      y: 5,
    });
    expect(mockedMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        base_selection_revision: 1,
        content_revision: 1,
      }),
    );
  });

  it.each(["toggle", "clear"] as const)(
    "waits for an earlier selection before a free-color %s and its receipt hydration",
    async (action) => {
      const selectionResponse = deferred<SelectionDocumentResponse>();
      const selected = { ...document(1), selected_color_hexes: ["112233"], editor_content_revision: 2 };
      useConverterStore.setState({ selectionDocument: document(0) });
      mockedMutate.mockReturnValueOnce(selectionResponse.promise);
      mockedMutateFreeColors.mockRejectedValueOnce(new Error("response lost after commit"));
      mockedGetEditorCommitStatus.mockResolvedValueOnce({
        status: "committed", operation_id: "free-color-after-selection", operation: "free_colors",
        editor_content_revision: 2, visible_content_revision: 1, selection_revision: 1,
        result: { free_color_set: action === "toggle" ? ["112233"] : [], can_undo: true, can_redo: false },
      });
      mockedGet.mockResolvedValueOnce(selected);
      const publications: Array<{ revision: number | undefined; pending: number }> = [];
      const unsubscribe = useConverterStore.subscribe((state) => publications.push({
        revision: state.selectionDocument?.selection_revision,
        pending: state.pendingSelectionMutations.length,
      }));
      const selection = useConverterStore.getState().applySelectionMutation({ operation: "point-toggle", x: 5, y: 5 });
      await vi.waitFor(() => expect(mockedMutate).toHaveBeenCalledOnce());
      if (action === "toggle") useConverterStore.getState().toggleFreeColor("aabbcc");
      else useConverterStore.getState().clearFreeColors();
      // Let the queued free-color action reach its selection barrier.
      await new Promise((resolve) => setTimeout(resolve, 0));
      const sentBeforeSelection = mockedMutateFreeColors.mock.calls.length;
      selectionResponse.resolve(selected);
      await selection;
      await vi.waitFor(() => expect(useConverterStore.getState().contentCommitStatus).toBe("committed"));
      unsubscribe();

      expect(sentBeforeSelection).toBe(0);
      expect(publications.some((state) => state.revision === 1 && state.pending > 0)).toBe(false);
      expect(mockedMutateFreeColors).toHaveBeenCalledWith(
        useConverterStore.getState().sessionId, action, action === "toggle" ? ["112233"] : [], expect.any(String),
      );
      expect(useConverterStore.getState().selectionDocument).toBe(selected);
    },
  );

  it.each(["toggle", "clear"] as const)(
    "lets a free-color %s started first finish before a later selection",
    async (action) => {
      const freeColorResponse = deferred<Awaited<ReturnType<typeof mutateFreeColors>>>();
      useConverterStore.setState({ selectionDocument: document(1) });
      mockedMutateFreeColors.mockReturnValueOnce(freeColorResponse.promise);
      mockedMutate.mockResolvedValueOnce(document(2));
      if (action === "toggle") useConverterStore.getState().toggleFreeColor("aabbcc");
      else useConverterStore.getState().clearFreeColors();
      const selection = useConverterStore.getState().applySelectionMutation({ operation: "point-toggle", x: 5, y: 5 });
      await vi.waitFor(() => expect(mockedMutateFreeColors).toHaveBeenCalledOnce());
      expect(mockedMutate).not.toHaveBeenCalled();
      freeColorResponse.resolve({
        status: "ok", free_color_set: action === "toggle" ? ["aabbcc"] : [],
        can_undo: true, can_redo: false, editor_content_revision: 2,
      });
      await selection;
      expect(mockedMutate).toHaveBeenCalledOnce();
      expect(useConverterStore.getState().selectionDocument?.selection_revision).toBe(2);
    },
  );

  it.each(["toggle", "clear"] as const)(
    "keeps a free-color %s between earlier and later queued selections",
    async (action) => {
      const firstSelection = deferred<SelectionDocumentResponse>();
      const secondSelection = deferred<SelectionDocumentResponse>();
      const freeColorResponse = deferred<Awaited<ReturnType<typeof mutateFreeColors>>>();
      useConverterStore.setState({ selectionDocument: document(0) });
      mockedMutate.mockReturnValueOnce(firstSelection.promise).mockReturnValueOnce(secondSelection.promise);
      mockedMutateFreeColors.mockReturnValueOnce(freeColorResponse.promise);
      const first = useConverterStore.getState().applySelectionMutation({ operation: "point-toggle", x: 5, y: 5 });
      await vi.waitFor(() => expect(mockedMutate).toHaveBeenCalledOnce());
      if (action === "toggle") useConverterStore.getState().toggleFreeColor("aabbcc");
      else useConverterStore.getState().clearFreeColors();
      const second = useConverterStore.getState().applySelectionMutation({ operation: "point-toggle", x: 15, y: 5 });
      firstSelection.resolve(document(1));
      await vi.waitFor(() => expect(mockedMutateFreeColors).toHaveBeenCalledOnce());
      const selectionsBeforeFreeColorConfirmation = mockedMutate.mock.calls.length;
      freeColorResponse.resolve({
        status: "ok", free_color_set: action === "toggle" ? ["aabbcc"] : [],
        can_undo: true, can_redo: false, editor_content_revision: 2,
      });
      secondSelection.resolve(document(2));
      await Promise.all([first, second]);
      expect(selectionsBeforeFreeColorConfirmation).toBe(1);
      expect(mockedMutate).toHaveBeenCalledTimes(2);
    },
  );

  it("keeps the draft and blocks dependent edits when the operation receipt is unknown", async () => {
    const sessionId = "unknown-replacement-response";
    useConverterStore.setState({
      sessionId,
      selectionDocument: document(1, 1),
      colorRemapMap: { aabbcc: "ffffff" },
      palette: [
        {
          quantized_hex: "aabbcc",
          matched_hex: "aabbcc",
          pixel_count: 10,
          percentage: 1,
        },
      ],
    });
    mockedReplaceColorsBatch.mockRejectedValueOnce(new Error("response lost"));
    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "pending",
      operation_id: "replace-op-unknown",
      editor_content_revision: 1,
      selection_revision: 1,
    });

    await useConverterStore.getState().submitReplacePreview();

    expect(useConverterStore.getState().colorRemapMap).toEqual({
      aabbcc: "ffffff",
    });
    expect(useConverterStore.getState().contentCommitStatus).toBe("unknown");

    mockedMutate.mockResolvedValueOnce(document(2, 7));
    const selectionRequest = useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle",
      x: 5,
      y: 5,
    });
    await Promise.resolve();
    await Promise.resolve();
    expect(mockedMutate).not.toHaveBeenCalled();

    // The explicit sync action must reconcile the same operation even if an
    // unrelated preview epoch made its original response stale.
    useConverterStore.setState((state) => ({
      previewRequestRevision: state.previewRequestRevision + 1,
    }));
    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "committed",
      operation_id: "replace-op-unknown",
      editor_content_revision: 7,
      selection_revision: 1,
    });
    mockedGet.mockResolvedValueOnce(document(1, 7));
    await useConverterStore.getState().reconcileUnknownContentCommit();
    await selectionRequest;

    expect(mockedMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        session_id: sessionId,
        content_revision: 7,
      }),
    );
    expect(useConverterStore.getState().contentCommitStatus).toBe("committed");
  });

  it("waits for an unconfirmed selection before a selection-scoped replace", async () => {
    const sessionId = "selection-before-replace";
    const selectionCommit = deferred<SelectionDocumentResponse>();
    useConverterStore.setState({
      sessionId,
      selectionDocument: document(1, 1),
      pendingReplacement: {
        sourceHex: "aabbcc",
        targetHex: "ff0000",
        mode: "multi-select",
      },
    });
    mockedMutate.mockReturnValueOnce(selectionCommit.promise);
    mockedRegionReplace.mockResolvedValueOnce({
      preview_url: "/api/files/selection-replaced.png",
      message: "ok",
      selection: document(3, 2),
    } as never);

    const selectionRequest = useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle",
      x: 5,
      y: 5,
    });
    const replacementRequest = useConverterStore.getState().confirmReplacement();

    await Promise.resolve();
    await Promise.resolve();
    expect(mockedRegionReplace).not.toHaveBeenCalled();

    selectionCommit.resolve(document(2, 1));
    await selectionRequest;
    await replacementRequest;

    expect(mockedRegionReplace).toHaveBeenCalledWith(
      sessionId,
      "#ff0000",
      undefined,
      2,
      expect.any(String),
    );
  });

  it("makes a selection mutation wait for an in-flight content commit", async () => {
    const sessionId = "content-before-selection";
    const replacementCommit = deferred<unknown>();
    useConverterStore.setState({
      sessionId,
      selectionDocument: document(1, 1),
      selectedColors: new Set(["aabbcc"]),
      selectedColor: "aabbcc",
      palette: [
        {
          quantized_hex: "aabbcc",
          matched_hex: "aabbcc",
          pixel_count: 10,
          percentage: 1,
        },
      ],
    });
    mockedReplaceColorsBatch.mockReturnValueOnce(replacementCommit.promise as never);
    mockedMutate.mockResolvedValueOnce(document(2, 2));

    const replacementRequest = useConverterStore
      .getState()
      .applyBatchColorRemap("ff0000");
    const selectionRequest = useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle",
      x: 5,
      y: 5,
    });

    await Promise.resolve();
    await Promise.resolve();
    expect(mockedMutate).not.toHaveBeenCalled();

    replacementCommit.resolve({
      status: "ok",
      message: "ok",
      preview_url: "/api/files/replaced.png",
      replacement_count: 1,
      selection: document(1, 2),
    });
    await replacementRequest;
    await selectionRequest;

    expect(mockedMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        session_id: sessionId,
        base_selection_revision: 1,
        content_revision: 2,
      }),
    );
  });

  it("reconciles a lost selection response before the next queued gesture", async () => {
    useConverterStore.setState({ selectionDocument: document(1, 4) });
    const hydration = deferred<SelectionDocumentResponse>();
    mockedMutate.mockRejectedValueOnce(new Error("response lost"));
    mockedGet.mockReturnValueOnce(hydration.promise);
    const failed = useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle", x: 6, y: 6,
    });
    const clear = useConverterStore.getState().clearSelection();
    await vi.waitFor(() => expect(mockedGet).toHaveBeenCalledOnce());
    expect(mockedMutate).toHaveBeenCalledTimes(1);
    mockedMutate.mockResolvedValueOnce({ ...document(0, 4), selection_revision: 3 });
    hydration.resolve(document(2, 4));
    await Promise.all([failed, clear]);
    expect(mockedMutate.mock.calls[1][0]).toMatchObject({
      operation: "clear", base_selection_revision: 2, content_revision: 4,
    });
    expect(useConverterStore.getState().selectionDocument?.selected_pixel_count).toBe(0);
  });

  it("keeps selection mutation queues isolated per session", async () => {
    const first = deferred<SelectionDocumentResponse>();
    mockedMutate.mockImplementation((request) => {
      if (request.session_id === "parallel-session-a") {
        return first.promise;
      }
      return Promise.resolve(document(1, 2));
    });

    useConverterStore.setState({
      sessionId: "parallel-session-a",
      selectionDocument: null,
    });
    const firstRequest = useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle",
      x: 1,
      y: 1,
    });

    useConverterStore.setState({
      sessionId: "parallel-session-b",
      selectionDocument: null,
    });
    const secondRequest = useConverterStore.getState().applySelectionMutation({
      operation: "point-toggle",
      x: 2,
      y: 2,
    });
    await vi.waitFor(() => expect(
      mockedMutate.mock.calls.some(
        ([request]) => request.session_id === "parallel-session-b",
      ),
    ).toBe(true));

    first.resolve(document(1, 1));
    await Promise.all([firstRequest, secondRequest]);
  });
});
