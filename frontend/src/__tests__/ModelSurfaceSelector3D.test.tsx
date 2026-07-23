import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createEvent, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import * as THREE from "three";
import type { ModelSurfacePlacement } from "../stores/converter";
import { useSettingsStore } from "../stores/settingsStore";
import {
  computeArtworkCanvasTransform,
  computeArtworkPlacementDrawSize,
  computeArtworkPlacementDrawSizeMm,
} from "../components/modelSurface/artworkPlacement";
import {
  CanvasOverlayHtml,
  getCanvasOverlayFrame,
} from "../components/modelSurface/overlayLayout";

const mockParseStl = vi.fn((_buffer: ArrayBuffer) => new THREE.BoxGeometry(20, 10, 2));
const mockInvalidate = vi.fn();
const mockCamera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
const mockControls = {
  target: new THREE.Vector3(),
  maxDistance: 0,
  minDistance: 0,
  enabled: true,
  update: vi.fn(),
};
const mockGl: { domElement?: HTMLCanvasElement } = {};
const mockUseFrame = vi.hoisted(() => vi.fn());
const mockHtmlProps = vi.hoisted(() => [] as Array<Record<string, unknown>>);

vi.mock("three/examples/jsm/loaders/STLLoader.js", () => ({
  STLLoader: class {
    parse(buffer: ArrayBuffer) {
      return mockParseStl(buffer);
    }
  },
}));

vi.mock("three/examples/jsm/loaders/OBJLoader.js", () => ({
  OBJLoader: class {
    parse() {
      return new THREE.Group();
    }
  },
}));

vi.mock("@react-three/fiber", () => ({
  useFrame: mockUseFrame,
  useThree: (selector?: (state: Record<string, unknown>) => unknown) => {
    const state = {
      camera: mockCamera,
      controls: mockControls,
      invalidate: mockInvalidate,
      gl: mockGl,
    };
    return selector ? selector(state) : state;
  },
}));

vi.mock("@react-three/drei", () => ({
  Html: (props: { children?: React.ReactNode }) => {
    mockHtmlProps.push(props as Record<string, unknown>);
    return <div data-testid="mock-html">{props.children}</div>;
  },
}));

import ModelSurfaceSelector3D, {
  computeModelRotationDragDegrees,
  findSelectableCandidateFromModelPoint,
  findNearestRotationAxisScreenHit,
  getReadableSurfaceCameraDirection,
  getReadableSurfaceCameraUp,
  getViewCubeCameraTransform,
  getViewCubeCornerHitZones,
  getViewCubeEdgeHitZones,
  getViewCubeFaceHitZones,
  getRotationGizmoRadius,
  getRotationHitTargetTubeRadius,
  getRotationPointerResultFromPointOrRay,
  getRotationTickSegmentRadii,
  getModelBodyRaycastProps,
  applySurfaceMaterial,
  updateSurfaceMaterialColor,
  getSurfaceFocusRadius,
  computeArtworkPlacementDragUpdate,
  computeArtworkCoverDrawSize,
  computeSurfaceArtworkCanvasSize,
  computeSurfacePreviewOffsetMm,
  configureSurfaceArtworkTextureForPreview,
  createSurfaceArtworkGeometry,
  createSurfaceArtworkInteractionGeometry,
  ensureCameraDepthClipping,
  createSurfaceHitShape,
  findSelectableCandidateFromPointerRay,
  insetRingTowardPoint,
  pointToSurfaceLocal,
  prepareStlPreviewGeometry,
  rotateModelPointAroundPivot,
  SURFACE_ARTWORK_MATERIAL_DEPTH_FLAGS,
  SURFACE_MARKER_MATERIAL_DEPTH_FLAGS,
} from "../components/ModelSurfaceSelector3D";

function requireModelSurfaceBody(): HTMLElement {
  const element = document.querySelector('mesh[name="model-surface-body"]');
  expect(element).not.toBeNull();
  return element as HTMLElement;
}

function findArtworkTextureMaterial(): HTMLElement | null {
  return (Array.from(document.querySelectorAll("meshBasicMaterial")).find((element) => {
    const htmlElement = element as HTMLElement;
    return (
      htmlElement.getAttribute("polygonOffsetFactor") === "-2" ||
      htmlElement.getAttribute("polygonoffsetfactor") === "-2"
    );
  }) as HTMLElement | undefined) ?? null;
}

function fireModelSurfacePointerDown(
  modelMesh: HTMLElement,
  point = new THREE.Vector3(5, 0, 1),
): void {
  const event = createEvent.pointerDown(modelMesh);
  Object.defineProperty(event, "point", { value: point });
  fireEvent(modelMesh, event);
}

function fireModelSurfacePointerMove(
  modelMesh: HTMLElement,
  point = new THREE.Vector3(5, 0, 1),
): void {
  const event = createEvent.pointerMove(modelMesh);
  Object.defineProperty(event, "point", { value: point });
  fireEvent(modelMesh, event);
}

