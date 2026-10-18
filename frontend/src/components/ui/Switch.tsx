import { cx } from "./panelPrimitives";

interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  checkedLabel?: string;
  uncheckedLabel?: string;
  disabled?: boolean;
  ariaLabel?: string;
}

/** The bare pill track + knob, shared by `Switch` and switch-style `Checkbox` rows. */
export function SwitchTrack({ checked }: { checked: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cx(
        "relative inline-flex h-6 w-11 shrink-0 rounded-full transition-colors duration-200",
        checked ? "bg-blue-500" : "bg-slate-300 dark:bg-slate-600"
      )}
    >
      <span
        className={cx(
          "absolute top-1 h-4 w-4 rounded-full bg-white shadow-sm transition-all duration-200",
          checked ? "left-6" : "left-1"
        )}
      />
    </span>
  );
}

export default function Switch({
  checked,
  onChange,
  checkedLabel,
  uncheckedLabel,
  disabled = false,
  ariaLabel,
}: SwitchProps) {
  const hasStateLabel = Boolean(checkedLabel || uncheckedLabel);
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(
        "inline-flex shrink-0 items-center gap-2 rounded-full transition-opacity duration-200 focus:outline-none focus-visible:ring-4 focus-visible:ring-[var(--focus-ring)]",
        disabled ? "cursor-not-allowed opacity-40" : "cursor-pointer hover:opacity-90"
      )}
    >
      {hasStateLabel && (
        <span
          className={cx(
            "select-none text-[11px] font-medium transition-colors duration-200",
            checked ? "text-blue-700 dark:text-blue-200" : "text-slate-500 dark:text-slate-300"
          )}
        >
          {checked ? checkedLabel : uncheckedLabel}
        </span>
      )}
      <SwitchTrack checked={checked} />
    </button>
  );
}
