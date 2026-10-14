/**
 * ColorQuickReplacePanel — quick recolor card in the Color Adjustment page.
 * 「颜色调整」页中的快速换色卡片。
 *
 * Works on the shared selection made in the 2D preview: replace it with the
 * nearest printable color to a target color B, or apply one of the recipes
 * whose color is closest to the selection (or to B). It reuses the existing
 * region-replace and recipe-override store actions; it keeps no edit state.
 * 作用于 2D 预览中的共享选区：一键换成最接近目标色 B 的可打印颜色，或套用
 * 与选区颜色（或 B）色差最小的配方。复用已有的区域替换与配方覆盖动作，
 * 不保存任何编辑状态。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import type { SimilarRecipeItem } from "../../api/types";
import { normalizeReferenceHex, useSimilarRecipes } from "../../hooks/useSimilarRecipes";
import { useI18n } from "../../i18n/context";
import { useConverterStore } from "../../stores/converter";
import { useEyedropperStore } from "../../stores/eyedropperStore";
import { StatusBanner, cardClass, cardDividerClass, cx, groupHeaderClass } from "../ui/panelPrimitives";
import SimilarRecipeList from "./SimilarRecipeList";
import TargetColorPanel from "./TargetColorPanel";
import type { RecipeChannel } from "./recipeSuggestionUtils";

type RecipeBasis = "selection" | "target";

/** ``/similar-recipes`` always returns recipes top (viewing face) to bottom. */
const SUGGESTION_LAYER_ORDER = "Top2Bottom";

/**
 * Apply one suggestion to the shared selection. Measured LUT entries and
 * colors already in the image go through region replacement; predictive
 * entries are forward-model recipes and must be applied as recipe overrides.
 * 把一条推荐应用到共享选区：LUT 实测条目和图中已有颜色走区域替换；
 * 预测条目是模型配方，需以配方覆盖方式应用。
 */
