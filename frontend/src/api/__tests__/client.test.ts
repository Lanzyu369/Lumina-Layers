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
  apiErrorToVisibleMessage,
  assertResourceDownloadAvailable,
  downloadResourceBlob,
} from "../client";

const jsonHeaders = {
  get: (name: string) =>
    name.toLowerCase() === "content-type" ? "application/json" : null,
};

describe("apiClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useActionHistoryStore.getState()._resetForTests();
    useSettingsStore.setState({ language: "en" });
  });

  afterEach(() => {
    apiClient.defaults.adapter = undefined;
  });

  it("redacts server error details from user-facing API failures and logs", async () => {
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

    const expectedMessage =
      "The server hit an internal error. Request ID: req-500-debug.";
    const rejected = await apiClient.post("/convert/generate", {}).catch((err) => err);
    expect(rejected).toMatchObject({ message: expectedMessage });
    expect(rejected.response?.data?.detail).toBe(expectedMessage);
    expect(JSON.stringify(rejected.response?.data)).not.toContain("worker crashed");

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
          response_detail: {
            detail_redacted: true,
            detail_type: "string",
            detail_length: "worker crashed".length,
          },
          error_message: expectedMessage,
        }),
      }),
    );
    expect(JSON.stringify(vi.mocked(postClientLog).mock.calls)).not.toContain(
      "worker crashed",
    );
    expect(useActionHistoryStore.getState().history.at(-1)?.error).toEqual(
      expect.objectContaining({
        status_code: 500,
        path: "/convert/generate",
        request_id: "req-500-debug",
        error_message: expectedMessage,
      }),
    );
    expect(
      JSON.stringify(useActionHistoryStore.getState().history.at(-1)),
    ).not.toContain("worker crashed");
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

  it("uses structured detail object messages before HTTP status fallbacks", async () => {
    const error = new Error("Request failed with status code 422");
    Object.assign(error, {
      config: { method: "post", url: "/convert/preview" },
      response: {
        status: 422,
        data: {
          detail: {
            error: "preview_cache_size_limit_exceeded",
            message:
              "Estimated preview cache arrays exceed the configured limit.",
            estimate_bytes: 640_000_000,
            max_bytes: 536_870_912,
            estimated_width: 2000,
            estimated_height: 2000,
            estimated_layers: 5,
          },
        },
      },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(apiClient.post("/convert/preview", {})).rejects.toMatchObject({
      message: expect.stringContaining(
        "Estimated preview cache arrays exceed the configured limit.",
      ),
    });

    expect(postClientLog).toHaveBeenCalledWith(
      "api: request failed",
      expect.objectContaining({
        details: expect.objectContaining({
          status_code: 422,
          error_message: expect.stringContaining(
            "Estimated preview cache arrays exceed the configured limit.",
          ),
        }),
      }),
    );
  });

  it("uses a top-level message before a structured detail error code", async () => {
    const error = new Error("Request failed with status code 409");
    Object.assign(error, {
      config: { method: "post", url: "/convert/generate" },
      response: {
        status: 409,
        data: {
          detail: { error: "preview_cache_missing" },
          message: "Preview cache is missing. Run preview again.",
        },
      },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(apiClient.post("/convert/generate", {})).rejects.toMatchObject({
      message: "Preview cache is missing. Run preview again.",
    });
  });

  it("uses readable HTTP fallbacks instead of structured detail error codes", async () => {
    const error = new Error("Request failed with status code 409");
    Object.assign(error, {
      config: { method: "post", url: "/convert/generate" },
      response: {
        status: 409,
        data: {
          detail: { error: "preview_cache_missing" },
        },
      },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    const rejected = await apiClient.post("/convert/generate", {}).catch((err) => err);
    const expectedMessage = "The request conflicts with the current server state.";
    expect(rejected).toMatchObject({ message: expectedMessage });
    expect(rejected.response?.data?.detail).toBe(expectedMessage);
  });

  it("replaces string error codes with readable HTTP fallbacks", async () => {
    const error = new Error("Request failed with status code 409");
    Object.assign(error, {
      config: { method: "post", url: "/convert/generate" },
      response: {
        status: 409,
        data: { detail: "preview_cache_missing" },
      },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    const rejected = await apiClient.post("/convert/generate", {}).catch((err) => err);
    expect(rejected).toMatchObject({
      message: "The request conflicts with the current server state.",
    });
    expect(rejected.response?.data?.detail).toBe(
      "The request conflicts with the current server state.",
    );
  });

  it("replaces top-level string error codes with readable HTTP fallbacks", async () => {
    const error = new Error("Request failed with status code 409");
    Object.assign(error, {
      config: { method: "post", url: "/convert/generate" },
      response: {
        status: 409,
        data: { message: "preview_cache_missing" },
      },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    const rejected = await apiClient.post("/convert/generate", {}).catch((err) => err);
    expect(rejected).toMatchObject({
      message: "The request conflicts with the current server state.",
    });
    expect(rejected.response?.data?.message).toBe(
      "The request conflicts with the current server state.",
    );
  });

  it("replaces duplicated detail and message error codes together", async () => {
    const error = new Error("Request failed with status code 409");
    Object.assign(error, {
      config: { method: "post", url: "/convert/generate" },
      response: {
        status: 409,
        data: {
          detail: "preview_cache_missing",
          message: "preview-cache-missing",
        },
      },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    const rejected = await apiClient.post("/convert/generate", {}).catch((err) => err);
    const expectedMessage = "The request conflicts with the current server state.";
    expect(rejected).toMatchObject({ message: expectedMessage });
    expect(rejected.response?.data?.detail).toBe(expectedMessage);
    expect(rejected.response?.data?.message).toBe(expectedMessage);
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

  it("replaces numeric-only backend details with readable HTTP fallbacks", async () => {
    const error = new Error("Request failed with status code 500");
    Object.assign(error, {
      config: { method: "post", url: "/convert/generate" },
      response: { status: 500, data: { detail: "500" } },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    const expectedMessage =
      "The server hit an internal error. Check the log for the request ID.";
    const rejected = await apiClient.post("/convert/generate", {}).catch((err) => err);
    expect(rejected).toMatchObject({ message: expectedMessage });
    expect(rejected.response?.data?.detail).toBe(expectedMessage);
    expect(postClientLog).toHaveBeenCalledWith(
      "api: request failed",
      expect.objectContaining({
        details: expect.objectContaining({
          status_code: 500,
          response_detail: {
            detail_redacted: true,
            detail_type: "string",
            detail_length: "500".length,
          },
          error_message: expectedMessage,
        }),
      }),
    );
    expect(useActionHistoryStore.getState().history.at(-1)?.error).toEqual(
      expect.objectContaining({
        status_code: 500,
        path: "/convert/generate",
        error_message: expectedMessage,
      }),
    );
  });

  it("replaces code-only backend details with readable HTTP fallbacks", async () => {
    const error = new Error("Request failed with status code 402");
    Object.assign(error, {
      config: { method: "post", url: "/convert/generate" },
      response: { status: 402, data: { detail: "HTTP error 402" } },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    const expectedMessage =
      "This action requires an available quota or payment before it can continue.";
    const rejected = await apiClient.post("/convert/generate", {}).catch((err) => err);
    expect(rejected).toMatchObject({ message: expectedMessage });
    expect(rejected.response?.data?.detail).toBe(expectedMessage);
  });

  it.each([
    {
      status: 402,
      detail: "HTTP 402 Payment Required",
      expected:
        "This action requires an available quota or payment before it can continue.",
    },
    {
      status: 422,
      detail: "Request failed with status code 422: Unprocessable Entity",
      expected: "The request is missing required data or contains invalid values.",
    },
  ])(
    "replaces status detail '$detail' with readable HTTP fallbacks",
    async ({ status, detail, expected }) => {
      const error = new Error(`Request failed with status code ${status}`);
      Object.assign(error, {
        config: { method: "post", url: "/convert/generate" },
        response: {
          status,
          data: { detail },
        },
      });
      apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

      const rejected = await apiClient.post("/convert/generate", {}).catch((err) => err);
      expect(rejected).toMatchObject({ message: expected });
      expect(rejected.response?.data?.detail).toBe(expected);
    },
  );

  it("keeps backend details where numbers are part of the real message", async () => {
    const error = new Error("Request failed with status code 422");
    Object.assign(error, {
      config: { method: "post", url: "/convert/generate" },
      response: { status: 422, data: { detail: "value must be <= 500" } },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    const rejected = await apiClient.post("/convert/generate", {}).catch((err) => err);
    expect(rejected).toMatchObject({
      message: "value must be <= 500",
    });
    expect(rejected.response?.data?.detail).toBe("value must be <= 500");
  });

  it("redacts server error details even when they mention an upstream status", async () => {
    const error = new Error("Request failed with status code 500");
    Object.assign(error, {
      config: { method: "post", url: "/convert/generate" },
      response: {
        status: 500,
        data: { detail: "upstream dependency returned status 500 while slicing" },
      },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    const rejected = await apiClient.post("/convert/generate", {}).catch((err) => err);
    const expectedMessage =
      "The server hit an internal error. Check the log for the request ID.";
    expect(rejected).toMatchObject({
      message: expectedMessage,
    });
    expect(rejected.response?.data?.detail).toBe(expectedMessage);
    expect(JSON.stringify(rejected.response?.data)).not.toContain(
      "upstream dependency returned status 500 while slicing",
    );
  });

  it("redacts top-level and structured server error messages", async () => {
    const expectedMessage =
      "The server hit an internal error. Check the log for the request ID.";
    for (const data of [
      { message: "worker crashed" },
      { detail: { message: "worker crashed", error: "worker_crashed" } },
      { detail: ["worker crashed"] },
    ]) {
      const error = new Error("Request failed with status code 500");
      Object.assign(error, {
        config: { method: "post", url: "/convert/generate" },
        response: { status: 500, data },
      });
      apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

      const rejected = await apiClient.post("/convert/generate", {}).catch((err) => err);
      expect(rejected).toMatchObject({ message: expectedMessage });
      expect(JSON.stringify(rejected.response?.data)).not.toContain("worker crashed");
      expect(JSON.stringify(vi.mocked(postClientLog).mock.calls)).not.toContain(
        "worker crashed",
      );
      vi.mocked(postClientLog).mockClear();
    }
  });

  it("still replaces generic request-failed status details", async () => {
    const error = new Error("Request failed with status code 500");
    Object.assign(error, {
      config: { method: "post", url: "/convert/generate" },
      response: {
        status: 500,
        data: { detail: "Request failed with status code 500" },
      },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(apiClient.post("/convert/generate", {})).rejects.toMatchObject({
      message: "The server hit an internal error. Check the log for the request ID.",
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

  it("normalizes bare generic HTTP errors for store-level callers", () => {
    expect(
      apiErrorToVisibleMessage(
        new Error("Request failed with status code 500"),
      ),
    ).toBe("The server hit an internal error. Check the log for the request ID.");
    expect(
      apiErrorToVisibleMessage(new Error("Request failed with status code 422")),
    ).toBe("The request is missing required data or contains invalid values.");
    expect(
      apiErrorToVisibleMessage(new Error("Vectorizer dependency missing")),
    ).toBe("Vectorizer dependency missing");
  });

  it("normalizes bare network and timeout errors for visible UI callers", () => {
    for (const error of [
      new Error("Network Error"),
      new TypeError("Failed to fetch"),
      new Error("timeout of 30000ms exceeded"),
    ]) {
      const message = apiErrorToVisibleMessage(error);
      expect(message).toBe(
        "API request failed before the server returned a response.",
      );
      expect(message).not.toMatch(/Network Error|Failed to fetch|timeout of/i);
    }
  });

  it("turns failed resource downloads into readable errors", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 404,
      headers: jsonHeaders,
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

  it("records failed resource downloads in client logs and action history", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 404,
      headers: new Headers({
        "content-type": "application/json",
        "x-request-id": "req-resource-404",
      }),
      json: () => Promise.resolve({ detail: "File not found or expired" }),
    }) as unknown as typeof fetch;

    try {
      await expect(downloadResourceBlob("/api/files/missing")).rejects.toThrow(
        "File not found or expired",
      );

      expect(postClientLog).toHaveBeenCalledWith(
        "api: request failed",
        expect.objectContaining({
          scope: "api",
          phase: "request-failed",
          method: "error",
          details: expect.objectContaining({
            method: "GET",
            url: "/api/files/missing",
            status_code: 404,
            request_id: "req-resource-404",
            error_message: "File not found or expired",
          }),
        }),
      );
      expect(useActionHistoryStore.getState().history.at(-1)?.error).toEqual(
        expect.objectContaining({
          status_code: 404,
          path: "/api/files/missing",
          request_id: "req-resource-404",
          error_message: "File not found or expired",
        }),
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("uses structured detail object messages for failed resource downloads", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 422,
      headers: jsonHeaders,
      json: () =>
        Promise.resolve({
          detail: {
            error: "preview_cache_size_limit_exceeded",
            message:
              "Estimated preview cache arrays exceed the configured limit.",
          },
        }),
    }) as unknown as typeof fetch;

    try {
      await expect(downloadResourceBlob("/api/files/preview")).rejects.toThrow(
        "Estimated preview cache arrays exceed the configured limit.",
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("turns resource download network failures into readable errors", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch")) as unknown as typeof fetch;

    try {
      let caught: unknown;
      try {
        await downloadResourceBlob("/api/files/model");
      } catch (error) {
        caught = error;
      }
      expect(caught).toBeInstanceOf(Error);
      expect((caught as Error).message).toBe(
        "API request failed before the server returned a response.",
      );
      expect((caught as Error).message).not.toContain("Failed to fetch");
      expect((caught as Error).cause).toBeInstanceOf(TypeError);
      expect(
        (caught as Error & { response?: { status: number | null } }).response
          ?.status,
      ).toBeNull();
      expect(
        (
          (caught as Error & { response?: { data: { detail?: unknown } } })
            .response?.data.detail
        ),
      ).toBe("API request failed before the server returned a response.");
      expect(
        (
          (caught as Error & { response?: { data: { url?: unknown } } })
            .response?.data.url
        ),
      ).toBe("/api/files/model");
      expect(postClientLog).toHaveBeenCalledWith(
        "api: request failed",
        expect.objectContaining({
          scope: "api",
          phase: "request-failed",
          method: "error",
          details: expect.objectContaining({
            method: "GET",
            url: "/api/files/model",
            status_code: null,
            request_id: null,
            error_message:
              "API request failed before the server returned a response.",
          }),
        }),
      );
      expect(useActionHistoryStore.getState().history).toHaveLength(0);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("turns interrupted resource body reads into readable errors", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: { get: () => "application/octet-stream" },
      blob: () =>
        Promise.reject(
          new TypeError("NetworkError when attempting to fetch resource."),
        ),
    }) as unknown as typeof fetch;

    try {
      let caught: unknown;
      try {
        await downloadResourceBlob("/api/files/model");
      } catch (error) {
        caught = error;
      }
      expect(caught).toBeInstanceOf(Error);
      expect((caught as Error).message).toBe(
        "API request failed before the server returned a response.",
      );
      expect((caught as Error).message).not.toContain("NetworkError");
      expect((caught as Error).cause).toBeInstanceOf(TypeError);
      expect(
        (caught as Error & { response?: { status: number | null } }).response
          ?.status,
      ).toBeNull();
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("redacts server error details for failed resource downloads", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 500,
      headers: jsonHeaders,
      json: () => Promise.resolve({ detail: "worker crashed" }),
    }) as unknown as typeof fetch;

    try {
      let caught: unknown;
      try {
        await downloadResourceBlob("/api/files/broken");
      } catch (error) {
        caught = error;
      }
      expect(caught).toBeInstanceOf(Error);
      expect((caught as Error).message).toBe(
        "The server hit an internal error. Check the log for the request ID.",
      );
      expect(JSON.stringify((caught as { response?: { data?: unknown } }).response?.data))
        .not.toContain("worker crashed");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("includes request ids in failed resource download server errors", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 500,
      headers: {
        get: (name: string) => {
          const normalized = name.toLowerCase();
          if (normalized === "content-type") return "application/json";
          if (normalized === "x-request-id") return "req-file-500";
          return null;
        },
      },
      json: () => Promise.resolve({ detail: "worker crashed" }),
    }) as unknown as typeof fetch;

    try {
      await expect(downloadResourceBlob("/api/files/broken")).rejects.toThrow(
        "The server hit an internal error. Request ID: req-file-500.",
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("redacts top-level server error messages for failed resource downloads", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 500,
      headers: jsonHeaders,
      json: () => Promise.resolve({ message: "worker crashed" }),
    }) as unknown as typeof fetch;

    try {
      let caught: unknown;
      try {
        await downloadResourceBlob("/api/files/broken");
      } catch (error) {
        caught = error;
      }
      expect(caught).toBeInstanceOf(Error);
      expect((caught as Error).message).toBe(
        "The server hit an internal error. Check the log for the request ID.",
      );
      expect(JSON.stringify((caught as { response?: { data?: unknown } }).response?.data))
        .not.toContain("worker crashed");
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

  it("turns resource validation network failures into readable errors", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch")) as unknown as typeof fetch;

    try {
      let caught: unknown;
      try {
        await assertResourceDownloadAvailable("/api/files/model");
      } catch (error) {
        caught = error;
      }
      expect(caught).toBeInstanceOf(Error);
      expect((caught as Error).message).toBe(
        "API request failed before the server returned a response.",
      );
      expect((caught as Error).message).not.toContain("Failed to fetch");
      expect((caught as Error).cause).toBeInstanceOf(TypeError);
      expect(
        (caught as Error & { response?: { status: number | null } }).response
          ?.status,
      ).toBeNull();
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("turns failed resource validation into readable errors", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 404,
      headers: jsonHeaders,
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
