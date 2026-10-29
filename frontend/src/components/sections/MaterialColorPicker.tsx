import { useState, useCallback, useMemo, memo } from "react";
import { useConverterStore } from "../../stores/converter";
import { useI18n } from "../../i18n/context";
import { cx, StatusBanner, cardClass, compactFieldClass, wellPadClass } from "../ui/panelPrimitives";
import type { MaterialColorSuggestionItem } from "../../api/types";
import GradientGroupsPanel from "./GradientGroupsPanel";

/**
 * Material-archive color picker.
 * 材料档案模式下的颜色拾取器。
 *
 * Replaces the LUT swatch grid when ``source_version === "material"``: the
 * LUT palette does not exist in material-archive mode, so we let the user
 * pick any target color (native ``<input type="color">`` + hex entry), send
 * it to ``/api/extractor/material-solver-cache/suggest-colors``, and render
 * the returned ``top_k`` achievable-color candidates as clickable swatches
 * that drive the same ``setPendingReplacement`` flow used by LutColorGrid.
 */
export default function MaterialColorPicker() {
  const { t } = useI18n();

  const selectedColor = useConverterStore((s) => s.selectedColor);
  const selectionDocument = useConverterStore((s) => s.selectionDocument);
  const hasPendingSelection = useConverterStore((s) => Boolean(s.sessionId &&
    s.pendingSelectionMutations.some((mutation) => mutation.sessionId === s.sessionId)));
  const selectedMaterialDirNames = useConverterStore(
    (s) => s.selectedMaterialDirNames,
  );
  const suggestions = useConverterStore((s) => s.materialSuggestions);
  const loading = useConverterStore((s) => s.materialSuggestionsLoading);
  const targetHex = useConverterStore((s) => s.materialSuggestionsTargetHex);
  const error = useConverterStore((s) => s.materialSuggestionsError);
  const fetchSuggestions = useConverterStore((s) => s.fetchMaterialSuggestions);
  const selectionMode = useConverterStore((s) => s.selectionMode);
  const selectedColors = useConverterStore((s) => s.selectedColors);
  const selectedRegions = useConverterStore((s) => s.selectedRegions);
  const replacePreviewLoading = useConverterStore((s) => s.replacePreviewLoading);
  const setPendingReplacement = useConverterStore((s) => s.setPendingReplacement);
  const pendingReplacement = useConverterStore((s) => s.pendingReplacement);
  const confirmReplacement = useConverterStore((s) => s.confirmReplacement);

  // Seed the local target input from the currently selected source color so
  // a quick "replace with something close" flow is one click away.
  // 初始目标色默认填入当前选中的源色，便于快速"替换成接近的颜色"。
  const initialTarget = useMemo(() => {
    if (selectedColor) return `#${selectedColor.replace(/^#/, "")}`;
    return "#888888";
  }, [selectedColor]);

  const hasMaterials = (selectedMaterialDirNames ?? []).length > 0;

  const stagePendingReplacement = useCallback(
    (target: string, options: { requireSource: boolean } = { requireSource: true }) => {
      const hexNoHash = target.replace(/^#/, "").toLowerCase();
      if (hasPendingSelection || (selectionDocument && selectionDocument.selected_component_count > 0)) {
        setPendingReplacement({
          sourceHex: selectedColor ?? "",
          targetHex: hexNoHash,
          mode: "multi-select",
          sourceRegions: [...selectedRegions],
        });
        return true;
      }
      switch (selectionMode) {
        case "select-all": {
          const colors =
            selectedColors.size > 0
              ? Array.from(selectedColors)
              : selectedColor
                ? [selectedColor]
                : [];
          if (colors.length === 0) return false;
          setPendingReplacement({
            sourceHex: colors[0],
            targetHex: hexNoHash,
            mode: "select-all",
            sourceColors: colors.length > 1 ? colors : undefined,
          });
          return true;
        }
        case "multi-select": {
          if (selectedRegions.length === 0) return false;
          setPendingReplacement({
            sourceHex: selectedColor ?? "",
            targetHex: hexNoHash,
            mode: "multi-select",
            sourceRegions: [...selectedRegions],
          });
          return true;
        }
        case "current":
        case "region": {
          if (options.requireSource && !selectedColor) return false;
          setPendingReplacement({
            sourceHex: selectedColor ?? "",
            targetHex: hexNoHash,
            mode: selectionMode,
          });
          return true;
        }
      }
    },
    [
      hasPendingSelection,
      selectionDocument,
      selectionMode,
      selectedColors,
      selectedRegions,
      selectedColor,
      setPendingReplacement,
    ],
  );

  const handleSubmitTarget = useCallback(
    async (normalizedTarget: string) => {
      if (!hasMaterials) return;
      await fetchSuggestions(normalizedTarget);
      const nextState = useConverterStore.getState();
      const firstSuggestion =
        nextState.materialSuggestionsError == null &&
        nextState.materialSuggestionsTargetHex === normalizedTarget
          ? nextState.materialSuggestions?.suggestions[0]
          : null;
      const staged = firstSuggestion
        ? stagePendingReplacement(firstSuggestion.hex)
        : false;
      if (!staged) {
        setPendingReplacement(null);
      }
    },
    [
      fetchSuggestions,
      hasMaterials,
      stagePendingReplacement,
      setPendingReplacement,
    ],
  );

  const handleSuggestionClick = useCallback(
    (item: MaterialColorSuggestionItem) => {
      if (replacePreviewLoading) return;
      stagePendingReplacement(item.hex, { requireSource: false });
    },
    [
      replacePreviewLoading,
      stagePendingReplacement,
    ],
  );

  return (
    <div className="relative h-full">
      {replacePreviewLoading && (
        <div className="absolute inset-0 z-10 flex items-center justify-center rounded-2xl bg-slate-950/40">
          <p className="text-xs text-slate-100">{t("lut_grid_loading")}</p>
        </div>
      )}
      <div className={cx(cardClass, "panel-default-surface flex h-full flex-col gap-3 px-4 py-4")}>
        {/* Pending replacement bar — mirrors LutColorGrid for consistent UX */}
        {pendingReplacement && (
          <div className={cx(wellPadClass, "flex flex-col gap-2")}>
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              <div className="flex min-w-0 flex-wrap items-center gap-0.5">
                {pendingReplacement.mode === "select-all" &&
                pendingReplacement.sourceColors &&
                pendingReplacement.sourceColors.length > 1 ? (
                  pendingReplacement.sourceColors.map((hex) => (
                    <span
                      key={hex}
                      className="inline-block h-5 w-5 rounded-md border border-slate-400/80 dark:border-slate-500/80"
                      style={{ backgroundColor: `#${hex}` }}
                      title={`#${hex}`}
                    />
                  ))
                ) : pendingReplacement.mode === "multi-select" &&
                  pendingReplacement.sourceRegions ? (
                  pendingReplacement.sourceRegions.map((region) => {
                    const hex = region.colorHex.replace(/^#/, "");
                    return (
                      <span
                        key={region.regionId}
                        className="inline-block h-5 w-5 rounded-md border border-slate-400/80 dark:border-slate-500/80"
                        style={{ backgroundColor: `#${hex}` }}
                        title={`#${hex} (${region.pixelCount}px)`}
                      />
                    );
                  })
                ) : (
                  <span
                    className="inline-block h-5 w-5 rounded-md border border-slate-400/80 dark:border-slate-500/80"
                    style={{ backgroundColor: `#${pendingReplacement.sourceHex}` }}
                    title={`#${pendingReplacement.sourceHex}`}
                  />
                )}
              </div>
              <span className="text-xs text-slate-400">→</span>
              <span
                className="inline-block h-5 w-5 shrink-0 rounded-md border border-slate-400/80 dark:border-slate-500/80"
                style={{ backgroundColor: `#${pendingReplacement.targetHex}` }}
                title={`#${pendingReplacement.targetHex}`}
              />
            </div>
            <div className="flex flex-wrap justify-end gap-1.5">
              <button
                type="button"
                onClick={() => confirmReplacement()}
                className="action-control rounded-full px-2.5 py-1 text-[10px] font-medium transition-colors"
              >
                {t("replace_confirm_btn")}
              </button>
              <button
                type="button"
                onClick={() => setPendingReplacement(null)}
                className="ghost-control rounded-full px-2.5 py-1 text-[10px] font-medium text-slate-700 dark:text-slate-200"
              >
                {t("replace_cancel_btn")}
              </button>
            </div>
          </div>
        )}

        {/* Header: title + hint */}
        <div className="flex flex-col gap-0.5">
          <h4 className="text-[clamp(0.7rem,0.85vw,0.75rem)] font-semibold text-slate-700 dark:text-slate-200">
            {t("material_picker_title")}
          </h4>
          <p className="text-[clamp(0.6rem,0.75vw,0.65rem)] leading-tight text-slate-500 dark:text-slate-400">
            {t("material_picker_hint")}
          </p>
        </div>

        {/* Gradient banding groups (material-archive only; self-hides if none). */}
        <GradientGroupsPanel />

        {/* No-material guard */}
        {!hasMaterials ? (
          <p className="py-4 text-sm text-slate-500 dark:text-slate-400">
            {t("material_picker_no_material")}
          </p>
        ) : (
          <>
            {/* Target color input row */}
            <TargetColorInputRow
              initialTarget={initialTarget}
              loading={loading}
              onSubmit={handleSubmitTarget}
            />

            {/* Status line — source + count, after a successful response */}
            {suggestions && (
              <p className="text-[clamp(0.6rem,0.75vw,0.65rem)] text-slate-500 dark:text-slate-400">
                {t("material_picker_result_count").replace(
                  "{count}",
                  String(suggestions.suggestions.length),
                )}
                {" · "}
                <span className="font-mono">{suggestions.target_hex}</span>
                {" · "}
                <span
                  className={
                    suggestions.source === "cache"
                      ? "text-emerald-500"
                      : suggestions.source === "runtime"
                        ? "text-sky-500"
                      : "text-amber-500"
                  }
                >
                  {suggestions.source === "cache"
                    ? t("material_picker_source_cache")
                    : suggestions.source === "runtime"
                      ? t("material_picker_source_runtime")
                    : t("material_picker_source_mitm")}
                </span>
              </p>
            )}

            {/* Error line */}
            {error && (
              <StatusBanner role="alert" tone="error">
                {t("material_picker_error").replace("{message}", error)}
              </StatusBanner>
            )}

            {/* Loading / empty / grid */}
            {loading ? (
              <p className="py-4 text-sm text-slate-500 dark:text-slate-400">
                {t("material_picker_loading")}
              </p>
            ) : suggestions && suggestions.suggestions.length > 0 ? (
              <div
                className="dock-scrollbar min-h-0 flex-1 overflow-y-auto pr-1"
                role="listbox"
                aria-label={t("material_picker_title")}
              >
                <SuggestionGrid
                  items={suggestions.suggestions}
                  onClick={handleSuggestionClick}
                  currentTarget={targetHex}
                />
              </div>
            ) : (
              <p className="py-4 text-sm text-slate-500 dark:text-slate-400">
                {t("material_picker_empty")}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Target color input row
// ---------------------------------------------------------------------------

interface TargetColorInputRowProps {
  initialTarget: string;
  loading: boolean;
  onSubmit: (normalizedTarget: string) => void | Promise<void>;
}

/**
 * Isolated color-picker / hex-input / submit trio.
 * 隔离的取色器 / 十六进制输入 / 提交按钮行。
 *
 * Kept as its own component so continuous ``<input type="color">`` drag
 * events only re-render this small subtree rather than the whole picker
 * (pending-replacement bar, gradient groups, suggestion grid, etc.).
 * 独立组件保证拖动取色器时只重渲染这一小块子树，不会带着上方待替换条、
 * 渐变分组、建议网格一起刷。
 */
const TargetColorInputRow = memo(function TargetColorInputRow({
  initialTarget,
  loading,
  onSubmit,
}: TargetColorInputRowProps) {
  const { t } = useI18n();
  const [draftTarget, setDraftTarget] = useState<string>(initialTarget);

  const normalizedTarget = useMemo(() => _normalizeHex(draftTarget), [draftTarget]);

  const handleSubmit = useCallback(() => {
    if (!normalizedTarget) return;
    onSubmit(normalizedTarget);
  }, [normalizedTarget, onSubmit]);

  const handleSubmitOnEnter = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") handleSubmit();
    },
    [handleSubmit],
  );

  return (
    <div className={cx(wellPadClass, "flex flex-col gap-2")}>
      <label className="text-[clamp(0.6rem,0.75vw,0.65rem)] font-medium text-slate-600 dark:text-slate-300">
        {t("material_picker_target_label")}
      </label>
      <div className="flex items-center gap-2">
        <input
          type="color"
          aria-label={t("material_picker_target_label")}
          value={normalizedTarget || "#888888"}
          onChange={(e) => setDraftTarget(e.target.value)}
          className="h-8 w-10 cursor-pointer rounded-md border border-slate-300/80 bg-transparent dark:border-slate-700/80"
        />
        <input
          type="text"
          inputMode="text"
          spellCheck={false}
          placeholder={t("material_picker_target_placeholder")}
          value={draftTarget}
          onChange={(e) => setDraftTarget(e.target.value)}
          onKeyDown={handleSubmitOnEnter}
          className={cx(compactFieldClass, "flex-1 py-1.5 font-mono text-[clamp(0.65rem,0.85vw,0.75rem)]")}
        />
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!normalizedTarget || loading}
          className="action-control rounded-full px-3 py-1.5 text-[clamp(0.6rem,0.75vw,0.65rem)] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60"
        >
          {t("material_picker_submit")}
        </button>
      </div>
    </div>
  );
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const _HEX_REGEX = /^#?[0-9A-Fa-f]{6}$/;
const _SHORT_HEX_REGEX = /^#?[0-9A-Fa-f]{3}$/;

/** Normalise a user-typed hex to ``#RRGGBB`` (uppercase) or null if invalid. */
function _normalizeHex(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  if (_HEX_REGEX.test(trimmed)) {
    return `#${trimmed.replace(/^#/, "").toUpperCase()}`;
  }
  if (_SHORT_HEX_REGEX.test(trimmed)) {
    const expanded = trimmed
      .replace(/^#/, "")
      .split("")
      .map((c) => c + c)
      .join("");
    return `#${expanded.toUpperCase()}`;
  }
  return null;
}

interface SuggestionGridProps {
  items: MaterialColorSuggestionItem[];
  onClick: (item: MaterialColorSuggestionItem) => void;
  currentTarget: string | null;
}

const SuggestionGrid = memo(function SuggestionGrid({
  items,
  onClick,
  currentTarget,
}: SuggestionGridProps) {
  const { t } = useI18n();
  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(3rem,1fr))] gap-1.5">
      {items.map((item, i) => {
        const tooltip = t("material_picker_suggestion_tooltip")
          .replace("{hex}", item.hex)
          .replace("{delta}", item.delta_e.toFixed(2))
          .replace("{recipe}", item.recipe_display);
        const isCurrent =
          currentTarget &&
          currentTarget.replace(/^#/, "").toUpperCase() ===
            item.hex.replace(/^#/, "").toUpperCase();
        return (
          <button
            key={`${item.hex}-${i}`}
            type="button"
            aria-label={tooltip}
            title={tooltip}
            onClick={() => onClick(item)}
            className={`relative flex w-full min-w-0 flex-col items-center rounded-[10px] border px-1 py-1.5 transition-colors ${
              isCurrent
                ? "border-amber-400 bg-amber-400/10"
                : "border-transparent hover:border-[color:var(--surface-card-outline)] hover:bg-[var(--nav-chip-hover)]"
            }`}
          >
            <span
              className="block h-[clamp(1.1rem,1.7vw,1.3rem)] w-[clamp(1.1rem,1.7vw,1.3rem)] rounded-md border border-slate-300/80 dark:border-slate-600/80"
              style={{ backgroundColor: item.hex }}
            />
            <span className="mt-0.5 w-full truncate text-center font-mono text-[clamp(0.45rem,0.6vw,0.5rem)] leading-none text-slate-500 dark:text-slate-400">
              {t("material_picker_delta_e_label").replace(
                "{value}",
                item.delta_e.toFixed(1),
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
});
