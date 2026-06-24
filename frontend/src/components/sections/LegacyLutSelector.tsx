import Dropdown from "../ui/Dropdown";
import WikiTooltip from "../ui/WikiTooltip";
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
  selectedLutNames?: string[];
  manufacturerOptions: LegacyLutOption[];
  groupedLutOptions: LegacyLutOptionGroup[];
  onManufacturerChange: (value: string) => void;
  onLutChange: (value: string) => void;
  onLutSelectionChange?: (values: string[]) => void;
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
    multiSelect?: string;
    selectedCount?: string;
  };
}

export default function LegacyLutSelector({
  manufacturer,
  lutName,
  selectedLutNames,
  manufacturerOptions,
  groupedLutOptions,
  onManufacturerChange,
  onLutChange,
  onLutSelectionChange,
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
  const selectedSet = new Set(
    selectedLutNames && selectedLutNames.length > 0
      ? selectedLutNames
      : lutName
        ? [lutName]
        : [],
  );
  const orderedLutValues = groupedLutOptions.flatMap((group) =>
    group.options.map((option) => option.value),
  );
  const selectedCount = orderedLutValues.filter((value) =>
    selectedSet.has(value),
  ).length;

  const handleToggleLut = (value: string) => {
    if (!onLutSelectionChange) {
      onLutChange(value);
      return;
    }
    const next = new Set(selectedSet);
    if (next.has(value)) {
      next.delete(value);
    } else {
      next.add(value);
    }
    onLutSelectionChange(
      orderedLutValues.filter((candidate) => next.has(candidate)),
    );
  };

  const refreshButton = (
    <WikiTooltip title={labels.refreshTooltip} description="">
      <button
        type="button"
        onClick={onRefresh}
        disabled={refreshing}
        aria-label={labels.refreshTooltip}
        className="inline-flex size-5 items-center justify-center rounded-full text-slate-500 transition-colors hover:bg-slate-200/70 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-45 dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-slate-200"
      >
        <span
          className={cx("text-[13px] leading-none", refreshing && "animate-spin")}
          aria-hidden="true"
        >
          ⟳
        </span>
      </button>
    </WikiTooltip>
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

  const multiSelectList =
    manufacturer && groupedLutOptions.length > 0 ? (
      <div className="grid gap-2 rounded-lg border border-slate-200/60 bg-slate-100/50 p-3 dark:border-slate-700/40 dark:bg-slate-900/40">
        <div className="flex items-center justify-between gap-2 text-xs font-medium uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">
          <span>{labels.multiSelect ?? labels.lut}</span>
          <span className="tracking-normal">{labels.selectedCount ?? "Selected"}: {selectedCount}</span>
        </div>
        <div className="grid gap-2">
          {groupedLutOptions.map((group) => (
            <div key={group.label} className="grid gap-1.5">
              <div className="text-xs text-slate-500 dark:text-slate-400">
                {group.label}
              </div>
              {group.options.map((option) => (
                <label
                  key={option.value}
                  className="flex min-h-8 items-center gap-2 rounded-md px-2 text-sm text-slate-700 transition-colors hover:bg-slate-200/60 dark:text-slate-200 dark:hover:bg-slate-800/60"
                >
                  <input
                    type="checkbox"
                    checked={selectedSet.has(option.value)}
                    disabled={lutDisabled}
                    onChange={() => handleToggleLut(option.value)}
                    className="size-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500 dark:border-slate-600 dark:bg-slate-900"
                  />
                  <span className="min-w-0 flex-1 truncate">{option.label}</span>
                </label>
              ))}
            </div>
          ))}
        </div>
      </div>
    ) : null;

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
        <Dropdown
          label={labels.lut}
          value={lutName}
          groupedOptions={groupedLutOptions}
          onChange={onLutChange}
          placeholder={labels.lutPlaceholder}
          disabled={lutDisabled}
          labelAccessory={refreshButton}
        />
        {uploadButton}
        {helperText && (
          <div className="px-1 text-xs text-slate-500 dark:text-slate-400">
            {helperText}
          </div>
        )}
        {multiSelectList}
      </div>
    );
  }

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
      <div className="flex items-end gap-2">
        <div className="min-w-0 flex-1">
          <Dropdown
            label={labels.lut}
            value={lutName}
            groupedOptions={groupedLutOptions}
            onChange={onLutChange}
            placeholder={labels.lutPlaceholder}
            disabled={lutDisabled}
            labelAccessory={refreshButton}
          />
        </div>
        <div className="shrink-0">{uploadButton}</div>
      </div>
      {helperText && (
        <div className="px-1 text-xs text-slate-500 dark:text-slate-400">
          {helperText}
        </div>
      )}
      {multiSelectList}
    </div>
  );
}
