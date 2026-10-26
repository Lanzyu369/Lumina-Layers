import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { getMachineRegistryAssetUrl } from "../../api/system";
import type { PrinterInfo, SlicerOption } from "../../api/types";
import { useI18n } from "../../i18n/context";
import { getPrinterNozzleSizeOptions } from "../../utils/settingsOptionIds";
import SlicerLogo from "../slicer/SlicerLogo";
import Button from "../ui/Button";
import Dropdown from "../ui/Dropdown";
import {
  cx,
  workstationInputClass,
} from "../ui/panelPrimitives";

interface MachineSelectionDialogProps {
  open: boolean;
  printers: PrinterInfo[];
  slicers: SlicerOption[];
  printersLoading: boolean;
  slicersLoading: boolean;
  slicerSoftware: string;
  printerModel: string;
  nozzleSize: string;
  onSlicerChange: (id: string) => void;
  onPrinterChange: (id: string) => void;
  onPrinterNozzleChange: (printer: PrinterInfo, value: string) => void;
  onClose: () => void;
}

type PrinterBrandGroup = {
  brand: string;
  printers: PrinterInfo[];
};

function getMachinePlaceholderLabel(printer: PrinterInfo): string {
  const compactBrand = printer.brand.replace(/\s+/g, "");
  return (compactBrand || printer.display_name).slice(0, 2).toUpperCase();
}

/**
 * Searchable machine registry dialog used by system settings.
 * 系统设置使用的可搜索机器选择弹窗。
 */
