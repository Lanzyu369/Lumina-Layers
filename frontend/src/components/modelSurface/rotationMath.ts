import * as THREE from "three";
import type { ModelSurfaceModelRotation } from "../../stores/converter";

export interface ModelRotation {
  x: number;
  y: number;
  z: number;
}

export type RotationAxis = "x" | "y" | "z";

export interface ScreenPoint {
  x: number;
  y: number;
}

export interface ScreenRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface RotationPlaneFrame {
  center: THREE.Vector3;
  uAxis: THREE.Vector3;
  vAxis: THREE.Vector3;
  normal: THREE.Vector3;
}

const ROTATION_GIZMO_OFFSET_MM = 5;
export const ROTATION_GRABBER_OFFSET = 0.15;
export const ROTATION_COARSE_SNAP_REGIONS = 8;
export const ROTATION_SCALE_LONG_TOOTH = 0.1;
const SURFACE_FACE_UP_ALIGNMENT_EPSILON = 1e-4;
export const ROTATION_SCALE_STEPS = 72;
export const ROTATION_SCALE_LONG_EVERY = 2;
export const ROTATION_SNAP_DEGREES = 360 / ROTATION_SCALE_STEPS;
const ROTATION_HIT_TARGET_RADIUS_RATIO = 0.16;
const ROTATION_HIT_TARGET_MIN_RADIUS = 8;
const ROTATION_SCREEN_HIT_TARGET_PX = 28;
const ROTATION_SCREEN_CENTER_DEAD_ZONE_PX = 36;
const SELECTED_SURFACE_MIN_CAMERA_Z = 0.42;
export const ROTATION_RING_CONFIG: Record<RotationAxis, { rotation: [number, number, number] }> = {
  x: { rotation: [0, Math.PI / 2, 0] },
  y: { rotation: [Math.PI / 2, 0, 0] },
  z: { rotation: [0, 0, 0] },
};

export function toModelEuler(rotation: ModelRotation): THREE.Euler {
  return new THREE.Euler(rotation.x, rotation.y, rotation.z, "XYZ");
}

export function modelRotationToDegrees(
  rotation: ModelRotation,
): Record<RotationAxis, number> {
  return {
    x: THREE.MathUtils.radToDeg(rotation.x),
    y: THREE.MathUtils.radToDeg(rotation.y),
    z: THREE.MathUtils.radToDeg(rotation.z),
  };
}

export function modelRotationToSurfaceModelRotation(
  rotation: ModelRotation,
): ModelSurfaceModelRotation {
  return {
    x_deg: normalizeDegrees(THREE.MathUtils.radToDeg(rotation.x)),
    y_deg: normalizeDegrees(THREE.MathUtils.radToDeg(rotation.y)),
    z_deg: normalizeDegrees(THREE.MathUtils.radToDeg(rotation.z)),
  };
}

export function isSameSurfaceModelRotation(
  a: ModelSurfaceModelRotation,
  b: ModelSurfaceModelRotation,
): boolean {
  return (
    Math.abs(a.x_deg - b.x_deg) < 1e-6
    && Math.abs(a.y_deg - b.y_deg) < 1e-6
    && Math.abs(a.z_deg - b.z_deg) < 1e-6
  );
}

export function normalizeDegrees(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  const normalized = ((value % 360) + 360) % 360;
  return Math.abs(normalized) < 0.0001 || Math.abs(normalized - 360) < 0.0001
    ? 0
    : normalized;
}

export function getModelRotationWithSurfaceFacingUp(
  surfaceNormal: THREE.Vector3,
  rotation: ModelRotation,
): ModelRotation | null {
  if (surfaceNormal.lengthSq() <= 1e-12) {
    return null;
  }
  const currentQuaternion = new THREE.Quaternion().setFromEuler(toModelEuler(rotation));
  const worldNormal = surfaceNormal.clone().applyQuaternion(currentQuaternion).normalize();
  if (worldNormal.z >= 1 - SURFACE_FACE_UP_ALIGNMENT_EPSILON) {
    return null;
  }

  const correctionQuaternion = new THREE.Quaternion().setFromUnitVectors(
    worldNormal,
    new THREE.Vector3(0, 0, 1),
  );
  const nextEuler = new THREE.Euler().setFromQuaternion(
    correctionQuaternion.multiply(currentQuaternion),
    "XYZ",
  );
  const nextRotation = {
    x: nextEuler.x,
    y: nextEuler.y,
    z: nextEuler.z,
  };
  const nextDegrees = modelRotationToDegrees(nextRotation);
  if (
    Math.abs(normalizeDegrees(nextDegrees.x) - 180) < 0.001
    && Math.abs(normalizeDegrees(nextDegrees.y)) < 0.001
    && Math.abs(normalizeDegrees(nextDegrees.z) - 180) < 0.001
  ) {
    return {
      x: 0,
      y: Math.PI,
      z: 0,
    };
  }
  return nextRotation;
}

