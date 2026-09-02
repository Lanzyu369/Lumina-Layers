import { beforeEach, describe, expect, it, vi } from "vitest";
import { useConverterStore } from "../stores/converter";
import type { ConverterState } from "../stores/converter";
import type { ReplacementHistoryResponse } from "../api/types";

// The replacement undo/redo flow is server-checkpoint based since the selection
// workstation work: ``undoColorRemap`` / ``redoColorRemap`` call
// ``replacementHistory`` and rebuild state from ``buildHistoryRestoreState``.
// 选区工作站之后撤销/重做改为服务端 checkpoint 机制：``undoColorRemap`` /
// ``redoColorRemap`` 调 ``replacementHistory``，再通过 ``buildHistoryRestoreState``
// 重建状态。
vi.mock("../api/converter", () => ({
  replacementHistory: vi.fn(),
  resetReplacements: vi.fn(),
  replaceColorsBatch: vi.fn(),
  fetchLutList: vi.fn(),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  fetchBedSizes: vi.fn(),
  uploadHeightmap: vi.fn(),
  fetchLutColors: vi.fn(),
  cropImage: vi.fn(),
  convertBatch: vi.fn(),
  replaceColor: vi.fn(),
}));

import { replacementHistory } from "../api/converter";

const mockReplacementHistory = vi.mocked(replacementHistory);
const heightMap = { bee6f8: 0.48, "112233": 2.0 };

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function historyResponse(
  overrides: Partial<ReplacementHistoryResponse> = {},
): ReplacementHistoryResponse {
  return {
    status: "ok",
    action: "undo",
    message: "ok",
    preview_url: "/api/files/restored",
    preview_glb_url: null,
    can_undo: false,
    can_redo: true,
    replacement_regions: [],
    recipe_overrides: [],
    recipe_override_count: 0,
    free_color_set: [],
    entry_kind: "content",
    ...overrides,
  };
}

function seedStore(
  overrides: Partial<ConverterState> & { _pollAsyncGlb?: () => void },
): void {
  useConverterStore.setState({
    sessionId: "height-identity-session",
    color_height_map: { ...heightMap },
    colorRemapMap: {},
    remapHistory: [],
    replacement_regions: [],
    regionReplacementCount: 0,
    regionData: null,
    selectedRegions: [],
    gradientSelection: null,
    selectedGradientRegions: [],
    selectedColors: new Set<string>(),
    selectedColor: null,
    pendingReplacement: null,
    replacePreviewLoading: false,
    historyBusy: false,
    historyCanUndo: true,
    historyCanRedo: false,
    previewBaseImageUrl: "/api/files/base",
    previewImageUrl: "/api/files/base",
    _pollAsyncGlb: vi.fn(),
    error: null,
    ...overrides,
  } as Partial<ConverterState>);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockReplacementHistory.mockResolvedValue(historyResponse());
});

