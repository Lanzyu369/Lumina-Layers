import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../client", () => ({
  default: {
    get: vi.fn(),
  },
}));

import apiClient from "../client";
import { getSettings } from "../system";

describe("system API", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("passes request options through settings reads", async () => {
    const response = { status: "success", settings: {} };
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: response });

    await expect(
      getSettings({ suppressClientLog: true }),
    ).resolves.toBe(response);

    expect(apiClient.get).toHaveBeenCalledWith("/system/settings", {
      suppressClientLog: true,
    });
  });
});
