import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../utils/clientLog", () => ({
  postClientLog: vi.fn(),
  summarizeErrorForLog: (error: unknown) => ({
    error_message: error instanceof Error ? error.message : String(error),
  }),
}));

import { postClientLog } from "../../utils/clientLog";
import { useActionHistoryStore } from "../../stores/actionHistoryStore";
import { useSettingsStore } from "../../stores/settingsStore";
import apiClient, {
  assertResourceDownloadAvailable,
  downloadResourceBlob,
} from "../client";

describe("apiClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useActionHistoryStore.getState()._resetForTests();
    useSettingsStore.setState({ language: "en" });
  });

  afterEach(() => {
    apiClient.defaults.adapter = undefined;
  });

  it("records failed API responses in the client log buffer", async () => {
    const error = new Error("Request failed");
    Object.assign(error, {
      config: { method: "post", url: "/convert/generate" },
      response: {
        status: 500,
        headers: { "x-request-id": "req-500-debug" },
        data: { detail: "worker crashed" },
      },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(apiClient.post("/convert/generate", {})).rejects.toMatchObject({
      message: "worker crashed",
    });

    expect(postClientLog).toHaveBeenCalledWith(
      "api: request failed",
      expect.objectContaining({
        scope: "api",
        phase: "request-failed",
        method: "error",
        details: expect.objectContaining({
          method: "POST",
          url: "/convert/generate",
          status_code: 500,
          request_id: "req-500-debug",
          response_detail: { detail: "worker crashed" },
          error_message: "worker crashed",
        }),
      }),
    );
    expect(useActionHistoryStore.getState().history.at(-1)?.error).toEqual(
      expect.objectContaining({
        status_code: 500,
        path: "/convert/generate",
        request_id: "req-500-debug",
        error_message: "worker crashed",
      }),
    );
  });

  it("turns FastAPI validation details into a readable rejected message", async () => {
    const error = new Error("Request failed with status code 422");
    Object.assign(error, {
      config: { method: "post", url: "/convert/puzzle-layout-preview" },
      response: {
        status: 422,
        data: {
          detail: [
            { loc: ["body", "session_id"], msg: "Field required" },
            { loc: ["body", "params"], msg: "Field required" },
          ],
        },
      },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(
      apiClient.post("/convert/puzzle-layout-preview", {}),
    ).rejects.toMatchObject({
      message: "body.session_id: Field required; body.params: Field required",
    });

    expect(postClientLog).toHaveBeenCalledWith(
      "api: request failed",
      expect.objectContaining({
        details: expect.objectContaining({
          status_code: 422,
          error_message:
            "body.session_id: Field required; body.params: Field required",
        }),
      }),
    );
  });

  it("uses a readable HTTP fallback when the response has no detail", async () => {
    const error = new Error("Request failed with status code 503");
    Object.assign(error, {
      config: { method: "get", url: "/system/settings" },
      response: { status: 503, data: {} },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(apiClient.get("/system/settings")).rejects.toMatchObject({
      message: "Server temporarily unavailable. Please try again later.",
    });
  });

  it("explains quota/payment failures with the HTTP 402 fallback", async () => {
    const error = new Error("Request failed with status code 402");
    Object.assign(error, {
      config: { method: "post", url: "/convert/generate" },
      response: { status: 402, data: {} },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(apiClient.post("/convert/generate", {})).rejects.toMatchObject({
      message:
        "This action requires an available quota or payment before it can continue.",
    });
  });

  it("replaces generic framework details with a real user-facing reason", async () => {
    const error = new Error("Request failed with status code 404");
    Object.assign(error, {
      config: { method: "get", url: "/missing-preview.png" },
      response: { status: 404, data: { detail: "Not Found" } },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(apiClient.get("/missing-preview.png")).rejects.toMatchObject({
      message: "The requested resource was not found or has expired.",
    });
  });

  it("uses a language fallback for unknown client errors without exposing status numbers", async () => {
    const error = new Error("Request failed with status code 418");
    Object.assign(error, {
      config: { method: "post", url: "/convert/generate" },
      response: { status: 418, data: {} },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(apiClient.post("/convert/generate", {})).rejects.toMatchObject({
      message:
        "The server did not accept the request. Check the current input, permissions, or resource availability.",
    });
  });

  it("turns failed resource downloads into readable errors", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 404,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve({ detail: "Not Found" }),
    }) as unknown as typeof fetch;

    try {
      await expect(downloadResourceBlob("/api/files/missing")).rejects.toThrow(
        "The requested resource was not found or has expired.",
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("preserves detailed backend messages for failed resource downloads", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 500,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve({ detail: "worker crashed" }),
    }) as unknown as typeof fetch;

    try {
      await expect(downloadResourceBlob("/api/files/broken")).rejects.toThrow(
        "worker crashed",
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("validates resource downloads with a bounded range request", async () => {
    const originalFetch = globalThis.fetch;
    const cancel = vi.fn().mockResolvedValue(undefined);
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      status: 206,
      headers: { get: () => "application/octet-stream" },
      body: { cancel },
    }) as unknown as typeof fetch;

    try {
      await expect(
        assertResourceDownloadAvailable("/api/files/model"),
      ).resolves.toBeUndefined();
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/files/model",
        expect.objectContaining({
          headers: expect.any(Headers),
        }),
      );
      const init = vi.mocked(globalThis.fetch).mock.calls[0]?.[1] as RequestInit;
      expect((init.headers as Headers).get("Range")).toBe("bytes=0-0");
      expect(cancel).toHaveBeenCalledOnce();
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("turns failed resource validation into readable errors", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 404,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve({ detail: "File not found or expired" }),
    }) as unknown as typeof fetch;

    try {
      await expect(
        assertResourceDownloadAvailable("/api/files/missing-model"),
      ).rejects.toThrow("File not found or expired");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
