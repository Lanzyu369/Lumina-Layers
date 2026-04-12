import { useCallback, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render } from "@testing-library/react";
import * as THREE from "three";
import type { FridgeMagnetItem } from "../api/types";
import { FRIDGE_MAGNET_SPACER_CLEARANCE_MM } from "../constants/fridgeMagnets";
import FridgeMagnet3D, {
  clampFridgeMagnetCenter,
  createFridgeMagnetProxyEdgeGeometry,
  createFridgeMagnetProxyGeometry,
  getFridgeMagnetGeometryKey,
  getFridgeMagnetProxyDimensions,
  getInitialDragPoint,
  getFridgeMagnetProxyPosition,
} from "../components/FridgeMagnet3D";

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

vi.mock("@react-three/fiber", () => ({
  useThree: () => mockThreeState,
}));

const modelBounds = {
  minX: -10,
  maxX: 10,
  minY: -15,
  maxY: 15,
  maxZ: 8,
};

const roundMagnet: FridgeMagnetItem = {
  id: "magnet-round",
  shape: "round",
  preset_key: "round-d12x3",
  diameter_mm: 12,
  width_mm: null,
  height_mm: null,
  thickness_mm: 3,
  center_x_mm: 0,
  center_y_mm: 0,
};

const rectMagnet: FridgeMagnetItem = {
  id: "magnet-rect",
  shape: "rect",
  preset_key: "rect-15x5x2",
  diameter_mm: null,
  width_mm: 15,
  height_mm: 5,
  thickness_mm: 2,
  center_x_mm: 4,
  center_y_mm: -3,
};

