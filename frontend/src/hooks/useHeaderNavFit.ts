import { useLayoutEffect, useState, type RefObject } from "react";
import { flushSync } from "react-dom";
import {
  resolveHeaderNavFit,
  type HeaderNavFit,
} from "../components/widget/headerNavLayout";
import type { HeaderNavAlignment } from "../stores/settingsStore";

export interface HeaderNavElements {
  /** Header whose padding and column gap are read. 读取内边距和列间距的顶栏。 */
  header: RefObject<HTMLElement | null>;
  /**
   * Zero-height element spanning the header's content box. It is observed
   * instead of the header because the header gets taller when the tabs wrap,
   * and a size change made inside the observer's own callback is reported as
   * a "ResizeObserver loop" error.
   * 横跨顶栏内容区、高度为 0 的元素。观察它而不是顶栏本身：主导航换行会让顶栏变高，
   * 在观察回调内部引起的尺寸变化会被浏览器报告为 ResizeObserver 循环错误。
   */
  contentWidthProbe: RefObject<HTMLElement | null>;
  brandLogo: RefObject<HTMLElement | null>;
  /** Title element that keeps its natural width while collapsed. 收起时仍保持自然宽度的标题元素。 */
  brandTitle: RefObject<HTMLElement | null>;
  primaryTabs: RefObject<HTMLElement | null>;
  tools: RefObject<HTMLElement | null>;
}

const INITIAL_FIT: HeaderNavFit = {
  singleRow: true,
  showBrandTitle: true,
  primaryTabsInsetPx: 0,
  centerLineClearance: null,
};

function readPixels(value: string): number {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function isSameFit(previous: HeaderNavFit, next: HeaderNavFit): boolean {
  return (
    previous.singleRow === next.singleRow &&
    previous.paddingLeft === next.paddingLeft &&
    previous.paddingRight === next.paddingRight &&
    previous.showBrandTitle === next.showBrandTitle &&
    previous.primaryTabsInsetPx === next.primaryTabsInsetPx &&
    previous.centerLineClearance?.brandSidePx === next.centerLineClearance?.brandSidePx &&
    previous.centerLineClearance?.toolsSidePx === next.centerLineClearance?.toolsSidePx
  );
}

/**
 * Measure how the brand, primary tabs and tools share the header row.
 * 测量标题、主导航和工具按钮如何共用顶栏一行。
 *
 * Every input is a natural width that the chosen layout does not change: the
 * logo and the title are measured separately, the title keeps its width
 * while collapsed, and the primary tab strip exposes its full content
 * through ``scrollWidth``. The result therefore never flips back and forth.
 * 所有输入都是不受所选布局影响的自然宽度：标志和标题分开测量，标题收起时宽度不变，
 * 主导航通过 scrollWidth 给出完整内容宽度，因此结果不会来回切换。
 */
export function useHeaderNavFit(
  alignment: HeaderNavAlignment,
  { header, contentWidthProbe, brandLogo, brandTitle, primaryTabs, tools }: HeaderNavElements,
): HeaderNavFit {
  const [fit, setFit] = useState<HeaderNavFit>(INITIAL_FIT);

  useLayoutEffect(() => {
    const headerElement = header.current;
    const probeElement = contentWidthProbe.current;
    const brandLogoElement = brandLogo.current;
    const brandTitleElement = brandTitle.current;
    const primaryTabsElement = primaryTabs.current;
    const toolsElement = tools.current;
    if (
      !headerElement ||
      !probeElement ||
      !brandLogoElement ||
      !brandTitleElement ||
      !primaryTabsElement ||
      !toolsElement
    ) {
      return;
    }

    const measure = () => {
      const style = window.getComputedStyle(headerElement);
      const next = resolveHeaderNavFit(
        alignment,
        {
          availableWidth: probeElement.getBoundingClientRect().width,
          logoWidth: brandLogoElement.getBoundingClientRect().width,
          brandTitleWidth: brandTitleElement.getBoundingClientRect().width,
          primaryTabsWidth: primaryTabsElement.scrollWidth,
          toolsWidth: toolsElement.getBoundingClientRect().width,
          columnGap: readPixels(style.columnGap),
        },
        readPixels(style.paddingLeft),
        readPixels(style.paddingRight),
      );
      setFit((previous) => (isSameFit(previous, next) ? previous : next));
    };

    measure();
    if (typeof ResizeObserver === "undefined") {
      return;
    }
    // Resize callbacks run before paint; committing synchronously keeps the
    // squeezed intermediate row from ever reaching the screen. The probe and
    // the tools keep their size across that commit; the deeper elements that
    // may change are delivered again within the same frame.
    const observer = new ResizeObserver(() => flushSync(measure));
    const observed = [
      probeElement,
      brandTitleElement,
      primaryTabsElement,
      toolsElement,
      primaryTabsElement.firstElementChild,
    ];
    for (const element of observed) {
      if (element) {
        observer.observe(element);
      }
    }
    return () => observer.disconnect();
  }, [alignment, header, contentWidthProbe, brandLogo, brandTitle, primaryTabs, tools]);

  return fit;
}
