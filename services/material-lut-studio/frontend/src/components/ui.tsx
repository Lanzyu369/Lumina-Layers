import type { ButtonHTMLAttributes, ReactNode } from "react";

/**
 * 共享 UI 原子组件。全部基于主题 token（var(--*)），不出现裸色值，
 * 自动适配浅色/深色主题，符合 DESIGN.md 的设计语言。
 */

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary:
    "bg-[var(--accent)] text-[var(--accent-contrast)] hover:opacity-90 border border-transparent",
  secondary:
    "bg-[var(--surface-muted)] text-[var(--text)] hover:bg-[var(--border)] border border-[var(--border)]",
  danger:
    "bg-transparent text-[var(--danger)] hover:bg-[var(--surface-muted)] border border-[var(--danger)]",
  ghost:
    "bg-transparent text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-muted)] border border-transparent",
};

export function Button({ variant = "secondary", className = "", ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${VARIANT_CLASS[variant]} ${className}`}
    />
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={`rounded-lg border border-[var(--border)] bg-[var(--surface)] ${className}`}
    >
      {children}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
      <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-[var(--border)] border-t-[var(--accent)]" />
      {label}
    </div>
  );
}

export function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex h-40 items-center justify-center text-sm text-[var(--text-muted)]">
      {text}
    </div>
  );
}

export function ErrorBanner({ message, onRetry, retryLabel }: { message: string; onRetry?: () => void; retryLabel?: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-[var(--danger)] bg-[var(--surface-muted)] px-3 py-2 text-sm text-[var(--danger)]">
      <span className="truncate">{message}</span>
      {onRetry && (
        <button onClick={onRetry} className="shrink-0 underline hover:no-underline">
          {retryLabel}
        </button>
      )}
    </div>
  );
}

export function Toast({ message, onClose }: { message: string; onClose: () => void }) {
  return (
    <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2">
      <div className="flex items-center gap-3 rounded-md border border-[var(--border)] bg-[var(--surface)] px-4 py-2 text-sm text-[var(--text)] shadow-lg">
        <span>{message}</span>
        <button onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text)]">
          ✕
        </button>
      </div>
    </div>
  );
}

export function Swatch({ hex, size = 20 }: { hex: string | null; size?: number }) {
  const safe = hex && /^#[0-9a-fA-F]{6}$/.test(hex) ? hex : null;
  return (
    <span
      className="inline-block rounded border border-[var(--border)]"
      style={{
        width: size,
        height: size,
        backgroundColor: safe ?? "transparent",
        backgroundImage: safe
          ? undefined
          : "repeating-conic-gradient(var(--border) 0% 25%, transparent 0% 50%)",
        backgroundSize: safe ? undefined : "8px 8px",
      }}
      title={safe ?? "—"}
    />
  );
}
