import Dropdown from "../ui/Dropdown";
import { cx } from "../ui/panelPrimitives";

interface LegacyLutOption {
  label: string;
  value: string;
}

interface LegacyLutOptionGroup {
  label: string;
  options: LegacyLutOption[];
}

interface LegacyLutSelectorProps {
  manufacturer: string;
  lutName: string;
  manufacturerOptions: LegacyLutOption[];
  groupedLutOptions: LegacyLutOptionGroup[];
  onManufacturerChange: (value: string) => void;
  onLutChange: (value: string) => void;
  onRefresh: () => void;
  onUploadClick: () => void;
  loading?: boolean;
  lutLoading?: boolean;
  refreshing?: boolean;
  compact?: boolean;
  labels: {
    manufacturer: string;
    manufacturerPlaceholder: string;
    lut: string;
    lutPlaceholder: string;
    refreshTooltip: string;
    upload: string;
    loadingHint: string;
    noBrandHint: string;
  };
}

function RefreshIcon({ spinning }: { spinning: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 20 20"
      className={cx("h-4 w-4", spinning && "animate-spin")}
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.8"
    >
      <path d="M16 6.5A7 7 0 1 0 17 10" />
      <path d="M16 3.5v3h-3" />
    </svg>
  );
}

export default function LegacyLutSelector({
  manufacturer,
  lutName,
  manufacturerOptions,
  groupedLutOptions,
  onManufacturerChange,
  onLutChange,
  onRefresh,
  onUploadClick,
  loading = false,
  lutLoading = false,
  refreshing = false,
  compact = false,
  labels,
}: LegacyLutSelectorProps) {
  const lutDisabled = loading || lutLoading || !manufacturer;
  const helperText = loading || lutLoading
    ? labels.loadingHint
    : !manufacturer
      ? labels.noBrandHint
      : "";

  const refreshButton = (
    <button
      type="button"
      onClick={onRefresh}
      disabled={refreshing}
      aria-label={labels.refreshTooltip}
      title={labels.refreshTooltip}
      className="inline-flex min-h-11 w-full items-center justify-center rounded-2xl border border-slate-200/80 bg-slate-100/75 px-3 text-slate-600 shadow-[var(--shadow-control)] transition-colors hover:bg-slate-200/70 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-45 dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:bg-slate-800/75 dark:hover:text-slate-100"
    >
      <RefreshIcon spinning={refreshing} />
    </button>
  );

  const uploadButton = (
    <button
      type="button"
      onClick={onUploadClick}
      className="inline-flex min-h-11 w-full items-center justify-center rounded-2xl border border-slate-200/80 bg-slate-100/75 px-3 text-sm font-medium text-slate-700 shadow-[var(--shadow-control)] transition-colors hover:bg-slate-200/70 hover:text-slate-900 focus:outline-none focus:ring-4 focus:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-200 dark:hover:bg-slate-800/75 dark:hover:text-slate-50"
    >
      {labels.upload}
    </button>
  );

  if (compact) {
    return (
      <div className="grid grid-cols-1 gap-2">
        <Dropdown
          label={labels.manufacturer}
          value={manufacturer}
          options={manufacturerOptions}
          onChange={onManufacturerChange}
          placeholder={labels.manufacturerPlaceholder}
          disabled={loading || manufacturerOptions.length === 0}
        />
        {refreshButton}
        <Dropdown
          label={labels.lut}
          value={lutName}
          groupedOptions={groupedLutOptions}
          onChange={onLutChange}
          placeholder={labels.lutPlaceholder}
          disabled={lutDisabled}
        />
        {uploadButton}
        {helperText && (
          <div className="px-1 text-xs text-slate-500 dark:text-slate-400">
            {helperText}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-2">
      <div className="flex items-end gap-2">
        <div className="min-w-0 flex-1">
          <Dropdown
            label={labels.manufacturer}
            value={manufacturer}
            options={manufacturerOptions}
            onChange={onManufacturerChange}
            placeholder={labels.manufacturerPlaceholder}
            disabled={loading || manufacturerOptions.length === 0}
          />
        </div>
        <div className="w-11 shrink-0">{refreshButton}</div>
      </div>
      <div className="flex items-end gap-2">
        <div className="min-w-0 flex-1">
          <Dropdown
            label={labels.lut}
            value={lutName}
            groupedOptions={groupedLutOptions}
            onChange={onLutChange}
            placeholder={labels.lutPlaceholder}
            disabled={lutDisabled}
          />
        </div>
        <div className="shrink-0">{uploadButton}</div>
      </div>
      {helperText && (
        <div className="px-1 text-xs text-slate-500 dark:text-slate-400">
          {helperText}
        </div>
      )}
    </div>
  );
}
