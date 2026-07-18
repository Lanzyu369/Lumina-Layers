export interface CameraClippingPlanes {
  near: number;
  far: number;
}

const MIN_NEAR_PLANE_MM = 0.1;
const MAX_NEAR_PLANE_MM = 20;
const MIN_FAR_PLANE_MM = 2_500;
const NEAR_DISTANCE_RATIO = 0.01;
const FAR_DISTANCE_RATIO = 10;

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

  return {
    near: Math.min(
      MAX_NEAR_PLANE_MM,
      Math.max(MIN_NEAR_PLANE_MM, distanceToTarget * NEAR_DISTANCE_RATIO),
    ),
    far: Math.max(MIN_FAR_PLANE_MM, distanceToTarget * FAR_DISTANCE_RATIO),
  };
}
