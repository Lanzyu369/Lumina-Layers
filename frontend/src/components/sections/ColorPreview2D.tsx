/* eslint-disable react-refresh/only-export-components */
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
import { useConverterStore } from '../../stores/converter';
import { useI18n } from '../../i18n/context';
import type { ZoomableImageHoverSample } from '../ui/ZoomableImage';
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
  buildPreviewCanvasBuffer,
  clampNumber,
  computeHoverInspectorStyle,
  mapPixelToBufferCoordinate,
  rgbToHex,
  setBoundedCacheValue,
} from '../ui/previewHoverInspectorUtils';
import { resolvePreviewHoverPixel } from './actionBarHoverUtils';
import { readPixelColor } from './colorPreview2DUtils';

/**
 * Convert a click on an <img> with object-contain to image pixel coordinates.
 * 将 object-contain 模式下 <img> 上的点击转换为图像像素坐标。
 *
 * @param event - The mouse event on the image element.
 * @param imgEl - The <img> DOM element.
 * @param naturalW - The intrinsic image width in pixels.
 * @param naturalH - The intrinsic image height in pixels.
 * @returns [pixelX, pixelY] in image space, or null if click is in letterbox padding.
 */
export function imgClickToPixel(
  event: React.MouseEvent<HTMLImageElement>,
  imgEl: HTMLImageElement,
  naturalW: number,
  naturalH: number,
): [number, number] | null {
  const rect = imgEl.getBoundingClientRect();
  const clientW = rect.width;
  const clientH = rect.height;

  if (naturalW <= 0 || naturalH <= 0 || clientW <= 0 || clientH <= 0) {
    return null;
  }

  // Compute the rendered image rect within the element (object-contain)
  const scale = Math.min(clientW / naturalW, clientH / naturalH);
  const renderedW = naturalW * scale;
  const renderedH = naturalH * scale;
  const offsetX = (clientW - renderedW) / 2;
  const offsetY = (clientH - renderedH) / 2;

  const relX = event.clientX - rect.left - offsetX;
  const relY = event.clientY - rect.top - offsetY;

  // Click in letterbox padding
  if (relX < 0 || relX >= renderedW || relY < 0 || relY >= renderedH) {
    return null;
  }

  const pixelX = Math.floor((relX / renderedW) * naturalW);
  const pixelY = Math.floor((relY / renderedH) * naturalH);

  return [
    Math.max(0, Math.min(naturalW - 1, pixelX)),
    Math.max(0, Math.min(naturalH - 1, pixelY)),
  ];
}

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
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  // Use previewBaseImageUrl for a stable image that only changes on actual
  // content updates (initial preview, color replacement, undo), not on
  // region detection, color highlighting, or selection mode switching.
  const previewBaseImageUrl = useConverterStore((s) => s.previewBaseImageUrl);
  const previewImageUrl = useConverterStore((s) => s.previewImageUrl);
  const stableImageUrl = previewBaseImageUrl ?? previewImageUrl;

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
  const previewWidthMm = useConverterStore((s) => s.preview_width_mm);
  const bedLabel = useConverterStore((s) => s.bed_label);
  const bedSizes = useConverterStore((s) => s.bedSizes);
  const fetchLayerImages = useConverterStore((s) => s.fetchLayerImages);
  const layerImagesLoading = useConverterStore((s) => s.layerImagesLoading);
  const layerImages = useConverterStore((s) => s.layerImages);

  const setSelectedColor = useConverterStore((s) => s.setSelectedColor);
  const toggleColorInSelection = useConverterStore((s) => s.toggleColorInSelection);
  const detectRegion = useConverterStore((s) => s.detectRegion);
  const detectAndAccumulateRegion = useConverterStore((s) => s.detectAndAccumulateRegion);

  const [hoverSample, setHoverSample] = useState<ZoomableImageHoverSample | null>(null);
  const [hoverLayerColors, setHoverLayerColors] = useState<HoverLayerColorSample[]>([]);
  const [hoverSurfaceHex, setHoverSurfaceHex] = useState<string | null>(null);
  const [previewCanvasBuffer, setPreviewCanvasBuffer] = useState<PreviewCanvasBuffer | null>(null);
  const [layerCanvasBuffers, setLayerCanvasBuffers] = useState<LayerCanvasBuffer[]>([]);
  const pendingHoverSampleRef = useRef<ZoomableImageHoverSample | null>(null);
  const hoverDelayTimerRef = useRef<number | null>(null);
  const hoverResourceReleaseTimerRef = useRef<number | null>(null);
  const magnifierCanvasRef = useRef<HTMLCanvasElement>(null);
  const fetchedLayerSessionRef = useRef<string | null>(null);
  const layerSampleCacheRef = useRef<Map<string, HoverLayerColorSample[]>>(new Map());
  const surfaceSampleCacheRef = useRef<Map<string, string | null>>(new Map());
  const needsLayerHoverData = hoverInspectorEnabled && showLayerDetails && hoverSample !== null;

  // --------------- Zoom / Pan state ---------------
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const isPanningRef = useRef(false);
  const panStartRef = useRef({ x: 0, y: 0, panX: 0, panY: 0 });
  const didDragRef = useRef(false);

  // Track container dimensions for explicit image fitting.
  // Re-run when displayUrl changes so the observer attaches after the
  // placeholder is replaced by the main view (containerRef becomes valid).
  const [cSize, setCSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      setCSize({ w: width, h: height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [displayUrl]);

  // Track image natural dimensions
  const [natSize, setNatSize] = useState({ w: 0, h: 0 });
  const handleImgLoad = useCallback(() => {
    const img = imgRef.current;
    if (!img) return;
    setNatSize({ w: img.naturalWidth, h: img.naturalHeight });
    setPreviewCanvasBuffer(buildPreviewCanvasBuffer(img));
    surfaceSampleCacheRef.current.clear();
  }, []);

  // Compute fitted image dimensions (image scaled to fit container)
  const fitScale =
    natSize.w > 0 && natSize.h > 0 && cSize.w > 0 && cSize.h > 0
      ? Math.min(cSize.w / natSize.w, cSize.h / natSize.h)
      : 0;
  const fittedW = natSize.w * fitScale;
  const fittedH = natSize.h * fitScale;

  const mapPointerToHoverSample = useCallback(
    (clientX: number, clientY: number): ZoomableImageHoverSample | null => {
      const container = containerRef.current;
      if (!container || !natSize.w || !natSize.h || !fittedW || !fittedH) {
        return null;
      }

      const rect = container.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) {
        return null;
      }

      const baseOffX = (rect.width - fittedW) / 2;
      const baseOffY = (rect.height - fittedH) / 2;
      const relX = clientX - rect.left;
      const relY = clientY - rect.top;
      const imageX = (relX - pan.x) / zoom - baseOffX;
      const imageY = (relY - pan.y) / zoom - baseOffY;

      if (imageX < 0 || imageX >= fittedW || imageY < 0 || imageY >= fittedH) {
        return null;
      }

      const pixelX = Math.floor((imageX / fittedW) * natSize.w);
      const pixelY = Math.floor((imageY / fittedH) * natSize.h);

      return {
        containerX: Math.round(relX),
        containerY: Math.round(relY),
        containerWidth: Math.round(rect.width),
        containerHeight: Math.round(rect.height),
        containerLeft: Math.round(rect.left),
        containerTop: Math.round(rect.top),
        pixelX: Math.max(0, Math.min(natSize.w - 1, pixelX)),
        pixelY: Math.max(0, Math.min(natSize.h - 1, pixelY)),
        naturalWidth: natSize.w,
        naturalHeight: natSize.h,
      };
    },
    [natSize, fittedW, fittedH, pan, zoom],
  );

  const handleHoverSample = useCallback((sample: ZoomableImageHoverSample | null) => {
    if (!hoverInspectorEnabled) {
      pendingHoverSampleRef.current = null;
      if (hoverDelayTimerRef.current !== null) {
        window.clearTimeout(hoverDelayTimerRef.current);
        hoverDelayTimerRef.current = null;
      }
      if (hoverResourceReleaseTimerRef.current !== null) {
        window.clearTimeout(hoverResourceReleaseTimerRef.current);
        hoverResourceReleaseTimerRef.current = null;
      }
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
    if (hoverResourceReleaseTimerRef.current !== null) {
      window.clearTimeout(hoverResourceReleaseTimerRef.current);
      hoverResourceReleaseTimerRef.current = null;
    }

    if (sample === null) {
      setHoverSample((previous) => (previous === null ? previous : null));
      hoverResourceReleaseTimerRef.current = window.setTimeout(() => {
        hoverResourceReleaseTimerRef.current = null;
        setLayerCanvasBuffers((previous) => (previous.length === 0 ? previous : []));
        layerSampleCacheRef.current.clear();
        surfaceSampleCacheRef.current.clear();
      }, HOVER_RESOURCE_RELEASE_DELAY_MS);
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
  }, [hoverInspectorEnabled]);

  useEffect(() => {
    if (!hoverInspectorEnabled) {
      handleHoverSample(null);
    }
  }, [handleHoverSample, hoverInspectorEnabled]);

  useEffect(() => {
    if (hoverResourceReleaseTimerRef.current !== null) {
      window.clearTimeout(hoverResourceReleaseTimerRef.current);
      hoverResourceReleaseTimerRef.current = null;
    }
    setPreviewCanvasBuffer(null);
    setLayerCanvasBuffers([]);
    layerSampleCacheRef.current.clear();
    surfaceSampleCacheRef.current.clear();
    setHoverSample(null);
    setHoverLayerColors([]);
    setHoverSurfaceHex(null);
  }, [displayUrl]);

  useEffect(() => {
    return () => {
      if (hoverDelayTimerRef.current !== null) {
        window.clearTimeout(hoverDelayTimerRef.current);
        hoverDelayTimerRef.current = null;
      }
      if (hoverResourceReleaseTimerRef.current !== null) {
        window.clearTimeout(hoverResourceReleaseTimerRef.current);
        hoverResourceReleaseTimerRef.current = null;
      }
    };
  }, []);

  // Reset zoom/pan when the image source changes
  useEffect(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, [stableImageUrl]);

  useEffect(() => {
    if (!sessionId) {
      fetchedLayerSessionRef.current = null;
      return;
    }

    if (!needsLayerHoverData || !displayUrl || layerImagesLoading || layerImages.length > 0) {
      return;
    }

    if (fetchedLayerSessionRef.current === sessionId) {
      return;
    }

    fetchedLayerSessionRef.current = sessionId;
    void fetchLayerImages();
  }, [displayUrl, sessionId, needsLayerHoverData, layerImagesLoading, layerImages.length, fetchLayerImages]);

  useEffect(() => {
    let cancelled = false;

    if (!needsLayerHoverData) {
      return () => {
        cancelled = true;
      };
    }

    if (layerImages.length === 0) {
      setLayerCanvasBuffers([]);
      layerSampleCacheRef.current.clear();
      return () => {
        cancelled = true;
      };
    }

    const buildBuffers = async () => {
      const loaded = await Promise.all(
        layerImages.map(
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
  }, [layerImages, needsLayerHoverData]);

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

  // Mouse wheel → zoom, centred on cursor
  const handleWheel = useCallback(
    (e: React.WheelEvent<HTMLDivElement>) => {
      e.preventDefault();
      handleHoverSample(null);
      const container = containerRef.current;
      if (!container) return;

      const rect = container.getBoundingClientRect();
      const cursorX = e.clientX - rect.left;
      const cursorY = e.clientY - rect.top;

      setZoom((prevZoom) => {
        const factor = e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP;
        const newZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, prevZoom * factor));
        const scale = newZoom / prevZoom;
        // Adjust pan so the point under the cursor stays fixed
        setPan((prev) => ({
          x: cursorX - scale * (cursorX - prev.x),
          y: cursorY - scale * (cursorY - prev.y),
        }));
        return newZoom;
      });
    },
    [handleHoverSample],
  );

  // Pan via drag
  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      handleHoverSample(null);
      // Only pan with middle button or when zoom is at exactly 1× (no zoom)
      if (e.button !== 1 && zoom === 1) return;
      if (e.button === 2) return; // ignore right-click
      isPanningRef.current = true;
      didDragRef.current = false;
      panStartRef.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y };
      (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    },
    [zoom, pan, handleHoverSample],
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (isPanningRef.current) {
        const dx = e.clientX - panStartRef.current.x;
        const dy = e.clientY - panStartRef.current.y;
        if (Math.abs(dx) > 3 || Math.abs(dy) > 3) didDragRef.current = true;
        setPan({ x: panStartRef.current.panX + dx, y: panStartRef.current.panY + dy });
        handleHoverSample(null);
        return;
      }

      handleHoverSample(mapPointerToHoverSample(e.clientX, e.clientY));
    },
    [handleHoverSample, mapPointerToHoverSample],
  );

  const handlePointerUp = useCallback(() => {
    isPanningRef.current = false;
  }, []);

  const handlePointerLeave = useCallback(() => {
    isPanningRef.current = false;
    handleHoverSample(null);
  }, [handleHoverSample]);

  // Double-click to reset zoom/pan
  const handleDoubleClick = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);

  /**
   * Map a mouse event on the container to raw image pixel coordinates,
   * accounting for current zoom/pan transform and fit-to-container scaling.
   */
  const containerClickToPixel = useCallback(
    (e: React.MouseEvent<HTMLDivElement>): [number, number] | null => {
      const container = containerRef.current;
      if (!container || !natSize.w || !natSize.h || !fittedW || !fittedH) return null;

      const cRect = container.getBoundingClientRect();
      const cW = cRect.width;
      const cH = cRect.height;
      if (cW <= 0 || cH <= 0) return null;

      // Centred offset of the fitted image within the container
      const baseOffX = (cW - fittedW) / 2;
      const baseOffY = (cH - fittedH) / 2;

      // Invert CSS transform: translate(pan) scale(zoom) with origin 0 0
      const relX = e.clientX - cRect.left;
      const relY = e.clientY - cRect.top;
      const ix = (relX - pan.x) / zoom - baseOffX;
      const iy = (relY - pan.y) / zoom - baseOffY;
      const px = Math.floor((ix / fittedW) * natSize.w);
      const py = Math.floor((iy / fittedH) * natSize.h);

      if (px < 0 || px >= natSize.w || py < 0 || py >= natSize.h) return null;
      return [px, py];
    },
    [zoom, pan, natSize, fittedW, fittedH],
  );

  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (replacePreviewLoading) return;
      if (didDragRef.current) return; // ignore click after drag
      if (!previewPixelWidth || !previewPixelHeight) return;

      const imgEl = imgRef.current;
      if (!imgEl) return;

      const pixel = containerClickToPixel(e);
      if (!pixel) return;
      const [px, py] = pixel;

      switch (selectionMode) {
        case 'select-all': {
          const rawHex = readPixelColor(imgEl, px, py);
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
          detectRegion(px, py);
          break;
        case 'multi-select':
          detectAndAccumulateRegion(px, py);
          break;
      }
    },
    [
      replacePreviewLoading,
      previewPixelWidth,
      previewPixelHeight,
      selectionMode,
      palette,
      selectedColors,
      containerClickToPixel,
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
    } else if (selectionMode === 'select-all' && selectedColors.size > 0) {
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
      <div
        ref={containerRef}
        data-testid="color-preview-2d-container"
        className="relative h-full w-full overflow-hidden bg-slate-200/60 dark:bg-slate-900/60"
        style={{ cursor: zoom > 1 ? 'grab' : 'crosshair' }}
        onWheel={handleWheel}
        onClick={handleClick}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerLeave}
        onDoubleClick={handleDoubleClick}
      >
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

        {/* Zoom indicator */}
        {zoom !== 1 && (
          <div className="absolute left-2 top-2 z-20 rounded-full bg-slate-900/60 px-2 py-0.5 text-[10px] text-slate-100 backdrop-blur-sm">
            {Math.round(zoom * 100)}%
          </div>
        )}

      {/* Inner wrapper — positioned by zoom/pan transform */}
      <div
        className="absolute inset-0 flex items-center justify-center"
        style={{
          transformOrigin: '0 0',
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          pointerEvents: 'none',
        }}
      >
        {/* Image + SVG wrapper — explicitly sized to fitted image dimensions
            so SVG overlay shares the exact same bounding box as the image */}
        {fittedW > 0 && fittedH > 0 && (
          <div className="relative" style={{ width: fittedW, height: fittedH }}>
            <img
              ref={imgRef}
              src={displayUrl ?? undefined}
              alt={previewAltText}
              crossOrigin="anonymous"
              onLoad={handleImgLoad}
              className="block h-full w-full"
              style={replacePreviewLoading ? { opacity: 0.6 } : undefined}
              draggable={false}
            />

            {/* SVG contour overlays — raw pixel coordinate space */}
            {svgContours.length > 0 && previewPixelWidth && previewPixelHeight && (
              <svg
                viewBox={`0 0 ${previewPixelWidth} ${previewPixelHeight}`}
                className="pointer-events-none absolute inset-0 h-full w-full"
                style={{ zIndex: 5 }}
              >
                {svgContours.map(({ hex, polygons }, ti) =>
                  polygons.map((polygon, pi) => {
                    if (polygon.length < 3) return null;
                    const previewWidthMm = useConverterStore.getState().preview_width_mm;
                    if (!previewWidthMm || previewWidthMm <= 0) return null;
                    const pixelScale = previewWidthMm / previewPixelWidth;

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
            )}
          </div>
        )}

        {/* Fallback: show image while computing fit dimensions */}
        {(fittedW <= 0 || fittedH <= 0) && (
          <img
            ref={imgRef}
            src={displayUrl ?? undefined}
            alt={previewAltText}
            crossOrigin="anonymous"
            onLoad={handleImgLoad}
            className="max-h-full max-w-full"
            draggable={false}
          />
        )}
      </div>
      </div>
      {hoverInspectorOverlay}
    </>
  );
}
