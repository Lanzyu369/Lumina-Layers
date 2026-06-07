import * as THREE from "three";

export function materializePositionAttributeForGeometryBake(
  geometry: THREE.BufferGeometry,
): void {
  const posAttr = geometry.getAttribute("position");
  if (!posAttr || !posAttr.normalized || posAttr.array instanceof Float32Array) {
    return;
  }
  const positions = new Float32Array(posAttr.count * posAttr.itemSize);
  for (let i = 0; i < posAttr.count; i++) {
    positions[i * posAttr.itemSize] = posAttr.getX(i);
    if (posAttr.itemSize > 1) positions[i * posAttr.itemSize + 1] = posAttr.getY(i);
    if (posAttr.itemSize > 2) positions[i * posAttr.itemSize + 2] = posAttr.getZ(i);
    if (posAttr.itemSize > 3) positions[i * posAttr.itemSize + 3] = posAttr.getW(i);
  }
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, posAttr.itemSize));
}
