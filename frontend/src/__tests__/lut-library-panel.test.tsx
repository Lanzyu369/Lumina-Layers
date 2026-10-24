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
    localStorage.removeItem("lut-library-pins");
    localStorage.removeItem("lut-library-order");
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

  it("renders a searchable grouped library and restores collapsed state", async () => {
    render(<LutLibraryPanel />);

    expect(await screen.findByTestId("lut-library-panel")).toBeInTheDocument();
    await screen.findByText("2个 LUT · 2个品牌");
    expect(screen.queryByTestId("lut-library-card")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "全部展开" }));
    expect(screen.getAllByTestId("lut-library-card")).toHaveLength(2);

    fireEvent.change(screen.getByTestId("lut-library-search-input"), {
      target: { value: "simulated" },
    });

    await waitFor(() => {
      expect(screen.getAllByTestId("lut-library-card")).toHaveLength(1);
    });
    expect(within(screen.getByTestId("lut-library-card")).getByText("Cloud - Simulated - local_simulated_lut")).toBeInTheDocument();
    expect(screen.getByText("1个 LUT · 1个品牌")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("lut-library-search-input"), { target: { value: "" } });
    expect(screen.getAllByTestId("lut-library-card")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "全部收起" }));
    fireEvent.change(screen.getByTestId("lut-library-search-input"), { target: { value: "6-color" } });
    expect(screen.getAllByTestId("lut-library-card")).toHaveLength(1);
    fireEvent.change(screen.getByTestId("lut-library-search-input"), { target: { value: "" } });
    expect(screen.queryByTestId("lut-library-card")).not.toBeInTheDocument();

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

  it("remembers pinned groups and their order and keeps detail switching in the library", async () => {
    const view = render(<LutLibraryPanel />);
    await screen.findByText("2个 LUT · 2个品牌");
    fireEvent.click(screen.getByRole("button", { name: "固定展开 Custom" }));
    fireEvent.keyDown(screen.getByRole("button", { name: /Custom.*1/ }), { key: "ArrowUp" });
    expect(screen.getAllByTestId("lut-library-brand-group")[0]).toHaveAttribute("data-brand", "Custom");
    fireEvent.click(screen.getByRole("button", { name: "全部收起" }));
    view.unmount();
    render(<LutLibraryPanel />);
    await screen.findByText("2个 LUT · 2个品牌");
    expect(screen.getAllByTestId("lut-library-brand-group")[0]).toHaveAttribute("data-brand", "Custom");
    expect(screen.getAllByTestId("lut-library-card")).toHaveLength(1);
    const card = screen.getByTestId("lut-library-card");
    fireEvent.click(card);
    expect(screen.getByTestId("lut-library-details")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByTestId("lut-library-details"), { key: "Escape" });
    expect(screen.queryByTestId("lut-library-details")).not.toBeInTheDocument();
    expect(card).toHaveFocus();
  });

  it("refreshes the details catalog before opening a library LUT", async () => {
    render(<LutLibraryPanel />);

    await screen.findByText("2个 LUT · 2个品牌");
    fireEvent.click(screen.getByRole("button", { name: "全部展开" }));
    const [card] = screen.getAllByTestId("lut-library-card");
    fireEvent.click(card);
    const details = screen.getByTestId("lut-library-details");
    expect(within(details).getByText("lut-preset/Cloud/Simulated/local_simulated_lut.json")).toBeInTheDocument();
    expect(fetchLutDetailsCatalog).toHaveBeenCalledTimes(1);
    fireEvent.click(within(details).getByRole("button", { name: "查看完整 LUT 分析" }));

    await waitFor(() => {
      expect(fetchLutDetailsCatalog).toHaveBeenCalledTimes(2);
    });
  });
});