describe("ModelSurfaceSelector3D", () => {
  beforeEach(() => {
    useSettingsStore.setState({ theme: "light" });
    mockUseFrame.mockClear();
    mockHtmlProps.length = 0;
    mockCamera.near = 0.1;
    mockCamera.far = 2000;
    mockCamera.fov = 45;
    mockCamera.position.set(0, 0, 500);
    mockCamera.lookAt(0, 0, 0);
    mockCamera.updateProjectionMatrix();
    mockCamera.updateMatrixWorld(true);
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    Object.defineProperty(HTMLElement.prototype, "updateWorldMatrix", {
      configurable: true,
      value: vi.fn(),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    useSettingsStore.setState({ theme: "light" });
    window.localStorage.removeItem("lumina-model-surface-toolbar-layout-v1");
    window.localStorage.removeItem("lumina-model-surface-rotation-panel-layout-v1");
    mockParseStl.mockClear();
    mockInvalidate.mockClear();
    mockControls.enabled = true;
    mockControls.update.mockClear();
    mockGl.domElement = undefined;
    mockUseFrame.mockClear();
    mockHtmlProps.length = 0;
  });

  it("preserves artwork aspect ratio when fitting edge-to-edge onto a square face", () => {
    expect(computeArtworkCoverDrawSize({
      sourceWidth: 80,
      sourceHeight: 40,
      availableWidth: 80,
      availableHeight: 80,
      scale: 1,
    })).toEqual({
      width: 160,
      height: 80,
    });
  });

  it("contains inset artwork using its rotated bounding box in pixels and millimetres", () => {
    const rotationDeg = 17;
    const rotationRadians = THREE.MathUtils.degToRad(rotationDeg);
    const assertContained = (
      size: { width: number; height: number },
      availableWidth: number,
      availableHeight: number,
      tolerance: number,
    ) => {
      const rotatedWidth =
        Math.abs(size.width * Math.cos(rotationRadians))
        + Math.abs(size.height * Math.sin(rotationRadians));
      const rotatedHeight =
        Math.abs(size.width * Math.sin(rotationRadians))
        + Math.abs(size.height * Math.cos(rotationRadians));
      expect(rotatedWidth).toBeLessThanOrEqual(availableWidth + tolerance);
      expect(rotatedHeight).toBeLessThanOrEqual(availableHeight + tolerance);
      expect(Math.max(rotatedWidth, rotatedHeight)).toBeGreaterThanOrEqual(
        Math.max(availableWidth, availableHeight) - tolerance,
      );
    };

    const pixelSize = computeArtworkPlacementDrawSize({
      sourceWidth: 40,
      sourceHeight: 80,
      availableWidth: 160,
      availableHeight: 160,
      scale: 1,
      mode: "inset",
      rotationDeg,
    });
    const millimetreSize = computeArtworkPlacementDrawSizeMm({
      sourceWidth: 40,
      sourceHeight: 80,
      availableWidthMm: 16,
      availableHeightMm: 16,
      scale: 1,
      mode: "inset",
      rotationDeg,
    });

    assertContained(pixelSize, 160, 160, 1);
    assertContained(millimetreSize, 16, 16, 0.001);
  });

  it("covers the surface corners with rotated edge-to-edge artwork", () => {
    const rotationDeg = 17;
    const rotationRadians = THREE.MathUtils.degToRad(rotationDeg);
    const size = computeArtworkPlacementDrawSize({
      sourceWidth: 40,
      sourceHeight: 40,
      availableWidth: 160,
      availableHeight: 160,
      scale: 1,
      mode: "edge_to_edge",
      rotationDeg,
    });
    const requiredLocalWidth =
      Math.abs(160 * Math.cos(rotationRadians))
      + Math.abs(160 * Math.sin(rotationRadians));
    const requiredLocalHeight =
      Math.abs(160 * Math.sin(rotationRadians))
      + Math.abs(160 * Math.cos(rotationRadians));

    expect(size.width).toBeGreaterThanOrEqual(requiredLocalWidth);
    expect(size.height).toBeGreaterThanOrEqual(requiredLocalHeight);
  });

  it("keeps screen-fixed overlays above the 3D scene stacking context", () => {
    const canvas = document.createElement("canvas");
    canvas.getBoundingClientRect = vi.fn(
      () =>
        ({
          left: 0,
          top: 100,
          width: 1000,
          height: 700,
          right: 1000,
          bottom: 800,
          x: 0,
          y: 100,
          toJSON: () => ({}),
        }) as DOMRect,
    );
    mockGl.domElement = canvas;

    render(
      <CanvasOverlayHtml>
        <div>overlay content</div>
      </CanvasOverlayHtml>,
    );

    expect(document.querySelector('[data-model-surface-canvas-overlay="fixed"]')).not.toBeNull();
    expect(mockHtmlProps.at(-1)?.wrapperClass).toBe("z-40");
    expect(mockHtmlProps.at(-1)?.zIndexRange).toEqual([40, 40]);
  });

  it("uses an adaptive preview texture budget instead of a fixed large-image cap", () => {
    const defaultPreview = computeSurfaceArtworkCanvasSize(1200, 800);
    const largeViewportPreview = computeSurfaceArtworkCanvasSize(1200, 800, {
      viewportLongestSidePx: 2600,
      devicePixelRatio: 1,
      maxTextureSize: 4096,
      maxTexturePixels: 4096 * 4096,
    });

    expect(defaultPreview.widthPx).toBeGreaterThan(1400);
    expect(largeViewportPreview.widthPx).toBeGreaterThan(defaultPreview.widthPx);
    expect(largeViewportPreview.widthPx).toBeLessThanOrEqual(4096);
    expect(largeViewportPreview.heightPx).toBeLessThanOrEqual(4096);
  });

  it("clips selected artwork geometry around pegboard holes instead of relying on transparent pixels", () => {
    const surface = {
      frame: {
        origin: new THREE.Vector3(0, 0, 1),
        normal: new THREE.Vector3(0, 0, 1),
        uAxis: new THREE.Vector3(1, 0, 0),
        vAxis: new THREE.Vector3(0, 1, 0),
      },
      boundsMin: [-10, -5] as [number, number],
      boundsMax: [10, 5] as [number, number],
      widthMm: 20,
      heightMm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [[[-2, -1], [2, -1], [2, 1], [-2, 1], [-2, -1]]] as [number, number][][],
    };
    const geometry = createSurfaceArtworkGeometry(surface);
    const material = new THREE.MeshBasicMaterial({ side: THREE.DoubleSide });
    const mesh = new THREE.Mesh(geometry, material);

    const holeRay = new THREE.Raycaster(
      new THREE.Vector3(0, 0, 10),
      new THREE.Vector3(0, 0, -1),
    );
    const artworkRay = new THREE.Raycaster(
      new THREE.Vector3(5, 0, 10),
      new THREE.Vector3(0, 0, -1),
    );
    const uv = geometry.getAttribute("uv");

    expect(holeRay.intersectObject(mesh)).toHaveLength(0);
    expect(artworkRay.intersectObject(mesh).length).toBeGreaterThan(0);
    expect(uv.count).toBe(geometry.getAttribute("position").count);
    for (let index = 0; index < uv.count; index += 1) {
      expect(uv.getX(index)).toBeGreaterThanOrEqual(0);
      expect(uv.getX(index)).toBeLessThanOrEqual(1);
      expect(uv.getY(index)).toBeGreaterThanOrEqual(0);
      expect(uv.getY(index)).toBeLessThanOrEqual(1);
    }

    geometry.dispose();
    material.dispose();
  });

  it("keeps an artwork interaction surface over holes so dragging is not stolen by orbit controls", () => {
    const surface = {
      frame: {
        origin: new THREE.Vector3(0, 0, 1),
        normal: new THREE.Vector3(0, 0, 1),
        uAxis: new THREE.Vector3(1, 0, 0),
        vAxis: new THREE.Vector3(0, 1, 0),
      },
      boundsMin: [-10, -5] as [number, number],
      boundsMax: [10, 5] as [number, number],
      widthMm: 20,
      heightMm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [[[-2, -1], [2, -1], [2, 1], [-2, 1], [-2, -1]]] as [number, number][][],
    };
    const visualGeometry = createSurfaceArtworkGeometry(surface);
    const interactionGeometry = createSurfaceArtworkInteractionGeometry(surface);
    const material = new THREE.MeshBasicMaterial({ side: THREE.DoubleSide });
    const visualMesh = new THREE.Mesh(visualGeometry, material);
    const interactionMesh = new THREE.Mesh(interactionGeometry, material);
    const holeRay = new THREE.Raycaster(
      new THREE.Vector3(0, 0, 10),
      new THREE.Vector3(0, 0, -1),
    );

    expect(holeRay.intersectObject(visualMesh)).toHaveLength(0);
    expect(holeRay.intersectObject(interactionMesh).length).toBeGreaterThan(0);

    visualGeometry.dispose();
    interactionGeometry.dispose();
    material.dispose();
  });

  it("uses a stable visual offset for model-surface artwork to avoid depth shimmer", () => {
    expect(computeSurfacePreviewOffsetMm(20, 10)).toBeGreaterThanOrEqual(0.18);
    expect(computeSurfacePreviewOffsetMm(200, 200)).toBeGreaterThanOrEqual(0.35);
    expect(computeSurfacePreviewOffsetMm(1000, 1000)).toBeLessThanOrEqual(0.8);
  });

  it("recomputes camera near clipping after returning from a large model-surface view", () => {
    const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 2000);

    ensureCameraDepthClipping(camera, 8800, 100);
    expect(camera.near).toBeGreaterThan(50);

    ensureCameraDepthClipping(camera, 25, 8);
    expect(camera.near).toBeLessThan(1);
    expect(camera.near).toBeGreaterThanOrEqual(0.1);
  });

  it("keeps a bottom-facing selected surface upright by flipping the camera up vector", () => {
    const direction = getReadableSurfaceCameraDirection(new THREE.Vector3(0, 0, -1), false);
    const up = getReadableSurfaceCameraUp(
      new THREE.Vector3(0, 0, -1),
      new THREE.Vector3(0, -1, 0),
      direction,
    );

    expect(Math.abs(up.x)).toBeLessThan(0.001);
    expect(up.y).toBeGreaterThan(0.999);
    expect(Math.abs(up.z)).toBeLessThan(0.001);
  });

  it("syncs the automatic bottom-surface face-up rotation into model transform state", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const onUpdateModelRotation = vi.fn();

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady
        selecting={false}
        footprint={{
          frame: {
            origin: [0, 0, -1],
            normal: [0, 0, -1],
            u_axis: [1, 0, 0],
            v_axis: [0, -1, 0],
          },
          bounds_min: [-10, -5],
          bounds_max: [10, 5],
          bounds_width_mm: 20,
          bounds_height_mm: 10,
          outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]],
          holes: [],
        }}
        onSelectFace={vi.fn()}
        onUpdateModelRotation={onUpdateModelRotation}
      />,
    );

    await waitFor(() => {
      expect(onUpdateModelRotation).toHaveBeenCalledWith({
        x_deg: 0,
        y_deg: 180,
        z_deg: 0,
      });
    });
  });

  it("keeps the uploaded model loaded when selection state changes", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    const arrayBufferSpy = vi
      .spyOn(file, "arrayBuffer")
      .mockResolvedValue(new ArrayBuffer(16));

    const { rerender } = render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    await waitFor(() => expect(arrayBufferSpy).toHaveBeenCalledTimes(1));

    rerender(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    await waitFor(() => expect(arrayBufferSpy).toHaveBeenCalledTimes(1));
    expect(mockParseStl).toHaveBeenCalledTimes(1);
  });

  it("reuses a parsed STL preview when the selector remounts with the same file", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    const arrayBufferSpy = vi
      .spyOn(file, "arrayBuffer")
      .mockResolvedValue(new ArrayBuffer(16));

    const { unmount } = render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    await waitFor(() => requireModelSurfaceBody());
    expect(arrayBufferSpy).toHaveBeenCalledTimes(1);
    expect(mockParseStl).toHaveBeenCalledTimes(1);

    unmount();

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    await waitFor(() => requireModelSurfaceBody());
    expect(arrayBufferSpy).toHaveBeenCalledTimes(1);
    expect(mockParseStl).toHaveBeenCalledTimes(1);
  });

  it("shows explicit model controls for rotating the model and reselecting the surface", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    expect(await screen.findByRole("button", { name: "旋转模型" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重选面" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "覆面编辑" }));
    expect(screen.getByRole("button", { name: "移动贴图" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "旋转贴图" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "缩放贴图" })).toBeInTheDocument();
  });

  it("uses a slicer-style floating secondary tab toolbar for model, artwork, and view controls", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const onBedGridVisibleChange = vi.fn();

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        bedGridVisible
        onBedGridVisibleChange={onBedGridVisibleChange}
        onSelectFace={vi.fn()}
      />,
    );

    const tabList = await screen.findByRole("tablist", { name: "模型覆面工具组" });
    const toolbarAnchor = tabList.closest('[data-model-surface-toolbar-anchor="scene-floating"]');
    const toolbarShell = tabList.closest('[data-model-surface-toolbar-shell="floating-command-band"]');
    expect(toolbarAnchor).not.toBeNull();
    expect(toolbarAnchor).toHaveClass("inset-0");
    expect(toolbarShell).not.toBeNull();
    expect(toolbarShell).toHaveAttribute("data-model-surface-toolbar-snap", "top-left");
    expect(toolbarShell).toHaveClass("rounded-[22px]");
    expect(tabList).toHaveAttribute("data-model-surface-toolbar-layout", "slicer-top-tabs");
    expect(screen.getByRole("button", { name: "拖动覆面工具条" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "收起覆面工具条" })).toBeInTheDocument();
    expect(within(tabList).getByRole("tab", { name: "模型操作" })).toHaveAttribute("aria-selected", "true");
    expect(within(tabList).getByRole("tab", { name: "覆面编辑" })).toHaveAttribute("aria-selected", "false");
    expect(within(tabList).getByRole("tab", { name: "视图" })).toHaveAttribute("aria-selected", "false");

    const secondaryToolbar = screen.getByRole("toolbar", { name: "模型覆面二级工具栏" });
    expect(secondaryToolbar).toHaveAttribute("data-model-surface-toolbar-row", "secondary");
    expect(secondaryToolbar).toHaveClass("w-full");
    expect(secondaryToolbar).toHaveClass("justify-center");
    expect(secondaryToolbar).toHaveClass("overflow-x-auto");
    expect(secondaryToolbar).not.toHaveClass("flex-wrap");
    const rotateModelButton = within(secondaryToolbar).getByRole("button", { name: "旋转模型" });
    expect(rotateModelButton).toBeInTheDocument();
    expect(rotateModelButton).toHaveAttribute("data-model-surface-tool-button", "icon-only");
    expect(rotateModelButton).toHaveClass("w-8");
    expect(rotateModelButton).not.toHaveClass("min-w-[4.5rem]");
    expect(rotateModelButton.querySelector("span")).toHaveClass("sr-only");
    expect(within(secondaryToolbar).getByRole("button", { name: "选择平面" })).toBeInTheDocument();

    fireEvent.click(within(tabList).getByRole("tab", { name: "覆面编辑" }));

    expect(within(tabList).getByRole("tab", { name: "覆面编辑" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("toolbar", { name: "模型覆面二级工具栏" })).toHaveTextContent("移动贴图");
    expect(screen.getByRole("toolbar", { name: "模型覆面二级工具栏" })).toHaveTextContent("旋转贴图");
    expect(screen.getByRole("toolbar", { name: "模型覆面二级工具栏" })).toHaveTextContent("缩放贴图");

    fireEvent.click(within(tabList).getByRole("tab", { name: "视图" }));

    const viewToolbar = screen.getByRole("toolbar", { name: "模型覆面二级工具栏" });
    expect(viewToolbar).toHaveTextContent("默认视图");
    expect(viewToolbar).toHaveTextContent("适配视图");
    expect(within(viewToolbar).getByRole("button", { name: "缩放按钮" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(viewToolbar).getByRole("button", { name: "坐标轴" })).toHaveAttribute("aria-pressed", "true");
    expect(within(viewToolbar).getByRole("button", { name: "网格线" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "显示选项" })).not.toBeInTheDocument();

    fireEvent.click(within(viewToolbar).getByRole("button", { name: "网格线" }));

    expect(onBedGridVisibleChange).toHaveBeenCalledWith(false);
  });

  it("exposes edge-to-edge and inset placement controls in the artwork toolbar", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const onUpdatePlacement = vi.fn();
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [],
    };

    render(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady
        selecting={false}
        footprint={footprint}
        placement={{
          mode: "inset",
          offset_x_mm: 0,
          offset_y_mm: 0,
          scale: 1,
          rotation_deg: 0,
          inset_mm: 1.5,
        }}
        onSelectFace={vi.fn()}
        onUpdatePlacement={onUpdatePlacement}
      />,
    );

    fireEvent.click(await screen.findByRole("tab", { name: "覆面编辑" }));
    const toolbar = screen.getByRole("toolbar", { name: "模型覆面二级工具栏" });
    const edgeButton = within(toolbar).getByRole("button", { name: "铺满" });
    const insetButton = within(toolbar).getByRole("button", { name: "内缩" });
    const insetInput = within(toolbar).getByRole("spinbutton", { name: "内缩距离" });

    expect(edgeButton).toHaveAttribute("aria-pressed", "false");
    expect(insetButton).toHaveAttribute("aria-pressed", "true");
    expect(insetInput).toHaveValue(1.5);

    fireEvent.click(edgeButton);
    expect(onUpdatePlacement).toHaveBeenCalledWith({ mode: "edge_to_edge" });

    fireEvent.change(insetInput, { target: { value: "2.4" } });
    expect(onUpdatePlacement).toHaveBeenCalledWith({ inset_mm: 2.4 });
  });

  it("defaults the selected-surface toolbar away from the top-center work area", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [],
    };

    render(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady
        selecting={false}
        footprint={footprint}
        onSelectFace={vi.fn()}
        onUpdatePlacement={vi.fn()}
      />,
    );

    const shell = await waitFor(() => {
      const element = document.querySelector('[data-model-surface-toolbar-shell="floating-command-band"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    expect(shell).toHaveAttribute("data-model-surface-toolbar-snap", "top-left");
  });

  it("shows slicer-style surface toolbar hover explanations over the 3D canvas", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    const rotateModelButton = await screen.findByRole("button", { name: "旋转模型" });
    fireEvent.mouseEnter(rotateModelButton.parentElement ?? rotateModelButton);

    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("旋转模型");
    expect(tooltip).toHaveTextContent("围绕模型中心旋转");
    expect(rotateModelButton).toHaveAttribute("title", expect.stringContaining("围绕模型中心旋转"));
  });

  it("shows reusable hover explanations for toolbar chrome and surface selection modes", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        surfaceCandidates={[
          {
            id: "surface-4",
            face_index: 4,
            face_count: 2,
            area_mm2: 200,
            normal: [0, 0, 1],
            footprint: {
              frame: {
                origin: [0, 0, 1],
                normal: [0, 0, 1],
                u_axis: [1, 0, 0],
                v_axis: [0, 1, 0],
              },
              bounds_min: [-10, -5],
              bounds_max: [10, 5],
              bounds_width_mm: 20,
              bounds_height_mm: 10,
              outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]],
              holes: [],
            },
          },
        ]}
        onSelectFace={vi.fn()}
      />,
    );

    const dragHandle = await screen.findByRole("button", { name: "拖动覆面工具条" });
    fireEvent.mouseEnter(dragHandle);

    const dragTooltip = await screen.findByRole("tooltip");
    expect(dragTooltip).toHaveTextContent("拖动覆面工具条");
    expect(dragTooltip).toHaveTextContent("拖动后会吸附到视口边缘或角落");

    fireEvent.mouseLeave(dragHandle);

    const collapseButton = screen.getByRole("button", { name: "收起覆面工具条" });
    fireEvent.mouseEnter(collapseButton);

    await waitFor(() => {
      const tooltips = screen.getAllByRole("tooltip");
      expect(tooltips.some((tooltip) => tooltip.textContent?.includes("收起覆面工具条"))).toBe(true);
      expect(tooltips.some((tooltip) => tooltip.textContent?.includes("收起二级工具"))).toBe(true);
    });

    fireEvent.mouseLeave(collapseButton);

    const groupedModeButton = screen.getByRole("button", { name: "选择平面组模式" });
    fireEvent.mouseEnter(groupedModeButton);

    await waitFor(() => {
      const tooltips = screen.getAllByRole("tooltip");
      expect(tooltips.some((tooltip) => tooltip.textContent?.includes("选择平面组模式"))).toBe(true);
      expect(tooltips.some((tooltip) => tooltip.textContent?.includes("把共面的三角面"))).toBe(true);
    });
  });

  it("drags the surface toolbar to a snapped viewport corner and persists the placement", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    const canvas = document.createElement("canvas");
    canvas.style.setProperty("--lumina-left-dock-width", "332px");
    canvas.style.setProperty("--lumina-right-dock-width", "280px");
    canvas.getBoundingClientRect = vi.fn(
      () =>
        ({
          left: 0,
          top: 0,
          width: 1000,
          height: 700,
          right: 1000,
          bottom: 700,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        }) as DOMRect,
    );
    mockGl.domElement = canvas;
    expect(getCanvasOverlayFrame(null, canvas)).toMatchObject({
      leftDockWidth: "332px",
      rightDockWidth: "280px",
    });
    const rectSpy = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
      this: HTMLElement,
    ) {
      if (this.dataset.modelSurfaceToolbarShell === "floating-command-band") {
        return {
          left: 350,
          top: 12,
          width: 300,
          height: 72,
          right: 650,
          bottom: 84,
          x: 350,
          y: 12,
          toJSON: () => ({}),
        } as DOMRect;
      }
      return {
        left: 0,
        top: 0,
        width: 1000,
        height: 700,
        right: 1000,
        bottom: 700,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      } as DOMRect;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    const { unmount } = render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    const dragHandle = await screen.findByRole("button", { name: "拖动覆面工具条" });
    fireEvent.pointerDown(dragHandle, { clientX: 24, clientY: 24, pointerId: 1 });
    fireEvent.pointerMove(window, { clientX: 940, clientY: 660, pointerId: 1 });
    fireEvent.pointerUp(window, { clientX: 940, clientY: 660, pointerId: 1 });

    const shell = document.querySelector(
      '[data-model-surface-toolbar-shell="floating-command-band"]',
    ) as HTMLElement;
    expect(shell).toHaveAttribute("data-model-surface-toolbar-snap", "bottom-right");
    expect(JSON.parse(window.localStorage.getItem("lumina-model-surface-toolbar-layout-v1") ?? "{}")).toMatchObject({
      snap: "bottom-right",
    });

    unmount();
    rectSpy.mockRestore();
    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    const restoredShell = await waitFor(() => {
      const element = document.querySelector('[data-model-surface-toolbar-shell="floating-command-band"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    expect(restoredShell).toHaveAttribute("data-model-surface-toolbar-snap", "bottom-right");
  });

  it("keeps screen-fixed surface overlays out of the Three render loop during camera movement", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    const canvas = document.createElement("canvas");
    canvas.getBoundingClientRect = vi.fn(
      () =>
        ({
          left: 0,
          top: 0,
          width: 1000,
          height: 700,
          right: 1000,
          bottom: 700,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        }) as DOMRect,
    );
    mockGl.domElement = canvas;
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      left: 0,
      top: 0,
      width: 1000,
      height: 700,
      right: 1000,
      bottom: 700,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    await screen.findByRole("button", { name: "拖动覆面工具条" });
    expect(mockUseFrame).toHaveBeenCalledTimes(1);
  });

  it("anchors screen-fixed surface overlays to viewport canvas coordinates", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    const canvas = document.createElement("canvas");
    canvas.getBoundingClientRect = vi.fn(
      () =>
        ({
          left: 100,
          top: 80,
          width: 500,
          height: 300,
          right: 600,
          bottom: 380,
          x: 100,
          y: 80,
          toJSON: () => ({}),
        }) as DOMRect,
    );
    mockGl.domElement = canvas;
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
      this: HTMLElement,
    ) {
      if (this.dataset.testid === "mock-html") {
        return {
          left: 20,
          top: 30,
          width: 500,
          height: 300,
          right: 520,
          bottom: 330,
          x: 20,
          y: 30,
          toJSON: () => ({}),
        } as DOMRect;
      }
      return {
        left: 0,
        top: 0,
        width: 500,
        height: 300,
        right: 500,
        bottom: 300,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      } as DOMRect;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    const overlay = await waitFor(() => {
      const element = document.querySelector('[data-model-surface-canvas-overlay="fixed"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    const portalHtmlProps = mockHtmlProps.find((props) => {
      const portal = props.portal as { current?: HTMLElement | null } | undefined;
      return portal?.current === document.body;
    });
    expect(portalHtmlProps).toBeDefined();
    const calculatePosition = portalHtmlProps?.calculatePosition as (() => number[]) | undefined;
    expect(calculatePosition?.()).toEqual([0, 0]);
    expect(overlay.style.position).toBe("fixed");
    expect(overlay.style.left).toBe("100px");
    expect(overlay.style.top).toBe("80px");
    expect(overlay.style.width).toBe("500px");
    expect(overlay.style.height).toBe("300px");
  });

  it("collapses the surface toolbar into a small draggable entry", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "收起覆面工具条" }));

    expect(screen.queryByRole("button", { name: "旋转模型" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "展开覆面工具条" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "拖动覆面工具条" })).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem("lumina-model-surface-toolbar-layout-v1") ?? "{}")).toMatchObject({
      collapsed: true,
    });
  });

  it("advances to the artwork toolbar after a flat surface is selected with artwork loaded", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const onSelectFace = vi.fn();
    const onUpdatePlacement = vi.fn();
    const onFitArtwork = vi.fn();
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [],
    };

    const { rerender } = render(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady={false}
        selecting={false}
        surfaceCandidates={[
          {
            id: "surface-4",
            face_index: 4,
            face_count: 2,
            area_mm2: 200,
            normal: [0, 0, 1],
            footprint,
          },
        ]}
        onSelectFace={onSelectFace}
        onUpdatePlacement={onUpdatePlacement}
        onFitArtwork={onFitArtwork}
      />,
    );

    const modelMesh = await waitFor(() => requireModelSurfaceBody());
    expect(document.querySelector('mesh[name^="model-surface-candidate-"]')).toBeNull();

    fireModelSurfacePointerDown(modelMesh);
    expect(onSelectFace).toHaveBeenCalledWith(4, "surface-4");

    rerender(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady
        selecting={false}
        footprint={footprint}
        surfaceCandidates={[
          {
            id: "surface-4",
            face_index: 4,
            face_count: 2,
            area_mm2: 200,
            normal: [0, 0, 1],
            footprint,
          },
        ]}
        onSelectFace={onSelectFace}
        onUpdatePlacement={onUpdatePlacement}
        onFitArtwork={onFitArtwork}
      />,
    );

    const tabList = screen.getByRole("tablist", { name: "模型覆面工具组" });
    await waitFor(() => {
      expect(within(tabList).getByRole("tab", { name: "覆面编辑" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
    });
    const secondaryToolbar = screen.getByRole("toolbar", { name: "模型覆面二级工具栏" });
    expect(within(secondaryToolbar).getByRole("button", { name: "移动贴图" })).toBeEnabled();
    expect(within(secondaryToolbar).getByRole("button", { name: "旋转贴图" })).toBeEnabled();
    expect(within(secondaryToolbar).getByRole("button", { name: "缩放贴图" })).toBeEnabled();
    expect(within(secondaryToolbar).getByRole("button", { name: "自适应" })).toBeEnabled();
    expect(screen.getByRole("status", { name: "已选覆面平面" })).toHaveTextContent("顶部");

    expect(screen.queryByRole("status", { name: "贴图位置读数" })).not.toBeInTheDocument();
    fireEvent.click(within(secondaryToolbar).getByRole("button", { name: "自适应" }));

    expect(onFitArtwork).toHaveBeenCalledTimes(1);
    expect(within(secondaryToolbar).getByRole("button", { name: "移动贴图" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(await screen.findByRole("status", { name: "贴图位置读数" })).toBeInTheDocument();
  });

  it("keeps default and fit-view controls in the top View toolbar instead of the view cube cluster", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    const modelGroup = await waitFor(() => {
      const element = document.querySelector('group[name="model-surface-transform"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    const initialRotation = modelGroup.getAttribute("rotation");
    const viewCubeCluster = screen.getByRole("group", { name: "视图立方体" }).parentElement;

    expect(viewCubeCluster).toHaveAttribute("data-model-view-navigator-layout", "cube-only");
    expect(document.querySelector('[data-view-cube-zoom-button="fit"]')).toBeNull();
    expect(document.querySelector('[data-view-cube-reset-button="default"]')).toBeNull();
    expect(screen.queryByRole("button", { name: "适配视图" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "视图" }));

    const viewToolbar = screen.getByRole("toolbar", { name: "模型覆面二级工具栏" });
    const viewportFitButton = within(viewToolbar).getByRole("button", { name: "适配视图" });
    const zoomToggle = within(viewToolbar).getByRole("button", { name: "缩放按钮" });
    expect(within(viewToolbar).getByRole("button", { name: "默认视图" })).toBeInTheDocument();
    expect(zoomToggle).toHaveAttribute("aria-pressed", "true");
    mockControls.update.mockClear();
    fireEvent.click(viewportFitButton);

    expect(modelGroup.getAttribute("rotation")).toBe(initialRotation);
    expect(mockControls.update).toHaveBeenCalled();

    fireEvent.click(zoomToggle);

    expect(zoomToggle).toHaveAttribute("aria-pressed", "false");
    expect(within(viewToolbar).queryByRole("button", { name: "适配视图" })).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "视图立方体" })).toBeInTheDocument();
  });

  it("integrates the XYZ axes into the translucent view cube without rendering a second bed grid", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const onBedGridVisibleChange = vi.fn();

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        bedGridVisible
        onBedGridVisibleChange={onBedGridVisibleChange}
        onSelectFace={vi.fn()}
      />,
    );

    expect(await screen.findByRole("group", { name: "视图立方体" })).toBeInTheDocument();
    const viewCube = screen.getByRole("group", { name: "视图立方体" });
    expect(screen.queryByRole("group", { name: "坐标轴指示器" })).not.toBeInTheDocument();
    expect(viewCube).toHaveAttribute("data-view-cube-layout", "integrated-navigation-cube");
    expect(viewCube).toHaveAttribute("data-view-cube-shell", "translucent-axis-cube");
    expect(viewCube).toHaveClass("bg-slate-100/38");
    expect(viewCube).toHaveClass("dark:bg-slate-950/32");
    expect(viewCube.querySelector('[data-view-cube-axis="x"]')).not.toBeNull();
    expect(viewCube.querySelector('[data-view-cube-axis="y"]')).not.toBeNull();
    expect(viewCube.querySelector('[data-view-cube-axis="z"]')).not.toBeNull();
    const viewCubeRotor = viewCube.querySelector('[data-testid="model-surface-view-cube-rotor"]');
    expect(viewCubeRotor).not.toBeNull();
    const axisLayer = viewCubeRotor?.querySelector('[data-view-cube-axis-gizmo="embedded-cube-axis"]');
    expect(axisLayer).not.toBeNull();
    expect(axisLayer).toHaveAttribute("data-view-cube-axis-anchor", "cube-corner");
    expect(axisLayer).toHaveClass("inset-0");
    expect(axisLayer).not.toHaveClass("-left-4");
    expect(axisLayer).not.toHaveClass("-top-4");
    expect(viewCube).not.toHaveClass("rounded-lg");
    expect(viewCube).not.toHaveClass("bg-slate-100/82");
    expect(screen.getByRole("button", { name: "顶部视图" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "底部视图" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "前面视图" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "后面视图" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "左面视图" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "右面视图" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "前面视图" })).toHaveAttribute(
      "data-view-cube-hit-face",
      "front",
    );
    expect(screen.getByRole("button", { name: "顶部视图" }).getAttribute("style")).toContain(
      "polygon(",
    );
    expect(viewCube.querySelector('[data-view-cube-visual-face="front"]')).not.toHaveAttribute(
      "data-view-cube-face",
    );
    expect(
      viewCube.querySelector('[data-view-cube-visual-face="front"]')?.getAttribute("style"),
    ).toContain("pointer-events: none");
    expect(viewCube.querySelector('[data-view-cube-visual-face="top"]')?.getAttribute("style")).toContain(
      "rotateX(90deg)",
    );
    expect(
      viewCube.querySelector('[data-view-cube-visual-face="bottom"]')?.getAttribute("style"),
    ).toContain(
      "rotateX(-90deg)",
    );
    fireEvent.click(screen.getByRole("tab", { name: "视图" }));

    expect(
      within(screen.getByRole("toolbar", { name: "模型覆面二级工具栏" })).getByRole("button", {
        name: "适配视图",
      }),
    ).toBeInTheDocument();
    expect(document.querySelector("axesHelper")).toBeNull();
    expect(document.querySelector("gridHelper")).toBeNull();

    const navigatorToggle = screen.getByRole("button", { name: "3D 导航器" });
    const axisToggle = screen.getByRole("button", { name: "坐标轴" });
    const gridToggle = screen.getByRole("button", { name: "网格线" });
    expect(navigatorToggle).toBeInTheDocument();
    expect(axisToggle).toBeInTheDocument();
    expect(gridToggle).toBeInTheDocument();
    expect(navigatorToggle).toHaveAttribute("aria-pressed", "true");
    expect(navigatorToggle).not.toHaveTextContent("●");
    expect(axisToggle).toHaveAttribute("aria-pressed", "true");
    expect(gridToggle).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "标签" })).toBeInTheDocument();

    fireEvent.click(axisToggle);

    expect(axisToggle).toHaveAttribute("aria-pressed", "false");
    expect(viewCube.querySelector('[data-view-cube-axis="x"]')).toBeNull();

    fireEvent.click(axisToggle);

    expect(axisToggle).toHaveAttribute("aria-pressed", "true");
    expect(viewCube.querySelector('[data-view-cube-axis="x"]')).not.toBeNull();

    fireEvent.click(gridToggle);

    expect(onBedGridVisibleChange).toHaveBeenCalledWith(false);
    expect(gridToggle).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(navigatorToggle);

    expect(navigatorToggle).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("group", { name: "视图立方体" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "模型操作" }));
    fireEvent.click(screen.getByRole("tab", { name: "模型操作" }));
    fireEvent.click(screen.getByRole("tab", { name: "模型操作" }));
    fireEvent.click(screen.getByRole("button", { name: "旋转模型" }));

    expect(document.querySelector("axesHelper")).toBeNull();
    expect(document.querySelector("gridHelper")).toBeNull();
    expect(document.querySelector('group[name="model-rotation-gizmo"]')).not.toBeNull();
    expect(
      document.querySelector('group[name="model-surface-transform"] group[name="model-rotation-gizmo"]'),
    ).toBeNull();
  });

  it("changes camera view without rotating the model when clicking the view navigator", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    const modelGroup = await waitFor(() => {
      const element = document.querySelector('group[name="model-surface-transform"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    const initialRotation = modelGroup.getAttribute("rotation");

    fireEvent.click(screen.getByRole("button", { name: "顶部视图" }));

    expect(modelGroup.getAttribute("rotation")).toBe(initialRotation);
  });

  it("marks the active orthographic face on the view cube like slicer navigation widgets", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    const viewCube = await screen.findByRole("group", { name: "视图立方体" });
    expect(within(viewCube).getByRole("button", { name: "顶部视图" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    fireEvent.click(within(viewCube).getByRole("button", { name: "前面视图" }));

    expect(within(viewCube).getByRole("button", { name: "顶部视图" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(within(viewCube).getByRole("button", { name: "前面视图" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    fireEvent.click(screen.getByRole("tab", { name: "视图" }));
    fireEvent.click(
      within(screen.getByRole("toolbar", { name: "模型覆面二级工具栏" })).getByRole("button", {
        name: "默认视图",
      }),
    );

    expect(within(viewCube).getByRole("button", { name: "前面视图" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("keeps the view cube cluster cube-only and puts default view in the View toolbar", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    const viewCube = await screen.findByRole("group", { name: "视图立方体" });

    expect(viewCube.parentElement).toHaveAttribute("data-model-view-navigator-layout", "cube-only");
    expect(within(viewCube).queryByRole("button", { name: "默认视图" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "默认视图" })).not.toBeInTheDocument();
    expect(within(viewCube).getByRole("button", { name: "顶部视图" })).toHaveAttribute(
      "data-view-cube-face",
      "top",
    );
    expect(within(viewCube).getByRole("button", { name: "前面视图" })).toHaveAttribute(
      "data-view-cube-face",
      "front",
    );
    expect(within(viewCube).getByRole("button", { name: "右面视图" })).toHaveAttribute(
      "data-view-cube-face",
      "right",
    );

    fireEvent.click(screen.getByRole("tab", { name: "视图" }));

    expect(
      within(screen.getByRole("toolbar", { name: "模型覆面二级工具栏" })).getByRole("button", {
        name: "默认视图",
      }),
    ).toBeInTheDocument();
  });

  it("keeps view cube edge and corner targets as hidden slicer-style hit zones", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    const viewCube = await screen.findByRole("group", { name: "视图立方体" });
    const edgeTarget = within(viewCube).getByRole("button", { name: "右前视图" });
    const cornerTarget = within(viewCube).getByRole("button", { name: "右前上等轴测视图" });
    const topFaceTarget = within(viewCube).getByRole("button", { name: "顶部视图" });

    expect(edgeTarget).toHaveClass("opacity-0");
    expect(edgeTarget).toHaveClass("z-50");
    expect(edgeTarget).not.toHaveClass("rounded-full");
    expect(cornerTarget).toHaveClass("opacity-0");
    expect(cornerTarget).toHaveClass("z-50");
    expect(cornerTarget).not.toHaveClass("rounded-full");
    expect(topFaceTarget).toHaveAttribute("data-view-cube-face", "top");
    expect(topFaceTarget).toHaveAttribute("data-view-cube-hit-face", "top");
    expect(topFaceTarget).toHaveAttribute("data-view-cube-hit-visible");
    expect(topFaceTarget).toHaveClass("z-[45]");
    expect(topFaceTarget.getAttribute("style")).toContain("polygon(");
    expect(viewCube.querySelector('[data-view-cube-visual-face="top"]')).toHaveClass("z-40");
  });

  it("projects view cube edge and corner hit zones into a screen-fixed overlay", () => {
    const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 2000);
    camera.position.set(80, -80, 80);
    camera.lookAt(0, 0, 0);
    camera.updateMatrixWorld(true);
    const transform = getViewCubeCameraTransform(camera);
    const edgeZones = getViewCubeEdgeHitZones(transform);
    const cornerZones = getViewCubeCornerHitZones(transform);

    expect(edgeZones).toHaveLength(12);
    expect(cornerZones).toHaveLength(8);
    expect(edgeZones.some((zone) => zone.visible)).toBe(true);
    expect(cornerZones.some((zone) => zone.visible)).toBe(true);
    for (const zone of [...edgeZones, ...cornerZones].filter((item) => item.visible)) {
      expect(zone.left).toBeGreaterThanOrEqual(0);
      expect(zone.top).toBeGreaterThanOrEqual(0);
      expect(zone.width).toBeGreaterThan(0);
      expect(zone.height).toBeGreaterThan(0);
      expect(zone.left + zone.width).toBeLessThanOrEqual(112);
      expect(zone.top + zone.height).toBeLessThanOrEqual(112);
    }
  });

  it("shows reusable hover explanations for view cube face edge and corner targets", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    const viewCube = await screen.findByRole("group", { name: "视图立方体" });

    fireEvent.mouseEnter(within(viewCube).getByRole("button", { name: "顶部视图" }));
    const faceTooltip = await screen.findByRole("tooltip");
    expect(faceTooltip).toHaveTextContent("顶部视图");
    expect(faceTooltip).toHaveTextContent("只移动相机，不改变模型旋转");

    fireEvent.mouseEnter(within(viewCube).getByRole("button", { name: "右前视图" }));
    expect(await screen.findByText("右前视图")).toBeInTheDocument();
    expect(screen.getByText("切换到两面之间的斜向视图，只移动相机。")).toBeInTheDocument();

    fireEvent.mouseEnter(within(viewCube).getByRole("button", { name: "右前上等轴测视图" }));
    expect(await screen.findByText("右前上等轴测视图")).toBeInTheDocument();
    expect(screen.getByText("切换到等轴测视图，只移动相机。")).toBeInTheDocument();
  });

  it("hides readable view cube face labels when the slicer-style labels toggle is off", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    const viewCube = await screen.findByRole("group", { name: "视图立方体" });
    expect(within(viewCube).getByText("顶部")).toBeInTheDocument();
    expect(within(viewCube).getByText("前面")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "视图" }));
    fireEvent.click(screen.getByRole("button", { name: "标签" }));

    expect(within(viewCube).queryByText("顶部")).not.toBeInTheDocument();
    expect(within(viewCube).queryByText("前面")).not.toBeInTheDocument();
    expect(within(viewCube).getByRole("button", { name: "顶部视图" })).toHaveAttribute(
      "data-view-cube-face",
      "top",
    );
  });

  it("returns from an orthographic face to the default slicer-style view from the view controls", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    const modelGroup = await waitFor(() => {
      const element = document.querySelector('group[name="model-surface-transform"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    const initialRotation = modelGroup.getAttribute("rotation");

    fireEvent.click(screen.getByRole("button", { name: "顶部视图" }));
    expect(Math.abs(mockCamera.position.y)).toBeLessThan(0.001);

    const viewCube = screen.getByRole("group", { name: "视图立方体" });
    expect(within(viewCube).queryByRole("button", { name: "默认视图" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "视图" }));
    fireEvent.click(
      within(screen.getByRole("toolbar", { name: "模型覆面二级工具栏" })).getByRole("button", {
        name: "默认视图",
      }),
    );

    expect(modelGroup.getAttribute("rotation")).toBe(initialRotation);
    expect(mockCamera.position.y).toBeLessThan(-1);
    expect(mockCamera.position.z).toBeGreaterThan(1);
  });

  it("moves the camera to each view cube face without changing model rotation", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    const modelGroup = await waitFor(() => {
      const element = document.querySelector('group[name="model-surface-transform"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    const initialRotation = modelGroup.getAttribute("rotation");
    const viewCube = await screen.findByRole("group", { name: "视图立方体" });

    fireEvent.click(within(viewCube).getByRole("button", { name: "顶部视图" }));
    expect(mockCamera.position.z).toBeGreaterThan(1);
    expect(Math.abs(mockCamera.position.x)).toBeLessThan(0.001);
    expect(Math.abs(mockCamera.position.y)).toBeLessThan(0.001);

    fireEvent.click(within(viewCube).getByRole("button", { name: "底部视图" }));
    expect(mockCamera.position.z).toBeLessThan(-1);
    expect(Math.abs(mockCamera.position.x)).toBeLessThan(0.001);
    expect(Math.abs(mockCamera.position.y)).toBeLessThan(0.001);

    fireEvent.click(within(viewCube).getByRole("button", { name: "前面视图" }));
    expect(mockCamera.position.y).toBeLessThan(-1);
    expect(Math.abs(mockCamera.position.z - mockControls.target.z)).toBeLessThan(0.001);

    fireEvent.click(within(viewCube).getByRole("button", { name: "后面视图" }));
    expect(mockCamera.position.y).toBeGreaterThan(1);
    expect(Math.abs(mockCamera.position.z - mockControls.target.z)).toBeLessThan(0.001);

    fireEvent.click(within(viewCube).getByRole("button", { name: "左面视图" }));
    expect(mockCamera.position.x).toBeLessThan(-1);
    expect(Math.abs(mockCamera.position.z - mockControls.target.z)).toBeLessThan(0.001);

    fireEvent.click(within(viewCube).getByRole("button", { name: "右面视图" }));
    expect(mockCamera.position.x).toBeGreaterThan(1);
    expect(Math.abs(mockCamera.position.z - mockControls.target.z)).toBeLessThan(0.001);
    expect(modelGroup.getAttribute("rotation")).toBe(initialRotation);
  });

  it("keeps reverse surface viewing on the readable side above the bed", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [],
    };

    const view = render(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
        onUpdatePlacement={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(document.querySelector('group[name="model-surface-transform"]')).not.toBeNull();
    });

    view.rerender(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady
        selecting={false}
        footprint={footprint}
        onSelectFace={vi.fn()}
        onUpdatePlacement={vi.fn()}
      />,
    );

    await screen.findByRole("status", { name: "已选覆面平面" });
    fireEvent.click(screen.getByRole("tab", { name: "模型操作" }));
    fireEvent.click(screen.getByRole("button", { name: "反向查看" }));

    await waitFor(() => expect(mockCamera.position.z).toBeGreaterThan(mockControls.target.z));
    const viewDirection = mockCamera.position.clone().sub(mockControls.target).normalize();
    expect(Math.abs(viewDirection.x)).toBeLessThan(0.001);
    expect(Math.abs(viewDirection.y)).toBeLessThan(0.001);
    expect(viewDirection.z).toBeGreaterThan(0.999);
  });

  it("uses a near-orthographic inspection field of view when focusing the selected surface", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [],
    };

    const view = render(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
        onUpdatePlacement={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(document.querySelector('group[name="model-surface-transform"]')).not.toBeNull();
    });

    view.rerender(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady
        selecting={false}
        footprint={footprint}
        onSelectFace={vi.fn()}
        onUpdatePlacement={vi.fn()}
      />,
    );

    await screen.findByRole("status", { name: "已选覆面平面" });

    await waitFor(() => expect(mockCamera.fov).toBeLessThanOrEqual(3));
    expect(mockCamera.position.z).toBeGreaterThan(mockControls.target.z);
  });

  it("expands the camera far clipping plane for large selected surfaces", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-100, -100, 0);
      this.max.set(100, 100, 5);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "pegboard.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const footprint = {
      frame: {
        origin: [-98.5, -98.5, 5] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [0, 0] as [number, number],
      bounds_max: [197, 197] as [number, number],
      bounds_width_mm: 197,
      bounds_height_mm: 197,
      outer: [[0, 0], [197, 0], [197, 197], [0, 197], [0, 0]] as [number, number][],
      holes: [],
    };

    const view = render(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
        onUpdatePlacement={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(document.querySelector('group[name="model-surface-transform"]')).not.toBeNull();
    });

    view.rerender(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady
        selecting={false}
        footprint={footprint}
        onSelectFace={vi.fn()}
        onUpdatePlacement={vi.fn()}
      />,
    );

    await screen.findByRole("status", { name: "已选覆面平面" });
    await waitFor(() => expect(mockCamera.fov).toBeLessThanOrEqual(3));

    const focusDistance = mockCamera.position.distanceTo(mockControls.target);
    expect(mockCamera.far).toBeGreaterThan(focusDistance + 100);
    expect(mockCamera.near).toBeGreaterThan(0.1);
  });

  it("turns a downward selected surface upward by rotating the model instead of moving the camera underneath", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, -1);
      this.max.set(10, 5, 1);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const footprint = {
      frame: {
        origin: [0, 0, -1] as [number, number, number],
        normal: [0, 0, -1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, -1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [],
    };
    const onUpdateModelRotation = vi.fn();

    const view = render(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
        onUpdateModelRotation={onUpdateModelRotation}
        onUpdatePlacement={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(document.querySelector('group[name="model-surface-transform"]')).not.toBeNull();
    });
    const initialTargetZ = mockControls.target.z;

    view.rerender(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady
        selecting={false}
        footprint={footprint}
        onSelectFace={vi.fn()}
        onUpdateModelRotation={onUpdateModelRotation}
        onUpdatePlacement={vi.fn()}
      />,
    );

    await screen.findByRole("status", { name: "已选覆面平面" });

    await waitFor(() => {
      expect(onUpdateModelRotation).toHaveBeenLastCalledWith({
        x_deg: 0,
        y_deg: 180,
        z_deg: 0,
      });
    });
    await waitFor(() => {
      const modelGroup = document.querySelector('group[name="model-surface-transform"]');
      expect(modelGroup).toHaveAttribute("rotation", expect.stringContaining("3.141"));
    });
    expect(mockControls.target.z).toBeCloseTo(initialTargetZ, 4);
  });

  it("turns a vertical selected surface upward without moving the camera", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 10);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "upright-plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const footprint = {
      frame: {
        origin: [0, 5, 5] as [number, number, number],
        normal: [0, 1, 0] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 0, 1] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [],
    };

    const onUpdateModelRotation = vi.fn();
    const view = render(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
        onUpdateModelRotation={onUpdateModelRotation}
        onUpdatePlacement={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(document.querySelector('group[name="model-surface-transform"]')).not.toBeNull();
    });
    const initialCameraPosition = mockCamera.position.clone();
    const initialTarget = mockControls.target.clone();

    view.rerender(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady
        selecting={false}
        footprint={footprint}
        onSelectFace={vi.fn()}
        onUpdateModelRotation={onUpdateModelRotation}
        onUpdatePlacement={vi.fn()}
      />,
    );

    await screen.findByRole("status", { name: "已选覆面平面" });
    await waitFor(() => {
      expect(onUpdateModelRotation).toHaveBeenLastCalledWith({
        x_deg: 90,
        y_deg: 0,
        z_deg: 0,
      });
    });
    expect(mockCamera.position).toEqual(initialCameraPosition);
    expect(mockControls.target).toEqual(initialTarget);
  });

  it("moves the camera from view cube corner buttons without rotating the model", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    const modelGroup = await waitFor(() => {
      const element = document.querySelector('group[name="model-surface-transform"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    const initialRotation = modelGroup.getAttribute("rotation");
    const viewCube = await screen.findByRole("group", { name: "视图立方体" });

    fireEvent.click(within(viewCube).getByRole("button", { name: "右前上等轴测视图" }));

    expect(modelGroup.getAttribute("rotation")).toBe(initialRotation);
    expect(mockCamera.position.x).toBeGreaterThan(1);
    expect(mockCamera.position.y).toBeLessThan(-1);
    expect(mockCamera.position.z).toBeGreaterThan(1);
    expect(within(viewCube).getByRole("button", { name: "右前上等轴测视图" })).toHaveAttribute(
      "data-view-cube-corner",
      "right-front-top",
    );
  });

  it("moves the camera from Bambu-style view cube edge buttons without rotating the model", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    const modelGroup = await waitFor(() => {
      const element = document.querySelector('group[name="model-surface-transform"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    const initialRotation = modelGroup.getAttribute("rotation");
    const viewCube = await screen.findByRole("group", { name: "视图立方体" });

    fireEvent.click(within(viewCube).getByRole("button", { name: "右前视图" }));

    expect(modelGroup.getAttribute("rotation")).toBe(initialRotation);
    expect(mockCamera.position.x).toBeGreaterThan(1);
    expect(mockCamera.position.y).toBeLessThan(-1);
    expect(mockCamera.position.z).toBeCloseTo(1);
    expect(within(viewCube).getByRole("button", { name: "右前视图" })).toHaveAttribute(
      "data-view-cube-edge",
      "right-front",
    );
  });

  it("drives the view cube orientation from the current camera quaternion", async () => {
    const topCamera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
    topCamera.position.set(0, 0, 500);
    topCamera.lookAt(0, 0, 0);
    topCamera.updateMatrixWorld(true);

    const frontCamera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
    frontCamera.position.set(0, -500, 0);
    frontCamera.lookAt(0, 0, 0);
    frontCamera.updateMatrixWorld(true);

    expect(getViewCubeCameraTransform(topCamera)).not.toEqual(
      getViewCubeCameraTransform(frontCamera),
    );
  });

  it("orients the view cube visible face from the camera world direction", () => {
    const topCamera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
    topCamera.position.set(0, 0, 500);
    topCamera.lookAt(0, 0, 0);
    topCamera.updateMatrixWorld(true);

    const frontCamera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
    frontCamera.position.set(0, -500, 0);
    frontCamera.lookAt(0, 0, 0);
    frontCamera.updateMatrixWorld(true);

    const rightCamera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
    rightCamera.position.set(500, 0, 0);
    rightCamera.lookAt(0, 0, 0);
    rightCamera.updateMatrixWorld(true);

    expect(getViewCubeCameraTransform(topCamera)).toContain("rotateX(-90.00deg)");
    expect(getViewCubeCameraTransform(frontCamera)).toContain("rotateX(0.00deg)");
    expect(getViewCubeCameraTransform(rightCamera)).toContain("rotateY(-90.00deg)");
  });

  it("keeps snapped view cube faces square to the selected orthographic view", () => {
    const topCamera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
    topCamera.position.set(0, 0, 500);
    topCamera.lookAt(0, 0, 0);
    topCamera.updateMatrixWorld(true);

    const frontCamera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
    frontCamera.position.set(0, -500, 0);
    frontCamera.lookAt(0, 0, 0);
    frontCamera.updateMatrixWorld(true);

    expect(getViewCubeCameraTransform(topCamera)).toBe(
      "rotateX(-90.00deg) rotateY(0.00deg) rotateZ(0.00deg)",
    );
    expect(getViewCubeCameraTransform(frontCamera)).toBe(
      "rotateX(0.00deg) rotateY(0.00deg) rotateZ(0.00deg)",
    );
  });

  it("does not add decorative relief rotation to free-camera view cube orientation", () => {
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
    camera.position.set(200, -300, 450);
    camera.lookAt(0, 0, 0);
    camera.updateMatrixWorld(true);

    const transform = getViewCubeCameraTransform(camera);

    expect(transform).not.toContain("rotateX(-16deg)");
    expect(transform).not.toContain("rotateY(24deg)");
  });

  it("projects view cube face hit zones from the current cube rotation", () => {
    const topCamera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
    topCamera.position.set(0, 0, 500);
    topCamera.lookAt(0, 0, 0);
    topCamera.updateMatrixWorld(true);

    const frontCamera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
    frontCamera.position.set(0, -500, 0);
    frontCamera.lookAt(0, 0, 0);
    frontCamera.updateMatrixWorld(true);

    const topZones = getViewCubeFaceHitZones(getViewCubeCameraTransform(topCamera));
    const frontZones = getViewCubeFaceHitZones(getViewCubeCameraTransform(frontCamera));
    const topFaceInTopView = topZones.find((zone) => zone.view === "top");
    const topFaceInFrontView = frontZones.find((zone) => zone.view === "top");

    expect(topFaceInTopView?.visible).toBe(true);
    expect(topFaceInTopView?.polygon).toContain("polygon(");
    expect(topFaceInFrontView?.polygon).toContain("polygon(");
    expect(topFaceInTopView?.polygon).not.toBe(topFaceInFrontView?.polygon);
    expect(topZones.filter((zone) => zone.visible).length).toBeGreaterThan(0);
  });

  it("uses a slicer-style top-front 45 degree camera direction for default view", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    await screen.findByRole("group", { name: "视图立方体" });
    fireEvent.click(screen.getByRole("tab", { name: "视图" }));
    fireEvent.click(
      within(screen.getByRole("toolbar", { name: "模型覆面二级工具栏" })).getByRole("button", {
        name: "默认视图",
      }),
    );

    const viewDirection = mockCamera.position.clone().sub(mockControls.target).normalize();
    expect(viewDirection.x).toBeCloseTo(0);
    expect(viewDirection.y).toBeLessThan(0);
    expect(viewDirection.z).toBeGreaterThan(0);
    expect(Math.abs(viewDirection.y)).toBeCloseTo(viewDirection.z, 3);
  });

  it("shows Bambu style relative and absolute rotation fields in model rotate mode", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));

    expect(screen.getByText("世界坐标")).toBeInTheDocument();
    expect(screen.getByText("旋转（相对）")).toBeInTheDocument();
    expect(screen.getByText("旋转（绝对）")).toBeInTheDocument();
    expect(screen.getAllByText("X").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Y").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Z").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("X 相对旋转")).toBeInTheDocument();
    expect(screen.getByLabelText("Y 相对旋转")).toBeInTheDocument();
    expect(screen.getByLabelText("Z 相对旋转")).toBeInTheDocument();
    expect(screen.getByLabelText("X 绝对旋转")).toBeInTheDocument();
    expect(screen.getByLabelText("Y 绝对旋转")).toBeInTheDocument();
    expect(screen.getByLabelText("Z 绝对旋转")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "完成" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "X 轴旋转" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Y 轴旋转" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Z 轴旋转" })).not.toBeInTheDocument();
    expect(document.querySelector('group[name="model-rotation-gizmo"]')).not.toBeNull();
    expect(document.querySelector('mesh[name="model-rotation-x-ring"]')).not.toBeNull();
    expect(document.querySelector('mesh[name="model-rotation-y-ring"]')).not.toBeNull();
    expect(document.querySelector('mesh[name="model-rotation-z-ring"]')).not.toBeNull();
    expect(document.querySelector('mesh[name="model-rotation-x-hit-target"]')).not.toBeNull();
    expect(document.querySelector('mesh[name="model-rotation-y-hit-target"]')).not.toBeNull();
    expect(document.querySelector('mesh[name="model-rotation-z-hit-target"]')).not.toBeNull();
    expect(document.querySelector('group[name="model-rotation-ticks"]')).not.toBeNull();
    expect(document.querySelector('group[name="model-rotation-coarse-snap-guides"]')).not.toBeNull();
    expect(document.querySelector('group[name="model-rotation-reference-rays"]')).not.toBeNull();
    expect(document.querySelector('group[name="model-rotation-angle-arc"]')).not.toBeNull();
    expect(document.querySelector('lineSegments[name="model-rotation-z-ticks"]')).not.toBeNull();
    expect(screen.queryByText("Z: 0.00°")).not.toBeInTheDocument();
    expect(document.querySelector('group[name="model-rotation-grabber-connection"]')).not.toBeNull();
    expect(document.querySelector('lineSegments[name="model-rotation-x-grabber-connection"]')).not.toBeNull();
    expect(document.querySelector('lineSegments[name="model-rotation-y-grabber-connection"]')).not.toBeNull();
    expect(document.querySelector('lineSegments[name="model-rotation-z-grabber-connection"]')).not.toBeNull();
    expect(document.querySelector('group[name="model-rotation-grabbers"]')).not.toBeNull();
    expect(document.querySelector('group[name="model-rotation-x-grabber"]')).not.toBeNull();
    expect(document.querySelector('group[name="model-rotation-y-grabber"]')).not.toBeNull();
    expect(document.querySelector('group[name="model-rotation-z-grabber"]')).not.toBeNull();
  });

  it("closes the Bambu style rotate window with a done button", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    expect(document.querySelector('group[name="model-rotation-gizmo"]')).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "完成" }));

    expect(screen.queryByText("世界坐标")).not.toBeInTheDocument();
    expect(document.querySelector('group[name="model-rotation-gizmo"]')).toBeNull();
  });

  it("keeps the selected surface active when finishing model rotate mode", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [],
    };

    render(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady
        selecting={false}
        footprint={footprint}
        surfaceCandidates={[
          {
            id: "surface-4",
            face_index: 4,
            face_count: 2,
            area_mm2: 200,
            normal: [0, 0, 1],
            footprint,
          },
        ]}
        onSelectFace={vi.fn()}
        onUpdatePlacement={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(document.querySelector('lineSegments[name="model-surface-selected-outline"]')).not.toBeNull();
    });

    fireEvent.click(screen.getByRole("tab", { name: "模型操作" }));
    fireEvent.click(screen.getByRole("button", { name: "旋转模型" }));
    fireEvent.click(screen.getByRole("button", { name: "完成" }));

    expect(screen.queryByText("世界坐标")).not.toBeInTheDocument();
    expect(document.querySelector('group[name="model-rotation-gizmo"]')).toBeNull();
    expect(document.querySelector('lineSegments[name="model-surface-selected-outline"]')).not.toBeNull();
    expect(document.querySelector('mesh[name^="model-surface-candidate-"]')).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "覆面编辑" }));
    expect(screen.getByRole("button", { name: "移动贴图" })).not.toBeDisabled();
  });

  it("keeps orbit controls available until the selected artwork is actively dragged", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [],
    };

    render(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady
        selecting={false}
        footprint={footprint}
        onSelectFace={vi.fn()}
        onUpdatePlacement={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("tab", { name: "覆面编辑" }));
    await screen.findByRole("button", { name: "移动贴图" });
    expect(mockControls.enabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "移动贴图" }));
    expect(mockControls.enabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "旋转贴图" }));
    expect(mockControls.enabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "缩放贴图" }));
    expect(mockControls.enabled).toBe(true);

    fireEvent.click(screen.getByRole("tab", { name: "模型操作" }));
    fireEvent.click(screen.getByRole("tab", { name: "模型操作" }));
    fireEvent.click(screen.getByRole("tab", { name: "模型操作" }));
    fireEvent.click(screen.getByRole("button", { name: "重选面" }));
    expect(mockControls.enabled).toBe(true);
  });

  it("coalesces artwork move drags into the next animation frame", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
      ((contextId: string) =>
        contextId === "2d"
          ? ({
              clearRect: vi.fn(),
              save: vi.fn(),
              translate: vi.fn(),
              rotate: vi.fn(),
              drawImage: vi.fn(),
              restore: vi.fn(),
              beginPath: vi.fn(),
              moveTo: vi.fn(),
              lineTo: vi.fn(),
              closePath: vi.fn(),
              fill: vi.fn(),
              globalCompositeOperation: "source-over",
            } as unknown as CanvasRenderingContext2D)
          : null) as typeof HTMLCanvasElement.prototype.getContext,
    );
    const originalImage = window.Image;
    let imageConstructCount = 0;
    class TestImage {
      naturalWidth = 800;
      naturalHeight = 400;
      width = 800;
      height = 400;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;

      constructor() {
        imageConstructCount += 1;
      }

      set src(_value: string) {
        queueMicrotask(() => this.onload?.());
      }
    }
    Object.defineProperty(window, "Image", {
      configurable: true,
      writable: true,
      value: TestImage,
    });
    const originalRequestAnimationFrame = window.requestAnimationFrame;
    const originalCancelAnimationFrame = window.cancelAnimationFrame;
    const frameCallbacks = new Map<number, FrameRequestCallback>();
    let nextFrameId = 1;
    Object.defineProperty(window, "requestAnimationFrame", {
      configurable: true,
      writable: true,
      value: vi.fn((callback: FrameRequestCallback) => {
        const id = nextFrameId;
        nextFrameId += 1;
        frameCallbacks.set(id, callback);
        return id;
      }),
    });
    Object.defineProperty(window, "cancelAnimationFrame", {
      configurable: true,
      writable: true,
      value: vi.fn((id: number) => {
        frameCallbacks.delete(id);
      }),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [],
    };
    const onUpdatePlacement = vi.fn();
    function Harness() {
      const [placement, setPlacement] = useState<ModelSurfacePlacement>({
        mode: "edge_to_edge" as const,
        offset_x_mm: 0,
        offset_y_mm: 0,
        scale: 1,
        rotation_deg: 0,
        inset_mm: 0,
      });

      return (
        <ModelSurfaceSelector3D
          file={file}
          artworkUrl="blob:artwork"
          selectionReady
          selecting={false}
          footprint={footprint}
          placement={placement}
          onSelectFace={vi.fn()}
          onUpdatePlacement={(updates) => {
            onUpdatePlacement(updates);
            setPlacement((current) => ({ ...current, ...updates }));
          }}
        />
      );
    }

    try {
      render(<Harness />);

      await waitFor(() => {
        expect(findArtworkTextureMaterial()).not.toBeNull();
      });
      fireEvent.click(screen.getByRole("tab", { name: "覆面编辑" }));
      fireEvent.click(screen.getByRole("button", { name: "移动贴图" }));

      const artworkMesh = findArtworkTextureMaterial()?.closest("mesh");
      expect(artworkMesh).not.toBeNull();

      const pointerDown = createEvent.pointerDown(artworkMesh!, { pointerId: 7 });
      Object.defineProperty(pointerDown, "point", { value: new THREE.Vector3(0, 0, 1) });
      fireEvent(artworkMesh!, pointerDown);
      expect(mockControls.enabled).toBe(false);

      const firstMove = createEvent.pointerMove(artworkMesh!, { pointerId: 7 });
      Object.defineProperty(firstMove, "point", { value: new THREE.Vector3(2, 0.5, 1) });
      fireEvent(artworkMesh!, firstMove);
      const secondMove = createEvent.pointerMove(artworkMesh!, { pointerId: 7 });
      Object.defineProperty(secondMove, "point", { value: new THREE.Vector3(4, 1, 1) });
      fireEvent(artworkMesh!, secondMove);

      expect(onUpdatePlacement).not.toHaveBeenCalled();
      expect(window.requestAnimationFrame).toHaveBeenCalledTimes(1);

      frameCallbacks.get(1)?.(16);

      expect(onUpdatePlacement).toHaveBeenCalledTimes(1);
      expect(onUpdatePlacement).toHaveBeenCalledWith({
        offset_x_mm: 4,
        offset_y_mm: -1,
      });
      await waitFor(() => {
        expect(screen.getByRole("status", { name: "贴图位置读数" })).toHaveTextContent(
          "Y -1.0 mm",
        );
      });
      expect(imageConstructCount).toBe(1);

      const pointerUp = createEvent.pointerUp(artworkMesh!, { pointerId: 7 });
      Object.defineProperty(pointerUp, "point", { value: new THREE.Vector3(4, 1, 1) });
      fireEvent(artworkMesh!, pointerUp);
      expect(mockControls.enabled).toBe(true);
    } finally {
      Object.defineProperty(window, "Image", {
        configurable: true,
        writable: true,
        value: originalImage,
      });
      Object.defineProperty(window, "requestAnimationFrame", {
        configurable: true,
        writable: true,
        value: originalRequestAnimationFrame,
      });
      Object.defineProperty(window, "cancelAnimationFrame", {
        configurable: true,
        writable: true,
        value: originalCancelAnimationFrame,
      });
    }
  });

  it("returns to surface reselect mode after finishing model rotate mode from reselect", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [],
    };

    render(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady
        selecting={false}
        footprint={footprint}
        surfaceCandidates={[
          {
            id: "surface-4",
            face_index: 4,
            face_count: 2,
            area_mm2: 200,
            normal: [0, 0, 1],
            footprint,
          },
        ]}
        onSelectFace={vi.fn()}
        onUpdatePlacement={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(document.querySelector('lineSegments[name="model-surface-selected-outline"]')).not.toBeNull();
    });

    fireEvent.click(screen.getByRole("tab", { name: "模型操作" }));
    fireEvent.click(screen.getByRole("button", { name: "重选面" }));
    await waitFor(() => {
      expect(screen.getByRole("status", { name: "选择覆面平面" })).toBeInTheDocument();
    });
    expect(document.querySelector('mesh[name^="model-surface-candidate-"]')).toBeNull();
    expect(document.querySelector('lineSegments[name="model-surface-selected-outline"]')).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "模型操作" }));
    fireEvent.click(screen.getByRole("button", { name: "旋转模型" }));
    fireEvent.click(screen.getByRole("button", { name: "完成" }));

    expect(screen.queryByText("世界坐标")).not.toBeInTheDocument();
    expect(document.querySelector('group[name="model-rotation-gizmo"]')).toBeNull();
    expect(screen.getByRole("status", { name: "选择覆面平面" })).toBeInTheDocument();
    expect(document.querySelector('mesh[name^="model-surface-candidate-"]')).toBeNull();
    expect(document.querySelector('lineSegments[name="model-surface-selected-outline"]')).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "覆面编辑" }));
    expect(screen.getByRole("button", { name: "移动贴图" })).toBeDisabled();
  });

  it("keeps model controls visible after rotating a selected model so the surface can be reselected", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [],
    };

    render(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady
        selecting={false}
        footprint={footprint}
        surfaceCandidates={[
          {
            id: "surface-4",
            face_index: 4,
            face_count: 2,
            area_mm2: 200,
            normal: [0, 0, 1],
            footprint,
          },
        ]}
        onSelectFace={vi.fn()}
        onUpdatePlacement={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(document.querySelector('lineSegments[name="model-surface-selected-outline"]')).not.toBeNull();
    });
    fireEvent.click(screen.getByRole("tab", { name: "模型操作" }));
    fireEvent.click(screen.getByRole("button", { name: "旋转模型" }));
    fireEvent.click(screen.getByRole("button", { name: "X 快速旋转 +90°" }));
    fireEvent.click(screen.getByRole("button", { name: "完成" }));

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "模型操作" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
    });
    const reselectButton = screen.getByRole("button", { name: "重选面" });
    expect(reselectButton).toBeVisible();
    expect(reselectButton).toBeEnabled();
  });

  it("places a newly selected surface upward after the model was rotated for reselection", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [],
    };
    const onUpdateModelRotation = vi.fn();

    const view = render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
        onUpdateModelRotation={onUpdateModelRotation}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    fireEvent.click(screen.getByRole("button", { name: "X 快速旋转 +90°" }));
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    await waitFor(() => {
      expect(onUpdateModelRotation).toHaveBeenLastCalledWith({
        x_deg: 90,
        y_deg: 0,
        z_deg: 0,
      });
    });

    view.rerender(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady
        selecting={false}
        footprint={footprint}
        onSelectFace={vi.fn()}
        onUpdateModelRotation={onUpdateModelRotation}
      />,
    );

    await waitFor(() => {
      expect(onUpdateModelRotation).toHaveBeenLastCalledWith({
        x_deg: 0,
        y_deg: 0,
        z_deg: 0,
      });
    });
  });

  it("uses theme-aware styling for the slicer-style rotate window", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));

    const toolbarShell = document.querySelector(
      '[data-model-surface-toolbar-shell="floating-command-band"]',
    );
    const integratedRotationPanel = document.querySelector(
      '[data-model-rotation-panel-shell="integrated-command-band"]',
    );
    expect(toolbarShell).not.toBeNull();
    expect(integratedRotationPanel).not.toBeNull();
    expect(toolbarShell).toContainElement(integratedRotationPanel as HTMLElement);
    expect(
      document.querySelector('[data-model-rotation-panel-shell="floating-rotation-panel"]'),
    ).toBeNull();
    expect(document.querySelectorAll('[data-model-surface-toolbar-anchor="scene-floating"]')).toHaveLength(1);

    const panelShell = screen
      .getByText("世界坐标")
      .closest('[data-model-rotation-panel-shell="integrated-command-band"]');
    const panel = panelShell?.closest(
      '[data-model-surface-toolbar-shell="floating-command-band"]',
    );
    expect(panelShell).not.toBeNull();
    expect(panelShell).toHaveAttribute("data-model-rotation-panel-orientation", "horizontal");
    expect(panelShell).toHaveAttribute("data-model-rotation-panel-density", "compact");
    expect(screen.queryByRole("button", { name: "拖动旋转窗口" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "拖动覆面工具条" })).toBeInTheDocument();
    expect(panel).not.toBeNull();
    expect(panel).toHaveClass("bg-slate-100/90");
    expect(panel).toHaveClass("dark:bg-slate-950/82");
    expect(panel).toHaveStyle({
      maxWidth: "calc(100% - var(--lumina-left-dock-width, 0px) - var(--lumina-right-dock-width, 0px) - 24px)",
    });

    const numericInputs = screen.getAllByRole("spinbutton");
    expect(numericInputs).toHaveLength(6);
    numericInputs.forEach((input) => {
      expect(input).toHaveClass("h-7");
      expect(input).toHaveClass("w-[54px]");
      expect(input).toHaveClass("font-mono");
      expect(input).toHaveClass("tabular-nums");
    });
    expect(
      document.querySelector('[data-model-rotation-actions="compact-horizontal"]'),
    ).not.toBeNull();

    expect(screen.getByLabelText("X 相对旋转")).toHaveClass("bg-slate-50");
    expect(screen.getByLabelText("X 相对旋转")).toHaveClass("dark:bg-slate-900");
  });

  it("shows reusable hover explanations for rotation panel quick actions", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    const quickRotateButton = screen.getByRole("button", { name: "X 快速旋转 +90°" });
    fireEvent.mouseEnter(quickRotateButton.parentElement ?? quickRotateButton);

    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("X 快速旋转 +90°");
    expect(tooltip).toHaveTextContent("按 90° 增量快速旋转模型");
  });

  it("shows reusable hover explanations for rotation panel inputs and actions", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));

    const absoluteInput = screen.getByLabelText("X 绝对旋转");
    fireEvent.mouseEnter(absoluteInput);

    const inputTooltip = await screen.findByRole("tooltip");
    expect(inputTooltip).toHaveTextContent("X 绝对旋转");
    expect(inputTooltip).toHaveTextContent("输入模型绕对应轴的绝对角度");

    fireEvent.mouseLeave(absoluteInput);

    const resetButton = screen.getByRole("button", { name: "归零" });
    fireEvent.mouseEnter(resetButton);

    await waitFor(() => {
      const tooltips = screen.getAllByRole("tooltip");
      expect(tooltips.some((tooltip) => tooltip.textContent?.includes("归零"))).toBe(true);
      expect(
        tooltips.some((tooltip) => tooltip.textContent?.includes("清除所有模型旋转")),
      ).toBe(true);
    });
  });

  it("gives every floating scene action button a native hover title", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        surfaceCandidates={[
          {
            id: "surface-4",
            face_index: 4,
            face_count: 2,
            area_mm2: 200,
            normal: [0, 0, 1],
            footprint: {
              frame: {
                origin: [0, 0, 1],
                normal: [0, 0, 1],
                u_axis: [1, 0, 0],
                v_axis: [0, 1, 0],
              },
              bounds_min: [-10, -5],
              bounds_max: [10, 5],
              bounds_width_mm: 20,
              bounds_height_mm: 10,
              outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]],
              holes: [],
            },
          },
        ]}
        onSelectFace={vi.fn()}
      />,
    );

    const toolbarShell = await waitFor(() => {
      const element = document.querySelector(
        '[data-model-surface-toolbar-shell="floating-command-band"]',
      );
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    const toolbarButtons = Array.from(toolbarShell.querySelectorAll("button"));
    expect(toolbarButtons.length).toBeGreaterThan(0);
    expect(
      toolbarButtons
        .filter((button) => !button.getAttribute("title")?.trim())
        .map((button) => button.getAttribute("aria-label") ?? button.textContent?.trim()),
    ).toEqual([]);

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    const rotationPanel = await waitFor(() => {
      const element = document.querySelector(
        '[data-model-rotation-panel-shell="integrated-command-band"]',
      );
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    const rotationButtons = Array.from(rotationPanel.querySelectorAll("button"));
    expect(rotationButtons.length).toBeGreaterThan(0);
    expect(
      rotationButtons
        .filter((button) => !button.getAttribute("title")?.trim())
        .map((button) => button.getAttribute("aria-label") ?? button.textContent?.trim()),
    ).toEqual([]);
  });

  it("uses the primary toolbar placement for integrated model rotation controls", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    const toolbarShell = document.querySelector(
      '[data-model-surface-toolbar-shell="floating-command-band"]',
    ) as HTMLElement;
    const rotationControls = document.querySelector(
      '[data-model-rotation-panel-shell="integrated-command-band"]',
    );
    expect(toolbarShell).toContainElement(rotationControls as HTMLElement);
    expect(screen.getAllByRole("button", { name: "拖动覆面工具条" })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "拖动旋转窗口" })).not.toBeInTheDocument();
    expect(document.querySelectorAll('[data-model-surface-toolbar-anchor="scene-floating"]')).toHaveLength(1);
    expect(window.localStorage.getItem("lumina-model-surface-rotation-panel-layout-v1")).toBeNull();
  });

  it("keeps all Bambu-style rotation rings visible while revealing angle ticks without adding a second coordinate bed", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    const zHitTarget = await waitFor(() => {
      const element = document.querySelector('mesh[name="model-rotation-z-hit-target"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });

    fireEvent.pointerEnter(zHitTarget);

    expect(document.querySelector('group[name="model-rotation-ticks"]')).not.toBeNull();
    expect(document.querySelector('group[name="model-rotation-coarse-snap-guides"]')).not.toBeNull();
    expect(document.querySelector('group[name="model-rotation-snap-radius-rings"]')).not.toBeNull();
    expect(document.querySelector('group[name="model-rotation-reference-rays"]')).not.toBeNull();
    expect(document.querySelector('lineSegments[name="model-rotation-z-coarse-snap-guides"]')).not.toBeNull();
    expect(document.querySelector('lineSegments[name="model-rotation-z-snap-radius-rings"]')).not.toBeNull();
    expect(document.querySelector('lineSegments[name="model-rotation-z-reference-ray"]')).not.toBeNull();
    expect(
      document
        .querySelector('lineSegments[name="model-rotation-z-coarse-snap-guides"] lineBasicMaterial')
        ?.getAttribute("color"),
    ).toBe("#475569");
    expect(
      document
        .querySelector('lineSegments[name="model-rotation-z-snap-radius-rings"] lineBasicMaterial')
        ?.getAttribute("color"),
    ).toBe("#475569");
    expect(
      document
        .querySelector('lineSegments[name="model-rotation-z-reference-ray"] lineBasicMaterial')
        ?.getAttribute("color"),
    ).toBe("#475569");
    expect(document.querySelector('lineSegments[name="model-rotation-x-coarse-snap-guides"]')).toBeNull();
    expect(document.querySelector('lineSegments[name="model-rotation-y-coarse-snap-guides"]')).toBeNull();
    expect(document.querySelector('lineSegments[name="model-rotation-x-snap-radius-rings"]')).toBeNull();
    expect(document.querySelector('lineSegments[name="model-rotation-y-snap-radius-rings"]')).toBeNull();
    expect(document.querySelector("gridHelper")).toBeNull();
    expect(document.querySelector("axesHelper")).toBeNull();
    expect(document.querySelector('group[name="model-rotation-angle-arc"]')).not.toBeNull();
    expect(document.querySelector('group[name="model-rotation-grabber-connection"]')).not.toBeNull();
    expect(document.querySelector('group[name="model-rotation-grabbers"]')).not.toBeNull();
    expect(document.querySelector('lineSegments[name="model-rotation-z-ticks"]')).not.toBeNull();
    expect(
      document
        .querySelector('lineSegments[name="model-rotation-z-ticks"] lineBasicMaterial')
        ?.getAttribute("color"),
    ).toBe("#475569");
    expect(
      document
        .querySelector('lineSegments[name="model-rotation-z-angle-arc"] lineBasicMaterial')
        ?.getAttribute("color"),
    ).toBe("#475569");
    expect(document.querySelector('lineSegments[name="model-rotation-x-ticks"]')).toBeNull();
    expect(document.querySelector('lineSegments[name="model-rotation-y-ticks"]')).toBeNull();
    expect(document.querySelector('mesh[name="model-rotation-z-ring"]')).not.toBeNull();
    expect(document.querySelector('mesh[name="model-rotation-x-ring"]')).not.toBeNull();
    expect(document.querySelector('mesh[name="model-rotation-y-ring"]')).not.toBeNull();
    expect(document.querySelector('group[name="model-rotation-z-grabber"]')).not.toBeNull();
    expect(document.querySelector('mesh[name="model-rotation-z-grabber-arrow"]')).not.toBeNull();
    expect(document.querySelector('mesh[name="model-rotation-z-grabber-opposite-arrow"]')).not.toBeNull();
    expect(document.querySelector('mesh[name="model-rotation-z-grabber-hit-target"]')).not.toBeNull();
  });

  it("uses relative rotation inputs as incremental deltas like slicer object controls", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    const modelGroup = await waitFor(() => {
      const element = document.querySelector('group[name="model-surface-transform"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    const initialRotation = modelGroup.getAttribute("rotation");

    fireEvent.change(screen.getByLabelText("X 绝对旋转"), { target: { value: "45" } });

    expect(screen.getByLabelText("X 绝对旋转")).toHaveValue(45);
    expect(screen.getByLabelText("X 相对旋转")).toHaveValue(0);
    const absoluteRotation = modelGroup.getAttribute("rotation");
    expect(absoluteRotation).not.toBe(initialRotation);

    fireEvent.change(screen.getByLabelText("X 相对旋转"), { target: { value: "15" } });

    expect(screen.getByLabelText("X 相对旋转")).toHaveValue(15);
    expect(screen.getByLabelText("X 绝对旋转")).toHaveValue(60);
    expect(modelGroup.getAttribute("rotation")).not.toBe(absoluteRotation);
  });

  it("notifies the workflow when model rotation changes so export uses the slicer object pose", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const onUpdateModelRotation = vi.fn();

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
        onUpdateModelRotation={onUpdateModelRotation}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    fireEvent.change(screen.getByLabelText("X 绝对旋转"), { target: { value: "45" } });

    await waitFor(() => {
      expect(onUpdateModelRotation).toHaveBeenLastCalledWith({
        x_deg: 45,
        y_deg: 0,
        z_deg: 0,
      });
    });
  });

  it("highlights the edited axis and shows the angle readout after numeric rotation input", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    await waitFor(() => {
      expect(document.querySelector('mesh[name="model-rotation-x-hit-target"]')).not.toBeNull();
    });
    expect(document.querySelector('lineSegments[name="model-rotation-z-ticks"]')).not.toBeNull();

    fireEvent.change(screen.getByLabelText("X 绝对旋转"), { target: { value: "45" } });

    expect(screen.getByText("X: 45.00°")).toBeInTheDocument();
    expect(document.querySelector('group[name="model-rotation-ticks"]')).not.toBeNull();
    expect(document.querySelector('lineSegments[name="model-rotation-x-ticks"]')).not.toBeNull();
    expect(document.querySelector('lineSegments[name="model-rotation-y-ticks"]')).toBeNull();
    expect(document.querySelector('lineSegments[name="model-rotation-z-ticks"]')).toBeNull();
  });

  it("marks the active axis controls in the rotation panel after numeric input", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    fireEvent.change(screen.getByLabelText("Y 绝对旋转"), { target: { value: "45" } });

    expect(screen.getByLabelText("Y 绝对旋转")).toHaveAttribute(
      "data-model-rotation-axis-active",
      "true",
    );
    expect(screen.getByLabelText("Y 相对旋转")).toHaveAttribute(
      "data-model-rotation-axis-active",
      "true",
    );
    expect(screen.getByRole("button", { name: "Y 快速旋转 +90°" })).toHaveAttribute(
      "data-model-rotation-axis-active",
      "true",
    );
    expect(screen.getByLabelText("X 绝对旋转")).toHaveAttribute(
      "data-model-rotation-axis-active",
      "false",
    );
    expect(screen.getByRole("button", { name: "X 快速旋转 +90°" })).toHaveAttribute(
      "data-model-rotation-axis-active",
      "false",
    );
  });

  it("previews the focused rotation axis before the user changes numeric values", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    const modelGroup = await waitFor(() => {
      const element = document.querySelector('group[name="model-surface-transform"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    const initialRotation = modelGroup.getAttribute("rotation");

    expect(screen.getByLabelText("Z 绝对旋转")).toHaveAttribute(
      "data-model-rotation-axis-active",
      "false",
    );
    expect(document.querySelector('lineSegments[name="model-rotation-z-ticks"]')).not.toBeNull();

    fireEvent.focus(screen.getByLabelText("Z 绝对旋转"));

    expect(screen.getByLabelText("Z 绝对旋转")).toHaveAttribute(
      "data-model-rotation-axis-active",
      "true",
    );
    expect(screen.getByLabelText("Z 相对旋转")).toHaveAttribute(
      "data-model-rotation-axis-active",
      "true",
    );
    expect(screen.getByText("Z: 0.00°")).toBeInTheDocument();
    expect(document.querySelector('lineSegments[name="model-rotation-z-ticks"]')).not.toBeNull();
    expect(modelGroup.getAttribute("rotation")).toBe(initialRotation);
  });

  it("offers slicer-style 90 degree quick rotation buttons for each model axis", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    const modelGroup = await waitFor(() => {
      const element = document.querySelector('group[name="model-surface-transform"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    const initialRotation = modelGroup.getAttribute("rotation");

    fireEvent.click(screen.getByRole("button", { name: "X 快速旋转 +90°" }));

    expect(screen.getByLabelText("X 绝对旋转")).toHaveValue(90);
    expect(screen.getByLabelText("X 相对旋转")).toHaveValue(90);
    expect(screen.getByText("X: 90.00°")).toBeInTheDocument();
    expect(document.querySelector('lineSegments[name="model-rotation-x-ticks"]')).not.toBeNull();
    const xRotation = modelGroup.getAttribute("rotation");
    expect(xRotation).not.toBe(initialRotation);

    fireEvent.click(screen.getByRole("button", { name: "Y 快速旋转 +90°" }));

    expect(screen.getByLabelText("Y 绝对旋转")).toHaveValue(90);
    expect(screen.getByLabelText("Y 相对旋转")).toHaveValue(90);
    expect(screen.getByText("Y: 90.00°")).toBeInTheDocument();
    expect(document.querySelector('lineSegments[name="model-rotation-y-ticks"]')).not.toBeNull();
    expect(modelGroup.getAttribute("rotation")).not.toBe(xRotation);
  });

  it("offers slicer-style positive and negative 90 degree quick rotation buttons", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    const modelGroup = await waitFor(() => {
      const element = document.querySelector('group[name="model-surface-transform"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    const initialRotation = modelGroup.getAttribute("rotation");
    const quickGrid = document.querySelector('[data-model-rotation-quick-grid="axis-pairs"]');

    expect(quickGrid).not.toBeNull();
    expect(quickGrid).toHaveClass("grid-cols-6");
    expect(quickGrid?.querySelectorAll("button")).toHaveLength(6);
    expect(screen.getByRole("button", { name: "X 快速旋转 -90°" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "X 快速旋转 +90°" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Y 快速旋转 -90°" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Y 快速旋转 +90°" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Z 快速旋转 -90°" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Z 快速旋转 +90°" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "X 快速旋转 -90°" })).toHaveTextContent("X -90°");
    expect(screen.getByRole("button", { name: "X 快速旋转 +90°" })).toHaveTextContent("X +90°");
    expect(screen.getByRole("button", { name: "Y 快速旋转 -90°" })).toHaveTextContent("Y -90°");
    expect(screen.getByRole("button", { name: "Y 快速旋转 +90°" })).toHaveTextContent("Y +90°");
    expect(screen.getByRole("button", { name: "Z 快速旋转 -90°" })).toHaveTextContent("Z -90°");
    expect(screen.getByRole("button", { name: "Z 快速旋转 +90°" })).toHaveTextContent("Z +90°");

    fireEvent.click(screen.getByRole("button", { name: "Z 快速旋转 -90°" }));

    expect(screen.getByLabelText("Z 绝对旋转")).toHaveValue(270);
    expect(screen.getByLabelText("Z 相对旋转")).toHaveValue(-90);
    expect(screen.getByText("Z: 270.00°")).toBeInTheDocument();
    expect(document.querySelector('lineSegments[name="model-rotation-z-ticks"]')).not.toBeNull();
    expect(modelGroup.getAttribute("rotation")).not.toBe(initialRotation);

    fireEvent.click(screen.getByRole("button", { name: "Z 快速旋转 +90°" }));

    expect(screen.getByLabelText("Z 绝对旋转")).toHaveValue(0);
    expect(screen.getByLabelText("Z 相对旋转")).toHaveValue(0);
    expect(screen.getByText("Z: 0.00°")).toBeInTheDocument();
  });

  it("rotates the model around its own bounding center like slicer rotate gizmos", async () => {
    const pivot = new THREE.Vector3(0, 0, 2.5);
    const bottomCenter = new THREE.Vector3(0, 0, 0);
    const rotatedBottomCenter = rotateModelPointAroundPivot(
      bottomCenter,
      pivot,
      new THREE.Euler(Math.PI / 2, 0, 0),
    );

    expect(rotateModelPointAroundPivot(pivot, pivot, new THREE.Euler(Math.PI / 2, 0, 0))).toEqual(
      pivot,
    );
    expect(rotatedBottomCenter.x).toBeCloseTo(0);
    expect(rotatedBottomCenter.y).toBeCloseTo(2.5);
    expect(rotatedBottomCenter.z).toBeCloseTo(2.5);

    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    const modelGroup = await waitFor(() => {
      const element = document.querySelector('group[name="model-surface-transform"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    const pivotGroup = document.querySelector('group[name="model-surface-pivot-offset"]');

    expect(modelGroup).toHaveAttribute("position", "0,0,1");
    expect(pivotGroup).toHaveAttribute("position", "0,0,-1");

    fireEvent.click(screen.getByRole("button", { name: "X 快速旋转 +90°" }));

    expect(modelGroup).toHaveAttribute("position", "0,0,1");
    expect(pivotGroup).toHaveAttribute("position", "0,0,-1");
    expect(screen.getByText("X: 90.00°")).toBeInTheDocument();
  });

  it("keeps relative rotation input at zero when reopening rotate mode while preserving absolute rotation", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    fireEvent.change(screen.getByLabelText("X 绝对旋转"), { target: { value: "45" } });
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    fireEvent.click(screen.getByRole("button", { name: "旋转模型" }));

    expect(screen.getByLabelText("X 绝对旋转")).toHaveValue(45);
    expect(screen.getByLabelText("X 相对旋转")).toHaveValue(0);

    fireEvent.change(screen.getByLabelText("X 相对旋转"), { target: { value: "15" } });

    expect(screen.getByLabelText("X 相对旋转")).toHaveValue(15);
    expect(screen.getByLabelText("X 绝对旋转")).toHaveValue(60);
  });

  it("keeps relative rotation deltas readable when absolute rotation wraps past 360 degrees", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    fireEvent.change(screen.getByLabelText("X 绝对旋转"), { target: { value: "350" } });
    expect(screen.getByLabelText("X 绝对旋转")).toHaveValue(350);
    expect(screen.getByLabelText("X 相对旋转")).toHaveValue(0);

    fireEvent.change(screen.getByLabelText("X 相对旋转"), { target: { value: "20" } });

    expect(screen.getByLabelText("X 相对旋转")).toHaveValue(20);
    expect(screen.getByLabelText("X 绝对旋转")).toHaveValue(10);
  });

  it("shows uploaded candidate planes and selects a candidate instead of a bevel triangle", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const onSelectFace = vi.fn();

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        surfaceCandidates={[
          {
            id: "surface-4",
            face_index: 4,
            face_count: 2,
            area_mm2: 200,
            normal: [0, 0, 1],
            footprint: {
              frame: {
                origin: [0, 0, 1],
                normal: [0, 0, 1],
                u_axis: [1, 0, 0],
                v_axis: [0, 1, 0],
              },
              bounds_min: [-10, -5],
              bounds_max: [10, 5],
              bounds_width_mm: 20,
              bounds_height_mm: 10,
              outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]],
              holes: [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]],
            },
          },
          {
            id: "surface-9",
            face_index: 9,
            face_count: 1,
            area_mm2: 1,
            normal: [0, 0, 1],
            footprint: {
              frame: {
                origin: [2, 2, 1.05],
                normal: [0, 0, 1],
                u_axis: [1, 0, 0],
                v_axis: [0, 1, 0],
              },
              bounds_min: [1.5, 1.5],
              bounds_max: [2.5, 2.5],
              bounds_width_mm: 1,
              bounds_height_mm: 1,
              outer: [[1.5, 1.5], [2.5, 1.5], [2.5, 2.5], [1.5, 2.5], [1.5, 1.5]],
              holes: [],
            },
          },
        ]}
        onSelectFace={onSelectFace}
      />,
    );

    const modelMesh = await waitFor(() => requireModelSurfaceBody());
    expect(document.querySelector('mesh[name^="model-surface-candidate-"]')).toBeNull();
    expect(screen.queryByRole("button", { name: "选择候选平面 1" })).not.toBeInTheDocument();
    const mappedCandidate = findSelectableCandidateFromModelPoint(
      new THREE.Vector3(5, 0, 1),
      [
        {
          id: "surface-4",
          faceIndex: 4,
          faceCount: 2,
          areaMm2: 200,
          surface: {
            frame: {
              origin: new THREE.Vector3(0, 0, 1),
              normal: new THREE.Vector3(0, 0, 1),
              uAxis: new THREE.Vector3(1, 0, 0),
              vAxis: new THREE.Vector3(0, 1, 0),
            },
            boundsMin: [-10, -5],
            boundsMax: [10, 5],
            widthMm: 20,
            heightMm: 10,
            outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]],
            holes: [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]],
          },
        },
        {
          id: "surface-9",
          faceIndex: 9,
          faceCount: 1,
          areaMm2: 1,
          surface: {
            frame: {
              origin: new THREE.Vector3(2, 2, 1.05),
              normal: new THREE.Vector3(0, 0, 1),
              uAxis: new THREE.Vector3(1, 0, 0),
              vAxis: new THREE.Vector3(0, 1, 0),
            },
            boundsMin: [1.5, 1.5],
            boundsMax: [2.5, 2.5],
            widthMm: 1,
            heightMm: 1,
            outer: [[1.5, 1.5], [2.5, 1.5], [2.5, 2.5], [1.5, 2.5], [1.5, 1.5]],
            holes: [],
          },
        },
      ],
      new THREE.Vector3(),
      new THREE.Euler(),
    );
    expect(mappedCandidate?.id).toBe("surface-4");
    expect(mappedCandidate?.faceIndex).toBe(4);

    const rawFaceEvent = createEvent.pointerDown(modelMesh);
    Object.defineProperty(rawFaceEvent, "faceIndex", { value: 9 });
    fireEvent(modelMesh, rawFaceEvent);
    expect(onSelectFace).not.toHaveBeenCalled();

    fireModelSurfacePointerDown(modelMesh);

    expect(onSelectFace).toHaveBeenCalledWith(4, "surface-4");
    expect(document.querySelector('mesh[name^="model-surface-candidate-"]')).toBeNull();
  });

  it("shrinks the visible candidate plane like slicer lay-on-face overlays while preserving the hit footprint", () => {
    expect(
      insetRingTowardPoint(
        [[-10, -5], [10, -5], [10, 5], [-10, 5]],
        [0, 0],
        0.9,
      ),
    ).toEqual([[-9, -4.5], [9, -4.5], [9, 4.5], [-9, 4.5]]);

    const candidate = {
      id: "surface-4",
      faceIndex: 4,
      faceCount: 2,
      areaMm2: 200,
      surface: {
        frame: {
          origin: new THREE.Vector3(0, 0, 1),
          normal: new THREE.Vector3(0, 0, 1),
          uAxis: new THREE.Vector3(1, 0, 0),
          vAxis: new THREE.Vector3(0, 1, 0),
        },
        boundsMin: [-10, -5] as [number, number],
        boundsMax: [10, 5] as [number, number],
        widthMm: 20,
        heightMm: 10,
        outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
        holes: [],
      },
    };

    expect(
      findSelectableCandidateFromModelPoint(
        new THREE.Vector3(9.5, 0, 1),
        [candidate],
        new THREE.Vector3(),
        new THREE.Euler(),
      )?.id,
    ).toBe("surface-4");
  });

  it("keeps grouped candidate hit targets selectable across pegboard holes", () => {
    const surface = {
      frame: {
        origin: new THREE.Vector3(0, 0, 1),
        normal: new THREE.Vector3(0, 0, 1),
        uAxis: new THREE.Vector3(1, 0, 0),
        vAxis: new THREE.Vector3(0, 1, 0),
      },
      boundsMin: [-10, -5] as [number, number],
      boundsMax: [10, 5] as [number, number],
      widthMm: 20,
      heightMm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]] as [number, number][][],
    };
    const candidate = {
      id: "surface-4",
      faceIndex: 4,
      faceCount: 2,
      areaMm2: 200,
      surface,
    };
    const hitShape = createSurfaceHitShape(surface);

    expect(hitShape.holes).toHaveLength(0);
    expect(
      findSelectableCandidateFromModelPoint(
        new THREE.Vector3(0, 0, 1),
        [candidate],
        new THREE.Vector3(),
        new THREE.Euler(),
      )?.id,
    ).toBe("surface-4");
    expect(
      findSelectableCandidateFromPointerRay(
        new THREE.Ray(new THREE.Vector3(0, 0, 20), new THREE.Vector3(0, 0, -1)),
        [candidate],
        new THREE.Vector3(),
        new THREE.Euler(),
      )?.id,
    ).toBe("surface-4");
  });

  it("maps flipped model pointer points back into surface-local artwork drag direction", () => {
    const surface = {
      frame: {
        origin: new THREE.Vector3(0, 0, 1),
        normal: new THREE.Vector3(0, 0, 1),
        uAxis: new THREE.Vector3(1, 0, 0),
        vAxis: new THREE.Vector3(0, 1, 0),
      },
      boundsMin: [-10, -5] as [number, number],
      boundsMax: [10, 5] as [number, number],
      widthMm: 20,
      heightMm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [],
    };
    const modelEuler = new THREE.Euler(0, Math.PI, 0);
    const modelPivot = new THREE.Vector3();
    const flippedWorldPoint = rotateModelPointAroundPivot(
      new THREE.Vector3(3, 2, 1),
      modelPivot,
      modelEuler,
    );

    expect(
      pointToSurfaceLocal(
        flippedWorldPoint,
        surface,
        new THREE.Vector3(),
        modelEuler,
        modelPivot,
      ),
    ).toEqual([3, 2]);
  });

  it("computes artwork move updates with weak edge snapping", () => {
    const startPlacement = {
      mode: "edge_to_edge" as const,
      offset_x_mm: 0,
      offset_y_mm: 0,
      scale: 1,
      rotation_deg: 0,
      inset_mm: 0,
    };

    expect(
      computeArtworkPlacementDragUpdate({
        tool: "move",
        center: [0, 0],
        startPoint: [0, 0],
        currentPoint: [0, 1],
        startPlacement,
      }),
    ).toEqual({ offset_x_mm: 0, offset_y_mm: -1 });

    expect(
      computeArtworkPlacementDragUpdate({
        tool: "move",
        center: [0, 0],
        startPoint: [0, 0],
        currentPoint: [-1.65, 0],
        startPlacement,
        surfaceBounds: {
          min: [-10, -5],
          max: [10, 5],
        },
        artworkSizeMm: {
          width: 16,
          height: 10,
        },
        snapThresholdMm: 0.5,
      }),
    ).toEqual({ offset_x_mm: -2, offset_y_mm: 0 });

    expect(
      computeArtworkPlacementDragUpdate({
        tool: "move",
        center: [0, 0],
        startPoint: [0, 0],
        currentPoint: [-1.4, 0],
        startPlacement,
        surfaceBounds: {
          min: [-10, -5],
          max: [10, 5],
        },
        artworkSizeMm: {
          width: 16,
          height: 10,
        },
        snapThresholdMm: 0.5,
      }),
    ).toEqual({ offset_x_mm: -1.4, offset_y_mm: 0 });
  });

  it("uses the rotated artwork bounding box for move edge snapping", () => {
    const update = computeArtworkPlacementDragUpdate({
      tool: "move",
      center: [0, 0],
      startPoint: [0, 0],
      currentPoint: [3.2, 0],
      startPlacement: {
        mode: "edge_to_edge",
        offset_x_mm: 0,
        offset_y_mm: 0,
        scale: 1,
        rotation_deg: 45,
        inset_mm: 0,
      },
      surfaceBounds: {
        min: [-10, -10],
        max: [10, 10],
      },
      artworkSizeMm: {
        width: 10,
        height: 10,
      },
      snapThresholdMm: 0.5,
    });

    expect(update.offset_x_mm).toBeCloseTo(10 - Math.sqrt(50), 6);
    expect(update.offset_y_mm).toBe(0);
  });

  it("computes artwork rotation and scale updates from surface-local drag points", () => {
    const startPlacement = {
      mode: "edge_to_edge" as const,
      offset_x_mm: 0,
      offset_y_mm: 0,
      scale: 1,
      rotation_deg: 15,
      inset_mm: 0,
    };

    expect(
      computeArtworkPlacementDragUpdate({
        tool: "rotate",
        center: [0, 0],
        startPoint: [10, 0],
        currentPoint: [0, 10],
        startPlacement,
      }),
    ).toEqual({ rotation_deg: 105 });

    expect(
      computeArtworkPlacementDragUpdate({
        tool: "rotate",
        center: [0, 0],
        startPoint: [10, 0],
        currentPoint: [0, 10],
        startPlacement: {
          ...startPlacement,
          offset_x_mm: 5,
          offset_y_mm: -3,
        },
      }),
    ).toEqual({ rotation_deg: 105 });

    expect(
      computeArtworkPlacementDragUpdate({
        tool: "scale",
        center: [0, 0],
        startPoint: [10, 0],
        currentPoint: [20, 0],
        startPlacement: { ...startPlacement, scale: 1.25 },
      }),
    ).toEqual({ scale: 2.5 });
  });

  it("builds artwork canvas transforms around the selected surface center", () => {
    expect(
      computeArtworkCanvasTransform({
        widthPx: 200,
        heightPx: 100,
        pixelsPerMm: 4,
        placement: {
          mode: "edge_to_edge",
          offset_x_mm: 5,
          offset_y_mm: -3,
          scale: 1,
          rotation_deg: 90,
          inset_mm: 0,
        },
      }),
    ).toEqual({
      pivotX: 100,
      pivotY: 50,
      offsetX: 20,
      offsetY: 12,
      drawCenterX: 120,
      drawCenterY: 62,
      rotationRadians: Math.PI / 2,
    });
  });

  it("gives OBJ meshes owned material clones without disposing the shared source", () => {
    const root = new THREE.Group();
    const originalMaterial = new THREE.MeshStandardMaterial();
    const sharedMaterial = new THREE.MeshStandardMaterial();
    const originalDispose = vi.spyOn(originalMaterial, "dispose");
    const sharedDispose = vi.spyOn(sharedMaterial, "dispose");
    const first = new THREE.Mesh(new THREE.BoxGeometry(), originalMaterial);
    const secondOriginal = new THREE.MeshStandardMaterial();
    const second = new THREE.Mesh(new THREE.BoxGeometry(), secondOriginal);
    root.add(first, second);

    applySurfaceMaterial(root, sharedMaterial);

    expect(originalDispose).toHaveBeenCalledOnce();
    expect(first.material).not.toBe(sharedMaterial);
    expect(second.material).not.toBe(sharedMaterial);
    expect(first.material).not.toBe(second.material);
    expect(sharedDispose).not.toHaveBeenCalled();

    updateSurfaceMaterialColor(root, new THREE.Color("#123456"));
    expect((first.material as THREE.MeshStandardMaterial).color.getHexString()).toBe("123456");
    expect((second.material as THREE.MeshStandardMaterial).color.getHexString()).toBe("123456");

    first.geometry.dispose();
    second.geometry.dispose();
    (first.material as THREE.Material).dispose();
    (second.material as THREE.Material).dispose();
    sharedMaterial.dispose();
  });

  it("maps through-hole clicks to grouped candidate planes", async () => {
    const candidate = {
      id: "surface-4",
      faceIndex: 4,
      faceCount: 2,
      areaMm2: 200,
      surface: {
        frame: {
          origin: new THREE.Vector3(0, 0, 1),
          normal: new THREE.Vector3(0, 0, 1),
          uAxis: new THREE.Vector3(1, 0, 0),
          vAxis: new THREE.Vector3(0, 1, 0),
        },
        boundsMin: [-10, -5] as [number, number],
        boundsMax: [10, 5] as [number, number],
        widthMm: 20,
        heightMm: 10,
        outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
        holes: [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]] as [number, number][][],
      },
    };

    expect(
      findSelectableCandidateFromModelPoint(
        new THREE.Vector3(0, 0, 1),
        [candidate],
        new THREE.Vector3(),
        new THREE.Euler(),
      )?.id,
    ).toBe("surface-4");
    expect(
      findSelectableCandidateFromModelPoint(
        new THREE.Vector3(5, 0, 1),
        [candidate],
        new THREE.Vector3(),
        new THREE.Euler(),
      )?.id,
    ).toBe("surface-4");
  });

  it("maps grouped candidate picks after the model rotates around its own center", async () => {
    const candidate = {
      id: "surface-4",
      faceIndex: 4,
      faceCount: 2,
      areaMm2: 200,
      surface: {
        frame: {
          origin: new THREE.Vector3(0, 0, 2),
          normal: new THREE.Vector3(0, 0, 1),
          uAxis: new THREE.Vector3(1, 0, 0),
          vAxis: new THREE.Vector3(0, 1, 0),
        },
        boundsMin: [-10, -5] as [number, number],
        boundsMax: [10, 5] as [number, number],
        widthMm: 20,
        heightMm: 10,
        outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
        holes: [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]] as [number, number][][],
      },
    };
    const modelOffset = new THREE.Vector3(3, -2, 0);
    const modelPivot = new THREE.Vector3(3, -2, 1);
    const modelEuler = new THREE.Euler(Math.PI / 2, 0, 0);
    const rotatedSurfacePoint = rotateModelPointAroundPivot(
      new THREE.Vector3(8, -2, 2),
      modelPivot,
      modelEuler,
    );
    const rotatedHolePoint = rotateModelPointAroundPivot(
      new THREE.Vector3(3, -2, 2),
      modelPivot,
      modelEuler,
    );

    expect(
      findSelectableCandidateFromModelPoint(
        rotatedSurfacePoint,
        [candidate],
        modelOffset,
        modelEuler,
        modelPivot,
      )?.id,
    ).toBe("surface-4");
    expect(
      findSelectableCandidateFromModelPoint(
        rotatedHolePoint,
        [candidate],
        modelOffset,
        modelEuler,
        modelPivot,
      )?.id,
    ).toBe("surface-4");
  });

  it("selects grouped candidate planes from model-body clicks after rotation input changes", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const onSelectFace = vi.fn();

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        surfaceCandidates={[
          {
            id: "surface-4",
            face_index: 4,
            face_count: 2,
            area_mm2: 200,
            normal: [0, 0, 1],
            footprint: {
              frame: {
                origin: [0, 0, 2],
                normal: [0, 0, 1],
                u_axis: [1, 0, 0],
                v_axis: [0, 1, 0],
              },
              bounds_min: [-10, -5],
              bounds_max: [10, 5],
              bounds_width_mm: 20,
              bounds_height_mm: 10,
              outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]],
              holes: [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]],
            },
          },
        ]}
        onSelectFace={onSelectFace}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    fireEvent.change(screen.getByLabelText("X 绝对旋转"), { target: { value: "90" } });
    fireEvent.click(screen.getByRole("button", { name: "完成" }));

    const modelMesh = await waitFor(() => {
      const element = document.querySelector('mesh[name="model-surface-body"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    const rotatedSurfacePoint = rotateModelPointAroundPivot(
      new THREE.Vector3(5, 0, 2),
      new THREE.Vector3(0, 0, 1),
      new THREE.Euler(Math.PI / 2, 0, 0),
    );
    const selectEvent = createEvent.pointerDown(modelMesh);
    Object.defineProperty(selectEvent, "point", { value: rotatedSurfacePoint });
    fireEvent(modelMesh, selectEvent);

    expect(onSelectFace).toHaveBeenCalledWith(4, "surface-4");
  });

  it("highlights grouped candidate planes from model-body hover points", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        surfaceCandidates={[
          {
            id: "surface-4",
            face_index: 4,
            face_count: 2,
            area_mm2: 200,
            normal: [0, 0, 1],
            footprint: {
              frame: {
                origin: [0, 0, 1],
                normal: [0, 0, 1],
                u_axis: [1, 0, 0],
                v_axis: [0, 1, 0],
              },
              bounds_min: [-10, -5],
              bounds_max: [10, 5],
              bounds_width_mm: 20,
              bounds_height_mm: 10,
              outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]],
              holes: [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]],
            },
          },
        ]}
        onSelectFace={vi.fn()}
      />,
    );

    const modelMesh = await waitFor(() => requireModelSurfaceBody());
    expect(document.querySelector('mesh[name^="model-surface-candidate-"]')).toBeNull();

    fireModelSurfacePointerMove(modelMesh);

    await waitFor(() => {
      expect(
        document.querySelector('lineSegments[name="model-surface-candidate-outline-surface-4"]'),
      ).not.toBeNull();
    });

    const holeHoverEvent = createEvent.pointerMove(modelMesh);
    Object.defineProperty(holeHoverEvent, "point", { value: new THREE.Vector3(0, 0, 1) });
    fireEvent(modelMesh, holeHoverEvent);

    await waitFor(() => {
      expect(
        document.querySelector('lineSegments[name="model-surface-candidate-outline-surface-4"]'),
      ).not.toBeNull();
    });
  });

  it("shows a slicer-style outline only on the hovered candidate plane", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        surfaceCandidates={[
          {
            id: "surface-4",
            face_index: 4,
            face_count: 2,
            area_mm2: 200,
            normal: [0, 0, 1],
            footprint: {
              frame: {
                origin: [0, 0, 1],
                normal: [0, 0, 1],
                u_axis: [1, 0, 0],
                v_axis: [0, 1, 0],
              },
              bounds_min: [-10, -5],
              bounds_max: [10, 5],
              bounds_width_mm: 20,
              bounds_height_mm: 10,
              outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]],
              holes: [[[ -2, -1], [2, -1], [2, 1], [-2, 1], [-2, -1]]],
            },
          },
        ]}
        onSelectFace={vi.fn()}
      />,
    );

    const modelMesh = await waitFor(() => requireModelSurfaceBody());
    expect(document.querySelector('mesh[name^="model-surface-candidate-"]')).toBeNull();

    expect(
      document.querySelector('lineSegments[name="model-surface-candidate-outline-surface-4"]'),
    ).toBeNull();
    expect(
      document.querySelector('lineSegments[name="model-surface-candidate-normal-surface-4"]'),
    ).toBeNull();
    expect(
      document.querySelector('mesh[name="model-surface-candidate-normal-tip-surface-4"]'),
    ).toBeNull();

    fireModelSurfacePointerMove(modelMesh);

    expect(
      document.querySelector('lineSegments[name="model-surface-candidate-outline-surface-4"]'),
    ).not.toBeNull();
    expect(
      document.querySelector('lineSegments[name="model-surface-candidate-hole-outline-surface-4-0"]'),
    ).not.toBeNull();
    expect(
      document.querySelector('lineSegments[name="model-surface-candidate-normal-surface-4"]'),
    ).not.toBeNull();
    expect(
      document.querySelector('mesh[name="model-surface-candidate-normal-tip-surface-4"]'),
    ).not.toBeNull();

    fireEvent.pointerLeave(modelMesh);

    expect(
      document.querySelector('lineSegments[name="model-surface-candidate-outline-surface-4"]'),
    ).toBeNull();
    expect(
      document.querySelector('lineSegments[name="model-surface-candidate-normal-surface-4"]'),
    ).toBeNull();
    expect(
      document.querySelector('mesh[name="model-surface-candidate-normal-tip-surface-4"]'),
    ).toBeNull();
  });

  it("does not mount candidate surface meshes so view movement cannot expose triangulation artifacts", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        surfaceCandidates={[
          {
            id: "surface-4",
            face_index: 4,
            face_count: 2,
            area_mm2: 200,
            normal: [0, 0, 1],
            footprint: {
              frame: {
                origin: [0, 0, 1],
                normal: [0, 0, 1],
                u_axis: [1, 0, 0],
                v_axis: [0, 1, 0],
              },
              bounds_min: [-10, -5],
              bounds_max: [10, 5],
              bounds_width_mm: 20,
              bounds_height_mm: 10,
              outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]],
              holes: [[[-2, -1], [2, -1], [2, 1], [-2, 1], [-2, -1]]],
            },
          },
        ]}
        onSelectFace={vi.fn()}
      />,
    );

    const modelMesh = await waitFor(() => {
      const element = document.querySelector('mesh[name="model-surface-body"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });

    expect(document.querySelector('mesh[name^="model-surface-candidate-"]')).toBeNull();

    const hoverEvent = createEvent.pointerMove(modelMesh);
    Object.defineProperty(hoverEvent, "point", { value: new THREE.Vector3(5, 0, 1) });
    fireEvent(modelMesh, hoverEvent);

    expect(
      document.querySelector('lineSegments[name="model-surface-candidate-outline-surface-4"]'),
    ).not.toBeNull();
  });

  it("shows a slicer-style hover readout for the candidate plane that will be selected", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        surfaceCandidates={[
          {
            id: "surface-4",
            face_index: 4,
            face_count: 2,
            area_mm2: 200,
            normal: [0, 0, 1],
            footprint: {
              frame: {
                origin: [0, 0, 1],
                normal: [0, 0, 1],
                u_axis: [1, 0, 0],
                v_axis: [0, 1, 0],
              },
              bounds_min: [-10, -5],
              bounds_max: [10, 5],
              bounds_width_mm: 20,
              bounds_height_mm: 10,
              outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]],
              holes: [],
            },
          },
          {
            id: "surface-8",
            face_index: 8,
            face_count: 4,
            area_mm2: 150,
            normal: [0, 0, 1],
            footprint: {
              frame: {
                origin: [0, 0, 1.1],
                normal: [0, 0, 1],
                u_axis: [1, 0, 0],
                v_axis: [0, 1, 0],
              },
              bounds_min: [-8, -4],
              bounds_max: [7, 6],
              bounds_width_mm: 15,
              bounds_height_mm: 10,
              outer: [[-8, -4], [7, -4], [7, 6], [-8, 6], [-8, -4]],
              holes: [],
            },
          },
        ]}
        onSelectFace={vi.fn()}
      />,
    );

    const modelMesh = await waitFor(() => requireModelSurfaceBody());
    expect(document.querySelector('mesh[name^="model-surface-candidate-"]')).toBeNull();

    expect(screen.queryByRole("status", { name: "候选平面读数" })).not.toBeInTheDocument();

    fireModelSurfacePointerMove(modelMesh, new THREE.Vector3(5, 0, 1));

    const firstReadout = screen.getByRole("status", { name: "候选平面读数" });
    expect(firstReadout).toHaveAttribute("data-model-surface-candidate-readout", "screen-fixed");
    expect(firstReadout).toHaveAttribute(
      "data-model-surface-candidate-readout-position",
      "viewport-corner",
    );
    expect(firstReadout).toHaveClass("right-4");
    expect(firstReadout).not.toHaveClass("left-1/2");
    expect(firstReadout).not.toHaveClass("-translate-x-1/2");
    expect(firstReadout).toHaveTextContent("候选平面");
    expect(firstReadout).toHaveTextContent("顶部");
    expect(firstReadout).toHaveTextContent("20.0 × 10.0 mm");
    expect(firstReadout).toHaveTextContent("200.00 mm²");
    expect(firstReadout).toHaveTextContent("2 面片");
    expect(firstReadout).not.toHaveTextContent("surface-4");

    fireEvent.pointerLeave(modelMesh);

    expect(screen.queryByRole("status", { name: "候选平面读数" })).not.toBeInTheDocument();

    fireModelSurfacePointerMove(modelMesh, new THREE.Vector3(6, 5.5, 1.1));

    const secondReadout = screen.getByRole("status", { name: "候选平面读数" });
    expect(secondReadout).toHaveTextContent("顶部");
    expect(secondReadout).toHaveTextContent("15.0 × 10.0 mm");
    expect(secondReadout).toHaveTextContent("150.00 mm²");
    expect(secondReadout).toHaveTextContent("4 面片");
    expect(secondReadout).not.toHaveTextContent("surface-8");
  });

  it("shows a slicer-style selection mode panel while choosing grouped overlay planes", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        surfaceCandidates={[
          {
            id: "surface-4",
            face_index: 4,
            face_count: 2,
            area_mm2: 200,
            normal: [0, 0, 1],
            footprint: {
              frame: {
                origin: [0, 0, 1],
                normal: [0, 0, 1],
                u_axis: [1, 0, 0],
                v_axis: [0, 1, 0],
              },
              bounds_min: [-10, -5],
              bounds_max: [10, 5],
              bounds_width_mm: 20,
              bounds_height_mm: 10,
              outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]],
              holes: [],
            },
          },
          {
            id: "surface-8",
            face_index: 8,
            face_count: 4,
            area_mm2: 150,
            normal: [0, 0, 1],
            footprint: {
              frame: {
                origin: [0, 0, 1.1],
                normal: [0, 0, 1],
                u_axis: [1, 0, 0],
                v_axis: [0, 1, 0],
              },
              bounds_min: [-8, -4],
              bounds_max: [7, 6],
              bounds_width_mm: 15,
              bounds_height_mm: 10,
              outer: [[-8, -4], [7, -4], [7, 6], [-8, 6], [-8, -4]],
              holes: [],
            },
          },
        ]}
        onSelectFace={vi.fn()}
      />,
    );

    const panel = await screen.findByRole("status", { name: "选择覆面平面" });
    expect(panel).toHaveTextContent("模式");
    expect(panel).toHaveTextContent("平面组");
    expect(panel).toHaveTextContent("2 候选平面");
    expect(panel).toHaveTextContent("已过滤小倒角");
  });

  it("orders and caps grouped candidate planes without rendering candidate meshes", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const surfaceCandidates = Array.from({ length: 260 }, (_, index) => {
      const area = index + 1;
      return {
        id: `surface-${area}`,
        face_index: area,
        face_count: 1,
        area_mm2: area,
        normal: [0, 0, 1] as [number, number, number],
        footprint: {
          frame: {
            origin: [0, 0, 1] as [number, number, number],
            normal: [0, 0, 1] as [number, number, number],
            u_axis: [1, 0, 0] as [number, number, number],
            v_axis: [0, 1, 0] as [number, number, number],
          },
          bounds_min: [-10, -5] as [number, number],
          bounds_max: [10, 5] as [number, number],
          bounds_width_mm: 20,
          bounds_height_mm: 10,
          outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
          holes: [],
        },
      };
    });

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        surfaceCandidates={surfaceCandidates}
        onSelectFace={vi.fn()}
      />,
    );

    const panel = await screen.findByRole("status", { name: "选择覆面平面" });
    expect(panel).toHaveTextContent("254 候选平面");
    expect(document.querySelector('mesh[name^="model-surface-candidate-"]')).toBeNull();

    const modelMesh = await waitFor(() => requireModelSurfaceBody());
    fireModelSurfacePointerMove(modelMesh);
    const readout = await screen.findByRole("status", { name: "候选平面读数" });
    expect(readout).toHaveTextContent("260.00 mm²");
  });

  it("switches between slicer-style plane groups and exact triangular facet picking", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const onSelectFace = vi.fn();

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        surfaceCandidates={[
          {
            id: "surface-4",
            face_index: 4,
            face_count: 2,
            area_mm2: 200,
            normal: [0, 0, 1],
            footprint: {
              frame: {
                origin: [0, 0, 1],
                normal: [0, 0, 1],
                u_axis: [1, 0, 0],
                v_axis: [0, 1, 0],
              },
              bounds_min: [-10, -5],
              bounds_max: [10, 5],
              bounds_width_mm: 20,
              bounds_height_mm: 10,
              outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]],
              holes: [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]],
            },
          },
        ]}
        onSelectFace={onSelectFace}
      />,
    );

    await screen.findByRole("status", { name: "选择覆面平面" });
    const modelMesh = await waitFor(() => {
      const element = document.querySelector('mesh[name="model-surface-body"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });

    expect(screen.getByRole("button", { name: "选择平面组模式" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "选择三角面模式" })).toHaveAttribute("aria-pressed", "false");
    expect(document.querySelector('mesh[name^="model-surface-candidate-"]')).toBeNull();

    const groupedFaceEvent = createEvent.pointerDown(modelMesh);
    Object.defineProperty(groupedFaceEvent, "faceIndex", { value: 9 });
    fireEvent(modelMesh, groupedFaceEvent);

    expect(onSelectFace).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "选择三角面模式" }));

    expect(screen.getByRole("button", { name: "选择平面组模式" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "选择三角面模式" })).toHaveAttribute("aria-pressed", "true");
    expect(document.querySelector('mesh[name^="model-surface-candidate-"]')).toBeNull();

    const triangularFaceEvent = createEvent.pointerDown(modelMesh);
    Object.defineProperty(triangularFaceEvent, "faceIndex", { value: 9 });
    fireEvent(modelMesh, triangularFaceEvent);

    expect(onSelectFace).toHaveBeenCalledWith(9);
  });

  it("highlights triangular facet picks with an outline only so hover cannot expose fill artifacts", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        surfaceCandidates={[
          {
            id: "surface-4",
            face_index: 4,
            face_count: 2,
            area_mm2: 200,
            normal: [0, 0, 1],
            footprint: {
              frame: {
                origin: [0, 0, 1],
                normal: [0, 0, 1],
                u_axis: [1, 0, 0],
                v_axis: [0, 1, 0],
              },
              bounds_min: [-10, -5],
              bounds_max: [10, 5],
              bounds_width_mm: 20,
              bounds_height_mm: 10,
              outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]],
              holes: [],
            },
          },
        ]}
        onSelectFace={vi.fn()}
      />,
    );

    const modelMesh = await waitFor(() => {
      const element = document.querySelector('mesh[name="model-surface-body"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });

    fireEvent.click(screen.getByRole("button", { name: "选择三角面模式" }));

    const hoverEvent = createEvent.pointerMove(modelMesh);
    Object.defineProperty(hoverEvent, "faceIndex", { value: 2 });
    fireEvent(modelMesh, hoverEvent);

    expect(document.querySelector('mesh[name="model-surface-triangle-hover"]')).toBeNull();
    expect(
      document.querySelector('lineSegments[name="model-surface-triangle-hover-outline"]'),
    ).not.toBeNull();
    expect(document.querySelector('mesh[name^="model-surface-candidate-"]')).toBeNull();

    fireEvent.pointerLeave(modelMesh);

    expect(document.querySelector('mesh[name="model-surface-triangle-hover"]')).toBeNull();
  });

  it("keeps the selected surface readout out of the visible 3D scene", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [[[-2, -1], [2, -1], [2, 1], [-2, 1], [-2, -1]]] as [number, number][][],
    };

    render(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady
        selecting={false}
        footprint={footprint}
        onSelectFace={vi.fn()}
        onUpdatePlacement={vi.fn()}
      />,
    );

    const panel = await screen.findByRole("status", { name: "已选覆面平面" });
    expect(panel).toHaveAttribute("data-model-surface-selected-panel", "screen-reader-status");
    expect(panel).toHaveClass("sr-only");
    expect(panel).toHaveTextContent("顶部");
    expect(panel).toHaveTextContent("20.0 × 10.0 mm");
    expect(panel).toHaveTextContent("已选");
    expect(panel).toHaveTextContent("贴图可调整");
    expect(panel).not.toHaveTextContent("移动 / 旋转 / 缩放");
    expect(screen.queryByRole("status", { name: "选择覆面平面" })).not.toBeInTheDocument();
    expect(document.querySelector('lineSegments[name="model-surface-selected-outline"]')).not.toBeNull();
    expect(document.querySelector('lineSegments[name="model-surface-selected-normal"]')).toBeNull();
    expect(document.querySelector('mesh[name="model-surface-selected-normal-tip"]')).toBeNull();
    expect(
      document.querySelector('lineSegments[name="model-surface-selected-hole-outline-0"]'),
    ).toBeNull();
  });

  it("uses theme-aware model body colors after selecting a surface instead of a blue shell", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const colorSetSpy = vi.spyOn(THREE.Color.prototype, "set");
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [[[-2, -1], [2, -1], [2, 1], [-2, 1], [-2, -1]]] as [number, number][][],
    };

    render(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady
        selecting={false}
        footprint={footprint}
        onSelectFace={vi.fn()}
        onUpdatePlacement={vi.fn()}
      />,
    );

    await waitFor(() => requireModelSurfaceBody());

    expect(colorSetSpy).not.toHaveBeenCalledWith("#89c2ff");
    expect(colorSetSpy).toHaveBeenCalledWith("#a8b4c4");

    colorSetSpy.mockClear();
    useSettingsStore.setState({ theme: "dark" });

    await waitFor(() => {
      expect(colorSetSpy).toHaveBeenCalledWith("#64748b");
    });
  });

  it("smooths shallow STL triangle seams while preserving the preview geometry", () => {
    const shallowAngleRadians = THREE.MathUtils.degToRad(12);
    const height = Math.tan(shallowAngleRadians);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute([
        0, 0, 0,
        1, 0, 0,
        0, 1, 0,
        1, 0, 0,
        1, 1, height,
        0, 1, 0,
      ], 3),
    );
    geometry.computeVertexNormals();
    const before = geometry.getAttribute("normal");
    const beforeSharedEdgeNormalA = new THREE.Vector3(
      before.getX(1),
      before.getY(1),
      before.getZ(1),
    );
    const beforeSharedEdgeNormalB = new THREE.Vector3(
      before.getX(3),
      before.getY(3),
      before.getZ(3),
    );

    const prepared = prepareStlPreviewGeometry(geometry);
    const after = prepared.getAttribute("normal");
    const afterSharedEdgeNormalA = new THREE.Vector3(
      after.getX(1),
      after.getY(1),
      after.getZ(1),
    );
    const afterSharedEdgeNormalB = new THREE.Vector3(
      after.getX(3),
      after.getY(3),
      after.getZ(3),
    );

    expect(beforeSharedEdgeNormalA.distanceTo(beforeSharedEdgeNormalB)).toBeGreaterThan(0.01);
    expect(afterSharedEdgeNormalA.distanceTo(afterSharedEdgeNormalB)).toBeLessThan(0.001);
    expect(prepared.getAttribute("position").count).toBe(6);
  });

  it("renders the model body as an unlit opaque depth-writing surface to avoid STL triangle shimmer", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const basicMaterialSetValuesSpy = vi.spyOn(THREE.MeshBasicMaterial.prototype, "setValues");
    const standardMaterialSetValuesSpy = vi.spyOn(
      THREE.MeshStandardMaterial.prototype,
      "setValues",
    );

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    await waitFor(() => requireModelSurfaceBody());
    const bodyMaterialOptions = basicMaterialSetValuesSpy.mock.calls
      .map(([options]) => options as Partial<THREE.MeshBasicMaterialParameters> | undefined)
      .find((options) => options?.color === "#a8b4c4");
    const shadedBodyMaterialOptions = standardMaterialSetValuesSpy.mock.calls
      .map(([options]) => options as Partial<THREE.MeshStandardMaterialParameters> | undefined)
      .filter((options) => options?.color === "#a8b4c4");

    expect(bodyMaterialOptions).toMatchObject({
      transparent: false,
      opacity: 1,
      depthTest: true,
      depthWrite: true,
      side: THREE.DoubleSide,
      toneMapped: false,
    });
    expect(shadedBodyMaterialOptions).toEqual([]);
  });

  it("draws rotated inset artwork inside the preview clearance", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -10, 0);
      this.max.set(10, 10, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const drawImage = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
      ((contextId: string) =>
        contextId === "2d"
          ? ({
              clearRect: vi.fn(),
              save: vi.fn(),
              translate: vi.fn(),
              rotate: vi.fn(),
              drawImage,
              restore: vi.fn(),
              beginPath: vi.fn(),
              moveTo: vi.fn(),
              lineTo: vi.fn(),
              closePath: vi.fn(),
              fill: vi.fn(),
              globalCompositeOperation: "source-over",
            } as unknown as CanvasRenderingContext2D)
          : null) as typeof HTMLCanvasElement.prototype.getContext,
    );
    const originalImage = window.Image;
    class TestImage {
      naturalWidth = 40;
      naturalHeight = 80;
      width = 40;
      height = 80;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;

      set src(_value: string) {
        queueMicrotask(() => this.onload?.());
      }
    }
    Object.defineProperty(window, "Image", {
      configurable: true,
      writable: true,
      value: TestImage,
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -10] as [number, number],
      bounds_max: [10, 10] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 20,
      outer: [[-10, -10], [10, -10], [10, 10], [-10, 10], [-10, -10]] as [number, number][],
      holes: [],
    };

    try {
      render(
        <ModelSurfaceSelector3D
          file={file}
          artworkUrl="blob:artwork"
          selectionReady
          selecting={false}
          footprint={footprint}
          placement={{
            mode: "inset",
            offset_x_mm: 0,
            offset_y_mm: 0,
            scale: 1,
            rotation_deg: 17,
            inset_mm: 2,
          }}
          onSelectFace={vi.fn()}
          onUpdatePlacement={vi.fn()}
        />,
      );

      await waitFor(() => expect(drawImage).toHaveBeenCalled());
      const call = drawImage.mock.calls.at(-1);
      const targetWidth = Number(call?.[3]);
      const targetHeight = Number(call?.[4]);
      const rotationRadians = THREE.MathUtils.degToRad(17);
      const rotatedWidth =
        Math.abs(targetWidth * Math.cos(rotationRadians))
        + Math.abs(targetHeight * Math.sin(rotationRadians));
      const rotatedHeight =
        Math.abs(targetWidth * Math.sin(rotationRadians))
        + Math.abs(targetHeight * Math.cos(rotationRadians));

      expect(rotatedWidth).toBeLessThanOrEqual(161);
      expect(rotatedHeight).toBeLessThanOrEqual(161);
      expect(Math.max(rotatedWidth, rotatedHeight)).toBeCloseTo(160, 0);
    } finally {
      Object.defineProperty(window, "Image", {
        configurable: true,
        writable: true,
        value: originalImage,
      });
    }
  });

  it("renders selected artwork at full opacity so model facets cannot bleed through", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
      ((contextId: string) =>
        contextId === "2d"
          ? ({
              clearRect: vi.fn(),
              save: vi.fn(),
              translate: vi.fn(),
              rotate: vi.fn(),
              drawImage: vi.fn(),
              restore: vi.fn(),
              beginPath: vi.fn(),
              moveTo: vi.fn(),
              lineTo: vi.fn(),
              closePath: vi.fn(),
              fill: vi.fn(),
              globalCompositeOperation: "source-over",
            } as unknown as CanvasRenderingContext2D)
          : null) as typeof HTMLCanvasElement.prototype.getContext,
    );
    const originalImage = window.Image;
    class TestImage {
      naturalWidth = 800;
      naturalHeight = 400;
      width = 800;
      height = 400;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;

      set src(_value: string) {
        queueMicrotask(() => this.onload?.());
      }
    }
    Object.defineProperty(window, "Image", {
      configurable: true,
      writable: true,
      value: TestImage,
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [[[-2, -1], [2, -1], [2, 1], [-2, 1], [-2, -1]]] as [number, number][][],
    };

    try {
      render(
        <ModelSurfaceSelector3D
          file={file}
          artworkUrl="blob:artwork"
          selectionReady
          selecting={false}
          footprint={footprint}
          onSelectFace={vi.fn()}
          onUpdatePlacement={vi.fn()}
        />,
      );

      await waitFor(() => {
        expect(findArtworkTextureMaterial()).not.toBeNull();
      });
      const artworkMaterial = findArtworkTextureMaterial();

      expect(artworkMaterial).toHaveAttribute("opacity", "1");
    } finally {
      Object.defineProperty(window, "Image", {
        configurable: true,
        writable: true,
        value: originalImage,
      });
    }
  });

  it("depth-tests selected artwork so it cannot show through the model body", () => {
    expect(SURFACE_ARTWORK_MATERIAL_DEPTH_FLAGS).toEqual({
      depthTest: true,
      depthWrite: false,
    });
  });

  it("uses stable texture sampling for selected artwork during oblique camera movement", () => {
    const canvas = document.createElement("canvas");
    const texture = new THREE.CanvasTexture(canvas);

    configureSurfaceArtworkTextureForPreview(texture);

    expect(texture.colorSpace).toBe(THREE.SRGBColorSpace);
    expect(texture.flipY).toBe(false);
    expect(texture.generateMipmaps).toBe(false);
    expect(texture.minFilter).toBe(THREE.LinearFilter);
    expect(texture.magFilter).toBe(THREE.LinearFilter);
    expect(texture.wrapS).toBe(THREE.ClampToEdgeWrapping);
    expect(texture.wrapT).toBe(THREE.ClampToEdgeWrapping);
  });

  it("depth-tests surface markers so selected outlines cannot show through the model body", () => {
    expect(SURFACE_MARKER_MATERIAL_DEPTH_FLAGS).toEqual({
      depthTest: true,
      depthWrite: false,
    });
  });

  it("keeps selected artwork geometry offset from the model surface", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
      ((contextId: string) =>
        contextId === "2d"
          ? ({
              clearRect: vi.fn(),
              save: vi.fn(),
              translate: vi.fn(),
              rotate: vi.fn(),
              drawImage: vi.fn(),
              restore: vi.fn(),
              beginPath: vi.fn(),
              moveTo: vi.fn(),
              lineTo: vi.fn(),
              closePath: vi.fn(),
              fill: vi.fn(),
              globalCompositeOperation: "source-over",
            } as unknown as CanvasRenderingContext2D)
          : null) as typeof HTMLCanvasElement.prototype.getContext,
    );
    const originalImage = window.Image;
    class TestImage {
      naturalWidth = 800;
      naturalHeight = 400;
      width = 800;
      height = 400;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;

      set src(_value: string) {
        queueMicrotask(() => this.onload?.());
      }
    }
    Object.defineProperty(window, "Image", {
      configurable: true,
      writable: true,
      value: TestImage,
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [[[-2, -1], [2, -1], [2, 1], [-2, 1], [-2, -1]]] as [number, number][][],
    };

    try {
      render(
        <ModelSurfaceSelector3D
          file={file}
          artworkUrl="blob:artwork"
          selectionReady
          selecting={false}
          footprint={footprint}
          onSelectFace={vi.fn()}
          onUpdatePlacement={vi.fn()}
        />,
      );

      await waitFor(() => {
        expect(findArtworkTextureMaterial()).not.toBeNull();
      });
      const artworkMaterial = findArtworkTextureMaterial();

      expect(artworkMaterial).toHaveAttribute("polygonOffsetFactor", "-2");
    } finally {
      Object.defineProperty(window, "Image", {
        configurable: true,
        writable: true,
        value: originalImage,
      });
    }
  });

  it("shows a compact artwork placement readout while editing the selected image", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [],
    };

    render(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady
        selecting={false}
        footprint={footprint}
        placement={{
          mode: "edge_to_edge",
          offset_x_mm: 12.345,
          offset_y_mm: -4.5,
          scale: 1.25,
          rotation_deg: 37.5,
          inset_mm: 0,
        }}
        onSelectFace={vi.fn()}
        onUpdatePlacement={vi.fn()}
      />,
    );

    expect(screen.queryByRole("status", { name: "贴图位置读数" })).not.toBeInTheDocument();

    fireEvent.click(await screen.findByRole("tab", { name: "覆面编辑" }));
    fireEvent.click(screen.getByRole("button", { name: "移动贴图" }));

    const readout = await screen.findByRole("status", { name: "贴图位置读数" });
    expect(readout).toHaveAttribute("data-model-surface-artwork-readout", "screen-fixed");
    expect(readout).toHaveAttribute(
      "data-model-surface-artwork-readout-position",
      "viewport-corner",
    );
    expect(readout).toHaveClass("right-4");
    expect(readout).not.toHaveClass("left-1/2");
    expect(readout).not.toHaveClass("-translate-x-1/2");
    expect(readout).toHaveTextContent("X 12.3 mm");
    expect(readout).toHaveTextContent("Y -4.5 mm");
    expect(readout).toHaveTextContent("37.5°");
    expect(readout).toHaveTextContent("1.25×");
  });

  it("reuses slicer-style rotation aids for planar artwork rotation", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const onUpdatePlacement = vi.fn();
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [],
    };

    render(
      <ModelSurfaceSelector3D
        file={file}
        artworkUrl="blob:artwork"
        selectionReady
        selecting={false}
        footprint={footprint}
        placement={{
          mode: "edge_to_edge",
          offset_x_mm: 4,
          offset_y_mm: -2,
          scale: 1,
          rotation_deg: 30,
          inset_mm: 0,
        }}
        onSelectFace={vi.fn()}
        onUpdatePlacement={onUpdatePlacement}
      />,
    );

    fireEvent.click(await screen.findByRole("tab", { name: "覆面编辑" }));
    fireEvent.click(screen.getByRole("button", { name: "旋转贴图" }));

    const panel = await screen.findByRole("group", { name: "贴图旋转" });
    expect(panel).toHaveAttribute("data-artwork-rotation-panel", "planar");
    expect(panel).toHaveAttribute("data-model-rotation-panel-orientation", "horizontal");
    expect(panel).toHaveAttribute("data-model-rotation-panel-density", "compact");
    expect(
      panel.querySelector('[data-model-rotation-actions="compact-horizontal"]'),
    ).not.toBeNull();
    const rotationGizmo = document.querySelector('group[name="artwork-rotation-gizmo"]');
    expect(rotationGizmo).toHaveAttribute("renderOrder", "40");
    expect(document.querySelector('lineSegments[name="artwork-rotation-z-ticks"]')).not.toBeNull();

    const ringTarget = document.querySelector('mesh[name="artwork-rotation-z-hit-target"]');
    expect(ringTarget).not.toBeNull();
    const ringPointerDown = createEvent.pointerDown(ringTarget!, { pointerId: 17 });
    Object.defineProperty(ringPointerDown, "point", {
      value: new THREE.Vector3(20, 0, 1),
    });
    Object.defineProperty(ringPointerDown, "ray", {
      value: new THREE.Ray(
        new THREE.Vector3(25, 0, 100),
        new THREE.Vector3(0, 0, -1),
      ),
    });
    fireEvent(ringTarget!, ringPointerDown);
    const ringPointerMove = createEvent.pointerMove(ringTarget!, { pointerId: 17 });
    Object.defineProperty(ringPointerMove, "point", {
      value: new THREE.Vector3(
        Math.cos(THREE.MathUtils.degToRad(13)) * 21,
        Math.sin(THREE.MathUtils.degToRad(13)) * 21,
        1,
      ),
    });
    Object.defineProperty(ringPointerMove, "ray", {
      value: new THREE.Ray(
        new THREE.Vector3(24.359, 5.624, 100),
        new THREE.Vector3(0, 0, -1),
      ),
    });
    fireEvent(ringTarget!, ringPointerMove);
    const ringPointerUp = createEvent.pointerUp(ringTarget!, { pointerId: 17 });
    Object.defineProperty(ringPointerUp, "point", {
      value: new THREE.Vector3(
        Math.cos(THREE.MathUtils.degToRad(13)) * 21,
        Math.sin(THREE.MathUtils.degToRad(13)) * 21,
        1,
      ),
    });
    fireEvent(ringTarget!, ringPointerUp);
    expect(onUpdatePlacement.mock.lastCall?.[0].rotation_deg).toBeCloseTo(43);

    fireEvent.change(within(panel).getByRole("spinbutton", { name: "贴图旋转角度" }), {
      target: { value: "45" },
    });
    expect(onUpdatePlacement).toHaveBeenLastCalledWith({ rotation_deg: 45 });

    fireEvent.click(within(panel).getByRole("button", { name: "贴图顺时针旋转 90°" }));
    expect(onUpdatePlacement).toHaveBeenLastCalledWith({ rotation_deg: 120 });

    fireEvent.click(within(panel).getByRole("button", { name: "贴图旋转归零" }));
    expect(onUpdatePlacement).toHaveBeenLastCalledWith({ rotation_deg: 0 });
  });

  it("uses mesh-free candidate picking and a lightweight selected outline", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [],
    };

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady
        selecting={false}
        footprint={footprint}
        surfaceCandidates={[
          {
            id: "surface-4",
            face_index: 4,
            face_count: 2,
            area_mm2: 200,
            normal: [0, 0, 1],
            footprint,
          },
        ]}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "重选面" }));

    const modelMesh = await waitFor(() => requireModelSurfaceBody());
    expect(document.querySelector('mesh[name^="model-surface-candidate-"]')).toBeNull();

    fireModelSurfacePointerDown(modelMesh);

    await waitFor(() => {
      expect(document.querySelector('lineSegments[name="model-surface-selected-outline"]')).not.toBeNull();
    });
    const selectedOutlineMaterial = document.querySelector(
      'lineSegments[name="model-surface-selected-outline"] lineBasicMaterial',
    );
    const selectedOutline = document.querySelector('lineSegments[name="model-surface-selected-outline"]');
    expect(selectedOutlineMaterial).not.toBeNull();
    expect(selectedOutlineMaterial).toHaveAttribute("opacity", "0.92");
    expect(selectedOutline).toHaveAttribute("position", "0,0,0.007000000000000001");
    expect(selectedOutline).toHaveAttribute("renderOrder", "31");
  });

  it("returns to mesh-free candidate picking when reselecting an already selected surface", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));
    const onSelectFace = vi.fn();
    const footprint = {
      frame: {
        origin: [0, 0, 1] as [number, number, number],
        normal: [0, 0, 1] as [number, number, number],
        u_axis: [1, 0, 0] as [number, number, number],
        v_axis: [0, 1, 0] as [number, number, number],
      },
      bounds_min: [-10, -5] as [number, number],
      bounds_max: [10, 5] as [number, number],
      bounds_width_mm: 20,
      bounds_height_mm: 10,
      outer: [[-10, -5], [10, -5], [10, 5], [-10, 5], [-10, -5]] as [number, number][],
      holes: [],
    };

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady
        selecting={false}
        footprint={footprint}
        surfaceCandidates={[
          {
            id: "surface-4",
            face_index: 4,
            face_count: 2,
            area_mm2: 200,
            normal: [0, 0, 1],
            footprint,
          },
        ]}
        onSelectFace={onSelectFace}
      />,
    );

    await screen.findByRole("button", { name: "重选面" });
    expect(document.querySelector('mesh[name^="model-surface-candidate-"]')).toBeNull();
    expect(document.querySelector('lineSegments[name="model-surface-selected-outline"]')).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "重选面" }));
    await waitFor(() => {
      expect(screen.getByRole("status", { name: "选择覆面平面" })).toBeInTheDocument();
    });
    expect(document.querySelector('mesh[name^="model-surface-candidate-"]')).toBeNull();
    expect(document.querySelector('lineSegments[name="model-surface-selected-outline"]')).toBeNull();

    fireModelSurfacePointerDown(requireModelSurfaceBody());

    expect(onSelectFace).toHaveBeenCalledWith(4, "surface-4");
  });

  it("does not rotate the uploaded model when dragging the model body in rotate mode", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    const modelGroup = await waitFor(() => {
      const element = document.querySelector('group[name="model-surface-transform"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });
    const initialRotation = modelGroup.getAttribute("rotation");

    const modelMesh = document.querySelector('mesh[name="model-surface-body"]');
    expect(modelMesh).not.toBeNull();
    fireEvent.pointerDown(modelMesh!, { clientX: 100, clientY: 100, pointerId: 1 });
    fireEvent.pointerMove(modelMesh!, { clientX: 150, clientY: 130, pointerId: 1 });
    fireEvent.pointerUp(modelMesh!, { clientX: 150, clientY: 130, pointerId: 1 });

    expect(modelGroup.getAttribute("rotation")).toBe(initialRotation);
  });

  it("keeps orbit controls available in rotate mode except while dragging a rotation ring", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    expect(mockControls.enabled).toBe(true);

    const zHitTarget = await waitFor(() => {
      const element = document.querySelector('mesh[name="model-rotation-z-hit-target"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });

    fireEvent.pointerDown(zHitTarget, { pointerId: 1, clientX: 100, clientY: 100 });
    expect(mockControls.enabled).toBe(false);

    fireEvent.pointerUp(zHitTarget, { pointerId: 1, clientX: 110, clientY: 110 });
    expect(mockControls.enabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    expect(mockControls.enabled).toBe(true);
  });

  it("keeps model rotation drag active when the pointer leaves the ring before release", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    const zHitTarget = await waitFor(() => {
      const element = document.querySelector('mesh[name="model-rotation-z-hit-target"]');
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });

    fireEvent.pointerDown(zHitTarget, { pointerId: 1, clientX: 100, clientY: 100 });
    expect(mockControls.enabled).toBe(false);

    fireEvent.pointerLeave(zHitTarget, { pointerId: 1, clientX: 40, clientY: 40 });
    expect(mockControls.enabled).toBe(false);

    fireEvent.pointerUp(zHitTarget, { pointerId: 1, clientX: 40, clientY: 40 });
    expect(mockControls.enabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    expect(mockControls.enabled).toBe(true);
  });

  it("reveals rotation axis details when native pointer hover is near a screen-projected ring", async () => {
    vi.spyOn(THREE.Box3.prototype, "setFromObject").mockImplementation(function (this: THREE.Box3) {
      this.min.set(-10, -5, 0);
      this.max.set(10, 5, 2);
      return this;
    });
    Object.defineProperty(HTMLElement.prototype, "updateMatrixWorld", {
      configurable: true,
      value: vi.fn(),
    });
    const canvas = document.createElement("canvas");
    Object.defineProperty(canvas, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        x: 0,
        y: 0,
        left: 0,
        top: 0,
        right: 1000,
        bottom: 1000,
        width: 1000,
        height: 1000,
        toJSON: () => undefined,
      }),
    });
    mockGl.domElement = canvas;
    const file = new File(["solid"], "plate.stl");
    vi.spyOn(file, "arrayBuffer").mockResolvedValue(new ArrayBuffer(16));

    render(
      <ModelSurfaceSelector3D
        file={file}
        selectionReady={false}
        selecting={false}
        onSelectFace={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "旋转模型" }));
    await waitFor(() => {
      expect(document.querySelector('mesh[name="model-rotation-z-hit-target"]')).not.toBeNull();
    });
    expect(document.querySelector('group[name="model-rotation-ticks"]')).not.toBeNull();
    expect(document.querySelector('lineSegments[name="model-rotation-z-ticks"]')).not.toBeNull();

    const center = new THREE.Vector3(0, 0, 1);
    const ringPoint = center.clone().add(new THREE.Vector3(Math.SQRT1_2 * 20, Math.SQRT1_2 * 20, 0));
    const projected = ringPoint.project(mockCamera);
    fireEvent.pointerMove(canvas, {
      clientX: ((projected.x + 1) / 2) * 1000 + 12,
      clientY: ((1 - projected.y) / 2) * 1000,
    });

    await waitFor(() => {
      expect(document.querySelector('group[name="model-rotation-ticks"]')).not.toBeNull();
    });
    expect(screen.getAllByText("Z: 0.00°").length).toBeGreaterThan(0);

    fireEvent.pointerDown(canvas, {
      pointerId: 1,
      button: 0,
      clientX: ((projected.x + 1) / 2) * 1000 + 12,
      clientY: ((1 - projected.y) / 2) * 1000,
    });
    fireEvent.pointerMove(canvas, {
      pointerId: 1,
      buttons: 1,
      clientX: ((projected.x + 1) / 2) * 1000 + 48,
      clientY: ((1 - projected.y) / 2) * 1000 + 24,
    });

    await waitFor(() => {
      expect(screen.getByLabelText("旋转角度提示")).toBeInTheDocument();
    });
  });
});

