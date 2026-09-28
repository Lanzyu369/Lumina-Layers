import { useMemo } from "react";
import { Html, Line } from "@react-three/drei";
import {
  buildLargeFormatTileOverlayGeometry,
  type LargeFormatOverlayBounds,
} from "../utils/largeFormatTileLayout";

/** Dark halo under the cut line so it stays visible on light artwork. */
const TILE_OUTLINE_HALO_COLOR = "#0f172a";
/** Bright cut line so it stays visible on dark artwork. */
const TILE_OUTLINE_COLOR = "#f59e0b";
const TILE_OUTLINE_HALO_WIDTH_PX = 5;
const TILE_OUTLINE_WIDTH_PX = 3;
const TILE_OUTLINE_RENDER_ORDER = 990;

export interface LargeFormatTileOverlay3DProps {
  /** Artwork canvas bounds in display space; image top maps to maxY. */
  bounds: LargeFormatOverlayBounds;
  /** Height at which the outline floats above the model top. */
  z: number;
  totalWidthMm: number;
  totalHeightMm: number;
  tileWidthMm: number;
  tileHeightMm: number;
}

/**
 * Draw the large-format cut lines and tile labels over the preview model.
 * 在预览模型上方绘制大画幅切割线与分块标签，让用户看清作品会被如何切开。
 */
export default function LargeFormatTileOverlay3D({
  bounds,
  z,
  totalWidthMm,
  totalHeightMm,
  tileWidthMm,
  tileHeightMm,
}: LargeFormatTileOverlay3DProps) {
  const geometry = useMemo(
    () =>
      buildLargeFormatTileOverlayGeometry(
        bounds,
        totalWidthMm,
        totalHeightMm,
        tileWidthMm,
        tileHeightMm,
      ),
    [bounds, totalWidthMm, totalHeightMm, tileWidthMm, tileHeightMm],
  );
  const points = useMemo(
    () =>
      geometry
        ? geometry.segments.map(([x, y]) => [x, y, z] as [number, number, number])
        : [],
    [geometry, z],
  );

  if (!geometry || points.length === 0) {
    return null;
  }

  return (
    <group name="large-format-tile-overlay">
      <Line
        points={points}
        segments
        color={TILE_OUTLINE_HALO_COLOR}
        lineWidth={TILE_OUTLINE_HALO_WIDTH_PX}
        transparent
        opacity={0.55}
        depthTest={false}
        depthWrite={false}
        toneMapped={false}
        renderOrder={TILE_OUTLINE_RENDER_ORDER}
      />
      <Line
        points={points}
        segments
        color={TILE_OUTLINE_COLOR}
        lineWidth={TILE_OUTLINE_WIDTH_PX}
        depthTest={false}
        depthWrite={false}
        toneMapped={false}
        renderOrder={TILE_OUTLINE_RENDER_ORDER + 1}
      />
      {geometry.labels.map((anchor) => (
        <Html
          key={anchor.label}
          center
          position={[anchor.x, anchor.y, z]}
          zIndexRange={[20, 0]}
          style={{ pointerEvents: "none" }}
        >
          <span
            data-testid="large-format-tile-label"
            className="select-none whitespace-nowrap rounded-md bg-slate-900/75 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-amber-300 shadow-sm dark:bg-slate-950/80"
          >
            {anchor.label}
          </span>
        </Html>
      ))}
    </group>
  );
}
