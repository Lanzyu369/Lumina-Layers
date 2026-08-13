/**
 * HelpDot - Canonical inline info-icon trigger that opens a WikiTooltip popover.
 * 标签旁的标准 ⓘ 信息图标触发器，悬停后弹出统一风格的 WikiTooltip 气泡。
 *
 * Visual contract (do not diverge): a 16px stroke-style info icon (circle + i)
 * with no background fill, tinted with the secondary text color and darkening
 * on hover. Any new label hint must reuse this component instead of inventing
 * its own shape, color, or background.
 *
 * 视觉契约（不要私自更改）：16px 描边风格 info 图标（圆圈 + i），无底色，
 * 颜色跟随次级文字色、hover 加深；任何新增的标签提示都应使用本组件，
 * 不要重新发明形状、颜色或底色。
 */
import type { Placement } from "@floating-ui/react";
import WikiTooltip from "./WikiTooltip";
import { InfoIcon } from "./icons";

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
        className="flex h-4 w-4 cursor-help items-center justify-center rounded-full text-slate-400 transition-colors hover:text-slate-600 focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)] dark:text-slate-500 dark:hover:text-slate-300"
      >
        <InfoIcon className="h-4 w-4" strokeWidth={1.75} />
      </span>
    </WikiTooltip>
  );
}
