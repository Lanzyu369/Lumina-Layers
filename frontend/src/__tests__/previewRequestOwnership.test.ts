import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  convertPreview: vi.fn(),
  fetchGradientGroups: vi.fn(),
  fetchSessionLutInfo: vi.fn(),
  uploadImagePreview: vi.fn(),
}));

vi.mock("../api/converter", async () => {
  const actual =
    await vi.importActual<typeof import("../api/converter")>("../api/converter");
  return {
    ...actual,
    convertPreview: mocks.convertPreview,
    fetchGradientGroups: mocks.fetchGradientGroups,
  };
});

vi.mock("../api/lut", async () => {
  const actual = await vi.importActual<typeof import("../api/lut")>("../api/lut");
  return {
    ...actual,
    fetchSessionLutInfo: mocks.fetchSessionLutInfo,
  };
});

vi.mock("../api/system", async () => {
  const actual =
    await vi.importActual<typeof import("../api/system")>("../api/system");
  return {
    ...actual,
    uploadImagePreview: mocks.uploadImagePreview,
  };
});

function deferredPreview() {
  let resolve!: (value: {
    session_id: string;
    status: string;
    message: string;
    preview_url: string;
    preview_glb_url: string;
    palette: never[];
    dimensions: { width: number; height: number };
    warnings: never[];
  }) => void;
  const promise = new Promise<Parameters<typeof resolve>[0]>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("preview request ownership across image changes", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:next-image"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
    mocks.fetchGradientGroups.mockResolvedValue({ groups: [] });
    mocks.fetchSessionLutInfo.mockResolvedValue(null);
    mocks.uploadImagePreview.mockResolvedValue({
      preview_url: "/api/files/raw-preview.png",
      width: 20,
      height: 10,
    });
  });

  it.each([
    {
      label: "a normal image replacement",
      replace: (store: Awaited<ReturnType<typeof loadStore>>) => {
        store.getState().setImageFile(
          new File(["next"], "next.png", { type: "image/png" }),
        );
      },
    },
    {
      label: "a RAW image replacement",
      replace: (store: Awaited<ReturnType<typeof loadStore>>) => {
        store.getState().setImageFile(
          new File(["raw"], "next.dng", { type: "" }),
        );
      },
    },
    {
      label: "clearing the current image",
      replace: (store: Awaited<ReturnType<typeof loadStore>>) => {
        store.getState().setImageFile(null);
      },
    },
    {
      label: "the shared multi-file selection entrypoint",
      replace: (store: Awaited<ReturnType<typeof loadStore>>) => {
        store.getState().handleFilesSelect([
          new File(["next"], "next.png", { type: "image/png" }),
        ]);
      },
    },
  ])("rejects an in-flight response after $label", async ({ replace }) => {
    const store = await loadStore();
    const oldFile = new File(["old"], "old.png", { type: "image/png" });
    store.setState({
      imageFile: oldFile,
      imagePreviewUrl: "blob:old-image",
      source_version: "legacy",
      lut_name: "test-lut",
      lut_names: ["test-lut"],
      enableCrop: false,
      cropModalOpen: false,
      batchFiles: [],
      batchMode: false,
      isLoading: false,
      sessionId: null,
      previewImageUrl: null,
      previewGlbUrl: null,
    });

    const deferred = deferredPreview();
    let requestSignal: AbortSignal | undefined;
    mocks.convertPreview.mockImplementationOnce((_file, _params, signal) => {
      requestSignal = signal;
      return deferred.promise;
    });

    const request = store.getState().submitPreview();
    expect(requestSignal?.aborted).toBe(false);

    replace(store);

    expect(requestSignal?.aborted).toBe(true);
    deferred.resolve({
      session_id: "stale-session",
      status: "ok",
      message: "stale",
      preview_url: "/api/files/stale-preview.png",
      preview_glb_url: "/api/files/stale-preview.glb",
      palette: [],
      dimensions: { width: 10, height: 10 },
      warnings: [],
    });
    await request;

    expect(store.getState().sessionId).toBeNull();
    expect(store.getState().previewImageUrl).toBeNull();
    expect(store.getState().previewGlbUrl).toBeNull();
  });
});

async function loadStore() {
  const { useConverterStore } = await import("../stores/converter");
  return useConverterStore;
}
