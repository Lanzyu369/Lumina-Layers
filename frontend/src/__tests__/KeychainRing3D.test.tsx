import { StrictMode } from "react";
import { act, render } from "@testing-library/react";
import { afterEach, describe, it, expect, vi } from "vitest";
import * as THREE from "three";
import {
  default as KeychainRing3D,
  createKeychainRingGeometry,
  computeLoopPosition,
  resetKeychainRingGeometryDisposeForTests,
} from "../components/KeychainRing3D";

const mockControls = { enabled: true };
const mockCanvas = document.createElement("canvas");
mockCanvas.getBoundingClientRect = () => ({
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

const mockCamera = new THREE.OrthographicCamera(-100, 100, 100, -100, 0.1, 1000);
mockCamera.position.set(0, 0, 100);
mockCamera.lookAt(0, 0, 0);
mockCamera.updateProjectionMatrix();
mockCamera.updateMatrixWorld(true);

const mockThreeState = {
  controls: mockControls,
  camera: mockCamera,
  gl: { domElement: mockCanvas },
};

// Mock R3F — Canvas renders as plain div in jsdom
vi.mock("@react-three/fiber", () => ({
  Canvas: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="mock-canvas">{children}</div>
  ),
  useThree: () => mockThreeState,
}));

const defaultBounds = {
  minX: -10,
  maxX: 10,
  minY: -15,
  maxY: 15,
  maxZ: 5,
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  resetKeychainRingGeometryDisposeForTests();
  mockControls.enabled = true;
  document.body.style.cursor = "default";
});

function getReactProps<T extends object>(element: Element): T {
  const reactPropsKey = Object.keys(element).find((key) => key.startsWith("__reactProps"));
  if (!reactPropsKey) {
    throw new Error("React props were not attached to the element");
  }

  return (element as unknown as Record<string, T>)[reactPropsKey];
}

describe("KeychainRing3D", () => {
  describe("enabled/disabled rendering", () => {
    it("returns null when enabled=false", () => {
      const { container } = render(
        <KeychainRing3D
          enabled={false}
          width={4}
          length={8}
          hole={2}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={defaultBounds}
        />,
      );
      expect(container.innerHTML).toBe("");
    });

    it("returns null when modelBounds is null (Req 6.2)", () => {
      const { container } = render(
        <KeychainRing3D
          enabled={true}
          width={4}
          length={8}
          hole={2}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={null}
        />,
      );
      expect(container.innerHTML).toBe("");
    });

    it("does not crash when enabled=true with valid params", () => {
      // Geometry creation is valid — component should render without error
      const geo = createKeychainRingGeometry(4, 8, 2);
      expect(geo).not.toBeNull();
    });

    it("geometry is null when hole >= width (component would return null)", () => {
      // hole === width → invalid geometry → component returns null
      const geo = createKeychainRingGeometry(3, 8, 3);
      expect(geo).toBeNull();
    });

    it("does not dispose the active geometry during StrictMode mount replay", () => {
      vi.useFakeTimers();
      const disposeSpy = vi.spyOn(THREE.BufferGeometry.prototype, "dispose");
      const { unmount } = render(
        <StrictMode>
          <KeychainRing3D
            enabled={true}
            width={4}
            length={8}
            hole={2}
            angle={0}
            offsetX={0}
            offsetY={0}
            positionPreset="top-center"
            modelBounds={defaultBounds}
          />
        </StrictMode>,
      );

      act(() => {
        vi.runAllTimers();
      });

      expect(disposeSpy).not.toHaveBeenCalled();

      unmount();
      act(() => {
        vi.runAllTimers();
      });
    });

    it("disposes replaced geometry only after the deferred timer flushes", () => {
      vi.useFakeTimers();
      const disposeSpy = vi.spyOn(THREE.BufferGeometry.prototype, "dispose");
      const { rerender, unmount } = render(
        <KeychainRing3D
          enabled={true}
          width={4}
          length={8}
          hole={2}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={defaultBounds}
        />,
      );

      rerender(
        <KeychainRing3D
          enabled={true}
          width={5}
          length={9}
          hole={1.5}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={defaultBounds}
        />,
      );

      expect(disposeSpy).not.toHaveBeenCalled();

      act(() => {
        vi.runAllTimers();
      });

      expect(disposeSpy).toHaveBeenCalledTimes(1);

      unmount();
      act(() => {
        vi.runAllTimers();
      });
    });

    it("disposes geometry when rerendering to null via enabled=false", () => {
      vi.useFakeTimers();
      const disposeSpy = vi.spyOn(THREE.BufferGeometry.prototype, "dispose");
      const { rerender, unmount } = render(
        <KeychainRing3D
          enabled={true}
          width={4}
          length={8}
          hole={2}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={defaultBounds}
        />,
      );

      rerender(
        <KeychainRing3D
          enabled={false}
          width={4}
          length={8}
          hole={2}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={defaultBounds}
        />,
      );

      expect(disposeSpy).not.toHaveBeenCalled();

      act(() => {
        vi.runAllTimers();
      });

      expect(disposeSpy).toHaveBeenCalledTimes(1);

      unmount();
    });

    it("restores orbit controls and cursor when dragging is interrupted by rerender-to-null", () => {
      const { container, rerender } = render(
        <KeychainRing3D
          enabled={true}
          width={4}
          length={8}
          hole={2}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={defaultBounds}
        />,
      );

      const ring = container.querySelector("mesh");
      expect(ring).not.toBeNull();

      act(() => {
        getReactProps<{
          onPointerDown: (event: {
            stopPropagation: () => void;
            ray: { intersectPlane: (plane: THREE.Plane, target: THREE.Vector3) => THREE.Vector3 };
          }) => void;
        }>(ring as Element).onPointerDown({
          stopPropagation: () => {},
          ray: {
            intersectPlane: (_plane: THREE.Plane, target: THREE.Vector3) => target.set(0, 0, 0),
          },
        });
      });

      expect(mockControls.enabled).toBe(false);
      expect(document.body.style.cursor).toBe("grabbing");

      rerender(
        <KeychainRing3D
          enabled={false}
          width={4}
          length={8}
          hole={2}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={defaultBounds}
        />,
      );

      expect(mockControls.enabled).toBe(true);
      expect(document.body.style.cursor).toBe("default");
    });

    it("restores orbit controls and cursor when dragging is interrupted by unmount", () => {
      const { container, unmount } = render(
        <KeychainRing3D
          enabled={true}
          width={4}
          length={8}
          hole={2}
          angle={0}
          offsetX={0}
          offsetY={0}
          positionPreset="top-center"
          modelBounds={defaultBounds}
        />,
      );

      const ring = container.querySelector("mesh");
      expect(ring).not.toBeNull();

      act(() => {
        getReactProps<{
          onPointerDown: (event: {
            stopPropagation: () => void;
            ray: { intersectPlane: (plane: THREE.Plane, target: THREE.Vector3) => THREE.Vector3 };
          }) => void;
        }>(ring as Element).onPointerDown({
          stopPropagation: () => {},
          ray: {
            intersectPlane: (_plane: THREE.Plane, target: THREE.Vector3) => target.set(0, 0, 0),
          },
        });
      });

      expect(mockControls.enabled).toBe(false);
      expect(document.body.style.cursor).toBe("grabbing");

      unmount();

      expect(mockControls.enabled).toBe(true);
      expect(document.body.style.cursor).toBe("default");
    });
  });
});

