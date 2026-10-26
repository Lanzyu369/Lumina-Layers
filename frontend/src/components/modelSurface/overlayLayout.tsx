import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from "react";
import { useThree } from "@react-three/fiber";
import { Html } from "@react-three/drei";

export interface CanvasOverlayFrame {
  canvasLeft: number;
  canvasTop: number;
  leftDockWidth: string;
  rightDockWidth: string;
  left: number;
  top: number;
  width: number;
  height: number;
}

export const DEFAULT_CANVAS_OVERLAY_FRAME: CanvasOverlayFrame = {
  canvasLeft: 0,
  canvasTop: 0,
  leftDockWidth: "0px",
  rightDockWidth: "0px",
  left: 0,
  top: 0,
  width: 0,
  height: 0,
};

export type ModelSurfaceToolbarSnap =
  | "top"
  | "top-left"
  | "top-right"
  | "bottom"
  | "bottom-left"
  | "bottom-right";

export interface ModelSurfaceToolbarLayout {
  snap: ModelSurfaceToolbarSnap;
  collapsed: boolean;
}

export interface ToolbarSize {
  width: number;
  height: number;
}

export interface ToolbarPosition {
  x: number;
  y: number;
}

interface ToolbarSafeInsets {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export interface ToolbarDragState {
  pointerId: number;
  startClientX: number;
  startClientY: number;
  startPosition: ToolbarPosition;
  size: ToolbarSize;
}

const MODEL_SURFACE_TOOLBAR_STORAGE_KEY = "lumina-model-surface-toolbar-layout-v1";
const MODEL_SURFACE_TOOLBAR_MARGIN_PX = 12;
const CANVAS_OVERLAY_Z_INDEX_RANGE: [number, number] = [40, 40];
export const MODEL_SURFACE_TOOLBAR_DEFAULT_SIZE: ToolbarSize = { width: 340, height: 78 };
const MODEL_SURFACE_TOOLBAR_COLLAPSED_SIZE: ToolbarSize = { width: 174, height: 40 };
export const MODEL_SURFACE_TOOLBAR_DEFAULT_LAYOUT: ModelSurfaceToolbarLayout = {
  snap: "top-left",
  collapsed: false,
};
const MODEL_SURFACE_TOOLBAR_SNAPS: ModelSurfaceToolbarSnap[] = [
  "top",
  "top-left",
  "top-right",
  "bottom",
  "bottom-left",
  "bottom-right",
];

function isModelSurfaceToolbarSnap(value: unknown): value is ModelSurfaceToolbarSnap {
  return typeof value === "string"
    && MODEL_SURFACE_TOOLBAR_SNAPS.includes(value as ModelSurfaceToolbarSnap);
}

export function readModelSurfaceToolbarLayout(): ModelSurfaceToolbarLayout {
  if (typeof window === "undefined") {
    return MODEL_SURFACE_TOOLBAR_DEFAULT_LAYOUT;
  }
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(MODEL_SURFACE_TOOLBAR_STORAGE_KEY) ?? "null",
    ) as Partial<ModelSurfaceToolbarLayout> | null;
    return {
      snap: isModelSurfaceToolbarSnap(parsed?.snap)
        ? parsed.snap
        : MODEL_SURFACE_TOOLBAR_DEFAULT_LAYOUT.snap,
      collapsed: typeof parsed?.collapsed === "boolean"
        ? parsed.collapsed
        : MODEL_SURFACE_TOOLBAR_DEFAULT_LAYOUT.collapsed,
    };
  } catch {
    return MODEL_SURFACE_TOOLBAR_DEFAULT_LAYOUT;
  }
}

export function writeModelSurfaceToolbarLayout(layout: ModelSurfaceToolbarLayout): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(MODEL_SURFACE_TOOLBAR_STORAGE_KEY, JSON.stringify(layout));
  } catch {
    // Local storage can be unavailable in private browsing; the toolbar remains usable.
  }
}

function parseCssPixelValue(value: string): number {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? Math.max(0, parsed) : 0;
}