describe("FridgeMagnet3D", () => {
  beforeEach(() => {
    mockControls.enabled = true;
    document.body.style.cursor = "default";
  });

  it("returns null when disabled or bounds are missing", () => {
    const disabled = render(
      <FridgeMagnet3D
        enabled={false}
        modelBounds={modelBounds}
        magnets={[roundMagnet]}
        scaleX={1}
        scaleY={1}
        selectedMagnetId={null}
        onSelectMagnet={vi.fn()}
        onUpdateMagnetCenter={vi.fn()}
      />,
    );
    expect(disabled.container.innerHTML).toBe("");

    const noBounds = render(
      <FridgeMagnet3D
        enabled={true}
        modelBounds={null}
        magnets={[roundMagnet]}
        scaleX={1}
        scaleY={1}
        selectedMagnetId={null}
        onSelectMagnet={vi.fn()}
        onUpdateMagnetCenter={vi.fn()}
      />,
    );
    expect(noBounds.container.innerHTML).toBe("");
  });

  it("renders one proxy per fridge magnet and supports round + rect geometry", () => {
    const { container } = render(
      <FridgeMagnet3D
        enabled={true}
        modelBounds={modelBounds}
        magnets={[roundMagnet, rectMagnet]}
        scaleX={1}
        scaleY={1}
        selectedMagnetId={rectMagnet.id}
        onSelectMagnet={vi.fn()}
        onUpdateMagnetCenter={vi.fn()}
      />,
    );

    const roundProxy = container.querySelector('group[name="fridge-magnet-proxy-magnet-round"]');
    const rectProxy = container.querySelector('group[name="fridge-magnet-proxy-magnet-rect"]');

    expect(roundProxy).not.toBeNull();
    expect(rectProxy).not.toBeNull();
    expect(roundProxy?.querySelectorAll("mesh").length).toBe(1);
    expect(rectProxy?.querySelectorAll("mesh").length).toBe(1);
    expect(roundProxy?.querySelectorAll("lineSegments").length).toBe(1);
    expect(rectProxy?.querySelectorAll("lineSegments").length).toBe(1);

    const roundOverlayMaterials = roundProxy?.querySelectorAll("meshBasicMaterial");
    const rectOverlayMaterials = rectProxy?.querySelectorAll("meshBasicMaterial");
    expect(roundOverlayMaterials).toHaveLength(1);
    expect(rectOverlayMaterials).toHaveLength(1);
    expect(roundProxy?.querySelectorAll("lineBasicMaterial")).toHaveLength(1);
    expect(rectProxy?.querySelectorAll("lineBasicMaterial")).toHaveLength(1);

    const roundFill = roundOverlayMaterials?.[0];
    const rectFill = rectOverlayMaterials?.[0];
    expect(roundFill?.getAttribute("color")).not.toBe(rectFill?.getAttribute("color"));
  });

  it("selects the clicked proxy and drags with window-level tracking while disabling orbit controls", () => {
    const onSelectMagnet = vi.fn();
    const onUpdateMagnetCenter = vi.fn();

    const { container } = render(
      <FridgeMagnet3D
        enabled={true}
        modelBounds={modelBounds}
        magnets={[roundMagnet]}
        scaleX={1}
        scaleY={1}
        selectedMagnetId={null}
        onSelectMagnet={onSelectMagnet}
        onUpdateMagnetCenter={onUpdateMagnetCenter}
      />,
    );

    const proxy = container.querySelector('group[name="fridge-magnet-proxy-magnet-round"]');
    expect(proxy).not.toBeNull();

    fireEvent.pointerDown(proxy as Element, { clientX: 100, clientY: 100 });

    expect(onSelectMagnet).toHaveBeenCalledWith(roundMagnet.id);
    expect(mockControls.enabled).toBe(false);

    fireEvent.pointerMove(window, { clientX: 200, clientY: 0 });

    expect(onUpdateMagnetCenter).toHaveBeenLastCalledWith(roundMagnet.id, 4, 9);

    fireEvent.pointerUp(window);

    expect(mockControls.enabled).toBe(true);
  });

  it("ignores non-primary pointerdown so right or middle click cannot start selection or drag", () => {
    const onSelectMagnet = vi.fn();
    const onUpdateMagnetCenter = vi.fn();

    const { container } = render(
      <FridgeMagnet3D
        enabled={true}
        modelBounds={modelBounds}
        magnets={[roundMagnet]}
        scaleX={1}
        scaleY={1}
        selectedMagnetId={null}
        onSelectMagnet={onSelectMagnet}
        onUpdateMagnetCenter={onUpdateMagnetCenter}
      />,
    );

    const proxy = container.querySelector('group[name="fridge-magnet-proxy-magnet-round"]');
    expect(proxy).not.toBeNull();

    fireEvent.pointerDown(proxy as Element, { button: 1, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 200, clientY: 0 });
    fireEvent.pointerUp(window, { button: 1 });

    fireEvent.pointerDown(proxy as Element, { button: 2, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 0, clientY: 200 });
    fireEvent.pointerUp(window, { button: 2 });

    expect(onSelectMagnet).not.toHaveBeenCalled();
    expect(onUpdateMagnetCenter).not.toHaveBeenCalled();
    expect(mockControls.enabled).toBe(true);
  });

  it("keeps dragging after pointerout and still completes on pointerup", () => {
    const onUpdateMagnetCenter = vi.fn();

    const { container } = render(
      <FridgeMagnet3D
        enabled={true}
        modelBounds={modelBounds}
        magnets={[roundMagnet]}
        scaleX={1}
        scaleY={1}
        selectedMagnetId={null}
        onSelectMagnet={vi.fn()}
        onUpdateMagnetCenter={onUpdateMagnetCenter}
      />,
    );

    const proxy = container.querySelector('group[name="fridge-magnet-proxy-magnet-round"]');
    expect(proxy).not.toBeNull();

    fireEvent.pointerDown(proxy as Element, { clientX: 100, clientY: 100 });
    expect(mockControls.enabled).toBe(false);

    fireEvent.pointerOut(proxy as Element);
    fireEvent.pointerMove(window, { clientX: 150, clientY: 50 });

    expect(onUpdateMagnetCenter).toHaveBeenLastCalledWith(roundMagnet.id, 4, 9);

    fireEvent.pointerUp(window);

    expect(mockControls.enabled).toBe(true);
    const callCountAfterPointerUp = onUpdateMagnetCenter.mock.calls.length;

    fireEvent.pointerMove(window, { clientX: 0, clientY: 200 });

    expect(onUpdateMagnetCenter).toHaveBeenCalledTimes(callCountAfterPointerUp);
  });

  it("restores orbit controls when drag is interrupted by pointercancel", () => {
    const onUpdateMagnetCenter = vi.fn();

    const { container } = render(
      <FridgeMagnet3D
        enabled={true}
        modelBounds={modelBounds}
        magnets={[roundMagnet]}
        scaleX={1}
        scaleY={1}
        selectedMagnetId={null}
        onSelectMagnet={vi.fn()}
        onUpdateMagnetCenter={onUpdateMagnetCenter}
      />,
    );

    const proxy = container.querySelector('group[name="fridge-magnet-proxy-magnet-round"]');
    expect(proxy).not.toBeNull();

    fireEvent.pointerDown(proxy as Element, { clientX: 100, clientY: 100 });
    expect(mockControls.enabled).toBe(false);

    fireEvent.pointerCancel(window);

    expect(mockControls.enabled).toBe(true);
    const callCountAfterCancel = onUpdateMagnetCenter.mock.calls.length;

    fireEvent.pointerMove(window, { clientX: 160, clientY: 40 });

    expect(onUpdateMagnetCenter).toHaveBeenCalledTimes(callCountAfterCancel);
  });

  it("restores orbit controls when window blur interrupts drag", () => {
    const onUpdateMagnetCenter = vi.fn();

    const { container } = render(
      <FridgeMagnet3D
        enabled={true}
        modelBounds={modelBounds}
        magnets={[roundMagnet]}
        scaleX={1}
        scaleY={1}
        selectedMagnetId={null}
        onSelectMagnet={vi.fn()}
        onUpdateMagnetCenter={onUpdateMagnetCenter}
      />,
    );

    const proxy = container.querySelector('group[name="fridge-magnet-proxy-magnet-round"]');
    expect(proxy).not.toBeNull();

    fireEvent.pointerDown(proxy as Element, { clientX: 100, clientY: 100 });
    expect(mockControls.enabled).toBe(false);

    fireEvent.blur(window);

    expect(mockControls.enabled).toBe(true);
    const callCountAfterBlur = onUpdateMagnetCenter.mock.calls.length;

    fireEvent.pointerMove(window, { clientX: 160, clientY: 40 });

    expect(onUpdateMagnetCenter).toHaveBeenCalledTimes(callCountAfterBlur);
  });

  it("keeps dragging across parent re-renders triggered by live center updates until pointerup", () => {
    const updateSpy = vi.fn();

    function StatefulWrapper() {
      const [magnet, setMagnet] = useState(roundMagnet);

      const handleUpdateMagnetCenter = useCallback(
        (id: string, centerX: number, centerY: number) => {
          updateSpy(id, centerX, centerY);
          setMagnet((current) => ({
            ...current,
            center_x_mm: centerX,
            center_y_mm: centerY,
          }));
        },
        [],
      );

      return (
        <FridgeMagnet3D
          enabled={true}
          modelBounds={modelBounds}
          magnets={[magnet]}
          scaleX={1}
          scaleY={1}
          selectedMagnetId={null}
          onSelectMagnet={vi.fn()}
          onUpdateMagnetCenter={handleUpdateMagnetCenter}
        />
      );
    }

    const { container } = render(<StatefulWrapper />);

    const proxy = container.querySelector('group[name="fridge-magnet-proxy-magnet-round"]');
    expect(proxy).not.toBeNull();

    fireEvent.pointerDown(proxy as Element, { clientX: 100, clientY: 100 });
    expect(mockControls.enabled).toBe(false);

    fireEvent.pointerMove(window, { clientX: 150, clientY: 50 });
    expect(updateSpy).toHaveBeenLastCalledWith(roundMagnet.id, 4, 9);
    expect(mockControls.enabled).toBe(false);

    fireEvent.pointerMove(window, { clientX: 0, clientY: 200 });
    expect(updateSpy).toHaveBeenLastCalledWith(roundMagnet.id, -4, -9);
    expect(updateSpy).toHaveBeenCalledTimes(2);
    expect(mockControls.enabled).toBe(false);

    fireEvent.pointerUp(window);

    expect(mockControls.enabled).toBe(true);

    const callCountAfterPointerUp = updateSpy.mock.calls.length;
    fireEvent.pointerMove(window, { clientX: 200, clientY: 0 });
    expect(updateSpy).toHaveBeenCalledTimes(callCountAfterPointerUp);
  });

  it("resets the grab cursor on unmount so fridge mode exit cannot leave stale cursor state", () => {
    const { container, unmount } = render(
      <FridgeMagnet3D
        enabled={true}
        modelBounds={modelBounds}
        magnets={[roundMagnet]}
        scaleX={1}
        scaleY={1}
        selectedMagnetId={null}
        onSelectMagnet={vi.fn()}
        onUpdateMagnetCenter={vi.fn()}
      />,
    );

    const proxy = container.querySelector('group[name="fridge-magnet-proxy-magnet-round"]');
    expect(proxy).not.toBeNull();

    fireEvent.pointerOver(proxy as Element);
    expect(document.body.style.cursor).toBe("grab");

    unmount();

    expect(document.body.style.cursor).toBe("default");
  });

  it("scales proxy placement without scaling the proxy footprint itself", () => {
    const { container } = render(
      <FridgeMagnet3D
        enabled={true}
        modelBounds={modelBounds}
        magnets={[rectMagnet]}
        scaleX={2}
        scaleY={3}
        selectedMagnetId={null}
        onSelectMagnet={vi.fn()}
        onUpdateMagnetCenter={vi.fn()}
      />,
    );

    const proxy = container.querySelector('group[name="fridge-magnet-proxy-magnet-rect"]');
    expect(proxy).not.toBeNull();
    expect(proxy?.getAttribute("position")).toBe("8,-9,1.4");
    expect(proxy?.getAttribute("scale")).toBeNull();
    expect(container.querySelector("group[scale]")).toBeNull();
  });

  it("converts scaled world-space drag movement back into raw preview-space center updates", () => {
    const onUpdateMagnetCenter = vi.fn();

    const { container } = render(
      <FridgeMagnet3D
        enabled={true}
        modelBounds={modelBounds}
        magnets={[roundMagnet]}
        scaleX={2}
        scaleY={2}
        selectedMagnetId={null}
        onSelectMagnet={vi.fn()}
        onUpdateMagnetCenter={onUpdateMagnetCenter}
      />,
    );

    const proxy = container.querySelector('group[name="fridge-magnet-proxy-magnet-round"]');
    expect(proxy).not.toBeNull();
    expect(proxy?.getAttribute("position")).toBe("0,0,1.9");
    expect(container.querySelector("group[scale]")).toBeNull();

    fireEvent.pointerDown(proxy as Element, { clientX: 100, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 104, clientY: 96 });

    const [id, centerX, centerY] = onUpdateMagnetCenter.mock.lastCall ?? [];
    expect(id).toBe(roundMagnet.id);
    expect(centerX).toBeCloseTo(2, 6);
    expect(centerY).toBeCloseTo(2, 6);
  });

  it("uses the latest scale props when drag starts after a re-render", () => {
    const onUpdateMagnetCenter = vi.fn();
    const onSelectMagnet = vi.fn();

    const { container, rerender } = render(
      <FridgeMagnet3D
        enabled={true}
        modelBounds={modelBounds}
        magnets={[rectMagnet]}
        scaleX={1}
        scaleY={1}
        selectedMagnetId={null}
        onSelectMagnet={onSelectMagnet}
        onUpdateMagnetCenter={onUpdateMagnetCenter}
      />,
    );

    rerender(
      <FridgeMagnet3D
        enabled={true}
        modelBounds={modelBounds}
        magnets={[rectMagnet]}
        scaleX={2}
        scaleY={2}
        selectedMagnetId={null}
        onSelectMagnet={onSelectMagnet}
        onUpdateMagnetCenter={onUpdateMagnetCenter}
      />,
    );

    const proxy = container.querySelector('group[name="fridge-magnet-proxy-magnet-rect"]');
    expect(proxy).not.toBeNull();

    fireEvent.pointerDown(proxy as Element, { clientX: 100, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 104, clientY: 96 });

    const [id, centerX, centerY] = onUpdateMagnetCenter.mock.lastCall ?? [];
    expect(id).toBe(rectMagnet.id);
    expect(centerX).toBeCloseTo(2, 6);
    expect(centerY).toBeCloseTo(2, 6);
  });

  it("keeps the geometry cache key stable when only the magnet center changes", () => {
    const movedMagnet = { ...roundMagnet, center_x_mm: 4, center_y_mm: -6 };
    const resizedMagnet = { ...roundMagnet, diameter_mm: 16 };

    expect(getFridgeMagnetGeometryKey(movedMagnet)).toBe(
      getFridgeMagnetGeometryKey(roundMagnet),
    );
    expect(getFridgeMagnetGeometryKey(resizedMagnet)).not.toBe(
      getFridgeMagnetGeometryKey(roundMagnet),
    );
  });
});

