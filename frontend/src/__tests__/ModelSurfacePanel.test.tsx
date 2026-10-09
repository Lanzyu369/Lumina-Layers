/**
 * Focused tests for the standalone Model Surface (model texture) panel.
 * 独立「模型贴图」面板的针对性测试。
 *
 * Covers the switch-driven enable flag, on/off content gating, drop-zone
 * routing, status/error banner paths, and the single-sided structure guard
 * migrated from BasicSettings after the widget extraction.
 * 覆盖开关驱动的启用标记、开/关内容门控、拖放区路由、状态/错误横幅路径，
 * 以及 Widget 拆分后从 BasicSettings 迁移来的单面结构守护。
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import ModelSurfacePanel from "../components/sections/ModelSurfacePanel";
import { useConverterStore } from "../stores/converter";
import * as converterApi from "../api/converter";
import {
  StructureMode as StructureModeEnum,
  ColorMode as ColorModeEnum,
  ModelingMode as ModelingModeEnum,
} from "../api/types";

vi.mock("../api/converter", async () => {
  const actual = await vi.importActual<typeof import("../api/converter")>(
    "../api/converter",
  );
  return {
    ...actual,
    fetchLutList: vi.fn(),
    uploadModelSurface: vi.fn(),
  };
});

function resetConverterStore() {
  useConverterStore.setState({
    imageFile: null,
    imagePreviewUrl: null,
    source_version: "legacy",
    color_mode: ColorModeEnum.FOUR_COLOR_RYBW,
    structure_mode: StructureModeEnum.SINGLE_SIDED,
    modeling_mode: ModelingModeEnum.HIGH_FIDELITY,
    modelSurfaceEnabled: false,
    modelSurfaceFile: null,
    modelSurfacePreviewUrl: null,
    modelSurfaceModelFileId: null,
    modelSurfaceSummary: null,
    modelSurfaceSelectionId: null,
    modelSurfaceSelection: null,
    modelSurfaceFootprint: null,
    modelSurfaceCandidates: [],
    modelSurfaceLoading: false,
    modelSurfaceSelecting: false,
    modelSurfaceError: null,
    modelSurfaceWarnings: [],
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(converterApi.uploadModelSurface).mockResolvedValue({
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
    surface_candidates: [],
    warnings: [],
  });
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:model");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  resetConverterStore();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ModelSurfacePanel", () => {
  it("starts off with only the switch row visible and toggles the store flag", () => {
    render(<ModelSurfacePanel />);

    const enableSwitch = screen.getByRole("switch", { name: "模型贴图" });
    expect(enableSwitch).toHaveAttribute("aria-checked", "false");
    expect(
      screen.queryByRole("button", { name: "拖拽 STL/OBJ 模型到此处或点击上传" }),
    ).not.toBeInTheDocument();

    fireEvent.click(enableSwitch);

    expect(useConverterStore.getState().modelSurfaceEnabled).toBe(true);
    expect(screen.getByRole("switch", { name: "模型贴图" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("reveals the sub-controls only while enabled and hides them again when disabled", () => {
    const { rerender } = render(<ModelSurfacePanel />);
    expect(
      screen.queryByRole("button", { name: "拖拽 STL/OBJ 模型到此处或点击上传" }),
    ).not.toBeInTheDocument();

    act(() => {
      useConverterStore.setState({ modelSurfaceEnabled: true });
    });
    rerender(<ModelSurfacePanel />);

    expect(
      screen.getByRole("button", { name: "拖拽 STL/OBJ 模型到此处或点击上传" }),
    ).toBeInTheDocument();
    expect(screen.getByText("支持 STL / OBJ；导入后在 3D 预览里旋转模型并选择贴图平面。")).toBeInTheDocument();

    act(() => {
      useConverterStore.getState().setModelSurfaceEnabled(false);
    });
    expect(
      screen.queryByRole("button", { name: "拖拽 STL/OBJ 模型到此处或点击上传" }),
    ).not.toBeInTheDocument();
  });

  it("routes a model dropped onto its upload zone into the model texture flow", async () => {
    useConverterStore.setState({ modelSurfaceEnabled: true });
    const file = new File(["solid"], "pegboard.stl", {
      type: "application/octet-stream",
    });

    render(<ModelSurfacePanel />);

    const dropZone = screen.getByRole("button", {
      name: "拖拽 STL/OBJ 模型到此处或点击上传",
    });
    fireEvent.drop(dropZone, {
      dataTransfer: {
        files: [file],
        types: ["Files"],
      },
    });

    await waitFor(() => {
      expect(converterApi.uploadModelSurface).toHaveBeenCalledWith(file);
    });
    const state = useConverterStore.getState();
    expect(state.modelSurfaceEnabled).toBe(true);
    expect(state.modelSurfaceFile).toBe(file);
    expect(state.imageFile).toBeNull();
  });

  it("does not tell users to pick a face when model texture analysis fails", async () => {
    useConverterStore.setState({ modelSurfaceEnabled: true });
    vi.mocked(converterApi.uploadModelSurface).mockRejectedValueOnce(
      new Error("backend unavailable"),
    );
    const file = new File(["solid"], "pegboard.stl", {
      type: "application/octet-stream",
    });

    render(<ModelSurfacePanel />);

    const dropZone = screen.getByRole("button", {
      name: "拖拽 STL/OBJ 模型到此处或点击上传",
    });
    fireEvent.drop(dropZone, {
      dataTransfer: {
        files: [file],
        types: ["Files"],
      },
    });

    expect(await screen.findByText("模型分析失败")).toBeInTheDocument();
    expect(screen.queryByText("右侧点选面")).not.toBeInTheDocument();
    expect(
      screen.queryByText("请在右侧 3D 预览中旋转模型、选择或重选面；选好后再移动、旋转或缩放贴图。"),
    ).not.toBeInTheDocument();
    expect(useConverterStore.getState().modelSurfaceModelFileId).toBeNull();
  });

  it("shows error and warning banners from the store while enabled", () => {
    useConverterStore.setState({
      modelSurfaceEnabled: true,
      modelSurfaceError: "模型上传失败",
      modelSurfaceWarnings: ["单位警告"],
    });

    render(<ModelSurfacePanel />);

    expect(screen.getByText("模型上传失败")).toBeInTheDocument();
    expect(screen.getByText("单位警告")).toBeInTheDocument();
  });

  it("shows the viewer hint once a model file has been analyzed", () => {
    const file = new File(["solid"], "pegboard.obj", {
      type: "application/octet-stream",
    });
    useConverterStore.setState({
      modelSurfaceEnabled: true,
      modelSurfaceFile: file,
      modelSurfaceModelFileId: "model-file-1",
      modelSurfaceSummary: {
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
    });

    render(<ModelSurfacePanel />);

    expect(
      screen.getByText("请在右侧 3D 预览中旋转模型、选择或重选面；选好后再移动、旋转或缩放贴图。"),
    ).toBeInTheDocument();
    expect(screen.getByText("pegboard.obj")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "拖拽 STL/OBJ 模型到此处或点击更换" })).toBeInTheDocument();
  });

  it("clears the uploaded model from the clear button", () => {
    const file = new File(["solid"], "pegboard.obj", {
      type: "application/octet-stream",
    });
    useConverterStore.setState({
      modelSurfaceEnabled: true,
      modelSurfaceFile: file,
      modelSurfacePreviewUrl: "blob:model",
    });

    render(<ModelSurfacePanel />);

    fireEvent.click(screen.getByRole("button", { name: "清除" }));

    const state = useConverterStore.getState();
    expect(state.modelSurfaceFile).toBeNull();
    expect(state.modelSurfacePreviewUrl).toBeNull();
  });

  it("forces single-sided structure when enabling from double-sided", () => {
    useConverterStore.setState({
      structure_mode: StructureModeEnum.DOUBLE_SIDED,
    } as never);

    render(<ModelSurfacePanel />);

    fireEvent.click(screen.getByRole("switch", { name: "模型贴图" }));

    expect(useConverterStore.getState().structure_mode).toBe(
      StructureModeEnum.SINGLE_SIDED,
    );
  });
});
