import { Suspense, useRef, useState, useEffect, useCallback, useMemo } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls, Environment, Html } from "@react-three/drei";
import { LIGHTING_CONFIG } from "./lightingConfig";
import * as THREE from "three";
import { computeFitDistance } from "./ModelViewer";
import InteractiveModelViewer from "./InteractiveModelViewer";
import BedPlatform from "./BedPlatform";
import KeychainRing3D from "./KeychainRing3D";
import FridgeMagnet3D from "./FridgeMagnet3D";
import { useConverterStore } from "../stores/converter";
import { useSettingsStore } from "../stores/settingsStore";
import { computeScaleFactor } from "../utils/scaleUtils";
import { useI18n } from "../i18n/context";
import { useThemeConfig } from "../hooks/useThemeConfig";
import { useWittyMessage } from "../hooks/useWittyMessage";
import {
  debugThreeLog,
  getHeapMemorySnapshot,
  getRendererInfoSnapshot,
  getThreePerfDebugConfig,
} from "../utils/threeDebug";
import { postClientLog } from "../utils/clientLog";
import { ActivityIcon, MaximizeIcon, MinimizeIcon, CameraIcon } from "./ui/icons";
import type { BatchPreviewItem } from "../api/types";

declare global {
  interface Window {
    __luminaCameraDebug?: () => {
      cameraPosition: { x: number; y: number; z: number };
      orbitTarget: { x: number; y: number; z: number };
      fov: number;
    };
  }
}

interface Scene3DProps {
  modelUrl?: string;
}

interface SceneDiagnosticsSnapshot {
  renderer: ReturnType<typeof getRendererInfoSnapshot>;
  heap: ReturnType<typeof getHeapMemorySnapshot>;
  fps: number | null;
}

function FrameSampler({
  onFps,
}: {
  onFps: (fps: number) => void;
}) {
  const frameCountRef = useRef(0);
  const lastFpsAtRef = useRef(performance.now());

  useFrame(() => {
    frameCountRef.current += 1;
  });

  useEffect(() => {
    const timerId = window.setInterval(() => {
      const now = performance.now();
      const elapsed = now - lastFpsAtRef.current;
      if (elapsed < 1000) {
        return;
      }
      const fps = Math.round((frameCountRef.current * 10000) / elapsed) / 10;
      frameCountRef.current = 0;
      lastFpsAtRef.current = now;
      onFps(fps);
    }, 1000);
    return () => {
      window.clearInterval(timerId);
    };
  }, [onFps]);

  return null;
}

function RendererDiagnosticsBridge({
  enabled,
  onSample,
}: {
  enabled: boolean;
  onSample: (snapshot: SceneDiagnosticsSnapshot) => void;
}) {
  const { gl } = useThree();
  const latestFpsRef = useRef<number | null>(null);

  const publishSnapshot = useCallback(() => {
    onSample({
      renderer: getRendererInfoSnapshot(gl),
      heap: getHeapMemorySnapshot(),
      fps: latestFpsRef.current,
    });
  }, [gl, onSample]);

  useEffect(() => {
    publishSnapshot();
  }, [publishSnapshot]);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    const { intervalMs } = getThreePerfDebugConfig();
    const timerId = window.setInterval(() => {
      publishSnapshot();
    }, intervalMs);
    return () => {
      window.clearInterval(timerId);
    };
  }, [enabled, publishSnapshot]);

  const handleFps = useCallback((fps: number) => {
    latestFpsRef.current = fps;
  }, []);

  if (!enabled) {
    return null;
  }

  return <FrameSampler onFps={handleFps} />;
}

/**
 * Helper component rendered inside <Canvas> to expose the gl context
 * for screenshot functionality via a callback ref.
 */
function ScreenshotHelper({
  onGlReady,
}: {
  onGlReady: (gl: THREE.WebGLRenderer) => void;
}) {
  const { gl } = useThree();
  useEffect(() => {
    onGlReady(gl);
  }, [gl, onGlReady]);
  return null;
}

/**
 * Expose camera debug info to window for tuning default view.
 * Run `window.__luminaCameraDebug()` in browser console to print current values.
 * 将相机调试信息暴露到 window，用于调优默认视角。
 */
