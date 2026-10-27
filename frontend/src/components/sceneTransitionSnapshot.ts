import * as THREE from "three";
import type { ConverterState } from "../stores/converter/types";

const MAX_SNAPSHOT_EDGE = 1600;
const stateIds = new WeakMap<object, number>();
let nextStateId = 0;
const SCENE_FIELDS = [
  "sessionId", "modelUrl", "previewGlbUrl", "batchPreviewItems", "bed_label",
  "modelBounds", "colorContours", "colorRemapMap", "color_height_map",
  "target_width_mm", "target_height_mm", "preview_width_mm", "preview_height_mm",
  "previewPixelWidth", "previewPixelHeight", "spacer_thick", "structure_mode",
  "enable_relief", "autoHeightMode", "heightmapThumbnailUrl", "heightmapUploadSessionId",
  "heightmap_max_height", "previewBaseImageUrl", "imagePreviewUrl", "aspectRatio",
  "enable_outline", "outline_width", "enable_cloisonne", "wire_width_mm", "wire_height_mm",
  "enable_coating", "coating_height_mm", "color_layers", "layer_height_mm",
  "puzzleEnabled", "puzzleOverlayUrl", "largeFormatEnabled", "largeFormatTileOverlayVisible",
  "tileWidthMm", "tileHeightMm", "add_loop", "loop_width", "loop_length", "loop_hole",
  "loop_angle", "loop_offset_x", "loop_offset_y", "loop_position_preset",
  "enable_fridge_magnet", "fridge_magnets", "selectedFridgeMagnetId",
  "modelSurfaceEnabled", "modelSurfaceFile", "modelSurfacePreviewUrl", "modelSurfaceSelectionId",
  "modelSurfaceModelFileId", "modelSurfaceFootprint", "modelSurfaceCandidates",
  "modelSurfacePlacement", "modelSurfaceModelRotation", "previewRequestRevision",
] as const satisfies readonly (keyof ConverterState)[];

export interface SceneCameraSnapshot {
  position: [number, number, number];
  quaternion: [number, number, number, number];
  up: [number, number, number];
  target: [number, number, number];
  fov: number;
  zoom: number;
  minDistance: number;
  maxDistance: number;
}

export interface SceneTransitionSnapshot {
  key: string;
  image: HTMLCanvasElement;
  width: number;
  height: number;
  camera: SceneCameraSnapshot;
}

export interface SnapshotOrbitControls {
  target: THREE.Vector3;
  minDistance: number;
  maxDistance: number;
  update: () => void;
}

let cachedSnapshot: SceneTransitionSnapshot | null = null;

/** Track rendered content, not catalog loading or unrelated form state. */
export function getSceneTransitionKey(state: Partial<ConverterState>, appearance: readonly unknown[]): string {
  const bed = state.bedSizes?.find((item) => item.label === state.bed_label);
  const values = [
    ...SCENE_FIELDS.map((field) => state[field]),
    bed?.width_mm, bed?.height_mm, bed?.printer_id,
    ...appearance,
  ];
  // Reference IDs avoid serializing large contours and do not retain assets.
  return JSON.stringify(values.map((value) => {
    if (value === null || typeof value !== "object") return value;
    let id = stateIds.get(value);
    if (id === undefined) {
      id = ++nextStateId;
      stateIds.set(value, id);
    }
    return ["ref", id];
  }));
}

export function getSceneTransitionSnapshot(key: string): SceneTransitionSnapshot | null {
  if (cachedSnapshot?.key !== key) cachedSnapshot = null;
  return cachedSnapshot;
}

export function clearSceneTransitionSnapshot(): void {
  cachedSnapshot = null;
}

/** Copy pixels once on departure; retain neither a renderer nor a Three scene. */
export function captureSceneTransitionSnapshot(
  key: string,
  canvas: HTMLCanvasElement,
  camera: THREE.PerspectiveCamera,
  controls: SnapshotOrbitControls,
): void {
  cachedSnapshot = null;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (width <= 0 || height <= 0 || canvas.width <= 0 || canvas.height <= 0) return;
  try {
    const image = document.createElement("canvas");
    const scale = Math.min(1, MAX_SNAPSHOT_EDGE / Math.max(canvas.width, canvas.height));
    image.width = Math.max(1, Math.round(canvas.width * scale));
    image.height = Math.max(1, Math.round(canvas.height * scale));
    const context = image.getContext("2d");
    if (!context) return;
    context.drawImage(canvas, 0, 0, image.width, image.height);
    cachedSnapshot = {
      key, image, width, height,
      camera: {
        position: camera.position.toArray(),
        quaternion: camera.quaternion.toArray(),
        up: camera.up.toArray(),
        target: controls.target.toArray(),
        fov: camera.fov,
        zoom: camera.zoom,
        minDistance: controls.minDistance,
        maxDistance: controls.maxDistance,
      },
    };
  } catch {
    // A lost/tainted context must never prevent navigation or resource release.
  }
}

export function restoreSceneTransitionCamera(
  snapshot: SceneCameraSnapshot,
  camera: THREE.PerspectiveCamera,
  controls: SnapshotOrbitControls,
): void {
  camera.position.fromArray(snapshot.position);
  camera.quaternion.fromArray(snapshot.quaternion);
  camera.up.fromArray(snapshot.up);
  camera.fov = snapshot.fov;
  camera.zoom = snapshot.zoom;
  camera.updateProjectionMatrix();
  controls.target.fromArray(snapshot.target);
  controls.minDistance = snapshot.minDistance;
  controls.maxDistance = snapshot.maxDistance;
  controls.update();
}
