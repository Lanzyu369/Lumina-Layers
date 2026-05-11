import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../utils/clientLog", () => ({
  postClientLog: vi.fn(),
  summarizeErrorForLog: (error: unknown) => ({
    error_message: error instanceof Error ? error.message : String(error),
  }),
}));

import { postClientLog } from "../../utils/clientLog";
import apiClient from "../client";

describe("apiClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    apiClient.defaults.adapter = undefined;
  });

  it("records failed API responses in the client log buffer", async () => {
    const error = new Error("Request failed");
    Object.assign(error, {
      config: { method: "post", url: "/convert/generate" },
      response: { status: 500, data: { detail: "worker crashed" } },
    });
    apiClient.defaults.adapter = vi.fn().mockRejectedValueOnce(error);

    await expect(apiClient.post("/convert/generate", {})).rejects.toBe(error);

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
          response_detail: { detail: "worker crashed" },
          error_message: "Request failed",
        }),
      }),
    );
  });
});
