import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import MaterialLibraryPanel from "../components/MaterialLibraryPanel";
import {
  deleteGradientCardMaterial,
  exportGradientCardMaterials,
  importGradientCardMaterials,
  listGradientCardMaterials,
} from "../api/extractor";
import { useSingleStageStore } from "../stores/singleStageStore";
import { useWidgetStore } from "../stores/widgetStore";

vi.mock("../api/extractor", () => ({
  deleteGradientCardMaterial: vi.fn(),
  exportGradientCardMaterials: vi.fn(),
  importGradientCardMaterials: vi.fn(),
  listGradientCardMaterials: vi.fn(),
}));

describe("MaterialLibraryPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWidgetStore.setState({ activeTab: "material-library" });
    useSingleStageStore.setState({
      materialName: "",
      verificationTargetDirectoryName: null,
      verificationTargetCount: 0,
    });
  });

  it("renders saved materials from the material library API", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          archive_path: "materials/pla-basic/material.json",
          stage_a_params_path: "materials/pla-basic/stage_A_parameters.json",
          material_file_url: "/api/files/material-json",
          stage_a_params_url: "/api/files/stage-a-json",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
          verification_history: [
            {
              verification_index: 1,
              captured_at: "2026-04-16T10:00:00Z",
              mean_delta_e: 1.5,
              rmse_linear: 0.015,
              estimated_rgb: [96, 112, 132],
              estimated_k: [1.1, 1.2, 1.3],
              e_values: [0.21, 0.31, 0.41],
              k_values: [1.1, 1.2, 1.3],
              white_c0_values: [0.91, 0.92, 0.93],
              black_c0_values: [0.11, 0.12, 0.13],
              white_detected_orientation: "identity",
              black_detected_orientation: "rotate_90_cw",
            },
          ],
        },
      ],
    });

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("material-library-panel")).toBeInTheDocument();
    });

    expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    expect(screen.getAllByRole("link")).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ href: expect.stringContaining("/api/files/material-json") }),
        expect.objectContaining({ href: expect.stringContaining("/api/files/stage-a-json") }),
      ]),
    );
    expect(screen.getAllByTestId("material-library-item")).toHaveLength(1);
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("expands saved material verification history details", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          archive_path: "materials/pla-basic/material.json",
          stage_a_params_path: "materials/pla-basic/stage_A_parameters.json",
          material_file_url: "/api/files/material-json",
          stage_a_params_url: "/api/files/stage-a-json",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
          verification_history: [
            {
              verification_index: 1,
              captured_at: "2026-04-16T10:00:00Z",
              mean_delta_e: 1.5,
              rmse_linear: 0.015,
              estimated_rgb: [96, 112, 132],
              estimated_k: [1.1, 1.2, 1.3],
              e_values: [0.21, 0.31, 0.41],
              k_values: [1.1, 1.2, 1.3],
              white_c0_values: [0.91, 0.92, 0.93],
              black_c0_values: [0.11, 0.12, 0.13],
              white_detected_orientation: "identity",
              black_detected_orientation: "rotate_90_cw",
            },
          ],
        },
      ],
    });

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /展开验证历史|show verification history/i }));

    expect(screen.getByTestId("material-library-history-pla-basic")).toBeInTheDocument();
    expect(screen.getByText(/第 1 次验证|Run 1/i)).toBeInTheDocument();
    expect(screen.getByText("0.0150")).toBeInTheDocument();
    expect(screen.getByText(/0.210, 0.310, 0.410/)).toBeInTheDocument();
    expect(screen.getByText(/White identity \/ Black rotate_90_cw|白底 identity \/ 黑底 rotate_90_cw/i)).toBeInTheDocument();
  });

  it("starts material re-verification and routes back to the extract tab", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          archive_path: "materials/pla-basic/material.json",
          stage_a_params_path: "materials/pla-basic/stage_A_parameters.json",
          material_file_url: "/api/files/material-json",
          stage_a_params_url: "/api/files/stage-a-json",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
      ],
    });

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /再次验证|re-verify/i }));

    expect(useWidgetStore.getState().activeTab).toBe("gradient-card-extract");
    expect(useSingleStageStore.getState().materialName).toBe("PLA Basic");
    expect(useSingleStageStore.getState().verificationTargetDirectoryName).toBe("pla-basic");
    expect(useSingleStageStore.getState().verificationTargetCount).toBe(3);
  });

  it("deletes a saved material from the library after confirmation", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          archive_path: "materials/pla-basic/material.json",
          stage_a_params_path: "materials/pla-basic/stage_A_parameters.json",
          material_file_url: "/api/files/material-json",
          stage_a_params_url: "/api/files/stage-a-json",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
      ],
    });
    vi.mocked(deleteGradientCardMaterial).mockResolvedValue({
      status: "ok",
      message: "deleted",
      directory_name: "pla-basic",
      material_name: "PLA Basic",
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /删除耗材|delete material/i }));

    await waitFor(() => {
      expect(deleteGradientCardMaterial).toHaveBeenCalledWith("pla-basic");
    });
    expect(screen.queryByText("PLA Basic")).not.toBeInTheDocument();
  });

  it("shows the empty state when no materials exist", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 0 saved materials",
      materials: [],
    });

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(
        screen.getByText(/还没有已保存的耗材档案|No saved material archives yet/i),
      ).toBeInTheDocument();
    });
  });

  it("exports selected materials as one ZIP archive", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          archive_path: "materials/pla-basic/material.json",
          stage_a_params_path: "materials/pla-basic/stage_A_parameters.json",
          material_file_url: "/api/files/material-json",
          stage_a_params_url: "/api/files/stage-a-json",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
      ],
    });
    vi.mocked(exportGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Exported 1 saved materials",
      download_url: "/api/files/material-export",
      filename: "materials.zip",
      exported_count: 1,
      exported_directory_names: ["pla-basic"],
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("material-library-select-pla-basic"));
    fireEvent.click(screen.getByRole("button", { name: /导出所选耗材|export selected/i }));

    await waitFor(() => {
      expect(exportGradientCardMaterials).toHaveBeenCalledWith(["pla-basic"]);
    });
    expect(screen.getByTestId("material-library-success")).toBeInTheDocument();
  });

  it("imports multiple ZIP archives and selects newly imported materials", async () => {
    vi.mocked(listGradientCardMaterials)
      .mockResolvedValueOnce({
        status: "ok",
        message: "Loaded 0 saved materials",
        materials: [],
      })
      .mockResolvedValueOnce({
        status: "ok",
        message: "Loaded 1 saved materials",
        materials: [
          {
            material_name: "PLA Basic",
            directory_name: "pla-basic",
            created_at: "2026-04-16T10:00:00Z",
            updated_at: "2026-04-16T11:00:00Z",
            archive_path: "materials/pla-basic/material.json",
            stage_a_params_path: "materials/pla-basic/stage_A_parameters.json",
            material_file_url: "/api/files/material-json",
            stage_a_params_url: "/api/files/stage-a-json",
            estimated_rgb: [100, 120, 140],
            layer_height_mm: 0.04,
            mean_delta_e: 1.23,
            verification_count: 3,
          },
        ],
      });
    vi.mocked(importGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Imported 1 saved materials",
      imported_count: 1,
      imported_materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          brand: null,
          archive_path: "materials/pla-basic/material.json",
          stage_a_params_path: "materials/pla-basic/stage_A_parameters.json",
          verification_count: 3,
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
        },
      ],
    });

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByText(/还没有已保存的耗材档案|No saved material archives yet/i)).toBeInTheDocument();
    });

    const importInput = screen.getByTestId("material-library-import-input");
    const zipA = new File(["zip-a"], "materials-a.zip", { type: "application/zip" });
    const zipB = new File(["zip-b"], "materials-b.zip", { type: "application/zip" });
    fireEvent.change(importInput, { target: { files: [zipA, zipB] } });

    await waitFor(() => {
      expect(importGradientCardMaterials).toHaveBeenCalledWith([zipA, zipB]);
    });
    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });
    expect(screen.getByTestId("material-library-success")).toBeInTheDocument();
    expect((screen.getByTestId("material-library-select-pla-basic") as HTMLInputElement).checked).toBe(true);
  });
});
