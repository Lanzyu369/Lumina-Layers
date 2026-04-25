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
import { buildLayerImagesSourceKey, useConverterStore } from '../../stores/converter';
import { useI18n } from '../../i18n/context';
import CanvasPreviewSurface from '../ui/CanvasPreviewSurface';
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

/**
 * Find the closest palette entry to a given hex color.
 * 查找与给定 hex 最接近的调色板条目。
 */
function findClosestPaletteHex(
  hex: string,
  palette: Array<{ matched_hex: string }>,
): string | null {
  if (palette.length === 0) return null;

  const hexLower = hex.toLowerCase();
  // Exact match first
  const exact = palette.find((p) => p.matched_hex.toLowerCase() === hexLower);
  if (exact) return exact.matched_hex;

  // Color distance match
  const tr = parseInt(hex.slice(0, 2), 16);
  const tg = parseInt(hex.slice(2, 4), 16);
  const tb = parseInt(hex.slice(4, 6), 16);

  let bestDist = Infinity;
  let bestHex: string | null = null;

  for (const entry of palette) {
    const h = entry.matched_hex.replace(/^#/, '');
    const er = parseInt(h.slice(0, 2), 16);
    const eg = parseInt(h.slice(2, 4), 16);
    const eb = parseInt(h.slice(4, 6), 16);
    const dist = (tr - er) ** 2 + (tg - eg) ** 2 + (tb - eb) ** 2;
    if (dist < bestDist) {
      bestDist = dist;
      bestHex = entry.matched_hex;
    }
  }

  return bestHex;
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

  const previewPixelWidth = useConverterStore((s) => s.previewPixelWidth);
  const previewPixelHeight = useConverterStore((s) => s.previewPixelHeight);
  const selectionMode = useConverterStore((s) => s.selectionMode);
  const selectedColor = useConverterStore((s) => s.selectedColor);
  const selectedColors = useConverterStore((s) => s.selectedColors);
  const palette = useConverterStore((s) => s.palette);
  const isLoading = useConverterStore((s) => s.isLoading);
  const replacePreviewLoading = useConverterStore((s) => s.replacePreviewLoading);
  const colorContours = useConverterStore((s) => s.colorContours);
  const regionData = useConverterStore((s) => s.regionData);
  const selectedRegions = useConverterStore((s) => s.selectedRegions);
  const sessionId = useConverterStore((s) => s.sessionId);
  const previewGlbUrl = useConverterStore((s) => s.previewGlbUrl);
  const previewWidthMm = useConverterStore((s) => s.preview_width_mm);
  const bedLabel = useConverterStore((s) => s.bed_label);
  const bedSizes = useConverterStore((s) => s.bedSizes);
  const fetchLayerImages = useConverterStore((s) => s.fetchLayerImages);
  const layerImagesLoading = useConverterStore((s) => s.layerImagesLoading);
  const layerImages = useConverterStore((s) => s.layerImages);
  const layerImagesSourceKey = useConverterStore((s) => s.layerImagesSourceKey);

  const setSelectedColor = useConverterStore((s) => s.setSelectedColor);
  const toggleColorInSelection = useConverterStore((s) => s.toggleColorInSelection);
  const detectRegion = useConverterStore((s) => s.detectRegion);
  const detectAndAccumulateRegion = useConverterStore((s) => s.detectAndAccumulateRegion);

  const [hoverSample, setHoverSample] = useState<CanvasPreviewHoverSample | null>(null);
  const [hoverLayerColors, setHoverLayerColors] = useState<HoverLayerColorSample[]>([]);
  const [hoverSurfaceHex, setHoverSurfaceHex] = useState<string | null>(null);
  const [previewCanvasBuffer, setPreviewCanvasBuffer] = useState<PreviewCanvasBuffer | null>(null);
  const [layerCanvasBuffers, setLayerCanvasBuffers] = useState<LayerCanvasBuffer[]>([]);
  const pendingHoverSampleRef = useRef<CanvasPreviewHoverSample | null>(null);
  const hoverDelayTimerRef = useRef<number | null>(null);
  const hoverResourceReleaseTimerRef = useRef<number | null>(null);
  const magnifierCanvasRef = useRef<HTMLCanvasElement>(null);
  const fetchedLayerSessionRef = useRef<string | null>(null);
  const layerSampleCacheRef = useRef<Map<string, HoverLayerColorSample[]>>(new Map());
  const surfaceSampleCacheRef = useRef<Map<string, string | null>>(new Map());
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
    setPreviewCanvasBuffer(payload?.previewBuffer ?? null);
    surfaceSampleCacheRef.current.clear();
  }, []);

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
  }, [clearHoverResourceReleaseTimer, hoverInspectorEnabled, scheduleHoverResourceRelease]);

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
    setPreviewCanvasBuffer(null);
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

  const handleClick = useCallback(
    (sample: CanvasPreviewHoverSample) => {
      if (replacePreviewLoading) return;
      if (!previewPixelWidth || !previewPixelHeight) return;

      const { pixelX, pixelY, naturalWidth, naturalHeight } = sample;

      switch (selectionMode) {
        case 'select-all': {
          const rawHex = readPixelColor(previewCanvasBuffer, {
            pixelX,
            pixelY,
            naturalWidth,
            naturalHeight,
          });
          if (!rawHex) return;
          const paletteHex = findClosestPaletteHex(rawHex, palette);
          if (!paletteHex) return;
          toggleColorInSelection(paletteHex);
          if (selectedColors.has(paletteHex)) {
            const remaining = Array.from(selectedColors).filter((c) => c !== paletteHex);
            setSelectedColor(remaining.length > 0 ? remaining[remaining.length - 1] : null);
          } else {
            setSelectedColor(paletteHex);
          }
          break;
        }
        case 'current':
        case 'region':
          detectRegion(pixelX, pixelY);
          break;
        case 'multi-select':
          detectAndAccumulateRegion(pixelX, pixelY);
          break;
      }
    },
    [
      replacePreviewLoading,
      previewPixelWidth,
      previewPixelHeight,
      selectionMode,
      previewCanvasBuffer,
      palette,
      selectedColors,
      toggleColorInSelection,
      setSelectedColor,
      detectRegion,
      detectAndAccumulateRegion,
    ],
  );

  // Collect contour polygons to render as SVG overlays
  const svgContours = useMemo(() => {
    if (!previewPixelWidth || !previewPixelHeight) return [];

    const targets: Array<{ hex: string; polygons: number[][][] }> = [];

    if (
      (selectionMode === 'current' || selectionMode === 'region') &&
      selectedColor &&
      regionData?.contours &&
      regionData.contours.length > 0
    ) {
      targets.push({ hex: selectedColor, polygons: regionData.contours });
    } else if (selectionMode === 'multi-select' && selectedRegions.length > 0) {
      for (const region of selectedRegions) {
        if (region.contours && region.contours.length > 0) {
          const hex = region.colorHex.replace(/^#/, '');
          targets.push({ hex, polygons: region.contours });
        }
      }
    } else if (
      selectionMode === 'select-all' &&
      selectedColors.size > 0 &&
      !isRegionScopedSelection
    ) {
      // Skip when the selection is region-scoped: ``colorContours`` lists
      // every pixel of each hex across the whole canvas, which would paint
      // cyan outlines far beyond the region's connected component. The
      // region flow already displays the backend's exact mask via
      // ``previewImageUrl`` above, so no client-side overlay is needed.
      // 区域来源跳过 contour 叠加——colorContours 是全图同色轮廓，叠上去
      // 会把区域外的同色像素也框住；区域流程已经通过 previewImageUrl 显
      // 示精确 mask 图，无需再叠轮廓。
      for (const hex of selectedColors) {
        if (colorContours[hex]) {
          targets.push({ hex, polygons: colorContours[hex] });
        }
      }
    } else if (selectedColor && colorContours[selectedColor]) {
      targets.push({ hex: selectedColor, polygons: colorContours[selectedColor] });
    }

    return targets;
  }, [
    selectionMode,
    selectedColor,
    selectedColors,
    selectedRegions,
    regionData,
    colorContours,
    previewPixelWidth,
    previewPixelHeight,
    isRegionScopedSelection,
  ]);

  const hoverInspectorStyle = hoverSample ? computeHoverInspectorStyle(hoverSample, {
    layerCount: hoverLayerColors.length,
    showMagnifier,
    showLayerDetails,
  }) : null;
  const hoverInspectorOverlay = hoverInspectorEnabled && hoverSample && hoverInspectorStyle && typeof document !== 'undefined'
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

  const contourOverlay = svgContours.length > 0 && previewPixelWidth && previewPixelHeight ? (
    <svg
      viewBox={`0 0 ${previewPixelWidth} ${previewPixelHeight}`}
      className="pointer-events-none absolute inset-0 h-full w-full"
      style={{ zIndex: 5 }}
    >
      {svgContours.map(({ hex, polygons }, ti) =>
        polygons.map((polygon, pi) => {
          if (polygon.length < 3) return null;
          const previewWidthMmState = useConverterStore.getState().preview_width_mm;
          if (!previewWidthMmState || previewWidthMmState <= 0) return null;
          const pixelScale = previewWidthMmState / previewPixelWidth;

          const points = polygon
            .map(([xMm, yMm]) => {
              const px = xMm / pixelScale;
              const py = previewPixelHeight - yMm / pixelScale;
              return `${px},${py}`;
            })
            .join(' ');

          return (
            <polygon
              key={`${hex}-${ti}-${pi}`}
              points={points}
              fill="none"
              stroke="#00ffff"
              strokeWidth={Math.max(1, previewPixelWidth / 500)}
              strokeLinejoin="round"
              opacity={0.85}
            />
          );
        }),
      )}
    </svg>
  ) : null;

  const floatingOverlay = (
    <>
      {replacePreviewLoading && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-950/40">
          <p className="text-xs text-slate-100">{t('lut_grid_loading')}</p>
        </div>
      )}

      <div
        className="pointer-events-none absolute inset-0 z-20 border-2"
        style={{ borderColor: 'var(--info-border)' }}
        aria-hidden="true"
      >
        <div
          className="absolute right-2 top-2 rounded-full border px-2 py-1 text-[10px] font-semibold"
          style={{
            borderColor: 'var(--info-border)',
            background: 'var(--info-soft)',
            color: 'var(--surface-text-muted)',
          }}
        >
          {t('preview_debug_main_2d')}
        </div>
      </div>

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
            "pointer-events-auto absolute right-2 top-10 z-30 flex h-7 w-7 items-center justify-center rounded-md border",
            "border-slate-300/80 bg-slate-100/90 text-slate-700 shadow-sm transition-colors",
            "hover:bg-slate-200/90 active:bg-slate-300/90",
            "dark:border-slate-700/80 dark:bg-slate-900/80 dark:text-slate-200 dark:hover:bg-slate-800/90",
            showOriginal && "bg-slate-300/90 dark:bg-slate-700/90",
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


  if (!displayUrl) {
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
        src={showOriginal && originalUploadUrl ? originalUploadUrl : displayUrl}
        alt={previewAltText}
        dataTestId="color-preview-2d-container"
        className="h-full w-full bg-slate-200/60 dark:bg-slate-900/60"
        surfaceClassName="cursor-crosshair"
        renderingQuality="crisp"
        overlay={contourOverlay}
        floatingOverlay={floatingOverlay}
        interactionsDisabled={replacePreviewLoading}
        minScale={MIN_ZOOM}
        maxScale={MAX_ZOOM}
        wheelZoomStepMultiplier={ZOOM_STEP}
        resetOnDoubleClick
        onHoverSample={handleCanvasHoverSample}
        onClickSample={handleClick}
        onSurfaceReady={handleSurfaceReady}
        onScaleChange={setZoom}
        canStartDrag={(event) => event.button === 2}
      />
      {hoverInspectorOverlay}
    </>
  );
}
