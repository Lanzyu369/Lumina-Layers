/**
 * KeychainRing3D — 3D keychain ring preview component using Three.js ExtrudeGeometry.
 * KeychainRing3D — 使用 Three.js ExtrudeGeometry 的 3D 钥匙扣环预览组件。
 *
 * Renders a rectangle+semicircle shape with a circular hole, matching backend geometry_utils.py.
 * 渲染矩形底部+半圆顶部的形状（含圆孔），与后端 geometry_utils.py 一致。
 */

import { useMemo, useState, useRef, useCallback, useEffect } from "react";
import { useThree } from "@react-three/fiber";
import type { ThreeEvent } from "@react-three/fiber";
import * as THREE from "three";
import { useConverterStore } from "../stores/converter";
import type { PreviewSpacePoint } from "../utils/previewSpace";

/** Shared raycaster for window-level pointer tracking during drag. */
const _raycaster = new THREE.Raycaster();
const _pointer = new THREE.Vector2();

/** Default extrusion depth matching spacer_thick (mm). (默认拉伸深度，匹配 spacer_thick) */
const EXTRUDE_DEPTH = 1.2;

/** Small offset above model top (mm). (模型顶部上方的小偏移量) */
const TOP_OFFSET = 0.1;

/** Number of segments for the circular hole. (圆形孔洞的分段数) */
const HOLE_SEGMENTS = 32;
const GEOMETRY_DISPOSE_DELAY_MS = 0;
const pendingKeychainRingGeometryDisposals = new Map<
  THREE.BufferGeometry,
  ReturnType<typeof setTimeout>
>();

function cancelPendingKeychainRingGeometryDispose(
  geometry: THREE.BufferGeometry | null,
): void {
  if (!geometry) {
    return;
  }

  const timer = pendingKeychainRingGeometryDisposals.get(geometry);
  if (timer === undefined) {
    return;
  }

  clearTimeout(timer);
  pendingKeychainRingGeometryDisposals.delete(geometry);
}

function scheduleKeychainRingGeometryDispose(
  geometry: THREE.BufferGeometry | null,
): void {
  if (!geometry || pendingKeychainRingGeometryDisposals.has(geometry)) {
    return;
  }

  const timer = setTimeout(() => {
    pendingKeychainRingGeometryDisposals.delete(geometry);
    geometry.dispose();
  }, GEOMETRY_DISPOSE_DELAY_MS);
  pendingKeychainRingGeometryDisposals.set(geometry, timer);
}

export function resetKeychainRingGeometryDisposeForTests(): void {
  for (const timer of pendingKeychainRingGeometryDisposals.values()) {
    clearTimeout(timer);
  }
  pendingKeychainRingGeometryDisposals.clear();
}

export interface ContourCanvasBounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

/**
 * Map an asset-space contour point into current display millimetres.
 * 将资产空间轮廓点映射为当前显示毫米坐标。
 */
export type ContourToDisplayPoint = (point: PreviewSpacePoint) => PreviewSpacePoint;

export interface KeychainRing3DProps {
  enabled: boolean;
  cameraPanModifierActive?: boolean;
  width: number; // mm, 2-10
  length: number; // mm, 4-15
  hole: number; // mm, 1-5
  angle: number; // degrees, -180 to 180
  offsetX: number; // mm, -20 to 20
  offsetY: number; // mm, -20 to 20
  positionPreset: string; // e.g. "top-center"
  modelBounds: {
    minX: number;
    maxX: number;
    minY: number;
    maxY: number;
    maxZ: number;
  } | null;
  contours?: Record<string, number[][][]>;
  contourCanvasBounds?: ContourCanvasBounds | null;
  /** Live preview resize transform for contour points. / 轮廓点的实时预览缩放变换。 */
  contourToDisplayPoint?: ContourToDisplayPoint;
}

