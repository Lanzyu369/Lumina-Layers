import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EditorCommitStatusResponse, PreviewResponse, SelectionDocumentResponse } from "../api/types";

vi.mock("../api/converter", async () => ({
  ...await vi.importActual<typeof import("../api/converter")>("../api/converter"),
  convertPreview: vi.fn(),
  exportEditorProject: vi.fn(),
  restoreEditorProject: vi.fn(),
  applyRecipeOverride: vi.fn(),
  getEditorSelection: vi.fn(),
  getGlbStatus: vi.fn().mockResolvedValue({ status: "idle", glb_url: null }),
  fetchGradientGroups: vi.fn().mockResolvedValue({ groups: [] }),
}));
vi.mock("../api/session", () => ({ closeSession: vi.fn().mockResolvedValue(undefined) }));

import { applyRecipeOverride, convertPreview, exportEditorProject, getEditorSelection, restoreEditorProject } from "../api/converter";
import { closeSession } from "../api/session";
import { useConverterStore } from "../stores/converter";
import { DEFAULT_STATE } from "../stores/converter/store";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

const selection: SelectionDocumentResponse = {
  selection_revision: 2, content_revision: 1, editor_content_revision: 3,
  selected_pixel_count: 2, selected_component_count: 1,
  selected_color_hexes: [], region_ids: [], components: [], contours: [],
  can_undo: false, can_redo: false,
};
const preview = {
  status: "ok", message: "preview", preview_glb_url: null, warnings: [],
  session_id: "restored-preview", preview_url: "/api/files/source.png",
  palette: [], dimensions: { width: 6, height: 4, preview_raw_url: "/api/files/source-raw.png" },
} satisfies PreviewResponse;
const restored: EditorCommitStatusResponse = {
  status: "committed", operation_id: "restored-operation", editor_content_revision: 3,
  result: { preview_url: "/api/files/edited.png", region_replacement_count: 1, recipe_overrides: [], free_color_set: [] },
};

beforeEach(() => {
  vi.clearAllMocks();
  useConverterStore.setState({ ...DEFAULT_STATE, source_version: "legacy", lut_name: "test-lut",
    imageFile: new File(["source"], "source.png"), imagePreviewUrl: "/source-upload.png" });
  vi.mocked(getEditorSelection).mockResolvedValue(selection);
  vi.mocked(convertPreview).mockResolvedValue(preview);
});
afterEach(() => vi.clearAllTimers());

