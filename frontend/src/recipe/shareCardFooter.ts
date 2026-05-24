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
 * Minimum footer width (px) below which QR and caption do not fit.
 * `buildCoverImage` pads narrow previews to this width to avoid clipping.
 * 最小页脚宽度（px）：低于此宽度无法容纳二维码和文字。
 * `buildCoverImage` 会在预览图较窄时把封面横向补白到这个宽度，避免内容被裁切。
 */
export const MIN_COVER_WIDTH = 360;

/**
 * Layout metrics (proportional to the cover width) used by the footer.
 * 布局参数（相对于封面宽度的比例）。
 */
const QR_SIZE_RATIO = 0.22;
const QR_TOP_GAP_RATIO = 0.03;
const QR_BOTTOM_GAP_RATIO = 0.025;
const CAPTION_FONT_RATIO = 0.034;
const CAPTION_BOTTOM_GAP_RATIO = 0.035;
const CAPTION_SIDE_MARGIN_RATIO = 0.04;
const CAPTION_LINE_HEIGHT = 1.4;

/** Minimum and maximum sizes (px) for footer elements. */
const MIN_QR_SIZE_PX = 96;
const MIN_FONT_PX = 12;
const BASE_FONT_FLOOR_PX = 14;

const FONT_STACK =
  '-apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", ' +
  '"Hiragino Sans GB", sans-serif';

export interface ShareCardFooterLayout {
  /** Side length of the QR code in px. */
  qrSize: number;
  /** Final font size used for the caption in px. */
  fontSize: number;
  /** One or two pre-wrapped caption lines that fit within the footer width. */
  lines: string[];
  /** Total footer height in px (covers all gaps + QR + caption block). */
  height: number;
  /** Vertical gap above the QR code. */
  topGap: number;
  /** Vertical gap between the QR code and the first caption line. */
  qrToCaptionGap: number;
  /** Vertical gap below the last caption line. */
  bottomGap: number;
}

/**
 * Compute footer layout (sizes + wrapped caption) for a given cover width.
 *
 * The caller supplies a measurement function that reports the rendered width
 * of `text` at a given font size. Browser canvas contexts satisfy this via
 * `ctx.measureText`. Tests/Node environments can pass a synthetic measurer.
 *
 * 计算页脚布局（尺寸 + 折行后的文字）。`measureText` 由调用方注入，浏览器
 * 直接使用 canvas context 的 `measureText`；测试可注入合成的实现。
 */
export function computeFooterLayout(
  width: number,
  caption: string,
  measureText: (text: string, fontSize: number) => number,
): ShareCardFooterLayout {
  const qrSize = Math.max(MIN_QR_SIZE_PX, Math.round(width * QR_SIZE_RATIO));
  const baseFontSize = Math.max(
    BASE_FONT_FLOOR_PX,
    Math.round(width * CAPTION_FONT_RATIO),
  );
  const sideMargin = Math.max(8, Math.round(width * CAPTION_SIDE_MARGIN_RATIO));
  const maxTextWidth = Math.max(1, width - sideMargin * 2);

  // 1) Try single line at base font size.
  let fontSize = baseFontSize;
  let lines = [caption];
  let measured = measureText(caption, fontSize);

  // 2) Shrink-to-fit, floor at MIN_FONT_PX.
  if (measured > maxTextWidth) {
    const scaled = Math.max(
      MIN_FONT_PX,
      Math.floor(baseFontSize * (maxTextWidth / measured)),
    );
    fontSize = scaled;
    measured = measureText(caption, fontSize);
  }

  // 3) Still too wide at floor: wrap into at most two lines.
  if (measured > maxTextWidth) {
    lines = wrapToTwoLines(caption, maxTextWidth, (text) =>
      measureText(text, fontSize),
    );
  }

  const topGap = Math.round(width * QR_TOP_GAP_RATIO);
  const qrToCaptionGap = Math.round(width * QR_BOTTOM_GAP_RATIO);
  const bottomGap = Math.round(width * CAPTION_BOTTOM_GAP_RATIO);
  const captionBlock = Math.round(fontSize * CAPTION_LINE_HEIGHT * lines.length);
  const height = topGap + qrSize + qrToCaptionGap + captionBlock + bottomGap;

  return {
    qrSize,
    fontSize,
    lines,
    height,
    topGap,
    qrToCaptionGap,
    bottomGap,
  };
}

