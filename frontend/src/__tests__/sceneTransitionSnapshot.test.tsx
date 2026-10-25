import { createRef, StrictMode, Suspense } from "react";
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import {
  captureSceneTransitionSnapshot,
  clearSceneTransitionSnapshot,
  getSceneTransitionKey,
  getSceneTransitionSnapshot,
  restoreSceneTransitionCamera,
} from "../components/sceneTransitionSnapshot";
import { SceneAssetReady, SceneTransitionBridge } from "../components/SceneTransitionBridge";

const fiber = vi.hoisted(() => ({
  state: {} as Record<string, unknown>,
  frame: null as (() => void) | null,
  after: new Set<() => void>(),
}));
vi.mock("@react-three/fiber", () => ({
  useThree: (select: (state: Record<string, unknown>) => unknown) => select(fiber.state),
  useFrame: (callback: () => void) => { fiber.frame = callback; },
  addAfterEffect: (callback: () => void) => {
    fiber.after.add(callback);
    return () => { fiber.after.delete(callback); };
  },
}));

function createView() {
  const canvas = document.createElement("canvas");
  canvas.width = 3200;
  canvas.height = 1800;
  Object.defineProperties(canvas, {
    clientWidth: { value: 1280 },
    clientHeight: { value: 720 },
  });
  const camera = new THREE.PerspectiveCamera(42);
  camera.position.set(12, -140, 350);
  camera.up.set(0, 0, 1);
  camera.lookAt(3, 4, 5);
  const controls = {
    target: new THREE.Vector3(3, 4, 5),
    minDistance: 3,
    maxDistance: 1800,
    update: vi.fn(),
  };
  fiber.state = { gl: { domElement: canvas }, camera, controls, invalidate: vi.fn() };
  return { canvas, camera, controls };
}

beforeEach(() => {
  clearSceneTransitionSnapshot();
  fiber.after.clear();
  fiber.frame = null;
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
    (() => ({ drawImage: vi.fn() })) as unknown as HTMLCanvasElement["getContext"],
  );
});
afterEach(() => {
  vi.restoreAllMocks();
  clearSceneTransitionSnapshot();
});

describe("scene departure pixels", () => {
  it("keeps one bounded image and restores the exact camera without retaining a renderer", () => {
    const { canvas, camera, controls } = createView();
    captureSceneTransitionSnapshot("artwork", canvas, camera, controls);
    const saved = getSceneTransitionSnapshot("artwork")!;
    expect([saved.image.width, saved.image.height]).toEqual([1600, 900]);
    expect([saved.width, saved.height]).toEqual([1280, 720]);
    expect(Object.keys(saved).sort()).toEqual(["camera", "height", "image", "key", "width"]);

    const nextCamera = new THREE.PerspectiveCamera();
    const nextControls = { ...controls, target: new THREE.Vector3(), update: vi.fn() };
    restoreSceneTransitionCamera(saved.camera, nextCamera, nextControls);
    expect(nextCamera.position.equals(camera.position)).toBe(true);
    expect(nextCamera.quaternion.equals(camera.quaternion)).toBe(true);
    expect(nextCamera.up.equals(camera.up)).toBe(true);
    expect(nextCamera.fov).toBe(42);
    expect(nextControls.target.toArray()).toEqual([3, 4, 5]);
    expect(nextControls.update).toHaveBeenCalledOnce();

    captureSceneTransitionSnapshot("new-artwork", canvas, camera, controls);
    expect(getSceneTransitionSnapshot("new-artwork")).not.toBe(saved);
    expect(getSceneTransitionSnapshot("artwork")).toBeNull();
  });

  it("rejects changed content, theme, printer, plate and slicer", () => {
    const { canvas, camera, controls } = createView();
    const state = { previewGlbUrl: "/artwork.glb" };
    const appearance = ["light", "a1", "pei", "BambuStudio"];
    const key = getSceneTransitionKey(state, appearance);
    expect(getSceneTransitionKey(state, appearance)).toBe(key);
    const changes = [
      getSceneTransitionKey({ previewGlbUrl: "/different.glb" }, appearance),
      ...appearance.map((_, index) => getSceneTransitionKey(state, appearance.map((value, i) => i === index ? "changed" : value))),
    ];
    for (const changed of changes) {
      captureSceneTransitionSnapshot(key, canvas, camera, controls);
      expect(getSceneTransitionSnapshot(changed)).toBeNull();
    }
  });

  it("keeps the image valid while converter catalogs reload on page entry", () => {
    const state = {
      previewGlbUrl: "/artwork.glb", bed_label: "A1", bedSizesLoading: false,
      bedSizes: [{ label: "A1", width_mm: 256, height_mm: 256, is_default: true }],
    };
    expect(getSceneTransitionKey({ ...state, bedSizesLoading: true, lut_name: "catalog refresh" }, ["light"]))
      .toBe(getSceneTransitionKey(state, ["light"]));
    expect(getSceneTransitionKey({ ...state, bedSizes: state.bedSizes.map((item) => ({ ...item })) }, ["light"]))
      .toBe(getSceneTransitionKey(state, ["light"]));
    expect(getSceneTransitionKey({ ...state, bedSizes: [{ ...state.bedSizes[0], width_mm: 350 }] }, ["light"]))
      .not.toBe(getSceneTransitionKey(state, ["light"]));
  });

  it("lets navigation proceed when pixel readback fails", () => {
    const { canvas, camera, controls } = createView();
    vi.mocked(HTMLCanvasElement.prototype.getContext).mockImplementation(() => {
      throw new Error("lost context");
    });
    expect(() => captureSceneTransitionSnapshot("lost", canvas, camera, controls)).not.toThrow();
    expect(getSceneTransitionSnapshot("lost")).toBeNull();
  });
});

