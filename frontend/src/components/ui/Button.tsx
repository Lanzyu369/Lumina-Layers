import type { ReactNode } from "react";
import { cx } from "./panelPrimitives";

/** Button emphasis levels. 按钮层级。
 *  - `ghost`     mode selection / toggles / close controls: boundary hidden at rest,
 *                appears on hover and keyboard focus (see `.ghost-control`) */
export type ButtonVariant = "primary" | "secondary" | "ghost";

export type ButtonTone = "default" | "danger";

interface ButtonProps {
  label: string;
  onClick?: () => void;
  type?: "button" | "submit" | "reset";
  disabled?: boolean;
  loading?: boolean;
  variant?: ButtonVariant;
  size?: "sm" | "md" | "icon";
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
      : variant === "ghost"
        ? "ghost-control"

  const sizeClasses =
    size === "sm"
      ? "min-h-8 rounded-lg px-3 py-1.5 text-xs"
      : size === "icon"
        ? "h-9 w-9 shrink-0 rounded-full p-0 text-sm"

  return (
      type={type}
      onClick={onClick}
      disabled={isDisabled}
      title={title ?? (icon ? label : undefined)}
      aria-pressed={isGhost ? active : undefined}
      data-active={isGhost && active ? "true" : undefined}
      data-testid={dataTestId}
      className={cx(
        sizeClasses,
        variantClasses,
        className
      )}
    >
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
  );
}
