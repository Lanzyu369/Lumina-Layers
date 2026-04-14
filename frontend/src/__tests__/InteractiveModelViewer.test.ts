import { createElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render } from "@testing-library/react";
import * as THREE from "three";

const mockFiberState = vi.hoisted(() => ({
  canvas: null as HTMLCanvasElement | null,
  gl: null as { domElement: HTMLCanvasElement } | null,
  camera: null as THREE.PerspectiveCamera | null,
}));

vi.mock("@react-three/fiber", () => {
  const canvas = document.createElement("canvas");
  canvas.getBoundingClientRect = () => ({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 200,
    bottom: 200,
    width: 200,
    height: 200,
    toJSON: () => ({}),
  });

  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 1000);
  camera.position.set(0, 0, 100);
  camera.lookAt(0, 0, 0);
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld(true);

  const gl = { domElement: canvas };
  mockFiberState.canvas = canvas;
  mockFiberState.gl = gl;
  mockFiberState.camera = camera;

  return {
    useThree: (selector?: (state: {
      gl: typeof gl;
      camera: THREE.PerspectiveCamera;
      scene: THREE.Scene;
      controls: null;
    }) => unknown) => {
      const state = {
        gl,
        camera,
        scene: new THREE.Scene(),
        controls: null,
      };
      return selector ? selector(state) : state;
    },
    useFrame: vi.fn(),
  };
});

vi.mock("@react-three/drei", () => {
  const useGLTF = vi.fn(() => {
    const scene = new THREE.Group();
    const colorMesh = new THREE.Mesh(
      new THREE.BoxGeometry(10, 10, 2),
      new THREE.MeshLambertMaterial({ color: 0xff0000 }),
    );
    colorMesh.name = "color_ff0000";
    scene.add(colorMesh);
    return { scene };
  });

  return {
    useGLTF: Object.assign(useGLTF, { clear: vi.fn() }),
  };
});

vi.mock("../components/OutlineFrame3D", () => ({ default: () => null }));
vi.mock("../components/CloisonneWire3D", () => ({ default: () => null }));
vi.mock("../components/PuzzleOverlay3D", () => ({ default: () => null }));
vi.mock("../components/useGltfCacheLifecycle", () => ({ useGltfCacheLifecycle: () => undefined }));
vi.mock("../utils/threeDebug", () => ({
  debugThreeLog: vi.fn(),
  getLatestResourceTiming: vi.fn(() => null),
  summarizeMeshList: vi.fn(() => []),
  summarizeObjectTree: vi.fn(() => ({})),
}));
vi.mock("../utils/threeDisposal", () => ({
  cloneObjectTreeWithOwnedResources: (object: THREE.Object3D) => object.clone(true),
  disposeMaterial: vi.fn(),
  disposeMeshResources: vi.fn(),
  disposeObjectTree: vi.fn(),
}));

import { useConverterStore } from "../stores/converter";
import InteractiveModelViewer, {
  extractHexFromMeshName,
  isClickWithoutDrag,
  resolveSelectionOutlineTargets,
  shouldHandleColorPickingEvent,
  toggleColorSelection,
} from "../components/InteractiveModelViewer";

describe("extractHexFromMeshName", () => {
  it('extracts hex from "color_ff0000"', () => {
    expect(extractHexFromMeshName("color_ff0000")).toBe("ff0000");
  });

  it('extracts hex from "color_00ff00"', () => {
    expect(extractHexFromMeshName("color_00ff00")).toBe("00ff00");
  });

  it('extracts hex from "color_AABBCC" preserving case', () => {
    expect(extractHexFromMeshName("color_AABBCC")).toBe("AABBCC");
  });

  it("extracts hex from color_ prefix with 6 chars", () => {
    expect(extractHexFromMeshName("color_000000")).toBe("000000");
    expect(extractHexFromMeshName("color_ffffff")).toBe("ffffff");
  });
});

describe("toggleColorSelection", () => {
  it("returns null when clicking the already selected color (deselect)", () => {
    expect(toggleColorSelection("ff0000", "ff0000")).toBeNull();
  });

  it("returns the clicked hex when no color is selected", () => {
    expect(toggleColorSelection(null, "00ff00")).toBe("00ff00");
  });

  it("returns the clicked hex when a different color is selected", () => {
    expect(toggleColorSelection("ff0000", "00ff00")).toBe("00ff00");
  });

  it("returns null for same color regardless of case match", () => {
    expect(toggleColorSelection("aabbcc", "aabbcc")).toBeNull();
  });

  it("returns clicked hex when selected is different", () => {
    expect(toggleColorSelection("111111", "222222")).toBe("222222");
  });
});