describe("replacement undo/redo preserves relief height identity", () => {
  it("keeps the local color_height_map after undo", async () => {
    seedStore({ color_height_map: { ...heightMap } });

    await useConverterStore.getState().undoColorRemap();

    expect(mockReplacementHistory).toHaveBeenCalledWith(
      "height-identity-session",
      "undo",
    );
    expect(useConverterStore.getState().color_height_map).toEqual(heightMap);
  });

  it("keeps the local color_height_map after redo", async () => {
    seedStore({
      color_height_map: { ...heightMap },
      historyCanUndo: false,
      historyCanRedo: true,
    });

    await useConverterStore.getState().redoColorRemap();

    expect(mockReplacementHistory).toHaveBeenCalledWith(
      "height-identity-session",
      "redo",
    );
    expect(useConverterStore.getState().color_height_map).toEqual(heightMap);
  });

  it("keeps the local color_height_map in the session-less undo flow", async () => {
    seedStore({
      sessionId: null,
      color_height_map: { ...heightMap },
      colorRemapMap: { bee6f8: "f46429" },
      remapHistory: [{ bee6f8: "445566" }],
    });

    await useConverterStore.getState().undoColorRemap();

    expect(mockReplacementHistory).not.toHaveBeenCalled();
    expect(useConverterStore.getState().color_height_map).toEqual(heightMap);
  });

  it.each([
    {
      action: "undo" as const,
      historyCanUndo: true,
      historyCanRedo: false,
    },
    {
      action: "redo" as const,
      historyCanUndo: false,
      historyCanRedo: true,
    },
  ])(
    "ignores a stale $action response after switching sessions",
    async ({ action, historyCanUndo, historyCanRedo }) => {
      const response = deferred<ReplacementHistoryResponse>();
      mockReplacementHistory.mockReturnValueOnce(response.promise);
      const pollAsyncGlb = vi.fn();
      seedStore({
        sessionId: "session-a",
        historyCanUndo,
        historyCanRedo,
        _pollAsyncGlb: pollAsyncGlb,
      });

      const request =
        action === "undo"
          ? useConverterStore.getState().undoColorRemap()
          : useConverterStore.getState().redoColorRemap();
      useConverterStore.setState({
        sessionId: "session-b",
        previewImageUrl: "/api/files/session-b",
        previewBaseImageUrl: "/api/files/session-b",
        replacement_regions: [],
        historyBusy: false,
        historyCanUndo: false,
        historyCanRedo: false,
        replacePreviewLoading: false,
      });
      response.resolve(
        historyResponse({
          action,
          preview_url: "/api/files/stale-session-a",
          can_undo: true,
          can_redo: true,
          replacement_regions: [
            {
              quantized_hex: "#112233",
              matched_hex: "#112233",
              replacement_hex: "#445566",
            },
          ],
        }),
      );

      await request;

      expect(mockReplacementHistory).toHaveBeenCalledWith("session-a", action);
      expect(useConverterStore.getState()).toMatchObject({
        sessionId: "session-b",
        previewImageUrl: "/api/files/session-b",
        previewBaseImageUrl: "/api/files/session-b",
        replacement_regions: [],
        historyBusy: false,
        historyCanUndo: false,
        historyCanRedo: false,
        replacePreviewLoading: false,
      });
      expect(pollAsyncGlb).not.toHaveBeenCalled();
    },
  );

  it.each([
    { action: "undo" as const, historyCanUndo: true, historyCanRedo: false },
    { action: "redo" as const, historyCanUndo: false, historyCanRedo: true },
  ])(
    "ignores a stale $action response after the preview revision changes",
    async ({ action, historyCanUndo, historyCanRedo }) => {
      const response = deferred<ReplacementHistoryResponse>();
      mockReplacementHistory.mockReturnValueOnce(response.promise);
      const pollAsyncGlb = vi.fn();
      seedStore({
        sessionId: "same-session",
        previewRequestRevision: 30,
        historyCanUndo,
        historyCanRedo,
        _pollAsyncGlb: pollAsyncGlb,
      });

      const request =
        action === "undo"
          ? useConverterStore.getState().undoColorRemap()
          : useConverterStore.getState().redoColorRemap();
      useConverterStore.setState({
        previewRequestRevision: 31,
        previewImageUrl: "/api/files/new-revision",
        previewBaseImageUrl: "/api/files/new-revision",
        previewGlbUrl: "/api/files/new-revision.glb",
        historyBusy: false,
        replacePreviewLoading: false,
      });
      response.resolve(
        historyResponse({
          action,
          preview_url: "/api/files/stale-revision",
          preview_glb_url: "/api/files/stale-revision.glb",
        }),
      );
      await request;

      expect(useConverterStore.getState()).toMatchObject({
        sessionId: "same-session",
        previewRequestRevision: 31,
        previewImageUrl: "/api/files/new-revision",
        previewBaseImageUrl: "/api/files/new-revision",
        previewGlbUrl: "/api/files/new-revision.glb",
        historyBusy: false,
        replacePreviewLoading: false,
      });
      expect(pollAsyncGlb).not.toHaveBeenCalled();
    },
  );
});
