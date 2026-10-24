/**
 * headerNavLayout - Layout rules for the two-level top navigation.
 * 顶部两级导航的布局规则。
 *
 * The header row holds the brand, the primary tabs and the tool buttons.
 * When the row gets tight the brand title collapses to the logo whenever
 * that gives the tabs the room they need, before the tabs leave their place;
 * centered tabs leave the window axis only as far as the brand and the tools
 * require; only when the tabs no longer fit between the logo and the tools
 * do they move to a row of their own. The tabs never overlap, truncate or
 * stretch.
 * 顶栏一行放标题、主导航和工具按钮。空间变紧时，只要收起标题文字能给主导航腾出所需
 * 空间，就先收成只剩标志，再考虑移动主导航；居中时主导航在不碰到两侧的前提下尽量
 * 靠近窗口中线；只有标志和工具按钮之间也放不下时，主导航才移到下一行。主导航不
 * 重叠、不截断、不拉伸。
 */
import type { HeaderNavAlignment } from "../../stores/settingsStore";

export interface HeaderNavMeasurements {
  /** Header content width without horizontal padding. 去掉左右内边距后的顶栏宽度。 */
  availableWidth: number;
  /** Logo width; the brand never gets narrower. 标志宽度，标题区最窄时只剩标志。 */
  logoWidth: number;
  /**
   * Natural width of the brand title including its gap to the logo, also
   * while collapsed; 0 when a breakpoint already hides it.
   * 标题文字（含与标志的间距）的自然宽度，收起时同样有效；断点已隐藏时为 0。
   */
  brandTitleWidth: number;
  primaryTabsWidth: number;
  toolsWidth: number;
  columnGap: number;
}

/**
 * Closest the primary tabs' centre line may come to each side of the header
 * content box while the tabs share the row with the brand and the tools.
 * 主导航与标题、工具按钮同处一行时，其中线距顶栏内容区两侧的最小距离。
 */
export interface CenterLineClearance {
  brandSidePx: number;
  toolsSidePx: number;
}

export interface HeaderNavFit {
  /** Brand, primary tabs and tools share one row. 标题、主导航和工具按钮在同一行。 */
  singleRow: boolean;
  centerOffsetPx?: number;
  paddingLeft?: number;
  paddingRight?: number;
  /** The brand title is shown next to the logo. 标志旁显示标题文字。 */
  showBrandTitle: boolean;
  /**
   * Distance from the header's left edge to the primary tabs; the
   * left-aligned sub-tab row starts at the same offset.
   * 顶栏左边缘到主导航的距离；居左时子导航从同一位置开始。
   */
  primaryTabsInsetPx: number;
  /** Set only for centered tabs on the shared row. 仅在居中且同处一行时有值。 */
  centerLineClearance: CenterLineClearance | null;
}

interface SingleRowCandidate {
  showBrandTitle: boolean;
  brandWidth: number;
  requiredWidth: number;
}

function centeredRowWidth(brandWidth: number, m: HeaderNavMeasurements, offset: number): number {
  return m.primaryTabsWidth + 2 * (Math.max(brandWidth - offset, m.toolsWidth + offset) + m.columnGap);
}

function sideBySideRowWidth(brandWidth: number, m: HeaderNavMeasurements): number {
  return brandWidth + m.primaryTabsWidth + m.toolsWidth + 2 * m.columnGap;
}

function singleRowCandidates(
  alignment: HeaderNavAlignment,
  m: HeaderNavMeasurements,
  offset: number,
): SingleRowCandidate[] {
  const fullBrandWidth = m.logoWidth + m.brandTitleWidth;
  const withTitle = { showBrandTitle: true, brandWidth: fullBrandWidth };
  const logoOnly = { showBrandTitle: false, brandWidth: m.logoWidth };
  if (alignment === "center") {
    // Hiding the title only helps when the brand is the tighter side, so
    // tabs leave the axis with the title still shown before it collapses.
    return [
      { ...withTitle, requiredWidth: centeredRowWidth(fullBrandWidth, m, offset) },
      { ...logoOnly, requiredWidth: centeredRowWidth(m.logoWidth, m, offset) },
      { ...withTitle, requiredWidth: sideBySideRowWidth(fullBrandWidth, m) },
      { ...logoOnly, requiredWidth: sideBySideRowWidth(m.logoWidth, m) },
    ];
  }
  return [
    { ...withTitle, requiredWidth: sideBySideRowWidth(fullBrandWidth, m) },
    { ...logoOnly, requiredWidth: sideBySideRowWidth(m.logoWidth, m) },
  ];
}

