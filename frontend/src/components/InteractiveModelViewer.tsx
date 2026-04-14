/* eslint-disable react-refresh/only-export-components */
import { useMemo, useEffect, useRef, useCallback } from "react";
import { useThree, useFrame } from "@react-three/fiber";
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
import PuzzleOverlay3D from "./PuzzleOverlay3D";
import { useGltfCacheLifecycle } from "./useGltfCacheLifecycle";

// ========== Exported pure utility functions (testable without Three.js) ==========

/**
 * Extract hex color string from a mesh name with "color_" prefix.
 * 从带有 "color_" 前缀的网格名称中提取 hex 颜色字符串。
 *
 * @param meshName - The mesh name, e.g. "color_ff0000". (网格名称)
 * @returns The hex string without prefix, e.g. "ff0000". (不含前缀的 hex 字符串)
 */
export function extractHexFromMeshName(meshName: string): string {
  return meshName.slice(6);
}

/**
 * Compute the next selected color after a click toggle.
 * 计算点击切换后的下一个选中颜色。
 *
 * @param currentSelected - Currently selected hex or null. (当前选中的 hex 或 null)
 * @param clickedHex - The hex that was clicked. (被点击的 hex)
 * @returns null if toggling off (same color), otherwise the clicked hex. (取消选中返回 null，否则返回被点击的 hex)
 */
export function toggleColorSelection(
  currentSelected: string | null,
  clickedHex: string,
): string | null {
  return currentSelected === clickedHex ? null : clickedHex;
}

/**
 * Determine whether a pointer interaction should still be treated as a click.
 * 判断一次指针交互是否仍应视为点击，而非拖拽。
 *
 * @param startX - Pointer-down X coordinate in CSS pixels. (按下时 X 坐标，单位 CSS 像素)
 * @param startY - Pointer-down Y coordinate in CSS pixels. (按下时 Y 坐标，单位 CSS 像素)
 * @param endX - Current or release X coordinate in CSS pixels. (当前或抬起时 X 坐标，单位 CSS 像素)
 * @param endY - Current or release Y coordinate in CSS pixels. (当前或抬起时 Y 坐标，单位 CSS 像素)
 * @param thresholdPx - Maximum movement allowed for a click. (判定为点击时允许的最大移动距离)
 * @returns True when the interaction stays within the click threshold. (位移未超过点击阈值时返回 true)
 */
export function isClickWithoutDrag(
  startX: number,
  startY: number,
  endX: number,
  endY: number,
  thresholdPx: number = 4,
): boolean {
  return Math.hypot(endX - startX, endY - startY) <= thresholdPx;
}

/**
 * Determine whether native canvas color-picking handlers should process an event.
 * 判断原生画布取色处理器是否应处理当前事件。
 *
 * @param button - Pointer button identifier from the native event. (原生事件中的按键编号)
 * @param colorPickingEnabled - Whether InteractiveModelViewer is allowed to pick colors. (是否允许取色)
 * @returns True only for enabled left-click interactions. (仅在启用且为左键时返回 true)
 */
export function shouldHandleColorPickingEvent(
  button: number,
  colorPickingEnabled: boolean,
): boolean {
  return colorPickingEnabled && button === 0;
}

interface SelectionVisualModelBounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
  maxZ: number;
}

interface SelectionVisualRegionData {
  contours?: number[][][] | null;
}

interface SelectionVisualRegion {
  colorHex: string;
  contours?: number[][][] | null;
}

interface ResolveSelectionOutlineTargetsArgs {
  selectionVisualsEnabled: boolean;
  modelBounds: SelectionVisualModelBounds | null;
  selectionMode: string;
  selectedColor: string | null;
  selectedColors: Set<string>;
  selectedRegions: SelectionVisualRegion[];
  regionData: SelectionVisualRegionData | null;
  colorContours: Record<string, number[][][]>;
}

