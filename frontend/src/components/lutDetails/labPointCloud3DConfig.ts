import * as THREE from "three";

export const HULL_FILL_COLOR = "#94a3b8";
export const HULL_EDGE_COLOR = "#cbd5e1";
export const REFERENCE_SLICE_OPACITY = 0.8;
export const REFERENCE_SLICE_TEXTURE_RESOLUTION = 512;

export const POINT_RENDER_ORDER = 1;
export const HULL_RENDER_ORDER = 0;
export const HULL_EDGE_RENDER_ORDER = 2;
export const REFERENCE_SLICE_RENDER_ORDER = -1;

export function getReferenceSliceMaterialProps() {
  return {
    transparent: true,
    opacity: REFERENCE_SLICE_OPACITY,
    side: THREE.DoubleSide,
    alphaTest: 0.001,
    depthWrite: true,
    toneMapped: false,
  };
}

export function getHullFillMaterialProps() {
  return {
    color: HULL_FILL_COLOR,
    transparent: true,
    opacity: 0.18,
    side: THREE.DoubleSide,
    depthWrite: false,
  };
}

export function getHullEdgeMaterialProps() {
  return {
    color: HULL_EDGE_COLOR,
    transparent: true,
    opacity: 0.72,
    depthWrite: false,
  };
}