describe("portable editor project orchestration", () => {
  it("captures the confirmed spatial revisions and refuses a later edit", async () => {
    useConverterStore.setState({ sessionId: "export-editor", regionReplacementCount: 1, selectionDocument: selection });
    const capture = deferred<File>();
    vi.mocked(exportEditorProject).mockReturnValue(capture.promise);
    const saving = useConverterStore.getState().prepareRecipeExport();
    await vi.waitFor(() => expect(exportEditorProject).toHaveBeenCalledWith("export-editor", 3, 2));
    useConverterStore.setState({ selectionDocument: { ...selection, selection_revision: 3 } });
    capture.resolve(new File(["checkpoint"], "editor.json.gz"));
    await expect(saving).rejects.toThrow();
  });

  it("refuses unconfirmed content rather than exporting incomplete edits", async () => {
    useConverterStore.setState({ sessionId: "unknown-editor", regionReplacementCount: 1, contentCommitStatus: "unknown" });
    await expect(useConverterStore.getState().prepareRecipeExport()).rejects.toThrow();
    expect(exportEditorProject).not.toHaveBeenCalled();
  });

  it("waits for a dialog recipe commit and saves the server-confirmed revisions", async () => {
    useConverterStore.setState({ sessionId: "recipe-editor", selectionDocument: selection,
      regionReplacementCount: 1, downloadUrl: "/api/files/previous-model.3mf", color_layers: 5 });
    const commit = deferred<Awaited<ReturnType<typeof applyRecipeOverride>>>();
    vi.mocked(applyRecipeOverride).mockReturnValue(commit.promise);
    const editing = useConverterStore.getState().commitRecipeOverride({
      session_id: "recipe-editor", region_ids: ["region:2"], recipe: [0, 1, 0],
      layer_order: "Top2Bottom", color_layers: 3, layer_height_mm: 0.08,
    });
    const saving = useConverterStore.getState().prepareRecipeExport();
    expect(exportEditorProject).not.toHaveBeenCalled();
    const committedSelection = { ...selection, editor_content_revision: 6, content_revision: 2 };
    const committedRecipes = [
      { region_id: "previous-region", recipe: [1, 1, 1], layer_order: "Top2Bottom" },
      { region_id: "region:2", recipe: [0, 1, 0], layer_order: "Top2Bottom" },
    ];
    vi.mocked(getEditorSelection).mockResolvedValue(committedSelection);
    vi.mocked(exportEditorProject).mockResolvedValue(new File(["checkpoint"], "editor.json.gz"));
    commit.resolve({ status: "ok", message: "applied", source: "model", rgb: [100, 20, 20], lab: [30, 10, 10],
      override_count: 2, recipe_overrides: committedRecipes, preview_url: "/api/files/recipe.png", selection: committedSelection, editor_content_revision: 6 });
    await editing;
    await saving;
    expect(exportEditorProject).toHaveBeenCalledWith("recipe-editor", 6, 2);
    expect(useConverterStore.getState().recipe_overrides).toEqual(committedRecipes);
    expect(useConverterStore.getState().downloadUrl).toBeNull();
    expect(useConverterStore.getState().color_layers).toBe(5);
  });

  it.each([false, true])("restores content before exposing the session, with raw preview=%s", async (withRaw) => {
    if (!withRaw) {
      vi.mocked(convertPreview).mockResolvedValue({
        ...preview, dimensions: { width: 6, height: 4 },
      });
    }
    const file = new File(["checkpoint"], "editor.json.gz");
    useConverterStore.setState({ pendingEditorProject: file });
    const restore = deferred<EditorCommitStatusResponse>();
    vi.mocked(restoreEditorProject).mockReturnValue(restore.promise);
    const previewing = useConverterStore.getState().submitPreview();
    await vi.waitFor(() => expect(restoreEditorProject).toHaveBeenCalled());
    expect(useConverterStore.getState().sessionId).toBeNull();
    expect(useConverterStore.getState().pendingEditorProject).toBe(file);
    restore.resolve(restored);
    await previewing;
    expect(useConverterStore.getState()).toMatchObject({
      sessionId: "restored-preview", pendingEditorProject: null, regionReplacementCount: 1,
      previewImageUrl: "/api/files/edited.png", previewBaseImageUrl: "/api/files/edited.png",
      originalPreviewUrl: preview.preview_url, imagePreviewUrl: "/source-upload.png",
    });
    expect(useConverterStore.getState().selectionDocument?.selected_pixel_count).toBe(2);
  });

  it.each([false, true])("keeps ordinary preview and original-image comparison, with raw preview=%s", async (withRaw) => {
    if (!withRaw) {
      vi.mocked(convertPreview).mockResolvedValue({
        ...preview, dimensions: { width: 6, height: 4 },
      });
    }
    await useConverterStore.getState().submitPreview();
    expect(restoreEditorProject).not.toHaveBeenCalled();
    expect(useConverterStore.getState()).toMatchObject({
      previewImageUrl: preview.preview_url, originalPreviewUrl: preview.preview_url,
      previewBaseImageUrl: withRaw ? preview.dimensions.preview_raw_url : preview.preview_url,
      imagePreviewUrl: "/source-upload.png",
    });
  });

  it("closes a failed fresh session and keeps the asset available for retry", async () => {
    const file = new File(["checkpoint"], "editor.json.gz");
    useConverterStore.setState({ pendingEditorProject: file });
    vi.mocked(restoreEditorProject).mockRejectedValue(new Error("invalid checkpoint"));
    await useConverterStore.getState().submitPreview();
    expect(closeSession).toHaveBeenCalledWith("restored-preview");
    expect(useConverterStore.getState()).toMatchObject({ sessionId: null, pendingEditorProject: file, error: "invalid checkpoint" });
  });

  it("discards a restored session whose source changed during import", async () => {
    useConverterStore.setState({ pendingEditorProject: new File(["checkpoint"], "editor.json.gz") });
    const restore = deferred<EditorCommitStatusResponse>();
    vi.mocked(restoreEditorProject).mockReturnValue(restore.promise);
    const previewing = useConverterStore.getState().submitPreview();
    await vi.waitFor(() => expect(restoreEditorProject).toHaveBeenCalled());
    useConverterStore.setState({ previewRequestRevision: useConverterStore.getState().previewRequestRevision + 1 });
    restore.resolve(restored);
    await previewing;
    expect(closeSession).toHaveBeenCalledWith("restored-preview");
    expect(useConverterStore.getState().sessionId).toBeNull();
  });
});
