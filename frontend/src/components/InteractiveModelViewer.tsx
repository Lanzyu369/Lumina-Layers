/* eslint-disable react-refresh/only-export-components */
import { useMemo, useEffect, useRef } from "react";
import { useGLTF } from "@react-three/drei";
import * as THREE from "three";
import { useConverterStore } from "../stores/converter";
import {
  cloneObjectTreeWithOwnedResources,
  disposeMaterial,
  disposeMeshResources,
  disposeObjectTree,
} from "../utils/threeDisposal";
import OutlineFrame3D from "./OutlineFrame3D";
import CloisonneWire3D from "./CloisonneWire3D";
import {
  debugThreeLog,
  getLatestResourceTiming,
  summarizeMeshList,
  summarizeObjectTree,
} from "../utils/threeDebug";
import { postClientLog } from "../utils/clientLog";
import { createMatteMaterialFromStandard } from "../utils/threeMatteMaterial";
import PuzzleOverlay3D from "./PuzzleOverlay3D";
import { useGltfCacheLifecycle } from "./useGltfCacheLifecycle";
import { materializePositionAttributeForGeometryBake } from "../utils/threeQuantizedGeometry";
import type { PuzzleOverlayBounds } from "./puzzleOverlay3DUtils";

type LuminaWindow = Window & { __luminaPreviewStart?: number };

function _getPreviewStartTime(): number | null {
  return (window as LuminaWindow).__luminaPreviewStart ?? null;
}

// ========== Exported pure utility functions (testable without Three.js) ==========

/**
 * Extract hex color string from a mesh name with "color_" prefix.
 * 从带有 "color_" 前缀的网格名称中提取 hex 颜色字符串。
 *
 * @param meshName - The mesh name, e.g. "color_ff0000". (网格名称)
 * @returns The hex string without prefix, e.g. "ff0000". (不含前缀的 hex 字符串)
 */
export function extractHexFromMeshName(meshName: string): string {
  return meshName.slice(6, 12);
}

// ========== Component ==========

export interface InteractiveModelViewerProps {
  url: string;
  colorRemapMap: Record<string, string>;
  colorHeightMap: Record<string, number>;
  baseHeight: number;
  enableRelief: boolean;
  scaleX?: number;  // X 方向缩放比例，默认 1.0
  scaleY?: number;  // Y 方向缩放比例，默认 1.0
  spacerThick?: number;    // 底板厚度 (mm)，默认 1.2
  structureMode?: string;  // "Double-sided" | "Single-sided"
  enableOutline?: boolean;   // 是否启用外轮廓预览，默认 false
  outlineWidth?: number;     // 外轮廓厚度 (mm)，默认 2.0
  enableCloisonne?: boolean;   // 是否启用景泰蓝预览，默认 false
  wireWidthMm?: number;        // 金丝宽度 (mm)，默认 0.4
  wireHeightMm?: number;       // 金丝高度 (mm)，默认 0.1
  enableFridgeMagnet?: boolean;
  rasterCellSize?: number;
  puzzleOverlayEnabled?: boolean;
  puzzleOverlayUrl?: string | null;
}

/** Color layer thickness in mm (5 layers × 0.08mm). */
const COLOR_LAYER_HEIGHT = 0.4;
const PREVIEW_CANVAS_BOUNDS_NODE_NAME = "preview_canvas_bounds";

export function computeOutlinePreviewHeight(
  spacerThick: number,
  structureMode: string,
  enableRelief: boolean,
  colorHeightMap: Record<string, number>,
  fallbackModelMaxZ: number,
): number {
  const safeSpacerThick = Number.isFinite(spacerThick)
    ? Math.max(0, spacerThick)
    : 0;
  const reliefHeights = Object.values(colorHeightMap).filter(
    (height) => Number.isFinite(height) && height > 0,
  );
  const colorLayerHeight = enableRelief && reliefHeights.length > 0
    ? Math.max(COLOR_LAYER_HEIGHT, ...reliefHeights)
    : COLOR_LAYER_HEIGHT * (structureMode.includes("Double") ? 2 : 1);
  const livePreviewHeight = safeSpacerThick + colorLayerHeight;
  if (livePreviewHeight > 0) {
    return livePreviewHeight;
  }
  return Number.isFinite(fallbackModelMaxZ) ? Math.max(0, fallbackModelMaxZ) : 0;
}

