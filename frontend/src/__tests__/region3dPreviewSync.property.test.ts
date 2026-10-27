import { describe, it, expect, vi, beforeEach } from "vitest";
import * as fc from "fast-check";

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
  detectRegion: vi.fn(),
  regionReplace: vi.fn(),
  resetReplacements: vi.fn(),
}));

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

import { useConverterStore } from "../stores/converter";
import type { RegionData } from "../stores/converter";
import type { RegionDetectResponse, RegionReplaceResponse } from "../api/types";

const glbUrlPath = fc
  .stringMatching(/^[a-z0-9]{6,12}$/)
  .map((id) => `/api/files/${id}`);

const optionalGlbUrl: fc.Arbitrary<string | null> = fc.oneof(
  fc.constant(null),
  glbUrlPath,
);

const hexColor = fc
  .stringMatching(/^[0-9a-f]{6}$/)
  .filter((s) => s.length === 6);

const contourPolygon = fc.array(
  fc
    .tuple(
      fc.float({ min: 0, max: 100, noNaN: true }),
      fc.float({ min: 0, max: 100, noNaN: true }),
    )
    .map(([x, y]) => [x, y]),
  { minLength: 3, maxLength: 8 },
);

const colorContoursData: fc.Arbitrary<Record<string, number[][][]>> = fc.dictionary(
  hexColor.map((h) => `#${h}`),
  fc.array(contourPolygon, { minLength: 1, maxLength: 3 }),
  { minKeys: 1, maxKeys: 4 },
);

const optionalColorContours: fc.Arbitrary<Record<string, number[][][]> | null> =
  fc.oneof(fc.constant(null), colorContoursData);

const regionReplaceResponse: fc.Arbitrary<RegionReplaceResponse> = fc.record({
  preview_url: fc.constant("/api/files/preview-mock"),
  preview_glb_url: optionalGlbUrl,
  color_contours: optionalColorContours,
  message: fc.constant("Region color replaced successfully"),
});

const existingGlbUrl = glbUrlPath;

const existingContours: fc.Arbitrary<Record<string, number[][][]>> = fc.dictionary(
  hexColor.map((h) => `#${h}`),
  fc.array(contourPolygon, { minLength: 1, maxLength: 2 }),
  { minKeys: 1, maxKeys: 3 },
);

