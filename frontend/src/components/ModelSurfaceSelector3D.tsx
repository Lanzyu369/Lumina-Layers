import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useThree } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import { OBJLoader } from "three/examples/jsm/loaders/OBJLoader.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { toCreasedNormals } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import * as THREE from "three";
import { useI18n } from "../i18n/context";
import type { ModelSurfaceCandidate } from "../api/types";
import { useSettingsStore } from "../stores/settingsStore";
import type { ModelSurfaceModelRotation, ModelSurfacePlacement } from "../stores/converter";
import { disposeMaterial, disposeObjectTree } from "../utils/threeDisposal";
import { useThemeConfig } from "../hooks/useThemeConfig";
import { computeFitDistance } from "./ModelViewer";
import {
  computeArtworkCanvasTransform,
  computeArtworkPlacementDrawSize,
  computeArtworkPlacementDrawSizeMm,
  computeArtworkPlacementDragUpdate,
  computeSurfaceArtworkCanvasSize,
  computeSurfaceArtworkPreviewBudget,
  computeSurfacePreviewOffsetMm,
  getSurfaceCenterLocal,
  type Numeric2,
  type SurfaceArtworkPreviewBudget,
} from "./modelSurface/artworkPlacement";
import {
  getViewCubeDiagonalDirection,
  type ViewDirection,
} from "./modelSurface/viewCube";
import {
  ROTATION_COARSE_SNAP_REGIONS,
  ROTATION_GRABBER_OFFSET,
  ROTATION_RING_CONFIG,
  ROTATION_SCALE_LONG_EVERY,
  ROTATION_SCALE_LONG_TOOTH,
  ROTATION_SCALE_STEPS,
  ROTATION_SNAP_DEGREES,
  computeModelRotationDragDegrees,
  ensureCameraDepthClipping,
  findNearestRotationAxisScreenHit,
  getModelRotationValue,
  getModelRotationWithSurfaceFacingUp,
  getPointerRayFromScreenPoint,
  getReadableSurfaceCameraDirection,
  getReadableSurfaceCameraUp,
  getRotationGizmoRadius,
  getRotationHitTargetTubeRadius,
  getRotationPlaneFrame,
  getRotationPointerResultFromPointOrRay,
  getSurfaceFocusRadius,
  inverseRotateModelPointAroundPivot,
  isSameSurfaceModelRotation,
  modelRotationToDegrees,
  modelRotationToSurfaceModelRotation,
  rotateModelPointAroundPivot,
  setRotationAxisDegrees,
  snapDegrees,
  toModelEuler,
  type ModelRotation,
  type RotationAxis,
  type ScreenPoint,
  type ScreenRect,
} from "./modelSurface/rotationMath";
import {
  CanvasOverlayHtml,
} from "./modelSurface/overlayLayout";
import {
  ModelSurfaceToolbar,
  type SurfaceSelectionMode,
  type SurfaceTool,
  type ViewDisplayOptions,
} from "./modelSurface/ModelSurfaceToolbar";
import { ModelViewNavigator } from "./modelSurface/ModelViewNavigator";
import WikiTooltip from "./ui/WikiTooltip";

export {
  computeArtworkCoverDrawSize,
  computeArtworkPlacementDragUpdate,
  computeSurfaceArtworkCanvasSize,
  computeSurfaceArtworkPreviewBudget,
  computeSurfacePreviewOffsetMm,
} from "./modelSurface/artworkPlacement";
export {
  getViewCubeCameraTransform,
  getViewCubeCornerHitZones,
  getViewCubeEdgeHitZones,
  getViewCubeFaceHitZones,
} from "./modelSurface/viewCube";
export {
  computeModelRotationDragDegrees,
  ensureCameraDepthClipping,
  findNearestRotationAxisScreenHit,
  getReadableSurfaceCameraDirection,
  getReadableSurfaceCameraUp,
  getRotationGizmoRadius,
  getRotationHitTargetTubeRadius,
  getRotationPointerResultFromPointOrRay,
  getSurfaceFocusRadius,
  rotateModelPointAroundPivot,
} from "./modelSurface/rotationMath";

interface ModelSurfaceSelector3DProps {
  file: File;
  artworkUrl?: string | null;
  footprint?: SurfaceFootprintPayload | null;
  surfaceCandidates?: ModelSurfaceCandidate[];
  placement?: ModelSurfacePlacement;
  bedGridVisible?: boolean;
  selectionReady: boolean;
  selecting: boolean;
  onSelectFace: (faceIndex: number, candidateId?: string) => void;
  onUpdatePlacement?: (updates: Partial<ModelSurfacePlacement>) => void;
  onUpdateModelRotation?: (rotation: ModelSurfaceModelRotation) => void;
  onFitArtwork?: () => void;
  onBedGridVisibleChange?: (visible: boolean) => void;
}

type LoadedSurfaceModel =
  | {
      kind: "stl";
      geometry: THREE.BufferGeometry;
      offset: THREE.Vector3;
    }
  | {
      kind: "object";
      object: THREE.Group;
      offset: THREE.Vector3;
    };

interface CachedStlPreviewModel {
  geometry: THREE.BufferGeometry;
  offset: THREE.Vector3;
}

type Numeric3 = [number, number, number];
interface SurfaceFramePayload {
  origin: Numeric3;
  normal: Numeric3;
  u_axis: Numeric3;
  v_axis: Numeric3;
}

export interface SurfaceFootprintPayload {
  frame?: SurfaceFramePayload;
  bounds_min?: Numeric2;
  bounds_max?: Numeric2;
  bounds_width_mm?: number;
  bounds_height_mm?: number;
  outer?: Numeric2[];
  holes?: Numeric2[][];
}

interface ResolvedSurfaceFootprint {
  frame: {
    origin: THREE.Vector3;
    normal: THREE.Vector3;
    uAxis: THREE.Vector3;
    vAxis: THREE.Vector3;
  };
  boundsMin: Numeric2;
  boundsMax: Numeric2;
  widthMm: number;
  heightMm: number;
  outer: Numeric2[];
  holes: Numeric2[][];
}

interface ResolvedSurfaceCandidate {
  id: string;
  faceIndex: number;
  faceCount: number;
  areaMm2: number;
  surface: ResolvedSurfaceFootprint;
}

interface SurfacePointerEvent {
  stopPropagation: () => void;
  point?: THREE.Vector3;
  pointerId?: number;
  clientX?: number;
  clientY?: number;
  nativeEvent?: {
    point?: THREE.Vector3;
  };
  target?: {
    setPointerCapture?: (pointerId: number) => void;
    releasePointerCapture?: (pointerId: number) => void;
  };
}

interface ModelRotatePointerEvent {
  stopPropagation: () => void;
  point?: THREE.Vector3;
  ray?: THREE.Ray;
  clientX?: number;
  clientY?: number;
  pointerId?: number;
  faceIndex?: number;
  nativeEvent?: {
    faceIndex?: number;
    point?: THREE.Vector3;
    ray?: THREE.Ray;
  };
  target?: {
    setPointerCapture?: (pointerId: number) => void;
    releasePointerCapture?: (pointerId: number) => void;
  };
}

interface DragState {
  tool: "move" | "rotate" | "scale";
  startPoint: Numeric2;
  startPlacement: ModelSurfacePlacement;
}

type ModelRotationDegrees = Record<RotationAxis, number>;
interface ModelRotationDragState {
  axis: RotationAxis;
  startClientX: number;
  startClientY: number;
  startRotation: ModelRotation;
  startPointerDegrees: number | null;
  center: THREE.Vector3;
  uAxis: THREE.Vector3;
  vAxis: THREE.Vector3;
  normal: THREE.Vector3;
  ringRadius: number;
}

const DEFAULT_PLACEMENT: ModelSurfacePlacement = {
  mode: "edge_to_edge",
  offset_x_mm: 0,
  offset_y_mm: 0,
  scale: 1,
  rotation_deg: 0,
  inset_mm: 0,
};

const DEFAULT_MODEL_ROTATION: ModelRotation = { x: 0, y: 0, z: 0 };
const DEFAULT_MODEL_RELATIVE_ROTATION_INPUT: ModelRotationDegrees = { x: 0, y: 0, z: 0 };
const MODEL_ROTATION_DRAG_SENSITIVITY = 0.01;
const SURFACE_EPSILON_MM = 0.035;
const TRIANGLE_HOVER_NORMAL_BIAS_MM = 0.05;
const STL_PREVIEW_CREASE_ANGLE_RADIANS = THREE.MathUtils.degToRad(35);
const SURFACE_CANDIDATE_RENDER_ORDER = 20;
const SURFACE_SELECTED_RENDER_ORDER = 30;
export const SURFACE_OVERLAY_MATERIAL_DEPTH_FLAGS = {
  depthTest: false,
  depthWrite: false,
} as const;
export const SURFACE_ARTWORK_MATERIAL_DEPTH_FLAGS = {
  depthTest: true,
  depthWrite: false,
} as const;
export const SURFACE_MARKER_MATERIAL_DEPTH_FLAGS = {
  depthTest: true,
  depthWrite: false,
} as const;
const SURFACE_CANDIDATE_MIN_AREA_RATIO = 0.01;
const SURFACE_CANDIDATE_PICK_LIMIT = 254;
const SURFACE_CANDIDATE_VISUAL_INSET_RATIO = 0.9;
const SURFACE_PICK_PLANE_TOLERANCE_MM = 1.5;
const DEFAULT_VIEW_DISPLAY: ViewDisplayOptions = {
  navigator: true,
  zoomButton: true,
  axes: true,
  gridLines: true,
  labels: true,
};
const AXIS_COLORS: Record<RotationAxis, string> = {
  x: "#f43f5e",
  y: "#65a30d",
  z: "#2563eb",
};
const ROTATION_MEASURE_COLORS = {
  light: "#475569",
  dark: "#f8fafc",
} as const;
const SELECTED_SURFACE_INSPECTION_FOV_DEGREES = 2;

type RaycastOverrideProps = { raycast?: THREE.Object3D["raycast"] };
const ENABLED_RAYCAST_PROPS: RaycastOverrideProps = {};
const DISABLED_RAYCAST_PROPS: Required<RaycastOverrideProps> = {
  raycast: () => undefined,
};

export function getModelBodyRaycastProps(activeTool: SurfaceTool): RaycastOverrideProps {
  return activeTool === "modelRotate" ? DISABLED_RAYCAST_PROPS : ENABLED_RAYCAST_PROPS;
}

function getArtworkTextureRaycastProps(activeTool: SurfaceTool): RaycastOverrideProps {
  return activeTool === "select" || activeTool === "modelRotate"
    ? DISABLED_RAYCAST_PROPS
    : ENABLED_RAYCAST_PROPS;
}

const stlPreviewModelCache = new WeakMap<File, Promise<CachedStlPreviewModel>>();

function isArtworkTransformTool(tool: SurfaceTool): boolean {
  return tool === "move" || tool === "rotate" || tool === "scale";
}

function shouldLockOrbitControls(_tool: SurfaceTool): boolean {
  return false;
}

function disposeLoadedModel(model: LoadedSurfaceModel): void {
  if (model.kind === "stl") {
    model.geometry.dispose();
    return;
  }
  disposeObjectTree(model.object);
}

export function applySurfaceMaterial(root: THREE.Object3D, material: THREE.Material): void {
  root.traverse((child) => {
    if (child instanceof THREE.Mesh) {
      disposeMaterial(child.material);
      child.material = material.clone();
      child.castShadow = false;
      child.receiveShadow = true;
    }
  });
}