function InteractiveModelViewer({
  url,
  colorRemapMap,
  colorHeightMap,
  baseHeight,
  enableRelief,
  scaleX = 1,
  scaleY = 1,
  spacerThick = 1.2,
  structureMode = "Double-sided",
  enableOutline = false,
  outlineWidth = 2.0,
  enableCloisonne = false,
  wireWidthMm = 0.4,
  wireHeightMm = 0.1,
  enableFridgeMagnet = false,
  rasterCellSize,
  puzzleOverlayEnabled = false,
  puzzleOverlayUrl = null,
}: InteractiveModelViewerProps) {
  const { scene } = useGLTF(url);
  const groupRef = useRef<THREE.Group>(null);
  useGltfCacheLifecycle(url, useGLTF.clear);

  useEffect(() => {
    debugThreeLog("InteractiveModelViewer.lifecycle", {
      event: "mount",
      url,
    });
    return () => {
      debugThreeLog("InteractiveModelViewer.lifecycle", {
        event: "unmount",
        url,
      });
    };
  }, [url]);

  useEffect(() => {
    const resourceTiming = getLatestResourceTiming(url);
    const sourceScene = summarizeObjectTree(scene);
    postClientLog("preview: GLB loaded (useGLTF resolved)", {
      startTime: _getPreviewStartTime(),
      scope: "preview-viewer",
      phase: "gltf-loaded",
      dedupeMs: 250,
      details: {
        url,
        resource_timing: resourceTiming,
        source_scene: sourceScene,
      },
    });
    debugThreeLog("InteractiveModelViewer.gltf", {
      url,
      resource_timing: resourceTiming,
      source_scene: sourceScene,
    });
  }, [scene, url]);

  // Clone scene once per URL load, apply rotation/centering,
  // and clone each color mesh's material to avoid shared-material mutations.
  // Also separate color_ meshes from non-color children for individual JSX rendering.
  const {
    nonColorObject,
    colorMeshes,
    modelBounds,
    sceneCenter,
    backingPlateMesh,
    puzzleOverlayBounds,
    buildSummary,
  } = useMemo(() => {
    const buildStart = performance.now();
    const clone = cloneObjectTreeWithOwnedResources(scene);

    // Remove any baked-in bed mesh
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
    // Skip backing_plate — it gets its own independent material below.
    clone.traverse((child) => {
      if (
        child instanceof THREE.Mesh
        && child.material
        && child.name !== "backing_plate"
        && child.name !== PREVIEW_CANVAS_BOUNDS_NODE_NAME
      ) {
        const previousMaterial = child.material;
        const mats = Array.isArray(previousMaterial)
          ? previousMaterial
          : [previousMaterial];
        const replacedMaterials: THREE.Material[] = [];
        const newMats = mats.map((mat: THREE.Material) => {
          if (mat instanceof THREE.MeshStandardMaterial) {
            replacedMaterials.push(mat);
            return createMatteMaterialFromStandard(mat);
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
    // We want the image to face the camera (stand upright in XY),
    // with thickness along +Z (toward camera).
    // No rotation needed — keep the Trimesh coordinate system as-is,
    // since Three.js XY plane is the screen plane.
    clone.updateMatrixWorld(true);

    // Compute the centering box from visible model geometry. The optional
    // preview-canvas anchor is only for overlay placement and must not change
    // legacy modelBounds used by keychain/fridge-magnet controls.
    const box = new THREE.Box3();
    const childBox = new THREE.Box3();
    clone.traverse((child) => {
      if (
        child instanceof THREE.Mesh
        && child.name !== PREVIEW_CANVAS_BOUNDS_NODE_NAME
      ) {
        childBox.setFromObject(child);
        box.union(childBox);
      }
    });
    if (box.isEmpty()) {
      box.setFromObject(clone);
    }

    // Center on X and Y (model centered on bed), but place bottom at Z=0
    // so the model sits on top of the bed platform (Z = -0.1).
    const center = new THREE.Vector3();
    box.getCenter(center);
    clone.position.set(-center.x, -center.y, -box.min.z);
    clone.updateMatrixWorld(true);

    // --- Extract full preview-canvas bounds anchor from GLB scene ---
    let extractedPreviewCanvasBounds: THREE.Mesh | null = null;
    clone.traverse((child) => {
      if (child instanceof THREE.Mesh && child.name === PREVIEW_CANVAS_BOUNDS_NODE_NAME) {
        extractedPreviewCanvasBounds = child;
      }
    });
    let resolvedPuzzleOverlayBounds: PuzzleOverlayBounds | null = null;
    if (extractedPreviewCanvasBounds !== null) {
      const canvasBoundsMesh = extractedPreviewCanvasBounds as THREE.Mesh;
      canvasBoundsMesh.updateWorldMatrix(true, false);
      materializePositionAttributeForGeometryBake(canvasBoundsMesh.geometry);
      canvasBoundsMesh.geometry.applyMatrix4(canvasBoundsMesh.matrixWorld);
      canvasBoundsMesh.position.set(0, 0, 0);
      canvasBoundsMesh.rotation.set(0, 0, 0);
      canvasBoundsMesh.scale.set(1, 1, 1);
      canvasBoundsMesh.updateMatrixWorld(true);
      canvasBoundsMesh.removeFromParent();

      canvasBoundsMesh.geometry.computeBoundingBox();
      const canvasBox = canvasBoundsMesh.geometry.boundingBox;
      if (canvasBox && !canvasBox.isEmpty()) {
        resolvedPuzzleOverlayBounds = {
          minX: canvasBox.min.x,
          maxX: canvasBox.max.x,
          minY: canvasBox.min.y,
          maxY: canvasBox.max.y,
          maxZ: canvasBox.max.z,
        };
      }
      disposeMeshResources(canvasBoundsMesh);
    }

    // --- Extract backing_plate mesh from GLB scene ---
    let extractedBackingPlate: THREE.Mesh | null = null;
    clone.traverse((child) => {
      if (child instanceof THREE.Mesh && child.name === "backing_plate") {
        extractedBackingPlate = child;
      }
    });

    if (extractedBackingPlate !== null) {
      const bp = extractedBackingPlate as THREE.Mesh;
      // Bake world matrix so geometry is in centered world space
      bp.updateWorldMatrix(true, false);
      materializePositionAttributeForGeometryBake(bp.geometry);
      bp.geometry.applyMatrix4(bp.matrixWorld);
      bp.position.set(0, 0, 0);
      bp.rotation.set(0, 0, 0);
      bp.scale.set(1, 1, 1);
      bp.updateMatrixWorld(true);

      // Detach from clone tree
      bp.removeFromParent();

      // Apply independent MeshLambertMaterial (Requirement 4.1, 4.2, 4.3)
      const previousBackingMaterial = bp.material;
      const backingMat = new THREE.MeshLambertMaterial({
        color: 0xf5f5f5,
        side: THREE.DoubleSide,
        toneMapped: false,
      });
      bp.material = backingMat;
      disposeMaterial(previousBackingMaterial);
    }

    // Separate color_ meshes from the rest (excluding backing_plate)
    const colorMeshList: THREE.Mesh[] = [];
    const colorMeshParents: { mesh: THREE.Mesh; parent: THREE.Object3D }[] = [];

    clone.traverse((child) => {
      if (child instanceof THREE.Mesh && child.name.startsWith("color_")) {
        colorMeshList.push(child);
        if (child.parent) {
          colorMeshParents.push({ mesh: child, parent: child.parent });
        }
      }
    });

    // Bake the parent's centering offset into each color mesh's geometry
    // so they remain centered after detachment from the clone tree.
    for (const mesh of colorMeshList) {
      materializePositionAttributeForGeometryBake(mesh.geometry);
      mesh.geometry.applyMatrix4(mesh.matrixWorld);
      mesh.position.set(0, 0, 0);
      mesh.rotation.set(0, 0, 0);
      mesh.scale.set(1, 1, 1);
      mesh.updateMatrixWorld(true);
    }

    // Detach color meshes from the clone tree so they can be rendered as individual JSX
    for (const { mesh, parent } of colorMeshParents) {
      parent.remove(mesh);
    }

    // Compute model bounding box from color meshes only (after centering).
    // Do NOT include the clone — it may be empty or contain stale transforms
    // that pollute the bounds and cause pixel coordinate offsets.
    const boundsBox = new THREE.Box3();
    for (const mesh of colorMeshList) {
      mesh.geometry.computeBoundingBox();
      if (mesh.geometry.boundingBox) {
        boundsBox.union(mesh.geometry.boundingBox);
      }
    }
    // Include backing plate in bounds calculation
    if (extractedBackingPlate !== null) {
      const bp = extractedBackingPlate as THREE.Mesh;
      bp.geometry.computeBoundingBox();
      if (bp.geometry.boundingBox) {
        boundsBox.union(bp.geometry.boundingBox);
      }
    }

    const bounds = boundsBox.isEmpty()
      ? null
      : {
          minX: boundsBox.min.x,
          maxX: boundsBox.max.x,
          minY: boundsBox.min.y,
          maxY: boundsBox.max.y,
          maxZ: boundsBox.max.z, // thickness direction (toward camera)
        };

    const buildSummary = {
      url,
      build_ms: +(performance.now() - buildStart).toFixed(2),
      source_scene: summarizeObjectTree(scene),
      non_color_scene: summarizeObjectTree(clone),
      color_meshes: summarizeMeshList(colorMeshList),
      backing_plate: summarizeMeshList(
        extractedBackingPlate ? [extractedBackingPlate as THREE.Mesh] : [],
      ),
      puzzle_overlay_bounds: resolvedPuzzleOverlayBounds,
      model_bounds: bounds,
      scene_center: {
        x: +center.x.toFixed(3),
        y: +center.y.toFixed(3),
        z: +center.z.toFixed(3),
      },
    };
    debugThreeLog("InteractiveModelViewer.build", buildSummary);

    return {
      nonColorObject: clone,
      colorMeshes: colorMeshList,
      modelBounds: bounds,
      sceneCenter: center,
      backingPlateMesh: extractedBackingPlate as THREE.Mesh | null,
      puzzleOverlayBounds: resolvedPuzzleOverlayBounds,
      buildSummary,
    };
  }, [scene, url]);

  useEffect(() => {
    postClientLog("preview: GLB scene processed (useMemo done)", {
      startTime: _getPreviewStartTime(),
      scope: "preview-viewer",
      phase: "scene-processed",
      dedupeMs: 250,
      details: buildSummary,
    });
  }, [buildSummary]);

  // Expose model bounds to store for KeychainRing3D positioning
  useEffect(() => {
    useConverterStore.getState().setModelBounds(modelBounds);
  }, [modelBounds]);

  useEffect(() => {
    return () => {
      debugThreeLog("InteractiveModelViewer.dispose", {
        url,
        non_color_scene: summarizeObjectTree(nonColorObject),
        color_meshes: summarizeMeshList(colorMeshes),
        backing_plate: summarizeMeshList(backingPlateMesh ? [backingPlateMesh] : []),
      });
      disposeObjectTree(nonColorObject);
      for (const mesh of colorMeshes) {
        disposeMeshResources(mesh);
      }
      if (backingPlateMesh) {
        disposeMeshResources(backingPlateMesh);
      }
    };
  }, [nonColorObject, colorMeshes, backingPlateMesh, url]);

  const outlinePreviewHeight = computeOutlinePreviewHeight(
    spacerThick,
    structureMode,
    enableRelief,
    colorHeightMap,
    modelBounds?.maxZ ?? 0,
  );

  // ---- White backing plate mesh ----
  const isDoubleSided = structureMode === "Double-sided";
  const backingMesh = useMemo(() => {
    // When GLB contains backing_plate: use it directly (Requirement 2.2, 2.4)
    if (backingPlateMesh) {
      return backingPlateMesh;
    }

    // Fallback: create rectangular BoxGeometry when GLB has no backing_plate (Requirement 2.3)
    if (!modelBounds) return null;
    const w = modelBounds.maxX - modelBounds.minX;
    const h = modelBounds.maxY - modelBounds.minY;
    if (w <= 0 || h <= 0) return null;

    const geo = new THREE.BoxGeometry(w, h, spacerThick);
    const mat = new THREE.MeshLambertMaterial({
      color: 0xf5f5f5,
      side: THREE.DoubleSide,
      toneMapped: false,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.name = "__backing_plate_fallback";

    const cx = (modelBounds.minX + modelBounds.maxX) / 2;
    const cy = (modelBounds.minY + modelBounds.maxY) / 2;
    mesh.position.set(cx, cy, spacerThick / 2);
    return mesh;
  }, [backingPlateMesh, modelBounds, spacerThick]);

  useEffect(() => {
    return () => {
      if (backingMesh && backingMesh !== backingPlateMesh) {
        disposeMeshResources(backingMesh);
      }
    };
  }, [backingMesh, backingPlateMesh]);

  // Camera is managed by BedPlatform's default view — skip auto-fit here
  // so the viewport stays stable when a preview model loads.

  // Double-sided mirror meshes: pre-create clones that share the same material
  // so color remap mutations apply to both sides automatically.
  const mirrorMeshes = useMemo(() => {
    if (!isDoubleSided) return [];
    return colorMeshes.map((mesh) => {
      const mirror = mesh.clone(true);
      // Share the same material instance so color remap applies to both
      mirror.material = mesh.material;
      mirror.name = `mirror_${mesh.name}`;
      return mirror;
    });
  }, [colorMeshes, isDoubleSided]);


  // Imperative Three.js mutations: color remap, relief scaling.
  useEffect(() => {
    // ---- Backing plate Z positioning and scaling (Requirements 3.1, 3.2, 3.3, 3.4) ----
    // XY scale is inherited from parent group via scaleX/scaleY (Requirement 3.4)
    if (backingMesh) {
      if (backingPlateMesh && backingMesh === backingPlateMesh) {
        // GLB-extracted backing plate: scale Z to match spacerThick
        // The native mesh has Z height = 1 voxel layer × LAYER_HEIGHT
        backingMesh.geometry.computeBoundingBox();
        const backingBBox = backingMesh.geometry.boundingBox;
        const nativeH = backingBBox
          ? backingBBox.max.z - backingBBox.min.z
          : 1;
        backingMesh.scale.z = nativeH > 0 ? spacerThick / nativeH : 1;
        // Bottom-aligned at Z=0; top face at Z=spacerThick (Requirement 3.1, 3.2)
        backingMesh.position.z = 0;
      }
      // Fallback BoxGeometry already has correct size and position from useMemo
    }

    for (const mesh of colorMeshes) {
      const origHex = extractHexFromMeshName(mesh.name);
      const mat = mesh.material as THREE.MeshLambertMaterial;

      // Color replacement — always apply
      const remappedHex = colorRemapMap[origHex] || origHex;
      mat.color.set(`#${remappedHex}`);

      // Keep all meshes fully opaque and unchanged
      mat.emissive.set(0x000000);
      mat.opacity = 1.0;
      mat.transparent = false;
      mat.side = THREE.DoubleSide;
      mat.toneMapped = false;
      mat.needsUpdate = true;

      // Compute Z scale: map the GLB's native color height to the target height
      // GLB color meshes span [0, nativeH] where nativeH ≈ 2.0mm (25 layers × 0.08)
      mesh.geometry.computeBoundingBox();
      const nativeH = mesh.geometry.boundingBox
        ? mesh.geometry.boundingBox.max.z - mesh.geometry.boundingBox.min.z
        : 1;

      if (enableRelief && baseHeight > 0) {
        // Relief mode: each color gets its own height from colorHeightMap
        const heightMm = colorHeightMap[origHex] ?? COLOR_LAYER_HEIGHT;
        mesh.scale.z = nativeH > 0 ? heightMm / nativeH : 1;
      } else {
        // Normal mode: scale to COLOR_LAYER_HEIGHT (0.4mm)
        mesh.scale.z = nativeH > 0 ? COLOR_LAYER_HEIGHT / nativeH : 1;
      }

      // Position color layer on top of the backing plate (top face at Z=spacerThick)
      mesh.position.z = spacerThick;
    }

    // Update mirror meshes for double-sided mode
    for (const mirror of mirrorMeshes) {
      const origName = mirror.name.replace("mirror_", "");
      const origMesh = colorMeshes.find((m) => m.name === origName);
      if (origMesh) {
        mirror.scale.z = -origMesh.scale.z; // flip Z direction
        mirror.position.z = 0; // grow downward from bottom of backing plate
      }
    }
  }, [colorMeshes, mirrorMeshes, colorRemapMap, colorHeightMap, enableRelief, baseHeight, modelBounds, sceneCenter, spacerThick, isDoubleSided, backingMesh, backingPlateMesh]);

  // Double-sided mirror meshes are defined above (before useEffect).

  return (
    <group ref={groupRef} scale={[scaleX, scaleY, 1]}>
      <primitive object={nonColorObject} />
      {/* Double-sided: mirror color layers below the backing plate (Z < 0) */}
      {mirrorMeshes.map((mesh) => (
        <primitive key={mesh.uuid} object={mesh} />
      ))}
      {/* White backing plate — GLB-extracted shape or rectangular fallback (Z ∈ [0, spacerThick]) */}
      {backingMesh && <primitive object={backingMesh} />}
      {/* Color layers on top of backing plate (Z ≥ spacerThick) */}
      {colorMeshes.map((mesh) => (
        <primitive key={mesh.uuid} object={mesh} />
      ))}
      {/* 外轮廓预览 */}
      <OutlineFrame3D
        enabled={enableOutline}
        outlineWidth={outlineWidth}
        backingPlateMesh={backingMesh}
        sourceMeshes={colorMeshes.length > 0 ? colorMeshes : undefined}
        modelMaxZ={outlinePreviewHeight}
        rasterCellSize={rasterCellSize}
        fillInteriorHoles={enableFridgeMagnet}
      />
      {/* 景泰蓝金色线条预览 */}
      <CloisonneWire3D
        enabled={enableCloisonne}
        wireWidthMm={wireWidthMm}
        wireHeightMm={wireHeightMm}
        colorMeshes={colorMeshes}
        backingPlateMesh={backingMesh}
        spacerThick={spacerThick}
      />
      <PuzzleOverlay3D
        enabled={puzzleOverlayEnabled}
        overlayUrl={puzzleOverlayUrl}
        modelBounds={modelBounds}
        previewCanvasBounds={puzzleOverlayBounds}
        spacerThick={spacerThick}
        enableRelief={enableRelief}
        colorHeightMap={colorHeightMap}
        enableOutline={enableOutline}
        enableCloisonne={enableCloisonne}
        wireHeightMm={wireHeightMm}
      />
    </group>
  );
}

export default InteractiveModelViewer;