describe("scene frame handoff", () => {
  it("waits for resources and this canvas's actual completed frame, then removes its observer", () => {
    createView();
    const captureRef = createRef<(() => void) | null>();
    const onFrameReady = vi.fn();
    const getCurrentKey = () => "artwork";
    const props = { snapshotKey: "artwork", getCurrentKey, snapshot: null, captureRef, onFrameReady };
    const { rerender, unmount } = render(<SceneTransitionBridge {...props} ready={false} />);
    act(() => {
      fiber.frame?.();
      fiber.after.forEach((callback) => callback());
    });
    expect(onFrameReady).not.toHaveBeenCalled();
    rerender(<SceneTransitionBridge {...props} ready />);
    act(() => { fiber.after.forEach((callback) => callback()); });
    expect(onFrameReady).not.toHaveBeenCalled();
    act(() => { fiber.frame?.(); });
    expect(onFrameReady).not.toHaveBeenCalled();
    act(() => { fiber.after.forEach((callback) => callback()); });
    expect(onFrameReady).toHaveBeenCalledOnce();
    captureRef.current?.();
    expect(getSceneTransitionSnapshot("artwork")).not.toBeNull();
    unmount();
    expect(fiber.after.size).toBe(0);
    expect(captureRef.current).toBeNull();
  });

  it("keeps the original image across a fast return that leaves before initialization finishes", () => {
    const { canvas, camera, controls } = createView();
    captureSceneTransitionSnapshot("artwork", canvas, camera, controls);
    const snapshot = getSceneTransitionSnapshot("artwork");
    const captureRef = createRef<(() => void) | null>();
    const { unmount } = render(<SceneTransitionBridge
      snapshotKey="artwork" getCurrentKey={() => "artwork"} snapshot={snapshot}
      ready={false} captureRef={captureRef} onFrameReady={vi.fn()}
    />);
    captureRef.current?.();
    expect(getSceneTransitionSnapshot("artwork")).toBe(snapshot);
    unmount();
  });

  it("restores the previous angle before the replacement is rendered, and ignores frames from other canvases", () => {
    const { canvas, camera, controls } = createView();
    captureSceneTransitionSnapshot("artwork", canvas, camera, controls);
    const snapshot = getSceneTransitionSnapshot("artwork")!;
    camera.position.set(0, 0, 1);
    const onFrameReady = vi.fn();
    const { unmount } = render(<StrictMode><SceneTransitionBridge
      snapshotKey="artwork" getCurrentKey={() => "artwork"} snapshot={snapshot}
      ready captureRef={createRef()} onFrameReady={onFrameReady}
    /></StrictMode>);
    act(() => { fiber.after.forEach((callback) => callback()); });
    expect(onFrameReady).not.toHaveBeenCalled();
    act(() => { fiber.frame?.(); });
    expect(camera.position.toArray()).toEqual(snapshot.camera.position);
    act(() => { fiber.after.forEach((callback) => callback()); });
    expect(onFrameReady).toHaveBeenCalledOnce();
    unmount();
    expect(fiber.after.size).toBe(0);
  });

  it("does not save a frame if content changed without being drawn", () => {
    createView();
    const captureRef = createRef<(() => void) | null>();
    let currentKey = "artwork";
    const { unmount } = render(<SceneTransitionBridge
      snapshotKey="artwork" getCurrentKey={() => currentKey} snapshot={null}
      ready captureRef={captureRef} onFrameReady={vi.fn()}
    />);
    act(() => {
      fiber.frame?.();
      fiber.after.forEach((callback) => callback());
    });
    currentKey = "different-artwork";
    captureRef.current?.();
    expect(getSceneTransitionSnapshot("different-artwork")).toBeNull();
    unmount();
  });

  it("reports suspended resource lifetime without keeping it mounted", () => {
    const onReadyChange = vi.fn();
    const { unmount } = render(<StrictMode><SceneAssetReady onReadyChange={onReadyChange} /></StrictMode>);
    expect(onReadyChange).toHaveBeenLastCalledWith(true);
    unmount();
    expect(onReadyChange).toHaveBeenLastCalledWith(false);
  });

  it("withdraws readiness when a visible model suspends for a replacement texture", async () => {
    const onReadyChange = vi.fn();
    let pending = false;
    let resolveLoad!: () => void;
    const loading = new Promise<void>((resolve) => { resolveLoad = resolve; });
    function Asset() {
      if (pending) throw loading;
      return null;
    }
    const content = () => <Suspense fallback={<span>loading</span>}>
      <Asset />
      <SceneAssetReady onReadyChange={onReadyChange} />
    </Suspense>;
    const { rerender, unmount } = render(content());
    expect(onReadyChange).toHaveBeenLastCalledWith(true);
    pending = true;
    rerender(content());
    expect(onReadyChange).toHaveBeenLastCalledWith(false);
    await act(async () => {
      pending = false;
      resolveLoad();
      await loading;
    });
    expect(onReadyChange).toHaveBeenLastCalledWith(true);
    unmount();
  });
});
