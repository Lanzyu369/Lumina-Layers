import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { CanvasPreviewSurfaceViewport } from '../ui/CanvasPreviewSurface';
import { buildSelectionOutlineGeometry, SelectionOutlineRenderer } from './selectionOutlineRenderer';

interface Props {
  contours: Array<{ polygons: number[][][] }>;
  pixelWidth: number;
  pixelHeight: number;
  contourWidth: number;
  viewport: CanvasPreviewSurfaceViewport;
  fallback: ReactNode;
}

/** Animate cached stroke geometry without rasterizing SVG paths every frame.
 * 直接绘制缓存描边数据，避免每帧重新光栅化 SVG 轮廓。
 */
export default function SelectionOutlineOverlay(props: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<SelectionOutlineRenderer | null>(null);
  const latestPropsRef = useRef(props);
  const [gpuReady, setGpuReady] = useState(false);
  const reducedMotionRef = useRef(false);
  const geometry = useMemo(() => buildSelectionOutlineGeometry(
    props.contours, props.contourWidth / props.pixelWidth, props.pixelHeight,
  ), [props.contours, props.contourWidth, props.pixelWidth, props.pixelHeight]);

  useLayoutEffect(() => {
    latestPropsRef.current = props;
  });

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const gl = canvas.getContext('webgl', { alpha: true, antialias: false, premultipliedAlpha: true });
    const renderer = gl ? SelectionOutlineRenderer.create(gl) : null;
    if (!renderer) {
      setGpuReady(false);
      return;
    }
    rendererRef.current = renderer;
    setGpuReady(true);
    const onContextLost = (event: Event) => {
      event.preventDefault();
      rendererRef.current?.dispose();
      rendererRef.current = null;
      setGpuReady(false);
    };
    const onContextRestored = () => {
      const restored = SelectionOutlineRenderer.create(gl!);
      rendererRef.current = restored;
      setGpuReady(Boolean(restored));
    };
    canvas.addEventListener('webglcontextlost', onContextLost);
    canvas.addEventListener('webglcontextrestored', onContextRestored);
    return () => {
      canvas.removeEventListener('webglcontextlost', onContextLost);
      canvas.removeEventListener('webglcontextrestored', onContextRestored);
      rendererRef.current?.dispose();
      rendererRef.current = null;
      // StrictMode and hot refresh replay effects on the same mounted canvas.
      // Release its context only after the canvas has actually left the DOM.
      queueMicrotask(() => {
        if (!canvas.isConnected) gl?.getExtension('WEBGL_lose_context')?.loseContext();
      });
    };
  }, []);

  useLayoutEffect(() => {
    if (!gpuReady) return;
    rendererRef.current?.setGeometry(geometry);
  }, [geometry, gpuReady]);

  const drawLatestFrame = useCallback((time: number) => {
    const canvas = canvasRef.current;
    const renderer = rendererRef.current;
    if (!canvas || !renderer) return;
    const { viewport, pixelWidth, pixelHeight } = latestPropsRef.current;
    const { width, height } = viewport.containerSize;
    const dpr = window.devicePixelRatio || 1;
    const bufferWidth = Math.max(1, Math.round(width * dpr));
    const bufferHeight = Math.max(1, Math.round(height * dpr));
    if (canvas.width !== bufferWidth) canvas.width = bufferWidth;
    if (canvas.height !== bufferHeight) canvas.height = bufferHeight;
    renderer.draw(viewport.imageScreenRect, pixelWidth, pixelHeight, width, height,
      bufferWidth, bufferHeight, reducedMotionRef.current ? 0 : time);
  }, []);

  // Draw viewport changes before paint so the outline never trails the image
  // by a frame while dragging. The independent clock handles stationary ants.
  useLayoutEffect(() => {
    if (gpuReady) drawLatestFrame(performance.now());
  }, [props.viewport, geometry, gpuReady, drawLatestFrame]);

  useEffect(() => {
    if (!gpuReady) return;
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const updateMotion = () => { reducedMotionRef.current = media.matches; };
    updateMotion();
    media.addEventListener('change', updateMotion);
    let frame = 0;
    const draw = (time: number) => {
      if (!rendererRef.current) return;
      drawLatestFrame(time);
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      media.removeEventListener('change', updateMotion);
    };
  }, [gpuReady, drawLatestFrame]);

  return (
    <>
      <canvas
        ref={canvasRef}
        data-testid="selection-outline-gpu"
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 h-full w-full"
        style={{ visibility: gpuReady ? 'visible' : 'hidden' }}
      />
      {!gpuReady && props.fallback}
    </>
  );
}
