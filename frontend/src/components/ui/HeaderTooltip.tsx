import type { ReactNode } from "react";

interface HeaderTooltipProps {
  /** Tooltip text; supply the same i18n string used for ``aria-label``. */
  label: string;
  /** Trigger element, typically a header icon button. */
  children: ReactNode;
  /** Hide the hint while a popover anchored to the trigger is open. */
  suppressed?: boolean;
  className?: string;
}

/**
 * Lightweight styled hover/focus hint for header icon buttons, replacing the
 * native ``title`` attribute per DESIGN.md §Inline Help Tooltips ("Do not use
 * native ``title`` attribute"). Visibility is pure CSS on trigger hover and
 * keyboard focus — no portal, no extra dependencies — and the surface reuses
 * the WikiTooltip light/dark token pairing so the header row stays on the
 * shared visual language. Only ``:focus-visible`` shows it, so focus a menu
 * returns to the trigger after a mouse click does not leave it hanging.
 *
 * 面向顶栏图标按钮的轻量样式化悬停/聚焦提示，依据 DESIGN.md「功能提示」规范
 * 取代原生 ``title`` 属性。显隐完全由触发器悬停与键盘聚焦的纯 CSS 控制——
 * 无传送门、无额外依赖——表面配色复用 WikiTooltip 的亮暗令牌组合，
 * 与顶栏整体视觉语言保持一致。只在 ``:focus-visible`` 时显示，鼠标点击后菜单把焦点
 * 还给触发按钮时不会一直挂着提示。
 */
export function HeaderTooltip({ label, children, suppressed = false, className = "" }: HeaderTooltipProps) {
  return (
    <span className={`group/header-tip relative inline-flex ${className}`}>
      {children}
      {!suppressed && (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute right-0 top-full z-50 mt-1.5 whitespace-nowrap rounded-lg border border-slate-200 bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 opacity-0 transition-opacity duration-150 group-hover/header-tip:opacity-100 group-has-[:focus-visible]/header-tip:opacity-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
        >
          {label}
        </span>
      )}
    </span>
  );
}
