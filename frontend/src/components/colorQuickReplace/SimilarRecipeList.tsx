/**
 * SimilarRecipeList — ranked recipe suggestions with one-click apply.
 * 相似配方列表：按色差排序展示推荐配方，并支持一键替换。
 */

import type { SimilarRecipeItem } from "../../api/types";
import { useI18n } from "../../i18n/context";
import Button from "../ui/Button";
import { cx, wellClass } from "../ui/panelPrimitives";
import {
  deltaEQualityKey,
  describeRecipeLayers,
  type RecipeChannel,
} from "./recipeSuggestionUtils";

/** Source pill per origin; ``image`` items are marked by the in-image badge instead. */
const SOURCE_PILL: Partial<Record<SimilarRecipeItem["source"], { labelKey: string; titleKey: string; className: string }>> = {
  lut: {
    labelKey: "quick_replace_source_lut",
    titleKey: "quick_replace_source_lut_title",
    className: "bg-sky-500/12 text-sky-700 dark:text-sky-300",
  },
  predictive: {
    labelKey: "quick_replace_source_predictive",
    titleKey: "quick_replace_source_predictive_title",
    className: "bg-violet-500/12 text-violet-700 dark:text-violet-300",
  },
};

const QUALITY_TEXT_CLASS: Record<string, string> = {
  quick_replace_delta_e_close: "text-emerald-700 dark:text-emerald-300",
  quick_replace_delta_e_near: "text-amber-700 dark:text-amber-300",
  quick_replace_delta_e_far: "text-slate-500 dark:text-slate-400",
};

/** Marks a suggested color that already appears in the current image. */
export function InImageBadge() {
  const { t } = useI18n();
  return (
    <span
      className="rounded-full bg-emerald-500/12 px-1.5 py-px text-[10px] font-semibold text-emerald-700 dark:text-emerald-300"
      title={t("quick_replace_in_image_title")}
      data-testid="quick-replace-in-image"
    >
      {t("quick_replace_in_image")}
    </span>
  );
}

/** Layer chips ordered from the viewing face (left) to the bottom (right). */
export function RecipeLayerChips({
  recipe,
  channels,
}: {
  recipe: number[];
  channels: RecipeChannel[];
}) {
  const { t } = useI18n();
  return (
    <div
      className="flex flex-wrap items-center gap-0.5"
      aria-label={`${t("quick_replace_recipe_layers_hint")}: ${describeRecipeLayers(recipe, channels)}`}
    >
      {recipe.map((index, layer) => {
        const channel = channels[index];
        const label = channel?.name ?? `#${index}`;
        return (
          <span
            key={`${layer}-${index}`}
            title={`${layer + 1}. ${label}`}
            className="inline-flex h-4 min-w-4 items-center justify-center rounded-[4px] border border-slate-300/80 px-0.5 text-[9px] font-semibold leading-none text-slate-600 dark:border-slate-600/80 dark:text-slate-300"
            style={channel?.hex ? { backgroundColor: channel.hex } : undefined}
          >
            {channel?.hex ? "" : label.slice(0, 1).toUpperCase()}
          </span>
        );
      })}
    </div>
  );
}

interface SimilarRecipeListProps {
  items: SimilarRecipeItem[];
  channels: RecipeChannel[];
  canApply: boolean;
  busy: boolean;
  onApply: (item: SimilarRecipeItem) => void;
}

export default function SimilarRecipeList({
  items,
  channels,
  canApply,
  busy,
  onApply,
}: SimilarRecipeListProps) {
  const { t } = useI18n();
  return (
    <ul className="flex flex-col gap-1.5" data-testid="quick-replace-recipe-list">
      {items.map((item) => {
        const qualityKey = deltaEQualityKey(item.delta_e00);
        const pill = SOURCE_PILL[item.source];
        const layers = describeRecipeLayers(item.recipe, channels);
        return (
          <li
            key={`${item.source}-${item.hex}-${item.recipe.join(",")}`}
            className={cx(wellClass, "flex items-center gap-3 px-3 py-2")}
            data-testid="quick-replace-recipe-item"
          >
            <span
              className="h-8 w-8 shrink-0 rounded-lg border border-slate-300/80 dark:border-slate-600/80"
              style={{ backgroundColor: item.hex }}
              title={item.hex}
            />
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px]">
                <span className="font-mono text-slate-700 dark:text-slate-200">{item.hex}</span>
                <span className="tabular-nums text-slate-500 dark:text-slate-400">
                  {t("quick_replace_delta_e_value").replace("{value}", item.delta_e00.toFixed(1))}
                </span>
                <span className={cx("font-semibold", QUALITY_TEXT_CLASS[qualityKey])}>
                  {t(qualityKey)}
                </span>
                {pill && (
                  <span
                    className={cx("rounded-full px-1.5 py-px text-[10px] font-semibold", pill.className)}
                    title={t(pill.titleKey)}
                  >
                    {t(pill.labelKey)}
                  </span>
                )}
                {item.in_image && <InImageBadge />}
              </div>
              <RecipeLayerChips recipe={item.recipe} channels={channels} />
            </div>
            <Button
              label={t("quick_replace_recipe_apply")}
              variant="secondary"
              size="sm"
              disabled={!canApply || busy}
              onClick={() => onApply(item)}
              title={
                canApply
                  ? t("quick_replace_recipe_apply_title")
                      .replace("{hex}", item.hex)
                      .replace("{layers}", layers)
                  : t("quick_replace_needs_selection")
              }
            />
          </li>
        );
      })}
    </ul>
  );
}