/**
 * Create keychain ring geometry: rectangle bottom + semicircle top with circular hole.
 * 创建钥匙扣环几何体：矩形底部 + 半圆顶部，圆孔位于半圆中心。
 *
 * Shape matches backend `create_keychain_loop()` in `core/geometry_utils.py`:
 * - Outer contour: rectangle from y=0 to y=rectHeight, semicircle arc on top
 * - Hole centered at (0, rectHeight) — the semicircle center
 * 形状与后端 geometry_utils.py 的 create_keychain_loop() 一致。
 *
 * @param width - Ring width in mm. (环宽度，毫米)
 * @param length - Ring length in mm. (环长度，毫米)
 * @param hole - Hole diameter in mm. (孔洞直径，毫米)
 * @returns ExtrudeGeometry or null if params invalid. (ExtrudeGeometry 或参数无效时返回 null)
 */
export function createKeychainRingGeometry(
  width: number,
  length: number,
  hole: number,
): THREE.ExtrudeGeometry | null {
  if (width <= 0 || length <= 0 || hole <= 0) {
    return null;
  }
  // Hole diameter must be less than min(width, length) for valid geometry
  if (hole >= Math.min(width, length)) {
    return null;
  }

  const halfW = width / 2;
  const circleRadius = halfW;
  const rectHeight = Math.max(0.2, length - circleRadius);

  // Outer contour: rectangle bottom + semicircle top
  const shape = new THREE.Shape();
  shape.moveTo(-halfW, 0);
  shape.lineTo(halfW, 0);
  shape.lineTo(halfW, rectHeight);
  // Semicircle arc from right (angle=0) to left (angle=PI)
  shape.absarc(0, rectHeight, circleRadius, 0, Math.PI, false);
  shape.lineTo(-halfW, rectHeight);
  shape.closePath();

  // Circular hole centered at semicircle center (0, rectHeight)
  const holePath = new THREE.Path();
  holePath.absarc(0, rectHeight, hole / 2, 0, Math.PI * 2, false);
  shape.holes.push(holePath);

  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: EXTRUDE_DEPTH,
    bevelEnabled: false,
    curveSegments: HOLE_SEGMENTS,
  });

  return geometry;
}

function contourTopWithinBand(
  contours: Record<string, number[][][]> | undefined,
  contourCanvasBounds: ContourCanvasBounds | null | undefined,
  centerX: number,
  contactWidth: number,
  contourToDisplayPoint?: ContourToDisplayPoint,
): number | null {
  if (!contours || !contourCanvasBounds || contactWidth <= 0) {
    return null;
  }

  const polygons = Object.values(contours).flat();
  if (
    !Number.isFinite(contourCanvasBounds.minX)
    || !Number.isFinite(contourCanvasBounds.maxX)
    || !Number.isFinite(contourCanvasBounds.minY)
    || !Number.isFinite(contourCanvasBounds.maxY)
    || contourCanvasBounds.maxX <= contourCanvasBounds.minX
    || contourCanvasBounds.maxY <= contourCanvasBounds.minY
  ) {
    return null;
  }

  // S11 emits contour points in full-canvas world-space millimetres with
  // origin (0, 0). The GLB canvas anchor is the same rectangle after the
  // viewer centers the scene, so only its world-space origin is required.
  // A live preview resize then scales that asset-space point for display.
  const mapPoint = (point: number[]) => {
    const assetPoint = {
      x: contourCanvasBounds.minX + point[0],
      y: contourCanvasBounds.minY + point[1],
    };
    return contourToDisplayPoint ? contourToDisplayPoint(assetPoint) : assetPoint;
  };
  const bandMinX = centerX - contactWidth / 2;
  const bandMaxX = centerX + contactWidth / 2;
  let topY = Number.NEGATIVE_INFINITY;

  const includePoint = (x: number, y: number) => {
    if (x >= bandMinX && x <= bandMaxX) {
      topY = Math.max(topY, y);
    }
  };

  for (const polygon of polygons) {
    if (polygon.length < 2) {
      continue;
    }
    for (let index = 0; index < polygon.length; index += 1) {
      const startPoint = polygon[index];
      const endPoint = polygon[(index + 1) % polygon.length];
      if (
        startPoint.length < 2
        || endPoint.length < 2
        || !Number.isFinite(startPoint[0])
        || !Number.isFinite(startPoint[1])
        || !Number.isFinite(endPoint[0])
        || !Number.isFinite(endPoint[1])
      ) {
        continue;
      }
      const start = mapPoint(startPoint);
      const end = mapPoint(endPoint);
      includePoint(start.x, start.y);
      includePoint(end.x, end.y);

      const deltaX = end.x - start.x;
      if (Math.abs(deltaX) <= Number.EPSILON) {
        continue;
      }
      for (const boundaryX of [bandMinX, bandMaxX]) {
        const ratio = (boundaryX - start.x) / deltaX;
        if (ratio >= 0 && ratio <= 1) {
          topY = Math.max(topY, start.y + ratio * (end.y - start.y));
        }
      }
    }
  }

  return Number.isFinite(topY) ? topY : null;
}