export function snapDegrees(value: number, step: number): number {
  if (!Number.isFinite(value) || step <= 0) {
    return normalizeDegrees(value);
  }
  return normalizeDegrees(Math.round(value / step) * step);
}

export function getRotationHitTargetTubeRadius(ringRadius: number): number {
  return Math.max(ringRadius * ROTATION_HIT_TARGET_RADIUS_RATIO, ROTATION_HIT_TARGET_MIN_RADIUS);
}

export function getRotationGizmoRadius(modelRadius: number): number {
  return Math.max(modelRadius + ROTATION_GIZMO_OFFSET_MM, 20);
}

function projectWorldPointToScreen(
  point: THREE.Vector3,
  camera: THREE.Camera,
  viewport: ScreenRect,
): ScreenPoint | null {
  const projected = point.clone().project(camera);
  if (
    !Number.isFinite(projected.x)
    || !Number.isFinite(projected.y)
    || !Number.isFinite(projected.z)
  ) {
    return null;
  }
  return {
    x: viewport.left + ((projected.x + 1) / 2) * viewport.width,
    y: viewport.top + ((1 - projected.y) / 2) * viewport.height,
  };
}

function distanceToScreenSegment(
  point: ScreenPoint,
  start: ScreenPoint,
  end: ScreenPoint,
): number {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const lengthSq = dx * dx + dy * dy;
  if (lengthSq <= 0.0001) {
    return Math.hypot(point.x - start.x, point.y - start.y);
  }
  const t = Math.max(
    0,
    Math.min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / lengthSq),
  );
  return Math.hypot(point.x - (start.x + t * dx), point.y - (start.y + t * dy));
}

export function findNearestRotationAxisScreenHit(
  pointer: ScreenPoint,
  center: THREE.Vector3,
  ringRadius: number,
  camera: THREE.Camera,
  viewport: ScreenRect,
  thresholdPx = ROTATION_SCREEN_HIT_TARGET_PX,
): RotationAxis | null {
  const screenCenter = projectWorldPointToScreen(center, camera, viewport);
  if (
    screenCenter
    && Math.hypot(pointer.x - screenCenter.x, pointer.y - screenCenter.y)
      <= ROTATION_SCREEN_CENTER_DEAD_ZONE_PX
  ) {
    return null;
  }
  const axes: RotationAxis[] = ["x", "y", "z"];
  let nearestAxis: RotationAxis | null = null;
  let nearestDistance = Number.POSITIVE_INFINITY;

  for (const axis of axes) {
    const frame = getRotationPlaneFrame(axis, center);
    let previous: ScreenPoint | null = null;
    for (let index = 0; index <= 96; index += 1) {
      const angle = (Math.PI * 2 * index) / 96;
      const worldPoint = center
        .clone()
        .addScaledVector(frame.uAxis, Math.cos(angle) * ringRadius)
        .addScaledVector(frame.vAxis, Math.sin(angle) * ringRadius);
      const screenPoint = projectWorldPointToScreen(worldPoint, camera, viewport);
      if (previous && screenPoint) {
        const distance = distanceToScreenSegment(pointer, previous, screenPoint);
        if (distance < nearestDistance) {
          nearestDistance = distance;
          nearestAxis = axis;
        }
      }
      previous = screenPoint;
    }
  }

  return nearestDistance <= thresholdPx ? nearestAxis : null;
}

