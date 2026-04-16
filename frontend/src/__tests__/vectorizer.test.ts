// @vitest-environment jsdom

/**
 * Unit tests for vectorizerStore and buildFileUrl.
 * vectorizerStore 和 buildFileUrl 单元测试。
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { createElement } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useVectorizerStore } from "../stores/vectorizerStore";
import VectorizerPanel, { buildFileUrl } from "../components/VectorizerPanel";

const {
  mockedApiClient,
  setConverterImageFileSpy,
  setWidgetActiveTabSpy,
} = vi.hoisted(() => ({
  mockedApiClient: {
    defaults: { baseURL: "/api" },
    post: vi.fn(),
    get: vi.fn(),
  },
  setConverterImageFileSpy: vi.fn(),
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
      setImageFile: setConverterImageFileSpy,
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

    fireEvent.click(
      screen.getByRole("button", {
        name: "vec.send_to_converter",
      }),
    );

    await waitFor(() => {
      expect(mockedApiClient.get).toHaveBeenCalledWith("/api/files/vectorized.svg", {
        responseType: "blob",
        baseURL: "",
      });
    });

    await waitFor(() => {
      expect(setConverterImageFileSpy).toHaveBeenCalledTimes(1);
    });

    const fileArg = setConverterImageFileSpy.mock.calls[0]?.[0];
    expect(fileArg).toBeInstanceOf(File);
    expect(fileArg.name).toBe("vectorized.svg");
    expect(fileArg.type).toBe("image/svg+xml");

    expect(setWidgetActiveTabSpy).toHaveBeenCalledWith("converter");
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

  it("keeps the backend origin when apiClient baseURL is absolute", () => {
    mockedApiClient.defaults.baseURL = "http://localhost:8000/api";
    const url = buildFileUrl("/api/files/test.svg");
    expect(url).toBe("http://localhost:8000/api/files/test.svg");
  });

  it("handles empty relative path", () => {
    const url = buildFileUrl("");
    expect(url).toBe("/api");
  });
});
