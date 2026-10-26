import { describe, it, beforeEach, vi, expect } from "vitest";
import * as fc from "fast-check";
import { useConverterStore } from "../stores/converter";
import type { ConverterState } from "../stores/converter";
import type { ColorReplaceResponse } from "../api/types";

vi.mock("../api/converter", () => ({
  fetchLutList: vi.fn(),
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  fetchBedSizes: vi.fn(),
  uploadHeightmap: vi.fn(),
  fetchLutColors: vi.fn(),
  cropImage: vi.fn(),
  convertBatch: vi.fn(),
  replaceColor: vi.fn(),
  replaceColorsBatch: vi.fn(),
  getEditorCommitStatus: vi.fn().mockResolvedValue({
    status: "failed",
    operation_id: "stale-operation",
    editor_content_revision: 0,
  }),
}));

import { replaceColorsBatch } from "../api/converter";

// submitReplacePreview now routes through /replace-colors-batch (single
// round-trip with one PNG+GLB render for the whole remap) instead of the
// old per-entry /replace-color loop. The mock target matches.
// submitReplacePreview 改走批量端点，mock 跟随更新。
const mockReplaceColorsBatch = vi.mocked(replaceColorsBatch);

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

vi.stubGlobal(
  "URL",
  Object.assign(globalThis.URL ?? {}, {
    createObjectURL: vi.fn(() => "blob:mock-url"),
    revokeObjectURL: vi.fn(),
  }),
);

vi.stubGlobal(
  "Image",
  class {
    onload: (() => void) | null = null;
    set src(_: string) {
      if (this.onload) this.onload();
    }
    naturalWidth = 100;
    naturalHeight = 100;
  },
);

const DEFAULT_STATE: Partial<ConverterState> = {
  imageFile: null,
  imagePreviewUrl: null,
  aspectRatio: null,
  sessionId: null,
  lut_name: "",
  colorRemapMap: {},
  remapHistory: [],
  palette: [],
  selectedColor: null,
  replacePreviewLoading: false,
  isLoading: false,
  error: null,
  previewImageUrl: null,
  modelUrl: null,
  previewGlbUrl: null,
  replacement_regions: [],
  free_color_set: new Set(),
};

function resetStore(): void {
  useConverterStore.setState(DEFAULT_STATE);
}

const arbHexColor = fc
  .stringMatching(/^[0-9a-fA-F]{6}$/)
  .filter((s) => s.length === 6);

const arbNonEmptyRemapMap = fc
  .array(fc.tuple(arbHexColor, arbHexColor), { minLength: 1, maxLength: 5 })
  .map((pairs) => {
    const map: Record<string, string> = {};
    for (const [orig, replacement] of pairs) {
      map[orig] = replacement;
    }
    return map;
  })
  .filter((m) => Object.keys(m).length > 0);

const arbRemapMap = fc.oneof(
  fc.constant({} as Record<string, string>),
  arbNonEmptyRemapMap,
);

const arbPreviewUrlPath = fc
  .stringMatching(/^\/output\/[a-zA-Z0-9_-]{1,30}\.png$/)
  .filter((s) => s.length > 0);

beforeEach(() => {
  vi.clearAllMocks();
  resetStore();
});

describe("replace preview behavior", () => {
  it("button enable condition equals: has remaps and not loading", () => {
    fc.assert(
      fc.property(arbRemapMap, fc.boolean(), (remapMap, loading) => {
        resetStore();
        useConverterStore.setState({
          colorRemapMap: remapMap,
          replacePreviewLoading: loading,
        });

        const state = useConverterStore.getState();
        const expectedEnabled =
          Object.keys(state.colorRemapMap).length > 0 &&
          !state.replacePreviewLoading;
        const derivedEnabled = Object.keys(remapMap).length > 0 && !loading;
        expect(expectedEnabled).toBe(derivedEnabled);
      }),
      { numRuns: 100 },
    );
  });

  it("after submitReplacePreview success, previewImageUrl equals latest response preview_url", async () => {
    await fc.assert(
      fc.asyncProperty(
        arbNonEmptyRemapMap,
        arbPreviewUrlPath,
        async (remapMap, previewPath) => {
          resetStore();
          vi.clearAllMocks();

          const palette = Object.keys(remapMap).map((hex) => ({
            quantized_hex: hex,
            matched_hex: hex,
            pixel_count: 100,
            percentage: 10,
          }));

          useConverterStore.setState({
            sessionId: "test-session",
            colorRemapMap: remapMap,
            palette,
            previewImageUrl: "/output/old.png",
          });

          const mockResponse: ColorReplaceResponse = {
            status: "ok",
            message: "replaced",
            preview_url: previewPath,
            replacement_count: 1,
          };
          mockReplaceColorsBatch.mockResolvedValue(mockResponse);

          await useConverterStore.getState().submitReplacePreview();
          const state = useConverterStore.getState();

          expect(state.previewImageUrl).toBe(previewPath);
          expect(state.replacePreviewLoading).toBe(false);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("does not commit an old replacement after the preview revision changes", async () => {
    const response = deferred<ColorReplaceResponse>();
    mockReplaceColorsBatch.mockReturnValueOnce(response.promise);
    useConverterStore.setState({
      sessionId: "same-session",
      previewRequestRevision: 10,
      colorRemapMap: { aabbcc: "ddeeff" },
      palette: [
        {
          quantized_hex: "aabbcc",
          matched_hex: "aabbcc",
          pixel_count: 10,
          percentage: 100,
        },
      ],
      previewImageUrl: "/api/files/current.png",
      previewBaseImageUrl: "/api/files/current.png",
      previewGlbUrl: "/api/files/current.glb",
      replacePreviewLoading: false,
    });

    const request = useConverterStore.getState().submitReplacePreview();
    useConverterStore.setState({
      previewRequestRevision: 11,
      previewImageUrl: "/api/files/new-revision.png",
      previewBaseImageUrl: "/api/files/new-revision.png",
      previewGlbUrl: "/api/files/new-revision.glb",
      replacePreviewLoading: false,
    });
    response.resolve({
      status: "ok",
      message: "stale",
      preview_url: "/api/files/stale.png",
      preview_3d_url: "/api/files/stale.glb",
      replacement_count: 1,
    });
    await request;

    expect(useConverterStore.getState()).toMatchObject({
      previewRequestRevision: 11,
      previewImageUrl: "/api/files/new-revision.png",
      previewBaseImageUrl: "/api/files/new-revision.png",
      previewGlbUrl: "/api/files/new-revision.glb",
      replacePreviewLoading: false,
    });
  });
});
