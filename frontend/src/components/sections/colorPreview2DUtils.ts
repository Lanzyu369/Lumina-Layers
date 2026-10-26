import {
  mapPixelToBufferCoordinate,
  rgbToHex,
  type PreviewCanvasBuffer,
} from '../ui/previewHoverInspectorUtils';

interface PreviewPixelReadOptions {
  pixelX: number;
  pixelY: number;
  naturalWidth: number;
  naturalHeight: number;
}

/**
 * Read the color of a preview pixel from the shared preview buffer.
 * 通过共享预览缓冲区读取预览像素颜色。
 *
 * @param previewBuffer - Shared preview canvas buffer.
 * @param options - Pixel coordinate and natural image size information.
 * @returns Hex string without '#' (e.g. "FF0000"), or null on failure.
 */
export function readPixelColor(
  previewBuffer: PreviewCanvasBuffer | null,
  options: PreviewPixelReadOptions,
): string | null {
  if (!previewBuffer) {
    return null;
  }

  const { pixelX, pixelY, naturalWidth, naturalHeight } = options;
  if (naturalWidth <= 0 || naturalHeight <= 0) {
    return null;
  }

  try {
    const x = mapPixelToBufferCoordinate(pixelX, naturalWidth, previewBuffer.width);
    const y = mapPixelToBufferCoordinate(pixelY, naturalHeight, previewBuffer.height);
    const rgba = previewBuffer.context.getImageData(x, y, 1, 1).data;
    return rgba[3] <= 8 ? null : rgbToHex(rgba[0], rgba[1], rgba[2]);
  } catch {
    return null;
  }
}