describe("getModelBodyRaycastProps", () => {
  it("keeps the model body raycastable while selecting faces and disables it only while rotating the model", () => {
    expect(getModelBodyRaycastProps("select")).not.toHaveProperty("raycast");
    expect(getModelBodyRaycastProps("move")).not.toHaveProperty("raycast");
    expect(getModelBodyRaycastProps("modelRotate").raycast).toEqual(expect.any(Function));
  });
});

describe("computeModelRotationDragDegrees", () => {
  it("keeps the current model angle when the pointer has not moved on the rotation ring", () => {
    expect(computeModelRotationDragDegrees(30, 95, 95, 80, 100)).toBeCloseTo(30);
  });

  it("uses the shortest signed delta from the pointer-down angle", () => {
    expect(computeModelRotationDragDegrees(30, 350, 10, 80, 100)).toBeCloseTo(50);
    expect(computeModelRotationDragDegrees(30, 10, 350, 80, 100)).toBeCloseTo(10);
  });

  it("wraps negative drag results back into slicer-style 0 to 360 degree angles", () => {
    expect(computeModelRotationDragDegrees(10, 20, 350, 80, 100)).toBeCloseTo(340);
  });

  it("snaps to coarse angle increments when the pointer is in the inner snap band", () => {
    expect(computeModelRotationDragDegrees(30, 0, 13, 45, 90)).toBeCloseTo(45);
  });

  it("snaps to fine scale-tooth increments when the pointer is on the outer scale band", () => {
    expect(computeModelRotationDragDegrees(0, 0, 13, 104, 100)).toBeCloseTo(15);
  });

  it("does not fine snap outside the slicer scale-tooth radius", () => {
    expect(computeModelRotationDragDegrees(0, 0, 13, 112, 100)).toBeCloseTo(13);
  });
});

