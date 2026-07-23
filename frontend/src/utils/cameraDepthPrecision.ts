export interface CameraClippingPlanes {
  near: number;
  far: number;
}

const MIN_NEAR_PLANE_MM = 0.1;
const MIN_FAR_PLANE_MM = 2_500;
const NEAR_DISTANCE_RATIO = 0.01;
const MAX_NEAR_DISTANCE_RATIO = 0.1;
const FAR_DISTANCE_RATIO = 10;
const DEPTH_BUFFER_LEVELS = 2 ** 24;
const MIN_MATERIAL_LAYER_MM = 0.08;
const DEPTH_RESOLUTION_SAFETY_FACTOR = 4;

/**
 * Resolve perspective-camera clipping planes for the current orbit distance.
 * 根据当前轨道相机距离计算透视裁剪面。
 */
export function resolveCameraClippingPlanes(
  distanceToTarget: number,
): CameraClippingPlanes {
  if (!Number.isFinite(distanceToTarget) || distanceToTarget <= 0) {
    return {
      near: MIN_NEAR_PLANE_MM,
      far: MIN_FAR_PLANE_MM,
    };
  }

  const maximumDepthResolutionMm =
    MIN_MATERIAL_LAYER_MM / DEPTH_RESOLUTION_SAFETY_FACTOR;
  const precisionBoundNearPlane =
    (distanceToTarget * distanceToTarget) /
    (DEPTH_BUFFER_LEVELS * maximumDepthResolutionMm);
  const maximumNearPlane = distanceToTarget * MAX_NEAR_DISTANCE_RATIO;

  return {
    near: Math.min(
      maximumNearPlane,
      Math.max(
        Math.min(MIN_NEAR_PLANE_MM, maximumNearPlane),
        distanceToTarget * NEAR_DISTANCE_RATIO,
        precisionBoundNearPlane,
      ),
    ),
    far: Math.max(MIN_FAR_PLANE_MM, distanceToTarget * FAR_DISTANCE_RATIO),
  };
}
