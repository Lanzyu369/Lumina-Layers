/**
 * HelpDot - Inline question-mark trigger that opens a WikiTooltip popover.
 * 行内问号触发器，悬停后弹出统一风格的 WikiTooltip 解释气泡。
 *
 * 该组件用来替代散落在表单标签旁的 `title="..."` 原生提示，
 * 以保持全局 tooltip 视觉一致：所有标签提示都走 WikiTooltip，
 * 而不是浏览器默认的 native tooltip 或自绘的 `bg-slate-100/85` 小方块。
 */
import type { Placement } from "@floating-ui/react";
import WikiTooltip from "./WikiTooltip";
import { HelpCircleIcon } from "./icons";

interface HelpDotProps {
  /** Tooltip title text */
  title: string;
  /** Tooltip description text */
  description: string;
  /** Optional wiki URL for external link */
  wikiUrl?: string;
  /** Preferred placement direction, default "top" */
  placement?: Placement;
  /** Optional aria-label override for the icon button */
  ariaLabel?: string;
  /** Extra classes for the trigger element */
  className?: string;
}

export default function HelpDot({
  title,
  description,
  wikiUrl,
  placement = "top",
  ariaLabel,
  className,
}: HelpDotProps) {
  return (
    <WikiTooltip
      title={title}
      description={description}
      wikiUrl={wikiUrl}
      placement={placement}
    >
      <button
        type="button"
        aria-label={ariaLabel ?? title}
        className={
          "inline-flex h-4 w-4 items-center justify-center rounded-full text-slate-400 transition-colors hover:text-slate-600 focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)] dark:text-slate-500 dark:hover:text-slate-300 " +
          (className ?? "")
        }
      >
        <HelpCircleIcon className="h-3.5 w-3.5" />
      </button>
    </WikiTooltip>
  );
}
