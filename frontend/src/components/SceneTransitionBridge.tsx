import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";
import { addAfterEffect, useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import {
  captureSceneTransitionSnapshot,
  getSceneTransitionSnapshot,
  restoreSceneTransitionCamera,
  type SceneTransitionSnapshot,
  type SnapshotOrbitControls,
} from "./sceneTransitionSnapshot";

export function SceneAssetReady({ onReadyChange }: { onReadyChange: (ready: boolean) => void }) {
  useLayoutEffect(() => {
    onReadyChange(true);
    return () => onReadyChange(false);
  }, [onReadyChange]);
  return null;
}

interface SceneTransitionBridgeProps {
  snapshotKey: string;
  getCurrentKey: () => string;
  snapshot: SceneTransitionSnapshot | null;
  ready: boolean;
  captureRef: RefObject<(() => void) | null>;
  onFrameReady: () => void;
}

/** Observe this root's completed frames, rather than Canvas creation or a timer. */
export function SceneTransitionBridge({
  snapshotKey, getCurrentKey, snapshot, ready, captureRef, onFrameReady,
}: SceneTransitionBridgeProps) {
  const gl = useThree((state) => state.gl);
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls) as unknown as SnapshotOrbitControls | null;
  const invalidate = useThree((state) => state.invalidate);
  const completedKey = useRef<string | null>(null);
  const rendered = useRef(false);
  const restored = useRef(false);
  const announced = useRef(false);

  useFrame(() => {
    rendered.current = ready && Boolean(controls);
    if (!ready || !controls || restored.current) return;
    restored.current = true;
    if (snapshot?.key === snapshotKey) {
      restoreSceneTransitionCamera(snapshot.camera, camera as THREE.PerspectiveCamera, controls);
    }
  });

  useEffect(() => {
    if (ready) invalidate();
  }, [ready, snapshotKey, invalidate]);

  useEffect(() => addAfterEffect(() => {
    if (!rendered.current) return;
    rendered.current = false;
    completedKey.current = snapshotKey;
    if (!announced.current) {
      announced.current = true;
      onFrameReady();
    }
  }), [snapshotKey, onFrameReady]);

  useLayoutEffect(() => {
    const capture = () => {
      if (!ready || !controls || completedKey.current !== getCurrentKey()) {
        // A quick round trip may leave before the replacement frame is ready.
        // Keep the original pixels if they still describe the current content.
        getSceneTransitionSnapshot(getCurrentKey());
        return;
      }
      captureSceneTransitionSnapshot(snapshotKey, gl.domElement, camera as THREE.PerspectiveCamera, controls);
    };
    captureRef.current = capture;
    return () => {
      if (captureRef.current === capture) captureRef.current = null;
    };
  }, [camera, controls, gl, captureRef, getCurrentKey, ready, snapshotKey]);

  return null;
}
