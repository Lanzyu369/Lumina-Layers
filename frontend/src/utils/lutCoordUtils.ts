/**
 * Coordinate mapping utilities for LUT preview image click handling.
 * LUT 预览图点击坐标映射工具函数。
 */

/** Rendered image rect within an object-contain element (excluding letterbox). */
/** object-contain 模式下图像实际渲染区域（不含 letterbox 留白） */
export interface RenderedImageRect {
  offsetX: number;   // Image content left offset relative to element edge. (图像内容左边距)
  offsetY: number;   // Image content top offset relative to element edge. (图像内容上边距)
  width: number;     // Rendered image width in pixels. (图像内容渲染宽度)
  height: number;    // Rendered image height in pixels. (图像内容渲染高度)
}

/**
 * Compute the actual rendered rect of an image in object-contain mode.
 * 计算 object-contain 模式下图像的实际渲染区域。
 *
 * Pure function with no side effects. When naturalWidth or naturalHeight
 * is zero, returns a zero-size rect to avoid division by zero.
 * 纯函数，无副作用。当 naturalWidth 或 naturalHeight 为 0 时返回零尺寸区域。
 *
 * @param naturalWidth - Intrinsic image width in pixels. (图像原始宽度)
 * @param naturalHeight - Intrinsic image height in pixels. (图像原始高度)
 * @param clientWidth - Element client width in pixels. (元素客户端宽度)
 * @param clientHeight - Element client height in pixels. (元素客户端高度)
 * @returns Rendered image rect with offset and dimensions. (渲染区域的偏移和尺寸)
 */
export function getObjectFitRect(
  naturalWidth: number,
  naturalHeight: number,
  clientWidth: number,
  clientHeight: number,
): RenderedImageRect {
  if (naturalWidth <= 0 || naturalHeight <= 0 || clientWidth <= 0 || clientHeight <= 0) {
    return { offsetX: 0, offsetY: 0, width: 0, height: 0 };
  }

  const ratio = Math.min(clientWidth / naturalWidth, clientHeight / naturalHeight);
  const width = Math.min(naturalWidth * ratio, clientWidth);
  const height = Math.min(naturalHeight * ratio, clientHeight);
  const offsetX = (clientWidth - width) / 2;
  const offsetY = (clientHeight - height) / 2;

  return { offsetX, offsetY, width, height };
}
