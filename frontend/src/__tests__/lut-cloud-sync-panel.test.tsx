import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import LutCloudSyncPanel from "../components/LutCloudSyncPanel";
import {
  fetchCloudLutRegistryCatalog,
  fetchCloudLutRegistryStatus,
  installCloudLut,
} from "../api/lut";

vi.mock("../api/lut", () => ({
  fetchCloudLutRegistryCatalog: vi.fn(),
  fetchCloudLutRegistryStatus: vi.fn(),
  installCloudLut: vi.fn(),
}));

describe("LutCloudSyncPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchCloudLutRegistryStatus).mockResolvedValue({
      configured: true,
      base_url: "https://registry.example.test",
      channels: ["official", "community"],
      installed_count: 1,
    });
    vi.mocked(fetchCloudLutRegistryCatalog).mockResolvedValue({
      configured: true,
      channels: ["official", "community"],
      total: 2,
      items: [
        {
          lut_id: "lut_4c_cmyw",
          revision_id: "rev_a",
          content_hash: "a".repeat(64),
          package_url: "/luts/lut_4c_cmyw.zip",
          package_sha256: "b".repeat(64),
          package_bytes: 2048,
          local_path: "Official/CMYW.json",
          channel: "official",
          visibility: "official",
          display: {
            name: "Official CMYW LUT",
            manufacturer: "Lumina",
          },
          compatibility: {
            color_mode: "4-Color (CMYW)",
          },
        },
        {
          lut_id: "lut_bw",
          revision_id: "rev_b",
          content_hash: "c".repeat(64),
          package_url: "/luts/lut_bw.zip",
          package_sha256: "d".repeat(64),
          package_bytes: 1024,
          local_path: "Community/BW.json",
          channel: "community",
          visibility: "community",
          display: {
            name: "BW LUT",
            manufacturer: "Lumina",
          },
          compatibility: {
            color_mode: "BW (Black & White)",
          },
        },
      ],
    });
    vi.mocked(installCloudLut).mockResolvedValue({
      lut_id: "lut_4c_cmyw",
      revision_id: "rev_a",
      content_hash: "a".repeat(64),
      package_url: "/luts/lut_4c_cmyw.zip",
      package_sha256: "b".repeat(64),
      package_bytes: 2048,
      local_path: "Official/CMYW.json",
      installed_path: "Cloud/Official/CMYW.json",
      installed_at: "2026-06-24T01:02:03Z",
    });
  });

  it("shows a clear notice when the cloud LUT registry is not configured", async () => {
    vi.mocked(fetchCloudLutRegistryStatus).mockResolvedValueOnce({
      configured: false,
      base_url: null,
      channels: ["official", "community"],
      installed_count: 0,
    });

    render(<LutCloudSyncPanel />);

    expect(await screen.findByTestId("lut-cloud-sync-panel")).toBeInTheDocument();
    expect(screen.getByTestId("lut-cloud-config-state")).toHaveTextContent(/未配置|not configured/i);
    expect(screen.getByTestId("lut-cloud-sync-notice")).toHaveTextContent(/尚未配置云端 LUT 库|not configured/i);
    expect(screen.getByTestId("lut-cloud-empty")).toHaveTextContent(/没有匹配的云端 LUT|No matching cloud LUTs/i);
    expect(fetchCloudLutRegistryCatalog).not.toHaveBeenCalled();
  });

  it("renders cloud LUT catalog cards and installs a selected LUT", async () => {
    render(<LutCloudSyncPanel />);

    expect(await screen.findByText("Official CMYW LUT")).toBeInTheDocument();
    expect(screen.getByTestId("lut-cloud-catalog-count")).toHaveTextContent("2");
    expect(screen.getByTestId("lut-cloud-installed-count")).toHaveTextContent("0");
    expect(screen.getAllByTestId("lut-cloud-official-badge")).toHaveLength(1);
    expect(screen.queryByText("community")).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId("lut-cloud-search-input"), {
      target: { value: "CMYW" },
    });

    await waitFor(() => {
      expect(screen.getAllByTestId("lut-cloud-catalog-card")).toHaveLength(1);
    });
    const card = screen.getByTestId("lut-cloud-catalog-card");
    expect(within(card).getByText("Official CMYW LUT")).toBeInTheDocument();
    expect(within(card).getByText("4-Color (CMYW)")).toBeInTheDocument();
    expect(within(card).getByText("Official/CMYW.json")).toBeInTheDocument();

    fireEvent.click(within(card).getByRole("button", { name: /下载到本地|download/i }));

    await waitFor(() => {
      expect(installCloudLut).toHaveBeenCalledWith(
        expect.objectContaining({
          lut_id: "lut_4c_cmyw",
          revision_id: "rev_a",
        }),
      );
    });
    expect(await screen.findByTestId("lut-cloud-sync-success")).toHaveTextContent(
      /LUT 已下载并安装到本地|downloaded and installed/i,
    );
  });

  it("marks a cloud LUT as installed when the matching preset exists locally", async () => {
    vi.mocked(fetchCloudLutRegistryCatalog).mockResolvedValueOnce({
      configured: true,
      channels: ["official"],
      total: 1,
      items: [
        {
          lut_id: "lut_existing",
          revision_id: "rev_existing",
          content_hash: "e".repeat(64),
          package_url: "/luts/existing.zip",
          package_sha256: "f".repeat(64),
          package_bytes: 1024,
          local_path: "Official/Test/Readable LUT.json",
          local_state: "local_available",
          local_exists: true,
          local_match_path: "Official/Test/Readable LUT.json",
          channel: "official",
          visibility: "official",
          display: {
            name: "Readable LUT",
            manufacturer: "Lumina",
          },
          compatibility: {
            color_mode: "4-Color (RYBW)",
          },
        },
      ],
    });

    render(<LutCloudSyncPanel />);

    const card = await screen.findByTestId("lut-cloud-catalog-card");
    expect(within(card).getByText("Readable LUT")).toBeInTheDocument();
    expect(screen.getByTestId("lut-cloud-state-lut_existing")).toHaveTextContent(
      /已安装|installed/i,
    );

    const button = within(card).getByRole("button", { name: /已安装|installed/i });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(installCloudLut).not.toHaveBeenCalled();
  });
});
