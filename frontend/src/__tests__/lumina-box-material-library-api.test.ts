import { beforeEach, describe, expect, it, vi } from "vitest";

import apiClient from "../api/client";
import {
  fitLuminaBoxMaterial,
  listGradientCardMaterials,
  saveLuminaBoxMaterial,
} from "../api/extractor";
import type {
  LuminaBoxFitRequest,
  LuminaBoxSaveRequest,
  SavedMaterialLibraryItem,
} from "../api/types";

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

const mockGet = vi.mocked(apiClient.get);
const mockPost = vi.mocked(apiClient.post);
const COLOR_BRIDGE_ID = "d65_10_to_d65_2_diagonal/v1" as const;
const libraryResponse = { data: { status: "ok", message: "Loaded 0 saved materials", materials: [] } };
const fitRequest = {
  protocol_id: "lumina_box_xyz_paired_diffuser_km/v2",
  value_scale: "percent_0_100",
  measurement_backing_percent_xyz: [19.8, 19.7, 24.7],
  is_reference_white: false,
  reference_directory_name: "reference-white",
  samples: [
    { thickness_mm: 0.08, transmittance_percent_xyz: [80, 80, 80], reflectance_percent_xyz: [20, 20, 20] },
    { thickness_mm: 0.16, transmittance_percent_xyz: [60, 60, 60], reflectance_percent_xyz: [22, 22, 22] },
    { thickness_mm: 0.32, transmittance_percent_xyz: [40, 40, 40], reflectance_percent_xyz: [24, 24, 24] },
  ],
} satisfies LuminaBoxFitRequest;
const saveRequest = {
  fit_session_id: "fit-session-1",
  material_name: "Test PLA",
} satisfies LuminaBoxSaveRequest;
const libraryItem = {
  material_name: "Test PLA",
  directory_name: "test-pla",
  material_file_url: null,
  estimated_rgb: [128, 120, 112],
  profile_kind: "lumina_box",
  color_bridge_id: COLOR_BRIDGE_ID,
} satisfies SavedMaterialLibraryItem;

beforeEach(() => {
  vi.clearAllMocks();
  mockGet.mockResolvedValue(libraryResponse);
});

describe("listGradientCardMaterials Lumina Box profile filter", () => {
  it("keeps the historical no-query request when callers use the default Stage A view", async () => {
    await listGradientCardMaterials();

    expect(mockGet).toHaveBeenCalledWith(
      "/extractor/gradient-card-materials",
      expect.objectContaining({ params: undefined }),
    );
  });

  it("forwards an explicitly selected profile filter", async () => {
    await listGradientCardMaterials({ profileKind: "lumina_box", includeFileUrls: true });

    expect(mockGet).toHaveBeenCalledWith(
      "/extractor/gradient-card-materials",
      expect.objectContaining({
        params: { profile_kind: "lumina_box", include_file_urls: true },
      }),
    );

    await listGradientCardMaterials({ profileKind: "all" });
    expect(mockGet).toHaveBeenLastCalledWith(
      "/extractor/gradient-card-materials",
      expect.objectContaining({ params: { profile_kind: "all" } }),
    );

    await listGradientCardMaterials({ profileKind: "stage_a" });
    expect(mockGet).toHaveBeenLastCalledWith(
      "/extractor/gradient-card-materials",
      expect.objectContaining({ params: { profile_kind: "stage_a" } }),
    );
  });

  it("preserves the fixed color bridge on Lumina Box list rows", async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        status: "ok",
        message: "Loaded 1 saved material",
        materials: [libraryItem],
      },
    });

    const response = await listGradientCardMaterials({ profileKind: "lumina_box" });

    expect(response.materials[0]?.color_bridge_id).toBe(COLOR_BRIDGE_ID);
  });
});

describe("Lumina Box fit/save API client contract", () => {
  it("preserves color_bridge_id from the fit response", async () => {
    mockPost.mockResolvedValueOnce({
      data: { color_bridge_id: COLOR_BRIDGE_ID },
    });

    const response = await fitLuminaBoxMaterial(fitRequest);

    expect(response.color_bridge_id).toBe(COLOR_BRIDGE_ID);
    expect(mockPost).toHaveBeenCalledWith(
      "/extractor/lumina-box/fit",
      fitRequest,
      expect.objectContaining({ timeout: 3_600_000 }),
    );
  });

  it("preserves color_bridge_id on the saved material response", async () => {
    mockPost.mockResolvedValueOnce({
      data: {
        material: {
          material_name: saveRequest.material_name,
          directory_name: "test-pla",
          brand: null,
          material_type: null,
          notes: null,
          created_at: null,
          updated_at: null,
          profile_kind: "lumina_box",
          acquisition_source: "lumina_box",
          optical_model: "km_xyz/v1",
          optical_model_id: "km_xyz/v1",
          measurement_protocol_id: "lumina_box_xyz_paired_diffuser_km/v2",
          color_bridge_id: COLOR_BRIDGE_ID,
          measurement_backing_base_percent_xyz: [19.8, 19.7, 24.7],
          measurement_backing_scale: 0.82,
          measurement_backing_effective_percent_xyz: [16.236, 16.154, 20.254],
          measurement_reflection_boundary_id: "instrument_diffuser_scaled/v1",
          estimated_effective_d65_10_xyz_relative: [0.2, 0.2, 0.2],
          estimated_reflectance_thickness_mm: 3,
          estimated_rgb: [128, 120, 112],
        },
      },
    });

    const response = await saveLuminaBoxMaterial(saveRequest);

    expect(response.material?.color_bridge_id).toBe(COLOR_BRIDGE_ID);
    expect(mockPost).toHaveBeenCalledWith(
      "/extractor/lumina-box/save",
      saveRequest,
      expect.objectContaining({ timeout: 3_600_000 }),
    );
  });
});
