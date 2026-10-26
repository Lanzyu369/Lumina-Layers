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

    expect(fetchCloudLutRegistryCatalog).not.toHaveBeenCalled();
  });

  it("renders cloud LUT catalog cards and installs a selected LUT", async () => {
    render(<LutCloudSyncPanel />);

    expect(await screen.findByText("Official CMYW LUT")).toBeInTheDocument();
    expect(screen.queryByText("community")).not.toBeInTheDocument();

      target: { value: "CMYW" },
    });

    await waitFor(() => {
    });
    expect(within(card).getByText("Official CMYW LUT")).toBeInTheDocument();
    expect(within(card).getByText("4-Color (CMYW)")).toBeInTheDocument();

    fireEvent.click(within(card).getByRole("button", { name: /下载到本地|download/i }));

    await waitFor(() => {
      expect(installCloudLut).toHaveBeenCalledWith(
        expect.objectContaining({
          lut_id: "lut_4c_cmyw",
          revision_id: "rev_a",
        }),
      );
    });
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

    expect(within(card).getByText("Readable LUT")).toBeInTheDocument();
    expect(installCloudLut).not.toHaveBeenCalled();
  });
});
