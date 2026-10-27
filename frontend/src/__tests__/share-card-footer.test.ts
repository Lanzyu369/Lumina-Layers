/**
 * Unit tests for share-card footer layout.
 * 分享卡页脚布局单元测试。
 *
 * Focus on the bug surfaced in code review: a narrow preview must not
 * produce a footer where the QR code or caption is clipped outside the
 * canvas. We exercise computeFooterLayout directly with a deterministic
 * synthetic text measurer.
 */

import { describe, expect, it } from "vitest";

import {
  MIN_COVER_WIDTH,
  computeFooterLayout,
} from "../recipe/shareCardFooter";

/** Synthetic measurer: each character is 0.6 × fontSize px wide. */
function syntheticMeasure(text: string, fontSize: number): number {
  return text.length * fontSize * 0.6;
}

describe("computeFooterLayout", () => {
  it("keeps QR fully inside the canvas at the minimum cover width", () => {
    const layout = computeFooterLayout(
      MIN_COVER_WIDTH,
      "Lumina 2.0 Import",
      syntheticMeasure,
    );

    // The footer always centers the QR; with width >= MIN_COVER_WIDTH the
    // QR must fit within [0, width].
    const qrLeft = Math.round((MIN_COVER_WIDTH - layout.qrSize) / 2);
    expect(qrLeft).toBeGreaterThanOrEqual(0);
    expect(qrLeft + layout.qrSize).toBeLessThanOrEqual(MIN_COVER_WIDTH);
  });

  it("scales QR proportionally for wide covers", () => {
    const narrow = computeFooterLayout(MIN_COVER_WIDTH, "Caption", syntheticMeasure);
    const wide = computeFooterLayout(800, "Caption", syntheticMeasure);

    expect(wide.qrSize).toBeGreaterThan(narrow.qrSize);
    // Wide cover: QR sized by ratio (~22% of width), not floored.
    expect(wide.qrSize).toBeGreaterThanOrEqual(Math.round(800 * 0.22) - 1);
  });

  it("shrinks the caption font instead of clipping when text is too wide", () => {
    const longCaption =
      "This is a very long English caption that should not fit on one line at base font";
    const layout = computeFooterLayout(MIN_COVER_WIDTH, longCaption, syntheticMeasure);

    const sideMargin = Math.max(8, Math.round(MIN_COVER_WIDTH * 0.04));
    const maxTextWidth = MIN_COVER_WIDTH - sideMargin * 2;

    // After shrink-to-fit + optional wrap, every line must fit the canvas.
    for (const line of layout.lines) {
      expect(syntheticMeasure(line, layout.fontSize)).toBeLessThanOrEqual(
        maxTextWidth + 1,
      );
    }
  });

  it("falls back to two lines when even the minimum font is too wide", () => {
    // Force a guaranteed wrap: huge token at the smallest font.
    const veryLong = "x".repeat(200);
    const layout = computeFooterLayout(MIN_COVER_WIDTH, veryLong, syntheticMeasure);

    // At most two lines; second line non-empty if wrapped.
    expect(layout.lines.length).toBeLessThanOrEqual(2);
    expect(layout.lines.join("")).toBe(veryLong);
  });

  it("wraps Chinese captions at character boundaries", () => {
    const chinese = "Lumina 2.0 可直接导入本图片生成可直接导入本图片生成可直接导入本图片生成";
    const layout = computeFooterLayout(MIN_COVER_WIDTH, chinese, syntheticMeasure);

    // The full caption must round-trip through any wrap.
    expect(layout.lines.join("")).toBe(chinese);
  });

  it("returns a positive footer height that scales with line count", () => {
    const oneLiner = computeFooterLayout(MIN_COVER_WIDTH, "Short", syntheticMeasure);
    const twoLiner = computeFooterLayout(
      MIN_COVER_WIDTH,
      "x".repeat(400),
      syntheticMeasure,
    );

    expect(oneLiner.height).toBeGreaterThan(0);
    expect(twoLiner.height).toBeGreaterThan(oneLiner.height);
  });
});