function getToolbarSafeInsets(container: HTMLElement | null): ToolbarSafeInsets {
  if (typeof window === "undefined" || !container) {
    return {
      left: MODEL_SURFACE_TOOLBAR_MARGIN_PX,
      right: MODEL_SURFACE_TOOLBAR_MARGIN_PX,
      top: MODEL_SURFACE_TOOLBAR_MARGIN_PX,
      bottom: MODEL_SURFACE_TOOLBAR_MARGIN_PX,
    };
  }
  const style = window.getComputedStyle(container);
  return {
    left:
      parseCssPixelValue(style.getPropertyValue("--lumina-left-dock-width"))
      + MODEL_SURFACE_TOOLBAR_MARGIN_PX,
    right:
      parseCssPixelValue(style.getPropertyValue("--lumina-right-dock-width"))
      + MODEL_SURFACE_TOOLBAR_MARGIN_PX,
    top: MODEL_SURFACE_TOOLBAR_MARGIN_PX,
    bottom: MODEL_SURFACE_TOOLBAR_MARGIN_PX,
  };
}

function getToolbarViewport(frame: CanvasOverlayFrame): { width: number; height: number } {
  const fallbackWidth = typeof window !== "undefined" ? window.innerWidth : 960;
  const fallbackHeight = typeof window !== "undefined" ? window.innerHeight : 640;
  return {
    width: frame.width > 0 ? frame.width : fallbackWidth,
    height: frame.height > 0 ? frame.height : fallbackHeight,
  };
}

function normalizeToolbarSize(size: ToolbarSize, collapsed: boolean): ToolbarSize {
  const fallback = collapsed
    ? MODEL_SURFACE_TOOLBAR_COLLAPSED_SIZE
    : MODEL_SURFACE_TOOLBAR_DEFAULT_SIZE;
  return {
    width: size.width > 0 ? size.width : fallback.width,
    height: size.height > 0 ? size.height : fallback.height,
  };
}

export function getMeasuredToolbarSize(
  element: HTMLElement | null,
  collapsed: boolean,
): ToolbarSize {
  const fallback = collapsed
    ? MODEL_SURFACE_TOOLBAR_COLLAPSED_SIZE
    : MODEL_SURFACE_TOOLBAR_DEFAULT_SIZE;
  if (!element) {
    return fallback;
  }
  const rect = element.getBoundingClientRect();
  return {
    width: rect.width > 0 ? rect.width : fallback.width,
    height: rect.height > 0 ? rect.height : fallback.height,
  };
}

function clampPositionToInsets(
  position: ToolbarPosition,
  frame: CanvasOverlayFrame,
  size: ToolbarSize,
  insets: ToolbarSafeInsets,
): ToolbarPosition {
  const viewport = getToolbarViewport(frame);
  const maxX = Math.max(insets.left, viewport.width - insets.right - size.width);
  const maxY = Math.max(insets.top, viewport.height - insets.bottom - size.height);
  return {
    x: Math.min(Math.max(position.x, insets.left), maxX),
    y: Math.min(Math.max(position.y, insets.top), maxY),
  };
}

export function clampToolbarPosition(
  position: ToolbarPosition,
  frame: CanvasOverlayFrame,
  size: ToolbarSize,
  container: HTMLElement | null,
): ToolbarPosition {
  return clampPositionToInsets(position, frame, size, getToolbarSafeInsets(container));
}

export function getModelSurfaceToolbarPosition(
  frame: CanvasOverlayFrame,
  rawSize: ToolbarSize,
  snap: ModelSurfaceToolbarSnap,
  container: HTMLElement | null,
  collapsed: boolean,
): ToolbarPosition {
  const size = normalizeToolbarSize(rawSize, collapsed);
  const viewport = getToolbarViewport(frame);
  const insets = getToolbarSafeInsets(container);
  const centerX = insets.left
    + Math.max(0, viewport.width - insets.left - insets.right - size.width) / 2;
  const bottomY = viewport.height - insets.bottom - size.height;
  const rightX = viewport.width - insets.right - size.width;
  const anchors: Record<ModelSurfaceToolbarSnap, ToolbarPosition> = {
    top: { x: centerX, y: insets.top },
    "top-left": { x: insets.left, y: insets.top },
    "top-right": { x: rightX, y: insets.top },
    bottom: { x: centerX, y: bottomY },
    "bottom-left": { x: insets.left, y: bottomY },
    "bottom-right": { x: rightX, y: bottomY },
  };
  return clampToolbarPosition(anchors[snap], frame, size, container);
}

