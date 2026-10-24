/**
 * ColorPreview2D — 2D preview image with click-to-select color/region support.
 * ColorPreview2D — 2D 预览图组件，支持点击选色/选区域。
 *
 * Replaces the 3D raycasting approach with direct pixel coordinate picking
 * on the quantized preview image, providing more accurate and performant
 * color selection across all four selection modes.
 * 用直接像素坐标拾取替代 3D raycasting，在所有四种选择模式下提供更精准、更高性能的颜色选择。
 */

import { useRef, useCallback, useMemo, useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { sourceColorPick } from '../../api/converter';
import { ModelingMode } from '../../api/types';
import { buildLayerImagesSourceKey, useConverterStore } from '../../stores/converter';
import type { SelectionDocument } from '../../stores/converter';
import { useEyedropperStore } from '../../stores/eyedropperStore';
import { useI18n } from '../../i18n/context';
import CanvasPreviewSurface, { type CanvasPreviewSurfaceViewport } from '../ui/CanvasPreviewSurface';
import { cx } from '../ui/panelPrimitives';
import type { CanvasPreviewHoverSample } from '../ui/canvasPreviewUtils';
import PreviewHoverInspector from '../ui/PreviewHoverInspector';
import {
  HOVER_POPOVER_DELAY_MS,
  HOVER_RESOURCE_RELEASE_DELAY_MS,
  MAGNIFIER_SIZE_PX,
  MAGNIFIER_ZOOM,
  type HoverLayerColorSample,
  type LayerCanvasBuffer,
  type PreviewCanvasBuffer,
  areHoverSamplesEqual,
  areLayerSamplesEqual,
  clampNumber,
  computeHoverInspectorStyle,
  mapPixelToBufferCoordinate,
  rgbToHex,
  setBoundedCacheValue,
} from '../ui/previewHoverInspectorUtils';
import { resolvePreviewHoverPixel } from './actionBarHoverUtils';
import { readPixelColor } from './colorPreview2DUtils';
import { detectLocalRegionContours } from './localRegionDetect';
import { BRUSH_STROKE_OPACITY, drawBrushStrokes } from './brushDraftComposite';
import SelectionOutlineOverlay from './SelectionOutlineOverlay';

/**
 * Find the closest palette entry to a given hex color.
 * 查找与给定 hex 最接近的调色板条目。
 */
function findClosestPaletteHex(
  hex: string,
  palette: Array<{ matched_hex: string }>,
): string | null {
  const targetHex = hex.replace(/^#/, '');
  if (!/^[0-9a-fA-F]{6}$/.test(targetHex)) return null;

  if (palette.length === 0) return targetHex.toUpperCase();

  const hexLower = targetHex.toLowerCase();
  // Exact match first
  const exact = palette.find((p) => p.matched_hex.replace(/^#/, '').toLowerCase() === hexLower);
  if (exact) return exact.matched_hex;

  // Do not force a nearest-palette fallback here: after a replacement or a
  // custom recipe, the colour the user sees may legitimately not be part of
  // the original palette. Returning the clicked HEX lets "same colour"
  // selection operate on the current preview state instead of the first
  // preview's colour set.
  return targetHex.toUpperCase();
}

function getContoursForHex(
  contoursByHex: Record<string, number[][][]>,
  hex: string,
): number[][][] | null {
  const noHash = hex.replace(/^#/, '');
  const candidates = [
    noHash,
    noHash.toLowerCase(),
    noHash.toUpperCase(),
    `#${noHash}`,
    `#${noHash.toLowerCase()}`,
    `#${noHash.toUpperCase()}`,
  ];
  for (const key of candidates) {
    const contours = contoursByHex[key];
    if (contours && contours.length > 0) {
      return contours;
    }
  }
  return null;
}

function normalizeHexForCompare(hex: string | null | undefined): string | null {
  if (!hex) return null;
  const normalized = hex.replace(/^#/, '').trim().toLowerCase();
  return /^[0-9a-f]{6}$/.test(normalized) ? normalized : null;
}

function averageRgbForHex(hex: string): number | null {
  const normalized = normalizeHexForCompare(hex);
  if (!normalized) return null;
  const r = Number.parseInt(normalized.slice(0, 2), 16);
  const g = Number.parseInt(normalized.slice(2, 4), 16);
  const b = Number.parseInt(normalized.slice(4, 6), 16);
  return (r + g + b) / 3;
}

const SELECTION_BLINK_ACTIVE_MS = 2000;
const SELECTION_BLINK_REST_MS = 2000;
const SELECTION_BLINK_LIGHT_AVERAGE_THRESHOLD = 160;
const SELECTION_BLINK_MAX_ALPHA = 0.46;
const SELECTION_BLINK_MIN_DRAW_ALPHA = 0.006;

function blinkFillStyleForHex(hex: string, pulse: number): string {
  const average = averageRgbForHex(hex);
  const isLightRegion =
    average !== null && average > SELECTION_BLINK_LIGHT_AVERAGE_THRESHOLD;
  const normalizedPulse = Math.max(0, Math.min(1, pulse));
  const alpha = normalizedPulse * SELECTION_BLINK_MAX_ALPHA;
  return isLightRegion
    ? `rgba(0, 0, 0, ${alpha})`
    : `rgba(255, 255, 255, ${alpha})`;
}

// A pre-rasterized blink overlay target: the Path2D (when supported) plus the
// raw polygons as a fallback, in canvas pixel space. Built by the data effect
// and consumed by the independent pulse-clock effect.
// 预光栅化的闪烁叠加目标：Path2D（若支持）+ 原始多边形兜底，处于 canvas 像素空间。
interface BlinkRenderTarget {
  hex: string;
  path: Path2D | null;
  polygons: [number, number][][];
}

function regionColorCompatibleWithSample(
  regionHex: string,
  sampleHex: string | null,
): boolean {
  const region = normalizeHexForCompare(regionHex);
  const sample = normalizeHexForCompare(sampleHex);
  return Boolean(region && sample && region === sample);
}

function selectedColorAfterToggle(
  selectedColors: Set<string>,
  paletteHex: string,
): string | null {
  const existing = Array.from(selectedColors).find(
    (color) => color.toLowerCase() === paletteHex.toLowerCase(),
  );
  if (!existing) {
    return paletteHex;
  }
  const remaining = Array.from(selectedColors).filter(
    (color) => color.toLowerCase() !== paletteHex.toLowerCase(),
  );
  return remaining.length > 0 ? remaining[remaining.length - 1] : null;
}

function resolvePreviewWidthForContours(
  previewWidthMm: number | null | undefined,
  previewPixelWidth: number | null | undefined,
): number | null {
  if (previewWidthMm && previewWidthMm > 0) return previewWidthMm;
  if (previewPixelWidth && previewPixelWidth > 0) return previewPixelWidth;
  return null;
}

function sampleToWorldPoint(
  sample: CanvasPreviewHoverSample,
  options: {
    previewPixelWidth: number | null;
    previewPixelHeight: number | null;
    previewWidthMm: number | null;
  },
): { x: number; y: number } | null {
  const pixelWidth = options.previewPixelWidth ?? sample.naturalWidth;
  const pixelHeight = options.previewPixelHeight ?? sample.naturalHeight;
  const contourWidth = resolvePreviewWidthForContours(options.previewWidthMm, pixelWidth);
  if (!contourWidth || pixelWidth <= 0 || pixelHeight <= 0) {
    return null;
  }
  const pixelScale = contourWidth / pixelWidth;
  return {
    x: sample.pixelX * pixelScale,
    y: (pixelHeight - sample.pixelY) * pixelScale,
  };
}

function pointOnSegment(
  point: { x: number; y: number },
  a: readonly [number, number],
  b: readonly [number, number],
): boolean {
  const cross =
    (point.y - a[1]) * (b[0] - a[0]) -
    (point.x - a[0]) * (b[1] - a[1]);
  if (Math.abs(cross) > 1e-6) return false;
  const dot =
    (point.x - a[0]) * (b[0] - a[0]) +
    (point.y - a[1]) * (b[1] - a[1]);
  if (dot < 0) return false;
  const lenSq = (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2;
  return dot <= lenSq;
}

function pointInPolygon(
  point: { x: number; y: number },
  polygon: number[][],
): boolean {
  if (polygon.length < 3) return false;

  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[j] as [number, number];
    const b = polygon[i] as [number, number];
    if (pointOnSegment(point, a, b)) {
      return true;
    }
    const intersects =
      (a[1] > point.y) !== (b[1] > point.y) &&
      point.x < ((b[0] - a[0]) * (point.y - a[1])) / (b[1] - a[1]) + a[0];
    if (intersects) inside = !inside;
  }
  return inside;
}

function sampleHitsRegion(
  sample: CanvasPreviewHoverSample,
  region: {
    colorHex?: string | null;
    contours?: number[][][] | null;
  },
  options: {
    previewPixelWidth: number | null;
    previewPixelHeight: number | null;
    previewWidthMm: number | null;
    sampleHex?: string | null;
  },
): boolean {
  if (
    options.sampleHex != null &&
    region.colorHex != null &&
    !regionColorCompatibleWithSample(region.colorHex, options.sampleHex)
  ) {
    return false;
  }

  const point = sampleToWorldPoint(sample, options);
  if (point && region.contours && region.contours.length > 0) {
    if (region.contours.some((polygon) => pointInPolygon(point, polygon))) {
      return true;
    }
  }

  return false;
}

// --------------- Zoom / Pan constants ---------------
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 10;
const ZOOM_STEP = 1.15;

interface ColorPreview2DProps {
  showMagnifier?: boolean;
  showLayerDetails?: boolean;
}

export default function ColorPreview2D({
  showMagnifier = true,
  showLayerDetails = true,
}: ColorPreview2DProps) {
  const SURFACE_CACHE_LIMIT = 256;
  const LAYER_CACHE_LIMIT = 128;
  const hoverInspectorEnabled = showMagnifier || showLayerDetails;
  const { t } = useI18n();
  const previewAltText = t('converter_preview_2d_alt');
  const modelingMode = useConverterStore((s) => s.modeling_mode);

  // Use previewBaseImageUrl for a stable image that only changes on actual
  // content updates (initial preview, color replacement, undo), not on
  // region detection, color highlighting, or selection mode switching.
  const previewBaseImageUrl = useConverterStore((s) => s.previewBaseImageUrl);
  const previewImageUrl = useConverterStore((s) => s.previewImageUrl);
  const originalUploadUrl = useConverterStore((s) => s.imagePreviewUrl);
  const gradientSelection = useConverterStore((s) => s.gradientSelection);
  // Region-scoped gradient selection must route through ``previewImageUrl``
  // (the exact cyan mask the backend computed for just this connected
  // component). Falling back to the SVG contour overlay path lights up
  // every pixel of those colours across the whole canvas, which is wrong:
  // the region is a strict *spatial* subset of those colours' pixels.
  // The whole-group and region-less flows still use the stable base image +
  // contour overlay because their mask really is "all pixels of these hexes
  // on the canvas", so the contour path is correct there.
  // 区域来源时必须显示后端精确 mask 图（previewImageUrl），不能走前端全图
  // 同色轮廓叠加——否则会把属于该区域材料色的所有像素都高亮，违背"区域"
  // 只是这些颜色在图上某一连通块的语义。整组/无来源仍走稳定 base + 轮廓
  // 叠加，因为它们的语义确实是"全图这些色"。
  const isRegionScopedSelection = gradientSelection?.kind === 'region';
  const stableImageUrl = isRegionScopedSelection
    ? (previewImageUrl ?? previewBaseImageUrl)
    : (previewBaseImageUrl ?? previewImageUrl);
  const [showOriginal, setShowOriginal] = useState(false);
  const releaseOriginalView = useCallback(() => setShowOriginal(false), []);

  // Shift keyboard shortcut: hold Shift anywhere (outside text inputs) to
  // temporarily show the original uploaded image, releasing on keyup or
  // window blur. Mirrors the press-and-hold button interaction.
  // Shift 键盘快捷键：在非文本输入环境下按住 Shift 即可临时查看原图，
  // keyup 或窗口失焦时自动恢复，与长按按钮行为一致。
  useEffect(() => {
    if (!originalUploadUrl) {
      return;
    }
    const isEditableTarget = (target: EventTarget | null): boolean => {
      if (!(target instanceof HTMLElement)) return false;
      const tag = target.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
      return target.isContentEditable;
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Shift') return;
      if (event.repeat) return;
      if (isEditableTarget(event.target)) return;
      setShowOriginal(true);
    };
    const handleKeyUp = (event: KeyboardEvent) => {
      if (event.key !== 'Shift') return;
      setShowOriginal(false);
    };
    const handleBlur = () => setShowOriginal(false);
    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);
    window.addEventListener('blur', handleBlur);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
      window.removeEventListener('blur', handleBlur);
    };
  }, [originalUploadUrl]);

  // Preload mechanism: keep current displayUrl until new image is fully loaded,
  // preventing visible flash when stableImageUrl changes after replacement.
  const [displayUrl, setDisplayUrl] = useState<string | null>(stableImageUrl);
  useEffect(() => {
    if (!stableImageUrl) {
      setDisplayUrl(null);
      return;
    }
    if (stableImageUrl === displayUrl) return;
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => setDisplayUrl(stableImageUrl);
    img.onerror = () => setDisplayUrl(stableImageUrl);
    img.src = stableImageUrl;
  }, [stableImageUrl]); // eslint-disable-line react-hooks/exhaustive-deps
  const activeCanvasSrc = showOriginal && originalUploadUrl ? originalUploadUrl : displayUrl;

  const previewPixelWidth = useConverterStore((s) => s.previewPixelWidth);
  const previewPixelHeight = useConverterStore((s) => s.previewPixelHeight);
  const selectionMode = useConverterStore((s) => s.selectionMode);
  const selectionTool = useConverterStore((s) => s.selectionTool);
  const selectionDocument = useConverterStore((s) => s.selectionDocument);
  const applySelectionMutation = useConverterStore((s) => s.applySelectionMutation);
  const brushSizePx = useConverterStore((s) => s.brushSizePx);
  const colorRangeTolerance = useConverterStore((s) => s.colorRangeTolerance);
  const eyedropperActive = useEyedropperStore((s) => s.active);
  const completeEyedropper = useEyedropperStore((s) => s.complete);
  // The eyedropper takes over clicks even while the brush tool is selected.
  const brushStrokesEnabled = selectionTool === 'brush' && !eyedropperActive;
  const selectedColor = useConverterStore((s) => s.selectedColor);
  const selectedColors = useConverterStore((s) => s.selectedColors);
  const isLoading = useConverterStore((s) => s.isLoading);
  const replacePreviewLoading = useConverterStore((s) => s.replacePreviewLoading);
  const colorContours = useConverterStore((s) => s.colorContours);
  const regionData = useConverterStore((s) => s.regionData);
  const selectedRegions = useConverterStore((s) => s.selectedRegions);
  const selectionBlinkEnabled = useConverterStore((s) => s.selectionBlinkEnabled);
  const sessionId = useConverterStore((s) => s.sessionId);
  const previewGlbUrl = useConverterStore((s) => s.previewGlbUrl);
  const previewWidthMm = useConverterStore((s) => s.preview_width_mm);
  const bedLabel = useConverterStore((s) => s.bed_label);
  const bedSizes = useConverterStore((s) => s.bedSizes);
  const fetchLayerImages = useConverterStore((s) => s.fetchLayerImages);
  const layerImagesLoading = useConverterStore((s) => s.layerImagesLoading);
  const layerImages = useConverterStore((s) => s.layerImages);
  const layerImagesSourceKey = useConverterStore((s) => s.layerImagesSourceKey);

  const detectRegion = useConverterStore((s) => s.detectRegion);
  const detectAndAccumulateRegion = useConverterStore((s) => s.detectAndAccumulateRegion);
  const removeRegionFromSelection = useConverterStore((s) => s.removeRegionFromSelection);
  const clearSelection = useConverterStore((s) => s.clearSelection);

  const [hoverSample, setHoverSample] = useState<CanvasPreviewHoverSample | null>(null);
  const [brushHoverSample, setBrushHoverSample] = useState<CanvasPreviewHoverSample | null>(null);
  const [hoverLayerColors, setHoverLayerColors] = useState<HoverLayerColorSample[]>([]);
  const [hoverSurfaceHex, setHoverSurfaceHex] = useState<string | null>(null);
  const [previewCanvasBuffer, setPreviewCanvasBuffer] = useState<PreviewCanvasBuffer | null>(null);
  const previewCanvasBufferRef = useRef<PreviewCanvasBuffer | null>(null);
  const previewCanvasBufferSourceRef = useRef<string | null>(null);
  const [layerCanvasBuffers, setLayerCanvasBuffers] = useState<LayerCanvasBuffer[]>([]);
  const pendingHoverSampleRef = useRef<CanvasPreviewHoverSample | null>(null);
  const hoverDelayTimerRef = useRef<number | null>(null);
  const hoverResourceReleaseTimerRef = useRef<number | null>(null);
  const magnifierCanvasRef = useRef<HTMLCanvasElement>(null);
  const selectionBlinkCanvasRef = useRef<HTMLCanvasElement>(null);
  const brushDraftCanvasRef = useRef<HTMLCanvasElement>(null);
  // 多笔累积：每一笔是一条点列。brushStrokesRef 存已抬笔的历史笔，
  // brushPointsRef 存正在画的当前笔；应用时把两者一起提交。
  // Strokes accumulate: past strokes live in brushStrokesRef, the in-progress
  // stroke in brushPointsRef; both are submitted together on apply.
  const brushStrokesRef = useRef<Array<Array<{ x: number; y: number }>>>([]);
  const brushPointsRef = useRef<Array<{ x: number; y: number }>>([]);
  // Display→image scale captured at stroke time, so executeBrushDraft can
  // convert the display-pixel brush size into image pixels consistently with
  // how the draft stroke is drawn (appendBrushSample). 落笔时记录的显示→图像比例。
  const brushDisplayToImageScaleRef = useRef(1);
  const [brushDraftVersion, setBrushDraftVersion] = useState(0);
  const fetchedLayerSessionRef = useRef<string | null>(null);
  const layerSampleCacheRef = useRef<Map<string, HoverLayerColorSample[]>>(new Map());
  const surfaceSampleCacheRef = useRef<Map<string, string | null>>(new Map());
  const selectAllPickSeqRef = useRef(0);
  // 闪烁目标与时间轴解耦：renderTargets 由数据 effect 写入，脉冲循环 effect 读取。
  // version 用于让脉冲循环仅在轮廓数据变化时重描，避免每帧重画 Path2D。
  // Blink targets are decoupled from the pulse clock so selection changes never
  // restart the animation — only the contour data is swapped.
  const blinkTargetsRef = useRef<readonly BlinkRenderTarget[]>([]);
  const blinkTargetsVersionRef = useRef(0);
  // 乐观轮廓：点击瞬间用本地 colorContours 立即高亮，待 region-detect 返回
  // 精确连通块轮廓后由 svgContours 的 regionData 分支接管。仅作即时视觉反馈，
  // 不写入 store，不干扰选中/替换逻辑。
  // Optimistic contours give instant feedback on click using the locally-known
  // full-colour outline while the precise connected-component contour is fetched.
  const [optimisticContours, setOptimisticContours] = useState<{
    hex: string;
    polygons: number[][][];
    clickX: number;
    clickY: number;
  } | null>(null);
  // 多选乐观累加：multi-select 下每次点击本地 flood-fill 立即追加一个精确连通块
  // 轮廓，与 selectedRegions 一起渲染；后端返回该块后按点击坐标移除。这样多选
  // 点第一个和连续点多个都即时显示，不用等每次 region-detect 的网络往返。
  // Optimistic accumulation for multi-select: each click flood-fills locally and
  // appends an exact outline immediately, rendered alongside selectedRegions; the
  // entry is removed (matched by click coords) once the backend region arrives.
  const [optimisticRegions, setOptimisticRegions] = useState<Array<{
    hex: string;
    polygons: number[][][];
    clickX: number;
    clickY: number;
  }>>([]);
  const needsLayerHoverData = hoverInspectorEnabled && showLayerDetails && hoverSample !== null;
  const displayPreviewSettled = displayUrl === stableImageUrl;
  const layerImagesCurrentKey = useMemo(
    () => buildLayerImagesSourceKey({
      sessionId,
      previewGlbUrl,
      previewBaseImageUrl,
      previewImageUrl,
    }),
    [previewBaseImageUrl, previewGlbUrl, previewImageUrl, sessionId],
  );
  const activeLayerImages = useMemo(
    () => {
      if (!displayPreviewSettled) {
        return layerImages;
      }
      return layerImagesSourceKey === layerImagesCurrentKey ? layerImages : [];
    },
    [displayPreviewSettled, layerImages, layerImagesCurrentKey, layerImagesSourceKey],
  );

  const [zoom, setZoom] = useState(1);
  const handleSurfaceReady = useCallback((payload: { previewBuffer: PreviewCanvasBuffer | null } | null) => {
    const nextPreviewBuffer = payload?.previewBuffer ?? null;
    previewCanvasBufferRef.current = nextPreviewBuffer;
    previewCanvasBufferSourceRef.current = nextPreviewBuffer ? activeCanvasSrc : null;
    setPreviewCanvasBuffer(nextPreviewBuffer);
    surfaceSampleCacheRef.current.clear();
  }, [activeCanvasSrc]);

  const readActivePreviewPixel = useCallback((sample: CanvasPreviewHoverSample): string | null => {
    const activeBuffer =
      activeCanvasSrc === displayUrl &&
      previewCanvasBufferSourceRef.current === displayUrl
        ? previewCanvasBufferRef.current
        : null;
    return readPixelColor(activeBuffer, {
      pixelX: sample.pixelX,
      pixelY: sample.pixelY,
      naturalWidth: sample.naturalWidth,
      naturalHeight: sample.naturalHeight,
    });
  }, [activeCanvasSrc, displayUrl]);

  const clearHoverResourceReleaseTimer = useCallback(() => {
    if (hoverResourceReleaseTimerRef.current !== null) {
      window.clearTimeout(hoverResourceReleaseTimerRef.current);
      hoverResourceReleaseTimerRef.current = null;
    }
  }, []);

  const scheduleHoverResourceRelease = useCallback(() => {
    clearHoverResourceReleaseTimer();
    hoverResourceReleaseTimerRef.current = window.setTimeout(() => {
      hoverResourceReleaseTimerRef.current = null;
      setLayerCanvasBuffers((previous) => (previous.length === 0 ? previous : []));
      layerSampleCacheRef.current.clear();
      surfaceSampleCacheRef.current.clear();
    }, HOVER_RESOURCE_RELEASE_DELAY_MS);
  }, [clearHoverResourceReleaseTimer]);

  const handleHoverSample = useCallback((sample: CanvasPreviewHoverSample | null) => {
    if (selectionTool === 'brush') {
      // In brush mode, show the brush cursor immediately without the hover
      // inspector delay, so the user can see where they're painting.
      // 越界采样照常存入 brushHoverSample（携带 isOutOfImage 标记与未夹取
      // 像素坐标）——它不流经悬停检查器等共享逻辑，只被光标圈消费：渲染时
      // 用图像 fit 矩形把位置夹回边缘，保证指示圈永不可见丢失。
      setBrushHoverSample((previous) => {
        if (sample === null && previous === null) return previous;
        if (sample && previous &&
            sample.containerX === previous.containerX &&
            sample.containerY === previous.containerY) {
          return previous;
        }
        return sample;
      });
      return;
    }
    setBrushHoverSample(null);

    if (!hoverInspectorEnabled) {
      pendingHoverSampleRef.current = null;
      if (hoverDelayTimerRef.current !== null) {
        window.clearTimeout(hoverDelayTimerRef.current);
        hoverDelayTimerRef.current = null;
      }
      clearHoverResourceReleaseTimer();
      setHoverSample((previous) => (previous === null ? previous : null));
      setHoverLayerColors((previous) => (previous.length === 0 ? previous : []));
      setHoverSurfaceHex((previous) => (previous === null ? previous : null));
      setLayerCanvasBuffers((previous) => (previous.length === 0 ? previous : []));
      layerSampleCacheRef.current.clear();
      surfaceSampleCacheRef.current.clear();
      return;
    }

    pendingHoverSampleRef.current = sample;

    if (hoverDelayTimerRef.current !== null) {
      window.clearTimeout(hoverDelayTimerRef.current);
      hoverDelayTimerRef.current = null;
    }
    clearHoverResourceReleaseTimer();

    if (sample === null) {
      setHoverSample((previous) => (previous === null ? previous : null));
      scheduleHoverResourceRelease();
      return;
    }

    setHoverSample((previous) => (previous === null ? previous : null));
    hoverDelayTimerRef.current = window.setTimeout(() => {
      hoverDelayTimerRef.current = null;
      const pending = pendingHoverSampleRef.current;
      if (!pending) {
        return;
      }
      setHoverSample((previous) => (areHoverSamplesEqual(previous, pending) ? previous : pending));
    }, HOVER_POPOVER_DELAY_MS);
  }, [clearHoverResourceReleaseTimer, hoverInspectorEnabled, scheduleHoverResourceRelease, selectionTool]);

  const handleCanvasHoverSample = useCallback((sample: CanvasPreviewHoverSample | null) => {
    handleHoverSample(sample);
  }, [handleHoverSample]);

  useEffect(() => {
    if (!hoverInspectorEnabled) {
      handleHoverSample(null);
    }
  }, [handleHoverSample, hoverInspectorEnabled]);

  useEffect(() => {
    clearHoverResourceReleaseTimer();
    setLayerCanvasBuffers([]);
    layerSampleCacheRef.current.clear();
    surfaceSampleCacheRef.current.clear();
    setHoverSample(null);
    setHoverLayerColors([]);
    setHoverSurfaceHex(null);
  }, [clearHoverResourceReleaseTimer, displayUrl]);

  useEffect(() => {
    return () => {
      if (hoverDelayTimerRef.current !== null) {
        window.clearTimeout(hoverDelayTimerRef.current);
        hoverDelayTimerRef.current = null;
      }
      clearHoverResourceReleaseTimer();
    };
  }, [clearHoverResourceReleaseTimer]);

  // Reset zoom when the image source changes
  useEffect(() => {
    setZoom(1);
  }, [stableImageUrl]);

  useEffect(() => {
    if (!sessionId) {
      fetchedLayerSessionRef.current = null;
      return;
    }

    if (
      !needsLayerHoverData
      || !displayUrl
      || !displayPreviewSettled
      || !layerImagesCurrentKey
      || layerImagesLoading
      || activeLayerImages.length > 0
    ) {
      return;
    }

    if (fetchedLayerSessionRef.current === layerImagesCurrentKey) {
      return;
    }

    fetchedLayerSessionRef.current = layerImagesCurrentKey;
    void fetchLayerImages(layerImagesCurrentKey);
  }, [
    activeLayerImages.length,
    displayPreviewSettled,
    displayUrl,
    fetchLayerImages,
    layerImagesCurrentKey,
    layerImagesLoading,
    needsLayerHoverData,
    sessionId,
  ]);

  useEffect(() => {
    let cancelled = false;

    if (!needsLayerHoverData) {
      return () => {
        cancelled = true;
      };
    }

    if (activeLayerImages.length === 0) {
      setLayerCanvasBuffers([]);
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
              image.crossOrigin = 'anonymous';
              image.onload = () => {
                const width = image.naturalWidth || image.width;
                const height = image.naturalHeight || image.height;
                if (width <= 0 || height <= 0) {
                  resolve(null);
                  return;
                }
                const canvas = document.createElement('canvas');
                canvas.width = width;
                canvas.height = height;
                const context = canvas.getContext('2d', { willReadFrequently: true });
                if (!context) {
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

      if (cancelled) return;
      setLayerCanvasBuffers(loaded.filter((entry): entry is LayerCanvasBuffer => entry !== null));
      layerSampleCacheRef.current.clear();
    };

    void buildBuffers();

    return () => {
      cancelled = true;
    };
  }, [activeLayerImages, needsLayerHoverData]);

  useEffect(() => {
    if (!hoverInspectorEnabled || !hoverSample) {
      setHoverLayerColors((previous) => (previous.length === 0 ? previous : []));
      setHoverSurfaceHex((previous) => (previous === null ? previous : null));
      return;
    }

    const surfaceCacheKey = `${hoverSample.pixelX},${hoverSample.pixelY}`;
    const resolvedLayerPixel = resolvePreviewHoverPixel(hoverSample, {
      rawWidth: previewPixelWidth,
      rawHeight: previewPixelHeight,
      previewWidthMm,
      bedLabel,
      bedSizes,
    });
    const layerBaseWidth = previewPixelWidth && previewPixelWidth > 0 ? previewPixelWidth : hoverSample.naturalWidth;
    const layerBaseHeight = previewPixelHeight && previewPixelHeight > 0 ? previewPixelHeight : hoverSample.naturalHeight;

    if (!previewCanvasBuffer) {
      setHoverSurfaceHex((previous) => (previous === null ? previous : null));
    } else {
      const cachedSurface = surfaceSampleCacheRef.current.get(surfaceCacheKey);
      if (cachedSurface !== undefined) {
        setHoverSurfaceHex((previous) => (previous === cachedSurface ? previous : cachedSurface));
      } else {
        let sampledSurface: string | null = null;
        const x = mapPixelToBufferCoordinate(hoverSample.pixelX, hoverSample.naturalWidth, previewCanvasBuffer.width);
        const y = mapPixelToBufferCoordinate(hoverSample.pixelY, hoverSample.naturalHeight, previewCanvasBuffer.height);
        try {
          const rgba = previewCanvasBuffer.context.getImageData(x, y, 1, 1).data;
          sampledSurface = rgba[3] <= 8 ? null : rgbToHex(rgba[0], rgba[1], rgba[2]);
        } catch {
          sampledSurface = null;
        }
        setBoundedCacheValue(surfaceSampleCacheRef.current, surfaceCacheKey, sampledSurface, SURFACE_CACHE_LIMIT);
        setHoverSurfaceHex((previous) => (previous === sampledSurface ? previous : sampledSurface));
      }
    }

    if (!showLayerDetails || !resolvedLayerPixel || layerCanvasBuffers.length === 0) {
      setHoverLayerColors((previous) => (previous.length === 0 ? previous : []));
      return;
    }

    const layerCacheKey = `${resolvedLayerPixel.pixelX},${resolvedLayerPixel.pixelY}`;
    const cachedLayers = layerSampleCacheRef.current.get(layerCacheKey);
    if (cachedLayers) {
      setHoverLayerColors((previous) => (areLayerSamplesEqual(previous, cachedLayers) ? previous : cachedLayers));
      return;
    }

    const sampledLayers = layerCanvasBuffers.map((layer, index) => {
      const x = mapPixelToBufferCoordinate(resolvedLayerPixel.pixelX, layerBaseWidth, layer.width);
      const y = mapPixelToBufferCoordinate(resolvedLayerPixel.pixelY, layerBaseHeight, layer.height);

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

    setBoundedCacheValue(layerSampleCacheRef.current, layerCacheKey, sampledLayers, LAYER_CACHE_LIMIT);
    setHoverLayerColors((previous) => (areLayerSamplesEqual(previous, sampledLayers) ? previous : sampledLayers));
  }, [
    hoverSample,
    previewPixelWidth,
    previewPixelHeight,
    previewWidthMm,
    bedLabel,
    bedSizes,
    previewCanvasBuffer,
    layerCanvasBuffers,
    hoverInspectorEnabled,
    showLayerDetails,
    SURFACE_CACHE_LIMIT,
    LAYER_CACHE_LIMIT,
  ]);

  useEffect(() => {
    const magnifierCanvas = magnifierCanvasRef.current;
    const context = magnifierCanvas?.getContext('2d');
    if (!magnifierCanvas || !context) {
      return;
    }

    context.clearRect(0, 0, magnifierCanvas.width, magnifierCanvas.height);
    if (!showMagnifier || !hoverSample || !previewCanvasBuffer) {
      return;
    }

    const centerX = mapPixelToBufferCoordinate(hoverSample.pixelX, hoverSample.naturalWidth, previewCanvasBuffer.width);
    const centerY = mapPixelToBufferCoordinate(hoverSample.pixelY, hoverSample.naturalHeight, previewCanvasBuffer.height);
    const sourceSize = MAGNIFIER_SIZE_PX / MAGNIFIER_ZOOM;
    const maxSourceX = Math.max(0, previewCanvasBuffer.width - sourceSize);
    const maxSourceY = Math.max(0, previewCanvasBuffer.height - sourceSize);
    const sourceX = clampNumber(centerX - sourceSize / 2, 0, maxSourceX);
    const sourceY = clampNumber(centerY - sourceSize / 2, 0, maxSourceY);

    context.imageSmoothingEnabled = false;
    context.drawImage(
      previewCanvasBuffer.context.canvas,
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
    context.strokeStyle = 'rgba(255, 255, 255, 0.9)';
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(center, 0);
    context.lineTo(center, magnifierCanvas.height);
    context.moveTo(0, center);
    context.lineTo(magnifierCanvas.width, center);
    context.stroke();
  }, [hoverSample, previewCanvasBuffer, showMagnifier]);

  const handleSelectAllClick = useCallback(
    async (sample: CanvasPreviewHoverSample) => {
      const requestSeq = selectAllPickSeqRef.current + 1;
      selectAllPickSeqRef.current = requestSeq;
      const sessionIdAtClick = sessionId;
      const applyRawHexIfCurrent = (rawHex: string | null): string | null => {
        if (!rawHex) return null;
        const state = useConverterStore.getState();
        if (
          state.selectionMode !== 'select-all'
          || state.sessionId !== sessionIdAtClick
          || state.replacePreviewLoading
        ) {
          return null;
        }
        const paletteHex = findClosestPaletteHex(rawHex, state.palette);
        if (!paletteHex) return null;
        state.toggleColorInSelection(paletteHex);
        state.setSelectedColor(selectedColorAfterToggle(state.selectedColors, paletteHex));
        return paletteHex;
      };

      const localRawHex = readActivePreviewPixel(sample);
      const optimisticPaletteHex = applyRawHexIfCurrent(localRawHex);

      if (sessionIdAtClick) {
        try {
          const pick = await sourceColorPick(sessionIdAtClick, sample.pixelX, sample.pixelY);
          if (selectAllPickSeqRef.current !== requestSeq) {
            return;
          }
          const serverPaletteHex = findClosestPaletteHex(
            pick.source_matched_hex,
            useConverterStore.getState().palette,
          );
          if (
            optimisticPaletteHex &&
            serverPaletteHex &&
            optimisticPaletteHex.toLowerCase() === serverPaletteHex.toLowerCase()
          ) {
            return;
          }
          if (optimisticPaletteHex) {
            // Correct an optimistic click sampled from a highlighted/blended
            // preview image. Toggle the optimistic colour off, then apply the
            // authoritative backend colour for this pixel.
            applyRawHexIfCurrent(optimisticPaletteHex);
          }
          applyRawHexIfCurrent(pick.source_matched_hex);
          return;
        } catch {
          // Fall back to the preview buffer for legacy sessions or transient API failures.
        }
      }
    },
    [readActivePreviewPixel, sessionId],
  );

  const handleClick = useCallback(
    (sample: CanvasPreviewHoverSample) => {
      if (replacePreviewLoading) return;

      const { pixelX, pixelY } = sample;

      // Eyedropper: read this point's colour for the quick-recolor card and
      // leave the selection untouched. Transparent background reads as null.
      // 吸管取色：只读取该点颜色交给快速换色卡片，不改变选区；透明背景忽略。
      if (eyedropperActive) {
        const pickedHex = readActivePreviewPixel(sample);
        if (pickedHex) completeEyedropper(pickedHex);
        return;
      }

      // Colour-range picks toggle every visible block within the ΔE00
      // tolerance. The server resolves the clicked colour, so no local
      // flood-fill placeholder is drawn (see DESIGN.md "No approximate flash").
      // 颜色范围选择：切换与点击色 ΔE00 不超过容差的全部可见色块；由服务端
      // 解析点击色，不绘制近似的本地占位轮廓。
      if (selectionTool === 'color-range') {
        void applySelectionMutation({
          operation: 'color-range-toggle',
          x: pixelX,
          y: pixelY,
          colorTolerance: colorRangeTolerance,
        });
        return;
      }

      if (
        selectionDocument &&
        selectionMode !== 'current' &&
        selectionMode !== 'region' &&
        (selectionTool === 'point' || selectionTool === 'same-color')
      ) {
        const buffer =
          activeCanvasSrc === displayUrl &&
          previewCanvasBufferSourceRef.current === displayUrl
            ? previewCanvasBufferRef.current
            : null;
        const widthMm =
          previewWidthMm && previewWidthMm > 0
            ? previewWidthMm
            : previewPixelWidth;
        const local =
          buffer && widthMm
            ? detectLocalRegionContours(buffer, {
                pixelX,
                pixelY,
                naturalWidth: sample.naturalWidth,
                naturalHeight: sample.naturalHeight,
                previewWidthMm: widthMm,
              })
            : null;
        if (!local) return;

        if (selectionTool === 'point') {
          const existing = selectionDocument.components.find(
            (component) =>
              component.color_hex.replace(/^#/, '').toLowerCase() === local.colorHex &&
              component.pixel_count === local.pixelCount &&
              component.bbox.join(',') === local.bbox.join(','),
          );

          // Toggle OFF: remove the clicked component from the display immediately.
          // We match by component identity (color + pixel count + bbox), not by
          // contour coordinates, because the backend may return simplified contours
          // that don't exactly match the locally-detected polygons.
          // 取消选择时按组件身份（颜色+像素数+bbox）匹配移除，不按轮廓坐标匹配，
          // 因为后端返回的简化轮廓和本地检测的 polygon 可能不完全一致。
          const existingIndex = existing
            ? selectionDocument.components.indexOf(existing)
            : -1;
          const optimisticContours = existing
            ? selectionDocument.contours.filter((_contour, index) => index !== existingIndex)
            : [...selectionDocument.contours, ...local.polygons];
          const optimisticComponents = existing
            ? selectionDocument.components.filter((_component, index) => index !== existingIndex)
            : [
                ...selectionDocument.components,
                {
                  label: -Math.max(1, selectionDocument.selection_revision + 1),
                  region_id: `__optimistic_selection__:${selectionDocument.selection_revision + 1}:${pixelX}:${pixelY}`,
                  color_hex: `#${local.colorHex}`,
                  pixel_count: local.pixelCount,
                  bbox: [...local.bbox],
                  anchor: [...local.anchor],
                  contours: local.polygons,
                },
              ];
          const optimisticColorHexes = Array.from(
            new Set(optimisticComponents.map((component) => component.color_hex)),
          );

          const optimisticDocument: SelectionDocument = {
            ...selectionDocument,
            selection_revision: selectionDocument.selection_revision + 1,
            selected_component_count: optimisticComponents.length,
            selected_pixel_count: Math.max(
              0,
              selectionDocument.selected_pixel_count +
              (existing ? -existing.pixel_count : local.pixelCount),
            ),
            selected_color_hexes: optimisticColorHexes,
            region_ids: optimisticComponents.map((component) => component.region_id),
            components: optimisticComponents,
            contours: optimisticContours,
          };

          // Apply the optimistic state IMMEDIATELY so the user sees the new
          // selection right away, then let the backend confirm it in the
          // background. Previously we waited for the backend response before
          // updating the UI, which caused the "new block disappears after a
          // few seconds" bug when the backend was slow or failed.
          // 立即应用乐观状态让用户看到新选区，后端在后台确认。之前等后端
          // 响应才更新 UI，导致新色块几秒后消失。
          useConverterStore.setState({
            selectionDocument: optimisticDocument,
          });

          void applySelectionMutation({
            operation: 'point-toggle',
            x: pixelX,
            y: pixelY,
            optimisticDocument,
          });
        } else {
          void applySelectionMutation({
            operation: 'same-color-toggle',
            x: pixelX,
            y: pixelY,
            colorHex: local.colorHex,
          });
        }
        return;
      }

      switch (selectionMode) {
        case 'select-all': {
          void handleSelectAllClick(sample);
          break;
        }
        case 'current':
        case 'region': {
          const rawHex = readActivePreviewPixel(sample);
          if (
            regionData &&
            sampleHitsRegion(sample, regionData, {
              previewPixelWidth,
              previewPixelHeight,
              previewWidthMm,
              sampleHex: rawHex,
            })
          ) {
            clearSelection();
            break;
          }
          const paletteHex = rawHex
            ? findClosestPaletteHex(rawHex, useConverterStore.getState().palette)
            : null;
          if (paletteHex) {
            useConverterStore.getState().setSelectedColor(paletteHex);
            // 乐观高亮：本地 flood-fill 立即算出**精确**的点击连通块轮廓，
            // 而不是“全图同色”的近似（那会把区域外同色像素也框进来）。
            // 后端 region-detect 返回后通常与本地结果一致，无视觉跳变。
            // Optimistic highlight: a local flood-fill yields the *exact*
            // connected component instantly — not the "all same-coloured pixels"
            // approximation that would outline同色 pixels outside the region.
            const buffer =
              activeCanvasSrc === displayUrl &&
              previewCanvasBufferSourceRef.current === displayUrl
                ? previewCanvasBufferRef.current
                : null;
            const widthMm =
              previewWidthMm && previewWidthMm > 0
                ? previewWidthMm
                : previewPixelWidth;
            const local =
              buffer && widthMm
                ? detectLocalRegionContours(buffer, {
                    pixelX,
                    pixelY,
                    naturalWidth: sample.naturalWidth,
                    naturalHeight: sample.naturalHeight,
                    previewWidthMm: widthMm,
                  })
                : null;
            setOptimisticContours(
              local && local.polygons.length > 0
                ? {
                    hex: paletteHex,
                    polygons: local.polygons,
                    clickX: pixelX,
                    clickY: pixelY,
                  }
                : null,
            );
          } else {
            setOptimisticContours(null);
          }
          detectRegion(pixelX, pixelY);
          break;
        }
        case 'multi-select': {
          const rawHex = readActivePreviewPixel(sample);
          const clickedRegion = selectedRegions.find((region) =>
            regionColorCompatibleWithSample(region.colorHex, rawHex) &&
            sampleHitsRegion(sample, region, {
              previewPixelWidth,
              previewPixelHeight,
              previewWidthMm,
              sampleHex: rawHex,
            }),
          );
          if (clickedRegion) {
            removeRegionFromSelection(clickedRegion.regionId);
            break;
          }
          // Toggle-off an optimistic region whose backend region hasn't arrived
          // yet: hitting its outline removes it from the optimistic list.
          // 取消一个后端尚未返回的乐观区域：命中其轮廓则从乐观列表移除。
          const clickedOptimistic = optimisticRegions.find((region) =>
            sampleHitsRegion(
              sample,
              { colorHex: region.hex, contours: region.polygons },
              {
                previewPixelWidth,
                previewPixelHeight,
                previewWidthMm,
                sampleHex: rawHex,
              },
            ),
          );
          if (clickedOptimistic) {
            setOptimisticRegions((previous) =>
              previous.filter(
                (entry) =>
                  entry.clickX !== clickedOptimistic.clickX ||
                  entry.clickY !== clickedOptimistic.clickY,
              ),
            );
            break;
          }
          const paletteHex = rawHex
            ? findClosestPaletteHex(rawHex, useConverterStore.getState().palette)
            : null;
          if (paletteHex) {
            useConverterStore.getState().setSelectedColor(paletteHex);
          }
          // 多选乐观累加：本地 flood-fill 立即算出精确连通块轮廓并追加显示，
          // 后端 region-detect 返回该块后按点击坐标移除（见下方清除 effect）。
          // Optimistic accumulate: flood-fill locally for an instant exact outline.
          {
            const buffer =
              activeCanvasSrc === displayUrl &&
              previewCanvasBufferSourceRef.current === displayUrl
                ? previewCanvasBufferRef.current
                : null;
            const widthMm =
              previewWidthMm && previewWidthMm > 0
                ? previewWidthMm
                : previewPixelWidth;
            const local =
              buffer && widthMm
                ? detectLocalRegionContours(buffer, {
                    pixelX,
                    pixelY,
                    naturalWidth: sample.naturalWidth,
                    naturalHeight: sample.naturalHeight,
                    previewWidthMm: widthMm,
                  })
                : null;
            if (local && local.polygons.length > 0 && paletteHex) {
              setOptimisticRegions((previous) => [
                // Drop any stale optimistic entry for the same click point.
                ...previous.filter(
                  (entry) => entry.clickX !== pixelX || entry.clickY !== pixelY,
                ),
                {
                  hex: paletteHex,
                  polygons: local.polygons,
                  clickX: pixelX,
                  clickY: pixelY,
                },
              ]);
            }
          }
          detectAndAccumulateRegion(pixelX, pixelY);
          break;
        }
      }
    },
    [
      replacePreviewLoading,
      previewPixelWidth,
      previewPixelHeight,
      previewWidthMm,
      selectionMode,
      selectionTool,
      selectionDocument,
      applySelectionMutation,
      colorRangeTolerance,
      eyedropperActive,
      completeEyedropper,
      handleSelectAllClick,
      readActivePreviewPixel,
      regionData,
      selectedRegions,
      activeCanvasSrc,
      displayUrl,
      detectRegion,
      detectAndAccumulateRegion,
      removeRegionFromSelection,
      clearSelection,
      optimisticRegions,
    ],
  );

  // Clear the optimistic outline once the precise contour for THIS click
  // arrives (matched by click coordinates), or when the selection is cleared /
  // mode changes. A stale ``regionData`` from a previous selection must NOT
  // clear it — that's exactly what let the old outline mask the optimistic one.
  // 仅当本次点击的精确轮廓返回时（按点击坐标匹配）才清除乐观轮廓；选区清空或
  // 切换模式时也清除。上一个选区残留的旧 regionData 绝不能清除它——正是那个
  // 误清除让旧轮廓盖住了乐观轮廓。
  useEffect(() => {
    if (!optimisticContours) return;
    const arrived =
      regionData?.contours &&
      regionData.contours.length > 0 &&
      regionData.clickX === optimisticContours.clickX &&
      regionData.clickY === optimisticContours.clickY;
    if (arrived) {
      setOptimisticContours(null);
      return;
    }
    if (!selectedColor && selectionMode !== 'multi-select') {
      setOptimisticContours(null);
    }
  }, [regionData, selectedColor, selectionMode, optimisticContours]);

  // Reconcile optimistic multi-select regions: drop each optimistic entry once
  // the backend ``selectedRegions`` contains a region at the same click point,
  // and clear them all when leaving multi-select or when the selection is
  // emptied (e.g. clear-all / undo). 多选乐观项对账：后端 selectedRegions 出现
  // 同点击坐标的区域后移除对应乐观项；切出多选或选区被清空时全部清空。
  useEffect(() => {
    if (selectionMode !== 'multi-select') {
      if (optimisticRegions.length > 0) setOptimisticRegions([]);
      return;
    }
    if (optimisticRegions.length === 0) return;
    const remaining = optimisticRegions.filter(
      (optimistic) =>
        !selectedRegions.some(
          (region) =>
            region.clickX === optimistic.clickX &&
            region.clickY === optimistic.clickY,
        ),
    );
    if (remaining.length !== optimisticRegions.length) {
      setOptimisticRegions(remaining);
    }
  }, [selectionMode, selectedRegions, optimisticRegions]);

  // Collect the single authoritative union contour. Legacy branches remain as
  // a compatibility fallback while gradient-panel callers migrate.
  const svgContours = useMemo(() => {
    if (!previewPixelWidth || !previewPixelHeight) return [];
    if (selectionDocument && selectionDocument.contours.length > 0) {
      return [
        {
          hex: selectionDocument.selected_color_hexes.at(-1)?.replace(/^#/, '') ?? 'ffffff',
          polygons: selectionDocument.contours,
        },
      ];
    }
    const targets: Array<{ hex: string; polygons: number[][][] }> = [];

    if (
      (selectionMode === 'current' || selectionMode === 'region') &&
      optimisticContours
    ) {
      // Optimistic outline takes top priority right after a click: it renders
      // immediately from the locally-known colour while region-detect is still
      // in flight. Without this priority, a stale ``regionData`` from the
      // previous selection would win and the outline would only appear after
      // the network round-trip — the residual delay the user noticed.
      // 点击后乐观轮廓优先：region-detect 未返回时先用本地已知颜色轮廓立即显示。
      // 否则上一个选区残留的旧 regionData 会占先，描边要等网络往返——正是用户
      // 感知到的残余延迟。
      targets.push({ hex: optimisticContours.hex, polygons: optimisticContours.polygons });
    } else if (
      (selectionMode === 'current' || selectionMode === 'region') &&
      selectedColor &&
      regionData?.contours &&
      regionData.contours.length > 0
    ) {
      targets.push({ hex: selectedColor, polygons: regionData.contours });
    } else if (selectionMode === 'multi-select') {
      for (const region of selectedRegions) {
        if (region.contours && region.contours.length > 0) {
          const hex = region.colorHex.replace(/^#/, '');
          targets.push({ hex, polygons: region.contours });
        }
      }
      // Optimistic accumulated regions render immediately alongside the
      // authoritative ones; they're removed once the backend region lands.
      // 乐观累加的区域与权威区域一起即时渲染；后端区域返回后即移除。
      for (const region of optimisticRegions) {
        targets.push({ hex: region.hex, polygons: region.polygons });
      }
    } else if (
      selectionMode === 'select-all' &&
      selectedColors.size > 0 &&
      !isRegionScopedSelection
    ) {
      // Skip when the selection is region-scoped: ``colorContours`` lists
      // every pixel of each hex across the whole canvas, which would paint
      // cyan outlines far beyond the region's connected component. The
      // region flow renders exact connected-component contours from
      // ``regionData`` / ``selectedRegions`` above, so no full-colour overlay
      // is needed here.
      // 区域来源跳过 contour 叠加——colorContours 是全图同色轮廓，叠上去
      // 会把区域外的同色像素也框住；区域流程已经通过 regionData /
      // selectedRegions 的轮廓显示精确区域，无需再叠全图同色轮廓。
      for (const hex of selectedColors) {
        const contours = getContoursForHex(colorContours, hex);
        if (contours) {
          targets.push({ hex, polygons: contours });
        }
      }
    } else if (
      selectionMode === 'select-all' &&
      selectedColor &&
      !isRegionScopedSelection
    ) {
      const contours = getContoursForHex(colorContours, selectedColor);
      if (contours) {
        targets.push({ hex: selectedColor, polygons: contours });
      }
    }

    return targets;
  }, [
    selectionMode,
    selectionDocument,
    selectedColor,
    selectedColors,
    selectedRegions,
    regionData,
    colorContours,
    optimisticContours,
    optimisticRegions,
    previewPixelWidth,
    previewPixelHeight,
    isRegionScopedSelection,
  ]);

  // --- 数据 effect：把 svgContours 转成可绘制的 renderTargets 存入 ref。 ---
  // 随选区/尺寸变化重跑，只更新数据 + 递增版本号，绝不动 rAF 循环和 opacity，
  // 因此选区变化不会打断闪烁相位。
  useEffect(() => {
    const contourWidth = resolvePreviewWidthForContours(previewWidthMm, previewPixelWidth);
    if (
      !selectionBlinkEnabled ||
      svgContours.length === 0 ||
      !previewPixelWidth ||
      !previewPixelHeight ||
      !contourWidth ||
      contourWidth <= 0
    ) {
      blinkTargetsRef.current = [];
      blinkTargetsVersionRef.current += 1;
      return;
    }

    const pixelScale = contourWidth / previewPixelWidth;
    const supportsPath2D = typeof Path2D !== 'undefined';
    const renderTargets: BlinkRenderTarget[] = svgContours.map((target) => {
      const polygons = target.polygons
        .filter((polygon) => polygon.length >= 3)
        .map((polygon) =>
          polygon.map(([xMm, yMm]) => [
            xMm / pixelScale,
            previewPixelHeight - yMm / pixelScale,
          ] as [number, number]),
        );
      const path = supportsPath2D ? new Path2D() : null;
      if (path) {
        for (const polygon of polygons) {
          polygon.forEach(([px, py], index) => {
            if (index === 0) {
              path.moveTo(px, py);
            } else {
              path.lineTo(px, py);
            }
          });
          path.closePath();
        }
      }
      return { hex: target.hex, path, polygons };
    });

    blinkTargetsRef.current =
      renderTargets.every((target) => target.polygons.length === 0)
        ? []
        : renderTargets;
    blinkTargetsVersionRef.current += 1;
  }, [
    selectionBlinkEnabled,
    svgContours,
    previewPixelWidth,
    previewPixelHeight,
    previewWidthMm,
  ]);

  // --- 脉冲时钟 effect：全局连续运行的 rAF 循环，只负责按相位更新 opacity。 ---
  // 只挂一次（依赖不含任何选区状态），每帧从 blinkTargetsRef 读最新轮廓，
  // 版本号变化时才重描轮廓，opacity 每帧照算 → 选区变化不打断周期/相位/频率。
  useEffect(() => {
    const canvas = selectionBlinkCanvasRef.current;
    if (!canvas || !selectionBlinkEnabled || !previewPixelWidth || !previewPixelHeight) {
      if (canvas) {
        canvas.style.opacity = '0';
        canvas.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height);
      }
      return;
    }

    const context = canvas.getContext('2d');
    if (!context) {
      canvas.style.opacity = '0';
      return;
    }

    canvas.width = previewPixelWidth;
    canvas.height = previewPixelHeight;

    const drawTarget = (target: BlinkRenderTarget) => {
      if (target.path) {
        context.fill(target.path);
        return;
      }
      for (const polygon of target.polygons) {
        context.beginPath();
        polygon.forEach(([px, py], index) => {
          if (index === 0) {
            context.moveTo(px, py);
          } else {
            context.lineTo(px, py);
          }
        });
        context.closePath();
        context.fill();
      }
    };

    const redrawTargets = () => {
      context.clearRect(0, 0, canvas.width, canvas.height);
      const targets = blinkTargetsRef.current;
      if (targets.length === 0) return;
      context.save();
      for (const target of targets) {
        context.fillStyle = blinkFillStyleForHex(target.hex, 1);
        drawTarget(target);
      }
      context.restore();
    };

    let lastDrawnVersion = -1;
    let animationFrame = 0;
    const blinkPeriodMs = SELECTION_BLINK_ACTIVE_MS + SELECTION_BLINK_REST_MS;

    const drawFrame = () => {
      const version = blinkTargetsVersionRef.current;
      if (version !== lastDrawnVersion) {
        lastDrawnVersion = version;
        redrawTargets();
      }
      const hasTargets = blinkTargetsRef.current.length > 0;
      const phaseMs = performance.now() % blinkPeriodMs;
      if (!hasTargets || phaseMs >= SELECTION_BLINK_ACTIVE_MS) {
        canvas.style.opacity = '0';
      } else {
        const progress = phaseMs / SELECTION_BLINK_ACTIVE_MS;
        const pulse = Math.sin(progress * Math.PI);
        canvas.style.opacity =
          pulse < SELECTION_BLINK_MIN_DRAW_ALPHA ? '0' : String(pulse);
      }
      animationFrame = window.requestAnimationFrame(drawFrame);
    };

    animationFrame = window.requestAnimationFrame(drawFrame);
    return () => {
      window.cancelAnimationFrame(animationFrame);
      canvas.style.opacity = '0';
      context.clearRect(0, 0, canvas.width, canvas.height);
    };
    // 仅在开关/画布尺寸变化时重建循环；选区状态（svgContours 等）刻意不在依赖里。
  }, [selectionBlinkEnabled, previewPixelWidth, previewPixelHeight]);

  const executeBrushDraft = useCallback(() => {
    const hasDraft = brushStrokesRef.current.length > 0 || brushPointsRef.current.length > 0;
    if (!selectionDocument || !hasDraft || !previewPixelWidth) return;
    // 提交所有累积的笔（历史笔 + 当前笔）的点，打平成一列。
    const points = [...brushStrokesRef.current, brushPointsRef.current].flat();
    const beforeRevision = selectionDocument.selection_revision;
    void applySelectionMutation({
      operation: 'brush-add',
      // brushPoints are in image-pixel space; convert the display-pixel brush
      // size with the same scale the draft stroke used so the backend hit-test
      // matches what the user painted. 笔迹按图像像素绘制，半径也要按同样比例换算。
      brushRadius: (brushSizePx / 2) * brushDisplayToImageScaleRef.current,
      brushPoints: points,
    }).then(() => {
      const current = useConverterStore.getState();
      if (
        current.selectionDocument?.selection_revision === beforeRevision &&
        current.error
      ) {
        return;
      }
      brushStrokesRef.current = [];
      brushPointsRef.current = [];
      brushDraftCanvasRef.current
        ?.getContext('2d')
        ?.clearRect(
          0,
          0,
          brushDraftCanvasRef.current?.width ?? 0,
          brushDraftCanvasRef.current?.height ?? 0,
        );
      setBrushDraftVersion((version) => version + 1);
    });
  }, [applySelectionMutation, brushSizePx, selectionDocument]);

  const clearBrushDraft = useCallback(() => {
    brushStrokesRef.current = [];
    brushPointsRef.current = [];
    const canvas = brushDraftCanvasRef.current;
    canvas?.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height);
    setBrushDraftVersion((version) => version + 1);
  }, []);

  // Clear any in-progress brush draft when the image/session changes, so
  // strokes made on the previous image can never be applied to the new one
  // (executeBrushDraft submits raw pixel coordinates, which are only valid
  // for the image they were drawn on).
  // 图像/会话切换时清空画笔草稿，避免把上一张图的笔迹提交给新图
  // （executeBrushDraft 提交的是像素坐标，仅对绘制它的那张图有效）。
  useEffect(() => {
    clearBrushDraft();
  }, [sessionId, stableImageUrl, clearBrushDraft]);

  const appendBrushSample = useCallback((sample: CanvasPreviewHoverSample, start: boolean) => {
    if (selectionTool !== 'brush' || !previewPixelWidth || !previewPixelHeight) return;
    // Keep the brush cursor visible during the stroke by updating the hover sample
    setBrushHoverSample(sample);
    const point = { x: sample.pixelX, y: sample.pixelY };
    if (start) brushPointsRef.current = [];
    brushPointsRef.current.push(point);
    const canvas = brushDraftCanvasRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context) return;
    if (canvas.width !== previewPixelWidth || canvas.height !== previewPixelHeight) {
      canvas.width = previewPixelWidth;
      canvas.height = previewPixelHeight;
    }
    // The brush size is in *display* pixels (what the user sees on screen).
    // The draft canvas is in preview image pixel space, so we convert display
    // pixels to image pixels. The image is letterboxed (object-fit contain)
    // inside the container, so the correct denominator is the *fitted* image
    // width on screen, not the full container width — otherwise the stroke is
    // smaller than the cursor when the container aspect differs from the image.
    // 画笔尺寸是屏幕像素，草稿画布是图像像素空间；图像在容器内按 contain
    // 缩放留边，换算分母必须用"图像在屏的实际宽度"而非容器宽度，否则
    // 容器与图像宽高比不一致时笔迹会比指示圈小。
    const naturalAspect =
      sample.naturalHeight > 0 ? sample.naturalWidth / sample.naturalHeight : 1;
    const containerAspect =
      sample.containerHeight > 0
        ? sample.containerWidth / sample.containerHeight
        : 1;
    const fittedImageWidth =
      containerAspect > naturalAspect
        ? sample.containerHeight * naturalAspect
        : sample.containerWidth;
    const displayToImageScale =
      fittedImageWidth > 0 ? sample.naturalWidth / fittedImageWidth : 1;
    brushDisplayToImageScaleRef.current = displayToImageScale;
    // The cursor and stroke should both track image pixels consistently so
    // their relationship stays constant at any zoom level.
    const imageBrushSizePx = brushSizePx * displayToImageScale;

    // 每个采样点把历史笔 + 当前笔全部重画（每条路径只 stroke 一次、不自我
    // 重叠），因此重叠采样点不会让 alpha 叠加，所有笔保持统一固定透明度、
    // 且都能同时看见。
    // Redraw every stroke (past + current) per sample; each path is stroked
    // once and never overlaps itself, so alpha stays uniform across all strokes.
    drawBrushStrokes(context, brushStrokesRef.current, brushPointsRef.current, imageBrushSizePx);
    setBrushDraftVersion((version) => version + 1);
  }, [brushSizePx, previewPixelHeight, previewPixelWidth, selectionTool]);

  // 抬笔：把当前笔并入历史笔，下一笔从新点列开始，但所有笔仍留在画布上。
  // On stroke end, fold the current stroke into history so the next stroke
  // starts fresh while all strokes stay on the canvas.
  const endBrushStroke = useCallback(() => {
    if (brushPointsRef.current.length > 0) {
      brushStrokesRef.current.push(brushPointsRef.current);
      brushPointsRef.current = [];
    }
    setBrushDraftVersion((version) => version + 1);
  }, []);

  useEffect(() => {
    if (selectionTool !== 'brush') {
      setBrushHoverSample(null);
    }
  }, [selectionTool]);

  const hoverInspectorStyle = hoverSample ? computeHoverInspectorStyle(hoverSample, {
    layerCount: hoverLayerColors.length,
    showMagnifier,
    showLayerDetails,
  }) : null;
  const hoverInspectorOverlay = hoverInspectorEnabled && selectionTool !== 'brush' && hoverSample && hoverInspectorStyle && typeof document !== 'undefined'
    ? createPortal(
      <PreviewHoverInspector
        dataTestId="main-2d-hover-inspector"
        style={hoverInspectorStyle}
        magnifierCanvasRef={magnifierCanvasRef}
        pixelX={hoverSample.pixelX}
        pixelY={hoverSample.pixelY}
        surfaceHex={hoverSurfaceHex}
        hoverLayerColors={hoverLayerColors}
        layerImagesLoading={layerImagesLoading}
        showMagnifier={showMagnifier}
        showLayerDetails={showLayerDetails}
      />,
      document.body,
    )
    : null;

  const renderBrushCursorScreenOverlay = useCallback((viewport: CanvasPreviewSurfaceViewport) => {
    if (selectionTool !== 'brush') return null;

    // 画笔指示圈只在图像内替代系统光标（此时 cursor-none）。越界时系统光标
    // 已恢复可见，指示圈若继续贴边残留，反而制造"圈在边缘、鼠标在别处"的
    // 双重光标假象，因此越界/未悬停时不渲染。
    if (!brushHoverSample || brushHoverSample.isOutOfImage) return null;

    const diameter = Math.max(brushSizePx * viewport.scale, 3);

    return (
      <div
        data-testid="selection-brush-cursor"
        className="pointer-events-none absolute z-30 rounded-full border border-pink-400 bg-pink-300/15 shadow-[0_0_0_1px_rgba(255,255,255,0.8)]"
        style={{
          width: `${diameter}px`,
          height: `${diameter}px`,
          left: `${brushHoverSample.containerX}px`,
          top: `${brushHoverSample.containerY}px`,
          transform: 'translate(-50%, -50%)',
        }}
        aria-hidden="true"
      />
    );
  }, [brushHoverSample, brushSizePx, selectionTool]);

  // Cache geometry in image pixels. Navigation changes only the enclosing
  // transform, so neither vertex projection nor SVG node count grows per frame.
  const marchingAntsPaths = useMemo(() => {
    const contourWidth = resolvePreviewWidthForContours(previewWidthMm, previewPixelWidth);
    if (!previewPixelWidth || !previewPixelHeight || !contourWidth) return null;
    const pixelScale = contourWidth / previewPixelWidth;
    const subpaths: string[] = [];
    for (const { polygons } of svgContours) {
      for (const polygon of polygons) {
        if (polygon.length < 3) continue;
        subpaths.push(`${polygon.map(([xMm, yMm], index) =>
          `${index === 0 ? 'M' : 'L'} ${xMm / pixelScale} ${previewPixelHeight - yMm / pixelScale}`,
        ).join(' ')} Z`);
      }
    }
    if (subpaths.length === 0) return null;
    const path = subpaths.join(' ');
    return (
      <>
        <path
          data-testid="selection-marching-ants-white"
          d={path}
          fill="none"
          stroke="#ffffff"
          strokeWidth={1}
          strokeDasharray="4 4"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
          className="selection-marching-ants selection-marching-ants--white"
        />
        <path
          data-testid="selection-marching-ants-black"
          d={path}
          fill="none"
          stroke="#1a1a1a"
          strokeWidth={1}
          strokeDasharray="4 4"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
          className="selection-marching-ants selection-marching-ants--black"
        />
      </>
    );
  }, [previewPixelHeight, previewPixelWidth, previewWidthMm, svgContours]);

  const renderMarchingAntsScreenOverlay = useCallback((viewport: CanvasPreviewSurfaceViewport) => {
    if (
      !previewPixelWidth ||
      !previewPixelHeight ||
      viewport.containerSize.width <= 0 ||
      viewport.containerSize.height <= 0 ||
      !marchingAntsPaths
    ) {
      return null;
    }

    const { x, y, width, height } = viewport.imageScreenRect;
    const contourWidth = resolvePreviewWidthForContours(previewWidthMm, previewPixelWidth);
    if (!contourWidth) return null;
    return (
      <SelectionOutlineOverlay
        contours={svgContours}
        pixelWidth={previewPixelWidth}
        pixelHeight={previewPixelHeight}
        contourWidth={contourWidth}
        viewport={viewport}
        fallback={(
          <svg
            data-testid="selection-marching-ants-overlay"
            viewBox={`0 0 ${viewport.containerSize.width} ${viewport.containerSize.height}`}
            className="pointer-events-none absolute inset-0 h-full w-full"
            aria-hidden="true"
          >
            <g transform={`translate(${x} ${y}) scale(${width / previewPixelWidth} ${height / previewPixelHeight})`}>
              {marchingAntsPaths}
            </g>
          </svg>
        )}
      />
    );
  }, [previewPixelHeight, previewPixelWidth, previewWidthMm, svgContours, marchingAntsPaths]);

  const renderSelectionScreenOverlay = useCallback((viewport: CanvasPreviewSurfaceViewport) => (
    <>
      {renderMarchingAntsScreenOverlay(viewport)}
      {renderBrushCursorScreenOverlay(viewport)}
    </>
  ), [renderBrushCursorScreenOverlay, renderMarchingAntsScreenOverlay]);

  // Always mount the pulse canvas once a preview exists. Previously it only
  // mounted after contours appeared, while the rAF effect had already returned
  // with a null ref; enabling blink therefore looked broken until another
  // unrelated dependency changed.
  const scaledPixelOverlay = previewPixelWidth && previewPixelHeight ? (
    <>
      <canvas
        ref={selectionBlinkCanvasRef}
        data-testid="selection-blink-canvas"
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 h-full w-full"
        style={{ zIndex: 6 }}
      />
      <canvas
        ref={brushDraftCanvasRef}
        data-testid="selection-brush-draft"
        data-version={brushDraftVersion}
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 h-full w-full"
        style={{ zIndex: 7, opacity: BRUSH_STROKE_OPACITY }}
      />
    </>
  ) : null;

  const floatingOverlay = (
    <>
      {replacePreviewLoading && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-950/40">
          <p className="text-xs text-slate-100">{t('lut_grid_loading')}</p>
        </div>
      )}

      <div
        className="pointer-events-none absolute inset-0 z-20"
        aria-hidden="true"
      >
        <div
          className="absolute right-2 top-2 rounded-full px-2 py-1 text-[10px] font-semibold"
          style={{
            background: 'var(--surface-well)',
            color: 'var(--surface-text-muted)',
          }}
        >
          {t('preview_debug_main_2d')}
        </div>
      </div>

      {selectionTool === 'brush' && (brushStrokesRef.current.length > 0 || brushPointsRef.current.length > 0) && (
        <div className="pointer-events-auto absolute bottom-2 left-1/2 z-30 flex -translate-x-1/2 gap-2 rounded-[10px] border border-slate-300/80 bg-white/95 p-2 dark:border-slate-700/80 dark:bg-slate-900/95">
          <button
            type="button"
            onClick={executeBrushDraft}
            className="action-control action-control-primary rounded-lg px-3 py-1.5 text-xs font-semibold"
          >
            {t('selection_brush_apply')}
          </button>
          <button
            type="button"
            onClick={clearBrushDraft}
            className="action-control rounded-lg px-3 py-1.5 text-xs"
          >
            {t('selection_brush_clear')}
          </button>
        </div>
      )}

      {originalUploadUrl && (
        <button
          type="button"
          aria-label={t('color_2d_hold_view_original')}
          title={t('color_2d_hold_view_original')}
          onPointerDown={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setShowOriginal(true);
          }}
          onPointerUp={releaseOriginalView}
          onPointerLeave={releaseOriginalView}
          onPointerCancel={releaseOriginalView}
          onContextMenu={(e) => e.preventDefault()}
          data-testid="color-preview-2d-hold-original"
          data-active={showOriginal || undefined}
          className={cx(
            "pointer-events-auto absolute right-2 top-10 z-30 flex h-7 w-7 items-center justify-center rounded-lg",
            "bg-slate-900/60 text-slate-100 backdrop-blur-sm transition-colors",
            "hover:bg-slate-900/75 active:bg-slate-900/85",
            showOriginal && "bg-slate-900/85",
          )}
          style={{ touchAction: 'none' }}
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <rect x="3" y="4" width="8" height="16" rx="1.5" />
            <rect x="13" y="4" width="8" height="16" rx="1.5" fill="currentColor" stroke="none" />
          </svg>
        </button>
      )}

      {zoom !== 1 && (
        <div className="absolute left-2 top-2 z-20 rounded-full bg-slate-900/60 px-2 py-0.5 text-[10px] text-slate-100 backdrop-blur-sm">
          {Math.round(zoom * 100)}%
        </div>
      )}
    </>
  );


  if (!activeCanvasSrc) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-sm text-slate-500 dark:text-slate-400">
        {isLoading ? (
          <>
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600 dark:border-slate-600 dark:border-t-slate-300" />
            <span>{t('color_2d_generating_preview')}</span>
          </>
        ) : (
          t('color_2d_no_preview')
        )}
      </div>
    );
  }

  return (
    <>
      <CanvasPreviewSurface
        src={activeCanvasSrc}
        alt={previewAltText}
        dataTestId="color-preview-2d-container"
        className={
          modelingMode === ModelingMode.VECTOR
            ? 'h-full w-full checkerboard-bg'
            : 'h-full w-full bg-slate-200/60 dark:bg-slate-900/60'
        }
        surfaceClassName={
          selectionTool === 'brush' && brushHoverSample && !brushHoverSample.isOutOfImage
            // 仅当指针确实悬停在图像上时隐藏系统光标（指示圈接管）；图像外
            // 留白区或未悬停时系统光标始终可见，任何时刻都不会"鼠标找不到"。
            ? 'cursor-none'
            : 'cursor-crosshair'
        }
        renderingQuality="crisp"
        overlay={scaledPixelOverlay}
        screenSpaceOverlay={renderSelectionScreenOverlay}
        floatingOverlay={floatingOverlay}
        interactionsDisabled={replacePreviewLoading}
        minScale={MIN_ZOOM}
        maxScale={MAX_ZOOM}
        wheelZoomStepMultiplier={ZOOM_STEP}
        allowOutOfImageHover={brushStrokesEnabled}
        onHoverSample={handleCanvasHoverSample}
        onClickSample={brushStrokesEnabled ? undefined : handleClick}
        onStrokeStart={brushStrokesEnabled ? (sample) => appendBrushSample(sample, true) : undefined}
        onStrokeMove={brushStrokesEnabled ? (sample) => appendBrushSample(sample, false) : undefined}
        onStrokeEnd={brushStrokesEnabled ? endBrushStroke : undefined}
        onStrokeCancel={brushStrokesEnabled ? () => setBrushDraftVersion((version) => version + 1) : undefined}
        onSurfaceReady={handleSurfaceReady}
        onScaleChange={setZoom}
        middleButtonPanEnabled
        spacePanEnabled
        canStartDrag={(event) => event.button === 2}
      />
      {hoverInspectorOverlay}
    </>
  );
}
