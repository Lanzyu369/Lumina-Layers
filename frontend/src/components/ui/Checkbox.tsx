import {
  cx,
  workstationChoiceRowActiveClass,
  workstationChoiceRowClass,
  workstationChoiceRowDisabledClass,
} from "./panelPrimitives";
import HelpDot from "./HelpDot";
import type { WikiDocPath } from "../../utils/wikiDocs";

interface CheckboxProps {
  label: React.ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  /** Optional hover hint. Rendered via the canonical WikiTooltip popover
   *  (NOT native `title`) so the visual style matches the rest of the app. */
  tooltip?: string;
  /** Optional tooltip title override. Defaults to the string form of `label`
   *  when `tooltip` is set; pass this when `label` is a non-string ReactNode. */
  tooltipTitle?: string;
  /** Optional matching article in the public Lumina Wiki. */
  wikiPath?: WikiDocPath;
}

export default function Checkbox({
  label,
  checked,
  onChange,
  disabled = false,
  tooltip,
  tooltipTitle,
  wikiPath,
}: CheckboxProps) {
  const labelClass = cx(
    "flex items-center gap-3 text-sm",
    workstationChoiceRowClass,
    checked && workstationChoiceRowActiveClass,
    disabled
      ? workstationChoiceRowDisabledClass
      : "cursor-pointer hover:border-slate-300 hover:bg-white/75 dark:hover:border-slate-600 dark:hover:bg-slate-900/75",
  );

  return (
    <div className="relative">
      <label className={labelClass}>
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
          className="sr-only"
        />
        <span
          aria-hidden="true"
          className={cx(
            "flex h-5 w-5 shrink-0 items-center justify-center rounded-xl border transition-all duration-200",
            checked
              ? "border-blue-500 bg-blue-500"
              : "border-slate-300/80 bg-white dark:border-slate-600/80 dark:bg-slate-800"
          )}
        >
          <span className={cx("h-2.5 w-2.5 rounded-sm", checked ? "bg-white" : "bg-transparent")} />
        </span>
        <span className="min-w-0 flex-1 whitespace-normal break-words font-medium text-slate-700 dark:text-slate-200">
          {label}
        </span>
        {tooltip && <span aria-hidden="true" className="h-4 w-4 shrink-0" />}
      </label>
      {tooltip && (
        <div className="absolute right-3.5 top-1/2 z-10 h-4 w-4 -translate-y-1/2">
          <HelpDot
            title={tooltipTitle ?? (typeof label === "string" ? label : "")}
            description={tooltip}
            wikiPath={wikiPath}
            ariaLabel={tooltip}
          />
        </div>
      )}
    </div>
  );
}
