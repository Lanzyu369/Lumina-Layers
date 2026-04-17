import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import type { SavedMaterialLibraryItem } from "../../api/types";
import { useI18n } from "../../i18n/context";
import Button from "./Button";
import Checkbox from "./Checkbox";

interface MaterialPickerDialogProps {
  open: boolean;
  materials: SavedMaterialLibraryItem[];
  loading: boolean;
  initialSelected: string[];
  onConfirm: (selected: string[]) => void;
  onCancel: () => void;
}

/**
 * Material selection modal dialog.
 * 耗材选择弹窗。
 *
 * Renders the available materials as a checkbox list inside a modal so the
 * caller can show only a compact summary in the parent component. Selection
 * is staged locally and only committed when the user confirms.
 */
export default function MaterialPickerDialog({
  open,
  materials,
  loading,
  initialSelected,
  onConfirm,
  onCancel,
}: MaterialPickerDialogProps) {
  const { t } = useI18n();
  const [staged, setStaged] = useState<string[]>(initialSelected);

  // Re-sync staged selection whenever the dialog opens or upstream changes.
  useEffect(() => {
    if (open) {
      setStaged(initialSelected);
    }
  }, [open, initialSelected]);

  const stagedSet = useMemo(() => new Set(staged), [staged]);
  const allDirNames = useMemo(
    () => materials.map((m) => m.directory_name),
    [materials],
  );
  const allSelected = allDirNames.length > 0 && allDirNames.every((name) => stagedSet.has(name));

  const toggle = (dirName: string) => {
    setStaged((previous) =>
      previous.includes(dirName)
        ? previous.filter((n) => n !== dirName)
        : [...previous, dirName],
    );
  };

  const selectAll = () => setStaged(allDirNames);
  const clearAll = () => setStaged([]);
  const handleConfirm = () => onConfirm(staged);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center backdrop-blur-sm"
      style={{ background: "var(--surface-scrim)" }}
      onClick={onCancel}
      data-testid="material-picker-dialog-overlay"
    >
      <div
        className="relative mx-4 flex max-h-[85vh] w-full max-w-md flex-col overflow-hidden rounded-2xl border shadow-2xl"
        style={{
          borderColor: "var(--surface-outline)",
          background: "var(--surface-panel-strong)",
        }}
        onClick={(e) => e.stopPropagation()}
        data-testid="material-picker-dialog"
      >
        {/* Header */}
        <div className="flex items-start justify-between border-b border-slate-200 px-5 py-4 dark:border-slate-700">
          <div className="flex flex-col gap-1">
            <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">
              {t("basic_material_picker_dialog_title")}
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {t("basic_material_picker_dialog_subtitle")}
            </p>
          </div>
          <button
            type="button"
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300"
            onClick={onCancel}
            aria-label={t("basic_material_picker_close")}
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading ? (
            <div className="text-xs text-slate-400 dark:text-slate-500">
              {t("basic_material_loading")}
            </div>
          ) : materials.length === 0 ? (
            <div className="text-xs text-slate-400 dark:text-slate-500">
              {t("basic_material_empty")}
            </div>
          ) : (
            <div className="grid gap-2">
              {materials.map((mat) => {
                const rgb =
                  Array.isArray(mat.estimated_rgb) && mat.estimated_rgb.length === 3
                    ? (mat.estimated_rgb as [number, number, number])
                    : null;
                return (
                  <Checkbox
                    key={mat.directory_name}
                    label={
                      <span className="inline-flex items-center gap-1.5">
                        {rgb && (
                          <span
                            className="inline-block size-3 rounded-full shrink-0 ring-1 ring-black/10 dark:ring-white/20"
                            style={{ backgroundColor: `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})` }}
                          />
                        )}
                        <span>{mat.material_name}</span>
                        {mat.mean_delta_e != null && (
                          <span className="text-[10px] text-slate-400 dark:text-slate-500">
                            {"\u0394E "}
                            {mat.mean_delta_e.toFixed(1)}
                          </span>
                        )}
                      </span>
                    }
                    checked={stagedSet.has(mat.directory_name)}
                    onChange={() => toggle(mat.directory_name)}
                  />
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-2 border-t border-slate-200 px-5 py-3 dark:border-slate-700">
          <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
            <button
              type="button"
              className="rounded px-2 py-1 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200 disabled:opacity-40"
              onClick={allSelected ? clearAll : selectAll}
              disabled={materials.length === 0}
            >
              {allSelected
                ? t("basic_material_picker_clear")
                : t("basic_material_picker_select_all")}
            </button>
            <span>
              {t("basic_material_selected_count")}: {staged.length}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <Button
              label={t("basic_material_picker_close")}
              variant="secondary"
              onClick={onCancel}
              className="px-4"
            />
            <Button
              label={t("basic_material_picker_done")}
              variant="primary"
              onClick={handleConfirm}
              className="px-4"
            />
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