function CameraDebugHelper() {
  const { camera, controls } = useThree();
  useEffect(() => {
    window.__luminaCameraDebug = () => {
      const pos = camera.position;
      const orbitControls =
        controls && "target" in controls
          ? (controls as { target?: THREE.Vector3 | null })
          : null;
      const target = orbitControls?.target ?? { x: 0, y: 0, z: 0 };
      const info = {
        cameraPosition: { x: +pos.x.toFixed(2), y: +pos.y.toFixed(2), z: +pos.z.toFixed(2) },
        orbitTarget: { x: +target.x.toFixed(2), y: +target.y.toFixed(2), z: +target.z.toFixed(2) },
        fov: (camera as THREE.PerspectiveCamera).fov,
      };
      console.log("📷 Camera Debug:", JSON.stringify(info, null, 2));
      return info;
    };
    return () => {
      delete window.__luminaCameraDebug;
    };
  }, [camera, controls]);
  return null;
}

/**
 * Inner component that syncs the Canvas clear color with the active theme.
 * Canvas 内部组件，将清除色与当前主题同步。
 */
function ThemeUpdater() {
  const { gl, invalidate } = useThree();
  const themeColors = useThemeConfig();
  useEffect(() => {
    gl.setClearColor(themeColors.canvasClearColor);
    invalidate();
  }, [gl, themeColors.canvasClearColor, invalidate]);
  return null;
}

const ORBIT_DAMPING_SETTLE_MS = 500;
const ORBIT_CHANGE_BURST_MS = 180;
const ORBIT_PASSTHROUGH_MAX_MS = 10000;
const ORBIT_PASSTHROUGH_CLASS = "lumina-canvas-orbiting";

function setWidgetPassthroughForCanvasInteraction(enabled: boolean): void {
  document.body.classList.toggle(ORBIT_PASSTHROUGH_CLASS, enabled);
  if (enabled) {
    return;
  }
  // Recover panels left non-interactive by older builds or interrupted HMR.
  document.querySelectorAll<HTMLElement>("[data-widget-id]").forEach((panel) => {
    if (
      panel.style.pointerEvents === "none" &&
      panel.style.getPropertyPriority("pointer-events") === "important"
    ) {
      panel.style.pointerEvents = "auto";
    }
  });
}

function CanvasInteractionBridge() {
  const { controls, invalidate } = useThree();
  useEffect(() => {
    if (!controls) return;
    const controlsWithEvents = controls as {
      addEventListener: (type: "start" | "change" | "end", listener: () => void) => void;
      removeEventListener: (type: "start" | "change" | "end", listener: () => void) => void;
    };

    let rafId: number | null = null;
    let passthroughTimerId: number | null = null;
    let keepRenderingUntil = 0;
    let interacting = false;

    const stopLoop = () => {
      if (rafId !== null) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
    };

    const tick = () => {
      invalidate();
      if (interacting || performance.now() < keepRenderingUntil) {
        rafId = requestAnimationFrame(tick);
        return;
      }
      rafId = null;
    };

    const ensureLoop = () => {
      if (rafId === null) {
        rafId = requestAnimationFrame(tick);
      }
    };

    const stopPassthroughTimer = () => {
      if (passthroughTimerId !== null) {
        window.clearTimeout(passthroughTimerId);
        passthroughTimerId = null;
      }
    };

    const finishInteraction = () => {
      if (!interacting) {
        setWidgetPassthroughForCanvasInteraction(false);
        return;
      }
      interacting = false;
      keepRenderingUntil = performance.now() + ORBIT_DAMPING_SETTLE_MS;
      stopPassthroughTimer();
      setWidgetPassthroughForCanvasInteraction(false);
      invalidate();
      ensureLoop();
    };

    const onStart = () => {
      interacting = true;
      keepRenderingUntil = Number.POSITIVE_INFINITY;
      setWidgetPassthroughForCanvasInteraction(true);
      stopPassthroughTimer();
      passthroughTimerId = window.setTimeout(finishInteraction, ORBIT_PASSTHROUGH_MAX_MS);
      invalidate();
      ensureLoop();
    };

    const onChange = () => {
      if (!interacting) {
        keepRenderingUntil = Math.max(keepRenderingUntil, performance.now() + ORBIT_CHANGE_BURST_MS);
        ensureLoop();
      }
      invalidate();
    };

    controlsWithEvents.addEventListener("start", onStart);
    controlsWithEvents.addEventListener("change", onChange);
    controlsWithEvents.addEventListener("end", finishInteraction);
    window.addEventListener("pointerup", finishInteraction);
    window.addEventListener("pointercancel", finishInteraction);
    window.addEventListener("blur", finishInteraction);
    window.addEventListener("contextmenu", finishInteraction);

    return () => {
      controlsWithEvents.removeEventListener("start", onStart);
      controlsWithEvents.removeEventListener("change", onChange);
      controlsWithEvents.removeEventListener("end", finishInteraction);
      window.removeEventListener("pointerup", finishInteraction);
      window.removeEventListener("pointercancel", finishInteraction);
      window.removeEventListener("blur", finishInteraction);
      window.removeEventListener("contextmenu", finishInteraction);
      stopLoop();
      stopPassthroughTimer();
      setWidgetPassthroughForCanvasInteraction(false);
    };
  }, [controls, invalidate]);
  return null;
}

