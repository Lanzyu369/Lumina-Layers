import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { XMarkIcon } from "@heroicons/react/24/outline";
import Button from "./Button";
import {
  cx,
  workstationInputClass,
} from "./panelPrimitives";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LutPickerOption {
  /** Unique LUT name that flows back to the store. */
  value: string;
  /** Human-readable label shown in the list. */
  label: string;
  /** Color-mode group label, e.g. "4 色 RYBW". */
  group: string;
}

export interface LutPickerBrand {
  value: string;
  label: string;
  displayName?: string;
  materialTypes?: string[];
  vendor?: string;
}

interface LutPickerDialogProps {
  open: boolean;
  /** All available brands (manufacturer dropdown options). */
  brands: LutPickerBrand[];
  /** All available LUT options for the currently selected brand. */
  lutOptions: LutPickerOption[];
  /** Currently selected brand value. */
  selectedBrand: string;
  /** Currently selected LUT name(s) — used to initialise staged state. */
  initialSelectedLuts: string[];
  onBrandChange: (brand: string) => void;
  onConfirm: (lutNames: string[]) => void;
  onCancel: () => void;
  onUploadClick: () => void;
  onRefresh: () => void;
  loading?: boolean;
  lutLoading?: boolean;
  refreshing?: boolean;
  labels: {
    title: string;
    searchPlaceholder: string;
    allGroups: string;
    brandLabel: string;
    upload: string;
    refreshTooltip: string;
    noBrandHint: string;
    noMatchHint: string;
    loadingHint: string;
    selectedCount: string;
    deselectAll: string;
    confirm: string;
    cancel: string;
    brandInfo?: string;
    materialType?: string;
    vendor?: string;
  };
}

