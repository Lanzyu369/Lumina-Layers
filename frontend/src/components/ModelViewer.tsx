import { useMemo, useEffect } from "react";
import { useThree } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import * as THREE from "three";
import {
  cloneObjectTreeWithOwnedResources,
  disposeMaterial,
  disposeObjectTree,
} from "../utils/threeDisposal";
import {
  debugThreeLog,
  getLatestResourceTiming,
  summarizeObjectTree,
} from "../utils/threeDebug";
import { useGltfCacheLifecycle } from "./useGltfCacheLifecycle";

type LuminaWindow = Window & { __luminaGenerateStart?: number };

function _clog(label: string) {
  const start = (window as LuminaWindow).__luminaGenerateStart;
  const elapsed_ms = start != null ? performance.now() - start : null;
  fetch('/api/client-log', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label, elapsed_ms }),
  }).catch(() => {});
}

/**
 * Compute the offset needed to center a bounding box at the origin.
 * Pure function, independently testable.
 */
export function computeCenterOffset(
  min: [number, number, number],
  max: [number, number, number],
): [number, number, number] {
  return [
    -(min[0] + max[0]) / 2,
    -(min[1] + max[1]) / 2,
    -(min[2] + max[2]) / 2,
  ];
}

/**
 * Compute camera distance so the model fits in view.
 * Returns the distance from the origin along the camera's forward axis.
 */
export function computeFitDistance(
  boundingSphereRadius: number,
  fovDeg: number,
): number {
  const halfFovRad = (fovDeg * Math.PI) / 360;
  return (boundingSphereRadius / Math.sin(halfFovRad)) * 1.2;
}

interface ModelViewerProps {
  url: string;
}

function ModelViewer({ url }: ModelViewerProps) {
  const { scene } = useGLTF(url);
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls);
  useGltfCacheLifecycle(url, useGLTF.clear);

  useEffect(() => {
    debugThreeLog("ModelViewer.lifecycle", {
      event: "mount",
      url,
    });
    return () => {
      debugThreeLog("ModelViewer.lifecycle", {
        event: "unmount",
        url,
      });
    };
  }, [url]);

  useEffect(() => {
    console.timeLog('[LUMINA] generate', 'GLB loaded (useGLTF resolved)');
    _clog('generate: GLB loaded (useGLTF resolved)');
    debugThreeLog("ModelViewer.gltf", {
      url,
      resource_timing: getLatestResourceTiming(url),
      source_scene: summarizeObjectTree(scene),
    });
  }, [scene, url]);

  const preparedScene = useMemo(() => {
    const buildStart = performance.now();
    const clone = cloneObjectTreeWithOwnedResources(scene);

    // Remove any baked-in bed mesh from old GLB files
    const toRemove: THREE.Object3D[] = [];
    clone.traverse((child) => {
      if (child.name.toLowerCase() === "bed") {
        toRemove.push(child);
      }
    });
    toRemove.forEach((obj) => obj.removeFromParent());

    // Convert all mesh materials to pure diffuse (no specular reflections).
    // Trimesh-exported GLB uses MeshStandardMaterial which reflects the HDR
    // environment map, causing unwanted glare on the color surfaces.
    // We replace them with MeshLambertMaterial for a completely matte finish.
    clone.traverse((child) => {
      if (child instanceof THREE.Mesh && child.material) {
        const previousMaterial = child.material;
        const mats = Array.isArray(previousMaterial)
          ? previousMaterial
          : [previousMaterial];
        const replacedMaterials: THREE.Material[] = [];
        const newMats = mats.map((mat: THREE.Material) => {
          if (mat instanceof THREE.MeshStandardMaterial) {
            replacedMaterials.push(mat);
            return new THREE.MeshLambertMaterial({ color: mat.color });
          }
          return mat;
        });
        if (replacedMaterials.length > 0) {
          for (const material of replacedMaterials) {
            disposeMaterial(material);
          }
          child.material = Array.isArray(previousMaterial) ? newMats : newMats[0];
        }
      }
    });

    // Trimesh exports Z-up with image in XY plane.
    // Keep as-is: image faces camera in XY, thickness along +Z.
    clone.updateMatrixWorld(true);

    // Compute bounding box
    const box = new THREE.Box3().setFromObject(clone);

    // Center on X and Y (model centered on bed), place bottom at Z=0
    // so the model sits on top of the bed platform.
    const center = new THREE.Vector3();
    box.getCenter(center);
    clone.position.set(-center.x, -center.y, -box.min.z);

    debugThreeLog("ModelViewer.build", {
      url,
      build_ms: +(performance.now() - buildStart).toFixed(2),
      source_scene: summarizeObjectTree(scene),
      prepared_scene: summarizeObjectTree(clone),
      center: {
        x: +center.x.toFixed(3),
        y: +center.y.toFixed(3),
        z: +center.z.toFixed(3),
      },
      min_z: +box.min.z.toFixed(3),
    });

    return clone;
  }, [scene, url]);

  useEffect(() => {
    console.timeLog('[LUMINA] generate', 'GLB scene processed (useMemo done)');
    _clog('generate: GLB scene processed (useMemo done)');
  }, [preparedScene]);

  useEffect(() => {
    return () => {
      debugThreeLog("ModelViewer.dispose", {
        url,
        prepared_scene: summarizeObjectTree(preparedScene),
      });
      disposeObjectTree(preparedScene);
    };
  }, [preparedScene, url]);

  // Auto-fit camera to model after load
  useEffect(() => {
    preparedScene.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(preparedScene);
    const sphere = new THREE.Sphere();
    box.getBoundingSphere(sphere);

    const perspCam = camera as THREE.PerspectiveCamera;
    const dist = computeFitDistance(sphere.radius, perspCam.fov);

    // Model is already centered at origin — camera looks straight at (0,0,0) from +Z
    camera.position.set(0, 0, dist);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();

    if (controls) {
      const oc = controls as unknown as {
        target: THREE.Vector3;
        maxDistance: number;
        minDistance: number;
        update: () => void;
      };
      oc.target.set(0, 0, 0);
      oc.maxDistance = dist * 5;
      oc.minDistance = dist * 0.1;
      oc.update();
    }

    console.timeLog('[LUMINA] generate', 'camera fitted (model fully visible)');
    console.timeEnd('[LUMINA] generate');
    _clog('generate: camera fitted (model fully visible)');
  }, [preparedScene, camera, controls]);

  return <primitive object={preparedScene} />;
}

export default ModelViewer;