function resetStore(overrides?: Partial<ReturnType<typeof useConverterStore.getState>>) {
  useConverterStore.setState({
    sessionId: "test-session",
    regionData: {
      regionId: "r1",
      colorHex: "#ff0000",
      pixelCount: 100,
      previewUrl: "/mock",
    },
    replacePreviewLoading: false,
    error: null,
    previewImageUrl: null,
    previewBaseImageUrl: null,
    previewGlbUrl: null,
    colorContours: {},
    threemfDiskPath: null,
    downloadUrl: null,
    ...overrides,
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("region 3d preview sync", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  it("keeps the base preview and stores contours when detectAndAccumulateRegion uses the fast click path", async () => {
    const { detectRegion } = await import("../api/converter");

    resetStore({
      selectionMode: "multi-select",
      originalPreviewUrl: "/api/files/original-preview",
      previewBaseImageUrl: "/api/files/original-preview",
      previewImageUrl: "/api/files/original-preview",
      selectedRegions: [],
      selectedColor: null,
    });

    const response: RegionDetectResponse = {
      region_id: "region-2",
      color_hex: "#00ff00",
      pixel_count: 42,
      preview_url: null,
      contours: [
        [
          [0, 0],
          [1, 0],
          [1, 1],
        ],
      ],
    };
    (detectRegion as ReturnType<typeof vi.fn>).mockResolvedValue(response);

    await useConverterStore.getState().detectAndAccumulateRegion(12, 34);

    const state = useConverterStore.getState();
    expect(detectRegion).toHaveBeenCalledWith("test-session", 12, 34);
    expect(state.previewImageUrl).toBe("/api/files/original-preview");
    expect(state.previewBaseImageUrl).toBe("/api/files/original-preview");
    expect(state.selectedColor).toBe("00ff00");
    expect(state.selectedRegions).toEqual([
      expect.objectContaining({
        regionId: "region-2",
        colorHex: "#00ff00",
        pixelCount: 42,
        previewUrl: "/api/files/original-preview",
        contours: response.contours,
        clickX: 12,
        clickY: 34,
      }),
    ]);
  });

  it("keeps the base preview when detectRegion uses the fast click path in single-region mode", async () => {
    const { detectRegion } = await import("../api/converter");

    resetStore({
      selectionMode: "current",
      originalPreviewUrl: "/api/files/original-preview",
      previewBaseImageUrl: "/api/files/original-preview",
      previewImageUrl: "/api/files/original-preview",
      regionData: null,
      selectedColor: null,
    });

    const response: RegionDetectResponse = {
      region_id: "region-single",
      color_hex: "#ff00ff",
      pixel_count: 7,
      preview_url: null,
      contours: [
        [
          [0, 0],
          [2, 0],
          [2, 2],
        ],
      ],
    };
    (detectRegion as ReturnType<typeof vi.fn>).mockResolvedValue(response);

    await useConverterStore.getState().detectRegion(5, 6);

    const state = useConverterStore.getState();
    expect(detectRegion).toHaveBeenCalledWith("test-session", 5, 6);
    expect(state.previewImageUrl).toBe("/api/files/original-preview");
    expect(state.regionData).toEqual(
      expect.objectContaining({
        regionId: "region-single",
        previewUrl: "/api/files/original-preview",
        contours: response.contours,
        clickX: 5,
        clickY: 6,
      }),
    );
    expect(state.selectedColor).toBe("ff00ff");
  });

  it("does not invent a misleading one-pixel contour when region-detect returns no contours", async () => {
    const { detectRegion } = await import("../api/converter");

    resetStore({
      selectionMode: "current",
      originalPreviewUrl: "/api/files/original-preview",
      previewBaseImageUrl: "/api/files/original-preview",
      previewImageUrl: "/api/files/original-preview",
      previewPixelWidth: 100,
      previewPixelHeight: 50,
      preview_width_mm: 200,
      regionData: null,
      selectedColor: null,
    });

    const response: RegionDetectResponse = {
      region_id: "region-single-pixel",
      color_hex: "#112233",
      pixel_count: 1,
      preview_url: null,
      contours: [],
    };
    (detectRegion as ReturnType<typeof vi.fn>).mockResolvedValue(response);

    await useConverterStore.getState().detectRegion(5, 6);

    const state = useConverterStore.getState();
    expect(state.regionData?.contours).toBeNull();
  });

  it("keeps both multi-select regions when consecutive clicks resolve out of order", async () => {
    const { detectRegion } = await import("../api/converter");
    const first = deferred<RegionDetectResponse>();
    const second = deferred<RegionDetectResponse>();
    (detectRegion as ReturnType<typeof vi.fn>)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    resetStore({
      selectionMode: "multi-select",
      originalPreviewUrl: "/api/files/original-preview",
      previewBaseImageUrl: "/api/files/original-preview",
      previewImageUrl: "/api/files/original-preview",
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      preview_width_mm: 100,
      selectedRegions: [],
      selectedColor: null,
    });

    const firstClick = useConverterStore.getState().detectAndAccumulateRegion(10, 10);
    const secondClick = useConverterStore.getState().detectAndAccumulateRegion(20, 20);

    second.resolve({
      region_id: "region-second",
      color_hex: "#00ff00",
      pixel_count: 8,
      preview_url: null,
      contours: [
        [
          [20, 80],
          [21, 80],
          [21, 79],
        ],
      ],
    });
    await Promise.resolve();

    first.resolve({
      region_id: "region-first",
      color_hex: "#ff0000",
      pixel_count: 6,
      preview_url: null,
      contours: [
        [
          [10, 90],
          [11, 90],
          [11, 89],
        ],
      ],
    });

    await Promise.all([firstClick, secondClick]);

    const state = useConverterStore.getState();
    expect(state.selectedRegions.map((region) => region.regionId).sort()).toEqual([
      "region-first",
      "region-second",
    ]);
    expect(state.selectedRegions.every((region) => region.contours?.length)).toBe(
      true,
    );
  });

  it("keeps a single-select region when duplicate detect responses resolve for one click", async () => {
    const { detectRegion } = await import("../api/converter");
    const first = deferred<RegionDetectResponse>();
    const duplicate = deferred<RegionDetectResponse>();
    (detectRegion as ReturnType<typeof vi.fn>)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(duplicate.promise);

    resetStore({
      selectionMode: "current",
      originalPreviewUrl: "/api/files/original-preview",
      previewBaseImageUrl: "/api/files/original-preview",
      previewImageUrl: "/api/files/original-preview",
      regionData: null,
      selectedColor: null,
    });

    const firstClick = useConverterStore.getState().detectRegion(10, 10);
    const duplicateClick = useConverterStore.getState().detectRegion(10, 10);

    const response: RegionDetectResponse = {
      region_id: "region-dup",
      color_hex: "#ff0000",
      pixel_count: 6,
      preview_url: null,
      contours: [
        [
          [10, 90],
          [11, 90],
          [11, 89],
        ],
      ],
    };
    first.resolve(response);
    await Promise.resolve();
    duplicate.resolve(response);

    await Promise.all([firstClick, duplicateClick]);

    const state = useConverterStore.getState();
    expect(state.regionData?.regionId).toBe("region-dup");
    expect(state.selectedColor).toBe("ff0000");
  });

  it("ignores stale single-select responses after a newer different click wins", async () => {
    const { detectRegion } = await import("../api/converter");
    const first = deferred<RegionDetectResponse>();
    const second = deferred<RegionDetectResponse>();
    (detectRegion as ReturnType<typeof vi.fn>)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    resetStore({
      selectionMode: "current",
      originalPreviewUrl: "/api/files/original-preview",
      previewBaseImageUrl: "/api/files/original-preview",
      previewImageUrl: "/api/files/original-preview",
      regionData: null,
      selectedColor: null,
    });

    const firstClick = useConverterStore.getState().detectRegion(10, 10);
    const secondClick = useConverterStore.getState().detectRegion(20, 20);

    second.resolve({
      region_id: "region-second",
      color_hex: "#00ff00",
      pixel_count: 8,
      preview_url: null,
      contours: [
        [
          [20, 80],
          [21, 80],
          [21, 79],
        ],
      ],
    });
    await Promise.resolve();

    first.resolve({
      region_id: "region-first",
      color_hex: "#ff0000",
      pixel_count: 6,
      preview_url: null,
      contours: [
        [
          [10, 90],
          [11, 90],
          [11, 89],
        ],
      ],
    });

    await Promise.all([firstClick, secondClick]);

    const state = useConverterStore.getState();
    expect(state.regionData?.regionId).toBe("region-second");
    expect(state.selectedColor).toBe("00ff00");
  });

  it("ignores duplicate multi-select detect responses that were not selected when requested", async () => {
    const { detectRegion } = await import("../api/converter");
    const first = deferred<RegionDetectResponse>();
    const duplicate = deferred<RegionDetectResponse>();
    (detectRegion as ReturnType<typeof vi.fn>)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(duplicate.promise);

    resetStore({
      selectionMode: "multi-select",
      originalPreviewUrl: "/api/files/original-preview",
      previewBaseImageUrl: "/api/files/original-preview",
      previewImageUrl: "/api/files/original-preview",
      selectedRegions: [],
      selectedColor: null,
    });

    const firstClick = useConverterStore.getState().detectAndAccumulateRegion(10, 10);
    const duplicateClick = useConverterStore.getState().detectAndAccumulateRegion(10, 10);

    const response: RegionDetectResponse = {
      region_id: "region-dup",
      color_hex: "#ff0000",
      pixel_count: 6,
      preview_url: null,
      contours: [
        [
          [10, 90],
          [11, 90],
          [11, 89],
        ],
      ],
    };
    first.resolve(response);
    await Promise.resolve();
    duplicate.resolve(response);

    await Promise.all([firstClick, duplicateClick]);

    const state = useConverterStore.getState();
    expect(state.selectedRegions.map((region) => region.regionId)).toEqual([
      "region-dup",
    ]);
    expect(state.selectedColor).toBe("ff0000");
  });

  it("does not resurrect a multi-select region after the user clears while detection is pending", async () => {
    const { detectRegion } = await import("../api/converter");
    const pending = deferred<RegionDetectResponse>();
    (detectRegion as ReturnType<typeof vi.fn>).mockReturnValueOnce(pending.promise);

    resetStore({
      selectionMode: "multi-select",
      originalPreviewUrl: "/api/files/original-preview",
      previewBaseImageUrl: "/api/files/original-preview",
      previewImageUrl: "/api/files/original-preview",
      selectedRegions: [],
      selectedColor: null,
    });

    const click = useConverterStore.getState().detectAndAccumulateRegion(10, 10);
    useConverterStore.getState().clearSelection();

    pending.resolve({
      region_id: "region-late",
      color_hex: "#ff0000",
      pixel_count: 6,
      preview_url: null,
      contours: [
        [
          [10, 90],
          [11, 90],
          [11, 89],
        ],
      ],
    });

    await click;

    const state = useConverterStore.getState();
    expect(state.selectedRegions).toEqual([]);
    expect(state.selectedColor).toBeNull();
  });

  it("keeps a new multi-select click after clearing an older pending click", async () => {
    const { detectRegion } = await import("../api/converter");
    const oldPending = deferred<RegionDetectResponse>();
    const newPending = deferred<RegionDetectResponse>();
    (detectRegion as ReturnType<typeof vi.fn>)
      .mockReturnValueOnce(oldPending.promise)
      .mockReturnValueOnce(newPending.promise);

    resetStore({
      selectionMode: "multi-select",
      originalPreviewUrl: "/api/files/original-preview",
      previewBaseImageUrl: "/api/files/original-preview",
      previewImageUrl: "/api/files/original-preview",
      selectedRegions: [],
      selectedColor: null,
    });

    const oldClick = useConverterStore.getState().detectAndAccumulateRegion(10, 10);
    useConverterStore.getState().clearSelection();
    const newClick = useConverterStore.getState().detectAndAccumulateRegion(20, 20);

    oldPending.resolve({
      region_id: "region-old",
      color_hex: "#ff0000",
      pixel_count: 6,
      preview_url: null,
      contours: [
        [
          [10, 90],
          [11, 90],
          [11, 89],
        ],
      ],
    });
    await oldClick;
    expect(useConverterStore.getState().selectedRegions).toEqual([]);

    newPending.resolve({
      region_id: "region-new",
      color_hex: "#00ff00",
      pixel_count: 8,
      preview_url: null,
      contours: [
        [
          [20, 80],
          [21, 80],
          [21, 79],
        ],
      ],
    });

    await newClick;

    const state = useConverterStore.getState();
    expect(state.selectedRegions.map((region) => region.regionId)).toEqual([
      "region-new",
    ]);
    expect(state.selectedColor).toBe("00ff00");
  });

  it("keeps a new single-select click after clearing an older pending click", async () => {
    const { detectRegion } = await import("../api/converter");
    const oldPending = deferred<RegionDetectResponse>();
    const newPending = deferred<RegionDetectResponse>();
    (detectRegion as ReturnType<typeof vi.fn>)
      .mockReturnValueOnce(oldPending.promise)
      .mockReturnValueOnce(newPending.promise);

    resetStore({
      selectionMode: "current",
      originalPreviewUrl: "/api/files/original-preview",
      previewBaseImageUrl: "/api/files/original-preview",
      previewImageUrl: "/api/files/original-preview",
      regionData: null,
      selectedColor: null,
    });

    const oldClick = useConverterStore.getState().detectRegion(10, 10);
    useConverterStore.getState().clearSelection();
    const newClick = useConverterStore.getState().detectRegion(20, 20);

    oldPending.resolve({
      region_id: "region-old",
      color_hex: "#ff0000",
      pixel_count: 6,
      preview_url: null,
      contours: [
        [
          [10, 90],
          [11, 90],
          [11, 89],
        ],
      ],
    });
    await oldClick;
    expect(useConverterStore.getState().regionData).toBeNull();

    newPending.resolve({
      region_id: "region-new",
      color_hex: "#00ff00",
      pixel_count: 8,
      preview_url: null,
      contours: [
        [
          [20, 80],
          [21, 80],
          [21, 79],
        ],
      ],
    });

    await newClick;

    const state = useConverterStore.getState();
    expect(state.regionData?.regionId).toBe("region-new");
    expect(state.selectedColor).toBe("00ff00");
  });

  it("falls back to the latest remaining region highlight when removing multi-select regions", () => {
    const regionA: RegionData = {
      regionId: "region-a",
      colorHex: "#ff0000",
      pixelCount: 10,
      previewUrl: "/api/files/highlight-region-a",
      clickX: 1,
      clickY: 2,
    };
    const regionB: RegionData = {
      regionId: "region-b",
      colorHex: "#00ff00",
      pixelCount: 20,
      previewUrl: "/api/files/highlight-region-b",
      clickX: 3,
      clickY: 4,
    };

    resetStore({
      selectionMode: "multi-select",
      originalPreviewUrl: "/api/files/original-preview",
      previewBaseImageUrl: "/api/files/original-preview",
      previewImageUrl: "/api/files/original-preview",
      selectedRegions: [regionA, regionB],
      selectedColor: "00ff00",
    });

    useConverterStore.getState().removeRegionFromSelection("region-b");

    let state = useConverterStore.getState();
    expect(state.selectedRegions).toEqual([regionA]);
    expect(state.selectedColor).toBe("ff0000");
    expect(state.previewImageUrl).toBe(regionA.previewUrl);

    useConverterStore.getState().removeRegionFromSelection("region-a");

    state = useConverterStore.getState();
    expect(state.selectedRegions).toEqual([]);
    expect(state.selectedColor).toBeNull();
    expect(state.previewImageUrl).toBe("/api/files/original-preview");
  });

  it("updates previewBaseImageUrl together with previewImageUrl after applyRegionReplace", async () => {
    const { regionReplace } = await import("../api/converter");

    resetStore({
      previewImageUrl: "/api/files/preview-before-replace",
      previewBaseImageUrl: "/api/files/preview-before-replace",
    });

    const response: RegionReplaceResponse = {
      preview_url: "/api/files/preview-after-replace",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    };
    (regionReplace as ReturnType<typeof vi.fn>).mockResolvedValue(response);

    await useConverterStore.getState().applyRegionReplace("abcdef");

    const state = useConverterStore.getState();
    expect(state.previewImageUrl).toBe("/api/files/preview-after-replace");
    expect(state.previewBaseImageUrl).toBe("/api/files/preview-after-replace");
  });

  it("updates previewGlbUrl and colorContours only when response fields are non-null", async () => {
    const { regionReplace } = await import("../api/converter");

    await fc.assert(
      fc.asyncProperty(
        regionReplaceResponse,
        existingGlbUrl,
        existingContours,
        async (response, prevGlbUrl, prevContours) => {
          resetStore({ previewGlbUrl: prevGlbUrl, colorContours: prevContours });
          (regionReplace as ReturnType<typeof vi.fn>).mockResolvedValue(response);

          await useConverterStore.getState().applyRegionReplace("ff0000");
          const state = useConverterStore.getState();

          if (response.preview_glb_url) {
            expect(state.previewGlbUrl).toBe(response.preview_glb_url);
          } else {
            expect(state.previewGlbUrl).toBe(prevGlbUrl);
          }

          if (response.color_contours) {
            expect(state.colorContours).toEqual(response.color_contours);
          } else {
            expect(state.colorContours).toEqual(prevContours);
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  it("sets previewGlbUrl to response.preview_glb_url when present", async () => {
    const { regionReplace } = await import("../api/converter");

    await fc.assert(
      fc.asyncProperty(glbUrlPath, async (glbPath) => {
        resetStore({ previewGlbUrl: null });

        const response: RegionReplaceResponse = {
          preview_url: "/api/files/preview-mock",
          preview_glb_url: glbPath,
          color_contours: null,
          message: "ok",
        };
        (regionReplace as ReturnType<typeof vi.fn>).mockResolvedValue(response);

        await useConverterStore.getState().applyRegionReplace("aabbcc");
        expect(useConverterStore.getState().previewGlbUrl).toBe(glbPath);
      }),
      { numRuns: 100 },
    );
  });

  it("preserves existing previewGlbUrl when response.preview_glb_url is null", async () => {
    const { regionReplace } = await import("../api/converter");
    const existingUrl = "/api/files/existing-glb-123";
    resetStore({ previewGlbUrl: existingUrl });

    const response: RegionReplaceResponse = {
      preview_url: "/api/files/preview-after-replace",
      preview_glb_url: null,
      color_contours: null,
      message: "Region color replaced successfully",
    };
    (regionReplace as ReturnType<typeof vi.fn>).mockResolvedValue(response);

    await useConverterStore.getState().applyRegionReplace("00ff00");

    const state = useConverterStore.getState();
    expect(state.previewGlbUrl).toBe(existingUrl);
    expect(state.previewImageUrl).toBe("/api/files/preview-after-replace");
  });

  it("preserves existing colorContours when response.color_contours is null", async () => {
    const { regionReplace } = await import("../api/converter");

    const existing = {
      "#ff0000": [[[0, 0], [10, 0], [10, 10]]],
      "#00ff00": [[[5, 5], [15, 5], [15, 15]]],
    };
    resetStore({ colorContours: existing });

    const response: RegionReplaceResponse = {
      preview_url: "/api/files/preview-after-replace",
      preview_glb_url: null,
      color_contours: null,
      message: "ok",
    };
    (regionReplace as ReturnType<typeof vi.fn>).mockResolvedValue(response);

    await useConverterStore.getState().applyRegionReplace("0000ff");
    expect(useConverterStore.getState().colorContours).toEqual(existing);
  });
});
