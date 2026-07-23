import * as THREE from "three";

export type ViewCubeFaceDirection = "top" | "bottom" | "front" | "back" | "left" | "right";
export type ViewCubeEdgeDirection =
  | "right-front"
  | "left-front"
  | "right-back"
  | "left-back"
  | "right-top"
  | "right-bottom"
  | "left-top"
  | "left-bottom"
  | "front-top"
  | "front-bottom"
  | "back-top"
  | "back-bottom";
export type ViewCubeCornerDirection =
  | "right-front-top"
  | "left-front-top"
  | "right-back-top"
  | "left-back-top"
  | "right-front-bottom"
  | "left-front-bottom"
  | "right-back-bottom"
  | "left-back-bottom";
export type ViewDirection =
  | "default"
  | ViewCubeFaceDirection
  | ViewCubeEdgeDirection
  | ViewCubeCornerDirection;
export type OrthographicViewDirection = ViewCubeFaceDirection;

export interface ViewCubeFaceHitZone {
  view: OrthographicViewDirection;
  polygon: string;
  visible: boolean;
  zIndex: number;
}

export interface ViewCubeScreenHitZone<TView extends string> {
  view: TView;
  visible: boolean;
  left: number;
  top: number;
  width: number;
  height: number;
  zIndex: number;
}

const VIEW_DIRECTION_ALIGNMENT_THRESHOLD = 0.97;
export const VIEW_CUBE_SHELL_SIZE_PX = 112;
const VIEW_CUBE_HALF_SIZE_PX = 32;
const VIEW_CUBE_CSS_PERSPECTIVE_PX = 320;

export const VIEW_CUBE_CORNERS: Array<{
  view: ViewCubeCornerDirection;
  labelKey: string;
  className: string;
  direction: [number, number, number];
}> = [
  {
    view: "right-front-top",
    labelKey: "model_surface_view_corner_right_front_top",
    className: "right-[-16px] top-[-16px]",
    direction: [1, -1, 1],
  },
  {
    view: "left-front-top",
    labelKey: "model_surface_view_corner_left_front_top",
    className: "left-[-16px] top-[-16px]",
    direction: [-1, -1, 1],
  },
  {
    view: "right-back-top",
    labelKey: "model_surface_view_corner_right_back_top",
    className: "right-[-16px] top-[16px]",
    direction: [1, 1, 1],
  },
  {
    view: "left-back-top",
    labelKey: "model_surface_view_corner_left_back_top",
    className: "left-[-16px] top-[16px]",
    direction: [-1, 1, 1],
  },
  {
    view: "right-front-bottom",
    labelKey: "model_surface_view_corner_right_front_bottom",
    className: "right-[-16px] bottom-[-16px]",
    direction: [1, -1, -1],
  },
  {
    view: "left-front-bottom",
    labelKey: "model_surface_view_corner_left_front_bottom",
    className: "left-[-16px] bottom-[-16px]",
    direction: [-1, -1, -1],
  },
  {
    view: "right-back-bottom",
    labelKey: "model_surface_view_corner_right_back_bottom",
    className: "right-[16px] bottom-[-16px]",
    direction: [1, 1, -1],
  },
  {
    view: "left-back-bottom",
    labelKey: "model_surface_view_corner_left_back_bottom",
    className: "left-[16px] bottom-[-16px]",
    direction: [-1, 1, -1],
  },
];

export const VIEW_CUBE_EDGES: Array<{
  view: ViewCubeEdgeDirection;
  labelKey: string;
  className: string;
  direction: [number, number, number];
}> = [
  {
    view: "right-front",
    labelKey: "model_surface_view_edge_right_front",
    className: "right-[-44px] top-[28px]",
    direction: [1, -1, 0],
  },
  {
    view: "left-front",
    labelKey: "model_surface_view_edge_left_front",
    className: "left-[-44px] top-[28px]",
    direction: [-1, -1, 0],
  },
  {
    view: "right-back",
    labelKey: "model_surface_view_edge_right_back",
    className: "right-[-44px] top-[44px]",
    direction: [1, 1, 0],
  },
  {
    view: "left-back",
    labelKey: "model_surface_view_edge_left_back",
    className: "left-[-44px] top-[44px]",
    direction: [-1, 1, 0],
  },
  {
    view: "right-top",
    labelKey: "model_surface_view_edge_right_top",
    className: "left-[44px] top-[-20px]",
    direction: [1, 0, 1],
  },
  {
    view: "right-bottom",
    labelKey: "model_surface_view_edge_right_bottom",
    className: "left-[44px] bottom-[-20px]",
    direction: [1, 0, -1],
  },
  {
    view: "left-top",
    labelKey: "model_surface_view_edge_left_top",
    className: "left-[4px] top-[-20px]",
    direction: [-1, 0, 1],
  },
  {
    view: "left-bottom",
    labelKey: "model_surface_view_edge_left_bottom",
    className: "left-[4px] bottom-[-20px]",
    direction: [-1, 0, -1],
  },
  {
    view: "front-top",
    labelKey: "model_surface_view_edge_front_top",
    className: "left-[64px] top-[-20px]",
    direction: [0, -1, 1],
  },
  {
    view: "front-bottom",
    labelKey: "model_surface_view_edge_front_bottom",
    className: "left-[64px] bottom-[-20px]",
    direction: [0, -1, -1],
  },
  {
    view: "back-top",
    labelKey: "model_surface_view_edge_back_top",
    className: "left-[24px] top-[-20px]",
    direction: [0, 1, 1],
  },
  {
    view: "back-bottom",
    labelKey: "model_surface_view_edge_back_bottom",
    className: "left-[24px] bottom-[-20px]",
    direction: [0, 1, -1],
  },
];

