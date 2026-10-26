import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import LutLibraryPanel from "../components/LutLibraryPanel";
import { fetchLutDetailsCatalog, uploadLocalLut } from "../api/lut";

vi.mock("../api/lut", () => ({
  fetchLutDetails: vi.fn(),
  fetchLutDetailsCatalog: vi.fn(),
  uploadLocalLut: vi.fn(),
}));

describe("LutLibraryPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchLutDetailsCatalog).mockResolvedValue({
      groups: [
        {
          manufacturer: "Cloud",
          items: [
            {
              name: "Cloud - Simulated - local_simulated_lut",
              path: "lut-preset/Cloud/Simulated/local_simulated_lut.json",
              color_mode: "4-Color (RYBW)",
              source_kind: "legacy_lookup",
              manufacturer: "Cloud",
              material_type: "Simulated",
              manufacturer_source: "folder",
              material_source: "folder",
              search_tokens: ["cloud", "simulated", "local"],
            },
          ],
        },
        {
          manufacturer: "Custom",
          items: [
            {
              name: "Custom - uploaded_lut",
              path: "lut-preset/Custom/uploaded_lut.json",
              color_mode: "6-Color",
              source_kind: "legacy_lookup",
              manufacturer: "Custom",
              material_type: "uploaded",
              manufacturer_source: "folder",
              material_source: "folder",
              search_tokens: ["custom", "uploaded"],
            },
          ],
        },
      ],
    });
    vi.mocked(uploadLocalLut).mockResolvedValue({
      status: "ok",
      message: "LUT uploaded",
      name: "Custom - uploaded_lut",
    });
  });

    render(<LutLibraryPanel />);

    expect(await screen.findByTestId("lut-library-panel")).toBeInTheDocument();
    expect(screen.getAllByTestId("lut-library-card")).toHaveLength(2);

    fireEvent.change(screen.getByTestId("lut-library-search-input"), {
      target: { value: "simulated" },
    });

    await waitFor(() => {
      expect(screen.getAllByTestId("lut-library-card")).toHaveLength(1);
    });
    expect(within(screen.getByTestId("lut-library-card")).getByText("Cloud - Simulated - local_simulated_lut")).toBeInTheDocument();
  });

  it("imports a LUT file and refreshes the catalog", async () => {
    render(<LutLibraryPanel />);

    expect(await screen.findByTestId("lut-library-panel")).toBeInTheDocument();
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['{"color_mode":"4-Color (RYBW)","entries":[]}'], "new_lut.json", {
      type: "application/json",
    });

    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(uploadLocalLut).toHaveBeenCalledWith(file);
    });
    expect(fetchLutDetailsCatalog).toHaveBeenCalledTimes(2);
    expect(await screen.findByTestId("lut-library-success")).toHaveTextContent("LUT uploaded");
  });

  it("refreshes the details catalog before opening a library LUT", async () => {
    render(<LutLibraryPanel />);


    await waitFor(() => {
      expect(fetchLutDetailsCatalog).toHaveBeenCalledTimes(2);
    });
  });
});
