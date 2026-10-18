import { useState } from "react";
import WikiTooltip from "../ui/WikiTooltip";
import LutPickerDialog, { type LutPickerBrand, type LutPickerOption } from "../ui/LutPickerDialog";
import { cx, workstationPickerTriggerClass, workstationFieldLabelClass } from "../ui/panelPrimitives";

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
  /** Catalog-wide labels for selected LUTs outside the visible brand. */
  allLutOptions?: LegacyLutOption[];
  brandInfo?: LegacyBrandInfo | null;
  onManufacturerChange: (value: string) => void;
  onLutChange: (value: string) => void;
  onLutSelectionChange?: (values: string[]) => void;
  onRefresh: () => void;
  onUploadClick: () => void;
  loading?: boolean;
  lutLoading?: boolean;
  refreshing?: boolean;
  labels: {
    manufacturer: string;
    manufacturerPlaceholder: string;
    lutPlaceholder: string;
    refreshTooltip: string;
    upload: string;
    loadingHint: string;
    noBrandHint: string;
    selectedCount?: string;
    brandInfo?: string;
    materialType?: string;
    vendor?: string;
    /** Dialog-specific labels (fall back to base labels when omitted). */
    dialogTitle?: string;
    dialogSearchPlaceholder?: string;
    dialogAllGroups?: string;
    dialogNoMatch?: string;
    dialogDeselectAll?: string;
    dialogConfirm?: string;
    dialogCancel?: string;
    openPicker?: string;
  };
}

// Flatten groups preserving order, deduplicating by value.
function flattenOptions(groups: LegacyLutOptionGroup[]): LegacyLutOption[] {
  const seen = new Set<string>();
  const result: LegacyLutOption[] = [];
  for (const group of groups) {
    for (const option of group.options) {
      if (seen.has(option.value)) continue;
      seen.add(option.value);
      result.push(option);
    }
  }
  return result;
}

// Build picker options from grouped LUT options.
function buildPickerOptions(groups: LegacyLutOptionGroup[]): LutPickerOption[] {
  const seen = new Set<string>();
  const result: LutPickerOption[] = [];
  for (const group of groups) {
    for (const option of group.options) {
      if (seen.has(option.value)) continue;
      seen.add(option.value);
      result.push({ value: option.value, label: option.label, group: group.label });
    }
  }
  return result;
}

