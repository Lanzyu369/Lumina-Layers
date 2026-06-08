import { beforeEach, describe, expect, it, vi } from "vitest";

import apiClient from "../api/client";
import {
  approveMaterialRegistryPackage,
  fetchMaterialRegistryCatalog,
  fetchMaterialSyncStatus,
  installMaterialRegistryCatalogEntry,
  refreshMaterialSyncFromRegistry,
  rollbackMaterialSyncRevision,
  uploadMaterialRegistryPackage,
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
      timeout: 120_000,
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

  it("fetches the remote material catalog without installing packages", async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        schema_version: "1.0",
        channels: ["official"],
        count: 1,
        materials: [
          {
            material_id: "mat_cloud",
            revision_id: "rev_cloud",
            content_hash: "sha256:cloud",
            channel: "official",
            visibility: "official",
            local_directory: "BrandA/pla-basic",
            display: { brand: "BrandA", material_name: "PLA Basic" },
            compatibility: {},
            package_url: "/v1/packages/material.zip",
            package_sha256: "a".repeat(64),
            package_bytes: 1234,
          },
        ],
      },
    });

    const response = await fetchMaterialRegistryCatalog();

    expect(mockGet).toHaveBeenCalledWith("/material-sync/catalog", {
      timeout: 120_000,
    });
    expect(response.count).toBe(1);
    expect(response.materials[0].material_id).toBe("mat_cloud");
  });

  it("installs one selected remote material catalog entry", async () => {
    mockPost.mockResolvedValueOnce({
      data: {
        status: "ok",
        message: "Installed 1 material packages",
        installed_count: 1,
        installed_materials: [],
      },
    });

    await installMaterialRegistryCatalogEntry({
      material_id: "mat_cloud",
      revision_id: "rev_cloud",
      package_url: "/v1/packages/material.zip",
      package_sha256: "a".repeat(64),
    });

    expect(mockPost).toHaveBeenCalledWith(
      "/material-sync/install-from-registry",
      {
        material_id: "mat_cloud",
        revision_id: "rev_cloud",
        package_url: "/v1/packages/material.zip",
        package_sha256: "a".repeat(64),
      },
      { timeout: 3_600_000 },
    );
  });

  it("posts a material sync rollback request", async () => {
    mockPost.mockResolvedValueOnce({
      data: {
        status: "ok",
        message: "rolled back",
        material_id: "mat_test",
        revision_id: "rev_old",
        content_hash: "sha256:old",
        channel: "official",
        local_directory: "BrandA/pla-basic",
      },
    });

    const response = await rollbackMaterialSyncRevision("mat_test", "rev_old");

    expect(mockPost).toHaveBeenCalledWith(
      "/material-sync/rollback",
      { material_id: "mat_test", revision_id: "rev_old" },
      { timeout: 60_000 },
    );
    expect(response.revision_id).toBe("rev_old");
  });

  it("uploads a material registry package as multipart form data", async () => {
    mockPost.mockResolvedValueOnce({
      data: {
        status: "ok",
        message: "uploaded",
        channel: "pending",
        package_path: "pending/mat/rev.zip",
        package_url: "/api/material-registry/v1/packages/pending/mat/rev.zip",
        package_sha256: "abc",
        package_bytes: 10,
        materials: [],
      },
    });
    const file = new File(["zip"], "material.zip", { type: "application/zip" });

    const response = await uploadMaterialRegistryPackage(file);

    expect(mockPost).toHaveBeenCalledWith(
      "/material-registry/v1/packages/upload",
      expect.any(FormData),
      {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 3_600_000,
      },
    );
    expect(response.channel).toBe("pending");
  });

  it("approves a registry package with the official password", async () => {
    mockPost.mockResolvedValueOnce({
      data: {
        status: "ok",
        message: "approved",
        channel: "official",
        package_path: "official/mat/rev.zip",
        package_url: "/api/material-registry/v1/packages/official/mat/rev.zip",
        package_sha256: "abc",
        package_bytes: 10,
        materials: [],
      },
    });

    const response = await approveMaterialRegistryPackage(
      "pending/mat/rev.zip",
      "approve-secret",
    );

    expect(mockPost).toHaveBeenCalledWith(
      "/material-registry/v1/packages/pending/mat/rev.zip/approve",
      { official_password: "approve-secret" },
      { timeout: 60_000 },
    );
    expect(response.channel).toBe("official");
  });
});
