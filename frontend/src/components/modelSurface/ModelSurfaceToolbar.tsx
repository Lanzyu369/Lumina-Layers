import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { useI18n } from "../../i18n/context";
import type { ModelSurfacePlacement } from "../../stores/converter";
import WikiTooltip from "../ui/WikiTooltip";
import {
  CameraIcon,
  ChevronDown,
  ChevronUp,
  CubeIcon,
  EyeIcon,
  EyeOffIcon,
  ExpandIcon,
  FlipVerticalIcon,
  MousePointerIcon,
  MoveIcon,
  RotateCwIcon,
} from "../ui/icons";
import {
  CanvasOverlayHtml,
  DEFAULT_CANVAS_OVERLAY_FRAME,
  MODEL_SURFACE_TOOLBAR_DEFAULT_SIZE,
  clampToolbarPosition,
  getMeasuredToolbarSize,
  getModelSurfaceToolbarPosition,
  getNearestModelSurfaceToolbarSnap,
  readModelSurfaceToolbarLayout,
  writeModelSurfaceToolbarLayout,
  type CanvasOverlayFrame,
  type ModelSurfaceToolbarLayout,
  type ToolbarDragState,
  type ToolbarPosition,
  type ToolbarSize,
} from "./overlayLayout";
import type { ViewDirection } from "./viewCube";

export type SurfaceTool = "modelRotate" | "select" | "move" | "rotate" | "scale";
export type SurfaceSelectionMode = "grouped" | "triangle";
type SurfaceToolbarTab = "model" | "artwork" | "view";

export interface ViewDisplayOptions {
  navigator: boolean;
  zoomButton: boolean;
  axes: boolean;
  gridLines: boolean;
  labels: boolean;
}

