import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { useI18n } from "../../i18n/context";
import WikiTooltip from "../ui/WikiTooltip";
import type { ViewDisplayOptions } from "./ModelSurfaceToolbar";
import { CanvasOverlayHtml } from "./overlayLayout";
import {
  VIEW_CUBE_CORNERS,
  VIEW_CUBE_EDGES,
  getViewCubeCameraTransform,
  getViewCubeCornerHitZones,
  getViewCubeEdgeHitZones,
  getViewCubeFaceHitZones,
  inferOrthographicViewFromCamera,
  isViewCubeFaceDirection,
  type OrthographicViewDirection,
  type ViewCubeCornerDirection,
  type ViewCubeEdgeDirection,
  type ViewDirection,
} from "./viewCube";

interface ViewCubeLabels {
  group: string;
  viewTop: string;
  viewBottom: string;
  viewFront: string;
  viewBack: string;
  viewLeft: string;
  viewRight: string;
  faceHint: string;
  edgeHint: string;
  cornerHint: string;
  faceTop: string;
  faceBottom: string;
  faceFront: string;
  faceBack: string;
  faceLeft: string;
  faceRight: string;
  edges: Record<ViewCubeEdgeDirection, string>;
  corners: Record<ViewCubeCornerDirection, string>;
}

function ViewCubeOverlay({
  labels,
  cameraTransform,
  activeView,
  showAxes,
  showLabels,
  onView,
}: {
  labels: ViewCubeLabels;
  cameraTransform: string;
  activeView: OrthographicViewDirection | null;
  showAxes: boolean;
  showLabels: boolean;
  onView: (view: ViewDirection) => void;
}) {
  const faceButtonClass =
    "pointer-events-none absolute left-2 top-2 z-40 flex h-16 w-16 items-center justify-center border border-slate-300/70 bg-slate-100/62 text-[11px] font-semibold text-slate-800 shadow-[0_8px_18px_rgba(15,23,42,0.14)] backdrop-blur-sm transition dark:border-slate-500/65 dark:bg-slate-700/52 dark:text-slate-100 dark:shadow-[0_10px_22px_rgba(0,0,0,0.34)]";
  const activeFaceButtonClass =
    "border-blue-500/80 bg-blue-100/78 text-blue-800 ring-2 ring-blue-500/35 dark:border-blue-300/70 dark:bg-blue-950/72 dark:text-blue-100";
  const getFaceButtonClass = (view: OrthographicViewDirection): string =>
    `${faceButtonClass} ${activeView === view ? activeFaceButtonClass : ""}`;
  const visibleFaceLabel = (label: string) => (showLabels ? label : null);
  const faceStyle = (transform: string): CSSProperties => ({
    backfaceVisibility: "hidden",
    pointerEvents: "none",
    transform,
    transformOrigin: "center",
  });
  const faceHitZoneClass =
    "absolute inset-0 z-[45] cursor-pointer border-0 bg-transparent text-transparent opacity-0 transition hover:bg-sky-300/25 hover:opacity-60 focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)] dark:hover:bg-sky-500/25";
  const faceHitZones = useMemo(
    () => getViewCubeFaceHitZones(cameraTransform),
    [cameraTransform],
  );
  const edgeHitZones = useMemo(
    () => getViewCubeEdgeHitZones(cameraTransform),
    [cameraTransform],
  );
  const cornerHitZones = useMemo(
    () => getViewCubeCornerHitZones(cameraTransform),
    [cameraTransform],
  );
  const faceHitZoneByView = useMemo(
    () => new Map(faceHitZones.map((zone) => [zone.view, zone])),
    [faceHitZones],
  );
  const edgeHitZoneByView = useMemo(
    () => new Map(edgeHitZones.map((zone) => [zone.view, zone])),
    [edgeHitZones],
  );
  const cornerHitZoneByView = useMemo(
    () => new Map(cornerHitZones.map((zone) => [zone.view, zone])),
    [cornerHitZones],
  );
  const faceDefinitions: Array<{
    view: OrthographicViewDirection;
    title: string;
    label: string;
    transform: string;
  }> = [
    {
      view: "front",
      title: labels.viewFront,
      label: labels.faceFront,
      transform: "translateZ(32px)",
    },
    {
      view: "back",
      title: labels.viewBack,
      label: labels.faceBack,
      transform: "rotateY(180deg) translateZ(32px)",
    },
    {
      view: "right",
      title: labels.viewRight,
      label: labels.faceRight,
      transform: "rotateY(90deg) translateZ(32px)",
    },
    {
      view: "left",
      title: labels.viewLeft,
      label: labels.faceLeft,
      transform: "rotateY(-90deg) translateZ(32px)",
    },
    {
      view: "top",
      title: labels.viewTop,
      label: labels.faceTop,
      transform: "rotateX(90deg) translateZ(32px)",
    },
    {
      view: "bottom",
      title: labels.viewBottom,
      label: labels.faceBottom,
      transform: "rotateX(-90deg) translateZ(32px)",
    },
  ];
  const cornerButtonClass =
    "absolute z-50 h-5 w-5 border-0 bg-transparent text-transparent opacity-0 transition hover:bg-sky-300/35 hover:opacity-60 focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)] dark:hover:bg-sky-500/30";
  const edgeButtonClass =
    "absolute z-50 h-5 w-5 border-0 bg-transparent text-transparent opacity-0 transition hover:bg-sky-300/35 hover:opacity-60 focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)] dark:hover:bg-sky-500/30";

  return (
    <div
      role="group"
      aria-label={labels.group}
      data-view-cube-layout="integrated-navigation-cube"
      data-view-cube-shell="translucent-axis-cube"
      className="pointer-events-auto relative h-[112px] w-[112px] overflow-visible rounded-[22px] border border-slate-300/35 bg-slate-100/38 shadow-[0_10px_24px_rgba(15,23,42,0.10)] backdrop-blur-sm dark:border-slate-500/30 dark:bg-slate-950/32 dark:shadow-[0_12px_28px_rgba(0,0,0,0.24)]"
      style={{ perspective: "320px" }}
    >
      <div
        className="absolute left-1/2 top-1/2 h-20 w-20 -translate-x-1/2 -translate-y-1/2"
        style={{ transformStyle: "preserve-3d" }}
      >
        <div
          data-testid="model-surface-view-cube-rotor"
          className="relative h-full w-full"
          style={{
            transform: cameraTransform,
            transformStyle: "preserve-3d",
            transition: "transform 120ms ease-out",
          }}
        >
          {showAxes ? (
            <div
              aria-hidden="true"
              data-view-cube-axis-gizmo="embedded-cube-axis"
              data-view-cube-axis-anchor="cube-corner"
              className="pointer-events-none absolute inset-0 z-10"
            >
              <svg
                viewBox="0 0 80 80"
                data-view-cube-axis-overlay="rotor-local"
                className="h-full w-full overflow-visible"
              >
                <line
                  data-view-cube-axis="x"
                  x1="13"
                  y1="68"
                  x2="69"
                  y2="74"
                  className="stroke-rose-500/90"
                  strokeWidth="3"
                  strokeLinecap="round"
                />
                <line
                  data-view-cube-axis="y"
                  x1="13"
                  y1="68"
                  x2="50"
                  y2="34"
                  className="stroke-lime-600/90 dark:stroke-lime-400/90"
                  strokeWidth="3"
                  strokeLinecap="round"
                />
                <line
                  data-view-cube-axis="z"
                  x1="13"
                  y1="68"
                  x2="13"
                  y2="16"
                  className="stroke-blue-500/90"
                  strokeWidth="3"
                  strokeLinecap="round"
                />
                <circle
                  cx="13"
                  cy="68"
                  r="3.2"
                  className="fill-slate-500/78 dark:fill-slate-200/78"
                />
              </svg>
              {showLabels ? (
                <>
                  <span
                    data-view-cube-axis-label="x"
                    className="pointer-events-none absolute bottom-[-1px] right-[2px] text-xs font-bold text-rose-500"
                  >
                    X
                  </span>
                  <span
                    data-view-cube-axis-label="y"
                    className="pointer-events-none absolute left-[47px] top-[25px] text-xs font-bold text-lime-600 dark:text-lime-400"
                  >
                    Y
                  </span>
                  <span
                    data-view-cube-axis-label="z"
                    className="pointer-events-none absolute left-[5px] top-[7px] text-xs font-bold text-blue-500"
                  >
                    Z
                  </span>
                </>
              ) : null}
            </div>
          ) : null}
          {faceDefinitions.map((face) => (
            <div
              key={`visual-${face.view}`}
              aria-hidden="true"
              data-view-cube-visual-face={face.view}
              className={getFaceButtonClass(face.view)}
              style={faceStyle(face.transform)}
            >
              {visibleFaceLabel(face.label)}
            </div>
          ))}
        </div>
      </div>
      {VIEW_CUBE_EDGES.map((edge) => {
        const hitZone = edgeHitZoneByView.get(edge.view);
        return (
          <WikiTooltip
            key={edge.view}
            title={labels.edges[edge.view]}
            description={labels.edgeHint}
            placement="right"
            delay={0}
            asChild
          >
            <button
              type="button"
              aria-label={labels.edges[edge.view]}
              title={labels.edges[edge.view]}
              data-view-cube-edge={edge.view}
              data-view-cube-hit-layer="screen-fixed"
              tabIndex={hitZone?.visible ? undefined : -1}
              onClick={() => onView(edge.view)}
              className={edgeButtonClass}
              style={{
                left: hitZone?.left,
                top: hitZone?.top,
                width: hitZone?.width,
                height: hitZone?.height,
                pointerEvents: hitZone?.visible ? "auto" : "none",
                zIndex: hitZone?.zIndex,
              }}
            />
          </WikiTooltip>
        );
      })}
      {VIEW_CUBE_CORNERS.map((corner) => {
        const hitZone = cornerHitZoneByView.get(corner.view);
        return (
          <WikiTooltip
            key={corner.view}
            title={labels.corners[corner.view]}
            description={labels.cornerHint}
            placement="right"
            delay={0}
            asChild
          >
            <button
              type="button"
              aria-label={labels.corners[corner.view]}
              title={labels.corners[corner.view]}
              data-view-cube-corner={corner.view}
              data-view-cube-hit-layer="screen-fixed"
              tabIndex={hitZone?.visible ? undefined : -1}
              onClick={() => onView(corner.view)}
              className={cornerButtonClass}
              style={{
                left: hitZone?.left,
                top: hitZone?.top,
                width: hitZone?.width,
                height: hitZone?.height,
                pointerEvents: hitZone?.visible ? "auto" : "none",
                zIndex: hitZone?.zIndex,
              }}
            />
          </WikiTooltip>
        );
      })}
      {faceDefinitions.map((face) => {
        const hitZone = faceHitZoneByView.get(face.view);
        return (
          <WikiTooltip
            key={`hit-${face.view}`}
            title={face.title}
            description={labels.faceHint}
            placement="right"
            delay={0}
            asChild
          >
            <button
              type="button"
              aria-label={face.title}
              aria-pressed={activeView === face.view}
              title={face.title}
              data-view-cube-face={face.view}
              data-view-cube-hit-face={face.view}
              data-view-cube-hit-visible={hitZone?.visible ? "true" : "false"}
              tabIndex={hitZone?.visible ? undefined : -1}
              onClick={() => onView(face.view)}
              className={faceHitZoneClass}
              style={{
                clipPath: hitZone?.polygon,
                WebkitClipPath: hitZone?.polygon,
                pointerEvents: hitZone?.visible ? "auto" : "none",
                zIndex: hitZone?.zIndex,
              }}
            />
          </WikiTooltip>
        );
      })}
    </div>
  );
}

