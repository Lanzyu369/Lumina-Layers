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

  it("opens details without installing and keeps search available without comparison tabs", async () => {
    render(<LutCloudSyncPanel />);
    const card = await screen.findByRole("button", { name: /Official CMYW LUT/ });
    fireEvent.click(card);
    expect(installCloudLut).not.toHaveBeenCalled();
    expect(screen.queryByText("Official/CMYW.json")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /关闭|Close/i })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("button", { name: /关闭|Close/i }), { key: "Escape" });
    expect(card).toHaveFocus();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "BW LUT" } });
    expect(screen.queryByRole("button", { name: /Official CMYW LUT/ })).not.toBeInTheDocument();
    expect(screen.getByRole("searchbox")).toHaveValue("BW LUT");
    expect(screen.getByRole("searchbox")).toHaveValue("BW LUT");
  });

  it("loads remaining catalog pages in the new view so search finds later entries", async () => {
    const baseline = await fetchCloudLutRegistryCatalog();
    vi.mocked(fetchCloudLutRegistryCatalog).mockClear();
    vi.mocked(fetchCloudLutRegistryCatalog)
      .mockResolvedValueOnce({ ...baseline, total: 2, items: [baseline.items[0]] })
      .mockResolvedValueOnce({ ...baseline, total: 2, items: [baseline.items[1]] });
    render(<LutCloudSyncPanel />);
    await waitFor(() => expect(fetchCloudLutRegistryCatalog).toHaveBeenCalledWith(expect.objectContaining({ offset: 1 })));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "BW LUT" } });
    expect(await screen.findByRole("button", { name: /BW LUT/ })).toBeInTheDocument();
  });

  it("shows a clear notice when the cloud LUT registry is not configured", async () => {
    vi.mocked(fetchCloudLutRegistryStatus).mockResolvedValueOnce({
      configured: false,
      base_url: null,
      channels: ["official", "community"],
      installed_count: 0,
    });

    render(<LutCloudSyncPanel />);

    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(await screen.findByText(/尚未配置云端 LUT 库|not configured/i)).toHaveTextContent(/尚未配置云端 LUT 库|not configured/i);
    expect(screen.getByText(/没有匹配的云端 LUT|No matching cloud LUTs/i)).toHaveTextContent(/没有匹配的云端 LUT|No matching cloud LUTs/i);
    expect(fetchCloudLutRegistryCatalog).not.toHaveBeenCalled();
  });

  it("renders cloud LUT catalog cards and installs a selected LUT", async () => {
    render(<LutCloudSyncPanel />);

    expect(await screen.findByText("Official CMYW LUT")).toBeInTheDocument();
    expect(screen.queryByText("community")).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "CMYW" },
    });

    await waitFor(() => {
      expect(screen.getAllByRole("article")).toHaveLength(1);
    });
    const card = screen.getByRole("article");
    expect(within(card).getByText("Official CMYW LUT")).toBeInTheDocument();
    expect(within(card).getByText("4-Color (CMYW)")).toBeInTheDocument();
    expect(within(card).queryByText("Official/CMYW.json")).not.toBeInTheDocument();

    fireEvent.click(within(card).getByRole("button", { name: /下载到本地|download/i }));

    await waitFor(() => {
      expect(installCloudLut).toHaveBeenCalledWith(
        expect.objectContaining({
          lut_id: "lut_4c_cmyw",
          revision_id: "rev_a",
        }),
      );
    });
    expect(await screen.findByText(/LUT 已下载并安装到本地|downloaded and installed/i)).toHaveTextContent(
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
          local_match_path: "Cloud/Actual/Readable LUT.json",
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

    const card = await screen.findByRole("article");
    expect(within(card).getByText("Readable LUT")).toBeInTheDocument();
    expect(card).toHaveTextContent(/已安装|installed/i);
    expect(within(card).queryByRole("button", { name: /下载到本地|download/i })).not.toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: /Readable LUT/ }));
    expect(screen.getByText("Cloud/Actual/Readable LUT.json")).toBeInTheDocument();
    expect(screen.queryByText("Official/Test/Readable LUT.json")).not.toBeInTheDocument();
    expect(installCloudLut).not.toHaveBeenCalled();
  });
});
