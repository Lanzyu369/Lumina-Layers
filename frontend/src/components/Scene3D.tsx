import { Suspense, useRef, useState, useEffect, useCallback, useMemo } from "react";
import { createPortal } from "react-dom";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, Environment, Html } from "@react-three/drei";
import { LIGHTING_CONFIG } from "./lightingConfig";
import * as THREE from "three";
import ModelViewer from "./ModelViewer";
import InteractiveModelViewer, { type ViewerHoverSample } from "./InteractiveModelViewer";
import BedPlatform from "./BedPlatform";
import KeychainRing3D from "./KeychainRing3D";
import FridgeMagnet3D from "./FridgeMagnet3D";
import PreviewHoverInspector from "./ui/PreviewHoverInspector";
import { buildLayerImagesSourceKey, useConverterStore } from "../stores/converter";
import { computeScaleFactor } from "../utils/scaleUtils";
import { useI18n } from "../i18n/context";
import { useThemeConfig } from "../hooks/useThemeConfig";
import { useWittyMessage } from "../hooks/useWittyMessage";
import { computeHoverInspectorStyle } from "./ui/previewHoverInspectorUtils";

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

const EMPTY_LAYER_IMAGES: { layer_index: number; name: string; url: string }[] = [];

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
  }, [camera, controls]);
  return null;
}

/**
 * Inner component that syncs the Canvas clear color with the active theme.
 * Canvas 内部组件，将清除色与当前主题同步。
 */
function ThemeUpdater() {
  const { gl } = useThree();
  const themeColors = useThemeConfig();
  useEffect(() => {
    gl.setClearColor(themeColors.canvasClearColor);
  }, [gl, themeColors.canvasClearColor]);
  return null;
}

interface LayerHoverColorSample {
  displayIndex: number;
  layerName: string;
  colorHex: string | null;
}

interface LayerCanvasBuffer {
  layerIndex: number;
  name: string;
  width: number;
  height: number;
  context: CanvasRenderingContext2D;
}

const MAGNIFIER_SIZE_PX = 152;
const MAGNIFIER_ZOOM = 3;
const HOVER_POPOVER_DELAY_MS = 180;

type HoverPerfWindow = Window & { __luminaHoverPerfDebug?: boolean };

interface SceneHoverPerfStats {
  layerSampleRuns: number;
  layerCacheHits: number;
  layerCacheMisses: number;
  totalLayerSampleMs: number;
  maxLayerSampleMs: number;
  magnifierDrawRuns: number;
  totalMagnifierDrawMs: number;
  maxMagnifierDrawMs: number;
  hoverShowCount: number;
  hoverHideCount: number;
  timerScheduleCount: number;
  timerCancelCount: number;
  lastLogAt: number;
}

function isHoverPerfDebugEnabled(): boolean {
  if (typeof window === "undefined") return false;
  return Boolean((window as HoverPerfWindow).__luminaHoverPerfDebug);
}

