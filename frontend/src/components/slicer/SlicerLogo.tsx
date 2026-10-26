import { useState } from "react";

import {
  getSlicerLogoSource,
  resolveSlicerBrandingId,
} from "../../utils/slicerBranding";
import { cx } from "../ui/panelPrimitives";

export interface SlicerLogoProps {
  slicerId: string;
  variant?: "surface" | "onBrand";
  loading?: boolean;
  className?: string;
}

export default function SlicerLogo({
  slicerId,
  variant = "surface",
  loading = false,
  className,
}: SlicerLogoProps) {
  const brandingId = resolveSlicerBrandingId(slicerId);
  const logoSource = getSlicerLogoSource(slicerId);
  const [failedSource, setFailedSource] = useState<string | null>(null);
  const showImage = Boolean(logoSource && failedSource !== logoSource);

  return (
    <span
      aria-hidden="true"
      data-testid={`slicer-logo-${brandingId || "unknown"}`}
      className={cx(
        "inline-flex h-7 w-7 shrink-0 items-center justify-center overflow-hidden rounded-lg border",
        variant === "onBrand"
          ? "border-white/45 bg-white/90 shadow-sm"
          : "border-slate-200/80 bg-slate-50/95 shadow-sm dark:border-slate-600/80 dark:bg-slate-800/95",
        className,
      )}
    >
      {loading ? (
        <svg
          data-testid="slicer-logo-spinner"
          className="h-4 w-4 animate-spin text-slate-600"
          viewBox="0 0 24 24"
          fill="none"
        >
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
          />
        </svg>
      ) : showImage && logoSource ? (
        <img
          data-testid="slicer-logo-image"
          src={logoSource}
          alt=""
          role="presentation"
          className="h-5 w-5 object-contain"
          onError={() => setFailedSource(logoSource)}
        />
      ) : (
        <svg
          data-testid="slicer-logo-fallback"
          className={cx(
            "h-5 w-5",
            variant === "onBrand" ? "text-slate-700" : "text-slate-500 dark:text-slate-300",
          )}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="m12 3 8 4.5-8 4.5-8-4.5L12 3Z" />
          <path d="m4 12 8 4.5 8-4.5" />
          <path d="m4 16.5 8 4.5 8-4.5" />
        </svg>
      )}
    </span>
  );
}