interface BatchPreviewModelsProps {
  items: BatchPreviewItem[];
  colorRemapMap: Record<string, string>;
  colorHeightMap: Record<string, number>;
  baseHeight: number;
  enableRelief: boolean;
  spacerThick: number;
  structureMode: string;
  enableOutline: boolean;
  outlineWidth: number;
  enableCloisonne: boolean;
  wireWidthMm: number;
  wireHeightMm: number;
  enableFridgeMagnet: boolean;
  rasterCellSize?: number;
}

function BatchPreviewModels({
  items,
  colorRemapMap,
  colorHeightMap,
  baseHeight,
  enableRelief,
  spacerThick,
  structureMode,
  enableOutline,
  outlineWidth,
  enableCloisonne,
  wireWidthMm,
  wireHeightMm,
  enableFridgeMagnet,
  rasterCellSize,
}: BatchPreviewModelsProps) {
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls);
  const bed_label = useConverterStore((s) => s.bed_label);
  const bedSizes = useConverterStore((s) => s.bedSizes);

  const bedDims = useMemo(() => {
    const found = bedSizes.find((b) => b.label === bed_label);
    return found ? { w: found.width_mm, h: found.height_mm } : { w: 256, h: 256 };
  }, [bed_label, bedSizes]);

  const positionedItems = useMemo(
    () =>
      items.map((item) => ({
        ...item,
        position: [
          item.tx_mm + item.width_mm / 2 - bedDims.w / 2,
          item.ty_mm + item.depth_mm / 2 - bedDims.h / 2,
          0,
        ] as [number, number, number],
      })),
    [bedDims.h, bedDims.w, items],
  );

  useEffect(() => {
    if (positionedItems.length === 0) {
      return;
    }
    const minX = Math.min(
      -bedDims.w / 2,
      ...items.map((item) => item.tx_mm - bedDims.w / 2),
    );
    const maxX = Math.max(
      bedDims.w / 2,
      ...items.map((item) => item.tx_mm + item.width_mm - bedDims.w / 2),
    );
    const minY = Math.min(
      -bedDims.h / 2,
      ...items.map((item) => item.ty_mm - bedDims.h / 2),
    );
    const maxY = Math.max(
      bedDims.h / 2,
      ...items.map((item) => item.ty_mm + item.depth_mm - bedDims.h / 2),
    );
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    const radius = Math.max(maxX - minX, maxY - minY) / 2;
    const perspCam = camera as THREE.PerspectiveCamera;
    const dist = computeFitDistance(radius, perspCam.fov) * 1.25;

    camera.position.set(centerX, centerY - 57, dist);
    camera.lookAt(centerX, centerY, 0);
    camera.updateProjectionMatrix();

    if (controls) {
      const oc = controls as unknown as {
        target: THREE.Vector3;
        maxDistance: number;
        minDistance: number;
        update: () => void;
      };
      oc.target.set(centerX, centerY, 0);
      oc.maxDistance = dist * 5;
      oc.minDistance = dist * 0.1;
      oc.update();
    }
  }, [bedDims.h, bedDims.w, camera, controls, items, positionedItems.length]);

  return (
    <>
      {positionedItems.map((item, index) => (
        <group key={`${item.url}-${index}`} position={item.position}>
          <InteractiveModelViewer
            url={item.url}
            colorRemapMap={colorRemapMap}
            colorHeightMap={colorHeightMap}
            baseHeight={baseHeight}
            enableRelief={enableRelief}
            scaleX={1}
            scaleY={1}
            spacerThick={spacerThick}
            structureMode={structureMode}
            enableOutline={enableOutline}
            outlineWidth={outlineWidth}
            enableCloisonne={enableCloisonne}
            wireWidthMm={wireWidthMm}
            wireHeightMm={wireHeightMm}
            enableFridgeMagnet={enableFridgeMagnet}
            rasterCellSize={rasterCellSize}
            puzzleOverlayEnabled={false}
            puzzleOverlayUrl={null}
          />
        </group>
      ))}
    </>
  );
}

