/**
 * navTabStyles - Shared tab styles for the primary and secondary navigation.
 * 主导航与子导航共用的标签样式。
 *
 * Both rows use the same borderless tab: no track behind the group, and the
 * text; icon size and the divider between the rows carry the hierarchy.
 * 层级由图标大小和两行之间的分隔线表达。
 */
/**
 * The strip scrolls horizontally only when a narrow window cannot hold the
 * tabs, and never shows a scrollbar. It never grows wider than its row and
 * never yields width to sibling spacers. Scroll containers clip their
 * overshoot visible.
 * 窗口过窄时标签条可横向滚动，但不显示滚动条；宽度不超过所在行，也不会被两侧
 */
export const NAV_TAB_STRIP_CLASS =
  "scrollbar-hidden flex w-fit max-w-full shrink-0 items-center overflow-x-auto overflow-y-hidden p-1";

const NAV_TAB_BASE_CLASS =
  "relative z-10 shrink-0 rounded-lg outline-none transition-colors duration-200 focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]";

const NAV_TAB_INACTIVE_HOVER_CLASS = "hover:bg-[var(--nav-chip-hover)]";

export const NAV_TAB_INDICATOR_CLASS =

// Overshoot must stay inside the strip padding; a larger bounce gets clipped
// by the scroll container.
export const NAV_TAB_INDICATOR_TRANSITION = {
  type: "spring",
  bounce: 0.1,
  duration: 0.5,
} as const;

export const SECONDARY_NAV_TAB_ICON_CLASS =
  "flex items-center justify-center [&>svg]:h-3.5 [&>svg]:w-3.5";

function navTabSizeClass(compact: boolean): string {
  return compact ? "px-3 text-[13px]" : "px-3.5 text-sm";
}

export function primaryNavTabClass(isActive: boolean, compact: boolean): string {
  const tone = isActive
    ? NAV_TAB_ACTIVE_TEXT_CLASS
    : `text-slate-600 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 ${NAV_TAB_INACTIVE_HOVER_CLASS}`;
  return `${NAV_TAB_BASE_CLASS} ${navTabSizeClass(compact)} py-1.5 font-semibold ${tone}`;
}

export function secondaryNavTabClass(isActive: boolean, compact: boolean): string {
  const tone = isActive
    ? NAV_TAB_ACTIVE_TEXT_CLASS
    : `text-slate-600 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 ${NAV_TAB_INACTIVE_HOVER_CLASS}`;
  return `${NAV_TAB_BASE_CLASS} ${navTabSizeClass(compact)} py-1 font-semibold ${tone}`;
}
