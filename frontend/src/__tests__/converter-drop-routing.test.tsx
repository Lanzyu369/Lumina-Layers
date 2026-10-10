/**
 * Global converter drop routing tests.
 * 转换页全局拖放路由测试。
 *
 * Guards the extraction of window-level STL/OBJ vs image drop routing into
 * useConverterDropRouting: the hook is mounted once at the WidgetWorkspace
 * level (not inside any panel), so a model drop must still reach
 * uploadModelSurfaceFile even when every dock widget — including the model
 * texture panel itself — is hidden (WidgetPanel unmounts invisible widgets).
 * 守护窗口级 STL/OBJ 与图片拖放路由的抽取：钩子挂载在 WidgetWorkspace 层级
 * （不在任何面板内部），因此即使所有 dock 面板（包括模型贴图面板）被隐藏
 * （WidgetPanel 会卸载不可见面板），模型拖放仍必须到达 uploadModelSurfaceFile。
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  ConverterDropIntentBanner,
  useConverterDropRouting,
} from "../hooks/useConverterDropRouting";
import { useConverterStore } from "../stores/converter";
import { DEFAULT_LAYOUT, useWidgetStore } from "../stores/widgetStore";
import * as converterApi from "../api/converter";
import {
  ColorMode as ColorModeEnum,
  StructureMode as StructureModeEnum,
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

/**
 * Minimal harness mirroring how WidgetWorkspace mounts the hook once at the
 * converter-tab level. No dock panels are rendered at all here — exactly the
 * situation after a user hides every widget.
 * 最小化测试挂载点，镜像 WidgetWorkspace 在转换页层级挂载钩子的方式。
 * 这里完全不渲染任何 dock 面板——正是用户隐藏全部面板后的情形。
 */