export function resolveSelectionOutlineTargets({
  selectionVisualsEnabled,
  modelBounds,
  selectionMode,
  selectedColor,
  selectedColors,
  selectedRegions,
  regionData,
  colorContours,
}: ResolveSelectionOutlineTargetsArgs): Array<{ hex: string; polygons: number[][][] }> {
  if (!selectionVisualsEnabled || !modelBounds) {
    return [];
  }

  if (
    (selectionMode === "current" || selectionMode === "region")
    && selectedColor
    && regionData?.contours
    && regionData.contours.length > 0
  ) {
    return [{ hex: selectedColor, polygons: regionData.contours }];
  }

  if (selectionMode === "multi-select" && selectedRegions.length > 0) {
    return selectedRegions.flatMap((region) => (
      region.contours && region.contours.length > 0
        ? [{ hex: region.colorHex.replace(/^#/, ""), polygons: region.contours }]
        : []
    ));
  }

  if (selectionMode === "select-all" && selectedColors.size > 0) {
    return Array.from(selectedColors).flatMap((hex) => (
      colorContours[hex] ? [{ hex, polygons: colorContours[hex] }] : []
    ));
  }

  if (selectedColor && colorContours[selectedColor]) {
    return [{ hex: selectedColor, polygons: colorContours[selectedColor] }];
  }

  return [];
}

// ========== Component ==========

export interface InteractiveModelViewerProps {
  url: string;
  colorRemapMap: Record<string, string>;
  colorHeightMap: Record<string, number>;
  selectedColor: string | null;
  baseHeight: number;
  enableRelief: boolean;
  onColorClick: (hex: string | null) => void;
  scaleX?: number;  // X 方向缩放比例，默认 1.0
  scaleY?: number;  // Y 方向缩放比例，默认 1.0
  spacerThick?: number;    // 底板厚度 (mm)，默认 1.2
  structureMode?: string;  // "Double-sided" | "Single-sided"
  enableOutline?: boolean;   // 是否启用外轮廓预览，默认 false
  outlineWidth?: number;     // 外轮廓厚度 (mm)，默认 2.0
  enableCloisonne?: boolean;   // 是否启用景泰蓝预览，默认 false
  wireWidthMm?: number;        // 金丝宽度 (mm)，默认 0.4
  wireHeightMm?: number;       // 金丝高度 (mm)，默认 0.1
  puzzleOverlayEnabled?: boolean;
  puzzleOverlayUrl?: string | null;
  colorPickingEnabled?: boolean;
  selectionVisualsEnabled?: boolean;
}

/** Color layer thickness in mm (5 layers × 0.08mm). */
const COLOR_LAYER_HEIGHT = 0.4;

interface ClickGestureState {
  pointerId: number;
  startClientX: number;
  startClientY: number;
  startedOnColor: boolean;
  dragged: boolean;
}

const CLICK_DRAG_THRESHOLD_PX = 4;

function InteractiveModelViewer({
  url,
  colorRemapMap,
  colorHeightMap,
  selectedColor,
  baseHeight,
  enableRelief,
  onColorClick,
  scaleX = 1,
  scaleY = 1,
  spacerThick = 1.2,
  structureMode = "Double-sided",
  enableOutline = false,
  outlineWidth = 2.0,
  enableCloisonne = false,
  wireWidthMm = 0.4,
  wireHeightMm = 0.1,
  puzzleOverlayEnabled = false,
  puzzleOverlayUrl = null,
  colorPickingEnabled = true,
  selectionVisualsEnabled = true,
}: InteractiveModelViewerProps) {
  const { scene } = useGLTF(url);
  const groupRef = useRef<THREE.Group>(null);
  const camera = useThree((state) => state.camera);
  const gl = useThree((state) => state.gl);
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
    debugThreeLog("InteractiveModelViewer.gltf", {
      url,
      resource_timing: getLatestResourceTiming(url),
      source_scene: summarizeObjectTree(scene),
    });
  }, [scene, url]);

  // Clone scene once per URL load, apply rotation/centering,
  // and clone each color mesh's material to avoid shared-material mutations.
  // Also separate color_ meshes from non-color children for individual JSX rendering.
  const { nonColorObject, colorMeshes, modelBounds, sceneCenter, backingPlateMesh } = useMemo(() => {
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
      if (child instanceof THREE.Mesh && child.material && child.name !== "backing_plate") {
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
    // We want the image to face the camera (stand upright in XY),
    // with thickness along +Z (toward camera).
    // No rotation needed — keep the Trimesh coordinate system as-is,
    // since Three.js XY plane is the screen plane.
    clone.updateMatrixWorld(true);

    // Compute bounding box
    const box = new THREE.Box3().setFromObject(clone);

    // Center on X and Y (model centered on bed), but place bottom at Z=0
    // so the model sits on top of the bed platform (Z = -0.1).
    const center = new THREE.Vector3();
    box.getCenter(center);
    clone.position.set(-center.x, -center.y, -box.min.z);
    clone.updateMatrixWorld(true);

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
    };
  }, [scene, url]);

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

  // Raycaster for manual hit-testing on click (avoids per-mesh R3F pointer events).
  const raycasterRef = useRef(new THREE.Raycaster());
  const pointerRef = useRef(new THREE.Vector2());

  // Flag to suppress onPointerMissed when a color mesh was clicked via native event.
  // We store this on the converterStore so Scene3D can read it.
  const colorHitRef = useRef(false);
  const clickGestureRef = useRef<ClickGestureState | null>(null);

  // Read selectionMode and related state for region click handling
  const selectionMode = useConverterStore((s) => s.selectionMode);
  const selectedColors = useConverterStore((s) => s.selectedColors);
  const toggleColorInSelection = useConverterStore((s) => s.toggleColorInSelection);
  const selectedRegions = useConverterStore((s) => s.selectedRegions);
  const detectRegion = useConverterStore((s) => s.detectRegion);
  const detectAndAccumulateRegion = useConverterStore((s) => s.detectAndAccumulateRegion);
  const regionData = useConverterStore((s) => s.regionData);
  const previewPixelWidth = useConverterStore((s) => s.previewPixelWidth);
  const previewPixelHeight = useConverterStore((s) => s.previewPixelHeight);
  const previewWidthMm = useConverterStore((s) => s.preview_width_mm);

  const mapWorldToPreviewPixel = useCallback(
    (worldPoint: THREE.Vector3): { x: number; y: number } | null => {
      if (
        !groupRef.current
        || !previewPixelWidth
        || !previewPixelHeight
        || !previewWidthMm
        || previewWidthMm <= 0
      ) {
        return null;
      }

      const localPoint = groupRef.current.worldToLocal(worldPoint.clone());
      const pixelScale = previewWidthMm / previewPixelWidth;
      const originalX = localPoint.x + sceneCenter.x;
      const originalY = localPoint.y + sceneCenter.y;
      const pixelX = Math.floor(originalX / pixelScale);
      const pixelY = Math.floor(previewPixelHeight - originalY / pixelScale);

      return {
        x: Math.max(0, Math.min(previewPixelWidth - 1, pixelX)),
        y: Math.max(0, Math.min(previewPixelHeight - 1, pixelY)),
      };
    },
    [previewPixelWidth, previewPixelHeight, previewWidthMm, sceneCenter],
  );

  const getColorHitAtPointerPosition = useCallback(
    (clientX: number, clientY: number) => {
      if (!colorPickingEnabled) {
        return null;
      }
      const canvas = gl.domElement;
      const rect = canvas.getBoundingClientRect();
      pointerRef.current.x = ((clientX - rect.left) / rect.width) * 2 - 1;
      pointerRef.current.y = -((clientY - rect.top) / rect.height) * 2 + 1;

      raycasterRef.current.setFromCamera(pointerRef.current, camera);
      const intersects = raycasterRef.current.intersectObjects(colorMeshes, false);
      if (intersects.length === 0) {
        return null;
      }

      const hitMesh = intersects[0].object as THREE.Mesh;
      if (!hitMesh.name.startsWith("color_")) {
        return null;
      }

      return {
        hitMesh,
        previewPixel: mapWorldToPreviewPixel(intersects[0].point),
      };
    },
    [gl, camera, colorMeshes, mapWorldToPreviewPixel, colorPickingEnabled],
  );

  const selectColorAtPointerPosition = useCallback(
    (clientX: number, clientY: number) => {
      if (!colorPickingEnabled) {
        return false;
      }
      const hit = getColorHitAtPointerPosition(clientX, clientY);
      if (!hit) {
        return false;
      }

      colorHitRef.current = true;
      const { hitMesh, previewPixel } = hit;

      if (selectionMode === "current" || selectionMode === "region" || selectionMode === "multi-select") {
        if (!previewPixel) {
          return false;
        }

        if (selectionMode === "multi-select") {
          detectAndAccumulateRegion(previewPixel.x, previewPixel.y);
        } else {
          detectRegion(previewPixel.x, previewPixel.y);
        }
        return true;
      }

      const hex = extractHexFromMeshName(hitMesh.name);
      toggleColorInSelection(hex);
      if (selectedColors.has(hex)) {
        const remaining = Array.from(selectedColors).filter((c) => c !== hex);
        onColorClick(remaining.length > 0 ? remaining[remaining.length - 1] : null);
      } else {
        onColorClick(hex);
      }
      return true;
    },
    [
      getColorHitAtPointerPosition,
      selectedColors,
      toggleColorInSelection,
      onColorClick,
      selectionMode,
      detectRegion,
      detectAndAccumulateRegion,
      colorPickingEnabled,
    ],
  );

  const handlePointerDown = useCallback(
    (event: PointerEvent) => {
      if (!shouldHandleColorPickingEvent(event.button, colorPickingEnabled)) {
        return;
      }
      colorHitRef.current = false;
      const startHit = getColorHitAtPointerPosition(event.clientX, event.clientY);
      colorHitRef.current = startHit !== null;
      clickGestureRef.current = {
        pointerId: event.pointerId,
        startClientX: event.clientX,
        startClientY: event.clientY,
        startedOnColor: startHit !== null,
        dragged: false,
      };
    },
    [getColorHitAtPointerPosition, colorPickingEnabled],
  );

  const handlePointerUp = useCallback(
    (event: PointerEvent) => {
      if (!shouldHandleColorPickingEvent(event.button, colorPickingEnabled)) {
        return;
      }

      const gesture = clickGestureRef.current;
      clickGestureRef.current = null;
      if (!gesture || gesture.pointerId !== event.pointerId) {
        return;
      }

      const isClick = !gesture.dragged && isClickWithoutDrag(
        gesture.startClientX,
        gesture.startClientY,
        event.clientX,
        event.clientY,
        CLICK_DRAG_THRESHOLD_PX,
      );
      if (!isClick) {
        colorHitRef.current = false;
        return;
      }

      if (gesture.startedOnColor) {
        colorHitRef.current = true;
      }
      selectColorAtPointerPosition(gesture.startClientX, gesture.startClientY);
    },
    [selectColorAtPointerPosition, colorPickingEnabled],
  );

  const handlePointerMove = useCallback(
    (event: PointerEvent) => {
      const gesture = clickGestureRef.current;
      if (gesture && gesture.pointerId === event.pointerId && !gesture.dragged) {
        gesture.dragged = !isClickWithoutDrag(
          gesture.startClientX,
          gesture.startClientY,
          event.clientX,
          event.clientY,
          CLICK_DRAG_THRESHOLD_PX,
        );
        if (gesture.dragged) {
          colorHitRef.current = false;
        }
      }
    },
    [],
  );

  const handleWheel = useCallback(() => {
    clickGestureRef.current = null;
    colorHitRef.current = false;
  }, []);

  const handlePointerLeave = useCallback(() => {
    clickGestureRef.current = null;
    colorHitRef.current = false;
  }, []);

  const handlePointerCancel = useCallback(() => {
    clickGestureRef.current = null;
    colorHitRef.current = false;
  }, []);

  useEffect(() => {
    if (colorPickingEnabled) {
      return;
    }
    clickGestureRef.current = null;
    colorHitRef.current = false;
  }, [colorPickingEnabled]);

  useEffect(() => {
    return () => {
      clickGestureRef.current = null;
    };
  }, []);

  // Expose colorHitRef check so Scene3D's onPointerMissed can query it
  useEffect(() => {
    (window as unknown as Record<string, unknown>).__luminaColorHitRef = colorHitRef;
    return () => {
      delete (window as unknown as Record<string, unknown>).__luminaColorHitRef;
    };
  }, []);

  // Attach/detach native pointer event for color mesh click detection
  useEffect(() => {
    const canvas = gl.domElement;
    canvas.addEventListener("pointerdown", handlePointerDown);
    canvas.addEventListener("pointerup", handlePointerUp);
    canvas.addEventListener("pointermove", handlePointerMove);
    canvas.addEventListener("wheel", handleWheel, { passive: true });
    canvas.addEventListener("pointerleave", handlePointerLeave);
    canvas.addEventListener("pointercancel", handlePointerCancel);
    return () => {
      canvas.removeEventListener("pointerdown", handlePointerDown);
      canvas.removeEventListener("pointerup", handlePointerUp);
      canvas.removeEventListener("pointermove", handlePointerMove);
      canvas.removeEventListener("wheel", handleWheel);
      canvas.removeEventListener("pointerleave", handlePointerLeave);
      canvas.removeEventListener("pointercancel", handlePointerCancel);
    };
  }, [gl, handlePointerDown, handlePointerUp, handlePointerMove, handleWheel, handlePointerLeave, handlePointerCancel]);

  // Edge outline LineSegments for selected color regions.
  const outlineObjsRef = useRef<THREE.LineSegments[]>([]);
  // Normalized arc-length ratios per outline, for flowing RGB animation.
  // Each entry is an array of [h0, h1] pairs (one per line segment).
  const outlineArcRef = useRef<Array<Array<[number, number]>>>([]);
  const outlineGroupRef = useRef<THREE.Group>(new THREE.Group());
  outlineGroupRef.current.name = "__outlineGroup";

  // Imperative Three.js mutations: color remap, contour-based outline, relief scaling.
  // Colors stay fully visible — contour lines from backend OpenCV mark the selected region.
  const colorContours = useConverterStore((s) => s.colorContours);

  useEffect(() => {
    // Clear previous outlines
    const outlineGroup = outlineGroupRef.current;
    for (const obj of outlineObjsRef.current) {
      outlineGroup.remove(obj);
      obj.geometry.dispose();
      (obj.material as THREE.Material).dispose();
    }
    outlineObjsRef.current = [];
    outlineArcRef.current = [];

    if (
      groupRef.current
      && typeof (groupRef.current as { add?: unknown }).add === "function"
      && !Array.from(groupRef.current.children).includes(outlineGroup)
    ) {
      groupRef.current.add(outlineGroup);
    }

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

    // Draw contour outlines for selected color(s) using backend-computed contours.
    // Contours are in raw world coords (mm, origin at bottom-left of image).
    // The GLB model is centered by subtracting sceneCenter, so apply same offset.
    // - current/region: regionData.contours (single connected region)
    // - select-all: colorContours[selectedColor] (all regions of that color)
    // - multi-select: each selectedRegion's own contours (individual connected regions)
    const outlineTargets = resolveSelectionOutlineTargets({
      selectionVisualsEnabled,
      modelBounds,
      selectionMode,
      selectedColor,
      selectedColors,
      selectedRegions,
      regionData,
      colorContours,
    });

    const offsetX = -sceneCenter.x;
    const offsetY = -sceneCenter.y;

    for (const { hex, polygons } of outlineTargets) {
      const colorTopZ = spacerThick + COLOR_LAYER_HEIGHT + 0.1;
      const topZ = enableRelief
        ? spacerThick + (colorHeightMap[hex] ?? COLOR_LAYER_HEIGHT) + 0.1
        : colorTopZ;

      for (const polygon of polygons) {
        if (polygon.length < 3) continue;
        const verts: number[] = [];
        const cumLen: number[] = [0];
        for (let i = 0; i < polygon.length; i++) {
          const [x0, y0] = polygon[i];
          const [x1, y1] = polygon[(i + 1) % polygon.length];
          const dx = x1 - x0;
          const dy = y1 - y0;
          cumLen.push(cumLen[cumLen.length - 1] + Math.sqrt(dx * dx + dy * dy));
        }
        const totalLen = cumLen[cumLen.length - 1] || 1;

        const arcPairs: Array<[number, number]> = [];
        for (let i = 0; i < polygon.length; i++) {
          const [x0, y0] = polygon[i];
          const [x1, y1] = polygon[(i + 1) % polygon.length];
          verts.push(
            x0 + offsetX, y0 + offsetY, topZ,
            x1 + offsetX, y1 + offsetY, topZ,
          );
          arcPairs.push([cumLen[i] / totalLen, cumLen[i + 1] / totalLen]);
        }

        const colorArr = new Float32Array(arcPairs.length * 6);
        const lineGeo = new THREE.BufferGeometry();
        lineGeo.setAttribute(
          "position",
          new THREE.Float32BufferAttribute(verts, 3),
        );
        lineGeo.setAttribute(
          "color",
          new THREE.BufferAttribute(colorArr, 3),
        );
        const lineMat = new THREE.LineBasicMaterial({
          vertexColors: true,
          linewidth: 3,
          depthTest: false,
        });
        const line = new THREE.LineSegments(lineGeo, lineMat);
        line.renderOrder = 999;
        outlineGroup.add(line);
        outlineObjsRef.current.push(line);
        outlineArcRef.current.push(arcPairs);
      }
    }
  }, [colorMeshes, mirrorMeshes, colorRemapMap, colorHeightMap, selectedColor, selectedColors, selectedRegions, enableRelief, baseHeight, colorContours, modelBounds, sceneCenter, spacerThick, isDoubleSided, backingMesh, backingPlateMesh, regionData, selectionMode, selectionVisualsEnabled]);

  // Flowing RGB animation with flash-on-select and brightness pulse.
  const tmpColorAnim = useRef(new THREE.Color());
  const outlineBirthTime = useRef(0);
  useFrame(() => {
    const lines = outlineObjsRef.current;
    const arcs = outlineArcRef.current;
    if (lines.length === 0) {
      outlineBirthTime.current = 0;
      return;
    }

    const now = performance.now();
    if (outlineBirthTime.current === 0) outlineBirthTime.current = now;
    const age = now - outlineBirthTime.current;

    // Flash twice on first appearance (0-700ms), then gentle pulse
    let lightness: number;
    if (age < 700) {
      const phase = (age / 175) * Math.PI;
      lightness = 0.35 + 0.4 * Math.abs(Math.sin(phase));
    } else {
      lightness = 0.45 + 0.1 * Math.sin(now * 0.005);
    }

    const time = now * 0.001;
    const c = tmpColorAnim.current;
    for (let li = 0; li < lines.length; li++) {
      const colorAttr = lines[li].geometry.getAttribute("color") as THREE.BufferAttribute;
      const arr = colorAttr.array as Float32Array;
      const pairs = arcs[li];
      if (!pairs) continue;

      for (let si = 0; si < pairs.length; si++) {
        const [t0, t1] = pairs[si];
        const idx = si * 6;
        c.setHSL((t0 + time) % 1.0, 1.0, lightness);
        arr[idx] = c.r; arr[idx + 1] = c.g; arr[idx + 2] = c.b;
        c.setHSL((t1 + time) % 1.0, 1.0, lightness);
        arr[idx + 3] = c.r; arr[idx + 4] = c.g; arr[idx + 5] = c.b;
      }
      colorAttr.needsUpdate = true;
    }
  });

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      for (const obj of outlineObjsRef.current) {
        obj.geometry.dispose();
        (obj.material as THREE.Material).dispose();
      }
      outlineObjsRef.current = [];
    };
  }, []);

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
        modelMaxZ={modelBounds?.maxZ ?? 0}
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