describe("FridgeMagnet3D helpers", () => {
  it("derives proxy dimensions from round and rect items", () => {
    expect(getFridgeMagnetProxyDimensions(roundMagnet)).toEqual({
      width: 12,
      height: 12,
      thickness: 3,
      rotation: [Math.PI / 2, 0, 0],
      geometry: "cylinder",
    });

    expect(getFridgeMagnetProxyDimensions(rectMagnet)).toEqual({
      width: 15,
      height: 5,
      thickness: 2,
      rotation: [0, 0, 0],
      geometry: "box",
    });
  });

  it("builds a smoothed edge geometry instead of a dense wireframe triangulation", () => {
    const roundGeometry = createFridgeMagnetProxyGeometry(roundMagnet);

    expect(roundGeometry).toBeInstanceOf(THREE.CylinderGeometry);
    expect(roundGeometry).not.toBeNull();

    const edgeGeometry = createFridgeMagnetProxyEdgeGeometry(roundGeometry!);
    const wireframeGeometry = new THREE.WireframeGeometry(roundGeometry!);

    expect(edgeGeometry).toBeInstanceOf(THREE.EdgesGeometry);
    expect(
      edgeGeometry.getAttribute("position").count,
    ).toBeLessThan(wireframeGeometry.getAttribute("position").count);

    edgeGeometry.dispose();
    wireframeGeometry.dispose();
    roundGeometry?.dispose();
  });

  it("uses the event ray intersection when available to anchor drag in real viewer interactions", () => {
    const plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
    const target = new THREE.Vector3();
    const expected = new THREE.Vector3(12, -4, 0);
    const intersectPlane = vi.fn((_plane: THREE.Plane, nextTarget: THREE.Vector3) => {
      nextTarget.copy(expected);
      return nextTarget;
    });

    const result = getInitialDragPoint(
      { ray: { intersectPlane } } as unknown as Parameters<typeof getInitialDragPoint>[0],
      5,
      6,
      plane,
      target,
    );

    expect(intersectPlane).toHaveBeenCalledWith(plane, target);
    expect(result).toBe(target);
    expect(target.toArray()).toEqual(expected.toArray());
  });

  it("clamps dragged magnet centers so the full proxy footprint stays inside bounds", () => {
    const roundDimensions = getFridgeMagnetProxyDimensions(roundMagnet);
    const rectDimensions = getFridgeMagnetProxyDimensions(rectMagnet);

    expect(roundDimensions).not.toBeNull();
    expect(rectDimensions).not.toBeNull();

    expect(clampFridgeMagnetCenter(-25, 30, modelBounds, roundDimensions!)).toEqual({
      x: -4,
      y: 9,
    });
    expect(clampFridgeMagnetCenter(20, -20, modelBounds, rectDimensions!)).toEqual({
      x: 2.5,
      y: -12.5,
    });
    expect(clampFridgeMagnetCenter(0, 0, modelBounds, rectDimensions!)).toEqual({ x: 0, y: 0 });
  });

  it("places the proxy at the backing-side cavity center instead of above the model", () => {
    const roundPosition = getFridgeMagnetProxyPosition(roundMagnet);
    const rectPosition = getFridgeMagnetProxyPosition(rectMagnet);
    const expectedRoundZ = FRIDGE_MAGNET_SPACER_CLEARANCE_MM + roundMagnet.thickness_mm / 2;
    const expectedRectZ = FRIDGE_MAGNET_SPACER_CLEARANCE_MM + rectMagnet.thickness_mm / 2;

    expect(roundPosition).toEqual([0, 0, expectedRoundZ]);
    expect(rectPosition).toEqual([4, -3, expectedRectZ]);
    expect(roundPosition?.[2]).toBeLessThan(modelBounds.maxZ);
    expect(rectPosition?.[2]).toBeLessThan(modelBounds.maxZ);
  });
});
