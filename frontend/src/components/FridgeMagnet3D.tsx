/* eslint-disable react-refresh/only-export-components */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useThree, type ThreeEvent } from "@react-three/fiber";
import * as THREE from "three";
import type { FridgeMagnetItem } from "../api/types";
import { FRIDGE_MAGNET_SPACER_CLEARANCE_MM } from "../constants/fridgeMagnets";

const SHARED_RAYCASTER = new THREE.Raycaster();
const SHARED_POINTER = new THREE.Vector2();

const ROUND_SEGMENTS = 72;
const EDGE_THRESHOLD_DEGREES = 24;
const PROXY_FILL_RENDER_ORDER = 1000;
const PROXY_EDGE_RENDER_ORDER = 1001;

const PROXY_VISUALS = {
  default: {
    fillColor: "#94a3b8",
    fillOpacity: 0.14,
    wireColor: "#cbd5e1",
    wireOpacity: 0.45,
  },
  hover: {
    fillColor: "#7dd3fc",
    fillOpacity: 0.2,
    wireColor: "#e0f2fe",
    wireOpacity: 0.6,
  },
  selected: {
    fillColor: "#38bdf8",
    fillOpacity: 0.28,
    wireColor: "#f0f9ff",
    wireOpacity: 0.95,
  },
  dragging: {
    fillColor: "#0ea5e9",
    fillOpacity: 0.34,
    wireColor: "#f8fafc",
    wireOpacity: 1,
  },
} as const;

export interface FridgeMagnetModelBounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
  maxZ: number;
}

export interface FridgeMagnet3DProps {
  enabled: boolean;
  modelBounds: FridgeMagnetModelBounds | null;
  magnets: FridgeMagnetItem[];
  scaleX: number;
  scaleY: number;
  selectedMagnetId: string | null;
  onSelectMagnet: (id: string | null) => void;
  onUpdateMagnetCenter: (id: string, centerX: number, centerY: number) => void;
}

interface ProxyDimensions {
  width: number;
  height: number;
  thickness: number;
  rotation: [number, number, number];
  geometry: "box" | "cylinder";
}

function clampToRange(value: number, min: number, max: number): number {
  if (min > max) {
    return (min + max) / 2;
  }
  return Math.min(Math.max(value, min), max);
}

export function clampFridgeMagnetCenter(
  centerX: number,
  centerY: number,
  modelBounds: Pick<FridgeMagnetModelBounds, "minX" | "maxX" | "minY" | "maxY">,
  dimensions?: Pick<ProxyDimensions, "width" | "height"> | null,
): { x: number; y: number } {
  const halfWidth = (dimensions?.width ?? 0) / 2;
  const halfHeight = (dimensions?.height ?? 0) / 2;

  return {
    x: clampToRange(centerX, modelBounds.minX + halfWidth, modelBounds.maxX - halfWidth),
    y: clampToRange(centerY, modelBounds.minY + halfHeight, modelBounds.maxY - halfHeight),
  };
}

export function getFridgeMagnetProxyDimensions(
  magnet: FridgeMagnetItem,
): ProxyDimensions | null {
  if (magnet.shape === "round") {
    const diameter = magnet.diameter_mm ?? 0;
    if (diameter <= 0 || magnet.thickness_mm <= 0) {
      return null;
    }

    return {
      width: diameter,
      height: diameter,
      thickness: magnet.thickness_mm,
      rotation: [Math.PI / 2, 0, 0],
      geometry: "cylinder",
    };
  }

  const width = magnet.width_mm ?? 0;
  const height = magnet.height_mm ?? 0;
  if (width <= 0 || height <= 0 || magnet.thickness_mm <= 0) {
    return null;
  }

  return {
    width,
    height,
    thickness: magnet.thickness_mm,
    rotation: [0, 0, 0],
    geometry: "box",
  };
}

export function createFridgeMagnetProxyGeometry(
  magnet: FridgeMagnetItem,
): THREE.BufferGeometry | null {
  const dimensions = getFridgeMagnetProxyDimensions(magnet);
  if (!dimensions) {
    return null;
  }

  return dimensions.geometry === "cylinder"
    ? new THREE.CylinderGeometry(
        dimensions.width / 2,
        dimensions.width / 2,
        dimensions.thickness,
        ROUND_SEGMENTS,
      )
    : new THREE.BoxGeometry(dimensions.width, dimensions.height, dimensions.thickness);
}

export function createFridgeMagnetProxyEdgeGeometry(
  geometry: THREE.BufferGeometry,
): THREE.EdgesGeometry {
  return new THREE.EdgesGeometry(geometry, EDGE_THRESHOLD_DEGREES);
}