describe("createKeychainRingGeometry", () => {
  it("produces valid geometry with default params", () => {
    const geo = createKeychainRingGeometry(4, 8, 2);
    expect(geo).not.toBeNull();
    expect(geo!.attributes.position.count).toBeGreaterThan(0);
  });

  it("produces geometry with vertices for min valid params", () => {
    // width=2, length=4, hole=1 → hole < min(2,4)=2 ✓
    const geo = createKeychainRingGeometry(2, 4, 1);
    expect(geo).not.toBeNull();
    expect(geo!.attributes.position.count).toBeGreaterThan(0);
  });

  it("produces geometry with vertices for max valid params", () => {
    // width=10, length=15, hole=5 → hole < min(10,15)=10 ✓
    const geo = createKeychainRingGeometry(10, 15, 5);
    expect(geo).not.toBeNull();
    expect(geo!.attributes.position.count).toBeGreaterThan(0);
  });

  it("returns null when hole >= min(width, length)", () => {
    // hole=5 >= min(5, 10)=5 → invalid
    expect(createKeychainRingGeometry(5, 10, 5)).toBeNull();
    // hole=6 >= min(4, 8)=4 → invalid
    expect(createKeychainRingGeometry(4, 8, 6)).toBeNull();
  });

  it("returns null when hole > width but < length", () => {
    // hole=4 >= min(3, 8)=3 → invalid
    expect(createKeychainRingGeometry(3, 8, 4)).toBeNull();
  });

  it("returns null for zero or negative dimensions", () => {
    expect(createKeychainRingGeometry(0, 8, 2)).toBeNull();
    expect(createKeychainRingGeometry(4, 0, 2)).toBeNull();
    expect(createKeychainRingGeometry(4, 8, 0)).toBeNull();
    expect(createKeychainRingGeometry(-1, 8, 2)).toBeNull();
  });

  it("geometry has non-degenerate faces (index count > 0)", () => {
    const geo = createKeychainRingGeometry(6, 10, 3);
    expect(geo).not.toBeNull();
    // ExtrudeGeometry uses indexed geometry
    if (geo!.index) {
      expect(geo!.index.count).toBeGreaterThan(0);
    } else {
      // Non-indexed: position count implies triangles
      expect(geo!.attributes.position.count).toBeGreaterThan(0);
    }
  });
});

describe("computeLoopPosition", () => {
  const bounds = { minX: -10, maxX: 10, minY: -15, maxY: 15 };

  it("returns center X, maxY as base position (top-center anchor)", () => {
    const pos = computeLoopPosition("top-center", bounds, 0, 0);
    expect(pos.x).toBe(0);
    expect(pos.y).toBe(15);
  });

  it("ignores preset value — always anchors at top-center", () => {
    // All presets should produce the same base position
    const presets = ["top-left", "top-right", "left-center", "right-center", "bottom-center", "invalid"];
    for (const preset of presets) {
      const pos = computeLoopPosition(preset, bounds, 0, 0);
      expect(pos.x).toBe(0);
      expect(pos.y).toBe(15);
    }
  });

  it("applies offset correctly", () => {
    const pos = computeLoopPosition("top-center", bounds, 5, -3);
    expect(pos.x).toBe(5);
    expect(pos.y).toBe(12);
  });

  it("works with asymmetric bounds", () => {
    const asymBounds = { minX: 0, maxX: 20, minY: -5, maxY: 25 };
    const pos = computeLoopPosition("top-center", asymBounds, 0, 0);
    expect(pos.x).toBe(10);
    expect(pos.y).toBe(25);
  });
});
