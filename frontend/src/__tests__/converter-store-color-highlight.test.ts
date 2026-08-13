import { beforeEach, describe, expect, it, vi } from "vitest";

const colorHighlightMock = vi.hoisted(() => vi.fn());

vi.mock("../api/converter", async () => {
  const actual =
    await vi.importActual<typeof import("../api/converter")>("../api/converter");
  return {
    ...actual,
    colorHighlight: colorHighlightMock,
  };
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function loadStore() {
  const mod = await import("../stores/converter");
  return mod.useConverterStore;
}

describe("converter store color highlight", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
  });

  it("keeps the latest manual multi-select highlight when an older response resolves later", async () => {
    const fifthHighlight = deferred<{ preview_url: string }>();
    const sixthHighlight = deferred<{ preview_url: string }>();
    colorHighlightMock
      .mockReturnValueOnce(fifthHighlight.promise)
      .mockReturnValueOnce(sixthHighlight.promise);

    const useConverterStore = await loadStore();
    useConverterStore.setState({
      sessionId: "session-highlight",
      selectionMode: "select-all",
      selectedColors: new Set(["111111", "222222", "333333", "444444"]),
      previewImageUrl: "/api/files/base.png",
      previewBaseImageUrl: "/api/files/base.png",
      originalPreviewUrl: "/api/files/base.png",
    });

    useConverterStore.getState().toggleColorInSelection("555555");
    useConverterStore.getState().toggleColorInSelection("666666");

    expect(colorHighlightMock).toHaveBeenNthCalledWith(1, "session-highlight", [
      "111111",
      "222222",
      "333333",
      "444444",
      "555555",
    ]);
    expect(colorHighlightMock).toHaveBeenNthCalledWith(2, "session-highlight", [
      "111111",
      "222222",
      "333333",
      "444444",
      "555555",
      "666666",
    ]);

    sixthHighlight.resolve({ preview_url: "/api/files/highlight-6.png" });
    await Promise.resolve();
    expect(useConverterStore.getState().previewImageUrl).toBe(
      "/api/files/highlight-6.png",
    );

    fifthHighlight.resolve({ preview_url: "/api/files/highlight-5.png" });
    await Promise.resolve();
    expect(useConverterStore.getState().previewImageUrl).toBe(
      "/api/files/highlight-6.png",
    );
  });

  it("drops a manual highlight response when the session changes before it resolves", async () => {
    const highlight = deferred<{ preview_url: string }>();
    colorHighlightMock.mockReturnValueOnce(highlight.promise);

    const useConverterStore = await loadStore();
    useConverterStore.setState({
      sessionId: "session-before",
      selectionMode: "select-all",
      selectedColors: new Set(["111111", "222222", "333333", "444444"]),
      previewImageUrl: "/api/files/base.png",
      previewBaseImageUrl: "/api/files/base.png",
      originalPreviewUrl: "/api/files/base.png",
    });

    useConverterStore.getState().toggleColorInSelection("555555");
    useConverterStore.setState({ sessionId: "session-after" });

    highlight.resolve({ preview_url: "/api/files/stale-session.png" });
    await Promise.resolve();

    expect(useConverterStore.getState().previewImageUrl).toBe(
      "/api/files/base.png",
    );
  });

  it("drops a manual highlight response when selection mode changes before it resolves", async () => {
    const highlight = deferred<{ preview_url: string }>();
    colorHighlightMock.mockReturnValueOnce(highlight.promise);

    const useConverterStore = await loadStore();
    useConverterStore.setState({
      sessionId: "session-highlight",
      selectionMode: "select-all",
      selectedColors: new Set(["111111", "222222", "333333", "444444"]),
      previewImageUrl: "/api/files/base.png",
      previewBaseImageUrl: "/api/files/base.png",
      originalPreviewUrl: "/api/files/base.png",
    });

    useConverterStore.getState().toggleColorInSelection("555555");
    useConverterStore.setState({ selectionMode: "current" });

    highlight.resolve({ preview_url: "/api/files/stale-mode.png" });
    await Promise.resolve();

    expect(useConverterStore.getState().previewImageUrl).toBe(
      "/api/files/base.png",
    );
  });

  it("uses local contour overlay instead of requesting highlight PNG when contours are cached", async () => {
    const useConverterStore = await loadStore();
    useConverterStore.setState({
      sessionId: "session-highlight",
      selectionMode: "select-all",
      selectedColors: new Set<string>(),
      previewImageUrl: "/api/files/base.png",
      previewBaseImageUrl: "/api/files/base.png",
      originalPreviewUrl: "/api/files/base.png",
      colorContours: {
        "555555": [
          [
            [0, 0],
            [1, 0],
            [1, 1],
          ],
        ],
      },
    });

    useConverterStore.getState().toggleColorInSelection("555555");

    expect(colorHighlightMock).not.toHaveBeenCalled();
    expect(useConverterStore.getState().previewImageUrl).toBe(
      "/api/files/base.png",
    );
    expect(useConverterStore.getState().selectedColors).toEqual(
      new Set(["555555"]),
    );
  });
});