/**
 * Compute keychain loop position from model bounds and offset.
 * 根据模型边界和偏移量计算钥匙扣挂孔的 3D 位置。
 *
 * Anchors top-center loops to the local contour when contour data is available.
 * 有轮廓数据时，顶部居中挂环会锚定到接触带下方的局部轮廓。
 *
 * @param preset - Position preset. Local contour protection applies to top-center.
 *   (位置预设；局部轮廓保护用于顶部居中)
 * @param modelBounds - Model bounding box in mm. (模型包围盒，毫米)
 * @param offsetX - X offset in mm. (X 偏移量，毫米)
 * @param offsetY - Y offset in mm. (Y 偏移量，毫米)
 * @param contourToDisplayPoint - Optional live resize transform applied to
 *   contour points; modelBounds must already be in display space.
 *   (可选的实时缩放变换，作用于轮廓点；modelBounds 需已为显示空间)
 * @returns Computed {x, y} position in mm. (计算后的 {x, y} 位置，毫米)
 */
export function computeLoopPosition(
  preset: string,
  modelBounds: { minX: number; maxX: number; minY: number; maxY: number },
  offsetX: number,
  offsetY: number,
  contours?: Record<string, number[][][]>,
  contactWidth = 0,
  contourCanvasBounds?: ContourCanvasBounds | null,
  contourToDisplayPoint?: ContourToDisplayPoint,
): { x: number; y: number } {
  return computeLoopPlacement(
    preset,
    modelBounds,
    offsetX,
    offsetY,
    contours,
    contactWidth,
    contourCanvasBounds,
    contourToDisplayPoint,
  ).position;
}

function computeLoopPlacement(
  preset: string,
  modelBounds: { minX: number; maxX: number; minY: number; maxY: number },
  offsetX: number,
  offsetY: number,
  contours: Record<string, number[][][]> | undefined,
  contactWidth: number,
  contourCanvasBounds: ContourCanvasBounds | null | undefined,
  contourToDisplayPoint?: ContourToDisplayPoint,
): { position: { x: number; y: number }; usesLocalContour: boolean } {
  const baseX = (modelBounds.minX + modelBounds.maxX) / 2;
  const x = baseX + offsetX;
  const localTop = preset === "top-center"
    ? contourTopWithinBand(
      contours,
      contourCanvasBounds,
      x,
      contactWidth,
      contourToDisplayPoint,
    )
    : null;
  if (localTop !== null) {
    return {
      position: { x, y: localTop + Math.max(0, offsetY) },
      usesLocalContour: true,
    };
  }

  return {
    position: { x, y: modelBounds.maxY + offsetY },
    usesLocalContour: false,
  };
}

/** Visual feedback constants for drag interaction states. (拖拽交互状态的视觉反馈常量) */
const DRAG_VISUAL = {
  default: { color: "#888888", opacity: 0.6 },
  hover: { color: "#aaaaff", opacity: 0.8 },
  dragging: { color: "#6666ff", opacity: 0.9 },
} as const;

/** Offset clamp range in mm — covers full bed travel. (偏移量限制范围，覆盖整个热床) */
const OFFSET_CLAMP = 200;

