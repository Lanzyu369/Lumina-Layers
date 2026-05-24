/**
 * Share card footer rendering: QR code + caption appended below the preview.
 * 分享卡底部装饰：在预览图下方渲染二维码 + 说明文字。
 */

import QRCode from "qrcode";
import { tRuntime } from "../i18n/runtime";

/** Wiki URL the QR code points to. */
export const SHARE_CARD_WIKI_URL = "https://wiki.luminastudio.com.cn/";

/** Translation key for the caption shown below the QR code. */
export const SHARE_CARD_CAPTION_KEY = "share_card_footer_caption";

/**
 * Layout metrics (proportional to the cover width) used by the footer.
 * 布局参数（相对于封面宽度的比例）。
 */
const QR_SIZE_RATIO = 0.22;
const QR_TOP_GAP_RATIO = 0.03;
const QR_BOTTOM_GAP_RATIO = 0.025;
const CAPTION_FONT_RATIO = 0.034;
const CAPTION_BOTTOM_GAP_RATIO = 0.035;

/** Minimum sizes (px) so very small previews still produce a readable footer. */
const MIN_QR_SIZE_PX = 96;
const MIN_FONT_PX = 14;

export interface ShareCardFooterMetrics {
  /** Total footer height to add below the preview, in pixels. */
  height: number;
  /** Computed QR size in pixels. */
  qrSize: number;
  /** Computed caption font size in pixels. */
  fontSize: number;
}

/**
 * Compute footer metrics for a given cover width. Returns the footer height
 * that must be reserved below the preview image.
 * 根据封面宽度计算页脚尺寸（包括二维码和文字所需的高度）。
 */
export function computeFooterMetrics(width: number): ShareCardFooterMetrics {
  const qrSize = Math.max(MIN_QR_SIZE_PX, Math.round(width * QR_SIZE_RATIO));
  const fontSize = Math.max(MIN_FONT_PX, Math.round(width * CAPTION_FONT_RATIO));
  const topGap = Math.round(width * QR_TOP_GAP_RATIO);
  const qrToCaptionGap = Math.round(width * QR_BOTTOM_GAP_RATIO);
  const bottomGap = Math.round(width * CAPTION_BOTTOM_GAP_RATIO);
  // Caption is single-line; reserve roughly 1.4 line height
  const captionBlock = Math.round(fontSize * 1.4);
  const height = topGap + qrSize + qrToCaptionGap + captionBlock + bottomGap;
  return { height, qrSize, fontSize };
}

/**
 * Render the QR code into an offscreen canvas using the qrcode browser API.
 * 使用 qrcode 浏览器接口将二维码渲染到离屏画布。
 *
 * @param url - URL or text encoded into the QR code.
 * @param size - Side length of the QR canvas in pixels.
 */
async function renderQrCanvas(url: string, size: number): Promise<HTMLCanvasElement> {
  const canvas = document.createElement("canvas");
  await QRCode.toCanvas(canvas, url, {
    width: size,
    margin: 1,
    errorCorrectionLevel: "M",
    color: {
      dark: "#000000",
      light: "#FFFFFF",
    },
  });
  return canvas;
}

/**
 * Draw the share card footer (QR code + caption) onto the destination canvas.
 *
 * The footer is drawn starting at `topY` and occupies the full width of the
 * destination canvas. Background is filled white to keep the footer legible
 * regardless of the preview's transparency.
 *
 * 在目标画布上绘制分享卡底部（二维码 + 文字）。
 *
 * @param ctx - Destination 2D context.
 * @param width - Width of the destination canvas (footer occupies full width).
 * @param topY - Y coordinate where the footer begins.
 * @param metrics - Pre-computed footer metrics for this width.
 * @param caption - Caption text rendered below the QR code.
 */
export async function drawShareCardFooter(
  ctx: CanvasRenderingContext2D,
  width: number,
  topY: number,
  metrics: ShareCardFooterMetrics,
  caption: string,
): Promise<void> {
  // Fill footer background white so caption/QR have a clean canvas.
  ctx.fillStyle = "#FFFFFF";
  ctx.fillRect(0, topY, width, metrics.height);

  // QR code, centered horizontally.
  const qrCanvas = await renderQrCanvas(SHARE_CARD_WIKI_URL, metrics.qrSize);
  const qrX = Math.round((width - metrics.qrSize) / 2);
  const qrY = topY + Math.round(width * QR_TOP_GAP_RATIO);
  ctx.drawImage(qrCanvas, qrX, qrY, metrics.qrSize, metrics.qrSize);

  // Caption, centered below the QR.
  const captionY = qrY + metrics.qrSize + Math.round(width * QR_BOTTOM_GAP_RATIO);
  ctx.fillStyle = "#111111";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  // System sans-serif stack covers both Latin and CJK glyphs reliably.
  ctx.font =
    `${metrics.fontSize}px -apple-system, "Segoe UI", "PingFang SC", ` +
    `"Microsoft YaHei", "Hiragino Sans GB", sans-serif`;
  ctx.fillText(caption, Math.round(width / 2), captionY);
}

/**
 * Resolve the localized caption string from the i18n runtime.
 * 从 i18n 运行时解析当前语言下的说明文字。
 */
export function getFooterCaption(): string {
  return tRuntime(SHARE_CARD_CAPTION_KEY);
}