/**
 * Wrap a caption into at most two lines. Splits at the latest whitespace
 * before the midpoint (works well for Latin captions); falls back to a
 * character-level split for languages without word boundaries (e.g. Chinese).
 *
 * 把文字折成最多两行：英文优先按空格断；中文等无空格语言按字符中点断。
 */
function wrapToTwoLines(
  text: string,
  maxWidth: number,
  measure: (segment: string) => number,
): string[] {
  if (text.length < 2) return [text];

  // Prefer breaking at the rightmost whitespace whose left segment fits.
  const tokens = text.split(/\s+/).filter((token) => token.length > 0);
  if (tokens.length > 1) {
    let bestSplit = -1;
    for (let i = 1; i < tokens.length; i++) {
      const left = tokens.slice(0, i).join(" ");
      if (measure(left) <= maxWidth) {
        bestSplit = i;
      } else {
        break;
      }
    }
    if (bestSplit > 0) {
      return [
        tokens.slice(0, bestSplit).join(" "),
        tokens.slice(bestSplit).join(" "),
      ];
    }
  }

  // Character-level fallback (CJK or single long token).
  const chars = Array.from(text);
  let bestIdx = Math.floor(chars.length / 2);
  for (let i = chars.length - 1; i >= 1; i--) {
    if (measure(chars.slice(0, i).join("")) <= maxWidth) {
      bestIdx = i;
      break;
    }
  }
  return [chars.slice(0, bestIdx).join(""), chars.slice(bestIdx).join("")];
}

/**
 * Render the QR code into an offscreen canvas using the qrcode browser API.
 * 使用 qrcode 浏览器接口将二维码渲染到离屏画布。
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
 * Build a measurement function backed by a 2D canvas context.
 * 基于 canvas 2D 上下文构造文字测量函数。
 */
export function makeCanvasMeasurer(
  ctx: CanvasRenderingContext2D,
): (text: string, fontSize: number) => number {
  return (text, fontSize) => {
    ctx.font = `${fontSize}px ${FONT_STACK}`;
    return ctx.measureText(text).width;
  };
}

/**
 * Draw the share card footer (QR code + caption) onto the destination canvas.
 *
 * The footer occupies `[0, topY] .. [width, topY + layout.height]`. Background
 * is filled white so the QR/caption stay legible even if the preview above is
 * transparent. QR is horizontally centered; caption lines are centered too.
 *
 * 在目标画布上绘制分享卡底部（二维码 + 文字）。背景填白，QR 与文字居中。
 *
 * @param ctx - Destination 2D context.
 * @param width - Width of the destination canvas (footer occupies full width).
 * @param topY - Y coordinate where the footer begins.
 * @param layout - Pre-computed layout from `computeFooterLayout`.
 */
export async function drawShareCardFooter(
  ctx: CanvasRenderingContext2D,
  width: number,
  topY: number,
  layout: ShareCardFooterLayout,
): Promise<void> {
  ctx.fillStyle = "#FFFFFF";
  ctx.fillRect(0, topY, width, layout.height);

  const qrCanvas = await renderQrCanvas(SHARE_CARD_WIKI_URL, layout.qrSize);
  const qrX = Math.round((width - layout.qrSize) / 2);
  const qrY = topY + layout.topGap;
  ctx.drawImage(qrCanvas, qrX, qrY, layout.qrSize, layout.qrSize);

  ctx.fillStyle = "#111111";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.font = `${layout.fontSize}px ${FONT_STACK}`;

  const lineHeight = layout.fontSize * CAPTION_LINE_HEIGHT;
  let captionY = qrY + layout.qrSize + layout.qrToCaptionGap;
  const centerX = Math.round(width / 2);
  for (const line of layout.lines) {
    ctx.fillText(line, centerX, captionY);
    captionY += lineHeight;
  }
}

/**
 * Resolve the localized caption string from the i18n runtime.
 * 从 i18n 运行时解析当前语言下的说明文字。
 */
export function getFooterCaption(): string {
  return tRuntime(SHARE_CARD_CAPTION_KEY);
}
