import * as THREE from "three";

function cloneMaterialWithOwnedTextures(
  material: THREE.Material,
): THREE.Material {
  const clone = material.clone();
  const cloneRecord = clone as unknown as Record<string, unknown>;

  for (const [key, value] of Object.entries(cloneRecord)) {
    if (value instanceof THREE.Texture) {
      cloneRecord[key] = value.clone();
    }
  }

  return clone;
}

function cloneOwnedMeshResources(
  source: THREE.Object3D,
  target: THREE.Object3D,
): void {
  if (source instanceof THREE.Mesh && target instanceof THREE.Mesh) {
    target.geometry = source.geometry.clone();
    target.material = Array.isArray(source.material)
      ? source.material.map(cloneMaterialWithOwnedTextures)
      : cloneMaterialWithOwnedTextures(source.material);
  }

  const childCount = Math.min(source.children.length, target.children.length);
  for (let i = 0; i < childCount; i += 1) {
    cloneOwnedMeshResources(source.children[i], target.children[i]);
  }
}

export function cloneObjectTreeWithOwnedResources<T extends THREE.Object3D>(
  root: T,
): T {
  const clone = root.clone(true) as T;
  cloneOwnedMeshResources(root, clone);
  return clone;
}

function disposeMaterialInstance(material: THREE.Material): void {
  for (const value of Object.values(material)) {
    if (value instanceof THREE.Texture) {
      value.dispose();
    }
  }
  material.dispose();
}

export function disposeMaterial(
  material: THREE.Material | THREE.Material[] | null | undefined,
): void {
  if (!material) {
    return;
  }

  if (Array.isArray(material)) {
    for (const entry of material) {
      disposeMaterialInstance(entry);
    }
    return;
  }

  disposeMaterialInstance(material);
}

export function disposeMeshResources(mesh: THREE.Mesh): void {
  mesh.geometry.dispose();
  disposeMaterial(mesh.material);
}

export function disposeObjectTree(
  root: THREE.Object3D | null | undefined,
): void {
  if (!root) {
    return;
  }

  root.traverse((child) => {
    if (child instanceof THREE.Mesh) {
      disposeMeshResources(child);
    }
  });
}
