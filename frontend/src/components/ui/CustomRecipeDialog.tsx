import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import Button from "./Button";
import Dropdown from "./Dropdown";
import { useI18n } from "../../i18n/context";
import {
  mutedSectionCardClass,
  workstationInputClass,
} from "./panelPrimitives";
import {
  applyRecipeOverride,
  predictCustomRecipe,
} from "../../api/converter";
import type {
  RecipeOverrideApplyResponse,
  RecipePredictResponse,
} from "../../api/types";
import {
  applyRecipePattern,
  buildPaletteHint,
  validateRecipePattern,
} from "../../utils/recipePattern";

interface PaletteOption {
  color: string;
  material?: string | null;
}

interface Props {
  open: boolean;
  sessionId: string;
  palette: PaletteOption[];
  regionIds: string[];
  colorLayers: number;
  layerHeightMm: number;
  layerOrder: string;
  baseChannelIdx: number;
  onClose: () => void;
  onApplied: (
    response: RecipeOverrideApplyResponse,
    recipe: number[],
    colorLayers: number,
    layerHeightMm: number,
  ) => void;
}

function buildDefaultRecipe(length: number, baseChannelIdx: number): number[] {
  return Array.from({ length }, () => baseChannelIdx);
}

export default function CustomRecipeDialog({
  open,
  sessionId,
  palette,
  regionIds,
  colorLayers,
  layerHeightMm,
  layerOrder,
  baseChannelIdx,
  onClose,
  onApplied,
}: Props) {
  const { t } = useI18n();
  const [recipe, setRecipe] = useState<number[]>(() =>
    buildDefaultRecipe(colorLayers, baseChannelIdx),
  );
  const [pattern, setPattern] = useState("");
  const [prediction, setPrediction] = useState<RecipePredictResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPredicting, setIsPredicting] = useState(false);
  const [isApplying, setIsApplying] = useState(false);

  useEffect(() => {
    if (!open) return;
    setRecipe(buildDefaultRecipe(colorLayers, baseChannelIdx));
    setPattern("");
    setPrediction(null);
    setError(null);
  }, [open, colorLayers, baseChannelIdx]);

  const colorOptions = useMemo(
    () =>
      palette.map((entry, index) => ({
        label: entry.material ? `${entry.color} · ${entry.material}` : entry.color,
        value: String(index),
      })),
    [palette],
  );

  const paletteHint = useMemo(() => buildPaletteHint(palette), [palette]);
  const canApply = regionIds.length > 0 && recipe.length > 0;

  const updateLayer = (index: number, value: number) => {
    setRecipe((current) => {
      const next = [...current];
      next[index] = value;
      return next;
    });
  };

  const handleAddLayer = () => {
    setRecipe((current) => [...current, baseChannelIdx]);
  };

  const handleRemoveLayer = (index: number) => {
    setRecipe((current) => current.filter((_, currentIndex) => currentIndex !== index));
  };

  const moveLayer = (index: number, delta: number) => {
    setRecipe((current) => {
      const nextIndex = index + delta;
      if (nextIndex < 0 || nextIndex >= current.length) return current;
      const next = [...current];
      const [item] = next.splice(index, 1);
      next.splice(nextIndex, 0, item);
      return next;
    });
  };

  const handleApplyPattern = () => {
    const invalidChar = validateRecipePattern(pattern, palette);
    if (invalidChar) {
      setError(
        t("recipe_custom_pattern_invalid").replace("{char}", invalidChar),
      );
      return;
    }
    setError(null);
    setRecipe((current) =>
      applyRecipePattern(pattern, palette, current.length, current),
    );
  };

  const handlePredict = async () => {
    setIsPredicting(true);
    setError(null);
    try {
      const response = await predictCustomRecipe({
        session_id: sessionId,
        recipe,
        layer_order: layerOrder,
        color_layers: recipe.length,
        layer_height_mm: layerHeightMm,
      });
      setPrediction(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("recipe_custom_predict_failed"));
    } finally {
      setIsPredicting(false);
    }
  };

  const handleApply = async () => {
    if (!canApply) {
      setError(t("recipe_custom_region_required"));
      return;
    }
    setIsApplying(true);
    setError(null);
    try {
      const response = await applyRecipeOverride({
        session_id: sessionId,
        recipe,
        layer_order: layerOrder,
        color_layers: recipe.length,
        layer_height_mm: layerHeightMm,
        region_ids: regionIds,
      });
      onApplied(response, recipe, recipe.length, layerHeightMm);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("recipe_custom_apply_failed"));
    } finally {
      setIsApplying(false);
    }
  };

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center p-4"
      style={{ backgroundColor: "color-mix(in srgb, var(--surface-panel) 82%, transparent)" }}
      onClick={onClose}
    >
      <div
        className={`${mutedSectionCardClass} max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-[28px] p-5 shadow-2xl`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
              {t("recipe_custom_title")}
            </h3>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {t("recipe_custom_layer_count").replace("{count}", String(recipe.length))}
            </p>
          </div>
          <Button label={t("recipe_custom_close")} variant="secondary" onClick={onClose} />
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <div className="flex flex-col gap-3">
            <div className="rounded-2xl border border-slate-200/80 bg-slate-50/70 p-3 text-xs text-slate-500 dark:border-slate-700/70 dark:bg-slate-900/50 dark:text-slate-400">
              {t("recipe_custom_pattern_hint")}
              <div className="mt-2 font-mono">{paletteHint}</div>
            </div>

            <div className="flex gap-2">
                <input
                  value={pattern}
                  onChange={(event) => setPattern(event.target.value)}
                  placeholder={t("recipe_custom_pattern_placeholder")}
                  className={`min-h-10 flex-1 ${workstationInputClass}`}
                />
              <Button
                label={t("recipe_custom_pattern_apply")}
                variant="secondary"
                onClick={handleApplyPattern}
              />
            </div>

            <div className="flex flex-col gap-3">
              {recipe.map((value, index) => (
                <div
                  key={`${index}-${value}`}
                  className="grid gap-2 rounded-2xl border border-slate-200/80 bg-slate-50/70 p-3 dark:border-slate-700/70 dark:bg-slate-900/50 lg:grid-cols-[auto_1fr_auto]"
                >
                  <div className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {t("recipe_custom_layer_label").replace("{index}", String(index + 1))}
                  </div>
                  <Dropdown
                    label=""
                    value={String(value)}
                    options={colorOptions}
                    onChange={(next) => updateLayer(index, Number(next))}
                  />
                  <div className="flex gap-2">
                    <Button
                      label={t("recipe_custom_move_up")}
                      variant="secondary"
                      onClick={() => moveLayer(index, -1)}
                      disabled={index === 0}
                    />
                    <Button
                      label={t("recipe_custom_move_down")}
                      variant="secondary"
                      onClick={() => moveLayer(index, 1)}
                      disabled={index === recipe.length - 1}
                    />
                    <Button
                      label={t("recipe_custom_remove_layer")}
                      variant="secondary"
                      onClick={() => handleRemoveLayer(index)}
                      disabled={recipe.length <= 1}
                    />
                  </div>
                </div>
              ))}
            </div>

            <div className="flex gap-2">
              <Button
                label={t("recipe_custom_add_layer")}
                variant="secondary"
                onClick={handleAddLayer}
                disabled={recipe.length >= 10}
              />
              <Button
                label={isPredicting ? t("recipe_custom_predicting") : t("recipe_custom_predict")}
                variant="secondary"
                onClick={() => void handlePredict()}
                disabled={isPredicting}
                loading={isPredicting}
              />
              <Button
                label={isApplying ? t("recipe_custom_applying") : t("recipe_custom_apply")}
                onClick={() => void handleApply()}
                disabled={!canApply || isApplying}
                loading={isApplying}
              />
            </div>
          </div>

          <div className="flex flex-col gap-3 rounded-2xl border border-slate-200/80 bg-slate-50/70 p-4 dark:border-slate-700/70 dark:bg-slate-900/50">
            <div className="text-sm font-medium text-slate-700 dark:text-slate-200">
              {t("recipe_custom_preview_color")}
            </div>
            {prediction ? (
              <>
                <div
                  className="h-24 rounded-2xl border border-slate-200/80 shadow-[var(--shadow-control)] dark:border-slate-700/70"
                  style={{
                    backgroundColor:
                      prediction.rgb.length === 3
                        ? `rgb(${prediction.rgb.join(",")})`
                        : "transparent",
                  }}
                />
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  {t("recipe_custom_rgb_label")}: {prediction.rgb.join(", ")}
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  {t("recipe_custom_lab_label")}: {prediction.lab.map((value) => value.toFixed(2)).join(", ")}
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  {prediction.source}
                  {prediction.runtime_mode_key ? ` · ${prediction.runtime_mode_key}` : ""}
                </div>
              </>
            ) : (
              <div className="text-xs text-slate-500 dark:text-slate-400">
                {t("recipe_custom_predict_hint")}
              </div>
            )}

            <div className="text-xs text-slate-500 dark:text-slate-400">
              {t("recipe_custom_region_count").replace("{count}", String(regionIds.length))}
            </div>
            {error && (
              <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-300">
                {error}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
