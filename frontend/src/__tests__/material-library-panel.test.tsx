import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import MaterialLibraryPanel from "../components/MaterialLibraryPanel";
import {
  deleteGradientCardMaterial,
  exportGradientCardMaterials,
  importGradientCardMaterials,
  listGradientCardMaterials,
  updateGradientCardMaterial,
} from "../api/extractor";
import { useSingleStageStore } from "../stores/singleStageStore";
import { useWidgetStore } from "../stores/widgetStore";
import { useLuminaBoxMaterialNavigation } from "../stores/luminaBoxMaterialNavigation";

vi.mock("../api/extractor", () => ({
  colorcheckerConfirm: vi.fn(),
  colorcheckerRelease: vi.fn(),
  colorcheckerTouch: vi.fn(() => Promise.resolve()),
  deleteGradientCardMaterial: vi.fn(),
  exportGradientCardMaterials: vi.fn(),
  importGradientCardMaterials: vi.fn(),
  listGradientCardMaterials: vi.fn(),
  updateGradientCardMaterial: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("MaterialLibraryPanel", () => {
  const expandAllMaterialLibraryGroups = () => {
    for (const toggle of screen.getAllByTestId("material-library-brand-group-toggle")) {
      if (toggle.getAttribute("aria-expanded") === "false") {
        fireEvent.click(toggle);
      }
    }
  };

  beforeEach(() => {
    vi.clearAllMocks();
    useLuminaBoxMaterialNavigation.setState({ libraryProfileKind: "stage_a", captureRequest: null, lastCaptureArchive: null });
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
          sync_material_id: "mat_official",
          sync_revision_id: "rev_official",
          sync_channel: "official",
          sync_official: true,
        },
      ],
    });

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("material-library-panel")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByTestId("material-library-brand-group-toggle")).toHaveAttribute("aria-expanded", "false");
    });
    expect(screen.queryByText("PLA Basic")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("material-library-brand-group-toggle"));
    expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    expect(screen.queryByText(/下载 material\.json|download material\.json/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/下载 stage_A_parameters\.json|download stage_a_parameters\.json/i)).not.toBeInTheDocument();
    expect(screen.getAllByTestId("material-library-item")).toHaveLength(1);
    expect(screen.getByTestId("material-library-official-badge")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("manages current Box archives and resumes their original material collection", async () => {
    const item = { material_name: "Box Red", directory_name: "box-red", brand: "PETG", estimated_rgb: [180, 20, 30],
      material_file_url: "/api/files/box-red", profile_kind: "lumina_box" as const, optical_model_id: "backed_gradient_spectral_four_flux_smooth/v3",
      capture_dataset_id: "collection-1", material_symbol: "R" as const, reference_id: "reference-1" };
    useLuminaBoxMaterialNavigation.setState({ libraryProfileKind: "lumina_box" });
    vi.mocked(listGradientCardMaterials).mockResolvedValue({ status: "ok", message: "Loaded", materials: [item,
      { ...item, material_name: "Old experiment", directory_name: "old", optical_model_id: "box_reference_consistent_feedback/equal_xyz_v1" }] });
    render(<MaterialLibraryPanel />);
    await screen.findByTestId("material-library-brand-group");
    expandAllMaterialLibraryGroups();
    await screen.findByText("Box Red");
    expect(screen.queryByText("Old experiment")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看采集记录" }));
    expect(useWidgetStore.getState().activeTab).toBe("lumina-box");
    expect(useLuminaBoxMaterialNavigation.getState().captureRequest).toEqual({ datasetId: "collection-1", materialSymbol: "R",
      archive: { name: "Box Red", brand: "PETG", material_type: "", directoryName: "box-red" } });
    fireEvent.click(screen.getByRole("button", { name: /编辑信息|edit/i }));
    expect(screen.queryByTestId("material-library-edit-color-picker")).not.toBeInTheDocument();
  });

  it("groups saved materials by brand and prefixes names with brand tags", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 4 saved materials",
      materials: [
        {
          material_name: "PLA Red",
          directory_name: "brand-a-red",
          brand: "Brand A",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json-a",
          stage_a_params_url: "/api/files/stage-a-json-a",
          estimated_rgb: [200, 30, 40],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
        {
          material_name: "PLA Blue",
          directory_name: "brand-b-blue",
          brand: "Brand B",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json-b",
          stage_a_params_url: "/api/files/stage-a-json-b",
          estimated_rgb: [30, 80, 200],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
        {
          material_name: "PLA Yellow",
          directory_name: "brand-a-yellow",
          brand: "Brand A",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json-c",
          stage_a_params_url: "/api/files/stage-a-json-c",
          estimated_rgb: [220, 180, 30],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
        {
          material_name: "PLA Natural",
          directory_name: "unassigned-natural",
          brand: null,
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json-d",
          stage_a_params_url: "/api/files/stage-a-json-d",
          estimated_rgb: [220, 220, 210],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
      ],
    });

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getAllByTestId("material-library-brand-group")).toHaveLength(3);
    });

    const groups = screen.getAllByTestId("material-library-brand-group");
    expect(groups).toHaveLength(3);
    expect(groups.map((group) => group.getAttribute("data-brand"))).toEqual([
      "Brand A",
      "Brand B",
      "",
    ]);

    const firstGroupToggle = within(groups[0]).getByTestId("material-library-brand-group-toggle");
    const secondGroupToggle = within(groups[1]).getByTestId("material-library-brand-group-toggle");
    const unassignedToggle = within(groups[2]).getByTestId("material-library-brand-group-toggle");
    expect(firstGroupToggle).toHaveAttribute("aria-expanded", "false");
    expect(secondGroupToggle).toHaveAttribute("aria-expanded", "false");
    expect(unassignedToggle).toHaveAttribute("aria-expanded", "false");
    expect(within(groups[0]).queryByText("PLA Red")).not.toBeInTheDocument();

    fireEvent.click(firstGroupToggle);
    fireEvent.click(secondGroupToggle);
    fireEvent.click(unassignedToggle);

    expect(within(groups[0]).getByText("PLA Red")).toBeInTheDocument();
    expect(within(groups[0]).getByText("PLA Yellow")).toBeInTheDocument();
    expect(within(groups[1]).getByText("PLA Blue")).toBeInTheDocument();
    expect(within(groups[2]).getByText("PLA Natural")).toBeInTheDocument();

    const brandTags = screen.getAllByTestId("material-library-brand-tag");
    expect(brandTags.map((tag) => tag.textContent)).toEqual([
      "Brand A",
      "Brand A",
      "Brand B",
      expect.stringMatching(/未分组|Unassigned/),
    ]);

    fireEvent.click(firstGroupToggle);
    expect(firstGroupToggle).toHaveAttribute("aria-expanded", "false");
    expect(within(groups[0]).queryByText("PLA Red")).not.toBeInTheDocument();
    expect(within(groups[0]).queryByText("PLA Yellow")).not.toBeInTheDocument();
    expect(within(groups[1]).getByText("PLA Blue")).toBeInTheDocument();

    fireEvent.click(firstGroupToggle);
    expect(firstGroupToggle).toHaveAttribute("aria-expanded", "true");
    expect(within(groups[0]).getByText("PLA Red")).toBeInTheDocument();
    expect(within(groups[0]).getByText("PLA Yellow")).toBeInTheDocument();
  });

  it("edits a saved material name and brand from the library", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          brand: null,
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json",
          stage_a_params_url: "/api/files/stage-a-json",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
      ],
    });
    vi.mocked(updateGradientCardMaterial).mockResolvedValue({
      status: "ok",
      message: "updated",
      material: {
        material_name: "PLA Matte",
        directory_name: "pla-basic",
        brand: "Bambu Lab",
        created_at: "2026-04-16T10:00:00Z",
        updated_at: "2026-04-17T11:00:00Z",
        material_file_url: "/api/files/material-json-updated",
        stage_a_params_url: "/api/files/stage-a-json-updated",
        estimated_rgb: [100, 120, 140],
        layer_height_mm: 0.04,
        mean_delta_e: 1.23,
        verification_count: 3,
        verification_history: [],
      },
    });

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });

    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /编辑信息|edit details/i }));

    expect(screen.getByTestId("material-library-edit-dialog")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("material-library-edit-name-input"), {
      target: { value: "PLA Matte" },
    });
    fireEvent.change(screen.getByTestId("material-library-edit-brand-input"), {
      target: { value: "Bambu Lab" },
    });
    fireEvent.click(screen.getByRole("button", { name: /保存修改|save changes/i }));

    await waitFor(() => {
      expect(updateGradientCardMaterial).toHaveBeenCalledWith("pla-basic", {
        materialName: "PLA Matte",
        brand: "Bambu Lab",
        estimatedRgb: [100, 120, 140],
      });
    });

    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(screen.getByText("PLA Matte")).toBeInTheDocument();
    });
    expect(screen.getByTestId("material-library-item-brand")).toHaveTextContent("Bambu Lab");
  });

  it("edits the display color via hex input from the library", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          brand: null,
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json",
          stage_a_params_url: "/api/files/stage-a-json",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
      ],
    });
    vi.mocked(updateGradientCardMaterial).mockResolvedValue({
      status: "ok",
      message: "updated",
      material: {
        material_name: "PLA Basic",
        directory_name: "pla-basic",
        brand: null,
        created_at: "2026-04-16T10:00:00Z",
        updated_at: "2026-04-17T11:00:00Z",
        material_file_url: "/api/files/material-json-updated",
        stage_a_params_url: "/api/files/stage-a-json-updated",
        estimated_rgb: [255, 128, 0],
        layer_height_mm: 0.04,
        mean_delta_e: 1.23,
        verification_count: 3,
        verification_history: [],
      },
    });

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });

    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /编辑信息|edit details/i }));

    const hexInput = screen.getByTestId("material-library-edit-color-hex-input") as HTMLInputElement;
    expect(hexInput.value.toUpperCase()).toBe("#64788C");

    fireEvent.change(hexInput, { target: { value: "#FF8000" } });

    const picker = screen.getByTestId("material-library-edit-color-picker") as HTMLInputElement;
    expect(picker.value.toLowerCase()).toBe("#ff8000");

    fireEvent.click(screen.getByRole("button", { name: /保存修改|save changes/i }));

    await waitFor(() => {
      expect(updateGradientCardMaterial).toHaveBeenCalledWith("pla-basic", {
        materialName: "PLA Basic",
        brand: null,
        estimatedRgb: [255, 128, 0],
      });
    });
  });

  it("rejects invalid hex input in the edit dialog", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          brand: null,
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
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
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });

    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /编辑信息|edit details/i }));

    const hexInput = screen.getByTestId("material-library-edit-color-hex-input") as HTMLInputElement;
    fireEvent.change(hexInput, { target: { value: "not-a-color" } });

    expect(screen.getByTestId("material-library-edit-color-hex-error")).toBeInTheDocument();
  });

  it("opens saved material verification history in a dialog", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
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
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });

    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /展开验证历史|show verification history/i }));

    expect(screen.getByTestId("material-library-history-dialog")).toBeInTheDocument();
    expect(screen.getByText(/第 1 次验证|Run 1/i)).toBeInTheDocument();
    expect(screen.getByText("0.0150")).toBeInTheDocument();
    expect(screen.getByText(/0.210, 0.310, 0.410/)).toBeInTheDocument();
    expect(screen.getByText(/White identity \/ Black rotate_90_cw|白底 identity \/ 黑底 rotate_90_cw/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /关闭|close/i }));

    await waitFor(() => {
      expect(screen.queryByTestId("material-library-history-dialog")).not.toBeInTheDocument();
    });
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
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });

    expandAllMaterialLibraryGroups();

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
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });

    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /删除耗材|delete material/i }));

    await waitFor(() => {
      expect(deleteGradientCardMaterial).toHaveBeenCalledWith("pla-basic");
    });
    expect(screen.queryByText("PLA Basic")).not.toBeInTheDocument();
  });

  it("surfaces duplicate dates and directory in the card and delete confirmation", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 2 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "Brand/PLA Basic_20260709_145858",
          brand: "Brand",
          created_at: "2026-07-09T14:58:58Z",
          updated_at: "2026-07-09T15:30:00Z",
          material_file_url: "/api/files/material-json-new",
          stage_a_params_url: "/api/files/stage-a-json-new",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
          verification_history: [
            {
              verification_index: 3,
              captured_at: "2026-07-09T14:59:00Z",
              mean_delta_e: 1.23,
              estimated_rgb: [100, 120, 140],
              estimated_k: [1.1, 1.2, 1.3],
              e_values: [0.21, 0.31, 0.41],
              k_values: [1.1, 1.2, 1.3],
              white_c0_values: [0.91, 0.92, 0.93],
              black_c0_values: [0.11, 0.12, 0.13],
            },
          ],
        },
        {
          material_name: "PLA Basic",
          directory_name: "Brand/PLA Basic_20260521_161941",
          brand: "Brand",
          created_at: "2026-05-21T16:19:41Z",
          updated_at: "2026-05-21T16:30:00Z",
          material_file_url: "/api/files/material-json-old",
          stage_a_params_url: "/api/files/stage-a-json-old",
          estimated_rgb: [90, 110, 130],
          layer_height_mm: 0.04,
          mean_delta_e: 2.34,
          verification_count: 1,
          verification_history: [
            {
              verification_index: 1,
              captured_at: "2026-05-21T16:19:50Z",
              mean_delta_e: 2.34,
              estimated_rgb: [90, 110, 130],
              estimated_k: [1.0, 1.1, 1.2],
              e_values: [0.2, 0.3, 0.4],
              k_values: [1.0, 1.1, 1.2],
              white_c0_values: [0.9, 0.91, 0.92],
              black_c0_values: [0.1, 0.11, 0.12],
            },
          ],
        },
      ],
    });
    vi.mocked(deleteGradientCardMaterial).mockResolvedValue({
      status: "ok",
      message: "deleted",
      directory_name: "Brand/PLA Basic_20260521_161941",
      material_name: "PLA Basic",
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });

    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(screen.getAllByTestId("material-library-item")).toHaveLength(2);
    });

    const cards = screen.getAllByTestId("material-library-item");
    expect(within(cards[0]).getByTestId("material-library-duplicate-badge")).toHaveTextContent(/同名 2 份|2 copies/i);
    expect(within(cards[0]).getByTestId("material-library-item-meta")).toHaveTextContent("Brand/PLA Basic_20260709_145858");
    expect(within(cards[0]).getByTestId("material-library-item-meta")).toHaveTextContent(/最近更新|Last updated/i);
    expect(within(cards[0]).getByTestId("material-library-item-meta")).not.toHaveTextContent(/最近验证|Last verified/i);
    expect(within(cards[0]).getByTestId("material-library-item-meta")).toHaveTextContent("2026");

    fireEvent.click(within(cards[1]).getByRole("button", { name: /删除耗材|delete material/i }));

    await waitFor(() => {
      expect(deleteGradientCardMaterial).toHaveBeenCalledWith("Brand/PLA Basic_20260521_161941");
    });
    const confirmMessage = String(confirmSpy.mock.calls[0]?.[0] ?? "");
    expect(confirmMessage).toContain("PLA Basic");
    expect(confirmMessage).toContain("Brand/PLA Basic_20260521_161941");
    expect(confirmMessage).toMatch(/最近更新|Last updated/);
    expect(confirmMessage).not.toMatch(/最近验证|Last verified/);
    expect(confirmMessage).toContain("2026");
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

  it("shows readable material library load failures instead of raw HTTP status text", async () => {
    vi.mocked(listGradientCardMaterials).mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    render(<MaterialLibraryPanel />);

    const error = await screen.findByTestId("material-library-error");
    expect(error).toHaveTextContent("服务器发生内部错误。请稍后重试；如果问题持续，请提交反馈。");
    expect(error).not.toHaveTextContent("Request failed with status code 500");
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
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });

    expandAllMaterialLibraryGroups();

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

  it("filters Lumina Box materials, clears Stage A selections, and exports one profile family", async () => {
    const stageAItem = {
      material_name: "Stage A Red",
      directory_name: "stage-a-red",
      created_at: "2026-04-16T10:00:00Z",
      updated_at: "2026-04-16T11:00:00Z",
      material_file_url: "/api/files/stage-a-material-json",
      stage_a_params_url: "/api/files/stage-a-params",
      estimated_rgb: [180, 50, 50] as [number, number, number],
      layer_height_mm: 0.04,
      mean_delta_e: 1.23,
      verification_count: 3,
      profile_kind: "stage_a" as const,
    };
    const luminaBoxItem = {
      material_name: "Lumina Blue",
      directory_name: "lumina-blue",
      created_at: "2026-04-16T10:00:00Z",
      updated_at: "2026-04-16T11:00:00Z",
      material_file_url: "/api/files/lumina-material-json",
      stage_a_params_url: null,
      estimated_rgb: [50, 90, 190] as [number, number, number],
      layer_height_mm: 0.04,
      mean_delta_e: null,
      verification_count: 0,
      profile_kind: "lumina_box" as const,
      optical_model_id: "backed_gradient_spectral_four_flux_smooth/v3",
    };
    vi.mocked(listGradientCardMaterials).mockImplementation(async ({ profileKind } = {}) => ({
      status: "ok",
      message: "Loaded saved materials",
      // Deliberately include a stale Stage A row in the Lumina response: the
      // panel must never expose a client-side mixed selection.
      materials: profileKind === "lumina_box"
        ? [luminaBoxItem, stageAItem]
        : [stageAItem],
    }));
    vi.mocked(exportGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Exported Lumina Box materials",
      download_url: "/api/files/lumina-export",
      filename: "lumina-box-materials-v3.zip",
      exported_count: 1,
      exported_directory_names: ["lumina-blue"],
    });
    const anchorClickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    try {
      render(<MaterialLibraryPanel />);

      await waitFor(() => {
        expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
        expect(listGradientCardMaterials).toHaveBeenLastCalledWith({ profileKind: "stage_a" });
      });
      expandAllMaterialLibraryGroups();
      await screen.findByText("Stage A Red");
      fireEvent.click(screen.getByTestId("material-library-select-stage-a-red"));
      expect(
        screen.getByTestId("material-library-select-stage-a-red"),
      ).toBeChecked();

      fireEvent.click(screen.getByTestId("material-library-profile-lumina_box"));

      await waitFor(() => {
        expect(listGradientCardMaterials).toHaveBeenLastCalledWith({ profileKind: "lumina_box" });
        expect(screen.queryByText("Stage A Red")).not.toBeInTheDocument();
      });
      expandAllMaterialLibraryGroups();
      await screen.findByText("Lumina Blue");
      expect(screen.queryByText("Stage A Red")).not.toBeInTheDocument();

      fireEvent.click(screen.getByTestId("material-library-select-lumina-blue"));
      fireEvent.click(screen.getByRole("button", { name: /导出所选耗材|export selected/i }));

      await waitFor(() => {
        expect(exportGradientCardMaterials).toHaveBeenCalledWith(["lumina-blue"]);
      });
    } finally {
      anchorClickSpy.mockRestore();
    }
  });

  it("refreshes and selects imported Lumina Box archives in the active family", async () => {
    const luminaBoxItem = {
      material_name: "Lumina Green",
      directory_name: "lumina-green",
      created_at: "2026-04-16T10:00:00Z",
      updated_at: "2026-04-16T11:00:00Z",
      material_file_url: "/api/files/lumina-green-material-json",
      stage_a_params_url: null,
      estimated_rgb: [50, 180, 90] as [number, number, number],
      layer_height_mm: 0.04,
      mean_delta_e: null,
      verification_count: 0,
      profile_kind: "lumina_box" as const,
      optical_model_id: "backed_gradient_spectral_four_flux_smooth/v3",
    };
    let imported = false;
    vi.mocked(listGradientCardMaterials).mockImplementation(async ({ profileKind } = {}) => ({
      status: "ok",
      message: imported ? "Loaded 1 saved material" : "Loaded 0 saved materials",
      materials: profileKind === "lumina_box" && imported ? [luminaBoxItem] : [],
    }));
    vi.mocked(importGradientCardMaterials).mockImplementation(async () => {
      imported = true;
      return {
        status: "ok",
        message: "Imported 1 saved material",
        imported_count: 1,
        imported_materials: [
          {
            material_name: "Lumina Green",
            directory_name: "lumina-green",
            brand: null,
            verification_count: 0,
            created_at: "2026-04-16T10:00:00Z",
            updated_at: "2026-04-16T11:00:00Z",
          },
        ],
      };
    });

    render(<MaterialLibraryPanel />);
    fireEvent.click(screen.getByTestId("material-library-profile-lumina_box"));

    await waitFor(() => {
      expect(listGradientCardMaterials).toHaveBeenLastCalledWith({ profileKind: "lumina_box" });
    });
    const importInput = screen.getByTestId("material-library-import-input");
    const luminaBundle = new File(
      ["lumina-box-v3"],
      "lumina-box-materials-v3.zip",
      { type: "application/zip" },
    );
    fireEvent.change(importInput, { target: { files: [luminaBundle] } });

    await waitFor(() => {
      expect(importGradientCardMaterials).toHaveBeenCalledWith([luminaBundle]);
      expect(listGradientCardMaterials).toHaveBeenLastCalledWith({ profileKind: "lumina_box" });
    });
    await screen.findByTestId("material-library-brand-group");
    expandAllMaterialLibraryGroups();
    await screen.findByText("Lumina Green");
    expect(
      screen.getByTestId("material-library-select-lumina-green"),
    ).toBeChecked();
  });

  it("keeps the Lumina Box list current when a pending Stage A import resolves", async () => {
    const pendingImport = deferred<
      Awaited<ReturnType<typeof importGradientCardMaterials>>
    >();
    const luminaBoxItem = {
      material_name: "Lumina Blue",
      directory_name: "lumina-blue",
      created_at: "2026-04-16T10:00:00Z",
      updated_at: "2026-04-16T11:00:00Z",
      material_file_url: "/api/files/lumina-blue-material-json",
      stage_a_params_url: null,
      estimated_rgb: [50, 90, 190] as [number, number, number],
      layer_height_mm: 0.04,
      mean_delta_e: null,
      verification_count: 0,
      profile_kind: "lumina_box" as const,
      optical_model_id: "backed_gradient_spectral_four_flux_smooth/v3",
    };
    vi.mocked(listGradientCardMaterials).mockImplementation(async ({ profileKind } = {}) => ({
      status: "ok",
      message: "Loaded saved materials",
      materials: profileKind === "lumina_box" ? [luminaBoxItem] : [],
    }));
    vi.mocked(importGradientCardMaterials).mockReturnValue(pendingImport.promise);

    render(<MaterialLibraryPanel />);
    await waitFor(() => {
      expect(listGradientCardMaterials).toHaveBeenLastCalledWith({ profileKind: "stage_a" });
    });

    const importInput = screen.getByTestId("material-library-import-input");
    const stageABundle = new File(["stage-a"], "stage-a-materials.zip", {
      type: "application/zip",
    });
    fireEvent.change(importInput, { target: { files: [stageABundle] } });
    await waitFor(() => {
      expect(importGradientCardMaterials).toHaveBeenCalledWith([stageABundle]);
    });

    fireEvent.click(screen.getByTestId("material-library-profile-lumina_box"));
    await screen.findByTestId("material-library-brand-group");
    expandAllMaterialLibraryGroups();
    await screen.findByText("Lumina Blue");

    await act(async () => {
      pendingImport.resolve({
        status: "ok",
        message: "Imported Stage A material",
        imported_count: 1,
        imported_materials: [
          {
            material_name: "Stage A Red",
            directory_name: "stage-a-red",
            brand: null,
            verification_count: 1,
            created_at: "2026-04-16T10:00:00Z",
            updated_at: "2026-04-16T11:00:00Z",
          },
        ],
      });
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(listGradientCardMaterials).toHaveBeenLastCalledWith({ profileKind: "lumina_box" });
      expect(screen.getByText("Lumina Blue")).toBeInTheDocument();
    });
    expect(screen.queryByText("Stage A Red")).not.toBeInTheDocument();
    expect(screen.queryByTestId("material-library-select-stage-a-red")).not.toBeInTheDocument();
    expect(screen.getByTestId("material-library-select-lumina-blue")).not.toBeChecked();
    expect(screen.queryByTestId("material-library-success")).not.toBeInTheDocument();
    expect(screen.queryByTestId("material-library-error")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /导入.*ZIP|Import.*ZIP/i }),
    ).toBeEnabled();
  });

  it("does not download a stale Stage A export after switching to Lumina Box", async () => {
    const pendingExport = deferred<
      Awaited<ReturnType<typeof exportGradientCardMaterials>>
    >();
    const stageAItem = {
      material_name: "Stage A Red",
      directory_name: "stage-a-red",
      created_at: "2026-04-16T10:00:00Z",
      updated_at: "2026-04-16T11:00:00Z",
      material_file_url: "/api/files/stage-a-red-material-json",
      stage_a_params_url: "/api/files/stage-a-red-params",
      estimated_rgb: [180, 50, 50] as [number, number, number],
      layer_height_mm: 0.04,
      mean_delta_e: 1.23,
      verification_count: 1,
      profile_kind: "stage_a" as const,
    };
    const luminaBoxItem = {
      material_name: "Lumina Green",
      directory_name: "lumina-green",
      created_at: "2026-04-16T10:00:00Z",
      updated_at: "2026-04-16T11:00:00Z",
      material_file_url: "/api/files/lumina-green-material-json",
      stage_a_params_url: null,
      estimated_rgb: [50, 180, 90] as [number, number, number],
      layer_height_mm: 0.04,
      mean_delta_e: null,
      verification_count: 0,
      profile_kind: "lumina_box" as const,
      optical_model_id: "backed_gradient_spectral_four_flux_smooth/v3",
    };
    vi.mocked(listGradientCardMaterials).mockImplementation(async ({ profileKind } = {}) => ({
      status: "ok",
      message: "Loaded saved materials",
      materials: profileKind === "lumina_box" ? [luminaBoxItem] : [stageAItem],
    }));
    vi.mocked(exportGradientCardMaterials).mockReturnValue(pendingExport.promise);
    const anchorClickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    try {
      render(<MaterialLibraryPanel />);
      await screen.findByTestId("material-library-brand-group");
      expandAllMaterialLibraryGroups();
      await screen.findByText("Stage A Red");
      fireEvent.click(screen.getByTestId("material-library-select-stage-a-red"));
      fireEvent.click(screen.getByRole("button", { name: /导出所选耗材|export selected/i }));
      await waitFor(() => {
        expect(exportGradientCardMaterials).toHaveBeenCalledWith(["stage-a-red"]);
      });

      fireEvent.click(screen.getByTestId("material-library-profile-lumina_box"));
      await screen.findByTestId("material-library-brand-group");
      expandAllMaterialLibraryGroups();
      await screen.findByText("Lumina Green");

      await act(async () => {
        pendingExport.resolve({
          status: "ok",
          message: "Exported Stage A material",
          download_url: "/api/files/stage-a-export",
          filename: "stage-a-materials.zip",
          exported_count: 1,
          exported_directory_names: ["stage-a-red"],
        });
        await Promise.resolve();
      });

      expect(anchorClickSpy).not.toHaveBeenCalled();
      expect(screen.queryByTestId("material-library-success")).not.toBeInTheDocument();
      expect(screen.queryByTestId("material-library-error")).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /导入.*ZIP|Import.*ZIP/i }),
      ).toBeEnabled();
    } finally {
      anchorClickSpy.mockRestore();
    }
  });

  it("shows readable material export failures instead of raw HTTP status text", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json",
          stage_a_params_url: "/api/files/stage-a-json",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
      ],
    });
    vi.mocked(exportGradientCardMaterials).mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });
    expandAllMaterialLibraryGroups();
    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("material-library-select-pla-basic"));
    fireEvent.click(screen.getByRole("button", { name: /导出所选耗材|export selected/i }));

    const error = await screen.findByTestId("material-library-error");
    expect(error).toHaveTextContent("服务器发生内部错误。请稍后重试；如果问题持续，请提交反馈。");
    expect(error).not.toHaveTextContent("Request failed with status code 500");
  });

  it("does not expose cloud upload controls in the distribution UI", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "BrandA/pla-basic",
          brand: "BrandA",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
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

    await screen.findByTestId("material-library-brand-group-toggle");
    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: /上传到云端|upload to cloud/i })).not.toBeInTheDocument();
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
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });

    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });
    expect(screen.getByTestId("material-library-success")).toBeInTheDocument();
    expect((screen.getByTestId("material-library-select-pla-basic") as HTMLInputElement).checked).toBe(true);
  });

});
