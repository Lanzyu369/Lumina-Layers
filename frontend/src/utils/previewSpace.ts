export interface PreviewSpaceBounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
  maxZ: number;
}

export interface PreviewSpacePoint {
  x: number;
  y: number;
}

export interface PreviewSpace {
  assetBounds: PreviewSpaceBounds;
  displayBounds: PreviewSpaceBounds;
  center: PreviewSpacePoint;
  scaleX: number;
  scaleY: number;
  /** Translation paired with the Three.js asset-group scale. / 与 Three.js 资产组缩放配套的平移。 */
  assetGroupPosition: PreviewSpacePoint;
  /** Convert an asset-local point into current display millimetres. / 将资产局部点转换为当前显示毫米坐标。 */
  toDisplayPoint: (point: PreviewSpacePoint) => PreviewSpacePoint;
  /** Convert current display millimetres into asset-local coordinates. / 将当前显示毫米坐标转换为资产局部坐标。 */
  toAssetPoint: (point: PreviewSpacePoint) => PreviewSpacePoint;
  /** Convert a display-space drag delta into an asset-space delta. / 将显示空间拖拽增量转换为资产空间增量。 */
  displayDeltaToAsset: (delta: PreviewSpacePoint) => PreviewSpacePoint;
}

function safeScale(value: number): number {
  return Number.isFinite(value) && value > 0 ? value : 1;
}

/**
 * Build the coordinate contract between one cached preview asset and its
 * current browser dimensions. Scaling is centred on the asset bounds so an
 * asymmetric footprint does not drift when dimensions change.
 *
 * 建立缓存预览资产与当前浏览器尺寸之间的坐标契约。缩放围绕资产边界中心
 * 进行，避免非对称轮廓在尺寸变化时漂移。
 */
export function createPreviewSpace(
  assetBounds: PreviewSpaceBounds,
  scaleX: number,
  scaleY: number,
): PreviewSpace {
  const resolvedScaleX = safeScale(scaleX);
  const resolvedScaleY = safeScale(scaleY);
  const center = {
    x: (assetBounds.minX + assetBounds.maxX) / 2,
    y: (assetBounds.minY + assetBounds.maxY) / 2,
  };
  const toDisplayPoint = (point: PreviewSpacePoint): PreviewSpacePoint => ({
    x: center.x + (point.x - center.x) * resolvedScaleX,
    y: center.y + (point.y - center.y) * resolvedScaleY,
  });
  const toAssetPoint = (point: PreviewSpacePoint): PreviewSpacePoint => ({
    x: center.x + (point.x - center.x) / resolvedScaleX,
    y: center.y + (point.y - center.y) / resolvedScaleY,
  });
  const min = toDisplayPoint({ x: assetBounds.minX, y: assetBounds.minY });
  const max = toDisplayPoint({ x: assetBounds.maxX, y: assetBounds.maxY });

  return {
    assetBounds,
    displayBounds: {
      minX: Math.min(min.x, max.x),
      maxX: Math.max(min.x, max.x),
      minY: Math.min(min.y, max.y),
      maxY: Math.max(min.y, max.y),
      maxZ: assetBounds.maxZ,
    },
    center,
    scaleX: resolvedScaleX,
    scaleY: resolvedScaleY,
    assetGroupPosition: {
      x: center.x * (1 - resolvedScaleX),
      y: center.y * (1 - resolvedScaleY),
    },
    toDisplayPoint,
    toAssetPoint,
    displayDeltaToAsset: (delta: PreviewSpacePoint): PreviewSpacePoint => ({
      x: delta.x / resolvedScaleX,
      y: delta.y / resolvedScaleY,
    }),
  };
}