export function getNearestModelSurfaceToolbarSnap(
  position: ToolbarPosition,
  rawSize: ToolbarSize,
  frame: CanvasOverlayFrame,
  container: HTMLElement | null,
  collapsed: boolean,
): ModelSurfaceToolbarSnap {
  const size = normalizeToolbarSize(rawSize, collapsed);
  const currentCenter = {
    x: position.x + size.width / 2,
    y: position.y + size.height / 2,
  };
  let nearest = MODEL_SURFACE_TOOLBAR_DEFAULT_LAYOUT.snap;
  let nearestDistance = Number.POSITIVE_INFINITY;
  for (const snap of MODEL_SURFACE_TOOLBAR_SNAPS) {
    const target = getModelSurfaceToolbarPosition(frame, size, snap, container, collapsed);
    const targetCenter = {
      x: target.x + size.width / 2,
      y: target.y + size.height / 2,
    };
    const dx = currentCenter.x - targetCenter.x;
    const dy = currentCenter.y - targetCenter.y;
    const distance = dx * dx + dy * dy;
    if (distance < nearestDistance) {
      nearest = snap;
      nearestDistance = distance;
    }
  }
  return nearest;
}

function areCanvasOverlayFramesEqual(
  current: CanvasOverlayFrame,
  next: CanvasOverlayFrame,
): boolean {
  return (
    Math.abs(current.left - next.left) < 0.5
    && Math.abs(current.top - next.top) < 0.5
    && Math.abs(current.width - next.width) < 0.5
    && Math.abs(current.height - next.height) < 0.5
    && Math.abs(current.canvasLeft - next.canvasLeft) < 0.5
    && Math.abs(current.canvasTop - next.canvasTop) < 0.5
    && current.leftDockWidth === next.leftDockWidth
    && current.rightDockWidth === next.rightDockWidth
  );
}

function getCanvasDockWidths(canvas: HTMLCanvasElement): {
  leftDockWidth: string;
  rightDockWidth: string;
} {
  let element: HTMLElement | null = canvas;
  while (element) {
    const style = window.getComputedStyle(element);
    const leftDockWidth = (
      element.style.getPropertyValue("--lumina-left-dock-width")
      || style.getPropertyValue("--lumina-left-dock-width")
    ).trim();
    const rightDockWidth = (
      element.style.getPropertyValue("--lumina-right-dock-width")
      || style.getPropertyValue("--lumina-right-dock-width")
    ).trim();
    if (leftDockWidth || rightDockWidth) {
      return {
        leftDockWidth: leftDockWidth || "0px",
        rightDockWidth: rightDockWidth || "0px",
      };
    }
    element = element.parentElement;
  }
  return {
    leftDockWidth: "0px",
    rightDockWidth: "0px",
  };
}

export function getCanvasOverlayFrame(
  _overlayRoot: HTMLDivElement | null,
  canvas: HTMLCanvasElement | undefined,
): CanvasOverlayFrame | null {
  if (!canvas) {
    return null;
  }
  const canvasRect = canvas.getBoundingClientRect();
  if (canvasRect.width <= 0 || canvasRect.height <= 0) {
    return null;
  }
  const dockWidths = getCanvasDockWidths(canvas);
  return {
    canvasLeft: canvasRect.left,
    canvasTop: canvasRect.top,
    ...dockWidths,
    left: 0,
    top: 0,
    width: canvasRect.width,
    height: canvasRect.height,
  };
}

export interface CanvasOverlayBox {
  left: number;
  top: number;
  width: number | "100%";
  height: number | "100%";
}

// Tolerance so float noise such as 163.0000001 does not shave off a whole pixel.
const OVERLAY_EDGE_SNAP_EPSILON_PX = 0.01;

function snapStartEdgeInward(value: number): number {
  const snapped = Math.ceil(value - OVERLAY_EDGE_SNAP_EPSILON_PX);
  // Math.ceil(-0.01) yields -0; normalize so styles and comparisons see a plain 0.
  return snapped === 0 ? 0 : snapped;
}

function snapEndEdgeInward(value: number): number {
  return Math.floor(value + OVERLAY_EDGE_SNAP_EPSILON_PX);
}

