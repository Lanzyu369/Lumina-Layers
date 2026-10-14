/**
 * TargetColorPanel — choose target color B and replace the selection with it.
 * 选择目标颜色 B，并一键把选区替换成最接近 B 的可打印颜色。
 */

import { useMemo } from "react";
import type { PaletteEntry, SimilarRecipeItem } from "../../api/types";
import { useI18n } from "../../i18n/context";
import Button from "../ui/Button";
import { cx, compactFieldClass, groupHeaderClass, wellPadClass } from "../ui/panelPrimitives";
import { InImageBadge, RecipeLayerChips } from "./SimilarRecipeList";
import { deltaEQualityKey, type RecipeChannel } from "./recipeSuggestionUtils";

const MAX_IMAGE_SWATCHES = 32;

interface TargetColorPanelProps {
  /** Raw text of the target colour input (may be invalid while typing). */
  targetInput: string;
  /** Normalised ``#rrggbb`` target, or ``null`` when the input is invalid. */
  targetHex: string | null;
  onTargetChange: (value: string) => void;
  /** Whether the next click on the 2D preview picks B from that point. */
  eyedropperActive: boolean;
  onToggleEyedropper: () => void;
  palette: PaletteEntry[];
  /**
   * True: replace with the printable LUT color nearest to B. False (material
   * archive, which can print any color): replace with B itself.
   */
  snapToPrintable: boolean;
  /** Closest printable recipe to B, when ``snapToPrintable`` and loaded. */
  nearest: SimilarRecipeItem | null;
  nearestLoading: boolean;
  channels: RecipeChannel[];
  canApply: boolean;
  busy: boolean;
  onApplyNearest: (item: SimilarRecipeItem) => void;
  onApplyExact: (hex: string) => void;
}

export default function TargetColorPanel({
  targetInput,
  targetHex,
  onTargetChange,
  eyedropperActive,
  onToggleEyedropper,
  palette,
  snapToPrintable,
  nearest,
  nearestLoading,
  channels,
  canApply,
  busy,
  onApplyNearest,
  onApplyExact,
}: TargetColorPanelProps) {
  const { t } = useI18n();
  const imageColors = useMemo(
    () =>
      [...palette]
        .sort((a, b) => b.percentage - a.percentage)
        .slice(0, MAX_IMAGE_SWATCHES)
        .map((entry) => `#${entry.matched_hex.replace(/^#/, "").toLowerCase()}`),
    [palette],
  );
  const showInvalid = targetInput.trim().length > 0 && targetHex === null;
  const replaceDisabled = !canApply || busy || (snapToPrintable && !nearest);
  const handleReplace = () => {
    if (snapToPrintable) {
      if (nearest) onApplyNearest(nearest);
    } else if (targetHex) {
      onApplyExact(targetHex);
    }
  };

  return (
    <section className="flex flex-col gap-3" aria-label={t("quick_replace_target_heading")}>
      <h3 className={groupHeaderClass}>
        <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-amber-500" />
        {t("quick_replace_target_heading")}
      </h3>

      <div className="flex items-center gap-2">
        <input
          type="color"
          aria-label={t("quick_replace_target_heading")}
          value={targetHex ?? "#808080"}
          onChange={(event) => onTargetChange(event.target.value)}
          className="h-9 w-10 shrink-0 cursor-pointer rounded-[10px] border border-slate-200/80 bg-transparent p-1 dark:border-slate-700/80"
          data-testid="quick-replace-target-picker"
        />
        <input
          type="text"
          inputMode="text"
          spellCheck={false}
          placeholder={t("quick_replace_target_hex_placeholder")}
          aria-label={t("quick_replace_target_heading")}
          aria-invalid={showInvalid}
          value={targetInput}
          onChange={(event) => onTargetChange(event.target.value)}
          className={cx(compactFieldClass, "min-w-0 flex-1 py-2 font-mono text-xs")}
          data-testid="quick-replace-target-hex"
        />
        <button
          type="button"
          aria-pressed={eyedropperActive}
          aria-label={t("quick_replace_eyedropper")}
          title={t("quick_replace_eyedropper_title")}
          onClick={onToggleEyedropper}
          data-testid="quick-replace-eyedropper"
          className={cx(
            "ghost-control flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] text-slate-600 dark:text-slate-300",
          )}
          data-active={eyedropperActive ? "true" : undefined}
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 4l5 5m-2.5-2.5L20 4M13.5 5.5l5 5L9 20H4v-5l9.5-9.5z" />
          </svg>
        </button>
      </div>
      {eyedropperActive && (
        <p className="text-[11px] text-blue-700 dark:text-blue-300" role="status">
          {t("quick_replace_eyedropper_active")}
        </p>
      )}
      {showInvalid && (
        <p className="text-[11px] text-rose-600 dark:text-rose-300">{t("quick_replace_target_hex_invalid")}</p>
      )}

      {imageColors.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <span className="text-[11px] text-slate-500 dark:text-slate-400">{t("quick_replace_target_from_image")}</span>
          <div className="flex flex-wrap gap-1">
            {imageColors.map((hex) => (
              <button
                key={hex}
                type="button"
                title={hex}
                aria-label={hex}
                onClick={() => onTargetChange(hex)}
                className={cx(
                  "h-5 w-5 rounded-md border transition-transform hover:scale-110",
                  targetHex === hex
                    ? "border-2 border-amber-500"
                    : "border-slate-300/80 dark:border-slate-600/80",
                )}
                style={{ backgroundColor: hex }}
              />
            ))}
          </div>
        </div>
      )}

      {targetHex && snapToPrintable && (
        <div className={cx(wellPadClass, "flex flex-col gap-2")} data-testid="quick-replace-nearest-printable">
          <span className="text-[11px] text-slate-500 dark:text-slate-400">{t("quick_replace_nearest_printable")}</span>
          {nearest ? (
            <div className="flex items-center gap-3">
              <span className="flex shrink-0 items-center gap-1">
                <span
                  className="h-7 w-7 rounded-lg border border-slate-300/80 dark:border-slate-600/80"
                  style={{ backgroundColor: targetHex }}
                  title={targetHex}
                />
                <span className="text-[10px] text-slate-400">→</span>
                <span
                  className="h-7 w-7 rounded-lg border border-slate-300/80 dark:border-slate-600/80"
                  style={{ backgroundColor: nearest.hex }}
                  title={nearest.hex}
                />
              </span>
              <div className="flex min-w-0 flex-col gap-1 text-[11px]">
                <span className="flex flex-wrap items-center gap-1.5 font-mono text-slate-700 dark:text-slate-200">
                  {nearest.hex} · {t("quick_replace_delta_e_value").replace("{value}", nearest.delta_e00.toFixed(1))} · {t(deltaEQualityKey(nearest.delta_e00))}
                  {nearest.in_image && <InImageBadge />}
                </span>
                <RecipeLayerChips recipe={nearest.recipe} channels={channels} />
              </div>
            </div>
          ) : (
            <span className="text-[12px] text-slate-500 dark:text-slate-400">
              {nearestLoading ? t("quick_replace_recipes_loading") : t("quick_replace_recipes_empty")}
            </span>
          )}
        </div>
      )}

      {targetHex && (
        <Button
          label={t("quick_replace_replace_button")}
          variant="primary"
          size="sm"
          disabled={replaceDisabled}
          title={canApply ? undefined : t("quick_replace_needs_selection")}
          onClick={handleReplace}
        />
      )}
    </section>
  );
}