/**
 * Pick the first single-row layout that fits; otherwise the primary tabs
 * take a new row.
 * 选出第一个放得下的单行布局；都放不下时主导航移到下一行。
 */
export function resolveHeaderNavFit(
  alignment: HeaderNavAlignment,
  measurements: HeaderNavMeasurements,
  paddingLeft: number,
  paddingRight: number = paddingLeft,
): HeaderNavFit {
  const centerOffsetPx = (paddingRight - paddingLeft) / 2;
  const geometry = { centerOffsetPx, paddingLeft, paddingRight };
  const candidate = singleRowCandidates(alignment, measurements, centerOffsetPx).find(
    ({ requiredWidth }) => measurements.availableWidth >= requiredWidth,
  );
  if (!candidate) {
    return {
      ...geometry,
      singleRow: false,
      showBrandTitle: true,
      primaryTabsInsetPx: Math.round(paddingLeft),
      centerLineClearance: null,
    };
  }
  const brandSide = candidate.brandWidth + measurements.columnGap;
  const toolsSide = measurements.toolsWidth + measurements.columnGap;
  const halfTabs = measurements.primaryTabsWidth / 2;
  return {
    ...geometry,
    singleRow: true,
    showBrandTitle: candidate.showBrandTitle,
    primaryTabsInsetPx: Math.round(paddingLeft + (alignment === "left" ? brandSide : 0)),
    centerLineClearance:
      alignment === "center"
        ? { brandSidePx: brandSide + halfTabs, toolsSidePx: toolsSide + halfTabs }
        : null,
  };
}

/**
 * Shift inside the primary tabs' cell, which spans from the brand to the
 * tools, that puts the tabs on the header axis. The cell's spacers stop the
 * tabs at the cell edge when one side lacks room.
 * 主导航所在格子位于标题和工具按钮之间；返回让主导航落在顶栏中线上所需的偏移。
 * 某侧空间不足时，格子两侧的占位会让主导航停在格子边缘。
 */
export function primaryTabsCellShift(fit: HeaderNavFit): string {
  const clearance = fit.centerLineClearance;
  if (!clearance) {
    return `${fit.centerOffsetPx ?? 0}px`;
  }
  return `${(clearance.toolsSidePx - clearance.brandSidePx) / 2 + (fit.centerOffsetPx ?? 0)}px`;
}

/**
 * Shift of the sub tabs from their row's axis that keeps them on the primary
 * tabs' centre line. Percentages resolve against the sub-tab row, which has
 * the header's width and padding, so the browser keeps the value current
 * while the window resizes.
 * 子导航相对所在行中线的偏移，使两行共用同一条中线。百分比相对与顶栏同宽、同内边距
 * 的子导航行解析，窗口缩放时由浏览器实时计算。
 */
export function subTabsCenterShift(fit: HeaderNavFit): string {
  const clearance = fit.centerLineClearance;
  if (!clearance) {
    return `${fit.centerOffsetPx ?? 0}px`;
  }
  return `clamp(${clearance.brandSidePx}px - 50%, ${fit.centerOffsetPx ?? 0}px, 50% - ${clearance.toolsSidePx}px)`;
}

/** Brand, flexible primary-tab cell, tools. 标题、可伸缩的主导航格子、工具按钮。 */
export const HEADER_NAV_GRID_CLASS = "grid-cols-[auto_minmax(0,1fr)_auto]";

const NAV_ROW_JUSTIFY: Record<HeaderNavAlignment, string> = {
  center: "justify-center",
  left: "justify-start",
};

export function primaryTabsCellClass(
  alignment: HeaderNavAlignment,
  singleRow: boolean,
): string {
  const placement = singleRow
    ? "col-start-2 row-start-1"
    : "col-span-3 row-start-2";
  return `flex min-w-0 ${placement} ${NAV_ROW_JUSTIFY[alignment]}`;
}

export function subTabRowJustifyClass(alignment: HeaderNavAlignment): string {
  return NAV_ROW_JUSTIFY[alignment];
}
