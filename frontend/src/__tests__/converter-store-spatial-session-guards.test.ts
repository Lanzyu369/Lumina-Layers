import { beforeEach, describe, expect, it, vi } from "vitest";

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
  applyRecipeOverride: vi.fn(),
  colorHighlight: vi.fn(),
  detectRegion: vi.fn(),
  regionReplace: vi.fn(),
  regionReplaceBatch: vi.fn(),
  regionRequantize: vi.fn(),
  resetReplacements: vi.fn(),
  autoDetectColors: vi.fn(),
  fetchGradientGroups: vi.fn(),
  getGlbStatus: vi.fn().mockResolvedValue({
    session_id: "session-b",
    status: "idle",
    glb_url: null,
    job_token: null,
    error: null,
  }),
}));

import {
  regionReplace,
  regionReplaceBatch,
  regionRequantize,
} from "../api/converter";
import type { GradientGroupItem } from "../api/types";
import {
  useConverterStore,
  type ConverterState,
} from "../stores/converter";

const mockRegionReplace = vi.mocked(regionReplace);
const mockRegionReplaceBatch = vi.mocked(regionReplaceBatch);
const mockRegionRequantize = vi.mocked(regionRequantize);

const GRADIENT_GROUP: GradientGroupItem = {
  group_index: 3,
  total_pixel_count: 30,
  material_colour_count: 2,
  material_colours: [
    { hex: "#aabbcc", rgb: [170, 187, 204], pixel_count: 20 },
    { hex: "#112233", rgb: [17, 34, 51], pixel_count: 10 },
  ],
  representative_hex: "#aabbcc",
  representative_rgb: [170, 187, 204],
  boundary_pair_count: 1,
  regions: [
    {
      region_index: 1,
      pixel_count: 20,
      bbox: [0, 0, 2, 2],
      centroid: [1, 1],
      material_breakdown: [
        { hex: "#aabbcc", rgb: [170, 187, 204], pixel_count: 20 },
      ],
    },
    {
      region_index: 2,
      pixel_count: 10,
      bbox: [3, 0, 5, 2],
      centroid: [4, 1],
      material_breakdown: [
        { hex: "#112233", rgb: [17, 34, 51], pixel_count: 10 },
      ],
    },
  ],
};

const SESSION_A_REGIONS = [
  { groupIndex: 3, regionIndex: 1 },
  { groupIndex: 3, regionIndex: 2 },
];
const SESSION_B_REGIONS = [{ groupIndex: 9, regionIndex: 7 }];

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function seedSessionA(overrides: Partial<ConverterState> = {}) {
  useConverterStore.setState({
    sessionId: "session-a",
    previewImageUrl: "/api/files/session-a.png",
    previewBaseImageUrl: "/api/files/session-a.png",
    previewGlbUrl: null,
    regionReplacementCount: 3,
    replacePreviewLoading: false,
    error: null,
    gradientGroups: [GRADIENT_GROUP],
    gradientGroupsSessionId: "session-a",
    gradientSelection: {
      kind: "multi-region",
      groupIndex: 3,
      regionIndices: [1, 2],
    },
    selectedGradientRegions: SESSION_A_REGIONS,
    selectedColors: new Set(["aabbcc"]),
    selectedColor: "aabbcc",
    regionData: null,
    ...overrides,
  } as Partial<ConverterState>);
}

function switchToSessionB() {
  useConverterStore.setState({
    sessionId: "session-b",
    previewImageUrl: "/api/files/session-b.png",
    previewBaseImageUrl: "/api/files/session-b.png",
    regionReplacementCount: 0,
    replacePreviewLoading: true,
    error: "session-b-error",
    gradientSelection: {
      kind: "multi-region",
      groupIndex: 9,
      regionIndices: [7],
    },
    selectedGradientRegions: SESSION_B_REGIONS,
    selectedColors: new Set(["778899"]),
    selectedColor: "778899",
  });
}

function expectSessionBUnchanged() {
  const state = useConverterStore.getState();
  expect(state.sessionId).toBe("session-b");
  expect(state.previewImageUrl).toBe("/api/files/session-b.png");
  expect(state.previewBaseImageUrl).toBe("/api/files/session-b.png");
  expect(state.regionReplacementCount).toBe(0);
  expect(state.replacePreviewLoading).toBe(true);
  expect(state.error).toBe("session-b-error");
  expect(state.gradientSelection).toEqual({
    kind: "multi-region",
    groupIndex: 9,
    regionIndices: [7],
  });
  expect(state.selectedGradientRegions).toEqual(SESSION_B_REGIONS);
  expect(state.selectedColors).toEqual(new Set(["778899"]));
  expect(state.selectedColor).toBe("778899");
}

function staleResponse() {
  return {
    preview_url: "/api/files/stale-session-a.png",
    preview_glb_url: null,
    color_contours: null,
    message: "ok",
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  seedSessionA();
});

describe("spatial edit session guards", () => {
  it("clears the replacement loading flag when the preview session resets", () => {
    seedSessionA({ replacePreviewLoading: true });

    useConverterStore.getState().setImageFile(null);

    expect(useConverterStore.getState().sessionId).toBeNull();
    expect(useConverterStore.getState().replacePreviewLoading).toBe(false);
  });

  it("ignores a stale gradient-region replacement response", async () => {
    const response = deferred<Awaited<ReturnType<typeof regionReplace>>>();
    mockRegionReplace.mockReturnValueOnce(response.promise);

    const request = useConverterStore
      .getState()
      .applyGradientRegionPixelReplace(3, 1, "ddeeff");
    switchToSessionB();
    response.resolve(staleResponse());
    await request;

    expectSessionBUnchanged();
  });

  it("ignores a stale selected-region flatten response", async () => {
    const response = deferred<Awaited<ReturnType<typeof regionReplaceBatch>>>();
    mockRegionReplaceBatch.mockReturnValueOnce(response.promise);

    const request = useConverterStore
      .getState()
      .flattenSelectedGradientRegions();
    switchToSessionB();
    response.resolve(staleResponse());
    await request;

    expectSessionBUnchanged();
  });

  it("ignores a stale selected-region requantize response", async () => {
    const response = deferred<Awaited<ReturnType<typeof regionRequantize>>>();
    mockRegionRequantize.mockReturnValueOnce(response.promise);

    const request = useConverterStore
      .getState()
      .requantizeSelectedGradientRegions(24);
    switchToSessionB();
    response.resolve(staleResponse());
    await request;

    expectSessionBUnchanged();
  });

  it("ignores a stale multi-gradient-region replacement response", async () => {
    const response = deferred<Awaited<ReturnType<typeof regionReplaceBatch>>>();
    mockRegionReplaceBatch.mockReturnValueOnce(response.promise);

    const request = useConverterStore
      .getState()
      .applyMultiRegionPixelReplace("ddeeff");
    switchToSessionB();
    response.resolve(staleResponse());
    await request;

    expectSessionBUnchanged();
  });

  it("ignores a stale gradient-group flatten response", async () => {
    const response = deferred<Awaited<ReturnType<typeof regionReplace>>>();
    mockRegionReplace.mockReturnValueOnce(response.promise);

    const request = useConverterStore
      .getState()
      .applyGradientReplaceForGroup(3);
    switchToSessionB();
    response.resolve(staleResponse());
    await request;

    expectSessionBUnchanged();
  });
});