/**
 * Snap the overlay box to whole pixels without leaving the canvas bounds.
 * 将覆盖层盒子对齐到整数像素，且不超出画布边界。
 *
 * The overlay is portaled into `document.body` under a transformed wrapper, so it
 * takes part in document scroll overflow. Rounding the origin and size separately
 * can push the box 1px past the viewport (e.g. top 163.5 + height 604.5), which
 * adds page scrollbars and shrinks the widget workspace. Snapping each edge inward
 * keeps the box inside the canvas, and therefore inside the viewport.
 * 覆盖层通过 portal 挂到 `document.body` 且外层带 transform，会参与文档滚动溢出。
 * 分别取整起点和尺寸可能让盒子越出视口 1px，从而出现页面滚动条并挤窄工作区；
 * 向内对齐每条边可保证盒子始终位于画布（也即视口）之内。
 *
 * Args:
 *   frame (CanvasOverlayFrame): Measured canvas frame in viewport pixels. (视口像素下的画布测量框)
 *
 * Returns:
 *   CanvasOverlayBox: Integer CSS box; unmeasured sizes fall back to "100%". (整数 CSS 盒子；未测量尺寸回退为 "100%")
 */
export function getCanvasOverlayBox(frame: CanvasOverlayFrame): CanvasOverlayBox {
  const left = snapStartEdgeInward(frame.canvasLeft);
  const top = snapStartEdgeInward(frame.canvasTop);
  return {
    left,
    top,
    width: frame.width > 0
      ? Math.max(0, snapEndEdgeInward(frame.canvasLeft + frame.width) - left)
      : "100%",
    height: frame.height > 0
      ? Math.max(0, snapEndEdgeInward(frame.canvasTop + frame.height) - top)
      : "100%",
  };
}

const getStableCanvasOverlayHtmlPosition = (): [number, number] => [0, 0];

function useCanvasOverlayFrame(
  overlayRootRef: RefObject<HTMLDivElement | null>,
): CanvasOverlayFrame {
  const gl = useThree((state) => state.gl as { domElement?: HTMLCanvasElement } | undefined);
  const [frame, setFrame] = useState<CanvasOverlayFrame>(DEFAULT_CANVAS_OVERLAY_FRAME);

  const updateFrame = useCallback(() => {
    const next = getCanvasOverlayFrame(overlayRootRef.current, gl?.domElement);
    if (!next) {
      return;
    }
    setFrame((current) => (areCanvasOverlayFramesEqual(current, next) ? current : next));
  }, [gl?.domElement, overlayRootRef]);

  useEffect(() => {
    updateFrame();
    window.addEventListener("resize", updateFrame);
    window.addEventListener("scroll", updateFrame, true);
    const resizeObserver = typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(updateFrame)
      : null;
    const canvas = gl?.domElement;
    const body = typeof document !== "undefined" ? document.body : null;
    if (resizeObserver) {
      if (canvas) {
        resizeObserver.observe(canvas);
      }
      if (body) {
        resizeObserver.observe(body);
      }
    }
    return () => {
      window.removeEventListener("resize", updateFrame);
      window.removeEventListener("scroll", updateFrame, true);
      resizeObserver?.disconnect();
    };
  }, [gl?.domElement, overlayRootRef, updateFrame]);

  return frame;
}

export function CanvasOverlayHtml({
  children,
}: {
  children: ReactNode | ((frame: CanvasOverlayFrame) => ReactNode);
}) {
  const overlayRootRef = useRef<HTMLDivElement>(null);
  const bodyPortalRef = useRef<HTMLElement>(null);
  if (typeof document !== "undefined") {
    bodyPortalRef.current = document.body;
  }
  const frame = useCanvasOverlayFrame(overlayRootRef);
  const style = {
    position: "fixed",
    ...getCanvasOverlayBox(frame),
    "--lumina-left-dock-width": frame.leftDockWidth,
    "--lumina-right-dock-width": frame.rightDockWidth,
  } as CSSProperties;
  const content = (
    <div
      ref={overlayRootRef}
      data-model-surface-canvas-overlay="fixed"
      className="pointer-events-none overflow-visible"
      style={style}
    >
      {typeof children === "function" ? children(frame) : children}
    </div>
  );

  return (
    <Html
      calculatePosition={getStableCanvasOverlayHtmlPosition}
      portal={bodyPortalRef as RefObject<HTMLElement>}
      style={{ pointerEvents: "none" }}
      wrapperClass="z-40"
      zIndexRange={CANVAS_OVERLAY_Z_INDEX_RANGE}
    >
      {content}
    </Html>
  );
}
