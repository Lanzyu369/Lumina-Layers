import { beforeEach, describe, expect, it, vi } from "vitest";
import { ColorMode, ModelingMode } from "../../api/types";
import {
  DEFAULT_STATE,
  useConverterStore,
} from "../../stores/converter";

const mocks = vi.hoisted(() => ({
  convertPreview: vi.fn(),
  uploadModelSurface: vi.fn(),
  selectModelSurface: vi.fn(),
  fetchGradientGroups: vi.fn(),
  getGlbStatus: vi.fn(),
}));

vi.mock("../../api/converter", async () => {
  const actual = await vi.importActual<typeof import("../../api/converter")>(
    "../../api/converter",
  );
  return {
    ...actual,
    convertPreview: mocks.convertPreview,
    uploadModelSurface: mocks.uploadModelSurface,
    selectModelSurface: mocks.selectModelSurface,
    fetchGradientGroups: mocks.fetchGradientGroups,
    getGlbStatus: mocks.getGlbStatus,
  };
});

vi.mock("../../api/lut", async () => {
  const actual = await vi.importActual<typeof import("../../api/lut")>(
    "../../api/lut",
  );
  return {
    ...actual,
    fetchSessionLutInfo: vi.fn().mockRejectedValue(new Error("not needed")),
  };
});

function resetStore(): void {
  useConverterStore.setState({
    ...DEFAULT_STATE,
    source_version: "legacy",
    lut_name: "default",
    imageFile: new File(["image"], "art.png", { type: "image/png" }),
    imagePreviewUrl: "blob:image",
    color_mode: ColorMode.FOUR_COLOR_RYBW,
    modeling_mode: ModelingMode.HIGH_FIDELITY,
  });
}

function previewResponse() {
  return {
    session_id: "session-1",
    status: "ok",
    message: "ok",
    preview_url: "/api/files/preview",
    preview_glb_url: null,
    palette: [],
    dimensions: { width: 20, height: 10 },
    warnings: [],
  };
}

describe("model surface overlay store flow", () => {
  beforeEach(() => {
    resetStore();
    mocks.convertPreview.mockReset();
    mocks.uploadModelSurface.mockReset();
    mocks.selectModelSurface.mockReset();
    mocks.fetchGradientGroups.mockReset();
    mocks.getGlbStatus.mockReset();
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:model");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  });

  it("uploads a model and stores the model surface file id", async () => {
    mocks.uploadModelSurface.mockResolvedValueOnce({
      status: "ok",
      model_file_id: "model-file-1",
      summary: {
        vertex_count: 8,
        face_count: 12,
        bounds_min_mm: [0, 0, 0],
        bounds_max_mm: [20, 10, 2],
        extents_mm: [20, 10, 2],
        is_watertight: true,
        is_winding_consistent: true,
        body_count: 1,
        unit_warning: null,
      },
      warnings: [],
    });

    const file = new File(["solid"], "plate.stl", {
      type: "application/octet-stream",
    });
    await useConverterStore.getState().uploadModelSurfaceFile(file);

    const state = useConverterStore.getState();
    expect(state.modelSurfaceEnabled).toBe(true);
    expect(state.modelSurfaceFile).toBe(file);
    expect(state.modelSurfaceModelFileId).toBe("model-file-1");
    expect(state.modelSurfaceSummary?.extents_mm).toEqual([20, 10, 2]);
  });

  it("selects a model face and sends surface config with preview", async () => {
    const selection = { face_indices: [0, 1], face_count: 2 };
    const footprint = {
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      frame: {
        origin: [0, 0, 1],
        normal: [0, 0, 1],
        u_axis: [1, 0, 0],
        v_axis: [0, 1, 0],
      },
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]],
      holes: [],
    };
    mocks.selectModelSurface.mockResolvedValueOnce({
      status: "ok",
      selection_id: "selection-1",
      selection,
      footprint,
      warnings: [],
    });
    mocks.convertPreview.mockResolvedValueOnce(previewResponse());
    mocks.fetchGradientGroups.mockResolvedValueOnce({ groups: [] });

    useConverterStore.setState({
      modelSurfaceEnabled: true,
      modelSurfaceModelFileId: "model-file-1",
      modelSurfaceFile: new File(["solid"], "plate.stl"),
    } as never);

    await useConverterStore.getState().selectModelSurfaceFace(4);
    await useConverterStore.getState().submitPreview();

    expect(mocks.selectModelSurface).toHaveBeenCalledWith("model-file-1", {
      face_index: 4,
    });
    const [, params] = mocks.convertPreview.mock.calls[0];
    expect(params.surface_model_file_id).toBe("model-file-1");
    expect(JSON.parse(params.surface_selection_json)).toEqual(selection);
    expect(JSON.parse(params.surface_footprint_json)).toEqual(footprint);
    expect(JSON.parse(params.surface_placement_json)).toEqual({
      mode: "edge_to_edge",
      offset_x_mm: 0,
      offset_y_mm: 0,
      scale: 1,
      rotation_deg: 0,
      inset_mm: 0,
    });
  });
});
