import { forwardRef } from "react";
import { XMarkIcon } from "@heroicons/react/24/outline";

interface CloseButtonProps {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  "data-testid"?: string;
}

const CloseButton = forwardRef<HTMLButtonElement, CloseButtonProps>(function CloseButton({ label, onClick, disabled, "data-testid": testId }, ref) {
  return (
    <button data-testid={testId} ref={ref} type="button" aria-label={label} onClick={onClick} disabled={disabled}
      className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-0 bg-slate-200 text-slate-600 transition-colors enabled:hover:bg-slate-300 enabled:hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-slate-700 dark:text-slate-300 dark:enabled:hover:bg-slate-600 dark:enabled:hover:text-slate-100">
      <XMarkIcon aria-hidden="true" className="h-5 w-5" />
    </button>
  );
});

export default CloseButton;