export function inferOrthographicViewFromCamera(
  camera: THREE.Camera,
): OrthographicViewDirection | null {
  const viewVector = new THREE.Vector3();
  camera.updateMatrixWorld(true);
  camera.getWorldDirection(viewVector);
  viewVector.negate().normalize();

  const axisValues = [
    { axis: "x" as const, value: viewVector.x },
    { axis: "y" as const, value: viewVector.y },
    { axis: "z" as const, value: viewVector.z },
  ];
  const dominant = axisValues.reduce((best, item) =>
    Math.abs(item.value) > Math.abs(best.value) ? item : best,
  );
  if (Math.abs(dominant.value) < VIEW_DIRECTION_ALIGNMENT_THRESHOLD) {
    return null;
  }
  if (dominant.axis === "z") {
    return dominant.value > 0 ? "top" : "bottom";
  }
  if (dominant.axis === "y") {
    return dominant.value < 0 ? "front" : "back";
  }
  return dominant.value < 0 ? "left" : "right";
}

export function isViewCubeFaceDirection(view: ViewDirection): view is ViewCubeFaceDirection {
  return (
    view === "top"
    || view === "bottom"
    || view === "front"
    || view === "back"
    || view === "left"
    || view === "right"
  );
}

export function getViewCubeDiagonalDirection(view: ViewDirection): THREE.Vector3 | null {
  const direction = [...VIEW_CUBE_EDGES, ...VIEW_CUBE_CORNERS].find((item) => item.view === view);
  return direction ? new THREE.Vector3(...direction.direction).normalize() : null;
}

export function getViewCubeCameraTransform(camera: THREE.Camera): string {
  const orthographicView = inferOrthographicViewFromCamera(camera);
  if (orthographicView) {
    const faceTransform: Record<OrthographicViewDirection, string> = {
      top: "rotateX(-90.00deg) rotateY(0.00deg) rotateZ(0.00deg)",
      bottom: "rotateX(90.00deg) rotateY(0.00deg) rotateZ(0.00deg)",
      front: "rotateX(0.00deg) rotateY(0.00deg) rotateZ(0.00deg)",
      back: "rotateX(0.00deg) rotateY(180.00deg) rotateZ(0.00deg)",
      left: "rotateX(0.00deg) rotateY(90.00deg) rotateZ(0.00deg)",
      right: "rotateX(0.00deg) rotateY(-90.00deg) rotateZ(0.00deg)",
    };
    return faceTransform[orthographicView];
  }

  camera.updateMatrixWorld(true);
  const orientation = camera.quaternion.clone().invert().normalize();
  const euler = new THREE.Euler().setFromQuaternion(orientation, "YXZ");
  const x = THREE.MathUtils.radToDeg(euler.x).toFixed(2);
  const y = THREE.MathUtils.radToDeg(euler.y).toFixed(2);
  const z = THREE.MathUtils.radToDeg(euler.z).toFixed(2);
  return `rotateX(${x}deg) rotateY(${y}deg) rotateZ(${z}deg)`;
}

const VIEW_CUBE_FACE_GEOMETRY: Record<
  OrthographicViewDirection,
  { normal: [number, number, number]; corners: Array<[number, number, number]> }
> = {
  front: {
    normal: [0, 0, 1],
    corners: [
      [-1, -1, 1],
      [1, -1, 1],
      [1, 1, 1],
      [-1, 1, 1],
    ],
  },
  back: {
    normal: [0, 0, -1],
    corners: [
      [1, -1, -1],
      [-1, -1, -1],
      [-1, 1, -1],
      [1, 1, -1],
    ],
  },
  right: {
    normal: [1, 0, 0],
    corners: [
      [1, -1, 1],
      [1, -1, -1],
      [1, 1, -1],
      [1, 1, 1],
    ],
  },
  left: {
    normal: [-1, 0, 0],
    corners: [
      [-1, -1, -1],
      [-1, -1, 1],
      [-1, 1, 1],
      [-1, 1, -1],
    ],
  },
  top: {
    normal: [0, -1, 0],
    corners: [
      [-1, -1, -1],
      [1, -1, -1],
      [1, -1, 1],
      [-1, -1, 1],
    ],
  },
  bottom: {
    normal: [0, 1, 0],
    corners: [
      [-1, 1, 1],
      [1, 1, 1],
      [1, 1, -1],
      [-1, 1, -1],
    ],
  },
};