// ---------------------------------------------------------------------------
// Focus trap
// ---------------------------------------------------------------------------

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "[href]",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function LutPickerDialog({
  open,
  brands,
  lutOptions,
  selectedBrand,
  initialSelectedLuts,
  onBrandChange,
  onConfirm,
  onCancel,
  onUploadClick,
  onRefresh,
  loading = false,
  lutLoading = false,
  refreshing = false,
  labels,
}: LutPickerDialogProps) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  // Held in a ref so the open effect can read the latest selection without
  // re-running (and re-focusing) on every parent render.
  const initialSelectedRef = useRef(initialSelectedLuts);
  initialSelectedRef.current = initialSelectedLuts;

  const [staged, setStaged] = useState<string[]>(initialSelectedLuts);
  const [query, setQuery] = useState("");
  const [groupFilter, setGroupFilter] = useState<string>("all");

  // Reset state when dialog opens
  useEffect(() => {
    if (!open) return undefined;

    previouslyFocusedRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;

    setStaged(initialSelectedRef.current);
    setQuery("");
    setGroupFilter("all");

    const timer = window.setTimeout(() => {
      searchRef.current?.focus();
    }, 0);

    return () => {
      window.clearTimeout(timer);
      previouslyFocusedRef.current?.focus();
    };
  }, [open]);

  // Keyboard: Escape → cancel; Tab → trap focus inside dialog
  useEffect(() => {
    if (!open) return undefined;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
        return;
      }
      if (e.key !== "Tab") return;
      const container = dialogRef.current;
      if (!container) return;
      const focusable = Array.from(
        container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      );
      if (focusable.length === 0) {
        e.preventDefault();
        container.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      } else if (!container.contains(active)) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onCancel]);

  // Derive unique groups for the filter bar
  const allGroups = useMemo(() => {
    const seen = new Set<string>();
    const result: string[] = [];
    for (const opt of lutOptions) {
      if (!seen.has(opt.group)) {
        seen.add(opt.group);
        result.push(opt.group);
      }
    }
    return result;
  }, [lutOptions]);

  // Selected brand meta
  const selectedBrandMeta = useMemo(
    () => brands.find((b) => b.value === selectedBrand) ?? null,
    [brands, selectedBrand],
  );

  // Filtered options by search + group
  const visibleOptions = useMemo(() => {
    const q = query.trim().toLowerCase();
    return lutOptions.filter((opt) => {
      const matchGroup = groupFilter === "all" || opt.group === groupFilter;
      const matchQuery = q === "" || opt.label.toLowerCase().includes(q);
      return matchGroup && matchQuery;
    });
  }, [lutOptions, query, groupFilter]);

  // Staged set for O(1) lookup
  const stagedSet = useMemo(() => new Set(staged), [staged]);

  // Brand navigation changes only the visible list, not the staged selection.
  useEffect(() => {
    setQuery("");
    setGroupFilter("all");
  }, [selectedBrand]);

  const handleToggle = (value: string) => {
    setStaged((prev) => {
      return prev.includes(value)
        ? prev.filter((name) => name !== value)
        : [...prev, value];
    });
  };

  if (!open) return null;

  const lutDisabled = loading || lutLoading || !selectedBrand;

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  return createPortal(
    <div
      role="presentation"
      className="fixed inset-0 z-[9999] flex items-center justify-center p-3 backdrop-blur-sm sm:p-5"
      style={{ background: "var(--surface-scrim)" }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        data-testid="lut-picker-dialog"
        className="flex w-[min(52rem,calc(100vw-1.5rem))] flex-col overflow-hidden rounded-[28px] border shadow-2xl"
        style={{
          maxHeight: "calc(100vh - 3rem)",
          borderColor: "var(--surface-outline)",
          background: "var(--surface-panel-strong)",
        }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* ---- Header ---- */}
        <div className="flex items-center justify-between border-b px-5 py-4" style={{ borderColor: "var(--surface-outline)" }}>
          <h2
            id={titleId}
            className="text-base font-semibold text-slate-900 dark:text-slate-50"
          >
            {labels.title}
          </h2>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onRefresh}
              disabled={refreshing || loading}
              aria-label={labels.refreshTooltip}
              title={labels.refreshTooltip}
              className="action-control inline-flex h-8 w-8 items-center justify-center rounded-full text-slate-500 dark:text-slate-400"
            >
              <span className={cx("text-sm leading-none", refreshing && "animate-spin")} aria-hidden="true">⟳</span>
            </button>
            <button
              type="button"
              onClick={onCancel}
              aria-label={labels.cancel}
              className="ghost-control inline-flex h-8 w-8 items-center justify-center rounded-full text-slate-500 dark:text-slate-400"
            >
              <XMarkIcon className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </div>

        {/* ---- Body: sidebar + main ---- */}
        <div className="flex min-h-0 flex-1">
          {/* Brand sidebar */}
          <aside
            data-testid="lut-picker-brand-sidebar"
            className="dock-scrollbar flex w-44 shrink-0 flex-col gap-1 overflow-y-auto border-r p-3"
            style={{ borderColor: "var(--surface-outline)" }}
          >
            <p className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
              {labels.brandLabel}
            </p>
            <div className="flex flex-col gap-0.5">
              {brands.map((brand) => {
                const isSelected = brand.value === selectedBrand;
                return (
                  <button
                    key={brand.value}
                    type="button"
                    data-testid={`lut-picker-brand-option-${brand.value}`}
                    onClick={() => {
                      onBrandChange(brand.value);
                      setGroupFilter("all");
                      setQuery("");
                    }}
                    className={cx(
                      "w-full rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors duration-100",
                      "focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--focus-ring)]",
                      isSelected
                        ? "bg-blue-50 font-medium text-blue-700 dark:bg-blue-500/15 dark:text-blue-200"
                        : "text-slate-700 hover:bg-[var(--nav-chip-hover)] dark:text-slate-300",
                    )}
                  >
                    <span className="block truncate">{brand.label}</span>
                  </button>
                );
              })}
            </div>

            {/* Upload */}
            <div className="mt-2 border-t pt-2" style={{ borderColor: "var(--surface-outline)" }}>
              <button
                type="button"
                onClick={onUploadClick}
                className="action-control w-full rounded-lg px-2.5 py-1.5 text-left text-sm text-slate-600 dark:text-slate-400"
              >
                {labels.upload}
              </button>
            </div>
          </aside>

          {/* Main content */}
          <div className="flex min-w-0 flex-1 flex-col">
            {/* Search + group filter bar */}
            <div className="flex items-center gap-2 border-b px-4 py-3" style={{ borderColor: "var(--surface-outline)" }}>
              <input
                ref={searchRef}
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={labels.searchPlaceholder}
                disabled={!selectedBrand}
                data-testid="lut-picker-search-input"
                className={cx(workstationInputClass, "min-h-9 py-1.5 text-sm")}
              />
            </div>

            {/* Group filter tabs */}
            {allGroups.length > 1 && (
              <div
                className="flex gap-1 overflow-x-auto border-b px-4 py-2"
                style={{ borderColor: "var(--surface-outline)" }}
                role="tablist"
                aria-label={labels.allGroups}
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={groupFilter === "all"}
                  onClick={() => setGroupFilter("all")}
                  className={cx(
                    "shrink-0 rounded-lg px-3 py-1 text-xs font-medium transition-colors",
                    groupFilter === "all"
                      ? "bg-blue-50 text-blue-700 dark:bg-blue-500/15 dark:text-blue-200"
                      : "text-slate-600 hover:bg-[var(--nav-chip-hover)] dark:text-slate-400",
                  )}
                >
                  {labels.allGroups}
                </button>
                {allGroups.map((g) => (
                  <button
                    key={g}
                    type="button"
                    role="tab"
                    aria-selected={groupFilter === g}
                    onClick={() => setGroupFilter(g)}
                    className={cx(
                      "shrink-0 rounded-lg px-3 py-1 text-xs font-medium transition-colors",
                      groupFilter === g
                        ? "bg-blue-50 text-blue-700 dark:bg-blue-500/15 dark:text-blue-200"
                        : "text-slate-600 hover:bg-[var(--nav-chip-hover)] dark:text-slate-400",
                    )}
                  >
                    {g}
                  </button>
                ))}
              </div>
            )}

            {/* LUT list */}
            <div className="dock-scrollbar min-h-0 flex-1 overflow-y-auto overscroll-contain p-4">
              {loading || lutLoading ? (
                <p className="flex min-h-32 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
                  {labels.loadingHint}
                </p>
              ) : !selectedBrand ? (
                <p className="flex min-h-32 items-center justify-center text-center text-sm text-slate-500 dark:text-slate-400">
                  {labels.noBrandHint}
                </p>
              ) : visibleOptions.length === 0 ? (
                <p
                  data-testid="lut-picker-no-match"
                  className="flex min-h-32 items-center justify-center text-sm text-slate-500 dark:text-slate-400"
                >
                  {labels.noMatchHint}
                </p>
              ) : (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {visibleOptions.map((opt) => {
                    const checked = stagedSet.has(opt.value);
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        role="checkbox"
                        aria-checked={checked}
                        disabled={lutDisabled}
                        onClick={() => handleToggle(opt.value)}
                        data-testid="lut-picker-option"
                        className={cx(
                          "flex items-center gap-3 rounded-[14px] border px-3.5 py-2.5 text-left text-sm transition-all duration-150",
                          "focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
                          "disabled:cursor-not-allowed disabled:opacity-45",
                          checked
                            ? "border-blue-300/80 bg-blue-50/60 dark:border-blue-400/60 dark:bg-blue-500/10"
                            : "border-slate-200/80 bg-white/60 hover:border-[color:var(--surface-card-outline)] hover:bg-[var(--nav-chip-hover)] dark:border-slate-700/80 dark:bg-slate-900/55",
                        )}
                      >
                        {/* Checkbox indicator */}
                        <span
                          aria-hidden="true"
                          className={cx(
                            "flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-all duration-200",
                            checked
                              ? "border-blue-500 bg-blue-500"
                              : "border-slate-300/80 bg-white dark:border-slate-600/80 dark:bg-slate-800",
                          )}
                        >
                          <span className={cx("h-2.5 w-2.5 rounded-sm", checked ? "bg-white" : "bg-transparent")} />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-medium text-slate-800 dark:text-slate-100">
                            {opt.label}
                          </span>
                          <span className="block truncate text-[11px] text-slate-500 dark:text-slate-400">
                            {opt.group}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Brand meta summary */}
            {selectedBrandMeta && (selectedBrandMeta.materialTypes?.length || selectedBrandMeta.vendor) && (
              <div className="border-t px-4 py-2.5" style={{ borderColor: "var(--surface-outline)" }}>
                <p className="flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-slate-500 dark:text-slate-400">
                  {selectedBrandMeta.displayName && (
                    <span>
                      {labels.brandInfo ?? "Brand"}: <span className="text-slate-700 dark:text-slate-300">{selectedBrandMeta.displayName}</span>
                    </span>
                  )}
                  {(selectedBrandMeta.materialTypes ?? []).length > 0 && (
                    <span>
                      {labels.materialType ?? "Material"}: <span className="text-slate-700 dark:text-slate-300">{(selectedBrandMeta.materialTypes ?? []).join(", ")}</span>
                    </span>
                  )}
                  {selectedBrandMeta.vendor && (
                    <span>
                      {labels.vendor ?? "Vendor"}: <span className="text-slate-700 dark:text-slate-300">{selectedBrandMeta.vendor}</span>
                    </span>
                  )}
                </p>
              </div>
            )}
          </div>
        </div>

        {/* ---- Footer ---- */}
        <div className="flex items-center justify-between gap-3 border-t px-5 py-3" style={{ borderColor: "var(--surface-outline)" }}>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            <span aria-live="polite">
              {labels.selectedCount}: <span className="font-semibold text-slate-800 dark:text-slate-200">{staged.length}</span>
            </span>
          </p>
          <div className="flex items-center gap-2">
            <Button
              label={labels.deselectAll}
              onClick={() => setStaged([])}
              disabled={staged.length === 0}
              variant="primary"
              size="sm"
            />
            <Button
              label={labels.confirm}
              onClick={() => onConfirm(staged)}
              size="sm"
            />
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
