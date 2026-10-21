import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { cx } from "./panelPrimitives";

/** Button emphasis levels. 按钮层级。
 *  - `primary`   opens an operation dialog or executes a function (blue fill)
 *  - `secondary` neutral dismissal / navigation actions (bordered)
 *  - `ghost`     mode selection / toggles / close controls: boundary hidden at rest,
 *                appears on hover and keyboard focus (see `.ghost-control`) */
export type ButtonVariant = "primary" | "secondary" | "ghost";

/** Only meaningful for the `ghost` variant. 仅幽灵按钮使用。 */
export type ButtonTone = "default" | "danger";

interface ButtonProps {
  label: string;
  onClick?: () => void;
  type?: "button" | "submit" | "reset";
  disabled?: boolean;
  loading?: boolean;
  variant?: ButtonVariant;
  size?: "sm" | "md" | "icon";
  /** Ghost only: red boundary / fill on hover for destructive actions. */
  tone?: ButtonTone;
  /** Ghost only: toggled-on state (fill tint, no boundary). */
  active?: boolean;
  className?: string;
  title?: string;
  icon?: ReactNode;
  /** Icon rendered before the label. 标签前的图标。 */
  leadingIcon?: ReactNode;
  "data-testid"?: string;
}

export default function Button({
  label,
  onClick,
  type = "button",
  disabled = false,
  loading = false,
  variant = "primary",
  size = "md",
  tone = "default",
  active = false,
  className,
  title,
  icon,
  leadingIcon,
  "data-testid": dataTestId,
}: ButtonProps) {
  const isDisabled = disabled || loading;
  const isGhost = variant === "ghost";

  // No `shadow-*` utility in any variant: the global rule in index.css strips
  // box-shadow from matching class strings, which would also drop the focus
  // ring (Tailwind draws `ring-*` with box-shadow).
  // 任何变体都不写 `shadow-*`：index.css 的全局规则会清掉阴影，焦点环靠
  // box-shadow 实现，会一并消失。
  const variantClasses =
    variant === "primary"
      ? "action-control"
      : variant === "ghost"
        ? "ghost-control"
        : "border border-slate-200/80 bg-white/70 text-slate-700 hover:bg-white dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-200 dark:hover:bg-slate-900";

  const sizeClasses =
    size === "sm"
      ? "min-h-8 rounded-lg px-3 py-1.5 text-xs"
      : size === "icon"
        ? "h-9 w-9 shrink-0 rounded-full p-0 text-sm"
        : "min-h-11 rounded-[10px] px-4 py-2.5 text-sm";

  return (
    <motion.button
      whileHover={isDisabled || isGhost ? {} : { scale: 1.01, y: -1 }}
      whileTap={isDisabled ? {} : { scale: 0.99 }}
      transition={{ type: "spring", stiffness: 400, damping: 25 }}
      type={type}
      onClick={onClick}
      disabled={isDisabled}
      title={title ?? (icon ? label : undefined)}
      aria-label={icon ? label : undefined}
      aria-pressed={isGhost ? active : undefined}
      data-active={isGhost && active ? "true" : undefined}
      data-tone={isGhost ? tone : undefined}
      data-testid={dataTestId}
      className={cx(
        "relative inline-flex min-w-0 items-center justify-center font-medium transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:translate-y-0",
        sizeClasses,
        variantClasses,
        className
      )}
    >
      {loading && (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute left-2.5 h-4 w-4 rounded-full border-2 border-current/25 border-t-current animate-spin"
        />
      )}
      {icon ? (
        <span className="inline-flex items-center justify-center" aria-hidden="true">
          {icon}
        </span>
      ) : (
        <span className="inline-flex min-w-0 items-center justify-center gap-1.5">
          {leadingIcon && (
            <span className="inline-flex shrink-0 items-center" aria-hidden="true">
              {leadingIcon}
            </span>
          )}
          <span className="min-w-0 truncate whitespace-nowrap leading-none" translate="no">{label}</span>
        </span>
      )}
    </motion.button>
  );
}