function createViewCubeTransformMatrix(transform: string): THREE.Matrix4 {
  const matrix = new THREE.Matrix4();
  const rotationPattern = /rotate([XYZ])\((-?\d+(?:\.\d+)?)deg\)/g;
  for (const match of transform.matchAll(rotationPattern)) {
    const radians = THREE.MathUtils.degToRad(Number(match[2]));
    const rotation = new THREE.Matrix4();
    if (match[1] === "X") {
      rotation.makeRotationX(radians);
    } else if (match[1] === "Y") {
      rotation.makeRotationY(radians);
    } else {
      rotation.makeRotationZ(radians);
    }
    matrix.multiply(rotation);
  }
  return matrix;
}

function projectViewCubePoint(point: THREE.Vector3): { x: number; y: number; z: number } {
  const scale = VIEW_CUBE_CSS_PERSPECTIVE_PX / (VIEW_CUBE_CSS_PERSPECTIVE_PX - point.z);
  const center = VIEW_CUBE_SHELL_SIZE_PX / 2;
  return {
    x: center + point.x * scale,
    y: center + point.y * scale,
    z: point.z,
  };
}

function formatViewCubeClipPolygon(points: Array<{ x: number; y: number }>): string {
  const polygon = points
    .map(({ x, y }) => {
      const px = (x / VIEW_CUBE_SHELL_SIZE_PX) * 100;
      const py = (y / VIEW_CUBE_SHELL_SIZE_PX) * 100;
      return `${px.toFixed(2)}% ${py.toFixed(2)}%`;
    })
    .join(", ");
  return `polygon(${polygon})`;
}

export function getViewCubeFaceHitZones(cameraTransform: string): ViewCubeFaceHitZone[] {
  const matrix = createViewCubeTransformMatrix(cameraTransform);
  const normalMatrix = new THREE.Matrix3().setFromMatrix4(matrix);
  const zones = Object.entries(VIEW_CUBE_FACE_GEOMETRY).map(([view, geometry]) => {
    const normal = new THREE.Vector3(...geometry.normal).applyMatrix3(normalMatrix).normalize();
    const transformedPoints = geometry.corners.map((corner) =>
      new THREE.Vector3(
        corner[0] * VIEW_CUBE_HALF_SIZE_PX,
        corner[1] * VIEW_CUBE_HALF_SIZE_PX,
        corner[2] * VIEW_CUBE_HALF_SIZE_PX,
      ).applyMatrix4(matrix),
    );
    const projectedPoints = transformedPoints.map(projectViewCubePoint);
    const depth = projectedPoints.reduce((sum, point) => sum + point.z, 0) / projectedPoints.length;
    return {
      view: view as OrthographicViewDirection,
      polygon: formatViewCubeClipPolygon(projectedPoints),
      visible: normal.z > 0.02,
      zIndex: 45,
      depth,
    };
  });

  const visibleZones = zones
    .filter((zone) => zone.visible)
    .sort((a, b) => a.depth - b.depth);
  const zIndexByView = new Map<OrthographicViewDirection, number>(
    visibleZones.map((zone, index) => [zone.view, 45 + index]),
  );

  return zones.map(({ depth: _depth, ...zone }) => ({
    ...zone,
    zIndex: zIndexByView.get(zone.view) ?? 0,
  }));
}

function getViewCubeScreenHitZones<TView extends string>(
  items: Array<{ view: TView; direction: [number, number, number] }>,
  cameraTransform: string,
  sizePx: number,
): Array<ViewCubeScreenHitZone<TView>> {
  const matrix = createViewCubeTransformMatrix(cameraTransform);
  const halfSize = sizePx / 2;
  return items.map((item) => {
    const point = new THREE.Vector3(...item.direction)
      .normalize()
      .multiplyScalar(VIEW_CUBE_HALF_SIZE_PX)
      .applyMatrix4(matrix);
    const projected = projectViewCubePoint(point);
    const left = THREE.MathUtils.clamp(
      projected.x - halfSize,
      0,
      VIEW_CUBE_SHELL_SIZE_PX - sizePx,
    );
    const top = THREE.MathUtils.clamp(
      projected.y - halfSize,
      0,
      VIEW_CUBE_SHELL_SIZE_PX - sizePx,
    );
    return {
      view: item.view,
      visible: projected.z > -VIEW_CUBE_HALF_SIZE_PX * 0.65,
      left,
      top,
      width: sizePx,
      height: sizePx,
      zIndex: Math.round(55 + projected.z),
    };
  });
}

export function getViewCubeEdgeHitZones(
  cameraTransform: string,
): Array<ViewCubeScreenHitZone<ViewCubeEdgeDirection>> {
  return getViewCubeScreenHitZones(VIEW_CUBE_EDGES, cameraTransform, 22);
}

export function getViewCubeCornerHitZones(
  cameraTransform: string,
): Array<ViewCubeScreenHitZone<ViewCubeCornerDirection>> {
  return getViewCubeScreenHitZones(VIEW_CUBE_CORNERS, cameraTransform, 24);
}