describe("getRotationPointerResultFromPointOrRay", () => {
  it("prefers the actual ring hit point over a ray-plane intersection", () => {
    const result = getRotationPointerResultFromPointOrRay(
      new THREE.Vector3(0, 100, 0),
      new THREE.Ray(new THREE.Vector3(-10, 0, -100), new THREE.Vector3(1, 0, 0)),
      new THREE.Vector3(0, 0, 0),
      new THREE.Vector3(0, 0, -1),
      new THREE.Vector3(0, 1, 0),
      new THREE.Vector3(1, 0, 0),
    );

    expect(result?.degrees).toBeCloseTo(90);
  });
});

describe("getRotationHitTargetTubeRadius", () => {
  it("keeps the invisible rotation ring hit area wider than the visual ring", () => {
    expect(getRotationHitTargetTubeRadius(100)).toBeCloseTo(16);
    expect(getRotationHitTargetTubeRadius(40)).toBeCloseTo(8);
  });
});

describe("Bambu/Orca rotation gizmo sizing", () => {
  it("uses a fixed 5mm object offset for the rotation ring instead of scaling the model radius", () => {
    expect(getRotationGizmoRadius(141.42)).toBeCloseTo(146.42);
    expect(getRotationGizmoRadius(8)).toBeCloseTo(20);
  });

  it("draws rotation scale ticks from the ring outward like slicer gizmos", () => {
    expect(getRotationTickSegmentRadii(0, 100).innerRadius).toBeCloseTo(100);
    expect(getRotationTickSegmentRadii(0, 100).outerRadius).toBeCloseTo(110);
    expect(getRotationTickSegmentRadii(1, 100).innerRadius).toBeCloseTo(100);
    expect(getRotationTickSegmentRadii(1, 100).outerRadius).toBeCloseTo(105);
  });
});