export function ModelViewNavigator({
  display,
  commandedView,
  onView,
}: {
  display: ViewDisplayOptions;
  commandedView: ViewDirection | null;
  onView: (view: ViewDirection) => void;
}) {
  const { t } = useI18n();
  const camera = useThree((state) => state.camera);
  const [cameraTransform, setCameraTransform] = useState(() =>
    getViewCubeCameraTransform(camera),
  );
  const [activeView, setActiveView] = useState<OrthographicViewDirection | null>(() =>
    inferOrthographicViewFromCamera(camera),
  );
  const cameraTransformRef = useRef(cameraTransform);
  const activeViewRef = useRef(activeView);
  useFrame(() => {
    const nextTransform = getViewCubeCameraTransform(camera);
    if (nextTransform !== cameraTransformRef.current) {
      cameraTransformRef.current = nextTransform;
      setCameraTransform(nextTransform);
    }
    const nextActiveView = inferOrthographicViewFromCamera(camera);
    if (nextActiveView !== activeViewRef.current) {
      activeViewRef.current = nextActiveView;
      setActiveView(nextActiveView);
    }
  });
  const handleView = useCallback(
    (view: ViewDirection) => {
      onView(view);
      const nextActiveView = isViewCubeFaceDirection(view) ? view : null;
      activeViewRef.current = nextActiveView;
      setActiveView(nextActiveView);
    },
    [onView],
  );
  useEffect(() => {
    if (!commandedView) {
      return;
    }
    const nextActiveView = isViewCubeFaceDirection(commandedView) ? commandedView : null;
    activeViewRef.current = nextActiveView;
    setActiveView(nextActiveView);
  }, [commandedView]);
  const viewCubeLabels: ViewCubeLabels = {
    group: t("model_surface_view_cube"),
    viewTop: t("model_surface_view_top"),
    viewBottom: t("model_surface_view_bottom"),
    viewFront: t("model_surface_view_front"),
    viewBack: t("model_surface_view_back"),
    viewLeft: t("model_surface_view_left"),
    viewRight: t("model_surface_view_right"),
    faceHint: t("model_surface_view_cube_face_hint"),
    edgeHint: t("model_surface_view_cube_edge_hint"),
    cornerHint: t("model_surface_view_cube_corner_hint"),
    faceTop: t("model_surface_face_top"),
    faceBottom: t("model_surface_face_bottom"),
    faceFront: t("model_surface_face_front"),
    faceBack: t("model_surface_face_back"),
    faceLeft: t("model_surface_face_left"),
    faceRight: t("model_surface_face_right"),
    edges: VIEW_CUBE_EDGES.reduce(
      (labels, edge) => ({
        ...labels,
        [edge.view]: t(edge.labelKey),
      }),
      {} as Record<ViewCubeEdgeDirection, string>,
    ),
    corners: VIEW_CUBE_CORNERS.reduce(
      (labels, corner) => ({
        ...labels,
        [corner.view]: t(corner.labelKey),
      }),
      {} as Record<ViewCubeCornerDirection, string>,
    ),
  };
  return (
    <CanvasOverlayHtml>
      <div
        data-model-view-navigator-layout="cube-only"
        className="pointer-events-none absolute bottom-4 z-10 flex items-end gap-2"
        style={{ left: "calc(var(--lumina-left-dock-width, 0px) + 12px)" }}
      >
        {display.navigator ? (
          <ViewCubeOverlay
            labels={viewCubeLabels}
            cameraTransform={cameraTransform}
            activeView={activeView}
            showAxes={display.axes}
            showLabels={display.labels}
            onView={handleView}
          />
        ) : null}
      </div>
    </CanvasOverlayHtml>
  );
}