function DropRoutingHarness() {
  const { dropImportIntent } = useConverterDropRouting();
  return <ConverterDropIntentBanner intent={dropImportIntent} />;
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
  // Simulate "every widget hidden": flip all widgets to visible=false while
  // keeping them registered, like persisted panel-controls state would.
  // 模拟「所有面板已隐藏」：保留注册但把所有 widget 置为 visible=false，
  // 与持久化的面板控件状态一致。
  const hiddenWidgets = Object.fromEntries(
    Object.entries(DEFAULT_LAYOUT).map(([id, layout]) => [
      id,
      { ...layout, visible: false },
    ]),
  ) as typeof DEFAULT_LAYOUT;
  useWidgetStore.setState({
    widgets: hiddenWidgets,
    isDragging: false,
    activeWidgetId: null,
    activeTab: "converter",
  });
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
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useConverterDropRouting", () => {
  it("routes a model drop to uploadModelSurfaceFile while every widget is hidden", async () => {
    const file = new File(["solid"], "pegboard.STL", {
      type: "application/octet-stream",
    });

    render(<DropRoutingHarness />);

    fireEvent.drop(window, {
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

  it("routes an image drop to image upload and never into the model flow", async () => {
    const file = new File(["img"], "artwork.jpg", { type: "image/jpeg" });

    render(<DropRoutingHarness />);

    fireEvent.drop(window, {
      dataTransfer: {
        files: [file],
        types: ["Files"],
      },
    });

    await waitFor(() => {
      expect(useConverterStore.getState().imageFile).toBe(file);
    });
    expect(converterApi.uploadModelSurface).not.toHaveBeenCalled();
    expect(useConverterStore.getState().modelSurfaceFile).toBeNull();
  });

  it("routes mixed model + image drops into both flows", async () => {
    const modelFile = new File(["solid"], "pegboard.obj", {
      type: "application/octet-stream",
    });
    const imageFile = new File(["img"], "artwork.png", { type: "image/png" });

    render(<DropRoutingHarness />);

    fireEvent.drop(window, {
      dataTransfer: {
        files: [modelFile, imageFile],
        types: ["Files"],
      },
    });

    await waitFor(() => {
      expect(converterApi.uploadModelSurface).toHaveBeenCalledWith(modelFile);
      expect(useConverterStore.getState().imageFile).toBe(imageFile);
    });
    expect(useConverterStore.getState().modelSurfaceEnabled).toBe(true);
    expect(useConverterStore.getState().modelSurfaceFile).toBe(modelFile);
  });

  it("skips drops landing inside the unified uploader zone for image-only drags", () => {
    const imageFile = new File(["img"], "artwork.png", { type: "image/png" });

    render(
      <>
        <div data-unified-uploader-drop-zone="true" data-testid="uploader-zone" />
        <DropRoutingHarness />
      </>,
    );

    const dropEvent = new Event("drop", { bubbles: true, cancelable: true }) as DragEvent;
    Object.defineProperty(dropEvent, "dataTransfer", {
      value: { files: [imageFile], types: ["Files"] },
    });
    Object.defineProperty(dropEvent, "target", {
      value: screen.getByTestId("uploader-zone"),
    });
    fireEvent(window, dropEvent);

    expect(useConverterStore.getState().imageFile).not.toBe(imageFile);
    expect(converterApi.uploadModelSurface).not.toHaveBeenCalled();
  });

  it("skips drops landing inside the model surface upload zone", () => {
    const file = new File(["solid"], "pegboard.stl", {
      type: "application/octet-stream",
    });

    render(
      <>
        <div data-model-surface-drop-zone="true" data-testid="surface-zone" />
        <DropRoutingHarness />
      </>,
    );

    const dropEvent = new Event("drop", { bubbles: true, cancelable: true }) as DragEvent;
    Object.defineProperty(dropEvent, "dataTransfer", {
      value: { files: [file], types: ["Files"] },
    });
    Object.defineProperty(dropEvent, "target", {
      value: screen.getByTestId("surface-zone"),
    });
    fireEvent(window, dropEvent);

    // The zone-local handler owns this drop; global routing must not double-handle.
    // 该拖放由面板本地处理器负责；全局路由不得重复处理。
    expect(converterApi.uploadModelSurface).not.toHaveBeenCalled();
  });

  it("keeps a pure image drop on a local file zone out of the main converter image flow (heightmap regression)", () => {
    const imageFile = new File(["heightmap"], "heightmap.png", { type: "image/png" });

    render(
      <>
        <div data-local-file-drop-zone="true" data-testid="local-zone" />
        <DropRoutingHarness />
      </>,
    );

    const dropEvent = new Event("drop", { bubbles: true, cancelable: true }) as DragEvent;
    Object.defineProperty(dropEvent, "dataTransfer", {
      value: { files: [imageFile], types: ["Files"] },
    });
    Object.defineProperty(dropEvent, "target", {
      value: screen.getByTestId("local-zone"),
    });
    fireEvent(window, dropEvent);

    // Global routing must leave pure image drops on local zones to their local handler.
    // 纯图片落在局部上传区时，全局路由必须放行，交由局部处理器（如高度图）处理。
    expect(useConverterStore.getState().imageFile).toBeNull();
    expect(converterApi.uploadModelSurface).not.toHaveBeenCalled();
  });

  it("still routes model files dropped on a local image uploader to model surface upload", () => {
    const model = new File(["solid"], "relief-source.stl", { type: "application/octet-stream" });

    render(
      <>
        <div data-local-file-drop-zone="true" data-testid="local-zone" />
        <DropRoutingHarness />
      </>,
    );

    const dropEvent = new Event("drop", { bubbles: true, cancelable: true }) as DragEvent;
    Object.defineProperty(dropEvent, "dataTransfer", {
      value: { files: [model], types: ["Files"] },
    });
    Object.defineProperty(dropEvent, "target", {
      value: screen.getByTestId("local-zone"),
    });
    fireEvent(window, dropEvent);

    expect(converterApi.uploadModelSurface).toHaveBeenCalledWith(model);
    expect(useConverterStore.getState().imageFile).toBeNull();
  });

  it("suppresses the global drag hint for pure image drags over a local file zone", () => {
    const imageFile = new File(["heightmap"], "heightmap.png", { type: "image/png" });

    render(
      <>
        <div data-local-file-drop-zone="true" data-testid="local-zone" />
        <DropRoutingHarness />
      </>,
    );

    const target = screen.getByTestId("local-zone");
    const dragEvent = new Event("dragover", { bubbles: true, cancelable: true }) as DragEvent;
    Object.defineProperty(dragEvent, "dataTransfer", {
      value: { files: [imageFile], types: ["Files"] },
    });
    Object.defineProperty(dragEvent, "target", { value: target });
    fireEvent(window, dragEvent);

    expect(screen.queryByRole("status", { name: "拖拽导入文件" })).not.toBeInTheDocument();
  });

  it("shows the floating drag hint for model then image drags", () => {
    const modelFile = new File(["solid"], "pegboard.stl", {
      type: "application/octet-stream",
    });
    const imageFile = new File(["img"], "artwork.png", { type: "image/png" });

    render(<DropRoutingHarness />);

    fireEvent.dragOver(window, {
      dataTransfer: {
        files: [modelFile],
        types: ["Files"],
      },
    });

    expect(screen.getByRole("status", { name: "拖拽导入文件" })).toHaveTextContent("导入模型");

    fireEvent.dragOver(window, {
      dataTransfer: {
        files: [imageFile],
        types: ["Files"],
      },
    });

    expect(screen.getByRole("status", { name: "拖拽导入文件" })).toHaveTextContent("导入图片");
  });
});