export default function MachineSelectionDialog({
  open,
  printers,
  slicers,
  printersLoading,
  slicersLoading,
  slicerSoftware,
  printerModel,
  nozzleSize,
  onSlicerChange,
  onPrinterChange,
  onPrinterNozzleChange,
  onClose,
}: MachineSelectionDialogProps) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    setQuery("");
    searchInputRef.current?.focus();

    return () => {
      previousFocusRef.current?.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }

      if (event.key === "Tab" && dialogRef.current) {
        const focusableElements = dialogRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        if (focusableElements.length === 0) return;

        const firstFocusableElement = focusableElements[0];
        const lastFocusableElement =
          focusableElements[focusableElements.length - 1];

        if (event.shiftKey && document.activeElement === firstFocusableElement) {
          event.preventDefault();
          lastFocusableElement.focus();
        } else if (
          !event.shiftKey &&
          document.activeElement === lastFocusableElement
        ) {
          event.preventDefault();
          firstFocusableElement.focus();
        }
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose, open]);

  const visiblePrinters = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    if (!normalizedQuery) return printers;
    return printers.filter((printer) =>
      `${printer.brand} ${printer.display_name}`
        .toLocaleLowerCase()
        .includes(normalizedQuery),
    );
  }, [printers, query]);

  const groupedPrinters = useMemo<PrinterBrandGroup[]>(() => {
    const groups = new Map<string, PrinterInfo[]>();
    for (const printer of visiblePrinters) {
      const current = groups.get(printer.brand);
      if (current) {
        current.push(printer);
      } else {
        groups.set(printer.brand, [printer]);
      }
    }
    return Array.from(groups, ([brand, grouped]) => ({
      brand,
      printers: grouped,
    }));
  }, [visiblePrinters]);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center p-3 backdrop-blur-sm sm:p-5"
      style={{ background: "var(--surface-scrim)" }}
      onClick={onClose}
      data-testid="machine-selection-dialog-overlay"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="machine-selection-dialog-title"
        aria-describedby="machine-selection-dialog-description"
        data-testid="machine-selection-dialog"
        onClick={(event) => event.stopPropagation()}
      >
          <div className="min-w-0">
            <h2
              id="machine-selection-dialog-title"
            >
              {t("settings.machine_dialog_title")}
            </h2>
            <p
              id="machine-selection-dialog-description"
              className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400"
            >
              {t("settings.machine_dialog_description")}
            </p>
          </div>
        </header>

          <Dropdown
            label={t("settings.slicer_software")}
            value={slicerSoftware}
            onChange={onSlicerChange}
            disabled={slicersLoading}
            options={slicers.map((slicer) => ({
              label: slicer.display_name,
              value: slicer.id,
              leading: <SlicerLogo slicerId={slicer.id} />,
            }))}
          />
          <div className="flex min-w-0 flex-col gap-1.5">
            <label
              htmlFor="machine-selection-search"
              className="text-sm font-medium text-slate-700 dark:text-slate-200"
            >
              {t("settings.machine_search_label")}
            </label>
            <input
              ref={searchInputRef}
              id="machine-selection-search"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              aria-label={t("settings.machine_search_label")}
              placeholder={t("settings.machine_search_placeholder")}
              className={workstationInputClass}
            />
          </div>
        </div>

        <div
          data-testid="machine-adapter-grid"
          className="dock-scrollbar min-h-0 overflow-y-auto overscroll-contain px-4 py-4 sm:px-6"
        >
          {printersLoading ? (
            <p className="text-sm text-slate-500 dark:text-slate-400">
              {t("settings.machine_options_loading")}
            </p>
          ) : groupedPrinters.length === 0 ? (
              <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
                {t("settings.machine_search_empty")}
              </p>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                {t("settings.machine_search_empty_hint")}
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-5">
              {groupedPrinters.map((group) => (
                <section key={group.brand} className="flex flex-col gap-2.5">
                  <div className="flex items-center gap-2">
                    <h3 className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {group.brand}
                    </h3>
                      {group.printers.length}
                    </span>
                  </div>
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {group.printers.map((printer) => {
                      const isSelected = printer.id === printerModel;
                      const thumbnailUrl = printer.thumbnail
                        ? getMachineRegistryAssetUrl(printer.thumbnail)
                        : null;
                      const nozzleOptions = getPrinterNozzleSizeOptions(
                        printer,
                        slicerSoftware,
                      );

                      return (
                        <div
                          key={printer.id}
                          className={cx(
                            isSelected
                          )}
                        >
                          <button
                            type="button"
                            aria-pressed={isSelected}
                            data-testid={`machine-adapter-card-${printer.id}`}
                            onClick={() => onPrinterChange(printer.id)}
                            disabled={printersLoading}
                          >
                            <span
                              className={cx(
                                "flex aspect-square w-[5.5rem] items-center justify-center overflow-hidden",
                                thumbnailUrl
                                  ? "rounded-none bg-transparent"
                              )}
                            >
                              {thumbnailUrl ? (
                                <img
                                  src={thumbnailUrl}
                                  alt={printer.display_name}
                                  className="h-full w-full object-contain p-0"
                                  loading="lazy"
                                />
                              ) : (
                                <span className="text-lg font-semibold text-slate-400 dark:text-slate-500">
                                  {getMachinePlaceholderLabel(printer)}
                                </span>
                              )}
                            </span>
                            <span className="flex min-w-0 flex-col gap-1.5">
                              <span className="truncate text-sm font-semibold text-slate-900 dark:text-slate-50">
                                {printer.display_name}
                              </span>
                              <span className="text-xs text-slate-500 dark:text-slate-400">
                                {printer.brand}
                              </span>
                              <span className="text-xs text-slate-500 dark:text-slate-400">
                                {t("settings.bed_size")}: {printer.bed_width}
                                &times;{printer.bed_depth} {t("common_unit_mm")}
                              </span>
                              <span className="text-xs text-slate-500 dark:text-slate-400">
                                {t("settings.nozzle_size")}:{" "}
                                {nozzleOptions
                                  .map(
                                    (size) =>
                                      `${size} ${t("common_unit_mm")}`,
                                  )
                                  .join(", ")}
                              </span>
                            </span>
                          </button>
                            {nozzleOptions.map((size) => {
                              const isNozzleSelected =
                                isSelected && size === nozzleSize;
                              return (
                                <button
                                  key={size}
                                  type="button"
                                  aria-pressed={isNozzleSelected}
                                  aria-label={`${printer.display_name} ${size} ${t("common_unit_mm")}`}
                                  data-testid={`machine-adapter-nozzle-${printer.id}-${size.replace(/\./g, "_")}`}
                                  onClick={() =>
                                    onPrinterNozzleChange(printer, size)
                                  }
                                  disabled={printersLoading}
                                  className={cx(
                                    isNozzleSelected
                                  )}
                                >
                                  {size} {t("common_unit_mm")}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
          )}
        </div>

          <Button
            label={t("settings.machine_dialog_done")}
            onClick={onClose}
          />
        </footer>
      </div>
    </div>,
    document.body,
  );
}