function SurfaceToolButton({
  active = false,
  disabled = false,
  description,
  label,
  onClick,
  children,
}: {
  active?: boolean;
  disabled?: boolean;
  description?: string;
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  const tooltipDescription = description ?? label;

  return (
    <WikiTooltip
      title={label}
      description={tooltipDescription}
      placement="bottom"
      delay={0}
      className="inline-flex"
    >
      <button
        type="button"
        aria-label={label}
        aria-pressed={active}
        title={tooltipDescription}
        data-model-surface-tool-button="icon-only"
        disabled={disabled}
        onClick={onClick}
        className={
          "inline-flex h-8 w-8 items-center justify-center rounded-xl border text-[11px] font-semibold backdrop-blur-sm shadow-[var(--shadow-control)] transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)] disabled:cursor-not-allowed disabled:opacity-45 "
          + (active
            ? "border-blue-500/70 bg-blue-500/20 text-blue-700 dark:text-blue-200"
            : "border-slate-200/80 bg-slate-100/85 text-slate-600 hover:bg-slate-200/90 dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:bg-slate-800/80")
        }
      >
        {children}
        <span className="sr-only">{label}</span>
      </button>
    </WikiTooltip>
  );
}

export function ModelSurfaceToolbar({
  activeTool,
  selectionReady,
  reverseView,
  canFocusSurface,
  canTransform,
  selecting,
  candidateCount,
  selectionMode,
  placement,
  display,
  contextualPanel,
  onSetTool,
  onFitArtwork,
  onUpdatePlacement,
  onFlipView,
  onSelectionModeChange,
  onToggleDisplay,
  onView,
  onFitView,
}: {
  activeTool: SurfaceTool;
  selectionReady: boolean;
  reverseView: boolean;
  canFocusSurface: boolean;
  canTransform: boolean;
  selecting: boolean;
  candidateCount: number;
  selectionMode: SurfaceSelectionMode;
  placement: ModelSurfacePlacement;
  display: ViewDisplayOptions;
  contextualPanel?: ReactNode;
  onSetTool: (tool: SurfaceTool) => void;
  onFitArtwork?: () => void;
  onUpdatePlacement?: (updates: Partial<ModelSurfacePlacement>) => void;
  onFlipView: () => void;
  onSelectionModeChange: (mode: SurfaceSelectionMode) => void;
  onToggleDisplay: (key: keyof ViewDisplayOptions) => void;
  onView: (view: ViewDirection) => void;
  onFitView: () => void;
}) {
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState<SurfaceToolbarTab>("model");
  const previousActiveToolRef = useRef(activeTool);
  const [toolbarLayout, setToolbarLayout] = useState<ModelSurfaceToolbarLayout>(
    readModelSurfaceToolbarLayout,
  );
  const [toolbarSize, setToolbarSize] = useState<ToolbarSize>(
    MODEL_SURFACE_TOOLBAR_DEFAULT_SIZE,
  );
  const [toolbarDragPosition, setToolbarDragPosition] = useState<ToolbarPosition | null>(null);
  const [isToolbarDragging, setIsToolbarDragging] = useState(false);
  const toolbarContainerRef = useRef<HTMLDivElement>(null);
  const toolbarShellRef = useRef<HTMLDivElement>(null);
  const toolbarFrameRef = useRef<CanvasOverlayFrame>(DEFAULT_CANVAS_OVERLAY_FRAME);
  const toolbarDragRef = useRef<ToolbarDragState | null>(null);
  const latestToolbarDragPositionRef = useRef<ToolbarPosition | null>(null);
  const selectLabel = selectionReady
    ? t("model_surface_tool_reselect")
    : t("model_surface_tool_select");
  const tabs: Array<{ id: SurfaceToolbarTab; label: string }> = [
    { id: "model", label: t("model_surface_toolbar_model") },
    { id: "artwork", label: t("model_surface_toolbar_artwork") },
    { id: "view", label: t("model_surface_toolbar_view") },
  ];
  const displayOptions: Array<{
    key: keyof ViewDisplayOptions;
    label: string;
    description: string;
  }> = [
    {
      key: "navigator",
      label: t("model_surface_display_navigator"),
      description: t("model_surface_display_navigator_hint"),
    },
    {
      key: "zoomButton",
      label: t("model_surface_display_zoom"),
      description: t("model_surface_display_zoom_hint"),
    },
    {
      key: "axes",
      label: t("model_surface_display_axes"),
      description: t("model_surface_display_axes_hint"),
    },
    {
      key: "gridLines",
      label: t("model_surface_display_grid"),
      description: t("model_surface_display_grid_hint"),
    },
    {
      key: "labels",
      label: t("model_surface_display_labels"),
      description: t("model_surface_display_labels_hint"),
    },
  ];
  const tabButtonClass = (tab: SurfaceToolbarTab): string =>
    "inline-flex h-8 items-center justify-center border-b-2 px-3 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)] "
    + (activeTab === tab
      ? "border-blue-500 text-blue-700 dark:text-blue-200"
      : "border-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100");
  const modeButtonClass = (mode: SurfaceSelectionMode): string =>
    "inline-flex h-8 items-center justify-center rounded-xl border px-2 text-[11px] font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)] "
    + (selectionMode === mode
      ? "border-blue-500/70 bg-blue-500/18 text-blue-700 dark:text-blue-200"
      : "border-slate-200/80 bg-slate-100/85 text-slate-600 hover:bg-slate-200/90 dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:bg-slate-800/80");
  const placementModeButtonClass = (active: boolean): string =>
    "inline-flex h-7 items-center justify-center rounded-lg px-2 text-[11px] font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)] disabled:cursor-not-allowed disabled:opacity-45 "
    + (active
      ? "bg-blue-500/20 text-blue-700 dark:text-blue-200"
      : "text-slate-600 hover:bg-slate-200/90 dark:text-slate-300 dark:hover:bg-slate-800/80");

  useEffect(() => {
    const previousActiveTool = previousActiveToolRef.current;
    previousActiveToolRef.current = activeTool;
    if (activeTool === "move" || activeTool === "rotate" || activeTool === "scale") {
      setActiveTab("artwork");
      return;
    }
    if (activeTool === "modelRotate") {
      setActiveTab("model");
      return;
    }
    if (activeTool === "select" && previousActiveTool === "modelRotate") {
      setActiveTab("model");
      return;
    }
    if (activeTool === "select" && selectionReady && canTransform && !selecting) {
      setActiveTab("artwork");
      return;
    }
    if (activeTool === "select") {
      setActiveTab("model");
    }
  }, [activeTool, canTransform, selecting, selectionReady]);

  useEffect(() => {
    writeModelSurfaceToolbarLayout(toolbarLayout);
  }, [toolbarLayout]);

  const measureToolbarSize = useCallback(
    (collapsed = toolbarLayout.collapsed): ToolbarSize => {
      const next = getMeasuredToolbarSize(toolbarShellRef.current, collapsed);
      setToolbarSize((current) =>
        Math.abs(current.width - next.width) < 0.5
        && Math.abs(current.height - next.height) < 0.5
          ? current
          : next,
      );
      return next;
    },
    [toolbarLayout.collapsed],
  );

  useEffect(() => {
    measureToolbarSize();
    const shell = toolbarShellRef.current;
    if (!shell || typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(() => measureToolbarSize());
    observer.observe(shell);
    return () => observer.disconnect();
  }, [activeTab, activeTool, candidateCount, display, measureToolbarSize, toolbarLayout.collapsed]);

  const handleToolbarDragPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLButtonElement>) => {
      if (event.button > 0) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      event.currentTarget.setPointerCapture?.(event.pointerId);
      const size = measureToolbarSize();
      const frame = toolbarFrameRef.current;
      const startPosition = toolbarDragPosition
        ?? getModelSurfaceToolbarPosition(
          frame,
          size,
          toolbarLayout.snap,
          toolbarContainerRef.current,
          toolbarLayout.collapsed,
        );
      toolbarDragRef.current = {
        pointerId: event.pointerId,
        startClientX: event.clientX,
        startClientY: event.clientY,
        startPosition,
        size,
      };
      latestToolbarDragPositionRef.current = startPosition;
      setToolbarDragPosition(startPosition);
      setIsToolbarDragging(true);
    },
    [measureToolbarSize, toolbarDragPosition, toolbarLayout.collapsed, toolbarLayout.snap],
  );

  useEffect(() => {
    if (!isToolbarDragging) {
      return;
    }
    const handlePointerMove = (event: PointerEvent) => {
      const drag = toolbarDragRef.current;
      if (!drag || event.pointerId !== drag.pointerId) {
        return;
      }
      event.preventDefault();
      const nextPosition = clampToolbarPosition(
        {
          x: drag.startPosition.x + event.clientX - drag.startClientX,
          y: drag.startPosition.y + event.clientY - drag.startClientY,
        },
        toolbarFrameRef.current,
        drag.size,
        toolbarContainerRef.current,
      );
      latestToolbarDragPositionRef.current = nextPosition;
      setToolbarDragPosition(nextPosition);
    };
    const handlePointerUp = (event: PointerEvent) => {
      const drag = toolbarDragRef.current;
      if (!drag || event.pointerId !== drag.pointerId) {
        return;
      }
      event.preventDefault();
      const finalPosition = latestToolbarDragPositionRef.current ?? drag.startPosition;
      const snap = getNearestModelSurfaceToolbarSnap(
        finalPosition,
        drag.size,
        toolbarFrameRef.current,
        toolbarContainerRef.current,
        toolbarLayout.collapsed,
      );
      setToolbarLayout((current) => ({ ...current, snap }));
      setToolbarDragPosition(null);
      latestToolbarDragPositionRef.current = null;
      toolbarDragRef.current = null;
      setIsToolbarDragging(false);
    };
    window.addEventListener("pointermove", handlePointerMove, { passive: false });
    window.addEventListener("pointerup", handlePointerUp, { passive: false });
    window.addEventListener("pointercancel", handlePointerUp, { passive: false });
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerUp);
    };
  }, [isToolbarDragging, toolbarLayout.collapsed]);

  const handleToggleToolbarCollapsed = useCallback(() => {
    setToolbarDragPosition(null);
    latestToolbarDragPositionRef.current = null;
    toolbarDragRef.current = null;
    setIsToolbarDragging(false);
    setToolbarLayout((current) => ({ ...current, collapsed: !current.collapsed }));
  }, []);

  const renderModelToolbar = () => (
    <>
      <SurfaceToolButton
        active={activeTool === "modelRotate"}
        disabled={selecting}
        description={t("model_surface_tool_orbit_hint")}
        label={t("model_surface_tool_orbit")}
        onClick={() => onSetTool("modelRotate")}
      >
        <RotateCwIcon />
      </SurfaceToolButton>
      <SurfaceToolButton
        active={activeTool === "select"}
        disabled={selecting}
        description={selectionReady
          ? t("model_surface_tool_reselect_hint")
          : t("model_surface_tool_select_hint")}
        label={selectLabel}
        onClick={() => onSetTool("select")}
      >
        <MousePointerIcon />
      </SurfaceToolButton>
      <SurfaceToolButton
        active={reverseView}
        disabled={!canFocusSurface}
        description={t("model_surface_view_reverse_hint")}
        label={t("model_surface_view_reverse")}
        onClick={onFlipView}
      >
        <FlipVerticalIcon />
      </SurfaceToolButton>
      {candidateCount > 0 ? (
        <>
          <div
            role="status"
            aria-label={t("model_surface_selection_panel")}
            className="inline-flex h-8 items-center gap-2 rounded-2xl border border-slate-200/80 bg-slate-100/78 px-2 text-[11px] font-semibold text-slate-600 dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-300"
          >
            <span>{t("model_surface_selection_mode")}</span>
            <span>
              {selectionMode === "grouped"
                ? t("model_surface_selection_mode_grouped")
                : t("model_surface_selection_mode_triangle")}
            </span>
            <span className="rounded-lg bg-blue-500/16 px-1.5 py-0.5 text-blue-700 dark:text-blue-200">
              {candidateCount} {t("model_surface_selection_candidate_unit")}
            </span>
            <span>{t("model_surface_selection_bevel_filtered")}</span>
          </div>
          <WikiTooltip
            title={t("model_surface_selection_mode_grouped_action")}
            description={t("model_surface_selection_mode_grouped_hint")}
            placement="bottom"
            delay={0}
            asChild
          >
            <button
              type="button"
              aria-label={t("model_surface_selection_mode_grouped_action")}
              title={t("model_surface_selection_mode_grouped_action")}
              aria-pressed={selectionMode === "grouped"}
              onClick={() => onSelectionModeChange("grouped")}
              className={modeButtonClass("grouped")}
            >
              {t("model_surface_selection_mode_grouped")}
            </button>
          </WikiTooltip>
          <WikiTooltip
            title={t("model_surface_selection_mode_triangle_action")}
            description={t("model_surface_selection_mode_triangle_hint")}
            placement="bottom"
            delay={0}
            asChild
          >
            <button
              type="button"
              aria-label={t("model_surface_selection_mode_triangle_action")}
              title={t("model_surface_selection_mode_triangle_action")}
              aria-pressed={selectionMode === "triangle"}
              onClick={() => onSelectionModeChange("triangle")}
              className={modeButtonClass("triangle")}
            >
              {t("model_surface_selection_mode_triangle")}
            </button>
          </WikiTooltip>
        </>
      ) : null}
    </>
  );

  const renderArtworkToolbar = () => (
    <>
      <SurfaceToolButton
        active={activeTool === "move"}
        disabled={!canTransform}
        description={t("model_surface_tool_move_hint")}
        label={t("model_surface_tool_move")}
        onClick={() => onSetTool("move")}
      >
        <MoveIcon />
      </SurfaceToolButton>
      <SurfaceToolButton
        active={activeTool === "rotate"}
        disabled={!canTransform}
        description={t("model_surface_tool_rotate_hint")}
        label={t("model_surface_tool_rotate")}
        onClick={() => onSetTool("rotate")}
      >
        <RotateCwIcon />
      </SurfaceToolButton>
      <SurfaceToolButton
        active={activeTool === "scale"}
        disabled={!canTransform}
        description={t("model_surface_tool_scale_hint")}
        label={t("model_surface_tool_scale")}
        onClick={() => onSetTool("scale")}
      >
        <ExpandIcon />
      </SurfaceToolButton>
      <SurfaceToolButton
        disabled={!canTransform || !onFitArtwork}
        description={t("model_surface_fit_hint")}
        label={t("model_surface_fit")}
        onClick={() => {
          onFitArtwork?.();
          onSetTool("move");
        }}
      >
        <CameraIcon />
      </SurfaceToolButton>
      <div
        role="group"
        aria-label={t("model_surface_edge_mode")}
        className="inline-flex h-8 flex-shrink-0 items-center rounded-xl border border-slate-200/80 bg-slate-100/78 p-0.5 dark:border-slate-700/80 dark:bg-slate-900/70"
      >
        <WikiTooltip
          title={t("model_surface_mode_edge")}
          description={t("model_surface_mode_edge_hint")}
          placement="bottom"
          delay={0}
          asChild
        >
          <button
            type="button"
            aria-label={t("model_surface_mode_edge")}
            aria-pressed={placement.mode === "edge_to_edge"}
            disabled={!canTransform || !onUpdatePlacement}
            onClick={() => onUpdatePlacement?.({ mode: "edge_to_edge" })}
            className={placementModeButtonClass(placement.mode === "edge_to_edge")}
          >
            {t("model_surface_mode_edge")}
          </button>
        </WikiTooltip>
        <WikiTooltip
          title={t("model_surface_mode_inset")}
          description={t("model_surface_mode_inset_hint")}
          placement="bottom"
          delay={0}
          asChild
        >
          <button
            type="button"
            aria-label={t("model_surface_mode_inset")}
            aria-pressed={placement.mode === "inset"}
            disabled={!canTransform || !onUpdatePlacement}
            onClick={() => onUpdatePlacement?.({ mode: "inset" })}
            className={placementModeButtonClass(placement.mode === "inset")}
          >
            {t("model_surface_mode_inset")}
          </button>
        </WikiTooltip>
      </div>
      <WikiTooltip
        title={t("model_surface_inset")}
        description={t("model_surface_inset_hint")}
        placement="bottom"
        delay={0}
        asChild
      >
        <label className="inline-flex h-8 flex-shrink-0 items-center gap-1 rounded-xl border border-slate-200/80 bg-slate-100/78 px-2 text-[11px] font-semibold text-slate-600 dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-300">
          <span>{t("model_surface_inset")}</span>
          <input
            type="number"
            min="0"
            step="0.1"
            value={placement.inset_mm}
            aria-label={t("model_surface_inset")}
            disabled={
              placement.mode !== "inset"
              || !canTransform
              || !onUpdatePlacement
            }
            onChange={(event) => {
              const value = event.currentTarget.valueAsNumber;
              if (Number.isFinite(value)) {
                onUpdatePlacement?.({ inset_mm: value });
              }
            }}
            className="h-6 w-14 rounded-lg border border-slate-200/80 bg-slate-50 px-1.5 text-right text-[11px] font-semibold text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-[var(--focus-ring)] disabled:cursor-not-allowed disabled:opacity-45 dark:border-slate-700/80 dark:bg-slate-950/70 dark:text-slate-200"
          />
          <span aria-hidden="true">{t("common_unit_mm")}</span>
        </label>
      </WikiTooltip>
    </>
  );

  const renderViewToolbar = () => (
    <>
      <SurfaceToolButton
        description={t("model_surface_view_default_hint")}
        label={t("model_surface_view_default")}
        onClick={() => onView("default")}
      >
        <CubeIcon />
      </SurfaceToolButton>
      {display.zoomButton ? (
        <SurfaceToolButton
          description={t("model_surface_fit_view_hint")}
          label={t("model_surface_fit_view")}
          onClick={onFitView}
        >
          <CameraIcon />
        </SurfaceToolButton>
      ) : null}
      {displayOptions.map((option) => (
        <SurfaceToolButton
          key={option.key}
          active={display[option.key]}
          description={option.description}
          label={option.label}
          onClick={() => onToggleDisplay(option.key)}
        >
          {display[option.key] ? <EyeIcon /> : <EyeOffIcon />}
        </SurfaceToolButton>
      ))}
    </>
  );

  return (
    <CanvasOverlayHtml>
      {(frame) => {
        toolbarFrameRef.current = frame;
        const position = toolbarDragPosition
          ?? getModelSurfaceToolbarPosition(
            frame,
            toolbarSize,
            toolbarLayout.snap,
            toolbarContainerRef.current,
            toolbarLayout.collapsed,
          );
        return (
          <div
            ref={toolbarContainerRef}
            data-model-surface-toolbar-anchor="scene-floating"
            className="pointer-events-none absolute inset-0 z-30 overflow-visible"
          >
            <div
              ref={toolbarShellRef}
              data-model-surface-toolbar-shell="floating-command-band"
              data-model-surface-toolbar-snap={toolbarLayout.snap}
              data-model-surface-toolbar-collapsed={toolbarLayout.collapsed ? "true" : "false"}
              data-model-surface-toolbar-dragging={isToolbarDragging ? "true" : "false"}
              className={
                "pointer-events-auto absolute flex max-w-[calc(100%-24px)] flex-col overflow-hidden rounded-[22px] border border-slate-200/80 bg-slate-100/90 shadow-[var(--shadow-control)] backdrop-blur-md dark:border-slate-700/80 dark:bg-slate-950/82 "
                + (isToolbarDragging ? "cursor-grabbing" : "transition-[left,top]")
              }
              style={{
                left: Math.round(position.x),
                top: Math.round(position.y),
                maxWidth: "calc(100% - var(--lumina-left-dock-width, 0px) - var(--lumina-right-dock-width, 0px) - 24px)",
              }}
            >
              <div
                data-model-surface-toolbar-drag-row="header"
                className={
                  "flex min-h-8 items-center gap-1 border-slate-200/80 px-1 dark:border-slate-700/80 "
                  + (toolbarLayout.collapsed ? "" : "border-b")
                }
              >
                <WikiTooltip
                  title={t("model_surface_toolbar_drag")}
                  description={t("model_surface_toolbar_drag_hint")}
                  placement="bottom"
                  delay={0}
                  asChild
                >
                  <button
                    type="button"
                    aria-label={t("model_surface_toolbar_drag")}
                    title={t("model_surface_toolbar_drag")}
                    data-model-surface-toolbar-drag-handle="true"
                    onPointerDown={handleToolbarDragPointerDown}
                    className="inline-flex h-7 w-7 flex-shrink-0 cursor-grab touch-none items-center justify-center rounded-xl text-slate-500 transition-colors hover:bg-slate-200/80 hover:text-slate-800 active:cursor-grabbing dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
                  >
                    <MoveIcon className="h-3.5 w-3.5" />
                  </button>
                </WikiTooltip>
                {toolbarLayout.collapsed ? (
                  <span className="min-w-20 flex-1 select-none px-1 text-xs font-semibold text-slate-700 dark:text-slate-200">
                    {t("model_surface_toolbar_title")}
                  </span>
                ) : (
                  <div
                    role="tablist"
                    aria-label={t("model_surface_toolbar_group")}
                    data-model-surface-toolbar-layout="slicer-top-tabs"
                    className="flex min-w-0 flex-1"
                  >
                    {tabs.map((tab) => (
                      <button
                        key={tab.id}
                        type="button"
                        role="tab"
                        aria-selected={activeTab === tab.id}
                        title={tab.label}
                        onClick={() => setActiveTab(tab.id)}
                        className={tabButtonClass(tab.id)}
                      >
                        {tab.label}
                      </button>
                    ))}
                  </div>
                )}
                <WikiTooltip
                  title={toolbarLayout.collapsed
                    ? t("model_surface_toolbar_expand")
                    : t("model_surface_toolbar_collapse")}
                  description={toolbarLayout.collapsed
                    ? t("model_surface_toolbar_expand_hint")
                    : t("model_surface_toolbar_collapse_hint")}
                  placement="bottom"
                  delay={0}
                  asChild
                >
                  <button
                    type="button"
                    aria-label={toolbarLayout.collapsed
                      ? t("model_surface_toolbar_expand")
                      : t("model_surface_toolbar_collapse")}
                    title={toolbarLayout.collapsed
                      ? t("model_surface_toolbar_expand")
                      : t("model_surface_toolbar_collapse")}
                    onClick={handleToggleToolbarCollapsed}
                    className="inline-flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-xl text-slate-500 transition-colors hover:bg-slate-200/80 hover:text-slate-800 focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)] dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
                  >
                    {toolbarLayout.collapsed ? <ChevronDown /> : <ChevronUp />}
                  </button>
                </WikiTooltip>
              </div>
              {toolbarLayout.collapsed ? null : (
                <>
                  <div
                    role="toolbar"
                    aria-label={t("model_surface_toolbar_secondary")}
                    data-model-surface-toolbar-row="secondary"
                    className="flex w-full max-w-full items-center justify-center gap-1.5 overflow-x-auto p-1.5"
                  >
                    {activeTab === "model" ? renderModelToolbar() : null}
                    {activeTab === "artwork" ? renderArtworkToolbar() : null}
                    {activeTab === "view" ? renderViewToolbar() : null}
                  </div>
                  {contextualPanel ? (
                    <div
                      data-model-surface-toolbar-row="contextual"
                      className="w-full max-w-full overflow-x-auto border-t border-slate-200/80 px-1.5 py-1 dark:border-slate-700/80"
                    >
                      {contextualPanel}
                    </div>
                  ) : null}
                </>
              )}
            </div>
          </div>
        );
      }}
    </CanvasOverlayHtml>
  );
}