export default function LegacyLutSelector({
  manufacturer,
  lutName,
  selectedLutNames,
  manufacturerOptions,
  groupedLutOptions,
  allLutOptions,
  brandInfo,
  onManufacturerChange,
  onLutChange,
  onLutSelectionChange,
  onRefresh,
  onUploadClick,
  loading = false,
  lutLoading = false,
  refreshing = false,
  labels,
}: LegacyLutSelectorProps) {
  const [dialogOpen, setDialogOpen] = useState(false);

  const catalogOptions = allLutOptions ?? flattenOptions(groupedLutOptions);
  const pickerOptions = buildPickerOptions(groupedLutOptions);

  const selectedSet = new Set(
    selectedLutNames && selectedLutNames.length > 0
      ? selectedLutNames
      : lutName
        ? [lutName]
        : [],
  );
  const optionsByName = new Map(catalogOptions.map((option) => [option.value, option]));
  const selectedOptions = Array.from(selectedSet, (value) =>
    optionsByName.get(value) ?? { value, label: value },
  );
  const selectedCount = selectedOptions.length;

  // Build brand list for picker sidebar
  const pickerBrands: LutPickerBrand[] = manufacturerOptions.map((opt) => ({
    value: opt.value,
    label: opt.label,
    displayName: brandInfo && opt.value === manufacturer ? brandInfo.displayName : undefined,
    materialTypes: brandInfo && opt.value === manufacturer ? brandInfo.materialTypes : undefined,
    vendor: brandInfo && opt.value === manufacturer ? brandInfo.vendor : undefined,
  }));

  const handleConfirm = (lutNames: string[]) => {
    setDialogOpen(false);
    if (onLutSelectionChange) {
      onLutSelectionChange(lutNames);
    } else if (lutNames.length > 0) {
      onLutChange(lutNames[0]);
    }
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

  // Summary chips shown on the trigger button
  const VISIBLE_LIMIT = 2;
  const visibleChips = selectedOptions.slice(0, VISIBLE_LIMIT);
  const overflowCount = selectedCount - visibleChips.length;

  // Trigger button: shows current brand + selected LUT chips
  const triggerEmpty = !manufacturer;
  const triggerPlaceholder = loading
    ? labels.loadingHint
    : triggerEmpty
      ? labels.manufacturerPlaceholder
      : labels.openPicker ?? labels.lutPlaceholder;

  return (
    <div className="flex flex-col gap-2">
      {/* Brand / LUT label row */}
      <div className="flex items-center gap-2">
        <span className={workstationFieldLabelClass}>{labels.manufacturer}</span>
        {refreshButton}
      </div>

      {/* Single trigger button: brand name + selected LUT chips */}
      <button
        type="button"
        disabled={loading && manufacturerOptions.length === 0}
        onClick={() => setDialogOpen(true)}
        data-testid="lut-picker-trigger"
        aria-label={labels.manufacturer}
        className={cx(
          workstationPickerTriggerClass,
          "flex min-h-11 items-center justify-between gap-2 text-left",
          triggerEmpty && "text-slate-400 dark:text-slate-500",
        )}
      >
        <span className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
          {manufacturer && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
              {brandInfo?.displayName ?? manufacturer}
            </span>
          )}
          {visibleChips.map((opt) => (
            <span
              key={opt.value}
              className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-500/15 dark:text-blue-200"
            >
              {opt.label}
            </span>
          ))}
          {overflowCount > 0 && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              +{overflowCount}
            </span>
          )}
          {!manufacturer && !loading && (
            <span className="text-sm text-slate-400 dark:text-slate-500">
              {triggerPlaceholder}
            </span>
          )}
          {manufacturer && selectedCount === 0 && (
            <span className="text-sm text-slate-400 dark:text-slate-500">
              {labels.lutPlaceholder}
            </span>
          )}
        </span>
        {selectedCount > 0 && (
          <span className="shrink-0 text-xs text-slate-400 dark:text-slate-500">
            {labels.selectedCount ?? "已选"}: {selectedCount}
          </span>
        )}
      </button>

      {/* The sr-only live region so screen readers still announce changes. */}
      <div className="sr-only" aria-live="polite">
        {labels.selectedCount ?? "Selected"}: {selectedCount}
      </div>

      <LutPickerDialog
        open={dialogOpen}
        brands={pickerBrands}
        lutOptions={pickerOptions}
        selectedBrand={manufacturer}
        initialSelectedLuts={
          selectedLutNames && selectedLutNames.length > 0
            ? selectedLutNames
            : lutName ? [lutName] : []
        }
        onBrandChange={(brand) => {
          onManufacturerChange(brand);
        }}
        onConfirm={handleConfirm}
        onCancel={() => setDialogOpen(false)}
        onUploadClick={() => {
          setDialogOpen(false);
          onUploadClick();
        }}
        onRefresh={onRefresh}
        loading={loading}
        lutLoading={lutLoading}
        refreshing={refreshing}
        labels={{
          title: labels.dialogTitle ?? labels.manufacturer,
          searchPlaceholder: labels.dialogSearchPlaceholder ?? labels.lutPlaceholder,
          allGroups: labels.dialogAllGroups ?? "全部",
          brandLabel: labels.manufacturer,
          upload: labels.upload,
          refreshTooltip: labels.refreshTooltip,
          noBrandHint: labels.noBrandHint,
          noMatchHint: labels.dialogNoMatch ?? "无匹配结果",
          loadingHint: labels.loadingHint,
          selectedCount: labels.selectedCount ?? "已选",
          deselectAll: labels.dialogDeselectAll ?? "清空",
          confirm: labels.dialogConfirm ?? "确认",
          cancel: labels.dialogCancel ?? "取消",
          brandInfo: labels.brandInfo,
          materialType: labels.materialType,
          vendor: labels.vendor,
        }}
      />
    </div>
  );
}
