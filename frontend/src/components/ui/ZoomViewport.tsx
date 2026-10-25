import { useRef, useEffect, type MouseEvent, type ReactNode } from "react";
import { wheelZoomDelta } from "../../utils/wheelZoom";

interface ZoomViewportProps {
  src?: string;
  alt?: string;
  scale: number;
  translate: { x: number; y: number };
  zoom: (mouseX: number, mouseY: number, deltaY: number) => void;
  mouseHandlers: {
    onMouseDown: (e: MouseEvent<HTMLDivElement>) => void;
    onMouseMove: (e: MouseEvent<HTMLDivElement>) => void;
    onMouseUp: () => void;
    onMouseLeave: () => void;
  };
  height?: number;
  children?: ReactNode;
}

export default function ZoomViewport({
  src,
  alt = "",
  scale,
  translate,
  zoom,
  mouseHandlers,
  height = 400,
  children,
}: ZoomViewportProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const rect = el.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      zoomRef.current(mouseX, mouseY, wheelZoomDelta(e.deltaY, e.deltaMode, rect.height));
    };
    el.addEventListener("wheel", handler, { passive: false });
    return () => el.removeEventListener("wheel", handler);
  }, []);

  const transformStyle = {
    transform: `translate(${translate.x}px, ${translate.y}px) scale(${scale})`,
    transformOrigin: "0 0",
  };

  return (
    <div
      ref={containerRef}
      className="relative w-full overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 cursor-grab active:cursor-grabbing select-none"
      style={{ height }}
      {...mouseHandlers}
    >
      {src && (
        <img
          src={src}
          alt={alt}
          draggable={false}
          className="absolute top-0 left-0 w-full h-full object-contain pointer-events-none"
          style={transformStyle}
        />
      )}
      {children}
    </div>
  );
}
