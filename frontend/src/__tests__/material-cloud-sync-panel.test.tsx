import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import MaterialCloudSyncPanel from "../components/MaterialCloudSyncPanel";
import {
  approveMaterialRegistryPackage,
  fetchMaterialSyncStatus,
  refreshMaterialSyncFromRegistry,
  rollbackMaterialSyncRevision,
  uploadMaterialRegistryPackage,
} from "../api/materialSync";

vi.mock("../api/materialSync", () => ({
  approveMaterialRegistryPackage: vi.fn(),
  fetchMaterialSyncStatus: vi.fn(),
  refreshMaterialSyncFromRegistry: vi.fn(),
  rollbackMaterialSyncRevision: vi.fn(),
  uploadMaterialRegistryPackage: vi.fn(),
}));

describe("MaterialCloudSyncPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue({
      status: "ok",
      message: "Material sync status loaded",
      schema_version: "1.0",
      index_state: "ready",
      last_sync_at: "2026-06-08T01:02:03Z",
      registries: {},
      installed_count: 1,
      installed: [
        {
          material_id: "mat_test",
          revision_id: "rev_new",
          content_hash: "sha256:new",
          channel: "official",
          source: "package",
          local_directory: "BrandA/pla-basic",
          display_brand: "BrandA",
          display_name: "PLA Basic",
          installed_at: "2026-06-08T01:02:03Z",
          updated_at: "2026-06-08T01:02:03Z",
          local_exists: true,
          material_file_exists: true,
          available_revisions: ["rev_old", "rev_new"],
        },
      ],
      local_overrides_count: 0,
    });
    vi.mocked(refreshMaterialSyncFromRegistry).mockResolvedValue({
      status: "ok",
      message: "Installed 0 material packages; skipped 1; failed 0",
      registry_url: "https://materials.example/v1",
      channels: ["official"],
      checked_count: 1,
      installed_count: 0,
      skipped_count: 1,
      failed_count: 0,
      installed_materials: [],
      failures: [],
    });
    vi.mocked(rollbackMaterialSyncRevision).mockResolvedValue({
      status: "ok",
      message: "rolled back",
      material_id: "mat_test",
      revision_id: "rev_old",
      content_hash: "sha256:old",
      channel: "official",
      local_directory: "BrandA/pla-basic",
    });
    vi.mocked(uploadMaterialRegistryPackage).mockResolvedValue({
      status: "ok",
      message: "uploaded",
      channel: "pending",
      package_path: "pending/mat_test/rev_new.zip",
      package_url: "/api/material-registry/v1/packages/pending/mat_test/rev_new.zip",
      package_sha256: "abc",
      package_bytes: 100,
      materials: [],
    });
    vi.mocked(approveMaterialRegistryPackage).mockResolvedValue({
      status: "ok",
      message: "approved",
      channel: "official",
      package_path: "official/mat_test/rev_new.zip",
      package_url: "/api/material-registry/v1/packages/official/mat_test/rev_new.zip",
      package_sha256: "abc",
      package_bytes: 100,
      materials: [],
    });
  });

  it("renders cloud sync status and rolls back a previous revision", async () => {
    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByTestId("material-cloud-sync-panel")).toBeInTheDocument();
    expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    expect(screen.getByTestId("material-cloud-official-badge")).toBeInTheDocument();
    expect(screen.getByTestId("material-cloud-sync-installed-count")).toHaveTextContent("1");

    fireEvent.click(screen.getByRole("button", { name: /回滚到 rev_old|rollback to rev_old/i }));

    await waitFor(() => {
      expect(rollbackMaterialSyncRevision).toHaveBeenCalledWith("mat_test", "rev_old");
    });
    expect(fetchMaterialSyncStatus).toHaveBeenCalledTimes(2);
  });

  it("uploads a package and approves it with the official password", async () => {
    render(<MaterialCloudSyncPanel />);

    await screen.findByTestId("material-cloud-sync-panel");
    const file = new File(["zip"], "material.zip", { type: "application/zip" });
    fireEvent.change(screen.getByTestId("material-cloud-upload-input"), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(uploadMaterialRegistryPackage).toHaveBeenCalledWith(file);
    });
    expect(screen.getByText("pending/mat_test/rev_new.zip")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("material-cloud-official-password-input"), {
      target: { value: "approve-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: /批准为官方耗材|approve as official/i }));

    await waitFor(() => {
      expect(approveMaterialRegistryPackage).toHaveBeenCalledWith(
        "pending/mat_test/rev_new.zip",
        "approve-secret",
      );
    });
  });
});
