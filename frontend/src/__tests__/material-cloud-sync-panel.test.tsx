import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import MaterialCloudSyncPanel from "../components/MaterialCloudSyncPanel";
import {
  approveMaterialRegistryPackage,
  fetchMaterialRegistryCatalog,
  fetchMaterialSyncStatus,
  installMaterialRegistryCatalogEntry,
  rollbackMaterialSyncRevision,
  uploadMaterialRegistryPackage,
} from "../api/materialSync";

vi.mock("../api/materialSync", () => ({
  approveMaterialRegistryPackage: vi.fn(),
  fetchMaterialRegistryCatalog: vi.fn(),
  fetchMaterialSyncStatus: vi.fn(),
  installMaterialRegistryCatalogEntry: vi.fn(),
  rollbackMaterialSyncRevision: vi.fn(),
  uploadMaterialRegistryPackage: vi.fn(),
}));

describe("MaterialCloudSyncPanel", () => {
  const enterOfficialPassword = () => {
    fireEvent.change(screen.getByTestId("material-cloud-official-password-input"), {
      target: { value: "approve-secret" },
    });
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue({
      status: "ok",
      message: "Material sync status loaded",
      schema_version: "1.0",
      index_state: "ready",
      last_sync_at: "2026-06-08T01:02:03Z",
      registries: {},
      installed_count: 2,
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
        {
          material_id: "mat_update",
          revision_id: "rev_1",
          content_hash: "sha256:old",
          channel: "official",
          source: "package",
          local_directory: "BrandA/pla-pro",
          display_brand: "BrandA",
          display_name: "PLA Pro",
          installed_at: "2026-06-08T01:02:03Z",
          updated_at: "2026-06-08T01:02:03Z",
          local_exists: true,
          material_file_exists: true,
          available_revisions: ["rev_1"],
        },
      ],
      local_overrides_count: 0,
    });
    vi.mocked(fetchMaterialRegistryCatalog).mockResolvedValue({
      schema_version: "1.0",
      channels: ["official", "community"],
      count: 3,
      total_count: 3,
      offset: 0,
      limit: 50,
      materials: [
        {
          material_id: "mat_test",
          revision_id: "rev_new",
          content_hash: "sha256:new",
          channel: "official",
          visibility: "official",
          local_directory: "BrandA/pla-basic",
          display: { brand: "BrandA", material_name: "PLA Basic" },
          compatibility: {},
          package_url: "/v1/packages/mat_test/rev_new.zip",
          package_sha256: "a".repeat(64),
          package_bytes: 2048,
        },
        {
          material_id: "mat_update",
          revision_id: "rev_2",
          content_hash: "sha256:newer",
          channel: "official",
          visibility: "official",
          local_directory: "BrandA/pla-pro",
          display: { brand: "BrandA", material_name: "PLA Pro" },
          compatibility: {},
          package_url: "/v1/packages/mat_update/rev_2.zip",
          package_sha256: "b".repeat(64),
          package_bytes: 4096,
        },
        {
          material_id: "mat_cloud",
          revision_id: "rev_cloud",
          content_hash: "sha256:cloud",
          channel: "community",
          visibility: "community",
          local_directory: "BrandB/petg-silk",
          display: { brand: "BrandB", material_name: "Silk PETG", estimated_rgb: [20, 120, 220] },
          compatibility: {},
          package_url: "/v1/packages/mat_cloud/rev_cloud.zip",
          package_sha256: "c".repeat(64),
          package_bytes: 8192,
        },
      ],
    });
    vi.mocked(installMaterialRegistryCatalogEntry).mockResolvedValue({
      status: "ok",
      message: "installed",
      installed_count: 1,
      installed_materials: [],
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

  it("renders the cloud catalog and installs a selected material", async () => {
    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByTestId("material-cloud-sync-panel")).toBeInTheDocument();
    expect(screen.getByTestId("material-cloud-catalog-count")).toHaveTextContent("3");
    expect(screen.getByTestId("material-cloud-sync-installed-count")).toHaveTextContent("2");
    expect(screen.getByTestId("material-cloud-update-count")).toHaveTextContent("1");
    expect(screen.getByText("Silk PETG")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("material-cloud-search-input"), {
      target: { value: "PETG" },
    });
    await waitFor(() => {
      expect(fetchMaterialRegistryCatalog).toHaveBeenCalledWith({
        limit: 50,
        offset: 0,
        q: "PETG",
      });
    });
    await waitFor(() => {
      expect(screen.getAllByTestId("material-cloud-catalog-card")).toHaveLength(1);
    });
    expect(within(screen.getAllByTestId("material-cloud-catalog-card")[0]).getByText("Silk PETG")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /下载到本地|download/i }));

    await waitFor(() => {
      expect(installMaterialRegistryCatalogEntry).toHaveBeenCalledWith(
        {
          material_id: "mat_cloud",
          revision_id: "rev_cloud",
          package_url: "/v1/packages/mat_cloud/rev_cloud.zip",
          package_sha256: "c".repeat(64),
        }
      );
    });
    expect(fetchMaterialRegistryCatalog).toHaveBeenCalledTimes(3);
    expect(fetchMaterialSyncStatus).toHaveBeenCalledTimes(3);
  });

  it("passes the official password when reloading a protected cloud catalog", async () => {
    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByTestId("material-cloud-sync-panel")).toBeInTheDocument();
    enterOfficialPassword();
    fireEvent.click(screen.getByRole("button", { name: /刷新云端目录|refresh catalog/i }));

    await waitFor(() => {
      expect(fetchMaterialRegistryCatalog).toHaveBeenCalledWith(
        { limit: 50, offset: 0 },
        "approve-secret",
      );
    });

    fireEvent.change(screen.getByTestId("material-cloud-search-input"), {
      target: { value: "PETG" },
    });

    await waitFor(() => {
      expect(fetchMaterialRegistryCatalog).toHaveBeenCalledWith(
        { limit: 50, offset: 0, q: "PETG" },
        "approve-secret",
      );
    });
  });

  it("renders cloud catalog cards with the local material card template", async () => {
    render(<MaterialCloudSyncPanel />);

    const catalogCards = await screen.findAllByTestId("material-cloud-catalog-card");
    const plaBasicCard = catalogCards.find((card) => within(card).queryByText("PLA Basic"));
    const silkPetgCard = catalogCards.find((card) => within(card).queryByText("Silk PETG"));

    expect(plaBasicCard).toBeDefined();
    expect(silkPetgCard).toBeDefined();
    expect(within(plaBasicCard!).getByTestId("material-cloud-official-badge")).toHaveTextContent(/官方|official/i);
    expect(within(silkPetgCard!).queryByTestId("material-cloud-official-badge")).not.toBeInTheDocument();
    expect(within(silkPetgCard!).getByTestId("material-cloud-catalog-swatch")).toHaveStyle({
      backgroundColor: "rgb(20, 120, 220)",
    });
    expect(within(silkPetgCard!).getByTestId("material-cloud-brand-tag")).toHaveTextContent("BrandB");
    expect(silkPetgCard!.parentElement?.className).toContain(
      "[grid-template-columns:repeat(auto-fit,minmax(min(100%,19rem),1fr))]",
    );
    expect(within(silkPetgCard!).getAllByTestId("material-cloud-card-meta")).toHaveLength(4);
    expect(
      within(silkPetgCard!).getAllByTestId("material-cloud-card-meta")[0].parentElement?.className,
    ).not.toContain("lg:grid-cols-4");
    expect(within(silkPetgCard!).getByText("BrandB/petg-silk")).toBeInTheDocument();
    expect(within(silkPetgCard!).getByText(/内容指纹|Fingerprint/i)).toBeInTheDocument();
    expect(within(silkPetgCard!).getByText("cloud")).toBeInTheDocument();
    expect(within(silkPetgCard!).queryByText("rev_cloud")).not.toBeInTheDocument();
  });

  it("loads the cloud catalog page by page", async () => {
    vi.mocked(fetchMaterialRegistryCatalog)
      .mockResolvedValueOnce({
        schema_version: "1.0",
        channels: ["official"],
        count: 1,
        total_count: 2,
        offset: 0,
        limit: 50,
        materials: [
          {
            material_id: "mat_page_0",
            revision_id: "rev_page_0",
            content_hash: "sha256:page0",
            channel: "official",
            visibility: "official",
            local_directory: "BrandA/page-0",
            display: { brand: "BrandA", material_name: "Page Zero PLA" },
            compatibility: {},
            package_url: "/v1/packages/mat_page_0/rev_page_0.zip",
            package_sha256: "0".repeat(64),
            package_bytes: 1024,
          },
        ],
      })
      .mockResolvedValueOnce({
        schema_version: "1.0",
        channels: ["official"],
        count: 1,
        total_count: 2,
        offset: 1,
        limit: 50,
        materials: [
          {
            material_id: "mat_page_1",
            revision_id: "rev_page_1",
            content_hash: "sha256:page1",
            channel: "official",
            visibility: "official",
            local_directory: "BrandA/page-1",
            display: { brand: "BrandA", material_name: "Page One PETG" },
            compatibility: {},
            package_url: "/v1/packages/mat_page_1/rev_page_1.zip",
            package_sha256: "1".repeat(64),
            package_bytes: 2048,
          },
        ],
      });

    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByText("Page Zero PLA")).toBeInTheDocument();
    expect(fetchMaterialRegistryCatalog).toHaveBeenCalledWith({ limit: 50, offset: 0 });
    expect(screen.queryByText("Page One PETG")).not.toBeInTheDocument();

    enterOfficialPassword();
    fireEvent.click(screen.getByRole("button", { name: /加载更多|load more/i }));

    await waitFor(() => {
      expect(fetchMaterialRegistryCatalog).toHaveBeenCalledWith(
        { limit: 50, offset: 1 },
        "approve-secret",
      );
    });
    expect(await screen.findByText("Page One PETG")).toBeInTheDocument();
    expect(screen.getAllByTestId("material-cloud-catalog-card")).toHaveLength(2);
  });

  it("loads every remaining cloud catalog page when requested", async () => {
    vi.mocked(fetchMaterialRegistryCatalog)
      .mockResolvedValueOnce({
        schema_version: "1.0",
        channels: ["official"],
        count: 1,
        total_count: 3,
        offset: 0,
        limit: 50,
        materials: [
          {
            material_id: "mat_page_0",
            revision_id: "rev_page_0",
            content_hash: "sha256:page0",
            channel: "official",
            visibility: "official",
            local_directory: "BrandA/page-0",
            display: { brand: "BrandA", material_name: "Page Zero PLA" },
            compatibility: {},
            package_url: "/v1/packages/mat_page_0/rev_page_0.zip",
            package_sha256: "0".repeat(64),
            package_bytes: 1024,
          },
        ],
      })
      .mockResolvedValueOnce({
        schema_version: "1.0",
        channels: ["official"],
        count: 1,
        total_count: 3,
        offset: 1,
        limit: 50,
        materials: [
          {
            material_id: "mat_page_1",
            revision_id: "rev_page_1",
            content_hash: "sha256:page1",
            channel: "official",
            visibility: "official",
            local_directory: "BrandA/page-1",
            display: { brand: "BrandA", material_name: "Page One PETG" },
            compatibility: {},
            package_url: "/v1/packages/mat_page_1/rev_page_1.zip",
            package_sha256: "1".repeat(64),
            package_bytes: 2048,
          },
        ],
      })
      .mockResolvedValueOnce({
        schema_version: "1.0",
        channels: ["official"],
        count: 1,
        total_count: 3,
        offset: 2,
        limit: 50,
        materials: [
          {
            material_id: "mat_page_2",
            revision_id: "rev_page_2",
            content_hash: "sha256:page2",
            channel: "official",
            visibility: "official",
            local_directory: "BrandA/page-2",
            display: { brand: "BrandA", material_name: "Page Two PLA" },
            compatibility: {},
            package_url: "/v1/packages/mat_page_2/rev_page_2.zip",
            package_sha256: "2".repeat(64),
            package_bytes: 2048,
          },
        ],
      });

    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByText("Page Zero PLA")).toBeInTheDocument();
    enterOfficialPassword();
    fireEvent.click(screen.getByRole("button", { name: /加载全部|load all/i }));

    await waitFor(() => {
      expect(fetchMaterialRegistryCatalog).toHaveBeenCalledWith(
        { limit: 50, offset: 1 },
        "approve-secret",
      );
      expect(fetchMaterialRegistryCatalog).toHaveBeenCalledWith(
        { limit: 50, offset: 2 },
        "approve-secret",
      );
    });
    expect(await screen.findByText("Page Two PLA")).toBeInTheDocument();
    expect(screen.getAllByTestId("material-cloud-catalog-card")).toHaveLength(3);
  });

  it("reloads the first cloud catalog page when searching", async () => {
    vi.mocked(fetchMaterialRegistryCatalog)
      .mockResolvedValueOnce({
        schema_version: "1.0",
        channels: ["official"],
        count: 1,
        total_count: 2,
        offset: 0,
        limit: 50,
        materials: [
          {
            material_id: "mat_page_0",
            revision_id: "rev_page_0",
            content_hash: "sha256:page0",
            channel: "official",
            visibility: "official",
            local_directory: "BrandA/pla-basic",
            display: { brand: "BrandA", material_name: "PLA Basic" },
            compatibility: {},
            package_url: "/v1/packages/mat_page_0/rev_page_0.zip",
            package_sha256: "0".repeat(64),
            package_bytes: 1024,
          },
        ],
      })
      .mockResolvedValueOnce({
        schema_version: "1.0",
        channels: ["official"],
        count: 1,
        total_count: 1,
        offset: 0,
        limit: 50,
        materials: [
          {
            material_id: "mat_petg",
            revision_id: "rev_petg",
            content_hash: "sha256:petg",
            channel: "official",
            visibility: "official",
            local_directory: "BrandB/petg-silk",
            display: { brand: "BrandB", material_name: "Silk PETG" },
            compatibility: {},
            package_url: "/v1/packages/mat_petg/rev_petg.zip",
            package_sha256: "1".repeat(64),
            package_bytes: 2048,
          },
        ],
      });

    render(<MaterialCloudSyncPanel />);

    await waitFor(() => {
      expect(screen.getAllByTestId("material-cloud-catalog-card")).toHaveLength(1);
    });
    expect(within(screen.getAllByTestId("material-cloud-catalog-card")[0]).getByText("PLA Basic")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("material-cloud-search-input"), {
      target: { value: "PETG" },
    });

    await waitFor(() => {
      expect(fetchMaterialRegistryCatalog).toHaveBeenCalledWith({
        limit: 50,
        offset: 0,
        q: "PETG",
      });
    });
    await waitFor(() => {
      expect(screen.getAllByTestId("material-cloud-catalog-card")).toHaveLength(1);
    });
    const searchCard = screen.getAllByTestId("material-cloud-catalog-card")[0];
    expect(within(searchCard).getByText("Silk PETG")).toBeInTheDocument();
    expect(within(searchCard).queryByText("PLA Basic")).not.toBeInTheDocument();
  });

  it("updates an installed material when the catalog revision is newer", async () => {
    render(<MaterialCloudSyncPanel />);

    expect((await screen.findAllByText("PLA Pro")).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /更新到 newer|update to newer/i }));

    await waitFor(() => {
      expect(installMaterialRegistryCatalogEntry).toHaveBeenCalledWith(
        {
          material_id: "mat_update",
          revision_id: "rev_2",
          package_url: "/v1/packages/mat_update/rev_2.zip",
          package_sha256: "b".repeat(64),
        },
      );
    });
  });

  it("does not count locally available historical catalog revisions as updates", async () => {
    vi.mocked(fetchMaterialRegistryCatalog).mockResolvedValue({
      schema_version: "1.0",
      channels: ["official", "community"],
      count: 3,
      total_count: 3,
      offset: 0,
      limit: 50,
      materials: [
        {
          material_id: "mat_test",
          revision_id: "rev_old",
          content_hash: "sha256:old",
          channel: "official",
          visibility: "official",
          local_directory: "BrandA/pla-basic",
          display: { brand: "BrandA", material_name: "PLA Basic" },
          compatibility: {},
          package_url: "/v1/packages/mat_test/rev_old.zip",
          package_sha256: "d".repeat(64),
          package_bytes: 2048,
        },
        {
          material_id: "mat_update",
          revision_id: "rev_2",
          content_hash: "sha256:newer",
          channel: "official",
          visibility: "official",
          local_directory: "BrandA/pla-pro",
          display: { brand: "BrandA", material_name: "PLA Pro" },
          compatibility: {},
          package_url: "/v1/packages/mat_update/rev_2.zip",
          package_sha256: "b".repeat(64),
          package_bytes: 4096,
        },
        {
          material_id: "mat_cloud",
          revision_id: "rev_cloud",
          content_hash: "sha256:cloud",
          channel: "community",
          visibility: "community",
          local_directory: "BrandB/petg-silk",
          display: { brand: "BrandB", material_name: "Silk PETG" },
          compatibility: {},
          package_url: "/v1/packages/mat_cloud/rev_cloud.zip",
          package_sha256: "c".repeat(64),
          package_bytes: 8192,
        },
      ],
    });

    render(<MaterialCloudSyncPanel />);

    expect((await screen.findAllByText("PLA Basic")).length).toBeGreaterThan(0);
    expect(screen.getByTestId("material-cloud-update-count")).toHaveTextContent("1");
    expect(screen.getByTestId("material-cloud-state-mat_test")).not.toHaveTextContent(/有新版本|update available/i);
    expect(screen.queryByRole("button", { name: /更新到 old|update to old/i })).not.toBeInTheDocument();
    enterOfficialPassword();
    expect(screen.getByRole("button", { name: /更新到 newer|update to newer/i })).toBeInTheDocument();
  });

  it("treats matching local directory and content hash as installed when material ids differ", async () => {
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
          material_id: "mat_local_identity",
          revision_id: "rev_local",
          content_hash: "sha256:exact",
          channel: "local",
          source: "local",
          local_directory: "BrandC/pla-local",
          display_brand: "BrandC",
          display_name: "PLA Local",
          installed_at: null,
          updated_at: null,
          local_exists: true,
          material_file_exists: true,
          available_revisions: ["rev_local"],
        },
      ],
      local_overrides_count: 0,
    });
    vi.mocked(fetchMaterialRegistryCatalog).mockResolvedValue({
      schema_version: "1.0",
      channels: ["official"],
      count: 1,
      total_count: 1,
      offset: 0,
      limit: 50,
      materials: [
        {
          material_id: "mat_cloud_identity",
          revision_id: "rev_cloud",
          content_hash: "sha256:exact",
          channel: "official",
          visibility: "official",
          local_directory: "BrandC/pla-local",
          display: { brand: "BrandC", material_name: "PLA Local" },
          compatibility: {},
          package_url: "/v1/packages/mat_cloud_identity/rev_cloud.zip",
          package_sha256: "d".repeat(64),
          package_bytes: 8192,
        },
      ],
    });

    render(<MaterialCloudSyncPanel />);

    expect((await screen.findAllByText("PLA Local")).length).toBeGreaterThan(0);
    expect(screen.getByTestId("material-cloud-sync-installed-count")).toHaveTextContent("1");
    expect(screen.getByTestId("material-cloud-update-count")).toHaveTextContent("0");
    expect(screen.getByTestId("material-cloud-state-mat_cloud_identity")).toHaveTextContent(/已安装|installed/i);
    expect(
      screen.getAllByRole("button", { name: /已安装|installed/i }).some((button) => button.hasAttribute("disabled")),
    ).toBe(true);
    expect(screen.queryByTestId("material-cloud-local-installed-card")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /下载到本地|download/i })).not.toBeInTheDocument();
  });

  it("does not render missing sync-index entries as local installed cards", async () => {
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue({
      status: "ok",
      message: "Material sync status loaded",
      schema_version: "1.0",
      index_state: "ready",
      last_sync_at: "2026-06-08T01:02:03Z",
      registries: {},
      installed_count: 0,
      installed: [
        {
          material_id: "mat_missing",
          revision_id: "rev_missing",
          content_hash: "sha256:missing",
          channel: "official",
          source: "package",
          local_directory: "BrandD/missing",
          display_brand: "BrandD",
          display_name: "Missing PLA",
          installed_at: "2026-06-08T01:02:03Z",
          updated_at: "2026-06-08T01:02:03Z",
          local_exists: false,
          material_file_exists: false,
          available_revisions: ["rev_missing"],
        },
      ],
      local_overrides_count: 0,
    });
    vi.mocked(fetchMaterialRegistryCatalog).mockResolvedValue({
      schema_version: "1.0",
      channels: ["official"],
      count: 0,
      total_count: 0,
      offset: 0,
      limit: 50,
      materials: [],
    });

    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByTestId("material-cloud-sync-panel")).toBeInTheDocument();
    expect(screen.getByTestId("material-cloud-sync-installed-count")).toHaveTextContent("0");
    expect(screen.queryByTestId("material-cloud-local-installed-card")).not.toBeInTheDocument();
    expect(screen.queryByText("Missing PLA")).not.toBeInTheDocument();
  });

  it("rolls back from the local installed section when catalog search hides the card", async () => {
    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByTestId("material-cloud-sync-panel")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("material-cloud-search-input"), {
      target: { value: "Silk" },
    });

    await waitFor(() => {
      expect(screen.getAllByTestId("material-cloud-catalog-card")).toHaveLength(1);
    });
    expect(within(screen.getAllByTestId("material-cloud-catalog-card")[0]).getByText("Silk PETG")).toBeInTheDocument();

    enterOfficialPassword();
    fireEvent.click(screen.getByRole("button", { name: /回滚到 rev_old|rollback to rev_old/i }));

    await waitFor(() => {
      expect(rollbackMaterialSyncRevision).toHaveBeenCalledWith(
        "mat_test",
        "rev_old",
        "approve-secret",
      );
    });
  });

  it("keeps local rollback controls available when catalog loading fails", async () => {
    vi.mocked(fetchMaterialRegistryCatalog).mockRejectedValue(new Error("catalog unavailable"));

    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByTestId("material-cloud-sync-error")).toHaveTextContent("catalog unavailable");

    enterOfficialPassword();
    fireEvent.click(screen.getByRole("button", { name: /回滚到 rev_old|rollback to rev_old/i }));

    await waitFor(() => {
      expect(rollbackMaterialSyncRevision).toHaveBeenCalledWith(
        "mat_test",
        "rev_old",
        "approve-secret",
      );
    });
  });

  it("renders installed catalog status and rolls back a previous revision", async () => {
    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByTestId("material-cloud-sync-panel")).toBeInTheDocument();
    expect(screen.getAllByText("PLA Basic").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("material-cloud-filter-official")).not.toBeInTheDocument();
    expect(screen.getByTestId("material-cloud-sync-installed-count")).toHaveTextContent("2");
    expect(
      screen.getAllByRole("button", { name: /已安装|installed/i }).some((button) => button.hasAttribute("disabled")),
    ).toBe(true);

    expect(screen.getByRole("button", {
      name: /回滚到 rev_old|rollback to rev_old/i,
    })).toBeDisabled();

    enterOfficialPassword();
    fireEvent.click(screen.getByRole("button", { name: /回滚到 rev_old|rollback to rev_old/i }));

    await waitFor(() => {
      expect(rollbackMaterialSyncRevision).toHaveBeenCalledWith(
        "mat_test",
        "rev_old",
        "approve-secret",
      );
    });
    expect(fetchMaterialSyncStatus).toHaveBeenCalledTimes(2);
    expect(fetchMaterialRegistryCatalog).toHaveBeenCalledTimes(2);
  });

  it("uploads a package and approves it with the official password", async () => {
    render(<MaterialCloudSyncPanel />);

    await screen.findByTestId("material-cloud-sync-panel");
    expect(screen.getByRole("button", { name: /上传耗材包|upload material package/i })).toBeDisabled();

    fireEvent.change(screen.getByTestId("material-cloud-official-password-input"), {
      target: { value: "approve-secret" },
    });

    const file = new File(["zip"], "material.zip", { type: "application/zip" });
    fireEvent.change(screen.getByTestId("material-cloud-upload-input"), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(uploadMaterialRegistryPackage).toHaveBeenCalledWith(file, "approve-secret");
    });
    expect(screen.getByText("pending/mat_test/rev_new.zip")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /批准为官方耗材|approve as official/i }));

    await waitFor(() => {
      expect(approveMaterialRegistryPackage).toHaveBeenCalledWith(
        "pending/mat_test/rev_new.zip",
        "approve-secret",
      );
    });
  });

  it("approves selected existing cloud catalog entries as official", async () => {
    render(<MaterialCloudSyncPanel />);

    const catalogCards = await screen.findAllByTestId("material-cloud-catalog-card");
    const silkPetgCard = catalogCards.find((card) => within(card).queryByText("Silk PETG"));
    expect(silkPetgCard).toBeDefined();

    fireEvent.change(screen.getByTestId("material-cloud-official-password-input"), {
      target: { value: "approve-secret" },
    });
    fireEvent.click(
      within(silkPetgCard!).getByRole("checkbox", { name: /选择云端耗材.*Silk PETG|select cloud material.*Silk PETG/i }),
    );
    fireEvent.click(screen.getByRole("button", { name: /批准选中云端耗材为官方|approve selected cloud materials/i }));

    await waitFor(() => {
      expect(approveMaterialRegistryPackage).toHaveBeenCalledWith(
        "mat_cloud/rev_cloud.zip",
        "approve-secret",
      );
    });
  });
});