export function getPointerRayFromScreenPoint(
  pointer: ScreenPoint,
  camera: THREE.Camera,
  viewport: ScreenRect,
): THREE.Ray {
  const ndc = new THREE.Vector2(
    ((pointer.x - viewport.left) / viewport.width) * 2 - 1,
    -(((pointer.y - viewport.top) / viewport.height) * 2 - 1),
  );
  const raycaster = new THREE.Raycaster();
  raycaster.setFromCamera(ndc, camera);
  return raycaster.ray.clone();
}

export function setRotationAxisDegrees(
  rotation: ModelRotation,
  axis: RotationAxis,
  degrees: number,
): ModelRotation {
  return {
    ...rotation,
    [axis]: THREE.MathUtils.degToRad(normalizeDegrees(degrees)),
  };
}

export function getModelRotationValue(
  rotation: ModelRotation,
  axis: RotationAxis,
): number {
  return rotation[axis];
}

export function rotateModelPointAroundPivot(
  point: THREE.Vector3,
  pivot: THREE.Vector3,
  euler: THREE.Euler,
): THREE.Vector3 {
  return pivot.clone().add(point.clone().sub(pivot).applyEuler(euler));
}

export function inverseRotateModelPointAroundPivot(
  point: THREE.Vector3,
  pivot: THREE.Vector3,
  euler: THREE.Euler,
): THREE.Vector3 {
  const inverseRotation = new THREE.Quaternion().setFromEuler(euler).invert();
  return pivot.clone().add(point.clone().sub(pivot).applyQuaternion(inverseRotation));
}

export function getRotationPlaneFrame(
  axis: RotationAxis,
  center: THREE.Vector3,
): RotationPlaneFrame {
  const euler = new THREE.Euler(...ROTATION_RING_CONFIG[axis].rotation, "XYZ");
  return {
    center: center.clone(),
    uAxis: new THREE.Vector3(1, 0, 0).applyEuler(euler).normalize(),
    vAxis: new THREE.Vector3(0, 1, 0).applyEuler(euler).normalize(),
    normal: new THREE.Vector3(0, 0, 1).applyEuler(euler).normalize(),
  };
}

function getRotationAngleFromFramePoint(
  point: THREE.Vector3,
  center: THREE.Vector3,
  uAxis: THREE.Vector3,
  vAxis: THREE.Vector3,
): { degrees: number; distance: number } | null {
  const relative = point.clone().sub(center);
  const x = relative.dot(uAxis);
  const y = relative.dot(vAxis);
  const distance = Math.hypot(x, y);
  if (distance <= 0.0001) {
    return null;
  }
  const radians = Math.atan2(y, x);
  const degrees = normalizeDegrees(
    THREE.MathUtils.radToDeg(radians < 0 ? radians + Math.PI * 2 : radians),
  );
  return { degrees, distance };
}

function snapRotationPlaneDegrees(
  degrees: number,
  distance: number,
  ringRadius: number,
): number {
  const coarseInner = ringRadius / 3;
  const coarseOuter = (2 * ringRadius) / 3;
  if (coarseInner <= distance && distance <= coarseOuter) {
    return snapDegrees(degrees, 360 / ROTATION_COARSE_SNAP_REGIONS);
  }
  const fineInner = ringRadius;
  const fineOuter = ringRadius * (1 + ROTATION_SCALE_LONG_TOOTH);
  if (fineInner <= distance && distance <= fineOuter) {
    return snapDegrees(degrees, ROTATION_SNAP_DEGREES);
  }
  return normalizeDegrees(degrees);
}

function signedAngleDeltaDegrees(startDegrees: number, currentDegrees: number): number {
  const delta = normalizeDegrees(currentDegrees - startDegrees);
  if (delta > 180) {
    return delta - 360;
  }
  if (delta < -180) {
    return delta + 360;
  }
  return delta;
}

export function computeModelRotationDragDegrees(
  startRotationDegrees: number,
  startPointerDegrees: number,
  currentPointerDegrees: number,
  distance: number,
  ringRadius: number,
): number {
  return snapRotationPlaneDegrees(
    startRotationDegrees + signedAngleDeltaDegrees(startPointerDegrees, currentPointerDegrees),
    distance,
    ringRadius,
  );
}