function KeychainRing3D({
  enabled,
  cameraPanModifierActive = false,
  width,
  length,
  hole,
  angle,
  offsetX,
  offsetY,
  positionPreset,
  modelBounds,
  contours,
  contourCanvasBounds,
  contourToDisplayPoint,
}: KeychainRing3DProps) {
  const { controls, camera, gl } = useThree();

  const [isDragging, setIsDragging] = useState(false);
  const [isHovered, setIsHovered] = useState(false);

  // Refs for drag calculation
  const dragPlane = useRef(new THREE.Plane(new THREE.Vector3(0, 0, 1), 0));
  const dragStartWorld = useRef(new THREE.Vector3());
  const dragStartOffset = useRef({ x: 0, y: 0 });
  const intersectPoint = useRef(new THREE.Vector3());
  const isDraggingRef = useRef(false);
  const isHoveredRef = useRef(false);

  // Store setters
  const setLoopOffsetX = useConverterStore((s) => s.setLoopOffsetX);
  const setLoopOffsetY = useConverterStore((s) => s.setLoopOffsetY);
  const shouldRenderGeometry = enabled && modelBounds !== null;

  // Memoize geometry — only regenerate when width/length/hole change (Req 6.1)
  const geometry = useMemo(
    () => (shouldRenderGeometry ? createKeychainRingGeometry(width, length, hole) : null),
    [shouldRenderGeometry, width, length, hole],
  );

  useEffect(() => {
    cancelPendingKeychainRingGeometryDispose(geometry);
    return () => {
      scheduleKeychainRingGeometryDispose(geometry);
    };
  }, [geometry]);

  // Memoize position — recompute when preset/offset/bounds change (Req 2.2, 3.4)
  const placement = useMemo(() => {
    if (!modelBounds) return null;
    return computeLoopPlacement(
      positionPreset,
      modelBounds,
      offsetX,
      offsetY,
      Math.abs(angle) <= 1e-9 ? contours : undefined,
      width,
      contourCanvasBounds,
      contourToDisplayPoint,
    );
  }, [
    positionPreset,
    modelBounds,
    offsetX,
    offsetY,
    angle,
    contours,
    width,
    contourCanvasBounds,
    contourToDisplayPoint,
  ]);
  const position = placement?.position ?? null;
  const constrainToLocalContour = placement?.usesLocalContour ?? false;

  useEffect(() => {
    if (enabled && constrainToLocalContour && offsetY < 0) {
      setLoopOffsetY(0);
    }
  }, [enabled, constrainToLocalContour, offsetY, setLoopOffsetY]);

  // Memoize rotation in radians (Req 1.2)
  const angleRad = useMemo(() => angle * (Math.PI / 180), [angle]);

  // Clamp helper
  const clamp = useCallback(
    (v: number) => Math.max(-OFFSET_CLAMP, Math.min(OFFSET_CLAMP, v)),
    [],
  );

  const setControlsEnabled = useCallback(
    (nextEnabled: boolean) => {
      if (controls) {
        (controls as unknown as { enabled: boolean }).enabled = nextEnabled;
      }
    },
    [controls],
  );

  const restoreInteractionState = useCallback(() => {
    isDraggingRef.current = false;
    isHoveredRef.current = false;
    setControlsEnabled(true);
    document.body.style.cursor = "default";
  }, [setControlsEnabled]);

  // --- Drag handlers (Req 7.1–7.6) ---
  // Uses window-level pointermove/pointerup to prevent losing grip on fast drag.
  // 使用 window 级别的 pointermove/pointerup 防止快速拖拽时丢失跟踪。

  const handlePointerDown = useCallback(
    (e: ThreeEvent<PointerEvent>) => {
      if (cameraPanModifierActive || e.button !== 0) {
        return;
      }
      e.stopPropagation();
      setIsDragging(true);
      isDraggingRef.current = true;

      // Record the world-space click position on the XY plane
      e.ray.intersectPlane(dragPlane.current, dragStartWorld.current);
      dragStartOffset.current = { x: offsetX, y: offsetY };

      // Disable OrbitControls during drag (Req 7.3)
      setControlsEnabled(false);
      document.body.style.cursor = "grabbing";
    },
    [cameraPanModifierActive, offsetX, offsetY, setControlsEnabled],
  );

  // Window-level pointermove + pointerup during drag — never loses tracking.
  // 拖拽期间使用 window 级别事件监听，鼠标移出 mesh 也不会丢失。
  useEffect(() => {
    if (!isDragging) return;

    const canvas = gl.domElement;

    const onPointerMove = (e: PointerEvent) => {
      if (!isDraggingRef.current) return;

      // Convert screen coords to normalized device coordinates
      const rect = canvas.getBoundingClientRect();
      _pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      _pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

      // Build ray from camera through pointer
      _raycaster.setFromCamera(_pointer, camera);
      _raycaster.ray.intersectPlane(dragPlane.current, intersectPoint.current);

      const deltaX = intersectPoint.current.x - dragStartWorld.current.x;
      const deltaY = intersectPoint.current.y - dragStartWorld.current.y;

      const newOffsetX = clamp(dragStartOffset.current.x + deltaX);
      const requestedOffsetY = clamp(dragStartOffset.current.y + deltaY);
      const newOffsetY = constrainToLocalContour
        ? Math.max(0, requestedOffsetY)
        : requestedOffsetY;

      setLoopOffsetX(newOffsetX);
      setLoopOffsetY(newOffsetY);
    };

    const onPointerUp = () => {
      if (!isDraggingRef.current) return;
      isDraggingRef.current = false;
      setIsDragging(false);

      // Restore OrbitControls (Req 7.5)
      setControlsEnabled(true);
      document.body.style.cursor = isHovered ? "grab" : "default";
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
    };
  }, [
    isDragging,
    camera,
    gl,
    isHovered,
    clamp,
    constrainToLocalContour,
    setControlsEnabled,
    setLoopOffsetX,
    setLoopOffsetY,
  ]);

  // --- Hover handlers (Req 7.7) ---

  const handlePointerOver = useCallback(
    (e: ThreeEvent<PointerEvent>) => {
      e.stopPropagation();
      isHoveredRef.current = true;
      setIsHovered(true);
      if (!isDragging) {
        document.body.style.cursor = "grab";
      }
    },
    [isDragging],
  );

  const handlePointerOut = useCallback(
    (e: ThreeEvent<PointerEvent>) => {
      e.stopPropagation();
      isHoveredRef.current = false;
      setIsHovered(false);
      if (!isDragging) {
        document.body.style.cursor = "default";
      }
    },
    [isDragging],
  );

  // Determine visual state
  const visual = isDragging
    ? DRAG_VISUAL.dragging
    : isHovered
      ? DRAG_VISUAL.hover
      : DRAG_VISUAL.default;

  const canRenderRing = Boolean(enabled && geometry && modelBounds && position);

  useEffect(() => {
    if (canRenderRing || (!isDragging && !isHovered)) {
      return;
    }

    if (isDragging) {
      setIsDragging(false);
    }
    if (isHovered) {
      setIsHovered(false);
    }
    restoreInteractionState();
  }, [canRenderRing, isDragging, isHovered, restoreInteractionState]);

  useEffect(() => {
    return () => {
      if (!isDraggingRef.current && !isHoveredRef.current) {
        return;
      }

      restoreInteractionState();
    };
  }, [restoreInteractionState]);

  // Return null when modelBounds is null (Req 6.2) or params invalid (Req 6.3)
  if (!enabled || !geometry || !modelBounds || !position) {
    return null;
  }

  const posX = position.x;
  const posY = position.y + TOP_OFFSET;
  const posZ = 0;

  return (
    <mesh
      geometry={geometry}
      position={[posX, posY, posZ]}
      rotation={[0, 0, angleRad]}
      onPointerDown={handlePointerDown}
      onPointerOver={handlePointerOver}
      onPointerOut={handlePointerOut}
    >
      <meshStandardMaterial
        color={visual.color}
        opacity={visual.opacity}
        transparent={true}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

export default KeychainRing3D;
