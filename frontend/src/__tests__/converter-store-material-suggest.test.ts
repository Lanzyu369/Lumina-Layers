import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  MaterialColorSuggestionsResponse,
} from "../api/types";

const fetchMaterialColorSuggestionsMock = vi.hoisted(() => vi.fn());

vi.mock("../api/materialCache", async () => {
  const actual = await vi.importActual<typeof import("../api/materialCache")>(
    "../api/materialCache",
  );
  return {
    ...actual,
    fetchMaterialColorSuggestions: fetchMaterialColorSuggestionsMock,
  };
});

async function loadStore() {
  const mod = await import("../stores/converter");
  return mod.useConverterStore;
}

function stubResponse(
  overrides: Partial<MaterialColorSuggestionsResponse> = {},
): MaterialColorSuggestionsResponse {
  return {
    status: "ok",
    message: "Returned 2 achievable colors (via solver cache, 1234 cells).",
    source: "cache",
    palette_hash: "fakehash",
    layer_count: 5,
    layer_height_mm: 0.08,
    substrate: "white",
    target_hex: "#C86432",
    target_rgb: [200, 100, 50],
    suggestions: [
      {
        hex: "#C86432",
        rgb: [200, 100, 50],
        delta_e: 0.5,
        recipe: [0, 1, 2, 1, 0],
        recipe_display: "[0,1,2,1,0]",
      },
      {
        hex: "#CA6838",
        rgb: [202, 104, 56],
        delta_e: 1.2,
        recipe: [0, 1, 2, 2, 0],
        recipe_display: "[0,1,2,2,0]",
      },
    ],
    ...overrides,
  };
}

function resetStore(store: Awaited<ReturnType<typeof loadStore>>) {
  store.setState({
    source_version: "material",
    selectedMaterialDirNames: ["red", "blue", "white"],
    materialLayerCount: 5,
    materialLayerHeightMm: 0.08,
    materialSuggestions: null,
    materialSuggestionsLoading: false,
    materialSuggestionsTargetHex: null,
    materialSuggestionsError: null,
  });
}