describe("getSurfaceFocusRadius", () => {
  it("keeps tiny triangle selections from pulling the camera inside the model", () => {
    expect(getSurfaceFocusRadius(1.2, 1.7, 100)).toBeCloseTo(22);
    expect(getSurfaceFocusRadius(200, 100, 100)).toBeCloseTo(100);
    expect(getSurfaceFocusRadius(1, 1, 8)).toBeCloseTo(8);
  });
});

describe("findNearestRotationAxisScreenHit", () => {
  it("hits the screen-projected rotation ring instead of requiring a precise 3D torus raycast", () => {
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
    camera.position.set(0, 0, 500);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld(true);
    const viewport = { left: 0, top: 0, width: 1000, height: 1000 };
    const projectedRingPoint = new THREE.Vector3(Math.SQRT1_2 * 100, Math.SQRT1_2 * 100, 0).project(camera);
    const pointer = {
      x: ((projectedRingPoint.x + 1) / 2) * viewport.width + 12,
      y: ((1 - projectedRingPoint.y) / 2) * viewport.height,
    };

    expect(
      findNearestRotationAxisScreenHit(
        pointer,
        new THREE.Vector3(0, 0, 0),
        100,
        camera,
        viewport,
        24,
      ),
    ).toBe("z");
    expect(
      findNearestRotationAxisScreenHit(
        { x: 50, y: 50 },
        new THREE.Vector3(0, 0, 0),
        100,
        camera,
        viewport,
        24,
      ),
    ).toBeNull();
    expect(
      findNearestRotationAxisScreenHit(
        { x: 500, y: 500 },
        new THREE.Vector3(0, 0, 0),
        100,
        camera,
        viewport,
        24,
      ),
    ).toBeNull();
  });
});
