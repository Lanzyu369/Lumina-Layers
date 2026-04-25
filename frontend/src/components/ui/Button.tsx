import { motion } from "framer-motion";
import { cx } from "./panelPrimitives";

interface ButtonProps {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  loading?: boolean;
  variant?: "primary" | "secondary";
  size?: "sm" | "md";
  className?: string;
  title?: string;
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
}: ButtonProps) {
  const isDisabled = disabled || loading;

  const variantClasses =
    variant === "primary"
      ? "bg-blue-600 text-white shadow-[0_12px_24px_rgba(37,99,235,0.22)] hover:bg-blue-700"
      : "border border-slate-200/80 bg-white/70 text-slate-700 shadow-[var(--shadow-control)] hover:bg-white hover:shadow-[var(--shadow-control-hover)] dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-200 dark:hover:bg-slate-900";

  const sizeClasses =
    size === "sm"
      ? "min-h-8 rounded-xl px-3 py-1.5 text-xs"
      : "min-h-11 rounded-2xl px-4 py-2.5 text-sm";

  return (
    <motion.button
      whileHover={isDisabled ? {} : { scale: 1.01, y: -1 }}
      whileTap={isDisabled ? {} : { scale: 0.99 }}
      transition={{ type: "spring", stiffness: 400, damping: 25 }}
      type="button"
      onClick={onClick}
      disabled={isDisabled}
      title={title}
      className={cx(
        "relative inline-flex flex-shrink-0 items-center justify-center gap-2 font-medium transition-all duration-200 focus:outline-none focus:ring-4 focus:ring-[var(--focus-ring)] disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:translate-y-0",
        sizeClasses,
        variantClasses,
        className
      )}
    >
      <span
        aria-hidden="true"
        className={cx(
          "h-4 w-4 rounded-full border-2 border-current/25 border-t-current",
          loading ? "animate-spin opacity-100" : "opacity-0",
        )}
      />
      <span translate="no">{label}</span>
    </motion.button>
  );
}