describe("converter store — fetchMaterialSuggestions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("populates suggestions state on a successful cache-hit response", async () => {
    const useConverterStore = await loadStore();
    resetStore(useConverterStore);
    const response = stubResponse();
    fetchMaterialColorSuggestionsMock.mockResolvedValueOnce(response);

    await useConverterStore.getState().fetchMaterialSuggestions("#C86432");

    const s = useConverterStore.getState();
    expect(s.materialSuggestions).toBe(response);
    expect(s.materialSuggestionsTargetHex).toBe("#C86432");
    expect(s.materialSuggestionsLoading).toBe(false);
    expect(s.materialSuggestionsError).toBeNull();
    expect(fetchMaterialColorSuggestionsMock).toHaveBeenCalledTimes(1);
    expect(fetchMaterialColorSuggestionsMock).toHaveBeenCalledWith(
      expect.objectContaining({
        materialDirectoryNames: ["red", "blue", "white"],
        layerCount: 5,
        layerHeightMm: 0.08,
        substrate: "white",
      }),
      "#C86432",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("records error state and clears loading on API failure", async () => {
    const useConverterStore = await loadStore();
    resetStore(useConverterStore);
    useConverterStore.setState({
      materialSuggestions: stubResponse(),
      materialSuggestionsTargetHex: "#C86432",
    });
    fetchMaterialColorSuggestionsMock.mockRejectedValueOnce(
      new Error("boom"),
    );

    await useConverterStore.getState().fetchMaterialSuggestions("#808080");

    const s = useConverterStore.getState();
    expect(s.materialSuggestions).toBeNull();
    expect(s.materialSuggestionsTargetHex).toBe("#808080");
    expect(s.materialSuggestionsLoading).toBe(false);
    expect(s.materialSuggestionsError).toBe("boom");
  });

  it("normalizes HTTP status errors before showing material suggestion failures", async () => {
    const useConverterStore = await loadStore();
    resetStore(useConverterStore);
    fetchMaterialColorSuggestionsMock.mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    await useConverterStore.getState().fetchMaterialSuggestions("#808080");

    const error = useConverterStore.getState().materialSuggestionsError;
    expect(error).toBeTruthy();
    expect(error).not.toMatch(/Request failed with status code 500/i);
    expect(error).not.toMatch(/status code\s+500/i);
  });

  it("short-circuits when called outside material-archive mode", async () => {
    const useConverterStore = await loadStore();
    resetStore(useConverterStore);
    useConverterStore.setState({ source_version: "legacy" });

    await useConverterStore.getState().fetchMaterialSuggestions("#808080");

    expect(fetchMaterialColorSuggestionsMock).not.toHaveBeenCalled();
    expect(
      useConverterStore.getState().materialSuggestionsError,
    ).toContain("material");
  });

  it("reports a friendly error when no materials are selected", async () => {
    const useConverterStore = await loadStore();
    resetStore(useConverterStore);
    useConverterStore.setState({ selectedMaterialDirNames: [] });

    await useConverterStore.getState().fetchMaterialSuggestions("#808080");

    expect(fetchMaterialColorSuggestionsMock).not.toHaveBeenCalled();
    const s = useConverterStore.getState();
    expect(s.materialSuggestions).toBeNull();
    expect(s.materialSuggestionsError).toContain("No materials");
  });

  it("clears state on empty target hex without calling the API", async () => {
    const useConverterStore = await loadStore();
    resetStore(useConverterStore);
    useConverterStore.setState({
      materialSuggestions: stubResponse(),
      materialSuggestionsTargetHex: "#C86432",
      materialSuggestionsError: null,
    });

    await useConverterStore.getState().fetchMaterialSuggestions("   ");

    expect(fetchMaterialColorSuggestionsMock).not.toHaveBeenCalled();
    const s = useConverterStore.getState();
    expect(s.materialSuggestions).toBeNull();
    expect(s.materialSuggestionsTargetHex).toBeNull();
  });

  it("serves a repeated target from the LRU cache without a network call", async () => {
    const useConverterStore = await loadStore();
    resetStore(useConverterStore);
    const response = stubResponse();
    fetchMaterialColorSuggestionsMock.mockResolvedValue(response);

    await useConverterStore.getState().fetchMaterialSuggestions("#C86432");
    // Second call for the same target uses the LRU, not the mock.
    await useConverterStore.getState().fetchMaterialSuggestions("#C86432");

    expect(fetchMaterialColorSuggestionsMock).toHaveBeenCalledTimes(1);
    const s = useConverterStore.getState();
    // Cached path sets the same response and a finite loading=false.
    expect(s.materialSuggestions).toBe(response);
    expect(s.materialSuggestionsLoading).toBe(false);
  });

  it("uses the dynamic printable maximum in the request and LRU key", async () => {
    const useConverterStore = await loadStore();
    resetStore(useConverterStore);
    useConverterStore.setState({
      materialDynamicLayerCountEnabled: true,
      materialMinLayerCount: 5,
      materialMaxLayerCount: 8,
    });
    fetchMaterialColorSuggestionsMock
      .mockResolvedValueOnce(stubResponse({ layer_count: 8 }))
      .mockResolvedValueOnce(stubResponse({ layer_count: 7 }));

    await useConverterStore.getState().fetchMaterialSuggestions("#C86432");
    useConverterStore.setState({ materialMaxLayerCount: 7 });
    await useConverterStore.getState().fetchMaterialSuggestions("#C86432");

    expect(fetchMaterialColorSuggestionsMock).toHaveBeenCalledTimes(2);
    expect(fetchMaterialColorSuggestionsMock.mock.calls[0]?.[0]).toEqual(
      expect.objectContaining({ layerCount: 8 }),
    );
    expect(fetchMaterialColorSuggestionsMock.mock.calls[1]?.[0]).toEqual(
      expect.objectContaining({ layerCount: 7 }),
    );
  });

  it("clears and rejects an in-flight result when the dynamic maximum changes", async () => {
    const useConverterStore = await loadStore();
    resetStore(useConverterStore);
    useConverterStore.setState({
      materialDynamicLayerCountEnabled: true,
      materialMinLayerCount: 5,
      materialMaxLayerCount: 8,
    });

    let requestSignal: AbortSignal | undefined;
    let resolveRequest: (value: MaterialColorSuggestionsResponse) => void =
      () => {};
    const pendingResponse = new Promise<MaterialColorSuggestionsResponse>(
      (resolve) => {
        resolveRequest = resolve;
      },
    );
    fetchMaterialColorSuggestionsMock.mockImplementationOnce(
      async (_key: unknown, _hex: string, options: { signal?: AbortSignal }) => {
        requestSignal = options.signal;
        return pendingResponse;
      },
    );

    const pending = useConverterStore
      .getState()
      .fetchMaterialSuggestions("#C86432");
    expect(useConverterStore.getState().materialSuggestionsLoading).toBe(true);

    useConverterStore.getState().setMaterialMaxLayerCount(7);
    expect(requestSignal?.aborted).toBe(true);
    expect(useConverterStore.getState().materialSuggestions).toBeNull();
    expect(useConverterStore.getState().materialSuggestionsLoading).toBe(false);

    resolveRequest(stubResponse({ layer_count: 8 }));
    await pending;

    expect(useConverterStore.getState().materialSuggestions).toBeNull();
    expect(useConverterStore.getState().materialSuggestionsTargetHex).toBeNull();
  });

  it("does not share cache between palettes with different ordering", async () => {
    const useConverterStore = await loadStore();
    resetStore(useConverterStore);
    const response1 = stubResponse({ palette_hash: "hash-A" });
    const response2 = stubResponse({ palette_hash: "hash-B" });
    fetchMaterialColorSuggestionsMock
      .mockResolvedValueOnce(response1)
      .mockResolvedValueOnce(response2);

    await useConverterStore.getState().fetchMaterialSuggestions("#C86432");
    expect(useConverterStore.getState().materialSuggestions?.palette_hash)
      .toBe("hash-A");
    // Swap the palette order — this must invalidate the LRU entry.
    useConverterStore.setState({
      selectedMaterialDirNames: ["blue", "red", "white"],
    });
    await useConverterStore.getState().fetchMaterialSuggestions("#C86432");

    expect(fetchMaterialColorSuggestionsMock).toHaveBeenCalledTimes(2);
    expect(useConverterStore.getState().materialSuggestions?.palette_hash)
      .toBe("hash-B");
  });

  it("cancels a stale request when a newer target supersedes it", async () => {
    const useConverterStore = await loadStore();
    resetStore(useConverterStore);

    let firstSignal: AbortSignal | undefined;
    let resolveFirst: (v: MaterialColorSuggestionsResponse) => void = () => {};
    let rejectFirst: (e: unknown) => void = () => {};
    const firstPromise = new Promise<MaterialColorSuggestionsResponse>(
      (resolve, reject) => {
        resolveFirst = resolve;
        rejectFirst = reject;
      },
    );
    fetchMaterialColorSuggestionsMock.mockImplementationOnce(
      async (_key: unknown, _hex: string, options: { signal?: AbortSignal }) => {
        firstSignal = options.signal;
        return firstPromise;
      },
    );
    const response2 = stubResponse({ palette_hash: "hash-second" });
    fetchMaterialColorSuggestionsMock.mockResolvedValueOnce(response2);

    // Kick off the first request but do not await it yet.
    const p1 = useConverterStore.getState().fetchMaterialSuggestions("#C86432");
    expect(useConverterStore.getState().materialSuggestionsLoading).toBe(true);

    // Fire a second request; this should abort the first.
    const p2 = useConverterStore.getState().fetchMaterialSuggestions("#808080");
    expect(firstSignal?.aborted).toBe(true);

    // Resolve the first (now stale) request — store must ignore it.
    rejectFirst(new DOMException("aborted", "AbortError"));
    await p1;
    // Second request completes normally.
    await p2;
    // To silence unhandled-promise linting.
    void resolveFirst;

    const s = useConverterStore.getState();
    expect(s.materialSuggestions).toBe(response2);
    expect(s.materialSuggestionsTargetHex).toBe("#808080");
    expect(s.materialSuggestionsLoading).toBe(false);
    expect(s.materialSuggestionsError).toBeNull();
  });

  it("clearMaterialSuggestions resets state and aborts pending requests", async () => {
    const useConverterStore = await loadStore();
    resetStore(useConverterStore);
    let signal: AbortSignal | undefined;
    fetchMaterialColorSuggestionsMock.mockImplementationOnce(
      async (_k: unknown, _h: string, opts: { signal?: AbortSignal }) => {
        signal = opts.signal;
        return new Promise<MaterialColorSuggestionsResponse>(() => {
          /* never resolves */
        });
      },
    );

    void useConverterStore.getState().fetchMaterialSuggestions("#C86432");
    expect(useConverterStore.getState().materialSuggestionsLoading).toBe(true);

    useConverterStore.getState().clearMaterialSuggestions();

    const s = useConverterStore.getState();
    expect(signal?.aborted).toBe(true);
    expect(s.materialSuggestions).toBeNull();
    expect(s.materialSuggestionsTargetHex).toBeNull();
    expect(s.materialSuggestionsError).toBeNull();
    expect(s.materialSuggestionsLoading).toBe(false);
  });
});
