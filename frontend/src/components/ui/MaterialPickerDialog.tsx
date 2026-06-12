import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import type { SavedMaterialLibraryItem } from "../../api/types";
import { useI18n } from "../../i18n/context";
import Button from "./Button";
import {
  cx,
  workstationChoiceRowActiveClass,
  workstationChoiceRowClass,
  workstationInputClass,
} from "./panelPrimitives";

interface MaterialPickerDialogProps {
  open: boolean;
  materials: SavedMaterialLibraryItem[];
  loading: boolean;
  initialSelected: string[];
  onConfirm: (selected: string[]) => void;
  onCancel: () => void;
}

const UNASSIGNED_BRAND_GROUP_KEY = "__unassigned__";

const getMaterialBrand = (item: SavedMaterialLibraryItem): string | null => {
  const brand = item.brand?.trim();
  return brand ? brand : null;
};

const getMaterialBrandGroupKey = (brand: string | null): string =>
  brand ?? UNASSIGNED_BRAND_GROUP_KEY;

type MaterialPickerBrandGroup = {
  brand: string | null;
  items: SavedMaterialLibraryItem[];
};

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
  const [query, setQuery] = useState<string>("");
  const [expandedBrandGroupKeys, setExpandedBrandGroupKeys] = useState<string[]>([]);

  // Re-sync staged selection whenever the dialog opens or upstream changes.
  useEffect(() => {
    if (open) {
      setStaged(initialSelected);
      setQuery("");
      setExpandedBrandGroupKeys([]);
    }
  }, [open, initialSelected]);

  const stagedSet = useMemo(() => new Set(staged), [staged]);

  // Filter materials by case-insensitive substring match against both the
  // user-facing material name and the directory name, so searches work for
  // localized names as well as internal identifiers.
  // 搜索同时匹配显示名与目录名，兼顾中英文名称与内部标识。
  const visibleMaterials = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return materials;
    return materials.filter((mat) => {
      const name = (mat.material_name ?? "").toLowerCase();
      const dir = (mat.directory_name ?? "").toLowerCase();
      return name.includes(q) || dir.includes(q);
    });
  }, [materials, query]);

  const visibleDirNames = useMemo(
    () => visibleMaterials.map((m) => m.directory_name),
    [visibleMaterials],
  );

  // Group visible materials by their brand (first path segment of
  // ``directory_name`` on the backend). Materials without a brand fall into
  // a single trailing group rendered with a localized "Unassigned" header.
  // 按品牌分组展示，未分组项统一归入末尾的"未分组"分组。
  const groupedVisibleMaterials = useMemo<MaterialPickerBrandGroup[]>(() => {
    const groups = new Map<string, SavedMaterialLibraryItem[]>();
    const unassigned: SavedMaterialLibraryItem[] = [];
    for (const mat of visibleMaterials) {
      const brand = getMaterialBrand(mat);
      if (brand) {
        const bucket = groups.get(brand);
        if (bucket) {
          bucket.push(mat);
        } else {
          groups.set(brand, [mat]);
        }
      } else {
        unassigned.push(mat);
      }
    }
    const result: MaterialPickerBrandGroup[] = [];
    for (const [brand, items] of groups) {
      result.push({ brand, items });
    }
    if (unassigned.length > 0) {
      result.push({ brand: null, items: unassigned });
    }
    return result;
  }, [visibleMaterials]);

  const allVisibleSelected =
    visibleDirNames.length > 0 &&
    visibleDirNames.every((name) => stagedSet.has(name));

  const toggle = (dirName: string) => {
    setStaged((previous) =>
      previous.includes(dirName)
        ? previous.filter((n) => n !== dirName)
        : [...previous, dirName],
    );
  };
  const toggleBrandGroupCollapsed = (groupKey: string) => {
    setExpandedBrandGroupKeys((previous) =>
      previous.includes(groupKey)
        ? previous.filter((item) => item !== groupKey)
        : [...previous, groupKey],
    );
  };

  // Select-all / clear-all operate on the currently visible subset so the
  // action stays predictable when the user has filtered the list.
  // 全选/清空只作用于当前过滤后的可见项，避免误操作被搜索隐藏的耗材。
  const selectAllVisible = () => {
    setStaged((previous) => {
      const merged = new Set(previous);
      for (const name of visibleDirNames) merged.add(name);
      return Array.from(merged);
    });
  };
  const clearAllVisible = () => {
    const visibleSet = new Set(visibleDirNames);
    setStaged((previous) => previous.filter((name) => !visibleSet.has(name)));
  };
  const deselectAll = () => {
    setStaged([]);
  };
  const handleConfirm = () => onConfirm(staged);

  const filterActive = query.trim().length > 0;
  const showEmpty = !loading && materials.length === 0;
  const showNoMatch = !loading && !showEmpty && visibleMaterials.length === 0;

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center backdrop-blur-sm"
      style={{ background: "var(--surface-scrim)" }}
      onClick={onCancel}
      data-testid="material-picker-dialog-overlay"
    >
      <div
        className="relative mx-4 grid w-full max-w-md overflow-hidden rounded-2xl border shadow-2xl"
        style={{
          borderColor: "var(--surface-outline)",
          background: "var(--surface-panel-strong)",
          height: "85vh",
          maxHeight: "42rem",
          gridTemplateRows: "auto auto minmax(0, 1fr) auto",
        }}
        onClick={(e) => e.stopPropagation()}
        data-testid="material-picker-dialog"
      >
        {/* Header */}
        <div className="row-start-1 flex items-start justify-between border-b border-slate-200 px-5 py-4 dark:border-slate-700">
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

        {/* Search */}
        {!showEmpty && (
          <div className="row-start-2 border-b border-slate-200 px-5 py-3 dark:border-slate-700">
            <div className="relative">
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("basic_material_picker_search_placeholder")}
                aria-label={t("basic_material_picker_search_placeholder")}
                className={`${workstationInputClass} pr-10`}
                data-testid="material-picker-search-input"
              />
              {filterActive && (
                <button
                  type="button"
                  onClick={() => setQuery("")}
                  aria-label={t("basic_material_picker_search_clear")}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300"
                  data-testid="material-picker-search-clear"
                >
                  ✕
                </button>
              )}
            </div>
          </div>
        )}

        {/* Body */}
        <div
          className="row-start-3 min-h-0 overflow-y-auto overscroll-contain px-5 py-4 [overflow-anchor:none]"
          data-testid="material-picker-scroll-area"
        >
          {loading ? (
            <div className="text-xs text-slate-400 dark:text-slate-500">
              {t("basic_material_loading")}
            </div>
          ) : showEmpty ? (
            <div className="text-xs text-slate-400 dark:text-slate-500">
              {t("basic_material_empty")}
            </div>
          ) : showNoMatch ? (
            <div
              className="text-xs text-slate-400 dark:text-slate-500"
              data-testid="material-picker-no-match"
            >
              {t("basic_material_picker_no_match")}
            </div>
          ) : (
            <div className="grid gap-3">
              {groupedVisibleMaterials.map(({ brand, items }) => {
                const groupKey = getMaterialBrandGroupKey(brand);
                const groupLabel = brand ?? t("basic_material_picker_brand_unassigned");
                const isExpanded = expandedBrandGroupKeys.includes(groupKey);
                const isCollapsed = !isExpanded;
                return (
                  <section
                    key={groupKey}
                    data-testid="material-picker-brand-group"
                    data-brand={brand ?? ""}
                    className="flex flex-col gap-1.5"
                  >
                    <button
                      type="button"
                      data-testid="material-picker-brand-group-toggle"
                      aria-expanded={!isCollapsed}
                      onClick={() => toggleBrandGroupCollapsed(groupKey)}
                      className="flex w-full items-center justify-between gap-2 rounded-xl border border-slate-200/80 px-2.5 py-1.5 text-left transition-colors hover:border-slate-300 hover:bg-slate-100/70 dark:border-slate-700/80 dark:hover:border-slate-600 dark:hover:bg-slate-800/70"
                    >
                      <span className="flex min-w-0 flex-wrap items-center gap-2">
                        <span className="truncate text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                          {groupLabel}
                        </span>
                        <span className="rounded-full border border-slate-200/80 px-2 py-0.5 text-[10px] font-semibold text-slate-500 dark:border-slate-700/80 dark:text-slate-400">
                          {items.length}
                        </span>
                      </span>
                      <svg
                        className={cx(
                          "h-4 w-4 shrink-0 text-slate-500 transition-transform dark:text-slate-400",
                          !isCollapsed && "rotate-90",
                        )}
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth={2}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden="true"
                      >
                        <polyline points="9 18 15 12 9 6" />
                      </svg>
                    </button>
                    {isCollapsed ? null : (
                      <div className="grid gap-2">
                    {items.map((mat) => {
                      const rgb =
                        Array.isArray(mat.estimated_rgb) && mat.estimated_rgb.length === 3
                          ? (mat.estimated_rgb as [number, number, number])
                          : null;
                      const checked = stagedSet.has(mat.directory_name);
                      const itemBrand = getMaterialBrand(mat);
                      const itemBrandLabel = itemBrand ?? t("basic_material_picker_brand_unassigned");
                      return (
                        <button
                          type="button"
                          key={mat.directory_name}
                          role="checkbox"
                          aria-checked={checked}
                          onClick={() => toggle(mat.directory_name)}
                          className={cx(
                            "flex w-full items-center gap-3 text-left text-sm hover:border-slate-300 hover:bg-white/75 dark:hover:border-slate-600 dark:hover:bg-slate-900/75",
                            workstationChoiceRowClass,
                            checked && workstationChoiceRowActiveClass,
                          )}
                        >
                          <span
                            aria-hidden="true"
                            className={cx(
                              "flex h-5 w-5 shrink-0 items-center justify-center rounded-xl border transition-all duration-200",
                              checked
                                ? "border-blue-500 bg-blue-500"
                                : "border-slate-300/80 bg-white dark:border-slate-600/80 dark:bg-slate-800",
                            )}
                          >
                            <span className={cx("h-2.5 w-2.5 rounded-sm", checked ? "bg-white" : "bg-transparent")} />
                          </span>
                          <span className="inline-flex items-center gap-1.5 font-medium text-slate-700 dark:text-slate-200">
                            {rgb && (
                              <span
                                className="inline-block size-3 shrink-0 rounded-full ring-1 ring-black/10 dark:ring-white/20"
                                style={{ backgroundColor: `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})` }}
                              />
                            )}
                            <span
                              data-testid="material-picker-brand-tag"
                              className="max-w-24 truncate rounded-full border border-slate-200/80 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-500 dark:border-slate-700/80 dark:text-slate-300"
                            >
                              {itemBrandLabel}
                            </span>
                            <span>{mat.material_name}</span>
                            {mat.mean_delta_e != null && (
                              <span className="text-[10px] text-slate-400 dark:text-slate-500">
                                {"\u0394E "}
                                {mat.mean_delta_e.toFixed(1)}
                              </span>
                            )}
                          </span>
                        </button>
                      );
                    })}
                      </div>
                    )}
                  </section>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="row-start-4 flex items-center justify-between gap-2 border-t border-slate-200 px-5 py-3 dark:border-slate-700">
          <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
            <button
              type="button"
              className="rounded px-2 py-1 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200 disabled:opacity-40"
              onClick={allVisibleSelected ? clearAllVisible : selectAllVisible}
              disabled={visibleMaterials.length === 0}
            >
              {allVisibleSelected
                ? t("basic_material_picker_clear")
                : t("basic_material_picker_select_all")}
            </button>
            <span>
              {t("basic_material_selected_count")}: {staged.length}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <Button
              label={t("basic_material_picker_deselect_all")}
              variant="secondary"
              onClick={deselectAll}
              disabled={staged.length === 0}
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
