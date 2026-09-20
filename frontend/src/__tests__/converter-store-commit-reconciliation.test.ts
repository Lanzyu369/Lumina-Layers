import { beforeEach, describe, expect, it, vi } from "vitest";
import { useConverterStore } from "../stores/converter";
import type {
  ColorReplacementItem,
  RecipeOverrideItem,
  SelectionDocumentResponse,
} from "../api/types";

vi.mock("../api/converter", async () => {
  const actual =
    await vi.importActual<typeof import("../api/converter")>(
      "../api/converter",
    );
  return {
    ...actual,
    resetReplacements: vi.fn(),
    applyRecipeOverride: vi.fn(),
    replacementHistory: vi.fn(),
    convertGenerate: vi.fn(),
    getEditorSelection: vi.fn(),
    getEditorCommitStatus: vi.fn(),
  };
});

import {
  applyRecipeOverride,
  convertGenerate,
  getEditorCommitStatus,
  getEditorSelection,
  replacementHistory,
  resetReplacements,
} from "../api/converter";

const mockedResetReplacements = vi.mocked(resetReplacements);
const mockedApplyRecipeOverride = vi.mocked(applyRecipeOverride);
const mockedReplacementHistory = vi.mocked(replacementHistory);
const mockedConvertGenerate = vi.mocked(convertGenerate);
const mockedGetEditorCommitStatus = vi.mocked(getEditorCommitStatus);
const mockedGetEditorSelection = vi.mocked(getEditorSelection);

let sessionCounter = 0;

function document(revision: number, contentRevision = 1): SelectionDocumentResponse {
  return {
    selection_revision: revision,
    content_revision: contentRevision,
    selected_pixel_count: 0,
    selected_component_count: 0,
    selected_color_hexes: [],
    region_ids: [],
    components: [],
    contours: [],
    can_undo: true,
    can_redo: false,
    editor_content_revision: contentRevision,
  };
}

const previousReplacement: ColorReplacementItem = {
  quantized_hex: "#ff0000",
  matched_hex: "#ff0000",
  replacement_hex: "#00ff00",
};

const previousRecipe: RecipeOverrideItem = {
  region_id: "region-a",
  recipe: [1, 1, 1],
  layer_order: "Top2Bottom",
};

