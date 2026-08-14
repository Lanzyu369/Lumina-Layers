import { beforeEach, describe, expect, it, vi } from "vitest";
import { ColorMode, ModelingMode } from "../../api/types";
import {
  DEFAULT_STATE,
  useConverterStore,
} from "../../stores/converter";

const mocks = vi.hoisted(() => ({
  convertGenerate: vi.fn(),
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
    convertGenerate: mocks.convertGenerate,
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
    mocks.convertGenerate.mockReset();
    mocks.convertPreview.mockReset();
    mocks.uploadModelSurface.mockReset();
    mocks.selectModelSurface.mockReset();
    mocks.fetchGradientGroups.mockReset();
    mocks.getGlbStatus.mockReset();
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:model");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  });

  it("uploads a model and stores the model surface file id", async () => {
    useConverterStore.setState({ backing_infill_density_percent: 20 });
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
      surface_candidates: [
        {
          id: "surface-4",
          face_index: 4,
          face_count: 2,
          area_mm2: 200,
          normal: [0, 0, 1],
          footprint: { area_mm2: 200 },
        },
      ],
      warnings: [],
    });

    const file = new File(["solid"], "plate.stl", {
      type: "application/octet-stream",
    });
    await useConverterStore.getState().uploadModelSurfaceFile(file);

    const state = useConverterStore.getState();
    expect(state.modelSurfaceEnabled).toBe(true);
    expect(state.backing_infill_density_percent).toBe(100);
    expect(state.modelSurfaceFile).toBe(file);
    expect(state.modelSurfaceModelFileId).toBe("model-file-1");
    expect(state.modelSurfaceSummary?.extents_mm).toEqual([20, 10, 2]);
    expect(state.modelSurfaceCandidates).toEqual([
      expect.objectContaining({ id: "surface-4", face_index: 4 }),
    ]);
  });

  it("ignores surface selection while the model upload is still pending", async () => {
    useConverterStore.setState({
      modelSurfaceEnabled: true,
      modelSurfaceFile: new File(["solid"], "plate.stl"),
      modelSurfaceLoading: true,
      modelSurfaceModelFileId: null,
      modelSurfaceError: null,
    } as never);

    await useConverterStore.getState().selectModelSurfaceFace(4, "surface-4");

    expect(mocks.selectModelSurface).not.toHaveBeenCalled();
    expect(useConverterStore.getState().modelSurfaceError).toBeNull();
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
      modelSurfaceModelRotation: {
        x_deg: 10,
        y_deg: 20,
        z_deg: 30,
      },
    } as never);

    await useConverterStore.getState().selectModelSurfaceFace(4, "surface-4");
    await useConverterStore.getState().submitPreview();

    expect(mocks.selectModelSurface).toHaveBeenCalledWith("model-file-1", {
      face_index: 4,
      candidate_id: "surface-4",
      model_transform: {
        rotation_deg: {
          x: 10,
          y: 20,
          z: 30,
        },
      },
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
    expect(JSON.parse(params.surface_model_transform_json)).toEqual({
      rotation_deg: {
        x: 10,
        y: 20,
        z: 30,
      },
    });
  });

  it("uses the latest model rotation when previewing after a selected face is rotated", async () => {
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

    await useConverterStore.getState().selectModelSurfaceFace(4, "surface-4");
    useConverterStore.getState().updateModelSurfaceModelRotation({ x_deg: 45 });
    await useConverterStore.getState().submitPreview();

    const [, params] = mocks.convertPreview.mock.calls[0];
    expect(JSON.parse(params.surface_model_transform_json)).toEqual({
      rotation_deg: {
        x: 45,
        y: 0,
        z: 0,
      },
    });
  });

  it("uses the latest artwork placement when previewing after the artwork is adjusted", async () => {
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

    await useConverterStore.getState().selectModelSurfaceFace(4, "surface-4");
    useConverterStore.getState().updateModelSurfacePlacement({
      offset_x_mm: 3,
      offset_y_mm: -2,
      scale: 1.5,
      rotation_deg: 25,
      inset_mm: 1,
    });
    await useConverterStore.getState().submitPreview();

    const [, params] = mocks.convertPreview.mock.calls[0];
    expect(JSON.parse(params.surface_placement_json)).toEqual({
      mode: "edge_to_edge",
      offset_x_mm: 3,
      offset_y_mm: -2,
      scale: 1.5,
      rotation_deg: 25,
      inset_mm: 1,
    });
  });

  it("sends the selected surface, artwork placement, and model rotation with final 3MF generation", async () => {
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
    mocks.convertGenerate.mockResolvedValueOnce({
      status: "ok",
      message: "generated",
      download_url: "/api/files/surface-output.3mf",
      preview_3d_url: "/api/files/surface-output.glb",
    });

    useConverterStore.setState({
      sessionId: "session-1",
      modelSurfaceEnabled: true,
      modelSurfaceModelFileId: "model-file-1",
      modelSurfaceFile: new File(["solid"], "plate.stl"),
      modelSurfaceSelectionId: "selection-1",
      modelSurfaceSelection: selection,
      modelSurfaceFootprint: footprint,
      modelSurfacePlacement: {
        mode: "edge_to_edge",
        offset_x_mm: 3,
        offset_y_mm: -2,
        scale: 1.5,
        rotation_deg: 25,
        inset_mm: 1,
      },
      modelSurfaceModelRotation: {
        x_deg: 10,
        y_deg: 20,
        z_deg: 30,
      },
    } as never);

    await useConverterStore.getState().submitGenerate();

    expect(mocks.convertGenerate).toHaveBeenCalledTimes(1);
    const [, params] = mocks.convertGenerate.mock.calls[0];
    expect(params.surface_model_file_id).toBe("model-file-1");
    expect(JSON.parse(params.surface_selection_json)).toEqual(selection);
    expect(JSON.parse(params.surface_footprint_json)).toEqual(footprint);
    expect(JSON.parse(params.surface_placement_json)).toEqual({
      mode: "edge_to_edge",
      offset_x_mm: 3,
      offset_y_mm: -2,
      scale: 1.5,
      rotation_deg: 25,
      inset_mm: 1,
    });
    expect(JSON.parse(params.surface_model_transform_json)).toEqual({
      rotation_deg: {
        x: 10,
        y: 20,
        z: 30,
      },
    });
  });

  it("resets artwork placement when selecting a different surface face", async () => {
    const selection = { face_indices: [2, 3], face_count: 2 };
    const footprint = {
      bounds_width_mm: 40,
      bounds_height_mm: 20,
      frame: {
        origin: [0, 0, 1],
        normal: [0, 0, 1],
        u_axis: [1, 0, 0],
        v_axis: [0, 1, 0],
      },
      outer: [[-20, -10], [20, -10], [20, 10], [-20, 10], [-20, -10]],
      holes: [],
    };
    mocks.selectModelSurface.mockResolvedValueOnce({
      status: "ok",
      selection_id: "selection-2",
      selection,
      footprint,
      warnings: [],
    });

    useConverterStore.setState({
      modelSurfaceEnabled: true,
      modelSurfaceModelFileId: "model-file-1",
      modelSurfaceFile: new File(["solid"], "plate.stl"),
      modelSurfaceSelectionId: "selection-1",
      modelSurfacePlacement: {
        mode: "inset",
        offset_x_mm: 9,
        offset_y_mm: 5,
        scale: 1.8,
        rotation_deg: 30,
        inset_mm: 2,
      },
    } as never);

    await useConverterStore.getState().selectModelSurfaceFace(8, "surface-8");

    expect(useConverterStore.getState().modelSurfacePlacement).toEqual({
      mode: "edge_to_edge",
      offset_x_mm: 0,
      offset_y_mm: 0,
      scale: 1,
      rotation_deg: 0,
      inset_mm: 0,
    });
  });

  it("invalidates the stale preview session when artwork placement changes", () => {
    useConverterStore.setState({
      sessionId: "stale-session",
      previewImageUrl: "/api/files/stale-preview.png",
      originalPreviewUrl: "/api/files/stale-original.png",
      previewGlbUrl: "/api/files/stale-preview.glb",
      modelUrl: "/api/files/stale-model.glb",
      downloadUrl: "/api/files/stale.3mf",
      threemfDiskPath: "/tmp/stale.3mf",
      palette: [{ quantized_hex: "ff0000" }],
    } as never);

    useConverterStore.getState().updateModelSurfacePlacement({
      offset_x_mm: 4,
      scale: 1.25,
      rotation_deg: 12,
    });

    const state = useConverterStore.getState();
    expect(state.modelSurfacePlacement).toMatchObject({
      offset_x_mm: 4,
      scale: 1.25,
      rotation_deg: 12,
    });
    expect(state.sessionId).toBeNull();
    expect(state.previewImageUrl).toBeNull();
    expect(state.originalPreviewUrl).toBeNull();
    expect(state.previewGlbUrl).toBeNull();
    expect(state.modelUrl).toBeNull();
    expect(state.downloadUrl).toBeNull();
    expect(state.threemfDiskPath).toBeNull();
    expect(state.palette).toEqual([]);
  });

  it("resets artwork placement to edge-to-edge fit when replacing the artwork image", () => {
    useConverterStore.setState({
      modelSurfaceEnabled: true,
      modelSurfaceSelectionId: "selection-1",
      modelSurfaceFootprint: {
        bounds_width_mm: 200,
        bounds_height_mm: 200,
      },
      modelSurfacePlacement: {
        mode: "inset",
        offset_x_mm: 18,
        offset_y_mm: -9,
        scale: 2.25,
        rotation_deg: 37,
        inset_mm: 4,
      },
      sessionId: "stale-session",
      previewImageUrl: "/api/files/stale-preview.png",
      downloadUrl: "/api/files/stale.3mf",
    } as never);

    const nextImage = new File(["next"], "next-art.png", { type: "image/png" });
    useConverterStore.getState().setImageFile(nextImage);

    const state = useConverterStore.getState();
    expect(state.imageFile).toBe(nextImage);
    expect(state.modelSurfacePlacement).toEqual({
      mode: "edge_to_edge",
      offset_x_mm: 0,
      offset_y_mm: 0,
      scale: 1,
      rotation_deg: 0,
      inset_mm: 0,
    });
    expect(state.sessionId).toBeNull();
    expect(state.previewImageUrl).toBeNull();
    expect(state.downloadUrl).toBeNull();
  });

  it("resets artwork placement when loading a vectorized SVG into the surface flow", () => {
    useConverterStore.setState({
      modelSurfaceEnabled: true,
      modelSurfacePlacement: {
        mode: "inset",
        offset_x_mm: -7,
        offset_y_mm: 13,
        scale: 0.45,
        rotation_deg: -22,
        inset_mm: 3,
      },
      sessionId: "stale-session",
      previewImageUrl: "/api/files/stale-preview.png",
      downloadUrl: "/api/files/stale.3mf",
    } as never);

    const svgFile = new File(["<svg/>"], "vectorized.svg", { type: "image/svg+xml" });
    useConverterStore.getState().loadVectorizedSvgIntoConverter(svgFile);

    const state = useConverterStore.getState();
    expect(state.imageFile).toBe(svgFile);
    expect(state.modelSurfacePlacement).toEqual({
      mode: "edge_to_edge",
      offset_x_mm: 0,
      offset_y_mm: 0,
      scale: 1,
      rotation_deg: 0,
      inset_mm: 0,
    });
    expect(state.sessionId).toBeNull();
    expect(state.previewImageUrl).toBeNull();
    expect(state.downloadUrl).toBeNull();
  });

  it("invalidates the stale preview session when model rotation changes", () => {
    useConverterStore.setState({
      sessionId: "stale-session",
      previewImageUrl: "/api/files/stale-preview.png",
      originalPreviewUrl: "/api/files/stale-original.png",
      previewGlbUrl: "/api/files/stale-preview.glb",
      modelUrl: "/api/files/stale-model.glb",
      downloadUrl: "/api/files/stale.3mf",
      threemfDiskPath: "/tmp/stale.3mf",
      palette: [{ quantized_hex: "ff0000" }],
    } as never);

    useConverterStore.getState().updateModelSurfaceModelRotation({
      x_deg: 15,
      y_deg: 30,
      z_deg: 45,
    });

    const state = useConverterStore.getState();
    expect(state.modelSurfaceModelRotation).toEqual({
      x_deg: 15,
      y_deg: 30,
      z_deg: 45,
    });
    expect(state.sessionId).toBeNull();
    expect(state.previewImageUrl).toBeNull();
    expect(state.originalPreviewUrl).toBeNull();
    expect(state.previewGlbUrl).toBeNull();
    expect(state.modelUrl).toBeNull();
    expect(state.downloadUrl).toBeNull();
    expect(state.threemfDiskPath).toBeNull();
    expect(state.palette).toEqual([]);
  });
});
