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
import apiClient from "../client";

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
      message: "Server temporarily unavailable. Please try again later. (HTTP 503)",
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
        "This action requires an available quota or payment before it can continue. (HTTP 402)",
    });
  });
});