function clampNumber(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function rgbToHex(r: number, g: number, b: number): string {
  const toHex = (component: number) => component.toString(16).padStart(2, "0").toUpperCase();
  return `${toHex(r)}${toHex(g)}${toHex(b)}`;
}

function areLayerSamplesEqual(
  left: LayerHoverColorSample[],
  right: LayerHoverColorSample[],
): boolean {
  if (left === right) return true;
  if (left.length !== right.length) return false;
  for (let i = 0; i < left.length; i += 1) {
    const a = left[i];
    const b = right[i];
    if (
      a.displayIndex !== b.displayIndex
      || a.layerName !== b.layerName
      || a.colorHex !== b.colorHex
    ) {
      return false;
    }
  }
  return true;
}

function areHoverSamplesEqual(
  left: ViewerHoverSample | null,
  right: ViewerHoverSample | null,
): boolean {
  if (left === right) return true;
  if (!left || !right) return false;
  return (
    left.containerX === right.containerX
    && left.containerY === right.containerY
    && left.containerWidth === right.containerWidth
    && left.containerHeight === right.containerHeight
    && left.containerLeft === right.containerLeft
    && left.containerTop === right.containerTop
    &&
    left.canvasX === right.canvasX
    && left.canvasY === right.canvasY
    && left.pixelX === right.pixelX
    && left.pixelY === right.pixelY
    && left.hitColorHex === right.hitColorHex
  );
}

function Scene3D({ modelUrl }: Scene3DProps) {
  const { t } = useI18n();
  const themeColors = useThemeConfig();
  const containerRef = useRef<HTMLDivElement>(null);
  const glRef = useRef<THREE.WebGLRenderer | null>(null);
  const magnifierCanvasRef = useRef<HTMLCanvasElement>(null);
  const layerCanvasBuffersRef = useRef<LayerCanvasBuffer[]>([]);
  const layerSampleCacheRef = useRef<Map<string, LayerHoverColorSample[]>>(new Map());
  const pendingHoverSampleRef = useRef<ViewerHoverSample | null>(null);
  const hoverDelayTimerRef = useRef<number | null>(null);
  const sceneHoverPerfStatsRef = useRef<SceneHoverPerfStats>({
    layerSampleRuns: 0,
    layerCacheHits: 0,
    layerCacheMisses: 0,
    totalLayerSampleMs: 0,
    maxLayerSampleMs: 0,
    magnifierDrawRuns: 0,
    totalMagnifierDrawMs: 0,
    maxMagnifierDrawMs: 0,
    hoverShowCount: 0,
    hoverHideCount: 0,
    timerScheduleCount: 0,
    timerCancelCount: 0,
    lastLogAt: performance.now(),
  });
  const activeLayerPreviewRef = useRef<string | null>(null);
  const fetchedLayerPreviewRef = useRef<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isOrbiting, setIsOrbiting] = useState(false);
  const [hoverSample, setHoverSample] = useState<ViewerHoverSample | null>(null);
  const [hoverLayerColors, setHoverLayerColors] = useState<LayerHoverColorSample[]>([]);
  const hoverPixelX = hoverSample?.pixelX ?? null;
  const hoverPixelY = hoverSample?.pixelY ?? null;

  // Witty Loading Messages (Req 1.4 & Enhancements)
  const isLoading = useConverterStore((s) => s.isLoading);
  const wittyMsg = useWittyMessage(2000, isLoading);

  const previewGlbUrl = useConverterStore((s) => s.previewGlbUrl);
  const colorRemapMap = useConverterStore((s) => s.colorRemapMap);
  const colorHeightMap = useConverterStore((s) => s.color_height_map);
  const selectedColor = useConverterStore((s) => s.selectedColor);
  const sessionId = useConverterStore((s) => s.sessionId);
  const layerImages = useConverterStore((s) => s.layerImages);
  const layerImagesLoading = useConverterStore((s) => s.layerImagesLoading);
  const layerImagesSourceKey = useConverterStore((s) => s.layerImagesSourceKey);
  const layerImagesCurrentKey = useConverterStore(buildLayerImagesSourceKey);
  const fetchLayerImages = useConverterStore((s) => s.fetchLayerImages);
  const resetLayerImages = useConverterStore((s) => s.resetLayerImages);
  const previewPixelWidth = useConverterStore((s) => s.previewPixelWidth);
  const previewPixelHeight = useConverterStore((s) => s.previewPixelHeight);
  const baseHeight = useConverterStore((s) => s.spacer_thick);
  const enableRelief = useConverterStore((s) => s.enable_relief);
  const setSelectedColor = useConverterStore((s) => s.setSelectedColor);
  const spacerThick = useConverterStore((s) => s.spacer_thick);
  const structureMode = useConverterStore((s) => s.structure_mode);
  const enableOutline = useConverterStore((s) => s.enable_outline);
  const outlineWidth = useConverterStore((s) => s.outline_width);
  const enableCloisonne = useConverterStore((s) => s.enable_cloisonne);
  const wireWidthMm = useConverterStore((s) => s.wire_width_mm);
  const wireHeightMm = useConverterStore((s) => s.wire_height_mm);
  const puzzleEnabled = useConverterStore((s) => s.puzzleEnabled);
  const puzzleOverlayUrl = useConverterStore((s) => s.puzzleOverlayUrl);
  const activeLayerImages = useMemo(
    () => (layerImagesSourceKey === layerImagesCurrentKey ? layerImages : EMPTY_LAYER_IMAGES),
    [layerImagesSourceKey, layerImagesCurrentKey, layerImages],
  );

  const maybeFlushScenePerfLog = useCallback((force = false) => {
    if (!isHoverPerfDebugEnabled()) {
      return;
    }

    const stats = sceneHoverPerfStatsRef.current;
    const now = performance.now();
    const elapsed = Math.max(1, now - stats.lastLogAt);
    if (!force && elapsed < 1000) {
      return;
    }

    const avgLayerSampleMs =
      stats.layerSampleRuns > 0 ? +(stats.totalLayerSampleMs / stats.layerSampleRuns).toFixed(3) : 0;
    const avgMagnifierMs =
      stats.magnifierDrawRuns > 0 ? +(stats.totalMagnifierDrawMs / stats.magnifierDrawRuns).toFixed(3) : 0;

    console.info("[HoverPerf][Scene3D]", {
      elapsed_ms: +elapsed.toFixed(1),
      layer_cache_hits: stats.layerCacheHits,
      layer_cache_misses: stats.layerCacheMisses,
      layer_sample_runs: stats.layerSampleRuns,
      layer_sample_avg_ms: avgLayerSampleMs,
      layer_sample_max_ms: +stats.maxLayerSampleMs.toFixed(3),
      magnifier_draw_runs: stats.magnifierDrawRuns,
      magnifier_avg_ms: avgMagnifierMs,
      magnifier_max_ms: +stats.maxMagnifierDrawMs.toFixed(3),
      hover_show_count: stats.hoverShowCount,
      hover_hide_count: stats.hoverHideCount,
      timer_schedule_count: stats.timerScheduleCount,
      timer_cancel_count: stats.timerCancelCount,
    });

    stats.layerSampleRuns = 0;
    stats.layerCacheHits = 0;
    stats.layerCacheMisses = 0;
    stats.totalLayerSampleMs = 0;
    stats.maxLayerSampleMs = 0;
    stats.magnifierDrawRuns = 0;
    stats.totalMagnifierDrawMs = 0;
    stats.maxMagnifierDrawMs = 0;
    stats.hoverShowCount = 0;
    stats.hoverHideCount = 0;
    stats.timerScheduleCount = 0;
    stats.timerCancelCount = 0;
    stats.lastLogAt = now;
  }, []);

  // Real-time scale dimensions
  const targetWidth = useConverterStore((s) => s.target_width_mm);
  const targetHeight = useConverterStore((s) => s.target_height_mm);
  const previewWidth = useConverterStore((s) => s.preview_width_mm);
  const previewHeight = useConverterStore((s) => s.preview_height_mm);

  const { scaleX, scaleY } = computeScaleFactor(
    targetWidth, targetHeight, previewWidth, previewHeight
  );

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
  const viewerSelectedColor = enableFridgeMagnet ? null : selectedColor;

  // Listen to fullscreenchange event
  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  useEffect(() => {
    if (!sessionId) {
      activeLayerPreviewRef.current = null;
      fetchedLayerPreviewRef.current = null;
      return;
    }

    if (
      !previewGlbUrl ||
      !layerImagesCurrentKey ||
      layerImagesLoading ||
      activeLayerImages.length > 0
    ) {
      return;
    }
    if (fetchedLayerPreviewRef.current === layerImagesCurrentKey) {
      return;
    }

    fetchedLayerPreviewRef.current = layerImagesCurrentKey;
    void fetchLayerImages(layerImagesCurrentKey);
  }, [
    previewGlbUrl,
    sessionId,
    layerImagesCurrentKey,
    layerImagesLoading,
    activeLayerImages.length,
    fetchLayerImages,
  ]);

  useEffect(() => {
    if (activeLayerPreviewRef.current && activeLayerPreviewRef.current !== previewGlbUrl) {
      fetchedLayerPreviewRef.current = null;
      resetLayerImages();
    }
    activeLayerPreviewRef.current = previewGlbUrl;

    if (!previewGlbUrl) {
      fetchedLayerPreviewRef.current = null;
      if (hoverDelayTimerRef.current !== null) {
        window.clearTimeout(hoverDelayTimerRef.current);
        hoverDelayTimerRef.current = null;
        sceneHoverPerfStatsRef.current.timerCancelCount += 1;
      }
      pendingHoverSampleRef.current = null;
      layerSampleCacheRef.current.clear();
      setHoverSample(null);
      setHoverLayerColors([]);
    }
  }, [previewGlbUrl, resetLayerImages]);

  useEffect(() => {
    if (!isOrbiting) {
      return;
    }
    if (hoverDelayTimerRef.current !== null) {
      window.clearTimeout(hoverDelayTimerRef.current);
      hoverDelayTimerRef.current = null;
      sceneHoverPerfStatsRef.current.timerCancelCount += 1;
    }
    pendingHoverSampleRef.current = null;
    setHoverSample((previous) => {
      if (previous !== null) {
        sceneHoverPerfStatsRef.current.hoverHideCount += 1;
      }
      return previous === null ? previous : null;
    });
    setHoverLayerColors((previous) => (previous.length === 0 ? previous : []));
  }, [isOrbiting]);

  useEffect(() => {
    const stats = sceneHoverPerfStatsRef.current;
    return () => {
      if (hoverDelayTimerRef.current !== null) {
        window.clearTimeout(hoverDelayTimerRef.current);
        hoverDelayTimerRef.current = null;
        stats.timerCancelCount += 1;
      }
      maybeFlushScenePerfLog(true);
    };
  }, [maybeFlushScenePerfLog]);

  useEffect(() => {
    let cancelled = false;

    if (activeLayerImages.length === 0) {
      layerCanvasBuffersRef.current = [];
      layerSampleCacheRef.current.clear();
      return () => {
        cancelled = true;
      };
    }

      const buildBuffers = async () => {
      const loaded = await Promise.all(
        activeLayerImages.map(
          (layer) =>
            new Promise<LayerCanvasBuffer | null>((resolve) => {
              const image = new Image();
              image.onload = () => {
                const width = image.naturalWidth || image.width;
                const height = image.naturalHeight || image.height;
                const canvas = document.createElement("canvas");
                canvas.width = width;
                canvas.height = height;
                const context = canvas.getContext("2d", { willReadFrequently: true });
                if (!context || width <= 0 || height <= 0) {
                  resolve(null);
                  return;
                }
                context.drawImage(image, 0, 0);
                resolve({
                  layerIndex: layer.layer_index,
                  name: layer.name,
                  width,
                  height,
                  context,
                });
              };
              image.onerror = () => resolve(null);
              image.src = layer.url;
            }),
        ),
      );

      if (cancelled) {
        return;
      }

      layerCanvasBuffersRef.current = loaded.filter(
        (entry): entry is LayerCanvasBuffer => entry !== null,
      );
      layerSampleCacheRef.current.clear();
    };

    void buildBuffers();

    return () => {
      cancelled = true;
    };
  }, [activeLayerImages]);

  useEffect(() => {
    if (hoverPixelX === null || hoverPixelY === null) {
      setHoverLayerColors((previous) => (previous.length === 0 ? previous : []));
      return;
    }

    const buffers = layerCanvasBuffersRef.current;
    if (buffers.length === 0) {
      setHoverLayerColors((previous) => (previous.length === 0 ? previous : []));
      return;
    }

    const cacheKey = `${hoverPixelX},${hoverPixelY}`;
    const cached = layerSampleCacheRef.current.get(cacheKey);
    if (cached) {
      sceneHoverPerfStatsRef.current.layerCacheHits += 1;
      setHoverLayerColors((previous) => (areLayerSamplesEqual(previous, cached) ? previous : cached));
      maybeFlushScenePerfLog(false);
      return;
    }

    const sampleStart = performance.now();
    sceneHoverPerfStatsRef.current.layerCacheMisses += 1;
    sceneHoverPerfStatsRef.current.layerSampleRuns += 1;

    const sampled = buffers.map((layer, index) => {
      const baseWidth = previewPixelWidth && previewPixelWidth > 0 ? previewPixelWidth : layer.width;
      const baseHeight = previewPixelHeight && previewPixelHeight > 0 ? previewPixelHeight : layer.height;
      const x = clampNumber(
        Math.round((hoverPixelX / Math.max(baseWidth - 1, 1)) * (layer.width - 1)),
        0,
        Math.max(layer.width - 1, 0),
      );
      const y = clampNumber(
        Math.round((hoverPixelY / Math.max(baseHeight - 1, 1)) * (layer.height - 1)),
        0,
        Math.max(layer.height - 1, 0),
      );

      try {
        const rgba = layer.context.getImageData(x, y, 1, 1).data;
        const alpha = rgba[3];
        return {
          displayIndex: index + 1,
          layerName: layer.name,
          colorHex: alpha <= 8 ? null : rgbToHex(rgba[0], rgba[1], rgba[2]),
        };
      } catch {
        return {
          displayIndex: index + 1,
          layerName: layer.name,
          colorHex: null,
        };
      }
    });

    const sampleMs = performance.now() - sampleStart;
    sceneHoverPerfStatsRef.current.totalLayerSampleMs += sampleMs;
    sceneHoverPerfStatsRef.current.maxLayerSampleMs = Math.max(
      sceneHoverPerfStatsRef.current.maxLayerSampleMs,
      sampleMs,
    );

    layerSampleCacheRef.current.set(cacheKey, sampled);
    setHoverLayerColors((previous) => (areLayerSamplesEqual(previous, sampled) ? previous : sampled));
    maybeFlushScenePerfLog(sampleMs > 8);
  }, [
    hoverPixelX,
    hoverPixelY,
    previewPixelWidth,
    previewPixelHeight,
    activeLayerImages,
    maybeFlushScenePerfLog,
  ]);

  useEffect(() => {
    const magnifierCanvas = magnifierCanvasRef.current;
    const context = magnifierCanvas?.getContext("2d");
    if (!magnifierCanvas || !context) {
      return;
    }

    context.clearRect(0, 0, magnifierCanvas.width, magnifierCanvas.height);

    if (!hoverSample) {
      return;
    }

    const webglCanvas = glRef.current?.domElement;
    if (!webglCanvas) {
      return;
    }

    const drawStart = performance.now();

    const dpr = window.devicePixelRatio || 1;
    const sourceSize = (MAGNIFIER_SIZE_PX / MAGNIFIER_ZOOM) * dpr;
    const maxSourceX = Math.max(0, webglCanvas.width - sourceSize);
    const maxSourceY = Math.max(0, webglCanvas.height - sourceSize);
    const sourceX = clampNumber(
      hoverSample.canvasX * dpr - sourceSize / 2,
      0,
      maxSourceX,
    );
    const sourceY = clampNumber(
      hoverSample.canvasY * dpr - sourceSize / 2,
      0,
      maxSourceY,
    );

    context.imageSmoothingEnabled = false;
    context.drawImage(
      webglCanvas,
      sourceX,
      sourceY,
      sourceSize,
      sourceSize,
      0,
      0,
      magnifierCanvas.width,
      magnifierCanvas.height,
    );

    const center = magnifierCanvas.width / 2;
    context.strokeStyle = "rgba(255, 255, 255, 0.9)";
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(center, 0);
    context.lineTo(center, magnifierCanvas.height);
    context.moveTo(0, center);
    context.lineTo(magnifierCanvas.width, center);
    context.stroke();

    const drawMs = performance.now() - drawStart;
    sceneHoverPerfStatsRef.current.magnifierDrawRuns += 1;
    sceneHoverPerfStatsRef.current.totalMagnifierDrawMs += drawMs;
    sceneHoverPerfStatsRef.current.maxMagnifierDrawMs = Math.max(
      sceneHoverPerfStatsRef.current.maxMagnifierDrawMs,
      drawMs,
    );
    maybeFlushScenePerfLog(drawMs > 8);
  }, [hoverSample, maybeFlushScenePerfLog]);

  const handleGlReady = useCallback((gl: THREE.WebGLRenderer) => {
    glRef.current = gl;
  }, []);

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

  const handleColorClick = useCallback(
    (hex: string | null) => {
      setSelectedColor(hex);
    },
    [setSelectedColor],
  );

  const handleHoverSample = useCallback((sample: ViewerHoverSample | null) => {
    const stats = sceneHoverPerfStatsRef.current;
    pendingHoverSampleRef.current = sample;

    if (hoverDelayTimerRef.current !== null) {
      window.clearTimeout(hoverDelayTimerRef.current);
      hoverDelayTimerRef.current = null;
      stats.timerCancelCount += 1;
    }

    if (sample === null) {
      setHoverSample((previous) => {
        if (previous !== null) {
          stats.hoverHideCount += 1;
        }
        return previous === null ? previous : null;
      });
      maybeFlushScenePerfLog(false);
      return;
    }

    setHoverSample((previous) => {
      if (previous !== null) {
        stats.hoverHideCount += 1;
      }
      return previous === null ? previous : null;
    });

    stats.timerScheduleCount += 1;
    hoverDelayTimerRef.current = window.setTimeout(() => {
      hoverDelayTimerRef.current = null;
      const pending = pendingHoverSampleRef.current;
      if (!pending) {
        return;
      }
      setHoverSample((previous) => {
        const next = areHoverSamplesEqual(previous, pending) ? previous : pending;
        if (previous === null && next !== null) {
          stats.hoverShowCount += 1;
        }
        return next;
      });
      maybeFlushScenePerfLog(false);
    }, HOVER_POPOVER_DELAY_MS);
  }, [maybeFlushScenePerfLog]);

  // Check if Fullscreen API is available
  const fullscreenSupported = typeof document.fullscreenElement !== "undefined";
  const surfaceHex = hoverSample
    ? (colorRemapMap[hoverSample.hitColorHex] || hoverSample.hitColorHex).toUpperCase()
    : null;
  const hoverInspectorStyle = (() => {
    if (!hoverSample) {
      return null;
    }
    return computeHoverInspectorStyle(hoverSample, {
      layerCount: hoverLayerColors.length,
      showMagnifier: true,
      showLayerDetails: true,
    });
  })();
  const hoverInspectorOverlay = hoverSample && hoverInspectorStyle && typeof document !== "undefined"
    ? createPortal(
      <PreviewHoverInspector
        dataTestId="viewer-hover-inspector"
        style={hoverInspectorStyle}
        magnifierCanvasRef={magnifierCanvasRef}
        pixelX={hoverSample.pixelX}
        pixelY={hoverSample.pixelY}
        surfaceHex={surfaceHex}
        hoverLayerColors={hoverLayerColors}
        layerImagesLoading={layerImagesLoading}
      />,
      document.body,
    )
    : null;

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full"
      data-testid="scene3d-container"
    >
      {/* Toolbar buttons */}
      <div className="absolute top-2 right-2 z-10 flex gap-1">
        {fullscreenSupported && (
          <button
            onClick={toggleFullscreen}
            className="rounded px-2 py-1 text-xs font-medium bg-slate-100/85 text-gray-700 transition-colors hover:bg-gray-200 dark:bg-gray-700/80 dark:text-gray-200 dark:hover:bg-gray-600 backdrop-blur-sm"
            aria-label={isFullscreen ? t("viewer_exit_fullscreen") : t("viewer_fullscreen")}
            title={isFullscreen ? t("viewer_exit_fullscreen") : t("viewer_fullscreen")}
          >
            {isFullscreen ? "⛶" : "⛶"} {isFullscreen ? t("viewer_exit_fullscreen") : t("viewer_fullscreen")}
          </button>
        )}
        <button
          onClick={takeScreenshot}
          className="rounded px-2 py-1 text-xs font-medium bg-slate-100/85 text-gray-700 transition-colors hover:bg-gray-200 dark:bg-gray-700/80 dark:text-gray-200 dark:hover:bg-gray-600 backdrop-blur-sm"
          aria-label={t("viewer_screenshot")}
          title={t("viewer_screenshot")}
        >
          {t("viewer_screenshot")}
        </button>
      </div>

      {/* Loading indicator is now 3D-anchored inside Canvas */}

      <Canvas
        camera={{ position: [0, -57, 474], fov: 45 }}
        gl={{ preserveDrawingBuffer: true }}
        onPointerMissed={() => {
          // Skip deselection if a color mesh was just clicked via native event
          const hitRef = (window as unknown as Record<string, unknown>).__luminaColorHitRef as
            | React.RefObject<boolean>
            | undefined;
          if (hitRef?.current) {
            hitRef.current = false;
            return;
          }
          if (hoverDelayTimerRef.current !== null) {
            window.clearTimeout(hoverDelayTimerRef.current);
            hoverDelayTimerRef.current = null;
            sceneHoverPerfStatsRef.current.timerCancelCount += 1;
          }
          pendingHoverSampleRef.current = null;
          if (enableFridgeMagnet) {
            selectFridgeMagnet(null);
          } else {
            setSelectedColor(null);
          }
          setHoverSample((previous) => {
            if (previous !== null) {
              sceneHoverPerfStatsRef.current.hoverHideCount += 1;
            }
            return previous === null ? previous : null;
          });
          maybeFlushScenePerfLog(false);
        }}
        onCreated={({ gl }) => {
          gl.setClearColor(themeColors.canvasClearColor);
          const canvas = gl.domElement;
          canvas.addEventListener("webglcontextlost", (e) => {
            e.preventDefault();
          });
          canvas.addEventListener("webglcontextrestored", () => {
            gl.setSize(canvas.clientWidth, canvas.clientHeight);
          });
        }}
      >
        <ScreenshotHelper onGlReady={handleGlReady} />
        <CameraDebugHelper />
        <ThemeUpdater />
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
          onStart={() => setIsOrbiting(true)}
          onEnd={() => setIsOrbiting(false)}
        />
        <BedPlatform />
        {modelUrl ? (
          <Suspense fallback={null}>
            <ModelViewer url={modelUrl} />
          </Suspense>
        ) : previewGlbUrl ? (
          <Suspense fallback={null}>
            <InteractiveModelViewer
              url={previewGlbUrl}
              colorRemapMap={colorRemapMap}
              colorHeightMap={colorHeightMap}
              selectedColor={viewerSelectedColor}
              baseHeight={baseHeight}
              enableRelief={enableRelief}
              onColorClick={handleColorClick}
              scaleX={scaleX}
              scaleY={scaleY}
              spacerThick={spacerThick}
              structureMode={structureMode}
              enableOutline={enableOutline}
              outlineWidth={outlineWidth}
              enableCloisonne={enableCloisonne}
              wireWidthMm={wireWidthMm}
              wireHeightMm={wireHeightMm}
              puzzleOverlayEnabled={puzzleEnabled && Boolean(puzzleOverlayUrl)}
              puzzleOverlayUrl={puzzleOverlayUrl}
              hoverEnabled={!isOrbiting}
              colorPickingEnabled={!enableFridgeMagnet}
              selectionVisualsEnabled={!enableFridgeMagnet}
              onHoverSample={handleHoverSample}
            />
          </Suspense>
        ) : null}
        {addLoop && modelBounds && (
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
        {enableFridgeMagnet && modelBounds && fridgeMagnets.length > 0 && (
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
              <div className="rounded-full border border-white/10 bg-gray-900/92 px-4 py-2">
                <p className="whitespace-nowrap text-sm font-medium tracking-wide text-white">
                  {wittyMsg}
                </p>
              </div>
            </div>
          </Html>
        )}
      </Canvas>

      {hoverInspectorOverlay}
    </div>
  );
}

export default Scene3D;