function seedEditorState(overrides: Record<string, unknown> = {}) {
  sessionCounter += 1;
  useConverterStore.setState({
    sessionId: `commit-reconciliation-${sessionCounter}`,
    selectionDocument: document(1, 1),
    previewRequestRevision: 1,
    previewImageUrl: "/api/files/preview-before.png",
    previewBaseImageUrl: "/api/files/preview-before.png",
    originalPreviewUrl: "/api/files/preview-before.png",
    previewGlbUrl: "/api/files/preview-before.glb",
    colorRemapMap: { ff0000: "00ff00" },
    replacement_regions: [previousReplacement],
    recipe_overrides: [previousRecipe],
    regionReplacementCount: 2,
    free_color_set: new Set(["abcdef"]),
    remapHistory: [{ ff0000: "0000ff" }],
    remapRedoHistory: [],
    adjustmentHistory: [],
    adjustmentRedoHistory: [],
    layerImages: [
      { layer_index: 0, name: "L0", url: "/api/files/layer-before.png" },
    ],
    layerImagesSourceKey: "before",
    historyCanUndo: true,
    historyCanRedo: false,
    historyBusy: false,
    replacePreviewLoading: false,
    contentCommitStatus: "idle",
    contentCommitOperationId: null,
    error: null,
    source_version: "legacy",
    lut_name: "test-lut",
    ...overrides,
  } as never);
  return `commit-reconciliation-${sessionCounter}`;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("editor commit receipt business-state reconciliation", () => {
  it("restores the clear snapshot when a later receipt confirms failure", async () => {
    const sessionId = seedEditorState();
    mockedResetReplacements.mockRejectedValueOnce(new Error("response lost"));
    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "pending",
      operation_id: "clear-operation",
      editor_content_revision: 1,
      visible_content_revision: 1,
    });

    await useConverterStore.getState().clearAllRemaps();
    await vi.waitFor(() => {
      expect(mockedGetEditorCommitStatus).toHaveBeenCalledWith(
        sessionId,
        expect.any(String),
      );
    });

    expect(useConverterStore.getState().contentCommitStatus).toBe("unknown");
    expect(useConverterStore.getState().colorRemapMap).toEqual({});

    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "failed",
      operation_id: "clear-operation",
      editor_content_revision: 1,
      visible_content_revision: 1,
    });
    await useConverterStore.getState().reconcileUnknownContentCommit();

    const state = useConverterStore.getState();
    expect(state.contentCommitStatus).toBe("failed");
    expect(state.colorRemapMap).toEqual({ ff0000: "00ff00" });
    expect(state.replacement_regions).toEqual([previousReplacement]);
    expect(state.recipe_overrides).toEqual([previousRecipe]);
    expect(state.previewBaseImageUrl).toBe("/api/files/preview-before.png");
    expect(state.previewGlbUrl).toBe("/api/files/preview-before.glb");
  });

  it("applies a committed recipe result when the HTTP response is lost", async () => {
    seedEditorState({ recipe_overrides: [] });
    mockedApplyRecipeOverride.mockRejectedValueOnce(new Error("response lost"));
    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "committed",
      operation_id: "recipe-operation",
      editor_content_revision: 4,
      visible_content_revision: 4,
      selection_revision: 1,
      result: {
        preview_url: "/api/files/recipe-committed.png",
        preview_glb_url: "/api/files/recipe-committed.glb",
        recipe_overrides: [
          {
            region_id: "region-a",
            recipe: [3, 3, 3],
            layer_order: "Top2Bottom",
          },
        ],
        recipe_override_count: 1,
        region_replacement_count: 2,
        can_undo: true,
        can_redo: false,
      },
    } as never);
    mockedGetEditorSelection.mockResolvedValueOnce(document(1, 4));

    await useConverterStore
      .getState()
      .applyCustomRecipeOverride(["region-a"], [3, 3, 3]);

    const state = useConverterStore.getState();
    expect(state.contentCommitStatus).toBe("committed");
    expect(state.recipe_overrides).toEqual([
      {
        region_id: "region-a",
        recipe: [3, 3, 3],
        layer_order: "Top2Bottom",
      },
    ]);
    expect(state.previewBaseImageUrl).toBe("/api/files/recipe-committed.png");
    expect(state.previewGlbUrl).toBe("/api/files/recipe-committed.glb");
  });

  it("restores the recipe history snapshot when a delayed receipt confirms failure", async () => {
    seedEditorState({ recipe_overrides: [] });
    const beforeHistory = useConverterStore.getState().adjustmentHistory;
    mockedApplyRecipeOverride.mockRejectedValueOnce(new Error("response lost"));
    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "pending",
      operation_id: "recipe-failed-operation",
      editor_content_revision: 1,
      visible_content_revision: 1,
    });

    await useConverterStore
      .getState()
      .applyCustomRecipeOverride(["region-a"], [3, 3, 3]);
    expect(useConverterStore.getState().contentCommitStatus).toBe("unknown");
    expect(useConverterStore.getState().adjustmentHistory).toHaveLength(1);

    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "failed",
      operation_id: "recipe-failed-operation",
      editor_content_revision: 1,
      visible_content_revision: 1,
    });
    await useConverterStore.getState().reconcileUnknownContentCommit();

    expect(useConverterStore.getState().contentCommitStatus).toBe("failed");
    expect(useConverterStore.getState().recipe_overrides).toEqual([]);
    expect(useConverterStore.getState().adjustmentHistory).toEqual(beforeHistory);
  });

  it("uses the committed undo result when preparing generation after sync", async () => {
    const sessionId = seedEditorState();
    mockedReplacementHistory.mockRejectedValueOnce(new Error("response lost"));
    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "pending",
      operation_id: "undo-operation",
      editor_content_revision: 1,
      visible_content_revision: 1,
    });

    await useConverterStore.getState().undoColorRemap();
    expect(useConverterStore.getState().contentCommitStatus).toBe("unknown");

    mockedGetEditorCommitStatus.mockResolvedValueOnce({
      status: "committed",
      operation_id: "undo-operation",
      editor_content_revision: 5,
      visible_content_revision: 5,
      selection_revision: 1,
      result: {
        preview_url: "/api/files/undo-committed.png",
        replacement_regions: [],
        recipe_overrides: [],
        recipe_override_count: 0,
        region_replacement_count: 0,
        free_color_set: [],
        can_undo: false,
        can_redo: true,
      },
    } as never);
    mockedGetEditorSelection.mockResolvedValueOnce(document(1, 5));
    await useConverterStore.getState().reconcileUnknownContentCommit();

    mockedConvertGenerate.mockResolvedValueOnce({
      status: "ok",
      message: "generated",
      download_url: "/api/files/result.3mf",
    });
    await useConverterStore.getState().submitGenerate();

    expect(mockedConvertGenerate).toHaveBeenCalledWith(
      sessionId,
      expect.objectContaining({
        replacement_regions: undefined,
        recipe_overrides: undefined,
        free_color_set: undefined,
      }),
      expect.anything(),
    );
    expect(useConverterStore.getState().replacement_regions).toEqual([]);
    expect(useConverterStore.getState().recipe_overrides).toEqual([]);
    expect(useConverterStore.getState().free_color_set).toEqual(new Set());
  });
});