function Scene3D({ modelUrl }: Scene3DProps) {
  const { t } = useI18n();
  const themeColors = useThemeConfig();
  const containerRef = useRef<HTMLDivElement>(null);
  const glRef = useRef<THREE.WebGLRenderer | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [diagnostics, setDiagnostics] = useState<SceneDiagnosticsSnapshot | null>(null);
  const [diagnosticsVisible, setDiagnosticsVisible] = useState(false);

  // Witty Loading Messages (Req 1.4 & Enhancements)
  const isLoading = useConverterStore((s) => s.isLoading);
  const enableWittyLoading = useSettingsStore((s) => s.enableWittyLoading);
  const wittyMsg = useWittyMessage(2000, isLoading && enableWittyLoading);

  const storeModelUrl = useConverterStore((s) => s.modelUrl);
  const effectiveModelUrl = modelUrl ?? storeModelUrl;
  const batchPreviewItems = useConverterStore((s) => s.batchPreviewItems);
  const previewGlbUrl = useConverterStore((s) => s.previewGlbUrl);
  const colorRemapMap = useConverterStore((s) => s.colorRemapMap);
  const colorHeightMap = useConverterStore((s) => s.color_height_map);
  const baseHeight = useConverterStore((s) => s.spacer_thick);
  const enableRelief = useConverterStore((s) => s.enable_relief);
  const spacerThick = useConverterStore((s) => s.spacer_thick);
  const structureMode = useConverterStore((s) => s.structure_mode);
  const enableOutline = useConverterStore((s) => s.enable_outline);
  const outlineWidth = useConverterStore((s) => s.outline_width);
  const enableCloisonne = useConverterStore((s) => s.enable_cloisonne);
  const wireWidthMm = useConverterStore((s) => s.wire_width_mm);
  const wireHeightMm = useConverterStore((s) => s.wire_height_mm);
  const puzzleEnabled = useConverterStore((s) => s.puzzleEnabled);
  const puzzleOverlayUrl = useConverterStore((s) => s.puzzleOverlayUrl);

  // Real-time scale dimensions
  const targetWidth = useConverterStore((s) => s.target_width_mm);
  const targetHeight = useConverterStore((s) => s.target_height_mm);
  const previewWidth = useConverterStore((s) => s.preview_width_mm);
  const previewHeight = useConverterStore((s) => s.preview_height_mm);
  const previewPixelWidth = useConverterStore((s) => s.previewPixelWidth);

  const { scaleX, scaleY } = computeScaleFactor(
    targetWidth, targetHeight, previewWidth, previewHeight
  );
  const rasterCellSize = previewWidth && previewPixelWidth && previewPixelWidth > 0
    ? previewWidth / previewPixelWidth
    : undefined;

  // Keychain ring params
  const addLoop = useConverterStore((s) => s.add_loop);
  const loopWidth = useConverterStore((s) => s.loop_width);
  const loopLength = useConverterStore((s) => s.loop_length);
  const loopHole = useConverterStore((s) => s.loop_hole);
  const loopAngle = useConverterStore((s) => s.loop_angle);
  const loopOffsetX = useConverterStore((s) => s.loop_offset_x);
  const loopOffsetY = useConverterStore((s) => s.loop_offset_y);
  const loopPositionPreset = useConverterStore((s) => s.loop_position_preset);
  const enableFridgeMagnet = useConverterStore((s) => s.enable_fridge_magnet);
  const fridgeMagnets = useConverterStore((s) => s.fridge_magnets);
  const selectedFridgeMagnetId = useConverterStore((s) => s.selectedFridgeMagnetId);
  const selectFridgeMagnet = useConverterStore((s) => s.selectFridgeMagnet);
  const updateFridgeMagnetCenter = useConverterStore((s) => s.updateFridgeMagnetCenter);
  const modelBounds = useConverterStore((s) => s.modelBounds);
  const diagnosticsSamplingEnabled = diagnosticsVisible || getThreePerfDebugConfig().enabled;

  const diagnosticsSourceLabel = batchPreviewItems.length > 0
    ? t("viewer_diagnostics_source_generate")
    : effectiveModelUrl
    ? t("viewer_diagnostics_source_generate")
    : previewGlbUrl
      ? t("viewer_diagnostics_source_preview")
      : t("viewer_diagnostics_source_idle");

  // Listen to fullscreenchange event
  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  const handleGlReady = useCallback((gl: THREE.WebGLRenderer) => {
    glRef.current = gl;
    const snapshot = {
      renderer: getRendererInfoSnapshot(gl),
      heap: getHeapMemorySnapshot(),
      fps: null,
    };
    setDiagnostics((current) => ({
      ...snapshot,
      fps: current?.fps ?? snapshot.fps,
    }));
    debugThreeLog("Scene3D.gl", {
      event: "ready",
      renderer: snapshot.renderer,
      heap: snapshot.heap,
    });
    postClientLog("viewer: gl ready", {
      scope: "viewer",
      phase: "gl-ready",
      dedupeMs: 250,
      details: {
        renderer: snapshot.renderer,
        heap: snapshot.heap,
      },
    });
  }, []);

  const handleDiagnosticsSample = useCallback((snapshot: SceneDiagnosticsSnapshot) => {
    setDiagnostics(snapshot);
  }, []);

  const toggleDiagnostics = useCallback(() => {
    const next = !diagnosticsVisible;
    setDiagnosticsVisible(next);
    postClientLog("viewer: diagnostics toggled", {
      scope: "viewer",
      phase: "diagnostics-toggle",
      details: {
        open: next,
        source: batchPreviewItems.length > 0
          ? "batch-preview"
          : effectiveModelUrl
            ? "generate"
            : previewGlbUrl
              ? "preview"
              : "idle",
      },
    });
  }, [batchPreviewItems.length, diagnosticsVisible, effectiveModelUrl, previewGlbUrl]);

  const toggleFullscreen = useCallback(() => {
    if (!containerRef.current) return;
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else {
      containerRef.current.requestFullscreen().catch(() => {
        // Fullscreen API not available, fail silently
      });
    }
  }, []);

  const takeScreenshot = useCallback(() => {
    const gl = glRef.current;
    if (!gl) return;
    // Render one frame with preserveDrawingBuffer behavior
    try {
      const dataUrl = gl.domElement.toDataURL("image/png");
      const link = document.createElement("a");
      link.download = `lumina-3d-screenshot-${Date.now()}.png`;
      link.href = dataUrl;
      link.click();
    } catch (err) {
      console.warn("Screenshot failed:", err);
    }
  }, []);

  useEffect(() => {
    postClientLog("viewer: source updated", {
      scope: "viewer",
      phase: "source-updated",
      dedupeMs: 250,
      details: {
        model_url: effectiveModelUrl ?? null,
        preview_glb_url: previewGlbUrl ?? null,
      },
    });
  }, [effectiveModelUrl, previewGlbUrl]);

  // Check if Fullscreen API is available
  const fullscreenSupported = typeof document.fullscreenElement !== "undefined";

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full"
      data-testid="scene3d-container"
    >
      {/* Floating action buttons — bottom-right with right-dock avoidance.
       * 浮动按钮组：右下角悬浮，依赖 WidgetWorkspace 注入的
       * `--lumina-right-dock-width` CSS 变量自动避开右侧坞内的 widget。
       */}
      <div
        className="absolute z-10 flex gap-1.5"
        style={{
          bottom: "12px",
          right: "calc(var(--lumina-right-dock-width, 0px) + 12px)",
        }}
      >
        <button
          onClick={toggleDiagnostics}
          aria-pressed={diagnosticsVisible}
          aria-label={t("viewer_diagnostics_toggle")}
          title={t("viewer_diagnostics_toggle")}
          data-testid="scene3d-diagnostics-toggle"
          className={
            "inline-flex h-9 w-9 items-center justify-center rounded-full border backdrop-blur-sm shadow-[var(--shadow-control)] transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)] " +
            (diagnosticsVisible
              ? "border-blue-500/60 bg-blue-500/15 text-blue-600 dark:text-blue-300"
              : "border-slate-200/80 bg-slate-100/85 text-slate-600 hover:bg-slate-200/90 dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:bg-slate-800/80")
          }
        >
          <ActivityIcon className="h-4 w-4" />
        </button>
        {fullscreenSupported && (
          <button
            onClick={toggleFullscreen}
            aria-label={isFullscreen ? t("viewer_exit_fullscreen") : t("viewer_fullscreen")}
            title={isFullscreen ? t("viewer_exit_fullscreen") : t("viewer_fullscreen")}
            className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-slate-200/80 bg-slate-100/85 text-slate-600 backdrop-blur-sm shadow-[var(--shadow-control)] transition-colors hover:bg-slate-200/90 focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:bg-slate-800/80"
          >
            {isFullscreen ? <MinimizeIcon className="h-4 w-4" /> : <MaximizeIcon className="h-4 w-4" />}
          </button>
        )}
        <button
          onClick={takeScreenshot}
          aria-label={t("viewer_screenshot")}
          title={t("viewer_screenshot")}
          className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-slate-200/80 bg-slate-100/85 text-slate-600 backdrop-blur-sm shadow-[var(--shadow-control)] transition-colors hover:bg-slate-200/90 focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:bg-slate-800/80"
        >
          <CameraIcon className="h-4 w-4" />
        </button>
      </div>

      {diagnosticsVisible && (
        <div
          role="dialog"
          aria-label={t("viewer_diagnostics_title")}
          className="absolute z-10 w-[260px] rounded-xl border px-3 py-2 text-[11px] shadow-xl"
          style={{
            bottom: "56px",
            right: "calc(var(--lumina-right-dock-width, 0px) + 12px)",
            borderColor: "var(--surface-outline)",
            background: "color-mix(in srgb, var(--surface-panel-strong) 90%, transparent)",
            color: "var(--surface-text-muted)",
          }}
          data-testid="scene3d-diagnostics-panel"
        >
          <div className="mb-2">
            <span className="text-xs font-semibold text-slate-900 dark:text-slate-50">
              {t("viewer_diagnostics_title")}
            </span>
          </div>
          <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <span>{t("viewer_diagnostics_source")}</span>
            <span className="truncate text-right">{diagnosticsSourceLabel}</span>
            <span>{t("viewer_diagnostics_fps")}</span>
            <span className="text-right flex items-center justify-end gap-1.5">
              {diagnostics?.fps != null ? (
                <>
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-full flex-shrink-0"
                    style={{
                      backgroundColor:
                        diagnostics.fps >= 50
                          ? "#22c55e"
                          : diagnostics.fps >= 30
                            ? "#eab308"
                            : "#ef4444",
                    }}
                  />
                  {diagnostics.fps.toFixed(1)}
                </>
              ) : (
                "—"
              )}
            </span>
            <span>{t("viewer_diagnostics_frame_time")}</span>
            <span className="text-right">
              {diagnostics?.fps != null && diagnostics.fps > 0
                ? `${(1000 / diagnostics.fps).toFixed(1)} ms`
                : "—"}
            </span>
            <span>{t("viewer_diagnostics_js_heap")}</span>
            <span className="text-right">
              {diagnostics?.heap
                ? `${diagnostics.heap.used_js_heap_mb} / ${diagnostics.heap.total_js_heap_mb} MB`
                : t("viewer_diagnostics_js_heap_unavailable")}
            </span>
            <span>{t("viewer_diagnostics_triangles")}</span>
            <span className="text-right">{diagnostics?.renderer.triangles ?? "—"}</span>
            <span>{t("viewer_diagnostics_draw_calls")}</span>
            <span className="text-right">{diagnostics?.renderer.calls ?? "—"}</span>
            <span>{t("viewer_diagnostics_textures")}</span>
            <span className="text-right">{diagnostics?.renderer.textures ?? "—"}</span>
            <span>{t("viewer_diagnostics_canvas")}</span>
            <span className="text-right">
              {diagnostics?.renderer
                ? `${diagnostics.renderer.canvas_width}×${diagnostics.renderer.canvas_height} @${diagnostics.renderer.pixel_ratio}x`
                : "—"}
            </span>
          </div>
        </div>
      )}

      {/* Loading indicator is now 3D-anchored inside Canvas */}

      <Canvas
        frameloop="demand"
        camera={{ position: [0, -57, 474], fov: 45 }}
        gl={{ preserveDrawingBuffer: true, toneMapping: THREE.NeutralToneMapping }}
        onPointerMissed={() => {
          if (enableFridgeMagnet) {
            selectFridgeMagnet(null);
          }
        }}
        onCreated={({ gl }) => {
          gl.setClearColor(themeColors.canvasClearColor);
          const canvas = gl.domElement;
          postClientLog("viewer: canvas created", {
            scope: "viewer",
            phase: "canvas-created",
            dedupeMs: 250,
            details: {
              renderer: getRendererInfoSnapshot(gl),
              heap: getHeapMemorySnapshot(),
            },
          });
          canvas.addEventListener("webglcontextlost", (e) => {
            e.preventDefault();
            postClientLog("viewer: webgl context lost", {
              scope: "viewer",
              phase: "context-lost",
              method: "warn",
              details: {
                canvas_width: canvas.width,
                canvas_height: canvas.height,
              },
            });
          });
          canvas.addEventListener("webglcontextrestored", () => {
            gl.setSize(canvas.clientWidth, canvas.clientHeight);
            postClientLog("viewer: webgl context restored", {
              scope: "viewer",
              phase: "context-restored",
              details: {
                renderer: getRendererInfoSnapshot(gl),
                heap: getHeapMemorySnapshot(),
              },
            });
          });
        }}
      >
        <ScreenshotHelper onGlReady={handleGlReady} />
        <RendererDiagnosticsBridge
          enabled={diagnosticsSamplingEnabled}
          onSample={handleDiagnosticsSample}
        />
        <CameraDebugHelper />
        <ThemeUpdater />
        <CanvasInteractionBridge />
        <Suspense fallback={null}>
          <Environment
            files={LIGHTING_CONFIG.environment.hdrFile}
            background={false}
            environmentIntensity={themeColors.environmentIntensity}
          />
        </Suspense>
        <directionalLight
          position={[...LIGHTING_CONFIG.keyLight.position]}
          intensity={themeColors.keyLightIntensity}
          color={themeColors.keyLightColor}
        />
        <OrbitControls
          makeDefault
          enableDamping
          dampingFactor={0.1}
          minDistance={10}
          maxDistance={2000}
        />
        <BedPlatform />
        {batchPreviewItems.length > 0 ? (
          <Suspense fallback={null}>
            <BatchPreviewModels
              items={batchPreviewItems}
              colorRemapMap={colorRemapMap}
              colorHeightMap={colorHeightMap}
              baseHeight={baseHeight}
              enableRelief={enableRelief}
              spacerThick={spacerThick}
              structureMode={structureMode}
              enableOutline={enableOutline}
              outlineWidth={outlineWidth}
              enableCloisonne={enableCloisonne}
              wireWidthMm={wireWidthMm}
              wireHeightMm={wireHeightMm}
              enableFridgeMagnet={enableFridgeMagnet}
              rasterCellSize={rasterCellSize}
            />
          </Suspense>
        ) : effectiveModelUrl ? (
          <Suspense fallback={null}>
            <InteractiveModelViewer
              url={effectiveModelUrl}
              colorRemapMap={colorRemapMap}
              colorHeightMap={colorHeightMap}
              baseHeight={baseHeight}
              enableRelief={enableRelief}
              scaleX={scaleX}
              scaleY={scaleY}
              spacerThick={spacerThick}
              structureMode={structureMode}
              enableOutline={enableOutline}
              outlineWidth={outlineWidth}
              enableCloisonne={enableCloisonne}
              wireWidthMm={wireWidthMm}
              wireHeightMm={wireHeightMm}
              enableFridgeMagnet={enableFridgeMagnet}
              rasterCellSize={rasterCellSize}
              puzzleOverlayEnabled={puzzleEnabled && Boolean(puzzleOverlayUrl)}
              puzzleOverlayUrl={puzzleOverlayUrl}
            />
          </Suspense>
        ) : previewGlbUrl ? (
          <Suspense fallback={null}>
            <InteractiveModelViewer
              url={previewGlbUrl}
              colorRemapMap={colorRemapMap}
              colorHeightMap={colorHeightMap}
              baseHeight={baseHeight}
              enableRelief={enableRelief}
              scaleX={scaleX}
              scaleY={scaleY}
              spacerThick={spacerThick}
              structureMode={structureMode}
              enableOutline={enableOutline}
              outlineWidth={outlineWidth}
              enableCloisonne={enableCloisonne}
              wireWidthMm={wireWidthMm}
              wireHeightMm={wireHeightMm}
              enableFridgeMagnet={enableFridgeMagnet}
              rasterCellSize={rasterCellSize}
              puzzleOverlayEnabled={puzzleEnabled && Boolean(puzzleOverlayUrl)}
              puzzleOverlayUrl={puzzleOverlayUrl}
            />
          </Suspense>
        ) : null}
        {batchPreviewItems.length === 0 && addLoop && modelBounds && (
          <KeychainRing3D
            enabled={addLoop}
            width={loopWidth}
            length={loopLength}
            hole={loopHole}
            angle={loopAngle}
            offsetX={loopOffsetX}
            offsetY={loopOffsetY}
            positionPreset={loopPositionPreset}
            modelBounds={modelBounds}
          />
        )}
        {batchPreviewItems.length === 0 && enableFridgeMagnet && modelBounds && fridgeMagnets.length > 0 && (
          <FridgeMagnet3D
            enabled={enableFridgeMagnet}
            magnets={fridgeMagnets}
            selectedMagnetId={selectedFridgeMagnetId}
            modelBounds={modelBounds}
            scaleX={scaleX}
            scaleY={scaleY}
            onSelectMagnet={selectFridgeMagnet}
            onUpdateMagnetCenter={updateFridgeMagnetCenter}
          />
        )}

        {/* 3D-Anchored Loading & Witty Messages (Req 1.4) */}
        {isLoading && (
          <Html center position={[0, 0, 80]} zIndexRange={[100, 0]}>
            <div
              className="flex flex-col items-center justify-center gap-4 select-none pointer-events-none"
              data-testid="loading-overlay"
            >
              <div className="relative flex items-center justify-center p-4">
                <div className="relative flex h-20 w-20 items-center justify-center">
                  <div className="absolute inset-0 rgb-loader-ring" />
                  <div className="h-3 w-3 rounded-full bg-slate-100/90 dark:bg-slate-50/90" />
                </div>
              </div>
              {enableWittyLoading && (
                <div className="rounded-full border border-white/10 bg-slate-900/92 px-4 py-2">
                  <p className="whitespace-nowrap text-sm font-medium tracking-wide text-white">
                    {wittyMsg}
                  </p>
                </div>
              )}
            </div>
          </Html>
        )}
      </Canvas>

    </div>
  );
}

export default Scene3D;
