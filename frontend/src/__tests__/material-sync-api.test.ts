import { beforeEach, describe, expect, it, vi } from "vitest";

import apiClient from "../api/client";
import {
  fetchMaterialSyncStatus,
  refreshMaterialSyncFromRegistry,
} from "../api/materialSync";

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

const mockGet = vi.mocked(apiClient.get);
const mockPost = vi.mocked(apiClient.post);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("material sync API client", () => {
  it("fetches local material sync status", async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        status: "ok",
        message: "loaded",
        schema_version: "1.0",
        index_state: "ready",
        last_sync_at: "2026-06-08T01:02:03Z",
        registries: {},
        installed_count: 1,
        installed: [],
        local_overrides_count: 0,
      },
    });

    const response = await fetchMaterialSyncStatus();

    expect(mockGet).toHaveBeenCalledWith("/material-sync/status", {
      timeout: 30_000,
    });
    expect(response.index_state).toBe("ready");
    expect(response.installed_count).toBe(1);
  });

  it("posts a read-only registry refresh request", async () => {
    mockPost.mockResolvedValueOnce({
      data: {
        status: "ok",
        message: "Installed 1 material packages; skipped 0; failed 0",
        registry_url: "https://materials.example/v1",
        channels: ["official"],
        checked_count: 1,
        installed_count: 1,
        skipped_count: 0,
        failed_count: 0,
        installed_materials: [],
        failures: [],
      },
    });

    const response = await refreshMaterialSyncFromRegistry();

    expect(mockPost).toHaveBeenCalledWith(
      "/material-sync/refresh",
      {},
      { timeout: 3_600_000 },
    );
    expect(response.installed_count).toBe(1);
  });
});
