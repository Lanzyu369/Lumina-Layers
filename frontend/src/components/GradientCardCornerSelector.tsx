import { useEffect, useRef, useState } from "react";

interface GradientCardCornerSelectorProps {
  title: string;
  hint: string;
  imageUrl: string | null;
  naturalWidth: number | null;
  naturalHeight: number | null;
  cornerPoints: Array<[number, number]>;
  emptyText: string;
  onSelectPoint: (point: [number, number]) => void;
  onImageLoad: (width: number, height: number) => void;
}

export default function GradientCardCornerSelector({
  title,
  hint,
  imageUrl,
  naturalWidth,
  naturalHeight,
  cornerPoints,
  emptyText,
  onSelectPoint,
  onImageLoad,
}: GradientCardCornerSelectorProps) {
  const imageRef = useRef<HTMLImageElement | null>(null);
  const [imageRect, setImageRect] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const updateRect = () => {
      const rect = imageRef.current?.getBoundingClientRect();
      if (!rect) {
        setImageRect({ width: 0, height: 0 });
        return;
      }
      setImageRect({ width: rect.width, height: rect.height });
    };
    updateRect();
    window.addEventListener("resize", updateRect);
    return () => window.removeEventListener("resize", updateRect);
  }, [imageUrl]);

  return (
    <section className="flex flex-col gap-3 rounded-3xl border border-slate-200/80 bg-slate-50/80 p-4 shadow-[var(--shadow-panel)] dark:border-slate-700/80 dark:bg-slate-900/70">
      <div className="flex flex-col gap-1">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-50">{title}</h3>
        <p className="text-xs text-slate-500 dark:text-slate-400">{hint}</p>
      </div>

      {!imageUrl ? (
        <div
          data-testid={`${title}-empty-state`}
          className="flex min-h-64 items-center justify-center rounded-2xl border border-dashed border-slate-300/80 bg-slate-50/80 px-4 text-center text-sm text-slate-500 dark:border-slate-700/80 dark:bg-slate-950/60 dark:text-slate-400"
        >
          {emptyText}
        </div>
      ) : (
        <div className="rounded-2xl border border-slate-200/80 bg-slate-50/60 p-3 dark:border-slate-700/80 dark:bg-slate-950/50">
          <div className="relative mx-auto w-full max-w-full">
            <img
              ref={imageRef}
              src={imageUrl}
              alt={title}
              className="block w-full rounded-xl object-contain"
              onLoad={(event) => {
                const target = event.currentTarget;
                onImageLoad(target.naturalWidth, target.naturalHeight);
                const rect = target.getBoundingClientRect();
                setImageRect({ width: rect.width, height: rect.height });
              }}
              onClick={(event) => {
                if (!naturalWidth || !naturalHeight || cornerPoints.length >= 4) {
                  return;
                }
                const rect = event.currentTarget.getBoundingClientRect();
                const x = Math.round(((event.clientX - rect.left) / rect.width) * naturalWidth);
                const y = Math.round(((event.clientY - rect.top) / rect.height) * naturalHeight);
                onSelectPoint([x, y]);
              }}
            />
            {naturalWidth && naturalHeight && imageRect.width > 0 && imageRect.height > 0
              ? cornerPoints.map(([x, y], index) => (
                  <span
                    key={`${title}-${index}-${x}-${y}`}
                    className="absolute flex h-7 w-7 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-slate-50 bg-slate-900 text-xs font-semibold text-slate-50 shadow-lg dark:border-slate-950 dark:bg-slate-100 dark:text-slate-900"
                    style={{
                      left: `${(x / naturalWidth) * 100}%`,
                      top: `${(y / naturalHeight) * 100}%`,
                    }}
                  >
                    {index + 1}
                  </span>
                ))
              : null}
          </div>
        </div>
      )}
    </section>
  );
}