async function applySuggestionToSelection(item: SimilarRecipeItem) {
  const state = useConverterStore.getState();
  const document = state.selectionDocument;
  if (!document || document.selected_component_count === 0) return;
  if (item.source === "predictive") {
    await state.applyCustomRecipeOverride(document.region_ids, item.recipe, SUGGESTION_LAYER_ORDER);
    return;
  }
  await state.replaceSharedSelectionColor(item.hex.replace(/^#/, ""));
}

function replaceSelectionWithExactColor(hex: string) {
  void useConverterStore.getState().replaceSharedSelectionColor(hex.replace(/^#/, ""));
}

export default function ColorQuickReplacePanel() {
  const { t } = useI18n();
  const { sessionId, palette, selectedLutInfo, sourceVersion, colorLayers, selectionDocument, busy } =
    useConverterStore(
      useShallow((s) => ({
        sessionId: s.sessionId,
        palette: s.palette,
        selectedLutInfo: s.selectedLutInfo,
        sourceVersion: s.source_version,
        colorLayers: s.color_layers,
        selectionDocument: s.selectionDocument,
        busy: s.replacePreviewLoading,
      })),
    );

  const [expanded, setExpanded] = useState(true);
  const [targetInput, setTargetInput] = useState("");
  const [basis, setBasis] = useState<RecipeBasis>("selection");
  const [pickedReference, setPickedReference] = useState<string | null>(null);

  const targetHex = normalizeReferenceHex(targetInput);
  const selectedHexes = useMemo(
    () => (selectionDocument?.selected_color_hexes ?? []).map((hex) => hex.toLowerCase()),
    [selectionDocument],
  );
  const hasSelection = Boolean(selectionDocument && selectionDocument.selected_component_count > 0);
  const selectionReference =
    pickedReference && selectedHexes.includes(pickedReference) ? pickedReference : selectedHexes[0] ?? null;
  const recipeReference =
    basis === "target" ? targetHex ?? selectionReference : selectionReference ?? targetHex;

  // Material archives can print any color, so B is applied as-is there; LUT
  // sources snap B to the nearest printable LUT color. Collapsed cards fetch nothing.
  const snapTargetToPrintable = sourceVersion !== "material";
  const suggestionSession = expanded ? sessionId : null;
  // Replace, recipe override, undo and redo advance the content revision and
  // change which suggestions are already in the image, so they refetch too.
  const contentRevision =
    selectionDocument?.editor_content_revision ?? selectionDocument?.content_revision ?? "";
  const refreshKey = `${selectedLutInfo?.name ?? ""}|${colorLayers ?? ""}|${contentRevision}`;
  const targetRecipes = useSimilarRecipes(suggestionSession, targetHex, refreshKey);
  const referenceRecipes = useSimilarRecipes(
    suggestionSession,
    recipeReference === targetHex ? null : recipeReference,
    refreshKey,
  );
  const listRecipes = recipeReference === targetHex ? targetRecipes : referenceRecipes;

  const channels: RecipeChannel[] = useMemo(
    () =>
      (selectedLutInfo?.palette ?? []).map((entry) => ({
        name: entry.color_name ?? entry.color,
        hex: entry.hex_color ?? null,
      })),
    [selectedLutInfo],
  );

  const handleTargetChange = useCallback((value: string) => {
    setTargetInput(value);
    if (normalizeReferenceHex(value)) setBasis("target");
  }, []);
  const handleApply = useCallback((item: SimilarRecipeItem) => {
    void applySuggestionToSelection(item);
  }, []);
  const { eyedropperActive, toggleEyedropper } = useTargetEyedropper(handleTargetChange, expanded);

  return (
    <section className={cx(cardClass, "flex flex-col gap-3 px-4 py-3")} data-testid="color-quick-replace-panel">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{t("quick_replace_title")}</h3>
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
          className="rounded-full px-2 py-0.5 text-[11px] text-slate-500 transition-colors hover:bg-slate-200/70 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
        >
          {t(expanded ? "quick_replace_collapse" : "quick_replace_expand")}
        </button>
      </div>

      {expanded && (
        <>
          {!hasSelection && (
            <p className="text-[11px] leading-5 text-slate-500 dark:text-slate-400">
              {t("quick_replace_needs_selection")}
            </p>
          )}
          <TargetColorPanel
            targetInput={targetInput}
            targetHex={targetHex}
            onTargetChange={handleTargetChange}
            eyedropperActive={eyedropperActive}
            onToggleEyedropper={toggleEyedropper}
            palette={palette}
            snapToPrintable={snapTargetToPrintable}
            nearest={targetRecipes.items[0] ?? null}
            nearestLoading={targetRecipes.status === "loading"}
            channels={channels}
            canApply={hasSelection}
            busy={busy}
            onApplyNearest={handleApply}
            onApplyExact={replaceSelectionWithExactColor}
          />
          <div className={cardDividerClass} aria-hidden="true" />
          <section className="flex flex-col gap-2" aria-label={t("quick_replace_recipes_heading")}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className={groupHeaderClass}>
                <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                {t("quick_replace_recipes_heading")}
              </h4>
              {recipeReference && (
                <span className="flex items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400">
                  {t("quick_replace_reference")}
                  <span
                    className="h-4 w-4 rounded-md border border-slate-300/80 dark:border-slate-600/80"
                    style={{ backgroundColor: recipeReference }}
                  />
                  <span className="font-mono">{recipeReference}</span>
                </span>
              )}
            </div>
            <BasisToggle
                basis={basis}
                onChange={setBasis}
                selectionAvailable={Boolean(selectionReference)}
                targetAvailable={Boolean(targetHex)}
              />
            {basis === "selection" && selectedHexes.length > 1 && (
              <ReferenceColorChooser
                hexes={selectedHexes}
                active={selectionReference}
                onPick={setPickedReference}
              />
            )}
            <RecipeSuggestionBody
              reference={recipeReference}
              status={listRecipes.status}
              items={listRecipes.items}
              channels={channels}
              canApply={hasSelection}
              busy={busy}
              onApply={handleApply}
            />
          </section>
        </>
      )}
    </section>
  );
}

/**
 * Feed eyedropper picks from the 2D preview into target color B. Esc cancels
 * the eyedropper before the page's own Esc handler can close the overlay, and
 * the eyedropper is switched off whenever the card collapses or unmounts.
 * 把 2D 预览的吸管取色结果填入目标颜色 B。Esc 优先取消吸管（不关闭页面）；
 * 卡片收起或卸载时自动关闭吸管。
 */
function useTargetEyedropper(onPick: (hex: string) => void, enabled: boolean) {
  const eyedropperActive = useEyedropperStore((s) => s.active);
  const lastPick = useEyedropperStore((s) => s.lastPick);
  const handledSeq = useRef(lastPick?.seq ?? 0);

  useEffect(() => {
    if (lastPick && lastPick.seq !== handledSeq.current) {
      handledSeq.current = lastPick.seq;
      onPick(lastPick.hex);
    }
  }, [lastPick, onPick]);

  useEffect(() => {
    if (!enabled) useEyedropperStore.getState().cancel();
    return () => useEyedropperStore.getState().cancel();
  }, [enabled]);

  useEffect(() => {
    if (!eyedropperActive) return;
    const cancelOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      useEyedropperStore.getState().cancel();
    };
    window.addEventListener("keydown", cancelOnEscape, { capture: true });
    return () => window.removeEventListener("keydown", cancelOnEscape, { capture: true });
  }, [eyedropperActive]);

  const toggleEyedropper = useCallback(() => {
    const store = useEyedropperStore.getState();
    if (store.active) store.cancel();
    else store.start();
  }, []);

  return { eyedropperActive, toggleEyedropper };
}

function BasisToggle({
  basis,
  onChange,
  selectionAvailable,
  targetAvailable,
}: {
  basis: RecipeBasis;
  onChange: (basis: RecipeBasis) => void;
  selectionAvailable: boolean;
  targetAvailable: boolean;
}) {
  const { t } = useI18n();
  return (
    <div className="flex gap-1" role="radiogroup" aria-label={t("quick_replace_reference")}>
      {(["selection", "target"] as const).map((option) => (
        <button
          key={option}
          type="button"
          role="radio"
          aria-checked={basis === option}
          disabled={option === "target" ? !targetAvailable : !selectionAvailable}
          onClick={() => onChange(option)}
          className={cx(
            "ghost-control rounded-full px-2.5 py-1 text-[11px]",
            basis === option ? "" : "text-slate-500 dark:text-slate-400",
          )}
          data-active={basis === option ? "true" : undefined}
        >
          {t(option === "selection" ? "quick_replace_basis_selection" : "quick_replace_basis_target")}
        </button>
      ))}
    </div>
  );
}

const MAX_REFERENCE_SWATCHES = 24;

function ReferenceColorChooser({
  hexes,
  active,
  onPick,
}: {
  hexes: string[];
  active: string | null;
  onPick: (hex: string) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] text-slate-500 dark:text-slate-400">{t("quick_replace_reference_colors")}</span>
      <div className="flex flex-wrap gap-1">
        {hexes.slice(0, MAX_REFERENCE_SWATCHES).map((hex) => (
          <button
            key={hex}
            type="button"
            title={hex}
            aria-label={hex}
            aria-pressed={active === hex}
            onClick={() => onPick(hex)}
            className={cx(
              "h-5 w-5 rounded-md border transition-transform hover:scale-110",
              active === hex ? "border-2 border-amber-500" : "border-slate-300/80 dark:border-slate-600/80",
            )}
            style={{ backgroundColor: hex }}
          />
        ))}
      </div>
    </div>
  );
}

function RecipeSuggestionBody({
  reference,
  status,
  items,
  channels,
  canApply,
  busy,
  onApply,
}: {
  reference: string | null;
  status: "idle" | "loading" | "ready" | "error";
  items: SimilarRecipeItem[];
  channels: RecipeChannel[];
  canApply: boolean;
  busy: boolean;
  onApply: (item: SimilarRecipeItem) => void;
}) {
  const { t } = useI18n();
  const hintClass = "text-[12px] text-slate-500 dark:text-slate-400";
  if (!reference) return <p className={hintClass}>{t("quick_replace_recipes_pick_reference")}</p>;
  if (status === "error") {
    return <StatusBanner tone="warning">{t("quick_replace_recipes_error")}</StatusBanner>;
  }
  if (items.length === 0) {
    return (
      <p className={hintClass}>
        {t(status === "ready" ? "quick_replace_recipes_empty" : "quick_replace_recipes_loading")}
      </p>
    );
  }
  return (
    <>
      <p className="text-[11px] text-slate-500 dark:text-slate-400">{t("quick_replace_recipe_layers_hint")}</p>
      <div className="dock-scrollbar max-h-72 overflow-y-auto pr-1">
        <SimilarRecipeList items={items} channels={channels} canApply={canApply} busy={busy} onApply={onApply} />
      </div>
    </>
  );
}
