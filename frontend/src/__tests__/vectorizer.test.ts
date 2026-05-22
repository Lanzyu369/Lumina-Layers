// @vitest-environment jsdom

/**
 * Unit tests for vectorizerStore and buildFileUrl.
 * vectorizerStore 和 buildFileUrl 单元测试。
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { StrictMode, createElement } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useVectorizerStore } from "../stores/vectorizerStore";
import VectorizerPanel, { buildFileUrl } from "../components/VectorizerPanel";
import { translations } from "../i18n/translations";

const {
  mockedApiClient,
  loadVectorizedSvgIntoConverterSpy,
  setWidgetActiveTabSpy,
} = vi.hoisted(() => ({
  mockedApiClient: {
    defaults: { baseURL: "/api" },
    post: vi.fn(),
    get: vi.fn(),
  },
  loadVectorizedSvgIntoConverterSpy: vi.fn(),
  setWidgetActiveTabSpy: vi.fn(),
}));

// Mock apiClient for buildFileUrl tests
vi.mock("../api/client", () => ({
  default: mockedApiClient,
}));

// Mock vectorizeImage to avoid real API calls
vi.mock("../api/vectorizer", () => ({
  vectorizeImage: vi.fn(),
}));

// Mock converterStore and widgetStore for send-to-converter tests
vi.mock("../stores/converter", () => ({
  useConverterStore: {
    getState: vi.fn(() => ({
      loadVectorizedSvgIntoConverter: loadVectorizedSvgIntoConverterSpy,
    })),
  },
}));

vi.mock("../stores/widgetStore", () => ({
  useWidgetStore: {
    getState: vi.fn(() => ({
      setActiveTab: setWidgetActiveTabSpy,
    })),
  },
}));

function resetStore() {
  useVectorizerStore.getState().reset();
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function getPanelButtonByKey(key: string): HTMLElement {
  const entry = translations[key];
  const labels = [entry?.zh, entry?.en, key].filter(
    (label): label is string => typeof label === "string" && label.length > 0,
  );
  const namePattern = new RegExp(`^(?:${labels.map(escapeRegExp).join("|")})$`, "i");
  return screen.getByRole("button", { name: namePattern });
}

describe("vectorizerStore", () => {
  beforeEach(() => {
    cleanup();
    resetStore();
    mockedApiClient.defaults.baseURL = "/api";
    vi.clearAllMocks();
  });

  // --- Initial state ---
  it("has correct initial state", () => {
    const state = useVectorizerStore.getState();
    expect(state.imageFile).toBeNull();
    expect(state.imagePreviewUrl).toBeNull();
    expect(state.isProcessing).toBe(false);
    expect(state.error).toBeNull();
    expect(state.result).toBeNull();
    expect(state.abortController).toBeNull();
  });

  it("has default params with all 23 fields", () => {
    const { params } = useVectorizerStore.getState();
    const keys = Object.keys(params);
    expect(keys).toHaveLength(23);
    expect(params.num_colors).toBe(0);
    expect(params.smoothness).toBe(0.5);
    expect(params.detail_level).toBe(-1);
  });

  // --- setParam ---
  it("setParam updates a single parameter", () => {
    useVectorizerStore.getState().setParam("num_colors", 32);
    expect(useVectorizerStore.getState().params.num_colors).toBe(32);
  });

  it("setParam does not affect other parameters", () => {
    const before = { ...useVectorizerStore.getState().params };
    useVectorizerStore.getState().setParam("smoothness", 0.9);
    const after = useVectorizerStore.getState().params;
    expect(after.smoothness).toBe(0.9);
    expect(after.num_colors).toBe(before.num_colors);
    expect(after.detail_level).toBe(before.detail_level);
  });

  // --- cancel ---
  it("cancel sets isProcessing=false and abortController=null", () => {
    // Simulate processing state
    const controller = new AbortController();
    useVectorizerStore.setState({
      isProcessing: true,
      abortController: controller,
    });

    useVectorizerStore.getState().cancel();

    const state = useVectorizerStore.getState();
    expect(state.isProcessing).toBe(false);
    expect(state.abortController).toBeNull();
  });

  it("cancel aborts the active AbortController", () => {
    const controller = new AbortController();
    const abortSpy = vi.spyOn(controller, "abort");
    useVectorizerStore.setState({
      isProcessing: true,
      abortController: controller,
    });

    useVectorizerStore.getState().cancel();
    expect(abortSpy).toHaveBeenCalled();
  });

  it("cancel is a no-op when not processing", () => {
    // Should not throw
    useVectorizerStore.getState().cancel();
    expect(useVectorizerStore.getState().isProcessing).toBe(false);
  });

  // --- reset ---
  it("reset restores all state to defaults", () => {
    // Mutate state
    useVectorizerStore.setState({
      isProcessing: true,
      error: "some error",
      result: {
        status: "ok",
        message: "done",
        svg_url: "/files/test.svg",
        width: 100,
        height: 100,
        num_shapes: 10,
        num_colors: 5,
        palette: ["#ff0000"],
      },
    });
    useVectorizerStore.getState().setParam("num_colors", 128);

    useVectorizerStore.getState().reset();

    const state = useVectorizerStore.getState();
    expect(state.imageFile).toBeNull();
    expect(state.imagePreviewUrl).toBeNull();
    expect(state.isProcessing).toBe(false);
    expect(state.error).toBeNull();
    expect(state.result).toBeNull();
    expect(state.params.num_colors).toBe(0);
    expect(state.params.smoothness).toBe(0.5);
  });

  // --- submit without image ---
  it("submit does nothing when imageFile is null", async () => {
    await useVectorizerStore.getState().submit();
    expect(useVectorizerStore.getState().isProcessing).toBe(false);
  });
});

describe("VectorizerPanel send-to-converter", () => {
  beforeEach(() => {
    cleanup();
    resetStore();
    mockedApiClient.defaults.baseURL = "/api";
    vi.clearAllMocks();
  });

  it("uses a full-width scroll area with a wide split content layout", () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 2400 });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 1200 });
    Object.defineProperty(window, "devicePixelRatio", { configurable: true, value: 1 });

    const { container } = render(createElement(VectorizerPanel));
    const scrollArea = container.firstElementChild as HTMLElement;
    const contentShell = scrollArea.firstElementChild as HTMLElement;
    const splitLayout = contentShell.firstElementChild as HTMLElement;

    expect(scrollArea).toHaveClass("panel-surface", "h-full", "w-full", "overflow-auto");
    expect(scrollArea).not.toHaveClass("mx-auto");
    expect(scrollArea).not.toHaveClass("max-w-4xl");
    expect(contentShell).toHaveClass("mx-auto", "w-full", "max-w-[96rem]");
    expect(splitLayout).toHaveClass(
      "grid",
      "min-h-0",
      "gap-5",
      "xl:grid-cols-[minmax(22rem,30rem)_minmax(0,1fr)]",
    );
  });

  it("fetches svg with normalized url and forwards it to converter tab", async () => {
    const svgBlob = new Blob(["<svg/>"], { type: "image/svg+xml" });
    mockedApiClient.get.mockResolvedValueOnce({ data: svgBlob });

    useVectorizerStore.setState({
      imagePreviewUrl: "blob:original-preview",
      result: {
        status: "ok",
        message: "done",
        svg_url: "/api/files/vectorized.svg",
        width: 100,
        height: 100,
        num_shapes: 12,
        num_colors: 4,
        palette: ["#000000", "#ffffff"],
      },
    });

    render(createElement(VectorizerPanel));

    fireEvent.click(getPanelButtonByKey("vec.send_to_converter"));

    await waitFor(() => {
      expect(mockedApiClient.get).toHaveBeenCalledWith("/api/files/vectorized.svg", {
        responseType: "blob",
        baseURL: "",
      });
    });

    await waitFor(() => {
      expect(loadVectorizedSvgIntoConverterSpy).toHaveBeenCalledTimes(1);
    });

    const fileArg = loadVectorizedSvgIntoConverterSpy.mock.calls[0]?.[0];
    expect(fileArg).toBeInstanceOf(File);
    expect(fileArg.name).toBe("vectorized.svg");
    expect(fileArg.type).toBe("image/svg+xml");

    expect(setWidgetActiveTabSpy).toHaveBeenCalledWith("converter");
  });

  it("downloads svg using a resolved anchor href", () => {
    useVectorizerStore.setState({
      imagePreviewUrl: "blob:original-preview",
      result: {
        status: "ok",
        message: "done",
        svg_url: "/api/files/vectorized.svg",
        width: 100,
        height: 100,
        num_shapes: 12,
        num_colors: 4,
        palette: ["#000000", "#ffffff"],
      },
    });

    render(createElement(VectorizerPanel));

    const originalCreateElement = document.createElement.bind(document);
    const anchorMock = {
      href: "",
      download: "",
      click: vi.fn(),
    } as unknown as HTMLAnchorElement;

    const createElementSpy = vi
      .spyOn(document, "createElement")
      .mockImplementation((tagName: string, options?: ElementCreationOptions) => {
        if (tagName.toLowerCase() === "a") {
          return anchorMock;
        }
        return originalCreateElement(tagName, options);
      });

    try {
      fireEvent.click(getPanelButtonByKey("vec.download_svg"));
    } finally {
      createElementSpy.mockRestore();
    }

    expect(anchorMock.href).toBe("/api/files/vectorized.svg");
    expect(anchorMock.download).toBe("vectorized.svg");
    expect(anchorMock.click).toHaveBeenCalledTimes(1);
  });

  it("does not reset vectorizer resources during StrictMode initial mount", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const abortSpy = vi.spyOn(controller, "abort");
    const originalRevokeObjectURL = URL.revokeObjectURL;
    const revokeObjectURLSpy = vi.fn();

    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: revokeObjectURLSpy,
    });

    useVectorizerStore.setState({
      imageFile: new File(["img"], "vectorizer.png", { type: "image/png" }),
      imagePreviewUrl: "blob:vectorizer-preview",
      isProcessing: true,
      abortController: controller,
    });

    render(createElement(StrictMode, null, createElement(VectorizerPanel)));

    await vi.advanceTimersByTimeAsync(0);

    expect(abortSpy).not.toHaveBeenCalled();
    expect(revokeObjectURLSpy).not.toHaveBeenCalled();
    expect(useVectorizerStore.getState().imagePreviewUrl).toBe("blob:vectorizer-preview");
    expect(useVectorizerStore.getState().abortController).toBe(controller);

    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: originalRevokeObjectURL,
    });
  });

  it("resets vectorizer resources after a real unmount once the delay flushes", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const abortSpy = vi.spyOn(controller, "abort");
    const originalRevokeObjectURL = URL.revokeObjectURL;
    const revokeObjectURLSpy = vi.fn();

    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: revokeObjectURLSpy,
    });

    useVectorizerStore.setState({
      imageFile: new File(["img"], "vectorizer.png", { type: "image/png" }),
      imagePreviewUrl: "blob:vectorizer-preview",
      isProcessing: true,
      abortController: controller,
    });

    const view = render(
      createElement(StrictMode, null, createElement(VectorizerPanel)),
    );

    await vi.advanceTimersByTimeAsync(0);

    expect(abortSpy).not.toHaveBeenCalled();
    expect(revokeObjectURLSpy).not.toHaveBeenCalled();

    view.unmount();

    expect(abortSpy).not.toHaveBeenCalled();
    expect(revokeObjectURLSpy).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(0);

    expect(abortSpy).toHaveBeenCalledOnce();
    expect(revokeObjectURLSpy).toHaveBeenCalledWith("blob:vectorizer-preview");
    expect(useVectorizerStore.getState().imagePreviewUrl).toBeNull();
    expect(useVectorizerStore.getState().abortController).toBeNull();

    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: originalRevokeObjectURL,
    });
  });
});

describe("buildFileUrl", () => {
  beforeEach(() => {
    mockedApiClient.defaults.baseURL = "/api";
  });

  it("prepends apiClient baseURL to legacy relative path", () => {
    const url = buildFileUrl("/files/test.svg");
    expect(url).toBe("/api/files/test.svg");
  });

  it("does not double-prefix api-prefixed paths", () => {
    const url = buildFileUrl("/api/files/test.svg");
    expect(url).toBe("/api/files/test.svg");
  });

  it("preserves path prefix when apiClient baseURL is absolute", () => {
    mockedApiClient.defaults.baseURL = "https://host.example/lumina/api";
    const url = buildFileUrl("/api/files/test.svg");
    expect(url).toBe("https://host.example/lumina/api/files/test.svg");
  });

  it("handles empty relative path", () => {
    const url = buildFileUrl("");
    expect(url).toBe("/api");
  });
});
