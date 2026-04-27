/**
 * HelpDot - Canonical inline "?" trigger that opens a WikiTooltip popover.
 * 标签旁的标准问号触发器，悬停后弹出统一风格的 WikiTooltip 气泡。
 *
 * Visual contract (do not diverge): the small `?` chip used in
 * `GradientCardExtractPanel.tsx` is the project-wide reference. Any new
 * label hint must reuse this component instead of inventing its own
 * shape, color, or background.
 *
 * 视觉契约（不要私自更改）：以 `GradientCardExtractPanel.tsx` 中的
 * 小问号样式为全局基准；任何新增的标签提示都应使用本组件，不要
 * 重新发明形状、颜色或底色。
 */
import type { Placement } from "@floating-ui/react";
import WikiTooltip from "./WikiTooltip";

interface HelpDotProps {
  /** Tooltip title (also used as default aria-label). */
  title: string;
  /** Tooltip description body. */
  description: string;
  /** Optional wiki URL for the "Learn more" link. */
  wikiUrl?: string;
  /** Preferred placement direction, default "top". */
  placement?: Placement;
  /** Optional aria-label override for the trigger. */
  ariaLabel?: string;
}

export default function HelpDot({
  title,
  description,
  wikiUrl,
  placement = "top",
  ariaLabel,
}: HelpDotProps) {
  return (
    <WikiTooltip
      title={title}
      description={description}
      wikiUrl={wikiUrl}
      placement={placement}
    >
      <span
        role="button"
        tabIndex={0}
        aria-label={ariaLabel ?? title}
        className="flex h-4 w-4 cursor-help items-center justify-center rounded-full bg-slate-200 text-[10px] font-bold text-slate-500 transition-colors hover:bg-slate-300 focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)] dark:bg-slate-700 dark:text-slate-400 dark:hover:bg-slate-600"
      >
        ?
      </span>
    </WikiTooltip>
  );
}