export function getFridgeMagnetGeometryKey(
  magnet: FridgeMagnetItem,
): string {
  return [
    magnet.shape,
    magnet.diameter_mm ?? "",
    magnet.width_mm ?? "",
    magnet.height_mm ?? "",
    magnet.thickness_mm,
  ].join(":");
}

export function getFridgeMagnetProxyPosition(
  magnet: FridgeMagnetItem,
  scaleX = 1,
  scaleY = 1,
): [number, number, number] | null {
  const dimensions = getFridgeMagnetProxyDimensions(magnet);
  if (!dimensions) {
    return null;
  }

  return [
    magnet.center_x_mm * scaleX,
    magnet.center_y_mm * scaleY,
    FRIDGE_MAGNET_SPACER_CLEARANCE_MM + dimensions.thickness / 2,
  ];
}

export function getInitialDragPoint(
  event: ThreeEvent<PointerEvent>,
  fallbackX: number,
  fallbackY: number,
  plane: THREE.Plane,
  target: THREE.Vector3,
): THREE.Vector3 {
  if (event.ray?.intersectPlane(plane, target)) {
    return target;
  }

  target.set(fallbackX, fallbackY, 0);
  return target;
}

function FridgeMagnetProxy({
  magnet,
  modelBounds,
  scaleX,
  scaleY,
  isSelected,
  onSelectMagnet,
  onUpdateMagnetCenter,
}: {
  magnet: FridgeMagnetItem;
  modelBounds: FridgeMagnetModelBounds;
  scaleX: number;
  scaleY: number;
  isSelected: boolean;
  onSelectMagnet: (id: string | null) => void;
  onUpdateMagnetCenter: (id: string, centerX: number, centerY: number) => void;
}) {
  const { controls, camera, gl } = useThree();

  const [isHovered, setIsHovered] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  const dragPlane = useRef(new THREE.Plane(new THREE.Vector3(0, 0, 1), 0));
  const dragStartWorld = useRef(new THREE.Vector3());
  const dragStartCenter = useRef({ x: magnet.center_x_mm, y: magnet.center_y_mm });
  const dragIntersect = useRef(new THREE.Vector3());
  const isDraggingRef = useRef(false);
  const isHoveredRef = useRef(false);

  // Depend only on dimension-defining fields so drag-time center updates do not
  // recreate geometry and accidentally tear down pointer interaction state.
  const dimensions = useMemo(
    () => getFridgeMagnetProxyDimensions(magnet),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      magnet.shape,
      magnet.diameter_mm,
      magnet.width_mm,
      magnet.height_mm,
      magnet.thickness_mm,
    ],
  );
  const geometry = useMemo(() => {
    if (!dimensions) {
      return null;
    }

    return dimensions.geometry === "cylinder"
      ? new THREE.CylinderGeometry(
          dimensions.width / 2,
          dimensions.width / 2,
          dimensions.thickness,
          ROUND_SEGMENTS,
        )
      : new THREE.BoxGeometry(dimensions.width, dimensions.height, dimensions.thickness);
  }, [dimensions]);
  const edgeGeometry = useMemo(() => {
    if (!geometry) {
      return null;
    }

    return createFridgeMagnetProxyEdgeGeometry(geometry);
  }, [geometry]);

  useEffect(() => () => geometry?.dispose(), [geometry]);
  useEffect(() => () => edgeGeometry?.dispose(), [edgeGeometry]);

  const position = useMemo(
    () => getFridgeMagnetProxyPosition(magnet, scaleX, scaleY),
    [magnet, scaleX, scaleY],
  );

  const visual = isDragging
    ? PROXY_VISUALS.dragging
    : isSelected
      ? PROXY_VISUALS.selected
      : isHovered
        ? PROXY_VISUALS.hover
        : PROXY_VISUALS.default;

  const setControlsEnabled = useCallback(
    (enabled: boolean) => {
      if (controls) {
        (controls as unknown as { enabled: boolean }).enabled = enabled;
      }
    },
    [controls],
  );

  const syncIdleCursor = useCallback(() => {
    document.body.style.cursor = isHoveredRef.current ? "grab" : "default";
  }, []);

  const resetInteractionCursor = useCallback(() => {
    document.body.style.cursor = "default";
  }, []);

  const finishDrag = useCallback(() => {
    if (!isDraggingRef.current) {
      return;
    }

    isDraggingRef.current = false;
    setIsDragging(false);
    setControlsEnabled(true);
    syncIdleCursor();
  }, [setControlsEnabled, syncIdleCursor]);

  const handlePointerDown = useCallback(
    (event: ThreeEvent<PointerEvent>) => {
      if (event.button !== 0) {
        return;
      }
      event.stopPropagation();
      onSelectMagnet(magnet.id);
      dragStartCenter.current = {
        x: magnet.center_x_mm,
        y: magnet.center_y_mm,
      };
      getInitialDragPoint(
        event,
        magnet.center_x_mm * scaleX,
        magnet.center_y_mm * scaleY,
        dragPlane.current,
        dragStartWorld.current,
      );
      isDraggingRef.current = true;
      setIsDragging(true);
      setControlsEnabled(false);
      document.body.style.cursor = "grabbing";
    },
    [
      magnet.center_x_mm,
      magnet.center_y_mm,
      magnet.id,
      onSelectMagnet,
      scaleX,
      scaleY,
      setControlsEnabled,
    ],
  );

  const handlePointerOver = useCallback(
    (event: ThreeEvent<PointerEvent>) => {
      event.stopPropagation();
      isHoveredRef.current = true;
      setIsHovered(true);
      if (!isDraggingRef.current) {
        document.body.style.cursor = "grab";
      }
    },
    [],
  );

  const handlePointerOut = useCallback(
    (event: ThreeEvent<PointerEvent>) => {
      event.stopPropagation();
      isHoveredRef.current = false;
      setIsHovered(false);
      if (!isDraggingRef.current) {
        document.body.style.cursor = "default";
      }
    },
    [],
  );

  useEffect(() => {
    if (!isDragging) {
      return;
    }

    const canvas = gl.domElement;

    const onPointerMove = (event: PointerEvent) => {
      if (!isDraggingRef.current) {
        return;
      }

      const rect = canvas.getBoundingClientRect();
      SHARED_POINTER.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      SHARED_POINTER.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

      SHARED_RAYCASTER.setFromCamera(SHARED_POINTER, camera);
      if (!SHARED_RAYCASTER.ray.intersectPlane(dragPlane.current, dragIntersect.current)) {
        return;
      }

      const deltaX = dragIntersect.current.x - dragStartWorld.current.x;
      const deltaY = dragIntersect.current.y - dragStartWorld.current.y;
      const nextCenter = clampFridgeMagnetCenter(
        dragStartCenter.current.x + deltaX / scaleX,
        dragStartCenter.current.y + deltaY / scaleY,
        modelBounds,
        dimensions,
      );

      onUpdateMagnetCenter(magnet.id, nextCenter.x, nextCenter.y);
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", finishDrag);
    window.addEventListener("pointercancel", finishDrag);
    window.addEventListener("blur", finishDrag);

    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", finishDrag);
      window.removeEventListener("pointercancel", finishDrag);
      window.removeEventListener("blur", finishDrag);
      finishDrag();
    };
  }, [
    camera,
    dimensions,
    finishDrag,
    gl,
    isDragging,
    magnet.id,
    modelBounds,
    onUpdateMagnetCenter,
    scaleX,
    scaleY,
  ]);

  useEffect(() => {
    return () => {
      isDraggingRef.current = false;
      isHoveredRef.current = false;
      setControlsEnabled(true);
      resetInteractionCursor();
    };
  }, [resetInteractionCursor, setControlsEnabled]);

  if (!dimensions || !geometry || !edgeGeometry || !position) {
    return null;
  }

  return (
    <group
      name={`fridge-magnet-proxy-${magnet.id}`}
      position={position}
      onPointerDown={handlePointerDown}
      onPointerOver={handlePointerOver}
      onPointerOut={handlePointerOut}
    >
      <mesh rotation={dimensions.rotation} geometry={geometry} renderOrder={PROXY_FILL_RENDER_ORDER}>
        <meshBasicMaterial
          color={visual.fillColor}
          opacity={visual.fillOpacity + (isSelected ? 0.02 : 0)}
          transparent={true}
          depthTest={false}
          depthWrite={false}
          toneMapped={false}
        />
      </mesh>
      <lineSegments
        rotation={dimensions.rotation}
        geometry={edgeGeometry}
        renderOrder={PROXY_EDGE_RENDER_ORDER}
      >
        <lineBasicMaterial
          color={visual.wireColor}
          opacity={visual.wireOpacity}
          transparent={true}
          depthTest={false}
          depthWrite={false}
          toneMapped={false}
        />
      </lineSegments>
    </group>
  );
}

function FridgeMagnet3D({
  enabled,
  modelBounds,
  magnets,
  scaleX,
  scaleY,
  selectedMagnetId,
  onSelectMagnet,
  onUpdateMagnetCenter,
}: FridgeMagnet3DProps) {
  if (!enabled || !modelBounds || magnets.length === 0) {
    return null;
  }

  return (
    <>
      {magnets.map((magnet) => (
        <FridgeMagnetProxy
          key={magnet.id}
          magnet={magnet}
          modelBounds={modelBounds}
          scaleX={scaleX}
          scaleY={scaleY}
          isSelected={magnet.id === selectedMagnetId}
          onSelectMagnet={onSelectMagnet}
          onUpdateMagnetCenter={onUpdateMagnetCenter}
        />
      ))}
    </>
  );
}

export default FridgeMagnet3D;
