/**
 * Matte material conversion helper for 3D model viewers.
 *
 * Converts MeshStandardMaterial to MeshLambertMaterial while preserving
 * visual properties that would otherwise be lost (vertexColors, map, etc.).
 *
 * LUM-20260519-002 Issue A: previous code only copied `color`, causing
 * vertex-colored meshes (like batch merge preview GLBs) to appear pure white.
 */

import * as THREE from "three";

/**
 * Create a MeshLambertMaterial from a MeshStandardMaterial, preserving
 * all visual properties needed for correct rendering.
 *
 * Properties preserved: color, vertexColors, map, alphaMap, transparent,
 * opacity, name. Preview materials are forced to DoubleSide and
 * toneMapped=false so flat color chips stay saturated and remain visible
 * from the back side.
 */
export function createMatteMaterialFromStandard(
  mat: THREE.MeshStandardMaterial,
): THREE.MeshLambertMaterial {
  return new THREE.MeshLambertMaterial({
    // When vertexColors is true, the material color multiplies with vertex
    // colors. Use white (1,1,1) to avoid washing out / tinting the vertex
    // colors. When vertexColors is false, preserve the original color.
    color: mat.vertexColors ? new THREE.Color(1, 1, 1) : mat.color,
    vertexColors: mat.vertexColors,
    map: mat.map,
    alphaMap: mat.alphaMap,
    transparent: mat.transparent,
    opacity: mat.opacity,
    side: THREE.DoubleSide,
    toneMapped: false,
    name: mat.name,
  });
}