export function getRotationPointerResultFromPointOrRay(
  point: THREE.Vector3 | null | undefined,
  ray: THREE.Ray | null | undefined,
  center: THREE.Vector3,
  uAxis: THREE.Vector3,
  vAxis: THREE.Vector3,
  normal: THREE.Vector3,
): { degrees: number; distance: number } | null {
  if (point) {
    return getRotationAngleFromFramePoint(point, center, uAxis, vAxis);
  }
  if (!ray) {
    return null;
  }
  const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(normal, center);
  const intersection = new THREE.Vector3();
  if (!ray.intersectPlane(plane, intersection)) {
    return null;
  }
  return getRotationAngleFromFramePoint(intersection, center, uAxis, vAxis);
}

export function getSurfaceFocusRadius(
  widthMm: number,
  heightMm: number,
  modelRadius: number,
): number {
  const surfaceRadius = Math.max(widthMm, heightMm, 1) / 2;
  const safeModelRadius = Math.max(modelRadius, 1);
  const minimumFocusRadius = Math.min(
    safeModelRadius,
    Math.max(20, safeModelRadius * 0.22),
  );
  return Math.max(surfaceRadius, minimumFocusRadius);
}

export function ensureCameraDepthClipping(
  camera: THREE.Camera,
  focusDistance: number,
  contentRadius: number,
): void {
  const clippingCamera = camera as THREE.PerspectiveCamera | THREE.OrthographicCamera;
  if (typeof clippingCamera.far !== "number") {
    return;
  }
  const safeDistance = Math.max(focusDistance, 1);
  const safeRadius = Math.max(contentRadius, 1);
  const requiredFar = Math.max(2000, safeDistance + safeRadius * 2 + 100);
  if (Number.isFinite(requiredFar) && clippingCamera.far < requiredFar) {
    clippingCamera.far = requiredFar;
  }
  if (typeof clippingCamera.near === "number") {
    const maxNonClippingNear = Math.max(0.1, safeDistance - safeRadius * 1.25);
    const desiredNear = Math.max(safeDistance * 0.01, 0.1);
    const nextNear = Math.min(desiredNear, maxNonClippingNear);
    if (Number.isFinite(nextNear) && Math.abs(nextNear - clippingCamera.near) > 1e-6) {
      clippingCamera.near = nextNear;
    }
  }
}

export function getReadableSurfaceCameraDirection(
  surfaceNormal: THREE.Vector3,
  reverseView: boolean,
): THREE.Vector3 {
  const direction = surfaceNormal.clone().multiplyScalar(reverseView ? -1 : 1);
  if (direction.lengthSq() <= 1e-12) {
    return new THREE.Vector3(0, 0, 1);
  }
  direction.normalize();
  if (direction.z < 0) {
    direction.multiplyScalar(-1);
  }
  if (direction.z >= SELECTED_SURFACE_MIN_CAMERA_Z) {
    return direction;
  }

  const horizontal = new THREE.Vector3(direction.x, direction.y, 0);
  if (horizontal.lengthSq() <= 1e-12) {
    return new THREE.Vector3(0, 0, 1);
  }
  horizontal.normalize().multiplyScalar(
    Math.sqrt(1 - SELECTED_SURFACE_MIN_CAMERA_Z * SELECTED_SURFACE_MIN_CAMERA_Z),
  );
  return new THREE.Vector3(horizontal.x, horizontal.y, SELECTED_SURFACE_MIN_CAMERA_Z);
}

export function getReadableSurfaceCameraUp(
  _surfaceNormal: THREE.Vector3,
  surfaceVAxis: THREE.Vector3,
  cameraDirection: THREE.Vector3,
): THREE.Vector3 {
  const direction = cameraDirection.lengthSq() > 1e-12
    ? cameraDirection.clone().normalize()
    : new THREE.Vector3(0, 0, 1);
  let up = surfaceVAxis.clone();
  up.addScaledVector(direction, -up.dot(direction));
  if (up.lengthSq() <= 1e-12) {
    up = Math.abs(direction.z) > 0.9
      ? new THREE.Vector3(0, 1, 0)
      : new THREE.Vector3(0, 0, 1);
    up.addScaledVector(direction, -up.dot(direction));
  }
  return up.normalize();
}