export function updateSurfaceMaterialColor(
  root: THREE.Object3D,
  color: THREE.Color,
): void {
  root.traverse((child) => {
    if (!(child instanceof THREE.Mesh)) {
      return;
    }
    const materials = Array.isArray(child.material)
      ? child.material
      : [child.material];
    for (const ownedMaterial of materials) {
      if ("color" in ownedMaterial && ownedMaterial.color instanceof THREE.Color) {
        ownedMaterial.color.copy(color);
        ownedMaterial.needsUpdate = true;
      }
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

export function prepareStlPreviewGeometry(geometry: THREE.BufferGeometry): THREE.BufferGeometry {
  geometry.deleteAttribute("normal");
  const prepared = toCreasedNormals(geometry, STL_PREVIEW_CREASE_ANGLE_RADIANS);
  prepared.computeBoundingBox();
  prepared.computeBoundingSphere();
  return prepared;
}

function cloneCachedStlPreviewModel(cached: CachedStlPreviewModel): LoadedSurfaceModel {
  return {
    kind: "stl",
    geometry: cached.geometry.clone(),
    offset: cached.offset.clone(),
  };
}

function loadCachedStlPreviewModel(file: File): Promise<CachedStlPreviewModel> {
  const cached = stlPreviewModelCache.get(file);
  if (cached) {
    return cached;
  }
  const next = (async () => {
    const buffer = await file.arrayBuffer();
    const geometry = prepareStlPreviewGeometry(new STLLoader().parse(buffer));
    const offset = centerGeometry(geometry);
    return { geometry, offset };
  })().catch((error) => {
    stlPreviewModelCache.delete(file);
    throw error;
  });
  stlPreviewModelCache.set(file, next);
  return next;
}

function centerModel(root: THREE.Object3D): { group: THREE.Group; offset: THREE.Vector3 } {
  root.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(root);
  const center = new THREE.Vector3();
  box.getCenter(center);
  const offset = new THREE.Vector3(-center.x, -center.y, -box.min.z);
  const group = new THREE.Group();
  root.position.copy(offset);
  group.add(root);
  group.updateMatrixWorld(true);
  group.raycast = (raycaster, intersects) => {
    raycaster.intersectObjects(group.children, true, intersects);
  };
  return { group, offset };
}

function vectorFromTuple(values: Numeric3): THREE.Vector3 {
  return new THREE.Vector3(values[0], values[1], values[2]);
}

function normalizeVector(values: Numeric3): THREE.Vector3 | null {
  const vector = vectorFromTuple(values);
  return vector.lengthSq() > 0 ? vector.normalize() : null;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isNumeric2(value: unknown): value is Numeric2 {
  return (
    Array.isArray(value) &&
    value.length === 2 &&
    isFiniteNumber(value[0]) &&
    isFiniteNumber(value[1])
  );
}

function normalizeRing(value: unknown): Numeric2[] {
  return Array.isArray(value) ? value.filter(isNumeric2) : [];
}

function resolveSurfaceFootprint(
  footprint: SurfaceFootprintPayload | null | undefined,
): ResolvedSurfaceFootprint | null {
  if (!footprint?.frame) {
    return null;
  }
  const { frame } = footprint;
  const normal = normalizeVector(frame.normal);
  const uAxis = normalizeVector(frame.u_axis);
  const vAxis = normalizeVector(frame.v_axis);
  if (!normal || !uAxis || !vAxis) {
    return null;
  }

  const widthMm = Number(footprint.bounds_width_mm);
  const heightMm = Number(footprint.bounds_height_mm);
  if (!Number.isFinite(widthMm) || !Number.isFinite(heightMm) || widthMm <= 0 || heightMm <= 0) {
    return null;
  }
  const boundsMin = isNumeric2(footprint.bounds_min)
    ? footprint.bounds_min
    : ([-widthMm / 2, -heightMm / 2] as Numeric2);
  const boundsMax = isNumeric2(footprint.bounds_max)
    ? footprint.bounds_max
    : ([boundsMin[0] + widthMm, boundsMin[1] + heightMm] as Numeric2);

  const outer = normalizeRing(footprint.outer);
  return {
    frame: {
      origin: vectorFromTuple(frame.origin),
      normal,
      uAxis,
      vAxis,
    },
    boundsMin,
    boundsMax,
    widthMm,
    heightMm,
    outer: outer.length > 0
      ? outer
      : [
          [boundsMin[0], boundsMin[1]],
          [boundsMax[0], boundsMin[1]],
          [boundsMax[0], boundsMax[1]],
          [boundsMin[0], boundsMax[1]],
          [boundsMin[0], boundsMin[1]],
        ],
    holes: Array.isArray(footprint.holes)
      ? footprint.holes.map(normalizeRing).filter((ring) => ring.length >= 3)
      : [],
  };
}

function resolveSurfaceCandidates(
  candidates: ModelSurfaceCandidate[] | undefined,
): ResolvedSurfaceCandidate[] {
  if (!Array.isArray(candidates)) {
    return [];
  }
  return candidates
    .map((candidate) => {
      const surface = resolveSurfaceFootprint(
        candidate.footprint as SurfaceFootprintPayload | null | undefined,
      );
      if (!surface) {
        return null;
      }
      return {
        id: candidate.id,
        faceIndex: candidate.face_index,
        faceCount: candidate.face_count,
        areaMm2: candidate.area_mm2,
        surface,
      } satisfies ResolvedSurfaceCandidate;
    })
    .filter((candidate): candidate is ResolvedSurfaceCandidate => candidate !== null);
}

function filterSelectableSurfaceCandidates(
  candidates: ResolvedSurfaceCandidate[],
): ResolvedSurfaceCandidate[] {
  if (candidates.length === 0) {
    return [];
  }
  const sortByAreaDescending = (items: ResolvedSurfaceCandidate[]) =>
    [...items].sort((left, right) => right.areaMm2 - left.areaMm2);
  const maxArea = Math.max(...candidates.map((candidate) => candidate.areaMm2));
  if (!Number.isFinite(maxArea) || maxArea <= 0) {
    return sortByAreaDescending(candidates).slice(0, SURFACE_CANDIDATE_PICK_LIMIT);
  }
  const minArea = maxArea * SURFACE_CANDIDATE_MIN_AREA_RATIO;
  const filtered = candidates.filter((candidate) => candidate.areaMm2 >= minArea);
  return sortByAreaDescending(filtered.length > 0 ? filtered : candidates).slice(
    0,
    SURFACE_CANDIDATE_PICK_LIMIT,
  );
}

function getPointerFaceIndex(event: ModelRotatePointerEvent): number | null {
  if (typeof event.faceIndex === "number" && Number.isFinite(event.faceIndex)) {
    return event.faceIndex;
  }
  const nativeFaceIndex = event.nativeEvent?.faceIndex;
  return typeof nativeFaceIndex === "number" && Number.isFinite(nativeFaceIndex) ? nativeFaceIndex : null;
}

function getPointerPoint(event: ModelRotatePointerEvent): THREE.Vector3 | null {
  if (event.point instanceof THREE.Vector3) {
    return event.point;
  }
  const nativePoint = event.nativeEvent?.point;
  return nativePoint instanceof THREE.Vector3 ? nativePoint : null;
}

function getSurfacePointerPoint(event: SurfacePointerEvent): THREE.Vector3 | null {
  if (event.point instanceof THREE.Vector3) {
    return event.point;
  }
  const nativePoint = event.nativeEvent?.point;
  return nativePoint instanceof THREE.Vector3 ? nativePoint : null;
}

function getTriangleVertex(
  geometry: THREE.BufferGeometry,
  faceIndex: number,
  vertexOffset: number,
): THREE.Vector3 | null {
  const position = geometry.getAttribute("position");
  if (!position) {
    return null;
  }
  const index = geometry.getIndex();
  const triangleVertexIndex = faceIndex * 3 + vertexOffset;
  const sourceVertexIndex = index ? index.getX(triangleVertexIndex) : triangleVertexIndex;
  if (
    !Number.isInteger(sourceVertexIndex) ||
    sourceVertexIndex < 0 ||
    sourceVertexIndex >= position.count
  ) {
    return null;
  }
  return new THREE.Vector3(
    position.getX(sourceVertexIndex),
    position.getY(sourceVertexIndex),
    position.getZ(sourceVertexIndex),
  );
}

function createTriangleFacetHoverGeometries(
  geometry: THREE.BufferGeometry,
  faceIndex: number,
): { outline: THREE.BufferGeometry } | null {
  const a = getTriangleVertex(geometry, faceIndex, 0);
  const b = getTriangleVertex(geometry, faceIndex, 1);
  const c = getTriangleVertex(geometry, faceIndex, 2);
  if (!a || !b || !c) {
    return null;
  }
  const normal = new THREE.Triangle(a, b, c).getNormal(new THREE.Vector3());
  if (!Number.isFinite(normal.lengthSq()) || normal.lengthSq() <= 1e-10) {
    return null;
  }
  const bias = normal.multiplyScalar(TRIANGLE_HOVER_NORMAL_BIAS_MM);
  const vertices = [a.add(bias), b.add(bias), c.add(bias)];
  const outlinePositions = [
    ...vertices[0].toArray(), ...vertices[1].toArray(),
    ...vertices[1].toArray(), ...vertices[2].toArray(),
    ...vertices[2].toArray(), ...vertices[0].toArray(),
  ];
  const outline = new THREE.BufferGeometry();
  outline.setAttribute("position", new THREE.Float32BufferAttribute(outlinePositions, 3));

  return { outline };
}

function formatRotationTooltip(axis: RotationAxis, angleRadians: number): string {
  const degrees = THREE.MathUtils.radToDeg(angleRadians);
  return `${axis.toUpperCase()}: ${degrees.toFixed(2)}°`;
}

export function getRotationTickSegmentRadii(
  index: number,
  radius: number,
): { innerRadius: number; outerRadius: number } {
  const isLongTick = index % ROTATION_SCALE_LONG_EVERY === 0;
  return {
    innerRadius: radius,
    outerRadius: radius * (1 + (isLongTick ? 0.1 : 0.05)),
  };
}

export function insetRingTowardPoint(
  ring: Numeric2[],
  center: Numeric2,
  ratio: number,
): Numeric2[] {
  const safeRatio = Number.isFinite(ratio) ? THREE.MathUtils.clamp(ratio, 0, 1) : 1;
  return ring.map(([x, y]) => [
    center[0] + (x - center[0]) * safeRatio,
    center[1] + (y - center[1]) * safeRatio,
  ] as Numeric2);
}

function getSurfaceCandidateVisualOuterRing(surface: ResolvedSurfaceFootprint): Numeric2[] {
  return insetRingTowardPoint(
    getSurfaceOuterRing(surface),
    getSurfaceCenterLocal(surface),
    SURFACE_CANDIDATE_VISUAL_INSET_RATIO,
  );
}

function createSurfaceShape(
  surface: ResolvedSurfaceFootprint,
  outerRing = getSurfaceOuterRing(surface),
  includeHoles = true,
): THREE.Shape {
  const [centerU, centerV] = getSurfaceCenterLocal(surface);
  const shape = new THREE.Shape();

  outerRing.forEach(([x, y], index) => {
    const localX = x - centerU;
    const localY = y - centerV;
    if (index === 0) {
      shape.moveTo(localX, localY);
    } else {
      shape.lineTo(localX, localY);
    }
  });
  shape.closePath();

  if (includeHoles) {
    surface.holes.forEach((ring) => {
      if (ring.length < 3) {
        return;
      }
      const hole = new THREE.Path();
      ring.forEach(([x, y], index) => {
        const localX = x - centerU;
        const localY = y - centerV;
        if (index === 0) {
          hole.moveTo(localX, localY);
        } else {
          hole.lineTo(localX, localY);
        }
      });
      hole.closePath();
      shape.holes.push(hole);
    });
  }

  return shape;
}

export function createSurfaceHitShape(surface: ResolvedSurfaceFootprint): THREE.Shape {
  return createSurfaceShape(surface, getSurfaceOuterRing(surface), false);
}

export function createSurfaceArtworkGeometry(surface: ResolvedSurfaceFootprint): THREE.BufferGeometry {
  const [centerU, centerV] = getSurfaceCenterLocal(surface);
  const width = Math.max(surface.boundsMax[0] - surface.boundsMin[0], 1e-9);
  const height = Math.max(surface.boundsMax[1] - surface.boundsMin[1], 1e-9);
  const geometry = new THREE.ShapeGeometry(createSurfaceShape(surface));
  const position = geometry.getAttribute("position");
  const uvs: number[] = [];
  for (let index = 0; index < position.count; index += 1) {
    const surfaceU = position.getX(index) + centerU;
    const surfaceV = position.getY(index) + centerV;
    uvs.push(
      THREE.MathUtils.clamp((surfaceU - surface.boundsMin[0]) / width, 0, 1),
      THREE.MathUtils.clamp((surfaceV - surface.boundsMin[1]) / height, 0, 1),
    );
  }
  geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
  geometry.computeVertexNormals();
  return geometry;
}

export function createSurfaceArtworkInteractionGeometry(
  surface: ResolvedSurfaceFootprint,
): THREE.BufferGeometry {
  const geometry = new THREE.ShapeGeometry(
    createSurfaceShape(surface, getSurfaceOuterRing(surface), false),
  );
  geometry.computeVertexNormals();
  return geometry;
}

function getSurfaceOuterRing(surface: ResolvedSurfaceFootprint): Numeric2[] {
  return surface.outer.length >= 3
    ? surface.outer
    : [
        [surface.boundsMin[0], surface.boundsMin[1]] as Numeric2,
        [surface.boundsMax[0], surface.boundsMin[1]] as Numeric2,
        [surface.boundsMax[0], surface.boundsMax[1]] as Numeric2,
        [surface.boundsMin[0], surface.boundsMax[1]] as Numeric2,
      ];
}

function createSurfaceRingOutlineGeometry(
  ring: Numeric2[],
  centerU: number,
  centerV: number,
): THREE.BufferGeometry {
  const positions: number[] = [];
  for (let index = 0; index < ring.length; index += 1) {
    const current = ring[index];
    const next = ring[(index + 1) % ring.length];
    if (!current || !next) {
      continue;
    }
    positions.push(
      current[0] - centerU,
      current[1] - centerV,
      0,
      next[0] - centerU,
      next[1] - centerV,
      0,
    );
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  return geometry;
}

function createSurfaceOutlineGeometry(surface: ResolvedSurfaceFootprint): THREE.BufferGeometry {
  const [centerU, centerV] = getSurfaceCenterLocal(surface);
  return createSurfaceRingOutlineGeometry(getSurfaceOuterRing(surface), centerU, centerV);
}

function createCandidateSurfaceOutlineGeometry(surface: ResolvedSurfaceFootprint): THREE.BufferGeometry {
  const [centerU, centerV] = getSurfaceCenterLocal(surface);
  return createSurfaceRingOutlineGeometry(getSurfaceCandidateVisualOuterRing(surface), centerU, centerV);
}

function createSurfaceHoleOutlineGeometries(surface: ResolvedSurfaceFootprint): THREE.BufferGeometry[] {
  const [centerU, centerV] = getSurfaceCenterLocal(surface);
  return surface.holes
    .filter((ring) => ring.length >= 3)
    .map((ring) => createSurfaceRingOutlineGeometry(ring, centerU, centerV));
}

function getSurfaceNormalIndicatorDimensions(surface: ResolvedSurfaceFootprint) {
  const referenceSize = Math.min(surface.widthMm, surface.heightMm);
  const length = THREE.MathUtils.clamp(referenceSize * 0.16, 4, 18);
  return {
    baseZ: SURFACE_EPSILON_MM * 1.5,
    headLength: Math.min(length * 0.28, 4),
    headSpread: THREE.MathUtils.clamp(referenceSize * 0.03, 2.4, 5.5),
    length,
    tipRadius: THREE.MathUtils.clamp(referenceSize * 0.026, 2.8, 6.5),
  };
}

function createSurfaceNormalIndicatorGeometry(surface: ResolvedSurfaceFootprint): THREE.BufferGeometry {
  const {
    baseZ,
    headLength,
    headSpread,
    length,
  } = getSurfaceNormalIndicatorDimensions(surface);
  const tipZ = baseZ + length;
  const headBaseZ = tipZ - headLength;
  const positions = [
    0, 0, baseZ,
    0, 0, tipZ,
    0, 0, tipZ,
    headSpread, 0, headBaseZ,
    0, 0, tipZ,
    -headSpread, 0, headBaseZ,
    0, 0, tipZ,
    0, headSpread, headBaseZ,
    0, 0, tipZ,
    0, -headSpread, headBaseZ,
  ];
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  return geometry;
}

function formatCandidateArea(areaMm2: number): string {
  const safeArea = Number.isFinite(areaMm2) ? areaMm2 : 0;
  return `${safeArea.toFixed(2)} mm²`;
}

function formatSurfaceSize(surface: ResolvedSurfaceFootprint): string {
  return `${surface.widthMm.toFixed(1)} × ${surface.heightMm.toFixed(1)} mm`;
}

function formatPlacementMm(value: number): string {
  return `${value.toFixed(1)} mm`;
}

function formatPlacementDegrees(value: number): string {
  return `${value.toFixed(1)}°`;
}

function formatPlacementScale(value: number): string {
  return `${value.toFixed(2)}×`;
}

function getSurfaceDirectionLabelKey(surface: ResolvedSurfaceFootprint): string {
  const { normal } = surface.frame;
  const axisWeights = [
    { axis: "x" as const, value: normal.x },
    { axis: "y" as const, value: normal.y },
    { axis: "z" as const, value: normal.z },
  ].sort((left, right) => Math.abs(right.value) - Math.abs(left.value));
  const dominant = axisWeights[0];
  if (dominant.axis === "z") {
    return dominant.value >= 0 ? "model_surface_face_top" : "model_surface_face_bottom";
  }
  if (dominant.axis === "y") {
    return dominant.value >= 0 ? "model_surface_face_back" : "model_surface_face_front";
  }
  return dominant.value >= 0 ? "model_surface_face_right" : "model_surface_face_left";
}

function createRotationTickGeometry(radius: number): THREE.BufferGeometry {
  const positions: number[] = [];
  for (let index = 0; index < ROTATION_SCALE_STEPS; index += 1) {
    const angle = (index / ROTATION_SCALE_STEPS) * Math.PI * 2;
    const { innerRadius, outerRadius } = getRotationTickSegmentRadii(index, radius);
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    positions.push(
      innerRadius * cos,
      innerRadius * sin,
      0,
      outerRadius * cos,
      outerRadius * sin,
      0,
    );
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  return geometry;
}

function createRotationCoarseSnapGuideGeometry(radius: number): THREE.BufferGeometry {
  const positions: number[] = [];
  const innerRadius = radius / 3;
  const outerRadius = (2 * radius) / 3;
  for (let index = 0; index < ROTATION_COARSE_SNAP_REGIONS; index += 1) {
    const angle = (index / ROTATION_COARSE_SNAP_REGIONS) * Math.PI * 2;
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    positions.push(
      innerRadius * cos,
      innerRadius * sin,
      0,
      outerRadius * cos,
      outerRadius * sin,
      0,
    );
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  return geometry;
}

function appendCircleSegments(
  positions: number[],
  radius: number,
  segmentCount = ROTATION_SCALE_STEPS,
) {
  for (let index = 0; index < segmentCount; index += 1) {
    const startAngle = (index / segmentCount) * Math.PI * 2;
    const endAngle = ((index + 1) / segmentCount) * Math.PI * 2;
    positions.push(
      Math.cos(startAngle) * radius,
      Math.sin(startAngle) * radius,
      0,
      Math.cos(endAngle) * radius,
      Math.sin(endAngle) * radius,
      0,
    );
  }
}

function createRotationSnapRadiusRingGeometry(radius: number): THREE.BufferGeometry {
  const positions: number[] = [];
  appendCircleSegments(positions, radius / 3);
  appendCircleSegments(positions, (2 * radius) / 3);
  appendCircleSegments(positions, radius);
  appendCircleSegments(positions, radius * (1 + ROTATION_SCALE_LONG_TOOTH));
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  return geometry;
}

function createRotationReferenceRayGeometry(radius: number): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry();
  const outerRadius = radius * (1 + ROTATION_GRABBER_OFFSET);
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute([0, 0, 0, outerRadius, 0, 0], 3),
  );
  return geometry;
}

function createRotationConnectionGeometry(radius: number, angle: number): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry();
  const grabberRadius = radius * (1 + ROTATION_GRABBER_OFFSET);
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(
      [0, 0, 0, Math.cos(angle) * grabberRadius, Math.sin(angle) * grabberRadius, 0],
      3,
    ),
  );
  return geometry;
}

function createRotationAngleArcGeometry(radius: number, angle: number): THREE.BufferGeometry {
  const normalized = ((angle % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
  const positions: number[] = [];
  const arcRadius = radius * (1 + ROTATION_GRABBER_OFFSET);
  if (normalized > 0.0001) {
    for (let index = 0; index < 64; index += 1) {
      const startAngle = (normalized * index) / 64;
      const endAngle = (normalized * (index + 1)) / 64;
      positions.push(
        Math.cos(startAngle) * arcRadius,
        Math.sin(startAngle) * arcRadius,
        0,
        Math.cos(endAngle) * arcRadius,
        Math.sin(endAngle) * arcRadius,
        0,
      );
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  return geometry;
}

function getRotationPointerResultFromPointerEvent(
  event: ModelRotatePointerEvent,
  drag: ModelRotationDragState,
): { degrees: number; distance: number } | null {
  return getRotationPointerResultFromPointOrRay(
    event.point,
    event.ray,
    drag.center,
    drag.uAxis,
    drag.vAxis,
    drag.normal,
  );
}

function getModelBounds(model: LoadedSurfaceModel | null): { center: THREE.Vector3; radius: number } {
  if (!model) {
    return { center: new THREE.Vector3(), radius: 80 };
  }
  const box = new THREE.Box3();
  if (model.kind === "stl") {
    model.geometry.computeBoundingBox();
    const geometryBox = model.geometry.boundingBox?.clone();
    if (geometryBox) {
      geometryBox.min.add(model.offset);
      geometryBox.max.add(model.offset);
      box.copy(geometryBox);
    }
  } else {
    model.object.updateMatrixWorld(true);
    box.setFromObject(model.object);
  }
  if (box.isEmpty()) {
    return { center: new THREE.Vector3(), radius: 80 };
  }
  const center = new THREE.Vector3();
  const size = new THREE.Vector3();
  box.getCenter(center);
  box.getSize(size);
  return {
    center,
    radius: Math.max(size.x, size.y, size.z, 1) / 2,
  };
}

function getSurfaceWorldCenter(
  surface: ResolvedSurfaceFootprint,
  modelOffset: THREE.Vector3,
): THREE.Vector3 {
  const [centerU, centerV] = getSurfaceCenterLocal(surface);
  const previewOffsetMm = computeSurfacePreviewOffsetMm(surface.widthMm, surface.heightMm);
  return surface.frame.origin
    .clone()
    .add(modelOffset)
    .addScaledVector(surface.frame.uAxis, centerU)
    .addScaledVector(surface.frame.vAxis, centerV)
    .addScaledVector(surface.frame.normal, previewOffsetMm);
}

function getSurfaceQuaternion(surface: ResolvedSurfaceFootprint): THREE.Quaternion {
  const matrix = new THREE.Matrix4().makeBasis(
    surface.frame.uAxis,
    surface.frame.vAxis,
    surface.frame.normal,
  );
  return new THREE.Quaternion().setFromRotationMatrix(matrix);
}

export function pointToSurfaceLocal(
  point: THREE.Vector3,
  surface: ResolvedSurfaceFootprint,
  modelOffset: THREE.Vector3,
  modelEuler = new THREE.Euler(),
  modelPivot = new THREE.Vector3(),
): Numeric2 {
  const modelPoint = inverseRotateModelPointAroundPivot(point, modelPivot, modelEuler);
  const relative = modelPoint.clone().sub(modelOffset).sub(surface.frame.origin);
  return [
    relative.dot(surface.frame.uAxis),
    relative.dot(surface.frame.vAxis),
  ];
}

function getArtworkRotationPointerLocal(
  event: ModelRotatePointerEvent,
  surface: ResolvedSurfaceFootprint,
  modelOffset: THREE.Vector3,
  modelEuler: THREE.Euler,
  modelPivot: THREE.Vector3,
): Numeric2 | null {
  let point: THREE.Vector3 | null = null;
  const pointerRay = event.ray ?? event.nativeEvent?.ray;
  if (pointerRay) {
    const planeOrigin = rotateModelPointAroundPivot(
      surface.frame.origin.clone().add(modelOffset),
      modelPivot,
      modelEuler,
    );
    const planeNormal = surface.frame.normal.clone().applyEuler(modelEuler).normalize();
    point = pointerRay.intersectPlane(
      new THREE.Plane().setFromNormalAndCoplanarPoint(planeNormal, planeOrigin),
      new THREE.Vector3(),
    );
  }
  point ??= getSurfacePointerPoint(event);
  return point
    ? pointToSurfaceLocal(point, surface, modelOffset, modelEuler, modelPivot)
    : null;
}

function isPointOnRingSegment(point: Numeric2, start: Numeric2, end: Numeric2): boolean {
  const dx = end[0] - start[0];
  const dy = end[1] - start[1];
  const lengthSq = dx * dx + dy * dy;
  if (lengthSq <= 1e-12) {
    return Math.hypot(point[0] - start[0], point[1] - start[1]) <= 1e-6;
  }
  const t = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / lengthSq;
  if (t < -1e-6 || t > 1 + 1e-6) {
    return false;
  }
  const projectedX = start[0] + t * dx;
  const projectedY = start[1] + t * dy;
  return Math.hypot(point[0] - projectedX, point[1] - projectedY) <= 1e-6;
}

function isPointInRing(point: Numeric2, ring: Numeric2[]): boolean {
  if (ring.length < 3) {
    return false;
  }

  let inside = false;
  for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index, index += 1) {
    const currentPoint = ring[index];
    const previousPoint = ring[previous];
    if (!currentPoint || !previousPoint) {
      continue;
    }
    if (isPointOnRingSegment(point, previousPoint, currentPoint)) {
      return true;
    }
    const intersects =
      currentPoint[1] > point[1] !== previousPoint[1] > point[1] &&
      point[0] <
        ((previousPoint[0] - currentPoint[0]) * (point[1] - currentPoint[1])) /
          (previousPoint[1] - currentPoint[1]) +
          currentPoint[0];
    if (intersects) {
      inside = !inside;
    }
  }
  return inside;
}

export function findSelectableCandidateFromModelPoint(
  worldPoint: THREE.Vector3,
  candidates: ResolvedSurfaceCandidate[],
  modelOffset: THREE.Vector3,
  modelEuler: THREE.Euler,
  modelPivot = new THREE.Vector3(),
): ResolvedSurfaceCandidate | null {
  if (candidates.length === 0) {
    return null;
  }

  const modelPoint = inverseRotateModelPointAroundPivot(worldPoint, modelPivot, modelEuler);
  let bestCandidate: ResolvedSurfaceCandidate | null = null;
  let bestScore = Number.POSITIVE_INFINITY;

  for (const candidate of candidates) {
    const relative = modelPoint
      .clone()
      .sub(modelOffset)
      .sub(candidate.surface.frame.origin);
    const planeDistance = Math.abs(relative.dot(candidate.surface.frame.normal));
    if (planeDistance > SURFACE_PICK_PLANE_TOLERANCE_MM) {
      continue;
    }
    const localPoint: Numeric2 = [
      relative.dot(candidate.surface.frame.uAxis),
      relative.dot(candidate.surface.frame.vAxis),
    ];
    if (!isPointInRing(localPoint, getSurfaceOuterRing(candidate.surface))) {
      continue;
    }
    const [centerU, centerV] = getSurfaceCenterLocal(candidate.surface);
    const centerDistance = Math.hypot(localPoint[0] - centerU, localPoint[1] - centerV);
    const score = planeDistance + centerDistance * 1e-6;
    if (score < bestScore) {
      bestScore = score;
      bestCandidate = candidate;
    }
  }

  return bestCandidate;
}

export function findSelectableCandidateFromPointerRay(
  ray: THREE.Ray,
  candidates: ResolvedSurfaceCandidate[],
  modelOffset: THREE.Vector3,
  modelEuler: THREE.Euler,
  modelPivot = new THREE.Vector3(),
): ResolvedSurfaceCandidate | null {
  if (candidates.length === 0) {
    return null;
  }

  let bestCandidate: ResolvedSurfaceCandidate | null = null;
  let bestDistance = Number.POSITIVE_INFINITY;

  for (const candidate of candidates) {
    const planeOrigin = rotateModelPointAroundPivot(
      candidate.surface.frame.origin.clone().add(modelOffset),
      modelPivot,
      modelEuler,
    );
    const planeNormal = candidate.surface.frame.normal.clone().applyEuler(modelEuler).normalize();
    const intersection = ray.intersectPlane(
      new THREE.Plane().setFromNormalAndCoplanarPoint(planeNormal, planeOrigin),
      new THREE.Vector3(),
    );
    if (!intersection) {
      continue;
    }
    const mappedCandidate = findSelectableCandidateFromModelPoint(
      intersection,
      [candidate],
      modelOffset,
      modelEuler,
      modelPivot,
    );
    if (!mappedCandidate) {
      continue;
    }
    const distance = intersection.distanceTo(ray.origin);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestCandidate = mappedCandidate;
    }
  }

  return bestCandidate;
}

function drawRing(
  ctx: CanvasRenderingContext2D,
  ring: Numeric2[],
  surface: ResolvedSurfaceFootprint,
  widthPx: number,
  heightPx: number,
): void {
  const minX = surface.boundsMin[0];
  const minY = surface.boundsMin[1];
  const maxY = surface.boundsMax[1];
  const scaleX = widthPx / Math.max(surface.boundsMax[0] - minX, 1e-9);
  const scaleY = heightPx / Math.max(maxY - minY, 1e-9);
  ring.forEach(([x, y], index) => {
    const px = (x - minX) * scaleX;
    const py = (maxY - y) * scaleY;
    if (index === 0) {
      ctx.moveTo(px, py);
    } else {
      ctx.lineTo(px, py);
    }
  });
}

function drawSurfaceArtworkCanvas(
  image: HTMLImageElement,
  surface: ResolvedSurfaceFootprint,
  placement: ModelSurfacePlacement,
  budget: SurfaceArtworkPreviewBudget,
  targetCanvas?: HTMLCanvasElement,
): HTMLCanvasElement {
  const { widthPx, heightPx, pixelsPerMm } = computeSurfaceArtworkCanvasSize(
    surface.widthMm,
    surface.heightMm,
    budget,
  );
  const canvas = targetCanvas ?? document.createElement("canvas");
  canvas.width = widthPx;
  canvas.height = heightPx;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return canvas;
  }

  const insetPx = placement.mode === "inset"
    ? Math.max(0, Math.round(placement.inset_mm * pixelsPerMm))
    : 0;
  const availableWidth = Math.max(1, widthPx - insetPx * 2);
  const availableHeight = Math.max(1, heightPx - insetPx * 2);
  const { width: targetWidth, height: targetHeight } = computeArtworkPlacementDrawSize({
    sourceWidth: image.naturalWidth || image.width,
    sourceHeight: image.naturalHeight || image.height,
    availableWidth,
    availableHeight,
    scale: placement.scale,
    mode: placement.mode,
    rotationDeg: placement.rotation_deg,
  });
  const transform = computeArtworkCanvasTransform({
    widthPx,
    heightPx,
    pixelsPerMm,
    placement,
  });

  ctx.clearRect(0, 0, widthPx, heightPx);
  ctx.save();
  ctx.translate(transform.drawCenterX, transform.drawCenterY);
  ctx.rotate(transform.rotationRadians);
  ctx.drawImage(image, -targetWidth / 2, -targetHeight / 2, targetWidth, targetHeight);
  ctx.restore();

  ctx.globalCompositeOperation = "destination-in";
  ctx.beginPath();
  drawRing(ctx, surface.outer, surface, widthPx, heightPx);
  ctx.closePath();
  ctx.fill();
  if (surface.holes.length > 0) {
    ctx.globalCompositeOperation = "destination-out";
    for (const hole of surface.holes) {
      ctx.beginPath();
      drawRing(ctx, hole, surface, widthPx, heightPx);
      ctx.closePath();
      ctx.fill();
    }
  }
  ctx.globalCompositeOperation = "source-over";
  return canvas;
}

function useSurfaceArtworkImage(artworkUrl: string | null | undefined): HTMLImageElement | null {
  const [image, setImage] = useState<HTMLImageElement | null>(null);

  useEffect(() => {
    if (!artworkUrl) {
      setImage(null);
      return undefined;
    }

    let canceled = false;
    const nextImage = new Image();
    nextImage.onload = () => {
      if (!canceled) {
        setImage(nextImage);
      }
    };
    nextImage.onerror = () => {
      if (!canceled) {
        setImage(null);
      }
    };
    nextImage.src = artworkUrl;

    return () => {
      canceled = true;
    };
  }, [artworkUrl]);

  return image;
}

export function configureSurfaceArtworkTextureForPreview(texture: THREE.Texture): void {
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.flipY = false;
  texture.generateMipmaps = false;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
}

function useSurfaceArtworkTexture(
  artworkUrl: string | null | undefined,
  surface: ResolvedSurfaceFootprint | null,
  placement: ModelSurfacePlacement,
  budget: SurfaceArtworkPreviewBudget,
  invalidate: () => void,
): THREE.Texture | null {
  const image = useSurfaceArtworkImage(artworkUrl);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const textureRef = useRef<THREE.CanvasTexture | null>(null);
  const [texture, setTexture] = useState<THREE.Texture | null>(null);

  useEffect(() => {
    if (!image || !surface) {
      textureRef.current?.dispose();
      textureRef.current = null;
      canvasRef.current = null;
      setTexture(null);
      invalidate();
      return;
    }

    const sourceWidth = image.naturalWidth || image.width;
    const sourceHeight = image.naturalHeight || image.height;
    const insetMm = placement.mode === "inset" ? Math.max(0, placement.inset_mm) : 0;
    const artworkSizeMm = computeArtworkPlacementDrawSizeMm({
      sourceWidth,
      sourceHeight,
      availableWidthMm: Math.max(0.001, surface.widthMm - insetMm * 2),
      availableHeightMm: Math.max(0.001, surface.heightMm - insetMm * 2),
      scale: placement.scale,
      mode: placement.mode,
      rotationDeg: placement.rotation_deg,
    });
    const canvas = drawSurfaceArtworkCanvas(
      image,
      surface,
      placement,
      budget,
      canvasRef.current ?? undefined,
    );
    canvasRef.current = canvas;

    let nextTexture = textureRef.current;
    if (!nextTexture) {
      nextTexture = new THREE.CanvasTexture(canvas);
      configureSurfaceArtworkTextureForPreview(nextTexture);
      textureRef.current = nextTexture;
      setTexture(nextTexture);
    }
    nextTexture.userData.artworkSizeMm = artworkSizeMm;
    nextTexture.needsUpdate = true;
    invalidate();
  }, [budget, image, invalidate, placement, surface]);

  useEffect(() => {
    return () => {
      textureRef.current?.dispose();
      textureRef.current = null;
      canvasRef.current = null;
    };
  }, []);

  return texture;
}

function CandidateSurfacePlane({
  candidate,
  modelOffset,
  highlighted,
}: {
  candidate: ResolvedSurfaceCandidate;
  modelOffset: THREE.Vector3;
  highlighted: boolean;
}) {
  if (!highlighted) {
    return null;
  }

  return <CandidateSurfaceHighlight candidate={candidate} modelOffset={modelOffset} />;
}

function CandidateSurfaceHighlight({
  candidate,
  modelOffset,
}: {
  candidate: ResolvedSurfaceCandidate;
  modelOffset: THREE.Vector3;
}) {
  const { surface } = candidate;
  const position = useMemo(
    () => getSurfaceWorldCenter(surface, modelOffset),
    [modelOffset, surface],
  );
  const quaternion = useMemo(() => getSurfaceQuaternion(surface), [surface]);
  const outlineGeometry = useMemo(() => createCandidateSurfaceOutlineGeometry(surface), [surface]);
  const normalGeometry = useMemo(() => createSurfaceNormalIndicatorGeometry(surface), [surface]);
  const normalIndicator = useMemo(() => getSurfaceNormalIndicatorDimensions(surface), [surface]);
  const holeOutlineGeometries = useMemo(() => createSurfaceHoleOutlineGeometries(surface), [surface]);

  useEffect(() => {
    return () => {
      outlineGeometry.dispose();
      normalGeometry.dispose();
      holeOutlineGeometries.forEach((geometry) => geometry.dispose());
    };
  }, [holeOutlineGeometries, normalGeometry, outlineGeometry]);

  return (
    <group
      name={`model-surface-candidate-group-${candidate.id}`}
      position={position}
      quaternion={quaternion}
    >
      <lineSegments
        name={`model-surface-candidate-outline-${candidate.id}`}
        geometry={outlineGeometry}
        renderOrder={SURFACE_CANDIDATE_RENDER_ORDER + 2}
      >
        <lineBasicMaterial
          color="#facc15"
          transparent
          opacity={0.95}
          {...SURFACE_MARKER_MATERIAL_DEPTH_FLAGS}
        />
      </lineSegments>
      <lineSegments
        name={`model-surface-candidate-normal-${candidate.id}`}
        geometry={normalGeometry}
        renderOrder={SURFACE_CANDIDATE_RENDER_ORDER + 2}
      >
        <lineBasicMaterial
          color="#facc15"
          transparent
          opacity={0.95}
          {...SURFACE_MARKER_MATERIAL_DEPTH_FLAGS}
        />
      </lineSegments>
      <mesh
        name={`model-surface-candidate-normal-tip-${candidate.id}`}
        position={[0, 0, normalIndicator.baseZ + normalIndicator.length]}
        raycast={() => undefined}
        renderOrder={SURFACE_CANDIDATE_RENDER_ORDER + 2}
      >
        <circleGeometry args={[normalIndicator.tipRadius, 32]} />
        <meshBasicMaterial
          color="#facc15"
          transparent
          opacity={0.88}
          side={THREE.DoubleSide}
          {...SURFACE_MARKER_MATERIAL_DEPTH_FLAGS}
        />
      </mesh>
      {holeOutlineGeometries.map((geometry, index) => (
        <lineSegments
          key={`${candidate.id}-hole-${index}`}
          name={`model-surface-candidate-hole-outline-${candidate.id}-${index}`}
          geometry={geometry}
          renderOrder={SURFACE_CANDIDATE_RENDER_ORDER + 2}
        >
          <lineBasicMaterial
            color="#facc15"
            transparent
            opacity={0.78}
            {...SURFACE_MARKER_MATERIAL_DEPTH_FLAGS}
          />
        </lineSegments>
      ))}
    </group>
  );
}

function TriangleFacetHover({
  geometry,
  faceIndex,
  modelOffset,
}: {
  geometry: THREE.BufferGeometry;
  faceIndex: number;
  modelOffset: THREE.Vector3;
}) {
  const hoverGeometry = useMemo(
    () => createTriangleFacetHoverGeometries(geometry, faceIndex),
    [faceIndex, geometry],
  );

  useEffect(() => {
    return () => {
      hoverGeometry?.outline.dispose();
    };
  }, [hoverGeometry]);

  if (!hoverGeometry) {
    return null;
  }

  return (
    <group name="model-surface-triangle-hover-group" position={modelOffset}>
      <lineSegments
        name="model-surface-triangle-hover-outline"
        geometry={hoverGeometry.outline}
        raycast={() => undefined}
        renderOrder={31}
      >
        <lineBasicMaterial
          color="#facc15"
          transparent
          opacity={0.95}
          {...SURFACE_MARKER_MATERIAL_DEPTH_FLAGS}
        />
      </lineSegments>
    </group>
  );
}

function CandidateSurfaceHoverReadout({
  candidate,
}: {
  candidate: ResolvedSurfaceCandidate | null;
}) {
  const { t } = useI18n();
  if (!candidate) {
    return null;
  }

  return (
    <CanvasOverlayHtml>
      <div
        role="status"
        aria-label={t("model_surface_candidate_readout")}
        data-model-surface-candidate-readout="screen-fixed"
        data-model-surface-candidate-readout-position="viewport-corner"
        className="pointer-events-none absolute bottom-[72px] right-4 z-20 flex max-w-[calc(100%-32px)] flex-wrap items-center justify-end gap-x-2 gap-y-1 rounded-[22px] border border-amber-300/80 bg-amber-50/94 px-3 py-1.5 text-[11px] font-semibold text-amber-950 shadow-lg backdrop-blur-md dark:border-amber-400/50 dark:bg-slate-950/88 dark:text-amber-100"
      >
        <span>{t("model_surface_candidate_hover")}</span>
        <span>{t(getSurfaceDirectionLabelKey(candidate.surface))}</span>
        <span className="font-mono">{formatSurfaceSize(candidate.surface)}</span>
        <span>{formatCandidateArea(candidate.areaMm2)}</span>
        <span>
          {candidate.faceCount} {t("model_surface_selected_faces")}
        </span>
      </div>
    </CanvasOverlayHtml>
  );
}

function SelectedSurfacePanel({
  surface,
  canTransform,
}: {
  surface: ResolvedSurfaceFootprint;
  canTransform: boolean;
}) {
  const { t } = useI18n();

  return (
    <CanvasOverlayHtml>
      <div
        role="status"
        aria-label={t("model_surface_selected_panel")}
        data-model-surface-selected-panel="screen-reader-status"
        className="sr-only"
      >
        <span>{t("model_surface_selected_short")}</span>
        <span>{t(getSurfaceDirectionLabelKey(surface))}</span>
        <span>{formatSurfaceSize(surface)}</span>
        <span>
          {canTransform
            ? t("model_surface_selected_ready")
            : t("model_surface_selected_waiting_artwork")}
        </span>
      </div>
    </CanvasOverlayHtml>
  );
}

function ArtworkPlacementReadout({
  placement,
}: {
  placement: ModelSurfacePlacement;
}) {
  const { t } = useI18n();

  return (
    <CanvasOverlayHtml>
      <div
        role="status"
        aria-label={t("model_surface_artwork_readout")}
        data-model-surface-artwork-readout="screen-fixed"
        data-model-surface-artwork-readout-position="viewport-corner"
        className="pointer-events-none absolute bottom-4 right-4 z-20 flex max-w-[calc(100%-32px)] flex-wrap items-center justify-end gap-x-2 gap-y-1 rounded-[22px] border border-slate-200/80 bg-slate-100/92 px-3 py-1.5 text-[11px] font-semibold text-slate-800 shadow-lg backdrop-blur-md dark:border-slate-700/80 dark:bg-slate-950/88 dark:text-slate-100"
      >
        <span>{t("model_surface_artwork_readout_offset")}</span>
        <span className="font-mono">X {formatPlacementMm(placement.offset_x_mm)}</span>
        <span className="font-mono">Y {formatPlacementMm(placement.offset_y_mm)}</span>
        <span>{t("model_surface_artwork_readout_rotation")}</span>
        <span className="font-mono">{formatPlacementDegrees(placement.rotation_deg)}</span>
        <span>{t("model_surface_artwork_readout_scale")}</span>
        <span className="font-mono">{formatPlacementScale(placement.scale)}</span>
      </div>
    </CanvasOverlayHtml>
  );
}

function RotationPanel({
  translate,
  rotation,
  relativeInput,
  feedbackAxis,
  axes = ["x", "y", "z"],
  title,
  panelKind = "model",
  axisLabels,
  relativeInputHint: relativeInputHintOverride,
  absoluteInputHint: absoluteInputHintOverride,
  quickRotateHint: quickRotateHintOverride,
  resetRelativeLabel: resetRelativeLabelOverride,
  resetRelativeHint: resetRelativeHintOverride,
  resetZeroLabel: resetZeroLabelOverride,
  resetZeroHint: resetZeroHintOverride,
  doneLabel: doneLabelOverride,
  doneHint: doneHintOverride,
  onChangeAbsoluteAxis,
  onChangeRelativeAxis,
  onFocusAxis,
  onQuickRotateAxis,
  onResetRelative,
  onResetZero,
  onDone,
}: {
  translate: (key: string) => string;
  rotation: ModelRotation;
  relativeInput: ModelRotationDegrees;
  feedbackAxis: RotationAxis | null;
  axes?: RotationAxis[];
  title?: string;
  panelKind?: "model" | "artwork";
  axisLabels?: Partial<Record<RotationAxis, {
    relativeLabel: string;
    absoluteLabel: string;
    quickPositiveLabel: string;
    quickNegativeLabel: string;
  }>>;
  relativeInputHint?: string;
  absoluteInputHint?: string;
  quickRotateHint?: string;
  resetRelativeLabel?: string;
  resetRelativeHint?: string;
  resetZeroLabel?: string;
  resetZeroHint?: string;
  doneLabel?: string;
  doneHint?: string;
  onChangeAbsoluteAxis: (axis: RotationAxis, degrees: number) => void;
  onChangeRelativeAxis: (axis: RotationAxis, degrees: number) => void;
  onFocusAxis: (axis: RotationAxis) => void;
  onQuickRotateAxis: (axis: RotationAxis, degrees: number) => void;
  onResetRelative: () => void;
  onResetZero: () => void;
  onDone: () => void;
}) {
  const t = translate;
  const absoluteDegrees = modelRotationToDegrees(rotation);
  const defaultAxisDefs: Record<RotationAxis, {
    axis: RotationAxis;
    relativeLabel: string;
    absoluteLabel: string;
    quickPositiveLabel: string;
    quickNegativeLabel: string;
  }> = {
    x: {
      axis: "x",
      relativeLabel: t("model_surface_rotation_relative_x"),
      absoluteLabel: t("model_surface_rotation_absolute_x"),
      quickPositiveLabel: t("model_surface_rotation_quick_x_positive"),
      quickNegativeLabel: t("model_surface_rotation_quick_x_negative"),
    },
    y: {
      axis: "y",
      relativeLabel: t("model_surface_rotation_relative_y"),
      absoluteLabel: t("model_surface_rotation_absolute_y"),
      quickPositiveLabel: t("model_surface_rotation_quick_y_positive"),
      quickNegativeLabel: t("model_surface_rotation_quick_y_negative"),
    },
    z: {
      axis: "z",
      relativeLabel: t("model_surface_rotation_relative_z"),
      absoluteLabel: t("model_surface_rotation_absolute_z"),
      quickPositiveLabel: t("model_surface_rotation_quick_z_positive"),
      quickNegativeLabel: t("model_surface_rotation_quick_z_negative"),
    },
  };
  const axisDefs = axes.map((axis) => ({
    ...defaultAxisDefs[axis],
    ...axisLabels?.[axis],
    axis,
  }));
  const panelTitle = title ?? t("model_surface_world_coordinates");
  const isAxisActive = (axis: RotationAxis) => feedbackAxis === axis;
  const axisActiveValue = (axis: RotationAxis) => (isAxisActive(axis) ? "true" : "false");
  const inputClassName = (axis: RotationAxis) =>
    [
      "h-7 w-[54px] rounded-lg px-1 text-center font-mono tabular-nums focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)]",
      isAxisActive(axis)
        ? "border border-current bg-sky-50 font-semibold ring-2 ring-current dark:bg-slate-800"
        : "border border-slate-300/80 bg-slate-50 text-slate-900 dark:border-slate-500/80 dark:bg-slate-900 dark:text-slate-100",
    ].join(" ");
  const quickButtonClassName = (axis: RotationAxis) =>
    [
      "h-7 min-w-[46px] rounded-lg px-1.5 text-center text-[10px] font-semibold focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)]",
      isAxisActive(axis)
        ? "border border-current bg-sky-50 ring-2 ring-current hover:bg-sky-100 dark:bg-slate-800 dark:hover:bg-slate-700"
        : "border border-slate-300/80 bg-slate-50 text-slate-800 hover:bg-slate-200 dark:border-slate-500/80 dark:bg-slate-900 dark:text-slate-100 dark:hover:bg-slate-800",
    ].join(" ");
  const relativeInputHint = relativeInputHintOverride ?? t("model_surface_rotation_relative_input_hint");
  const absoluteInputHint = absoluteInputHintOverride ?? t("model_surface_rotation_absolute_input_hint");
  const quickRotateHint = quickRotateHintOverride ?? t("model_surface_rotation_quick_hint");
  const resetRelativeLabel = resetRelativeLabelOverride ?? t("model_surface_rotation_reset_relative");
  const resetRelativeHint = resetRelativeHintOverride ?? t("model_surface_rotation_reset_relative_hint");
  const resetZeroLabel = resetZeroLabelOverride ?? t("model_surface_rotation_reset_zero");
  const resetZeroHint = resetZeroHintOverride ?? t("model_surface_rotation_reset_zero_hint");
  const doneLabel = doneLabelOverride ?? t("model_surface_rotation_done");
  const doneHint = doneHintOverride ?? t("model_surface_rotation_done_hint");

  return (
    <div
      role="group"
      aria-label={panelTitle}
      data-model-rotation-panel-shell="integrated-command-band"
      data-model-rotation-panel-orientation="horizontal"
      data-model-rotation-panel-density="compact"
      data-artwork-rotation-panel={panelKind === "artwork" ? "planar" : undefined}
      className="min-w-max text-[10px] text-slate-800 dark:text-slate-100"
    >
      <div className="min-w-max">
                <div
                  data-model-rotation-values="compact-horizontal"
                  className="flex h-7 items-center gap-2"
                >
                  <div className="flex shrink-0 items-center gap-1.5 pr-0.5">
                    <div className="whitespace-nowrap font-semibold text-slate-700 dark:text-slate-200">
                      {panelTitle}
                    </div>
                  </div>

                  <div className="h-5 w-px shrink-0 bg-slate-300/80 dark:bg-slate-700/80" />

                  <div
                    data-model-rotation-angle-group="relative"
                    className="flex shrink-0 items-center gap-1"
                  >
                    <div className="mr-0.5 whitespace-nowrap font-semibold text-slate-700 dark:text-slate-200">
                      {t("model_surface_rotation_relative")}
                    </div>
                    {axisDefs.map(({ axis, relativeLabel }) => (
                      <div key={`${axis}-relative-field`} className="flex items-center gap-1">
                        <span
                          data-model-rotation-axis={axis}
                          data-model-rotation-axis-active={axisActiveValue(axis)}
                          className="w-3 text-center text-xs font-bold"
                          style={{ color: AXIS_COLORS[axis] }}
                        >
                          {axis.toUpperCase()}
                        </span>
                        <WikiTooltip
                          title={relativeLabel}
                          description={relativeInputHint}
                          placement="bottom"
                          delay={0}
                          asChild
                        >
                          <input
                            aria-label={relativeLabel}
                            type="number"
                            value={Number(relativeInput[axis].toFixed(2))}
                            step={1}
                            data-model-rotation-axis={axis}
                            data-model-rotation-axis-active={axisActiveValue(axis)}
                            onFocus={() => onFocusAxis(axis)}
                            onChange={(event) =>
                              onChangeRelativeAxis(axis, Number(event.currentTarget.value))
                            }
                            className={inputClassName(axis)}
                            style={isAxisActive(axis) ? { color: AXIS_COLORS[axis] } : undefined}
                          />
                        </WikiTooltip>
                      </div>
                    ))}
                    <span className="pl-0.5">°</span>
                  </div>

                  <div className="h-5 w-px shrink-0 bg-slate-300/80 dark:bg-slate-700/80" />

                  <div
                    data-model-rotation-angle-group="absolute"
                    className="flex shrink-0 items-center gap-1"
                  >
                    <div className="mr-0.5 whitespace-nowrap font-semibold text-slate-700 dark:text-slate-200">
                      {t("model_surface_rotation_absolute")}
                    </div>
                    {axisDefs.map(({ axis, absoluteLabel }) => (
                      <div key={`${axis}-absolute-field`} className="flex items-center gap-1">
                        <span
                          data-model-rotation-axis={axis}
                          data-model-rotation-axis-active={axisActiveValue(axis)}
                          className="w-3 text-center text-xs font-bold"
                          style={{ color: AXIS_COLORS[axis] }}
                        >
                          {axis.toUpperCase()}
                        </span>
                        <WikiTooltip
                          title={absoluteLabel}
                          description={absoluteInputHint}
                          placement="bottom"
                          delay={0}
                          asChild
                        >
                          <input
                            aria-label={absoluteLabel}
                            type="number"
                            value={Number(absoluteDegrees[axis].toFixed(2))}
                            step={1}
                            data-model-rotation-axis={axis}
                            data-model-rotation-axis-active={axisActiveValue(axis)}
                            onFocus={() => onFocusAxis(axis)}
                            onChange={(event) =>
                              onChangeAbsoluteAxis(axis, Number(event.currentTarget.value))
                            }
                            className={inputClassName(axis)}
                            style={isAxisActive(axis) ? { color: AXIS_COLORS[axis] } : undefined}
                          />
                        </WikiTooltip>
                      </div>
                    ))}
                    <span className="pl-0.5">°</span>
                  </div>
                </div>

                <div
                  data-model-rotation-actions="compact-horizontal"
                  className="mt-1 flex h-8 items-center gap-1.5 border-t border-slate-300/80 pt-1 dark:border-slate-700/80"
                >
                  <div className="mr-0.5 whitespace-nowrap font-semibold text-slate-700 dark:text-slate-200">
                    {t("model_surface_rotation_quick")}
                  </div>
                  <div
                    data-model-rotation-quick-grid="axis-pairs"
                    className={
                      axisDefs.length === 1
                        ? "grid grid-cols-2 gap-1"
                        : "grid grid-cols-6 gap-1"
                    }
                  >
                    {axisDefs.flatMap(({ axis, quickNegativeLabel, quickPositiveLabel }) => [
                      <WikiTooltip
                        key={`${axis}-negative`}
                        title={quickNegativeLabel}
                        description={quickRotateHint}
                        placement="bottom"
                        delay={0}
                        className="inline-flex"
                      >
                        <button
                          type="button"
                          aria-label={quickNegativeLabel}
                          title={quickNegativeLabel}
                          data-model-rotation-axis={axis}
                          data-model-rotation-axis-active={axisActiveValue(axis)}
                          onFocus={() => onFocusAxis(axis)}
                          onClick={() => onQuickRotateAxis(axis, -90)}
                          className={quickButtonClassName(axis)}
                          style={{ color: AXIS_COLORS[axis] }}
                        >
                          {panelKind === "model" ? `${axis.toUpperCase()} ` : ""}
                          {t("model_surface_rotation_step_minus_90")}
                        </button>
                      </WikiTooltip>,
                      <WikiTooltip
                        key={`${axis}-positive`}
                        title={quickPositiveLabel}
                        description={quickRotateHint}
                        placement="bottom"
                        delay={0}
                        className="inline-flex"
                      >
                        <button
                          type="button"
                          aria-label={quickPositiveLabel}
                          title={quickPositiveLabel}
                          data-model-rotation-axis={axis}
                          data-model-rotation-axis-active={axisActiveValue(axis)}
                          onFocus={() => onFocusAxis(axis)}
                          onClick={() => onQuickRotateAxis(axis, 90)}
                          className={quickButtonClassName(axis)}
                          style={{ color: AXIS_COLORS[axis] }}
                        >
                          {panelKind === "model" ? `${axis.toUpperCase()} ` : ""}
                          {t("model_surface_rotation_step_90")}
                        </button>
                      </WikiTooltip>,
                    ])}
                  </div>

                  {feedbackAxis ? (
                    <div
                      role="status"
                      aria-label={t("model_surface_rotation_angle_readout")}
                      className="h-7 whitespace-nowrap rounded-lg border border-slate-300/70 bg-slate-200/70 px-2 text-right font-mono text-[10px] font-semibold leading-7 tabular-nums text-slate-800 dark:border-slate-600/70 dark:bg-slate-800/70 dark:text-slate-100"
                    >
                      {formatRotationTooltip(
                        feedbackAxis,
                        getModelRotationValue(rotation, feedbackAxis),
                      )}
                    </div>
                  ) : null}

                  <div className="min-w-1 flex-1" />

                  <WikiTooltip
                    title={resetRelativeLabel}
                    description={resetRelativeHint}
                    placement="top"
                    delay={0}
                    asChild
                  >
                    <button
                      type="button"
                      aria-label={resetRelativeLabel}
                      title={resetRelativeLabel}
                      onClick={onResetRelative}
                      className="h-7 whitespace-nowrap rounded-lg border border-slate-300/80 px-2 font-semibold text-slate-700 hover:bg-slate-200 dark:border-slate-500/80 dark:text-slate-100 dark:hover:bg-slate-800"
                    >
                      {resetRelativeLabel}
                    </button>
                  </WikiTooltip>
                  <WikiTooltip
                    title={resetZeroLabel}
                    description={resetZeroHint}
                    placement="top"
                    delay={0}
                    asChild
                  >
                    <button
                      type="button"
                      aria-label={resetZeroLabel}
                      title={resetZeroLabel}
                      onClick={onResetZero}
                      className="h-7 whitespace-nowrap rounded-lg border border-slate-300/80 px-2 font-semibold text-slate-700 hover:bg-slate-200 dark:border-slate-500/80 dark:text-slate-100 dark:hover:bg-slate-800"
                    >
                      {resetZeroLabel}
                    </button>
                  </WikiTooltip>
                  <WikiTooltip
                    title={doneLabel}
                    description={doneHint}
                    placement="top"
                    delay={0}
                    asChild
                  >
                    <button
                      type="button"
                      aria-label={doneLabel}
                      title={doneLabel}
                      onClick={onDone}
                      className="h-7 whitespace-nowrap rounded-lg bg-slate-900 px-2.5 font-semibold text-slate-100 hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-slate-200"
                    >
                      {doneLabel}
                    </button>
                  </WikiTooltip>
                </div>
      </div>
    </div>
  );
}

function ModelRotationTooltip({
  axis,
  point,
  rotation,
}: {
  axis: RotationAxis | null;
  point: ScreenPoint | null;
  rotation: ModelRotation;
}) {
  if (!axis || !point) {
    return null;
  }
  return (
    <CanvasOverlayHtml>
      {(frame) => (
      <div
        role="status"
        aria-label="旋转角度提示"
        className="pointer-events-none absolute z-20 rounded-xl border border-slate-300/80 bg-slate-100/94 px-2 py-1 text-[11px] font-semibold text-slate-900 shadow-lg backdrop-blur-md dark:border-slate-600/70 dark:bg-slate-950/88 dark:text-slate-100"
        style={{ left: point.x - frame.canvasLeft + 12, top: point.y - frame.canvasTop + 12 }}
      >
        {formatRotationTooltip(axis, getModelRotationValue(rotation, axis))}
      </div>
      )}
    </CanvasOverlayHtml>
  );
}

function ModelRotationRings({
  center,
  radius,
  rotation,
  axes = ["x", "y", "z"],
  namePrefix = "model-rotation",
  renderOrder = 0,
  activeAxis,
  hoveredAxis,
  focusedAxis,
  onHoverAxis,
  onStartAxisDrag,
  onMoveAxisDrag,
  onFinishAxisDrag,
}: {
  center: THREE.Vector3;
  radius: number;
  rotation: ModelRotation;
  axes?: RotationAxis[];
  namePrefix?: string;
  renderOrder?: number;
  activeAxis: RotationAxis | null;
  hoveredAxis: RotationAxis | null;
  focusedAxis: RotationAxis | null;
  onHoverAxis: (axis: RotationAxis | null) => void;
  onStartAxisDrag: (axis: RotationAxis, event: ModelRotatePointerEvent) => void;
  onMoveAxisDrag: (event: ModelRotatePointerEvent) => void;
  onFinishAxisDrag: (event: ModelRotatePointerEvent) => void;
}) {
  const ringRadius = getRotationGizmoRadius(radius);
  const tubeRadius = Math.max(ringRadius * 0.006, 0.2);
  const hitTargetTubeRadius = getRotationHitTargetTubeRadius(ringRadius);
  const theme = useSettingsStore((state) => state.theme);
  const measureColor = theme === "dark" ? ROTATION_MEASURE_COLORS.dark : ROTATION_MEASURE_COLORS.light;
  const visibleAxes = axes;
  const detailAxis =
    activeAxis ?? hoveredAxis ?? focusedAxis ?? visibleAxes[visibleAxes.length - 1] ?? null;

  const isEmphasized = useCallback(
    (axis: RotationAxis) =>
      activeAxis === axis ||
      (!activeAxis && hoveredAxis === axis) ||
      (!activeAxis && !hoveredAxis && focusedAxis === axis) ||
      (!activeAxis && !hoveredAxis && !focusedAxis),
    [activeAxis, focusedAxis, hoveredAxis],
  );

  return (
    <group name={`${namePrefix}-gizmo`} position={center} renderOrder={renderOrder}>
      {visibleAxes.map((axis) => (
        <group key={axis}>
          <mesh
            name={`${namePrefix}-${axis}-hit-target`}
            rotation={ROTATION_RING_CONFIG[axis].rotation}
            onPointerDown={(event: ModelRotatePointerEvent) => onStartAxisDrag(axis, event)}
            onPointerMove={onMoveAxisDrag}
            onPointerUp={onFinishAxisDrag}
            onPointerCancel={onFinishAxisDrag}
            onPointerEnter={() => onHoverAxis(axis)}
            onPointerOut={() => onHoverAxis(null)}
          >
            <torusGeometry args={[ringRadius, hitTargetTubeRadius, 8, 96]} />
            <meshBasicMaterial
              color={AXIS_COLORS[axis]}
              transparent
              opacity={0}
              colorWrite={false}
              depthWrite={false}
              depthTest={false}
            />
          </mesh>
          <mesh
            name={`${namePrefix}-${axis}-ring`}
            rotation={ROTATION_RING_CONFIG[axis].rotation}
            onPointerDown={(event: ModelRotatePointerEvent) => onStartAxisDrag(axis, event)}
            onPointerMove={onMoveAxisDrag}
            onPointerUp={onFinishAxisDrag}
            onPointerCancel={onFinishAxisDrag}
            onPointerEnter={() => onHoverAxis(axis)}
            onPointerOut={() => onHoverAxis(null)}
          >
            <torusGeometry args={[ringRadius, tubeRadius, 8, 96]} />
            <meshBasicMaterial
              color={AXIS_COLORS[axis]}
              transparent
              opacity={isEmphasized(axis) ? 0.82 : 0.38}
              depthWrite={false}
              depthTest={false}
            />
          </mesh>
        </group>
      ))}
      <group name={`${namePrefix}-grabber-connection`}>
        {visibleAxes.map((axis) => (
          <RotationAxisConnectionLayer
            key={axis}
            axis={axis}
            radius={ringRadius}
            angle={getModelRotationValue(rotation, axis)}
            emphasized={isEmphasized(axis)}
            namePrefix={namePrefix}
          />
        ))}
      </group>
      <group name={`${namePrefix}-grabbers`}>
        {visibleAxes.map((axis) => (
          <RotationAxisGrabber
            key={axis}
            axis={axis}
            radius={ringRadius}
            angle={getModelRotationValue(rotation, axis)}
            emphasized={isEmphasized(axis)}
            onStartAxisDrag={onStartAxisDrag}
            onMoveAxisDrag={onMoveAxisDrag}
            onFinishAxisDrag={onFinishAxisDrag}
            onHoverAxis={onHoverAxis}
            namePrefix={namePrefix}
          />
        ))}
      </group>
      {detailAxis ? (
        <>
          <group name={`${namePrefix}-coarse-snap-guides`}>
            <RotationAxisCoarseSnapGuideLayer
              axis={detailAxis}
              radius={ringRadius}
              color={measureColor}
              emphasized
              namePrefix={namePrefix}
            />
          </group>
          <group name={`${namePrefix}-snap-radius-rings`}>
            <RotationAxisSnapRadiusRingLayer
              axis={detailAxis}
              radius={ringRadius}
              color={measureColor}
              emphasized
              namePrefix={namePrefix}
            />
          </group>
          <group name={`${namePrefix}-reference-rays`}>
            <RotationAxisReferenceRayLayer
              axis={detailAxis}
              radius={ringRadius}
              color={measureColor}
              emphasized
              namePrefix={namePrefix}
            />
          </group>
          <group name={`${namePrefix}-ticks`}>
            <RotationAxisTickLayer
              axis={detailAxis}
              radius={ringRadius}
              color={measureColor}
              emphasized
              namePrefix={namePrefix}
            />
          </group>
          <group name={`${namePrefix}-angle-arc`}>
            <RotationAxisAngleArcLayer
              axis={detailAxis}
              radius={ringRadius}
              angle={getModelRotationValue(rotation, detailAxis)}
              color={measureColor}
              emphasized
              namePrefix={namePrefix}
            />
          </group>
        </>
      ) : null}
    </group>
  );
}

function RotationAxisCoarseSnapGuideLayer({
  axis,
  radius,
  color,
  emphasized,
  namePrefix,
}: {
  axis: RotationAxis;
  radius: number;
  color: string;
  emphasized: boolean;
  namePrefix: string;
}) {
  const geometry = useMemo(() => createRotationCoarseSnapGuideGeometry(radius), [radius]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return (
    <lineSegments
      name={`${namePrefix}-${axis}-coarse-snap-guides`}
      geometry={geometry}
      rotation={ROTATION_RING_CONFIG[axis].rotation}
    >
      <lineBasicMaterial
        color={color}
        transparent
        opacity={emphasized ? 0.5 : 0.18}
        depthWrite={false}
        depthTest={false}
      />
    </lineSegments>
  );
}

function RotationAxisSnapRadiusRingLayer({
  axis,
  radius,
  color,
  emphasized,
  namePrefix,
}: {
  axis: RotationAxis;
  radius: number;
  color: string;
  emphasized: boolean;
  namePrefix: string;
}) {
  const geometry = useMemo(() => createRotationSnapRadiusRingGeometry(radius), [radius]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return (
    <lineSegments
      name={`${namePrefix}-${axis}-snap-radius-rings`}
      geometry={geometry}
      rotation={ROTATION_RING_CONFIG[axis].rotation}
    >
      <lineBasicMaterial
        color={color}
        transparent
        opacity={emphasized ? 0.36 : 0.16}
        depthWrite={false}
        depthTest={false}
      />
    </lineSegments>
  );
}

function RotationAxisReferenceRayLayer({
  axis,
  radius,
  color,
  emphasized,
  namePrefix,
}: {
  axis: RotationAxis;
  radius: number;
  color: string;
  emphasized: boolean;
  namePrefix: string;
}) {
  const geometry = useMemo(() => createRotationReferenceRayGeometry(radius), [radius]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return (
    <lineSegments
      name={`${namePrefix}-${axis}-reference-ray`}
      geometry={geometry}
      rotation={ROTATION_RING_CONFIG[axis].rotation}
    >
      <lineBasicMaterial
        color={color}
        transparent
        opacity={emphasized ? 0.78 : 0.28}
        depthWrite={false}
        depthTest={false}
      />
    </lineSegments>
  );
}

function RotationAxisTickLayer({
  axis,
  radius,
  color,
  emphasized,
  namePrefix,
}: {
  axis: RotationAxis;
  radius: number;
  color: string;
  emphasized: boolean;
  namePrefix: string;
}) {
  const geometry = useMemo(() => createRotationTickGeometry(radius), [radius]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return (
    <lineSegments
      name={`${namePrefix}-${axis}-ticks`}
      geometry={geometry}
      rotation={ROTATION_RING_CONFIG[axis].rotation}
    >
      <lineBasicMaterial
        color={color}
        transparent
        opacity={emphasized ? 0.6 : 0.22}
        depthWrite={false}
        depthTest={false}
      />
    </lineSegments>
  );
}

function RotationAxisAngleArcLayer({
  axis,
  radius,
  angle,
  color,
  emphasized,
  namePrefix,
}: {
  axis: RotationAxis;
  radius: number;
  angle: number;
  color: string;
  emphasized: boolean;
  namePrefix: string;
}) {
  const geometry = useMemo(() => createRotationAngleArcGeometry(radius, angle), [angle, radius]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return (
    <lineSegments
      name={`${namePrefix}-${axis}-angle-arc`}
      geometry={geometry}
      rotation={ROTATION_RING_CONFIG[axis].rotation}
    >
      <lineBasicMaterial
        color={color}
        transparent
        opacity={emphasized ? 0.92 : 0.36}
        depthWrite={false}
        depthTest={false}
      />
    </lineSegments>
  );
}

function RotationAxisConnectionLayer({
  axis,
  radius,
  angle,
  emphasized,
  namePrefix,
}: {
  axis: RotationAxis;
  radius: number;
  angle: number;
  emphasized: boolean;
  namePrefix: string;
}) {
  const geometry = useMemo(() => createRotationConnectionGeometry(radius, angle), [angle, radius]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return (
    <lineSegments
      name={`${namePrefix}-${axis}-grabber-connection`}
      geometry={geometry}
      rotation={ROTATION_RING_CONFIG[axis].rotation}
    >
      <lineBasicMaterial
        color={emphasized ? AXIS_COLORS[axis] : "#94a3b8"}
        transparent
        opacity={emphasized ? 0.68 : 0.22}
        depthWrite={false}
        depthTest={false}
      />
    </lineSegments>
  );
}

function RotationAxisGrabber({
  axis,
  radius,
  angle,
  emphasized,
  onStartAxisDrag,
  onMoveAxisDrag,
  onFinishAxisDrag,
  onHoverAxis,
  namePrefix,
}: {
  axis: RotationAxis;
  radius: number;
  angle: number;
  emphasized: boolean;
  onStartAxisDrag: (axis: RotationAxis, event: ModelRotatePointerEvent) => void;
  onMoveAxisDrag: (event: ModelRotatePointerEvent) => void;
  onFinishAxisDrag: (event: ModelRotatePointerEvent) => void;
  onHoverAxis: (axis: RotationAxis | null) => void;
  namePrefix: string;
}) {
  const grabberRadius = radius * (1 + ROTATION_GRABBER_OFFSET);
  const handleSize = Math.max(radius * 0.045, 1.8);
  const position: [number, number, number] = [
    Math.cos(angle) * grabberRadius,
    Math.sin(angle) * grabberRadius,
    0,
  ];
  return (
    <group
      name={`${namePrefix}-${axis}-grabber`}
      rotation={ROTATION_RING_CONFIG[axis].rotation}
    >
      <mesh
        name={`${namePrefix}-${axis}-grabber-hit-target`}
        position={position}
        onPointerDown={(event: ModelRotatePointerEvent) => onStartAxisDrag(axis, event)}
        onPointerMove={onMoveAxisDrag}
        onPointerUp={onFinishAxisDrag}
        onPointerCancel={onFinishAxisDrag}
        onPointerEnter={() => onHoverAxis(axis)}
        onPointerOut={() => onHoverAxis(null)}
      >
        <sphereGeometry args={[handleSize * 1.8, 12, 8]} />
        <meshBasicMaterial
          color={AXIS_COLORS[axis]}
          transparent
          opacity={0}
          colorWrite={false}
          depthWrite={false}
          depthTest={false}
        />
      </mesh>
      <mesh
        name={`${namePrefix}-${axis}-grabber-arrow`}
        position={position}
        rotation={[0, 0, angle - Math.PI / 2]}
        onPointerDown={(event: ModelRotatePointerEvent) => onStartAxisDrag(axis, event)}
        onPointerMove={onMoveAxisDrag}
        onPointerUp={onFinishAxisDrag}
        onPointerCancel={onFinishAxisDrag}
        onPointerEnter={() => onHoverAxis(axis)}
        onPointerOut={() => onHoverAxis(null)}
      >
        <coneGeometry args={[handleSize * 0.72, handleSize * 2.25, 18]} />
        <meshBasicMaterial
          color={AXIS_COLORS[axis]}
          transparent
          opacity={emphasized ? 0.96 : 0.58}
          depthWrite={false}
          depthTest={false}
        />
      </mesh>
      <mesh
        name={`${namePrefix}-${axis}-grabber-opposite-arrow`}
        position={position}
        rotation={[0, 0, angle + Math.PI / 2]}
        onPointerDown={(event: ModelRotatePointerEvent) => onStartAxisDrag(axis, event)}
        onPointerMove={onMoveAxisDrag}
        onPointerUp={onFinishAxisDrag}
        onPointerCancel={onFinishAxisDrag}
        onPointerEnter={() => onHoverAxis(axis)}
        onPointerOut={() => onHoverAxis(null)}
      >
        <coneGeometry args={[handleSize * 0.72, handleSize * 2.25, 18]} />
        <meshBasicMaterial
          color={AXIS_COLORS[axis]}
          transparent
          opacity={emphasized ? 0.96 : 0.58}
          depthWrite={false}
          depthTest={false}
        />
      </mesh>
    </group>
  );
}

function SurfaceArtworkPlane({
  surface,
  modelOffset,
  modelEuler,
  modelPivot,
  artworkUrl,
  placement,
  activeTool,
  onUpdatePlacement,
}: {
  surface: ResolvedSurfaceFootprint;
  modelOffset: THREE.Vector3;
  modelEuler: THREE.Euler;
  modelPivot: THREE.Vector3;
  artworkUrl?: string | null;
  placement: ModelSurfacePlacement;
  activeTool: SurfaceTool;
  onUpdatePlacement?: (updates: Partial<ModelSurfacePlacement>) => void;
}) {
  const invalidate = useThree((state) => state.invalidate);
  const controls = useThree((state) => state.controls);
  const renderer = useThree((state) => state.gl as {
    domElement?: HTMLCanvasElement;
    capabilities?: { maxTextureSize?: number };
  } | undefined);
  const textureBudget = useMemo(
    () => computeSurfaceArtworkPreviewBudget(renderer),
    [renderer],
  );
  const texture = useSurfaceArtworkTexture(artworkUrl, surface, placement, textureBudget, invalidate);
  const dragRef = useRef<DragState | null>(null);
  const artworkRotationRingDragRef = useRef<{
    pointerId: number | null;
    center: Numeric2;
    startPointerDegrees: number;
    startRotationDegrees: number;
    ringRadius: number;
  } | null>(null);
  const onUpdatePlacementRef = useRef(onUpdatePlacement);
  const pendingPlacementUpdateRef = useRef<Partial<ModelSurfacePlacement> | null>(null);
  const pendingPlacementFrameRef = useRef<number | null>(null);
  const position = useMemo(
    () => getSurfaceWorldCenter(surface, modelOffset),
    [modelOffset, surface],
  );
  const quaternion = useMemo(() => getSurfaceQuaternion(surface), [surface]);
  const geometry = useMemo(() => createSurfaceArtworkGeometry(surface), [surface]);
  const interactionGeometry = useMemo(
    () => createSurfaceArtworkInteractionGeometry(surface),
    [surface],
  );
  const outlineGeometry = useMemo(() => createSurfaceOutlineGeometry(surface), [surface]);
  const [hoveredArtworkRotationAxis, setHoveredArtworkRotationAxis] =
    useState<RotationAxis | null>(null);
  const [artworkRotationDragging, setArtworkRotationDragging] = useState(false);
  const artworkRotation = useMemo<ModelRotation>(
    () => ({
      x: 0,
      y: 0,
      z: THREE.MathUtils.degToRad(placement.rotation_deg),
    }),
    [placement.rotation_deg],
  );
  const artworkRotationCenter = useMemo(
    () =>
      new THREE.Vector3(
        0,
        0,
        SURFACE_EPSILON_MM * 1.6,
      ),
    [],
  );
  const artworkRotationRadius = useMemo(
    () => Math.hypot(surface.widthMm, surface.heightMm) / 2,
    [surface.heightMm, surface.widthMm],
  );

  useEffect(() => {
    return () => {
      geometry.dispose();
    };
  }, [geometry]);

  useEffect(() => {
    return () => {
      interactionGeometry.dispose();
    };
  }, [interactionGeometry]);

  useEffect(() => {
    return () => {
      outlineGeometry.dispose();
    };
  }, [outlineGeometry]);

  useEffect(() => {
    onUpdatePlacementRef.current = onUpdatePlacement;
  }, [onUpdatePlacement]);

  const flushPendingPlacementUpdate = useCallback(() => {
    pendingPlacementFrameRef.current = null;
    const updates = pendingPlacementUpdateRef.current;
    pendingPlacementUpdateRef.current = null;
    if (!updates) {
      return;
    }
    onUpdatePlacementRef.current?.(updates);
    invalidate();
  }, [invalidate]);

  const flushPendingPlacementUpdateNow = useCallback(() => {
    const frameId = pendingPlacementFrameRef.current;
    if (
      frameId !== null
      && typeof window !== "undefined"
      && typeof window.cancelAnimationFrame === "function"
    ) {
      window.cancelAnimationFrame(frameId);
    }
    flushPendingPlacementUpdate();
  }, [flushPendingPlacementUpdate]);

  const schedulePlacementUpdate = useCallback(
    (updates: Partial<ModelSurfacePlacement>) => {
      pendingPlacementUpdateRef.current = updates;
      if (pendingPlacementFrameRef.current !== null) {
        return;
      }
      if (
        typeof window === "undefined"
        || typeof window.requestAnimationFrame !== "function"
      ) {
        flushPendingPlacementUpdate();
        return;
      }
      pendingPlacementFrameRef.current = window.requestAnimationFrame(() => {
        flushPendingPlacementUpdate();
      });
    },
    [flushPendingPlacementUpdate],
  );

  useEffect(
    () => () => {
      const frameId = pendingPlacementFrameRef.current;
      if (
        frameId !== null
        && typeof window !== "undefined"
        && typeof window.cancelAnimationFrame === "function"
      ) {
        window.cancelAnimationFrame(frameId);
      }
      pendingPlacementFrameRef.current = null;
      pendingPlacementUpdateRef.current = null;
    },
    [],
  );

  const setControlsEnabled = useCallback(
    (enabled: boolean) => {
      const orbit = controls as { enabled?: boolean; update?: () => void } | null;
      if (orbit && "enabled" in orbit) {
        orbit.enabled = enabled;
        orbit.update?.();
      }
    },
    [controls],
  );

  const handlePointerDown = useCallback(
    (event: SurfacePointerEvent) => {
      if (!onUpdatePlacement || activeTool === "select" || activeTool === "modelRotate") {
        return;
      }
      const point = getSurfacePointerPoint(event);
      if (!point) {
        return;
      }
      event.stopPropagation();
      const pointerId = event.pointerId;
      if (typeof pointerId === "number") {
        event.target?.setPointerCapture?.(pointerId);
      }
      dragRef.current = {
        tool: activeTool,
        startPoint: pointToSurfaceLocal(point, surface, modelOffset, modelEuler, modelPivot),
        startPlacement: { ...placement },
      };
      setControlsEnabled(false);
    },
    [
      activeTool,
      modelEuler,
      modelOffset,
      modelPivot,
      onUpdatePlacement,
      placement,
      setControlsEnabled,
      surface,
    ],
  );

  const handlePointerMove = useCallback(
    (event: SurfacePointerEvent) => {
      const drag = dragRef.current;
      if (!drag || !onUpdatePlacement) {
        return;
      }
      const point = getSurfacePointerPoint(event);
      if (!point) {
        return;
      }
      event.stopPropagation();
      const currentPoint = pointToSurfaceLocal(point, surface, modelOffset, modelEuler, modelPivot);
      const artworkSizeMm = texture?.userData.artworkSizeMm as
        | { width?: unknown; height?: unknown }
        | undefined;
      schedulePlacementUpdate(
        computeArtworkPlacementDragUpdate({
          tool: drag.tool,
          center: getSurfaceCenterLocal(surface),
          startPoint: drag.startPoint,
          currentPoint,
          startPlacement: drag.startPlacement,
          surfaceBounds: {
            min: surface.boundsMin,
            max: surface.boundsMax,
          },
          artworkSizeMm:
            typeof artworkSizeMm?.width === "number" && typeof artworkSizeMm.height === "number"
              ? {
                  width: artworkSizeMm.width,
                  height: artworkSizeMm.height,
                }
              : undefined,
        }),
      );
    },
    [
      modelEuler,
      modelOffset,
      modelPivot,
      onUpdatePlacement,
      schedulePlacementUpdate,
      surface,
      texture,
    ],
  );

  const finishDrag = useCallback(
    (event: SurfacePointerEvent) => {
      if (!dragRef.current) {
        return;
      }
      event.stopPropagation();
      const pointerId = event.pointerId;
      if (typeof pointerId === "number") {
        event.target?.releasePointerCapture?.(pointerId);
      }
      flushPendingPlacementUpdateNow();
      dragRef.current = null;
      setControlsEnabled(true);
      invalidate();
    },
    [flushPendingPlacementUpdateNow, invalidate, setControlsEnabled],
  );

  const handleArtworkRotationPointerDown = useCallback(
    (axis: RotationAxis, event: ModelRotatePointerEvent) => {
      if (axis !== "z") {
        return;
      }
      const localPoint = getArtworkRotationPointerLocal(
        event,
        surface,
        modelOffset,
        modelEuler,
        modelPivot,
      );
      if (!localPoint) {
        return;
      }
      event.stopPropagation();
      const pointerId = typeof event.pointerId === "number" ? event.pointerId : null;
      if (pointerId !== null) {
        event.target?.setPointerCapture?.(pointerId);
      }
      const [surfaceCenterX, surfaceCenterY] = getSurfaceCenterLocal(surface);
      const center: Numeric2 = [surfaceCenterX, surfaceCenterY];
      artworkRotationRingDragRef.current = {
        pointerId,
        center,
        startPointerDegrees: THREE.MathUtils.radToDeg(
          Math.atan2(localPoint[1] - center[1], localPoint[0] - center[0]),
        ),
        startRotationDegrees: placement.rotation_deg,
        ringRadius: getRotationGizmoRadius(artworkRotationRadius),
      };
      setArtworkRotationDragging(true);
      setControlsEnabled(false);
    },
    [
      artworkRotationRadius,
      modelEuler,
      modelOffset,
      modelPivot,
      placement.rotation_deg,
      setControlsEnabled,
      surface,
    ],
  );

  const handleArtworkRotationPointerMove = useCallback(
    (event: ModelRotatePointerEvent) => {
      const drag = artworkRotationRingDragRef.current;
      if (!drag) {
        return;
      }
      const localPoint = getArtworkRotationPointerLocal(
        event,
        surface,
        modelOffset,
        modelEuler,
        modelPivot,
      );
      if (!localPoint) {
        return;
      }
      event.stopPropagation();
      const currentPointerDegrees = THREE.MathUtils.radToDeg(
        Math.atan2(localPoint[1] - drag.center[1], localPoint[0] - drag.center[0]),
      );
      const distance = Math.hypot(
        localPoint[0] - drag.center[0],
        localPoint[1] - drag.center[1],
      );
      schedulePlacementUpdate({
        rotation_deg: computeModelRotationDragDegrees(
          drag.startRotationDegrees,
          drag.startPointerDegrees,
          currentPointerDegrees,
          distance,
          drag.ringRadius,
        ),
      });
    },
    [modelEuler, modelOffset, modelPivot, schedulePlacementUpdate, surface],
  );

  const finishArtworkRotationDrag = useCallback(
    (event: ModelRotatePointerEvent) => {
      const drag = artworkRotationRingDragRef.current;
      if (!drag) {
        setArtworkRotationDragging(false);
        return;
      }
      event.stopPropagation();
      if (drag.pointerId !== null) {
        event.target?.releasePointerCapture?.(drag.pointerId);
      }
      flushPendingPlacementUpdateNow();
      artworkRotationRingDragRef.current = null;
      setArtworkRotationDragging(false);
      setControlsEnabled(true);
      invalidate();
    },
    [flushPendingPlacementUpdateNow, invalidate, setControlsEnabled],
  );

  useEffect(() => {
    if (activeTool !== "rotate") {
      artworkRotationRingDragRef.current = null;
      setArtworkRotationDragging(false);
      setHoveredArtworkRotationAxis(null);
      setControlsEnabled(true);
    }
  }, [activeTool, setControlsEnabled]);

  return (
    <group position={position} quaternion={quaternion}>
      {activeTool === "rotate" && onUpdatePlacement ? (
        <ModelRotationRings
          center={artworkRotationCenter}
          radius={artworkRotationRadius}
          rotation={artworkRotation}
          axes={["z"]}
          namePrefix="artwork-rotation"
          renderOrder={SURFACE_SELECTED_RENDER_ORDER + 10}
          activeAxis={artworkRotationDragging ? "z" : null}
          hoveredAxis={hoveredArtworkRotationAxis}
          focusedAxis="z"
          onHoverAxis={setHoveredArtworkRotationAxis}
          onStartAxisDrag={handleArtworkRotationPointerDown}
          onMoveAxisDrag={handleArtworkRotationPointerMove}
          onFinishAxisDrag={finishArtworkRotationDrag}
        />
      ) : null}
      <lineSegments
        name="model-surface-selected-outline"
        geometry={outlineGeometry}
        position={[0, 0, SURFACE_EPSILON_MM * 0.2]}
        renderOrder={SURFACE_SELECTED_RENDER_ORDER + 1}
      >
        <lineBasicMaterial
          color="#0ea5e9"
          transparent
          opacity={0.92}
          {...SURFACE_MARKER_MATERIAL_DEPTH_FLAGS}
        />
      </lineSegments>
      {texture && (
        <>
          <mesh
            name="model-surface-artwork-hit-target"
            geometry={interactionGeometry}
            position={[0, 0, SURFACE_EPSILON_MM * 0.4]}
            renderOrder={SURFACE_SELECTED_RENDER_ORDER + 3}
            {...getArtworkTextureRaycastProps(activeTool)}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={finishDrag}
            onPointerCancel={finishDrag}
            onPointerLeave={finishDrag}
          >
            <meshBasicMaterial
              colorWrite={false}
              opacity={0}
              transparent
              side={THREE.DoubleSide}
              depthTest={false}
              depthWrite={false}
            />
          </mesh>
          <mesh
            geometry={geometry}
            renderOrder={SURFACE_SELECTED_RENDER_ORDER + 2}
            {...getArtworkTextureRaycastProps(activeTool)}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={finishDrag}
            onPointerCancel={finishDrag}
            onPointerLeave={finishDrag}
          >
            <meshBasicMaterial
              map={texture}
              alphaTest={0.02}
              opacity={1}
              transparent
              side={THREE.DoubleSide}
              {...SURFACE_ARTWORK_MATERIAL_DEPTH_FLAGS}
              polygonOffset
              polygonOffsetFactor={-2}
            />
          </mesh>
        </>
      )}
    </group>
  );
}

export default function ModelSurfaceSelector3D({
  file,
  artworkUrl = null,
  footprint = null,
  surfaceCandidates = [],
  placement = DEFAULT_PLACEMENT,
  bedGridVisible = true,
  selectionReady,
  selecting,
  onSelectFace,
  onUpdatePlacement,
  onUpdateModelRotation,
  onFitArtwork,
  onBedGridVisibleChange,
}: ModelSurfaceSelector3DProps) {
  const { t } = useI18n();
  const [model, setModel] = useState<LoadedSurfaceModel | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [activeTool, setActiveTool] = useState<SurfaceTool>("select");
  const [modelRotation, setModelRotation] = useState<ModelRotation>(DEFAULT_MODEL_ROTATION);
  const [modelRotationBaseline, setModelRotationBaseline] = useState<ModelRotation>(DEFAULT_MODEL_ROTATION);
  const [modelRotationRelativeInput, setModelRotationRelativeInput] = useState<ModelRotationDegrees>(
    DEFAULT_MODEL_RELATIVE_ROTATION_INPUT,
  );
  const [artworkRotationBaseline, setArtworkRotationBaseline] = useState(0);
  const [artworkRotationRelativeInput, setArtworkRotationRelativeInput] = useState(0);
  const [reverseView, setReverseView] = useState(false);
  const [forceReselect, setForceReselect] = useState(false);
  const [surfaceSelectionMode, setSurfaceSelectionMode] = useState<SurfaceSelectionMode>("grouped");
  const [viewDisplay, setViewDisplay] = useState<ViewDisplayOptions>(DEFAULT_VIEW_DISPLAY);
  const [lastRequestedView, setLastRequestedView] = useState<ViewDirection | null>(null);
  const [hoveredCandidateId, setHoveredCandidateId] = useState<string | null>(null);
  const [hoveredTriangleFaceIndex, setHoveredTriangleFaceIndex] = useState<number | null>(null);
  const [hoveredRotationAxis, setHoveredRotationAxis] = useState<RotationAxis | null>(null);
  const [activeRotationAxis, setActiveRotationAxis] = useState<RotationAxis | null>(null);
  const [focusedRotationAxis, setFocusedRotationAxis] = useState<RotationAxis | null>(null);
  const [rotationTooltipPoint, setRotationTooltipPoint] = useState<ScreenPoint | null>(null);
  const modelRotateDragRef = useRef<ModelRotationDragState | null>(null);
  const modelRotateReturnForceReselectRef = useRef(false);
  const faceUpOrientedSurfaceRef = useRef<ResolvedSurfaceFootprint | null>(null);
  const skipFocusAfterFaceUpOrientationRef = useRef<ResolvedSurfaceFootprint | null>(null);
  const lastCandidateSelectionRef = useRef<{
    faceIndex: number;
    candidateId: string;
    timestamp: number;
  } | null>(null);
  const notifiedModelRotationRef = useRef<ModelSurfaceModelRotation>(
    modelRotationToSurfaceModelRotation(DEFAULT_MODEL_ROTATION),
  );

  const commitModelRotation = useCallback(
    (updater: (current: ModelRotation) => ModelRotation) => {
      setModelRotation((current) => {
        const next = updater(current);
        return next;
      });
    },
    [],
  );
  const groupRef = useRef<THREE.Group>(null);
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls);
  const invalidate = useThree((state) => state.invalidate);
  const gl = useThree((state) => state.gl as { domElement?: HTMLCanvasElement } | undefined);
  const themeColors = useThemeConfig();
  const modelBodyColor = themeColors.modelSurfaceBody;
  const initialModelBodyColorRef = useRef(modelBodyColor);
  const defaultCameraFovRef = useRef<number | null>(null);
  const getPerspectiveCameraFov = useCallback(() => {
    const perspectiveCamera = camera as THREE.PerspectiveCamera;
    if (typeof perspectiveCamera.fov !== "number") {
      return null;
    }
    if (defaultCameraFovRef.current === null) {
      defaultCameraFovRef.current = perspectiveCamera.fov;
    }
    return perspectiveCamera.fov;
  }, [camera]);
  const restoreDefaultCameraFov = useCallback(() => {
    const perspectiveCamera = camera as THREE.PerspectiveCamera;
    const currentFov = getPerspectiveCameraFov();
    if (currentFov === null) {
      return 45;
    }
    const defaultFov = defaultCameraFovRef.current ?? currentFov;
    if (Math.abs(perspectiveCamera.fov - defaultFov) > 0.001) {
      perspectiveCamera.fov = defaultFov;
    }
    return perspectiveCamera.fov;
  }, [camera, getPerspectiveCameraFov]);
  const applySurfaceInspectionCameraFov = useCallback(() => {
    const perspectiveCamera = camera as THREE.PerspectiveCamera;
    const currentFov = getPerspectiveCameraFov();
    if (currentFov === null) {
      return 45;
    }
    if (Math.abs(perspectiveCamera.fov - SELECTED_SURFACE_INSPECTION_FOV_DEGREES) > 0.001) {
      perspectiveCamera.fov = SELECTED_SURFACE_INSPECTION_FOV_DEGREES;
    }
    return perspectiveCamera.fov;
  }, [camera, getPerspectiveCameraFov]);
  const material = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: initialModelBodyColorRef.current,
        transparent: false,
        opacity: 1,
        depthTest: true,
        depthWrite: true,
        side: THREE.DoubleSide,
        toneMapped: false,
      }),
    [],
  );
  const resolvedSurface = useMemo(
    () => resolveSurfaceFootprint(footprint),
    [footprint],
  );
  const resolvedCandidates = useMemo(
    () => resolveSurfaceCandidates(surfaceCandidates),
    [surfaceCandidates],
  );
  const selectableCandidates = useMemo(
    () => filterSelectableSurfaceCandidates(resolvedCandidates),
    [resolvedCandidates],
  );
  const modelOffset = model?.offset ?? new THREE.Vector3();
  const modelBounds = useMemo(() => getModelBounds(model), [model]);
  const modelEuler = useMemo(() => toModelEuler(modelRotation), [modelRotation]);
  const modelRotationTuple = useMemo(
    () => [modelRotation.x, modelRotation.y, modelRotation.z] as [number, number, number],
    [modelRotation],
  );
  const selectedSurfaceNeedsFaceUpRotation = useMemo(
    () =>
      resolvedSurface
        ? getModelRotationWithSurfaceFacingUp(resolvedSurface.frame.normal, modelRotation) !== null
        : false,
    [modelRotation, resolvedSurface],
  );
  const modelPivot = modelBounds.center;
  const modelPivotTuple = useMemo(
    () => [modelPivot.x, modelPivot.y, modelPivot.z] as [number, number, number],
    [modelPivot],
  );
  const inverseModelPivotTuple = useMemo(
    () => [-modelPivot.x, -modelPivot.y, -modelPivot.z] as [number, number, number],
    [modelPivot],
  );
  const rotationGizmoCenter = useMemo(
    () => modelBounds.center.clone(),
    [modelBounds.center],
  );
  const canFocusSurface = Boolean(resolvedSurface);
  const canTransform = Boolean(resolvedSurface && artworkUrl && onUpdatePlacement && !forceReselect);
  const showSurfaceCandidates = activeTool === "select" && (!resolvedSurface || forceReselect);
  const showGroupedSurfaceCandidates = showSurfaceCandidates && surfaceSelectionMode === "grouped";
  const showTriangleFacetHover =
    showSurfaceCandidates &&
    surfaceSelectionMode === "triangle" &&
    hoveredTriangleFaceIndex !== null &&
    model?.kind === "stl";
  const hoveredCandidate = useMemo(
    () =>
      showGroupedSurfaceCandidates
        ? selectableCandidates.find((candidate) => candidate.id === hoveredCandidateId) ?? null
        : null,
    [hoveredCandidateId, selectableCandidates, showGroupedSurfaceCandidates],
  );

  useEffect(() => {
    const next = modelRotationToSurfaceModelRotation(modelRotation);
    if (isSameSurfaceModelRotation(notifiedModelRotationRef.current, next)) {
      return;
    }
    notifiedModelRotationRef.current = next;
    onUpdateModelRotation?.(next);
  }, [modelRotation, onUpdateModelRotation]);

  const setOrbitControlsEnabled = useCallback(
    (enabled: boolean) => {
      const orbit = controls as { enabled?: boolean; update?: () => void } | null;
      if (orbit && "enabled" in orbit) {
        orbit.enabled = enabled;
        orbit.update?.();
      }
    },
    [controls],
  );

  const fitModelView = useCallback(
    (view?: ViewDirection) => {
      if (!model || !groupRef.current) {
        return;
      }
      groupRef.current.updateMatrixWorld(true);
      const box = new THREE.Box3().setFromObject(groupRef.current);
      if (box.isEmpty()) {
        return;
      }
      const center = new THREE.Vector3();
      const size = new THREE.Vector3();
      box.getCenter(center);
      box.getSize(size);
      const radius = Math.max(size.x, size.y, size.z, 1) / 2;
      const fov = restoreDefaultCameraFov();
      const dist = computeFitDistance(radius, fov) * 1.55;
      const direction = new THREE.Vector3(0, -1, 1).normalize();
      const diagonalDirection = view ? getViewCubeDiagonalDirection(view) : null;
      if (diagonalDirection) {
        direction.copy(diagonalDirection);
        camera.up.set(0, 0, 1);
      } else if (view === "top") {
        direction.set(0, 0, 1);
        camera.up.set(0, 1, 0);
      } else if (view === "bottom") {
        direction.set(0, 0, -1);
        camera.up.set(0, 1, 0);
      } else if (view === "front") {
        direction.set(0, -1, 0);
        camera.up.set(0, 0, 1);
      } else if (view === "back") {
        direction.set(0, 1, 0);
        camera.up.set(0, 0, 1);
      } else if (view === "left") {
        direction.set(-1, 0, 0);
        camera.up.set(0, 0, 1);
      } else if (view === "right") {
        direction.set(1, 0, 0);
        camera.up.set(0, 0, 1);
      } else {
        camera.up.set(0, 1, 0);
      }
      camera.position.copy(center).addScaledVector(direction, dist);
      camera.lookAt(center);
      ensureCameraDepthClipping(camera, dist, radius);
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
    },
    [camera, controls, invalidate, model, restoreDefaultCameraFov],
  );

  useEffect(() => {
    setViewDisplay((current) =>
      current.gridLines === bedGridVisible
        ? current
        : {
            ...current,
            gridLines: bedGridVisible,
          },
    );
  }, [bedGridVisible]);

  const handleToggleDisplay = useCallback((key: keyof ViewDisplayOptions) => {
    setViewDisplay((current) => {
      const nextValue = !current[key];
      if (key === "gridLines") {
        onBedGridVisibleChange?.(nextValue);
      }
      return {
        ...current,
        [key]: nextValue,
      };
    });
  }, [onBedGridVisibleChange]);

  const handleViewCommand = useCallback(
    (view: ViewDirection) => {
      setLastRequestedView(view);
      fitModelView(view);
    },
    [fitModelView],
  );

  const handleSelectionModeChange = useCallback(
    (mode: SurfaceSelectionMode) => {
      setSurfaceSelectionMode(mode);
      setHoveredCandidateId(null);
      setHoveredTriangleFaceIndex(null);
      invalidate();
    },
    [invalidate],
  );

  const handleSelectCandidate = useCallback(
    (faceIndex: number, candidateId: string) => {
      if (!selecting) {
        const timestamp = Date.now();
        const lastSelection = lastCandidateSelectionRef.current;
        if (
          lastSelection &&
          lastSelection.faceIndex === faceIndex &&
          lastSelection.candidateId === candidateId &&
          timestamp - lastSelection.timestamp < 250
        ) {
          return;
        }
        lastCandidateSelectionRef.current = { faceIndex, candidateId, timestamp };
        onSelectFace(faceIndex, candidateId);
        setForceReselect(false);
      }
    },
    [onSelectFace, selecting],
  );

  useEffect(() => {
    const canvas =
      gl?.domElement ??
      (typeof document !== "undefined" ? document.querySelector("canvas") : null);
    if (
      !canvas ||
      !showSurfaceCandidates ||
      surfaceSelectionMode !== "grouped" ||
      selectableCandidates.length === 0 ||
      selecting
    ) {
      return undefined;
    }

    const findCandidateFromCanvasPointer = (event: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      if (
        event.clientX < rect.left ||
        event.clientX > rect.left + rect.width ||
        event.clientY < rect.top ||
        event.clientY > rect.top + rect.height
      ) {
        return null;
      }
      return findSelectableCandidateFromPointerRay(
        getPointerRayFromScreenPoint(
          { x: event.clientX, y: event.clientY },
          camera,
          {
            left: rect.left,
            top: rect.top,
            width: rect.width,
            height: rect.height,
          },
        ),
        selectableCandidates,
        modelOffset,
        modelEuler,
        modelPivot,
      );
    };

    const handleCanvasPointerMove = (event: PointerEvent) => {
      if (event.defaultPrevented) {
        return;
      }
      const candidate = findCandidateFromCanvasPointer(event);
      const nextCandidateId = candidate?.id ?? null;
      if (nextCandidateId !== hoveredCandidateId) {
        setHoveredCandidateId(nextCandidateId);
        invalidate();
      }
    };

    const handleCanvasPointerDown = (event: PointerEvent) => {
      if (event.defaultPrevented || event.button !== 0) {
        return;
      }
      const candidate = findCandidateFromCanvasPointer(event);
      if (!candidate) {
        return;
      }
      event.preventDefault();
      handleSelectCandidate(candidate.faceIndex, candidate.id);
    };

    const handleCanvasPointerLeave = () => {
      if (hoveredCandidateId !== null) {
        setHoveredCandidateId(null);
        invalidate();
      }
    };

    canvas.addEventListener("pointermove", handleCanvasPointerMove);
    canvas.addEventListener("pointerdown", handleCanvasPointerDown);
    canvas.addEventListener("pointerleave", handleCanvasPointerLeave);
    return () => {
      canvas.removeEventListener("pointermove", handleCanvasPointerMove);
      canvas.removeEventListener("pointerdown", handleCanvasPointerDown);
      canvas.removeEventListener("pointerleave", handleCanvasPointerLeave);
    };
  }, [
    camera,
    gl,
    handleSelectCandidate,
    hoveredCandidateId,
    invalidate,
    modelEuler,
    modelOffset,
    modelPivot,
    selectableCandidates,
    selecting,
    showSurfaceCandidates,
    surfaceSelectionMode,
  ]);

  const handleChangeRotationAxis = useCallback(
    (axis: RotationAxis, degrees: number) => {
      commitModelRotation((current) => setRotationAxisDegrees(current, axis, degrees));
      setModelRotationRelativeInput({ ...DEFAULT_MODEL_RELATIVE_ROTATION_INPUT });
      setActiveRotationAxis(null);
      setHoveredRotationAxis(null);
      setFocusedRotationAxis(axis);
      setRotationTooltipPoint(null);
      invalidate();
    },
    [commitModelRotation, invalidate],
  );

  const handleChangeRelativeRotationAxis = useCallback(
    (axis: RotationAxis, degrees: number) => {
      const nextDegrees = Number.isFinite(degrees) ? degrees : 0;
      const previousDegrees = modelRotationRelativeInput[axis];
      const deltaDegrees = nextDegrees - previousDegrees;
      commitModelRotation((current) =>
        setRotationAxisDegrees(
          current,
          axis,
          THREE.MathUtils.radToDeg(current[axis]) + deltaDegrees,
        ),
      );
      setModelRotationRelativeInput((current) => ({
        ...current,
        [axis]: nextDegrees,
      }));
      setActiveRotationAxis(null);
      setHoveredRotationAxis(null);
      setFocusedRotationAxis(axis);
      setRotationTooltipPoint(null);
      invalidate();
    },
    [commitModelRotation, invalidate, modelRotationRelativeInput],
  );

  const handleFocusRotationAxis = useCallback(
    (axis: RotationAxis) => {
      setActiveRotationAxis(null);
      setHoveredRotationAxis(null);
      setFocusedRotationAxis(axis);
      setRotationTooltipPoint(null);
      invalidate();
    },
    [invalidate],
  );

  const handleQuickRotateAxis = useCallback(
    (axis: RotationAxis, degrees: number) => {
      const deltaDegrees = Number.isFinite(degrees) ? degrees : 0;
      commitModelRotation((current) =>
        setRotationAxisDegrees(
          current,
          axis,
          THREE.MathUtils.radToDeg(current[axis]) + deltaDegrees,
        ),
      );
      setModelRotationRelativeInput((current) => ({
        ...current,
        [axis]: current[axis] + deltaDegrees,
      }));
      setActiveRotationAxis(null);
      setHoveredRotationAxis(null);
      setFocusedRotationAxis(axis);
      setRotationTooltipPoint(null);
      invalidate();
    },
    [commitModelRotation, invalidate],
  );

  const handleResetModelRotationToBaseline = useCallback(() => {
    commitModelRotation(() => modelRotationBaseline);
    setModelRotationRelativeInput({ ...DEFAULT_MODEL_RELATIVE_ROTATION_INPUT });
    setFocusedRotationAxis(null);
    setRotationTooltipPoint(null);
    invalidate();
  }, [commitModelRotation, invalidate, modelRotationBaseline]);

  const handleResetModelRotationToZero = useCallback(() => {
    commitModelRotation(() => DEFAULT_MODEL_ROTATION);
    setModelRotationRelativeInput({ ...DEFAULT_MODEL_RELATIVE_ROTATION_INPUT });
    setFocusedRotationAxis(null);
    setRotationTooltipPoint(null);
    invalidate();
  }, [commitModelRotation, invalidate]);

  const handleChangeArtworkRotation = useCallback(
    (_axis: RotationAxis, degrees: number) => {
      if (!Number.isFinite(degrees)) {
        return;
      }
      onUpdatePlacement?.({ rotation_deg: degrees });
      setArtworkRotationRelativeInput(0);
      invalidate();
    },
    [invalidate, onUpdatePlacement],
  );

  const handleChangeRelativeArtworkRotation = useCallback(
    (_axis: RotationAxis, degrees: number) => {
      const nextDegrees = Number.isFinite(degrees) ? degrees : 0;
      const deltaDegrees = nextDegrees - artworkRotationRelativeInput;
      onUpdatePlacement?.({ rotation_deg: placement.rotation_deg + deltaDegrees });
      setArtworkRotationRelativeInput(nextDegrees);
      invalidate();
    },
    [artworkRotationRelativeInput, invalidate, onUpdatePlacement, placement.rotation_deg],
  );

  const handleQuickRotateArtwork = useCallback(
    (_axis: RotationAxis, degrees: number) => {
      const deltaDegrees = Number.isFinite(degrees) ? degrees : 0;
      onUpdatePlacement?.({ rotation_deg: placement.rotation_deg + deltaDegrees });
      setArtworkRotationRelativeInput((current) => current + deltaDegrees);
      invalidate();
    },
    [invalidate, onUpdatePlacement, placement.rotation_deg],
  );

  const handleResetArtworkRotationToBaseline = useCallback(() => {
    onUpdatePlacement?.({ rotation_deg: artworkRotationBaseline });
    setArtworkRotationRelativeInput(0);
    invalidate();
  }, [artworkRotationBaseline, invalidate, onUpdatePlacement]);

  const handleResetArtworkRotationToZero = useCallback(() => {
    onUpdatePlacement?.({ rotation_deg: 0 });
    setArtworkRotationRelativeInput(0);
    invalidate();
  }, [invalidate, onUpdatePlacement]);

  const handleSetTool = useCallback(
    (tool: SurfaceTool) => {
      if (tool === "modelRotate" && activeTool !== "modelRotate") {
        setModelRotationBaseline(modelRotation);
        setModelRotationRelativeInput({ ...DEFAULT_MODEL_RELATIVE_ROTATION_INPUT });
        setFocusedRotationAxis(null);
        setRotationTooltipPoint(null);
        modelRotateReturnForceReselectRef.current = forceReselect;
        setActiveTool(tool);
        return;
      }
      if (tool === "rotate" && activeTool !== "rotate") {
        setArtworkRotationBaseline(placement.rotation_deg);
        setArtworkRotationRelativeInput(0);
      }
      setForceReselect(tool === "select" && Boolean(resolvedSurface));
      setActiveTool(tool);
    },
    [activeTool, forceReselect, modelRotation, placement.rotation_deg, resolvedSurface],
  );

  const finishModelRotateMode = useCallback(() => {
    modelRotateDragRef.current = null;
    setActiveRotationAxis(null);
    setHoveredRotationAxis(null);
    setFocusedRotationAxis(null);
    setRotationTooltipPoint(null);
    setForceReselect(modelRotateReturnForceReselectRef.current);
    setActiveTool("select");
    setOrbitControlsEnabled(true);
    invalidate();
  }, [invalidate, setOrbitControlsEnabled]);

  const finishArtworkRotateMode = useCallback(() => {
    setArtworkRotationRelativeInput(0);
    setActiveTool("move");
    setOrbitControlsEnabled(true);
    invalidate();
  }, [invalidate, setOrbitControlsEnabled]);

  useEffect(() => {
    material.color.set(modelBodyColor);
    material.needsUpdate = true;
    if (model?.kind === "object") {
      updateSurfaceMaterialColor(model.object, material.color);
    }
    invalidate();
  }, [invalidate, material, model, modelBodyColor]);

  useEffect(() => {
    return () => {
      material.dispose();
    };
  }, [material]);

  useEffect(() => {
    if (hoveredCandidateId === null) {
      return;
    }
    if (
      !showSurfaceCandidates ||
      !showGroupedSurfaceCandidates ||
      !selectableCandidates.some((candidate) => candidate.id === hoveredCandidateId)
    ) {
      setHoveredCandidateId(null);
    }
  }, [hoveredCandidateId, selectableCandidates, showGroupedSurfaceCandidates, showSurfaceCandidates]);

  useEffect(() => {
    if (hoveredTriangleFaceIndex === null) {
      return;
    }
    if (!showSurfaceCandidates || surfaceSelectionMode !== "triangle" || model?.kind !== "stl") {
      setHoveredTriangleFaceIndex(null);
    }
  }, [hoveredTriangleFaceIndex, model, showSurfaceCandidates, surfaceSelectionMode]);

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
    setModelRotation(DEFAULT_MODEL_ROTATION);
    setModelRotationBaseline(DEFAULT_MODEL_ROTATION);
    setModelRotationRelativeInput({ ...DEFAULT_MODEL_RELATIVE_ROTATION_INPUT });
    setActiveRotationAxis(null);
    setHoveredRotationAxis(null);
    setFocusedRotationAxis(null);
    setRotationTooltipPoint(null);
    setSurfaceSelectionMode("grouped");
    setHoveredTriangleFaceIndex(null);
    modelRotateReturnForceReselectRef.current = false;
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
          const centered = centerModel(root);
          handleLoaded({
            kind: "object",
            object: centered.group,
            offset: centered.offset,
          });
          return;
        }
        const cached = await loadCachedStlPreviewModel(file);
        handleLoaded(cloneCachedStlPreviewModel(cached));
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
  }, [file, invalidate, material]);

  useEffect(() => {
    if (!resolvedSurface) {
      faceUpOrientedSurfaceRef.current = null;
      skipFocusAfterFaceUpOrientationRef.current = null;
      return;
    }
    if (faceUpOrientedSurfaceRef.current === resolvedSurface) {
      return;
    }
    const nextRotation = getModelRotationWithSurfaceFacingUp(
      resolvedSurface.frame.normal,
      modelRotation,
    );
    faceUpOrientedSurfaceRef.current = resolvedSurface;
    if (!nextRotation) {
      return;
    }
    skipFocusAfterFaceUpOrientationRef.current = resolvedSurface;
    commitModelRotation(() => nextRotation);
    setModelRotationRelativeInput({ ...DEFAULT_MODEL_RELATIVE_ROTATION_INPUT });
    invalidate();
  }, [commitModelRotation, invalidate, modelRotation, resolvedSurface]);

  useEffect(() => {
    if (shouldLockOrbitControls(activeTool)) {
      setOrbitControlsEnabled(false);
      return () => setOrbitControlsEnabled(true);
    }
    setOrbitControlsEnabled(true);
    return undefined;
  }, [activeTool, setOrbitControlsEnabled]);

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
    const fov = restoreDefaultCameraFov();
    const dist = computeFitDistance(radius, fov) * 1.55;
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
  }, [camera, controls, invalidate, model, restoreDefaultCameraFov]);

  const handleSelectPointerDown = useCallback(
    (event: ModelRotatePointerEvent) => {
      if (!showSurfaceCandidates || selecting) {
        return;
      }

      if (surfaceSelectionMode === "grouped" && selectableCandidates.length > 0) {
        const point = getPointerPoint(event);
        if (point) {
          const candidate = findSelectableCandidateFromModelPoint(
            point,
            selectableCandidates,
            modelOffset,
            modelEuler,
            modelPivot,
          );
          if (candidate) {
            event.stopPropagation();
            handleSelectCandidate(candidate.faceIndex, candidate.id);
          }
        }
        return;
      }

      const faceIndex = getPointerFaceIndex(event);
      if (faceIndex === null) {
        return;
      }

      event.stopPropagation();
      onSelectFace(faceIndex);
    },
    [
      handleSelectCandidate,
      modelEuler,
      modelOffset,
      modelPivot,
      onSelectFace,
      selectableCandidates,
      selecting,
      showSurfaceCandidates,
      surfaceSelectionMode,
    ],
  );

  const handleSelectPointerMove = useCallback(
    (event: ModelRotatePointerEvent) => {
      if (!showSurfaceCandidates || selecting) {
        if (hoveredCandidateId !== null) {
          setHoveredCandidateId(null);
          invalidate();
        }
        if (hoveredTriangleFaceIndex !== null) {
          setHoveredTriangleFaceIndex(null);
          invalidate();
        }
        return;
      }

      if (surfaceSelectionMode === "grouped") {
        const point = getPointerPoint(event);
        const candidate =
          point && selectableCandidates.length > 0
            ? findSelectableCandidateFromModelPoint(
                point,
                selectableCandidates,
                modelOffset,
                modelEuler,
                modelPivot,
              )
            : null;
        const nextCandidateId = candidate?.id ?? null;
        if (nextCandidateId !== hoveredCandidateId) {
          setHoveredCandidateId(nextCandidateId);
          invalidate();
        }
        if (candidate) {
          event.stopPropagation();
        }
        if (hoveredTriangleFaceIndex !== null) {
          setHoveredTriangleFaceIndex(null);
          invalidate();
        }
        return;
      }

      if (model?.kind !== "stl") {
        return;
      }

      const faceIndex = getPointerFaceIndex(event);
      if (faceIndex === null) {
        if (hoveredTriangleFaceIndex !== null) {
          setHoveredTriangleFaceIndex(null);
          invalidate();
        }
        return;
      }

      event.stopPropagation();
      setHoveredTriangleFaceIndex((current) => (current === faceIndex ? current : faceIndex));
      invalidate();
    },
    [
      hoveredCandidateId,
      hoveredTriangleFaceIndex,
      invalidate,
      model,
      modelEuler,
      modelOffset,
      modelPivot,
      selectableCandidates,
      selecting,
      showSurfaceCandidates,
      surfaceSelectionMode,
    ],
  );

  const handleModelRotatePointerMove = useCallback(
    (event: ModelRotatePointerEvent) => {
      const drag = modelRotateDragRef.current;
      if (!drag) {
        return;
      }
      event.stopPropagation();
      const pointerResult = getRotationPointerResultFromPointerEvent(event, drag);
      const startRotationDegrees = THREE.MathUtils.radToDeg(getModelRotationValue(drag.startRotation, drag.axis));
      const fallbackDelta =
        drag.axis === "x"
          ? (event.clientY ?? drag.startClientY) - drag.startClientY
          : (event.clientX ?? drag.startClientX) - drag.startClientX;
      const nextDegrees =
        pointerResult && drag.startPointerDegrees !== null
          ? computeModelRotationDragDegrees(
              startRotationDegrees,
              drag.startPointerDegrees,
              pointerResult.degrees,
              pointerResult.distance,
              drag.ringRadius,
            )
          : snapDegrees(
              startRotationDegrees + THREE.MathUtils.radToDeg(fallbackDelta * MODEL_ROTATION_DRAG_SENSITIVITY),
              ROTATION_SNAP_DEGREES,
            );
      commitModelRotation((current) => setRotationAxisDegrees(current, drag.axis, nextDegrees));
      invalidate();
    },
    [commitModelRotation, invalidate],
  );

  const handleAxisRotatePointerDown = useCallback(
    (axis: RotationAxis, event: ModelRotatePointerEvent) => {
      if (activeTool !== "modelRotate") {
        return;
      }
      event.stopPropagation();
      const pointerId = event.pointerId;
      if (typeof pointerId === "number") {
        event.target?.setPointerCapture?.(pointerId);
      }
      const ringRadius = getRotationGizmoRadius(modelBounds.radius);
      const frame = getRotationPlaneFrame(axis, rotationGizmoCenter);
      const drag: ModelRotationDragState = {
        axis,
        startClientX: event.clientX ?? 0,
        startClientY: event.clientY ?? 0,
        startRotation: { ...modelRotation },
        startPointerDegrees: null,
        ringRadius,
        ...frame,
      };
      drag.startPointerDegrees = getRotationPointerResultFromPointerEvent(event, drag)?.degrees ?? null;
      modelRotateDragRef.current = drag;
      setActiveRotationAxis(axis);
      setFocusedRotationAxis(null);
      setModelRotationRelativeInput({ ...DEFAULT_MODEL_RELATIVE_ROTATION_INPUT });
      setOrbitControlsEnabled(false);
    },
    [activeTool, modelBounds.radius, modelRotation, rotationGizmoCenter, setOrbitControlsEnabled],
  );

  const finishModelRotateDrag = useCallback(
    (event: ModelRotatePointerEvent) => {
      if (!modelRotateDragRef.current) {
        return;
      }
      event.stopPropagation();
      const pointerId = event.pointerId;
      if (typeof pointerId === "number") {
        event.target?.releasePointerCapture?.(pointerId);
      }
      modelRotateDragRef.current = null;
      setActiveRotationAxis(null);
      setOrbitControlsEnabled(true);
      invalidate();
    },
    [invalidate, setOrbitControlsEnabled],
  );

  useEffect(() => {
    if (activeTool !== "modelRotate") {
      return undefined;
    }
    const canvas = gl?.domElement;
    if (!canvas) {
      return undefined;
    }

    const stopNativeEvent = (event: PointerEvent) => {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
    };
    const viewportFromCanvas = (): ScreenRect => {
      const rect = canvas.getBoundingClientRect();
      return {
        left: rect.left,
        top: rect.top,
        width: rect.width,
        height: rect.height,
      };
    };
    const modelEventFromNative = (event: PointerEvent, viewport: ScreenRect): ModelRotatePointerEvent => ({
      stopPropagation: () => stopNativeEvent(event),
      ray: getPointerRayFromScreenPoint({ x: event.clientX, y: event.clientY }, camera, viewport),
      clientX: event.clientX,
      clientY: event.clientY,
      pointerId: event.pointerId,
      target: canvas,
    });

    const handleNativePointerDown = (event: PointerEvent) => {
      if (event.button !== 0 || modelRotateDragRef.current) {
        return;
      }
      const viewport = viewportFromCanvas();
      const axis = findNearestRotationAxisScreenHit(
        { x: event.clientX, y: event.clientY },
        rotationGizmoCenter,
        getRotationGizmoRadius(modelBounds.radius),
        camera,
        viewport,
      );
      if (!axis) {
        return;
      }
      handleAxisRotatePointerDown(axis, modelEventFromNative(event, viewport));
      setRotationTooltipPoint({ x: event.clientX, y: event.clientY });
      canvas.style.cursor = "grabbing";
      stopNativeEvent(event);
    };

    const handleNativePointerMove = (event: PointerEvent) => {
      if (!modelRotateDragRef.current) {
        const viewport = viewportFromCanvas();
        const axis = findNearestRotationAxisScreenHit(
          { x: event.clientX, y: event.clientY },
          rotationGizmoCenter,
          getRotationGizmoRadius(modelBounds.radius),
          camera,
          viewport,
        );
        setHoveredRotationAxis((current) => (current === axis ? current : axis));
        setRotationTooltipPoint(axis ? { x: event.clientX, y: event.clientY } : null);
        canvas.style.cursor = axis ? "grab" : "";
        return;
      }
      handleModelRotatePointerMove(modelEventFromNative(event, viewportFromCanvas()));
      setRotationTooltipPoint({ x: event.clientX, y: event.clientY });
      canvas.style.cursor = "grabbing";
      stopNativeEvent(event);
    };

    const handleNativePointerUp = (event: PointerEvent) => {
      if (!modelRotateDragRef.current) {
        return;
      }
      finishModelRotateDrag(modelEventFromNative(event, viewportFromCanvas()));
      setRotationTooltipPoint(null);
      canvas.style.cursor = "";
      stopNativeEvent(event);
    };

    const handleNativePointerLeave = () => {
      if (modelRotateDragRef.current) {
        return;
      }
      setHoveredRotationAxis(null);
      setRotationTooltipPoint(null);
      canvas.style.cursor = "";
    };

    canvas.addEventListener("pointerdown", handleNativePointerDown, true);
    canvas.addEventListener("pointermove", handleNativePointerMove, true);
    canvas.addEventListener("pointerup", handleNativePointerUp, true);
    canvas.addEventListener("pointercancel", handleNativePointerUp, true);
    canvas.addEventListener("pointerleave", handleNativePointerLeave, true);
    return () => {
      canvas.removeEventListener("pointerdown", handleNativePointerDown, true);
      canvas.removeEventListener("pointermove", handleNativePointerMove, true);
      canvas.removeEventListener("pointerup", handleNativePointerUp, true);
      canvas.removeEventListener("pointercancel", handleNativePointerUp, true);
      canvas.removeEventListener("pointerleave", handleNativePointerLeave, true);
      canvas.style.cursor = "";
    };
  }, [
    activeTool,
    camera,
    finishModelRotateDrag,
    gl?.domElement,
    handleAxisRotatePointerDown,
    handleModelRotatePointerMove,
    modelBounds.radius,
    rotationGizmoCenter,
  ]);

  const handleModelPointerDown = useCallback(
    (event: ModelRotatePointerEvent) => {
      if (activeTool === "modelRotate") {
        event.stopPropagation();
        return;
      }
      handleSelectPointerDown(event);
    },
    [activeTool, handleSelectPointerDown],
  );

  const handleModelPointerMove = useCallback(
    (event: ModelRotatePointerEvent) => {
      if (activeTool === "modelRotate") {
        return;
      }
      handleSelectPointerMove(event);
    },
    [activeTool, handleSelectPointerMove],
  );

  const handleModelPointerLeave = useCallback(
    (event: ModelRotatePointerEvent) => {
      if (hoveredCandidateId !== null) {
        event.stopPropagation();
        setHoveredCandidateId(null);
        invalidate();
      }
      if (hoveredTriangleFaceIndex !== null) {
        event.stopPropagation();
        setHoveredTriangleFaceIndex(null);
        invalidate();
      }
      finishModelRotateDrag(event);
    },
    [finishModelRotateDrag, hoveredCandidateId, hoveredTriangleFaceIndex, invalidate],
  );

  const focusSelectedSurface = useCallback(() => {
    if (!resolvedSurface) {
      return;
    }
    const center = rotateModelPointAroundPivot(
      getSurfaceWorldCenter(resolvedSurface, modelOffset),
      modelPivot,
      modelEuler,
    );
    const radius = getSurfaceFocusRadius(
      resolvedSurface.widthMm,
      resolvedSurface.heightMm,
      modelBounds.radius,
    );
    const fov = applySurfaceInspectionCameraFov();
    const dist = computeFitDistance(radius, fov) * 1.3;
    const direction = getReadableSurfaceCameraDirection(
      resolvedSurface.frame.normal.clone().applyEuler(modelEuler),
      reverseView,
    );
    const vAxis = resolvedSurface.frame.vAxis.clone().applyEuler(modelEuler).normalize();
    camera.up.copy(
      getReadableSurfaceCameraUp(
        resolvedSurface.frame.normal.clone().applyEuler(modelEuler),
        vAxis,
        direction,
      ),
    );
    camera.position.copy(center).addScaledVector(direction, dist);
    camera.lookAt(center);
    ensureCameraDepthClipping(camera, dist, Math.max(radius, modelBounds.radius));
    camera.updateProjectionMatrix();
    if (controls) {
      const orbit = controls as unknown as {
        target: THREE.Vector3;
        maxDistance: number;
        minDistance: number;
        update: () => void;
      };
      orbit.target.copy(center);
      orbit.minDistance = Math.max(1, dist * 0.06);
      orbit.maxDistance = dist * 5;
      orbit.update();
    }
    invalidate();
  }, [applySurfaceInspectionCameraFov, camera, controls, invalidate, modelBounds.radius, modelEuler, modelOffset, modelPivot, resolvedSurface, reverseView]);

  const handleFlipView = useCallback(() => {
    setReverseView((value) => !value);
  }, []);

  useEffect(() => {
    if (!resolvedSurface || selectedSurfaceNeedsFaceUpRotation || activeTool === "modelRotate") {
      return;
    }
    if (skipFocusAfterFaceUpOrientationRef.current === resolvedSurface) {
      skipFocusAfterFaceUpOrientationRef.current = null;
      return;
    }
    focusSelectedSurface();
    // Focus on selection changes or reverse-view toggles. Model rotation itself should not keep
    // pulling the camera while the user is dragging the model, except to skip the one auto-flip
    // handoff where the model moves instead of the camera.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolvedSurface, reverseView, selectedSurfaceNeedsFaceUpRotation]);

  if (!model) {
    if (loadState === "error") {
      return (
        <Html center>
          <div className="rounded-xl border border-red-300 bg-red-50 px-3 py-2 text-xs font-medium text-red-700 shadow-sm dark:border-red-800 dark:bg-red-950/80 dark:text-red-200">
            {t("model_surface_viewer_load_failed")}
          </div>
        </Html>
      );
    }
    if (loadState === "loading") {
      return (
        <Html center>
          <div className="rounded-xl border border-slate-200 bg-white/90 px-3 py-2 text-xs font-medium text-slate-700 shadow-sm dark:border-slate-700 dark:bg-slate-900/90 dark:text-slate-200">
            {t("model_surface_viewer_loading")}
          </div>
        </Html>
      );
    }
    return null;
  }

  const contextualRotationPanel = activeTool === "modelRotate" ? (
    <RotationPanel
      translate={t}
      rotation={modelRotation}
      relativeInput={modelRotationRelativeInput}
      feedbackAxis={focusedRotationAxis}
      onChangeAbsoluteAxis={handleChangeRotationAxis}
      onChangeRelativeAxis={handleChangeRelativeRotationAxis}
      onFocusAxis={handleFocusRotationAxis}
      onQuickRotateAxis={handleQuickRotateAxis}
      onResetRelative={handleResetModelRotationToBaseline}
      onResetZero={handleResetModelRotationToZero}
      onDone={finishModelRotateMode}
    />
  ) : canTransform && activeTool === "rotate" ? (
    <RotationPanel
      translate={t}
      rotation={{
        x: 0,
        y: 0,
        z: THREE.MathUtils.degToRad(placement.rotation_deg),
      }}
      relativeInput={{ x: 0, y: 0, z: artworkRotationRelativeInput }}
      feedbackAxis="z"
      axes={["z"]}
      title={t("model_surface_artwork_rotation_panel")}
      panelKind="artwork"
      axisLabels={{
        z: {
          relativeLabel: t("model_surface_artwork_rotation_relative"),
          absoluteLabel: t("model_surface_artwork_rotation_angle"),
          quickNegativeLabel: t("model_surface_artwork_rotation_minus_90"),
          quickPositiveLabel: t("model_surface_artwork_rotation_plus_90"),
        },
      }}
      relativeInputHint={t("model_surface_artwork_rotation_relative_hint")}
      absoluteInputHint={t("model_surface_artwork_rotation_angle_hint")}
      quickRotateHint={t("model_surface_artwork_rotation_quick_hint")}
      resetRelativeLabel={t("model_surface_artwork_rotation_reset_open")}
      resetRelativeHint={t("model_surface_artwork_rotation_reset_open_hint")}
      resetZeroLabel={t("model_surface_artwork_rotation_reset_zero")}
      resetZeroHint={t("model_surface_artwork_rotation_reset_zero_hint")}
      doneLabel={t("model_surface_artwork_rotation_done")}
      doneHint={t("model_surface_artwork_rotation_done_hint")}
      onChangeAbsoluteAxis={handleChangeArtworkRotation}
      onChangeRelativeAxis={handleChangeRelativeArtworkRotation}
      onFocusAxis={() => invalidate()}
      onQuickRotateAxis={handleQuickRotateArtwork}
      onResetRelative={handleResetArtworkRotationToBaseline}
      onResetZero={handleResetArtworkRotationToZero}
      onDone={finishArtworkRotateMode}
    />
  ) : undefined;

  return (
    <group>
      <ModelSurfaceToolbar
        activeTool={activeTool}
        selectionReady={selectionReady}
        reverseView={reverseView}
        canFocusSurface={canFocusSurface}
        canTransform={canTransform}
        selecting={selecting}
        candidateCount={showSurfaceCandidates ? selectableCandidates.length : 0}
        selectionMode={surfaceSelectionMode}
        placement={placement}
        display={viewDisplay}
        contextualPanel={contextualRotationPanel}
        onSetTool={handleSetTool}
        onFitArtwork={onFitArtwork}
        onUpdatePlacement={onUpdatePlacement}
        onFlipView={handleFlipView}
        onSelectionModeChange={handleSelectionModeChange}
        onToggleDisplay={handleToggleDisplay}
        onView={handleViewCommand}
        onFitView={() => fitModelView()}
      />
      <ModelViewNavigator
        display={viewDisplay}
        commandedView={lastRequestedView}
        onView={handleViewCommand}
      />
      {resolvedSurface && !forceReselect && activeTool !== "modelRotate" ? (
        <SelectedSurfacePanel surface={resolvedSurface} canTransform={canTransform} />
      ) : null}
      {canTransform && isArtworkTransformTool(activeTool) ? (
        <ArtworkPlacementReadout placement={placement} />
      ) : null}
      <CandidateSurfaceHoverReadout candidate={hoveredCandidate} />
      {activeTool === "modelRotate" ? (
        <ModelRotationTooltip
          axis={activeRotationAxis ?? hoveredRotationAxis}
          point={rotationTooltipPoint}
          rotation={modelRotation}
        />
      ) : null}
      {activeTool === "modelRotate" ? (
        <ModelRotationRings
          center={rotationGizmoCenter}
          radius={modelBounds.radius}
          rotation={modelRotation}
          activeAxis={activeRotationAxis}
          hoveredAxis={hoveredRotationAxis}
          focusedAxis={focusedRotationAxis}
          onHoverAxis={setHoveredRotationAxis}
          onStartAxisDrag={handleAxisRotatePointerDown}
          onMoveAxisDrag={handleModelRotatePointerMove}
          onFinishAxisDrag={finishModelRotateDrag}
        />
      ) : null}
      <group
        ref={groupRef}
        name="model-surface-transform"
        position={modelPivotTuple}
        rotation={modelRotationTuple}
      >
        <group name="model-surface-pivot-offset" position={inverseModelPivotTuple}>
        {model.kind === "stl" ? (
          <mesh
            name="model-surface-body"
            geometry={model.geometry}
            material={material}
            position={model.offset}
            {...getModelBodyRaycastProps(activeTool)}
            onPointerDown={activeTool === "modelRotate" ? undefined : handleModelPointerDown}
            onPointerMove={activeTool === "modelRotate" ? undefined : handleModelPointerMove}
            onPointerUp={activeTool === "modelRotate" ? undefined : finishModelRotateDrag}
            onPointerCancel={activeTool === "modelRotate" ? undefined : handleModelPointerLeave}
            onPointerLeave={activeTool === "modelRotate" ? undefined : handleModelPointerLeave}
          />
        ) : (
          <primitive
            name="model-surface-body"
            object={model.object}
            {...getModelBodyRaycastProps(activeTool)}
            onPointerDown={activeTool === "modelRotate" ? undefined : handleModelPointerDown}
            onPointerMove={activeTool === "modelRotate" ? undefined : handleModelPointerMove}
            onPointerUp={activeTool === "modelRotate" ? undefined : finishModelRotateDrag}
            onPointerCancel={activeTool === "modelRotate" ? undefined : handleModelPointerLeave}
            onPointerLeave={activeTool === "modelRotate" ? undefined : handleModelPointerLeave}
          />
        )}
        {showTriangleFacetHover && model.kind === "stl" ? (
          <TriangleFacetHover
            geometry={model.geometry}
            faceIndex={hoveredTriangleFaceIndex}
            modelOffset={modelOffset}
          />
        ) : null}
        {showGroupedSurfaceCandidates
          ? selectableCandidates.map((candidate) => (
              <CandidateSurfacePlane
                key={candidate.id}
                candidate={candidate}
                modelOffset={modelOffset}
                highlighted={hoveredCandidateId === candidate.id}
              />
            ))
          : null}
        {resolvedSurface && !forceReselect ? (
          <SurfaceArtworkPlane
            surface={resolvedSurface}
            modelOffset={modelOffset}
            modelEuler={modelEuler}
            modelPivot={modelPivot}
            artworkUrl={artworkUrl}
            placement={placement}
            activeTool={activeTool}
            onUpdatePlacement={onUpdatePlacement}
          />
        ) : null}
        </group>
      </group>
    </group>
  );
}
