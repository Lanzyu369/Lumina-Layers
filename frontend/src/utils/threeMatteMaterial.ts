/**
 * Unlit material conversion helper for 3D model viewers.
 *
 * Converts MeshStandardMaterial to MeshBasicMaterial while preserving
 * visual properties that would otherwise be lost (vertexColors, map, etc.).
 *
 * LUM-20260519-002 Issue A: previous code only copied `color`, causing
 * vertex-colored meshes (like batch merge preview GLBs) to appear pure white.
 */

import * as THREE from "three";

/**
 * Create a MeshBasicMaterial from a MeshStandardMaterial, preserving
 * all visual properties needed for correct rendering.
 *
 * Properties preserved: color, vertexColors, map, alphaMap, transparent,
 * opacity, name. Preview color chips are unlit (MeshBasicMaterial) so their
 * on-screen colour equals the source hex exactly — matching the 2D preview —
 * and brightness is decoupled from scene lighting. They are forced to
 * DoubleSide to stay visible from the back, and toneMapped=false so the exact
 * hex is not altered by the scene's tone mapping.
 */
export function createMatteMaterialFromStandard(
  mat: THREE.MeshStandardMaterial,
): THREE.MeshBasicMaterial {
  return new THREE.MeshBasicMaterial({
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
