import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useThree } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import { OBJLoader } from "three/examples/jsm/loaders/OBJLoader.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import * as THREE from "three";
import { useI18n } from "../i18n/context";
import { disposeObjectTree } from "../utils/threeDisposal";
import { computeFitDistance } from "./ModelViewer";

interface ModelSurfaceSelector3DProps {
  file: File;
  selectionReady: boolean;
  selecting: boolean;
  onSelectFace: (faceIndex: number) => void;
}

type LoadedSurfaceModel =
  | {
      kind: "stl";
      geometry: THREE.BufferGeometry;
      position: THREE.Vector3;
    }
  | {
      kind: "object";
      object: THREE.Group;
    };

function disposeLoadedModel(model: LoadedSurfaceModel): void {
  if (model.kind === "stl") {
    model.geometry.dispose();
    return;
  }
  disposeObjectTree(model.object);
}

function applySurfaceMaterial(root: THREE.Object3D, material: THREE.Material): void {
  root.traverse((child) => {
    if (child instanceof THREE.Mesh) {
      child.material = material;
      child.castShadow = false;
      child.receiveShadow = true;
    }
  });
}

function centerGeometry(geometry: THREE.BufferGeometry): THREE.Vector3 {
  geometry.computeBoundingBox();
  const box = geometry.boundingBox;
  if (!box) {
    return new THREE.Vector3();
  }
  const center = new THREE.Vector3();
  box.getCenter(center);
  return new THREE.Vector3(-center.x, -center.y, -box.min.z);
}

function centerModel(root: THREE.Object3D): THREE.Group {
  root.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(root);
  const center = new THREE.Vector3();
  box.getCenter(center);
  const group = new THREE.Group();
  root.position.set(-center.x, -center.y, -box.min.z);
  group.add(root);
  group.updateMatrixWorld(true);
  group.raycast = (raycaster, intersects) => {
    raycaster.intersectObjects(group.children, true, intersects);
  };
  return group;
}

export default function ModelSurfaceSelector3D({
  file,
  selectionReady,
  selecting,
  onSelectFace,
}: ModelSurfaceSelector3DProps) {
  const { t } = useI18n();
  const [model, setModel] = useState<LoadedSurfaceModel | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const groupRef = useRef<THREE.Group>(null);
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls);
  const invalidate = useThree((state) => state.invalidate);
  const material = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: selectionReady ? "#89c2ff" : "#d8dde6",
        roughness: 0.72,
        metalness: 0.02,
        side: THREE.DoubleSide,
      }),
    [selectionReady],
  );

  useEffect(() => {
    let canceled = false;
    const lowerName = file.name.toLowerCase();
    const handleLoaded = (nextModel: LoadedSurfaceModel) => {
      if (canceled) {
        disposeLoadedModel(nextModel);
        return;
      }
      setModel((previous) => {
        if (previous) {
          disposeLoadedModel(previous);
        }
        return nextModel;
      });
      setLoadState("ready");
      invalidate();
    };

    setLoadState("loading");
    setModel((previous) => {
      if (previous) {
        disposeLoadedModel(previous);
      }
      return null;
    });

    async function loadFile(): Promise<void> {
      try {
        if (lowerName.endsWith(".obj")) {
          const text = await file.text();
          const root = new OBJLoader().parse(text);
          applySurfaceMaterial(root, material);
          handleLoaded({ kind: "object", object: centerModel(root) });
          return;
        }
        const buffer = await file.arrayBuffer();
        const geometry = new STLLoader().parse(buffer);
        geometry.computeVertexNormals();
        handleLoaded({
          kind: "stl",
          geometry,
          position: centerGeometry(geometry),
        });
      } catch (err) {
        if (!canceled) {
          console.warn("Model surface preview load failed", err);
          setLoadState("error");
          invalidate();
        }
      }
    }

    void loadFile();

    return () => {
      canceled = true;
      setModel((previous) => {
        if (previous) {
          disposeLoadedModel(previous);
        }
        return null;
      });
    };
  }, [file, material, invalidate]);

  useEffect(() => {
    if (!model || !groupRef.current) {
      return;
    }
    groupRef.current.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(groupRef.current);
    if (box.isEmpty()) {
      return;
    }
    const center = new THREE.Vector3();
    box.getCenter(center);
    const size = new THREE.Vector3();
    box.getSize(size);
    const radius = Math.max(size.x, size.y, size.z, 1) / 2;
    const perspCam = camera as THREE.PerspectiveCamera;
    const dist = computeFitDistance(radius, perspCam.fov) * 1.55;
    camera.position.set(center.x, center.y - dist * 0.42, center.z + dist);
    camera.lookAt(center);
    camera.updateProjectionMatrix();
    if (controls) {
      const orbit = controls as unknown as {
        target: THREE.Vector3;
        maxDistance: number;
        minDistance: number;
        update: () => void;
      };
      orbit.target.copy(center);
      orbit.minDistance = Math.max(1, dist * 0.08);
      orbit.maxDistance = dist * 5;
      orbit.update();
    }
    invalidate();
  }, [camera, controls, invalidate, model]);

  const handlePointerDown = useCallback(
    (event: { stopPropagation: () => void; faceIndex?: number }) => {
      event.stopPropagation();
      if (selecting || typeof event.faceIndex !== "number") {
        return;
      }
      onSelectFace(event.faceIndex);
    },
    [onSelectFace, selecting],
  );

  if (!model) {
    if (loadState === "error") {
      return (
        <Html center>
          <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs font-medium text-red-700 shadow-sm dark:border-red-800 dark:bg-red-950/80 dark:text-red-200">
            {t("model_surface_viewer_load_failed")}
          </div>
        </Html>
      );
    }
    if (loadState === "loading") {
      return (
        <Html center>
          <div className="rounded-md border border-slate-200 bg-white/90 px-3 py-2 text-xs font-medium text-slate-700 shadow-sm dark:border-slate-700 dark:bg-slate-900/90 dark:text-slate-200">
            {t("model_surface_viewer_loading")}
          </div>
        </Html>
      );
    }
    return null;
  }

  return (
    <group ref={groupRef}>
      {model.kind === "stl" ? (
        <mesh
          geometry={model.geometry}
          material={material}
          position={model.position}
          onPointerDown={handlePointerDown}
        />
      ) : (
        <primitive object={model.object} onPointerDown={handlePointerDown} />
      )}
    </group>
  );
}
