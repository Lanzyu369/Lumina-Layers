import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { cx } from "./panelPrimitives";

interface ButtonProps {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  loading?: boolean;
  variant?: "primary" | "secondary";
  size?: "sm" | "md" | "icon";
  className?: string;
  title?: string;
  icon?: ReactNode;
}

export default function Button({
  label,
  onClick,
  disabled = false,
  loading = false,
  variant = "primary",
  size = "md",
  className,
  title,
  icon,
}: ButtonProps) {
  const isDisabled = disabled || loading;

  const variantClasses =
    variant === "primary"
      ? "bg-blue-600 text-white shadow-[0_12px_24px_rgba(37,99,235,0.22)] hover:bg-blue-700"
      : "border border-slate-200/80 bg-white/70 text-slate-700 shadow-[var(--shadow-control)] hover:bg-white hover:shadow-[var(--shadow-control-hover)] dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-200 dark:hover:bg-slate-900";

  const sizeClasses =
    size === "sm"
      ? "min-h-8 rounded-xl px-3 py-1.5 text-xs"
      : size === "icon"
      ? "h-9 w-9 shrink-0 rounded-full p-0 text-sm"
      : "min-h-11 rounded-2xl px-4 py-2.5 text-sm";

  return (
    <motion.button
      whileHover={isDisabled ? {} : { scale: 1.01, y: -1 }}
      whileTap={isDisabled ? {} : { scale: 0.99 }}
      transition={{ type: "spring", stiffness: 400, damping: 25 }}
      type="button"
      onClick={onClick}
      disabled={isDisabled}
      title={title ?? (icon ? label : undefined)}
      aria-label={icon ? label : undefined}
      className={cx(
        "relative inline-flex min-w-0 items-center justify-center font-medium transition-all duration-200 focus:outline-none focus:ring-4 focus:ring-[var(--focus-ring)] disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:translate-y-0",
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
        <span className="min-w-0 truncate whitespace-nowrap leading-none" translate="no">{label}</span>
      )}
    </motion.button>
  );
}
