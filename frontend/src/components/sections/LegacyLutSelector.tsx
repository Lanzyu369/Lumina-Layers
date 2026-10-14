import Dropdown from "../ui/Dropdown";
import WikiTooltip from "../ui/WikiTooltip";
import Checkbox from "../ui/Checkbox";
import { cx, dependentGroupClass } from "../ui/panelPrimitives";

interface LegacyLutOption {
  label: string;
  value: string;
}

interface LegacyLutOptionGroup {
  label: string;
  options: LegacyLutOption[];
}

interface LegacyBrandInfo {
  displayName: string;
  materialTypes: string[];
  vendor: string;
}

interface LegacyLutSelectorProps {
  manufacturer: string;
  lutName: string;
  selectedLutNames?: string[];
  manufacturerOptions: LegacyLutOption[];
  groupedLutOptions: LegacyLutOptionGroup[];
  brandInfo?: LegacyBrandInfo | null;
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
    brandInfo?: string;
    materialType?: string;
    vendor?: string;
    database?: string;
    databasePlaceholder?: string;
  };
}

function flattenOptions(groups: LegacyLutOptionGroup[]): LegacyLutOption[] {
  const seen = new Set<string>();
  const flattened: LegacyLutOption[] = [];
  for (const group of groups) {
    for (const option of group.options) {
      if (seen.has(option.value)) {
        continue;
      }
      seen.add(option.value);
      flattened.push(option);
    }
  }
  return flattened;
}

function formatList(values: string[]): string {
  return values.length > 0 ? values.join(", ") : "";
}

export default function LegacyLutSelector({
  manufacturer,
  lutName,
  selectedLutNames,
  manufacturerOptions,
  groupedLutOptions,
  brandInfo,
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
  const allLutOptions = flattenOptions(groupedLutOptions);
  const selectedSet = new Set(
    selectedLutNames && selectedLutNames.length > 0
      ? selectedLutNames
      : lutName
        ? [lutName]
        : [],
  );
  const selectedOptions = allLutOptions.filter((option) =>
    selectedSet.has(option.value),
  );
  const selectedCount = selectedOptions.length;

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
    const ordered = allLutOptions
      .map((option) => option.value)
      .filter((candidate) => next.has(candidate));
    onLutSelectionChange(ordered);
  };

  const refreshButton = (
    <WikiTooltip title={labels.refreshTooltip} description="">
      <button
        type="button"
        onClick={onRefresh}
        disabled={refreshing}
        aria-label={labels.refreshTooltip}
        className="ghost-control inline-flex size-5 items-center justify-center rounded-full text-slate-500 dark:text-slate-400"
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
      className="inline-flex min-h-11 w-full items-center justify-center rounded-[10px] border border-transparent bg-[var(--surface-well)] px-3 text-sm font-medium text-slate-700 transition-all duration-200 hover:border-[color:var(--surface-card-outline)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] dark:text-slate-200"
    >
      {labels.upload}
    </button>
  );

  const databaseSummary = selectedOptions.map((option) => option.label);
  const materialTypes = brandInfo?.materialTypes.filter(Boolean) ?? [];

  return (
    <div className="grid grid-cols-1 gap-2">
      <div className={`gap-2 ${compact ? "grid grid-cols-1" : "flex items-end"}`}>
        <div className="min-w-0 flex-1">
          <Dropdown
            label={labels.manufacturer}
            value={manufacturer}
            options={manufacturerOptions}
            onChange={onManufacturerChange}
            placeholder={labels.manufacturerPlaceholder}
            disabled={loading || manufacturerOptions.length === 0}
            labelAccessory={refreshButton}
          />
        </div>
        <div className={compact ? "" : "shrink-0"}>{uploadButton}</div>
      </div>

      {helperText && (
        <div className="px-1 text-xs text-slate-500 dark:text-slate-400">
          {helperText}
        </div>
      )}

      {manufacturer ? (
        <div className={cx(dependentGroupClass, "min-w-0")}>
          <div className="text-xs text-slate-500 dark:text-slate-400">
            {labels.brandInfo ?? "Brand Info"}:
            <span className="ml-1 text-slate-700 dark:text-slate-200">
              {brandInfo?.displayName || manufacturer}
            </span>
          </div>
          {materialTypes.length > 0 && (
            <div className="text-xs text-slate-500 dark:text-slate-400">
              {labels.materialType ?? "Material Type"}: {formatList(materialTypes)}
            </div>
          )}
          <div className="text-xs text-slate-500 dark:text-slate-400">
            {labels.vendor ?? "Vendor"}: {brandInfo?.vendor || manufacturer}
          </div>

          <div className="text-xs text-slate-500 dark:text-slate-400">
            {labels.database ?? labels.lut}:
            <span className="ml-1 whitespace-normal break-words text-slate-700 dark:text-slate-200">
              {databaseSummary.length > 0
                ? formatList(databaseSummary)
                : labels.databasePlaceholder ?? labels.lutPlaceholder}
            </span>
          </div>

          <div className="grid gap-2">
            {allLutOptions.map((option) => (
              <Checkbox
                key={option.value}
                label={(
                  <span className="block min-w-0 whitespace-normal break-words leading-6">
                    {option.label}
                  </span>
                )}
                checked={selectedSet.has(option.value)}
                disabled={lutDisabled}
                onChange={() => handleToggleLut(option.value)}
              />
            ))}
          </div>

          <div className="sr-only" aria-live="polite">
            {labels.selectedCount ?? "Selected"}: {selectedCount}
          </div>
        </div>
      ) : null}
    </div>
  );
}