describe("isClickWithoutDrag", () => {
  it("returns true when pointer movement stays within the threshold", () => {
    expect(isClickWithoutDrag(10, 10, 12, 13, 4)).toBe(true);
  });

  it("returns true when pointer movement is exactly on the threshold", () => {
    expect(isClickWithoutDrag(0, 0, 3, 4, 5)).toBe(true);
  });

  it("returns false when pointer movement exceeds the threshold", () => {
    expect(isClickWithoutDrag(0, 0, 4, 4, 5)).toBe(false);
  });
});

describe("shouldHandleColorPickingEvent", () => {
  it("suppresses color picking when the viewer disables it for fridge magnet mode", () => {
    expect(shouldHandleColorPickingEvent(0, false)).toBe(false);
  });

  it("allows left-click color picking when the viewer keeps it enabled", () => {
    expect(shouldHandleColorPickingEvent(0, true)).toBe(true);
  });

  it("ignores non-left clicks even when color picking is enabled", () => {
    expect(shouldHandleColorPickingEvent(2, true)).toBe(false);
  });
});

describe("resolveSelectionOutlineTargets", () => {
  const modelBounds = {
    minX: -10,
    maxX: 10,
    minY: -10,
    maxY: 10,
    maxZ: 2,
  };
  const polygon = [[[0, 0], [1, 0], [1, 1]]];

  it("returns no selection visuals when selectionVisualsEnabled is false even with stale selection state", () => {
    expect(resolveSelectionOutlineTargets({
      selectionVisualsEnabled: false,
      modelBounds,
      selectionMode: "current",
      selectedColor: "ff0000",
      selectedColors: new Set(["ff0000"]),
      selectedRegions: [{
        colorHex: "#ff0000",
        contours: polygon,
      }],
      regionData: {
        contours: polygon,
      },
      colorContours: { ff0000: polygon },
    })).toEqual([]);
  });

  it("keeps the existing contour selection semantics when selection visuals stay enabled", () => {
    expect(resolveSelectionOutlineTargets({
      selectionVisualsEnabled: true,
      modelBounds,
      selectionMode: "select-all",
      selectedColor: "ff0000",
      selectedColors: new Set(["ff0000"]),
      selectedRegions: [],
      regionData: null,
      colorContours: { ff0000: polygon },
    })).toEqual([{ hex: "ff0000", polygons: polygon }]);
  });
});

describe("InteractiveModelViewer native color-picking gate", () => {
  beforeEach(() => {
    useConverterStore.setState({
      selectionMode: "select-all",
      selectedColors: new Set<string>(),
      selectedRegions: [],
      regionData: null,
      previewPixelWidth: 100,
      previewPixelHeight: 100,
      preview_width_mm: 100,
    });
  });

  it("does not trigger color selection from native canvas pointer handlers when colorPickingEnabled is false", () => {
    const onColorClick = vi.fn();
    const addEventListenerSpy = vi.spyOn(mockFiberState.canvas!, "addEventListener");

    render(createElement(InteractiveModelViewer, {
      url: "/mock.glb",
      colorRemapMap: {},
      colorHeightMap: {},
      selectedColor: null,
      baseHeight: 1,
      enableRelief: false,
      onColorClick,
      colorPickingEnabled: false,
    }));

    expect(addEventListenerSpy).toHaveBeenCalledWith("pointerdown", expect.any(Function));
    expect(addEventListenerSpy).toHaveBeenCalledWith("pointerup", expect.any(Function));

    fireEvent.pointerDown(mockFiberState.canvas!, {
      button: 0,
      pointerId: 1,
      clientX: 20,
      clientY: 20,
    });
    fireEvent.pointerUp(mockFiberState.canvas!, {
      button: 0,
      pointerId: 1,
      clientX: 20,
      clientY: 20,
    });

    expect(onColorClick).not.toHaveBeenCalled();
    addEventListenerSpy.mockRestore();
  });
});
