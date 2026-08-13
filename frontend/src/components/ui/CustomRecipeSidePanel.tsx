import type React from "react";

import type { RecipeHistoryItem } from "../../api/types";
import { useI18n } from "../../i18n/context";

/**
 * 子集结构，避免侧栏与 dialog 之间引入额外类型层；和 CustomRecipeDialog
 * 里的 PaletteOption 结构兼容（hex 可空，渲染时灰色兜底）。
 * Minimal palette shape shared with the dialog; `hex` may be null and falls
 * back to a neutral swatch.
 */
export interface CustomRecipeSidePanelPaletteEntry {
  color: string;
  hex?: string | null;
}

export interface CustomRecipeSidePanelProps {
  /** 用于历史层条着色的 palette。Structure shared with the dialog. */
  palette: CustomRecipeSidePanelPaletteEntry[];
  /** 当前选区，为空时禁用历史行点击。Disables history rows when empty. */
  regionIds: string[];
  /** 历史条目（来自 store.customRecipeHistory）。 */
  history: RecipeHistoryItem[];
  /** 点击历史行时调用；父组件负责应用。 */
  onApplyHistory: (historyId: string) => void;
}

function ensureHash(hex: string): string {
  return hex.startsWith("#") ? hex.toUpperCase() : `#${hex.toUpperCase()}`;
}

function LayerBar({
  recipe,
  palette,
  displayHexes,
  displayLabels,
}: {
  recipe: number[];
  palette: CustomRecipeSidePanelPaletteEntry[];
  /** 每层的用户意图原色 hex；优先于 LUT palette 反查使用。 */
  displayHexes?: string[];
  /** 每层的用户意图原色名，作为 tooltip 的首选。 */
  displayLabels?: string[];
}): React.ReactElement {
  return (
    <div className="flex h-2 w-full overflow-hidden rounded-full border border-slate-300/60 dark:border-slate-600/60">
      {recipe.map((channel, idx) => {
        // Prefer the user-intent hex/label captured at apply time so sparse
        // LUTs don't make the history bar show the substitute channel color.
        // 优先使用应用时捕获的用户意图 hex/label，避免稀疏 LUT 把历史条渲染
        // 成代用通道的颜色。
        const intentHex = displayHexes?.[idx];
        const intentLabel = displayLabels?.[idx];
        const entry = palette[channel];
        const bg =
          intentHex ??
          (entry?.hex ? `#${entry.hex.replace(/^#/, "")}` : undefined);
        const title = intentLabel ?? entry?.color ?? `#${channel}`;
        return (
          <div
            key={`${idx}-${channel}`}
            data-testid={`recipe-history-layer-${idx}`}
            className={`flex-1 ${bg ? "" : "bg-slate-400"}`}
            style={bg ? { backgroundColor: bg } : undefined}
            title={title}
          />
        );
      })}
    </div>
  );
}

export default function CustomRecipeSidePanel({
  palette,
  regionIds,
  history,
  onApplyHistory,
}: CustomRecipeSidePanelProps): React.ReactElement {
  const { t } = useI18n();

  const canApplyHistory = regionIds.length > 0;

  return (
    <div className="flex flex-col gap-3 overflow-hidden rounded-2xl border border-slate-200/80 bg-slate-50/70 p-3 dark:border-slate-700/70 dark:bg-slate-900/50">
      <div className="text-sm font-medium text-slate-700 dark:text-slate-200">
        {t("recipe_custom_history_title")}
      </div>

      <div className="flex max-h-72 flex-col gap-2 overflow-y-auto rounded-2xl pr-1">
        {history.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-300/80 bg-slate-100/40 p-3 text-xs text-slate-400 dark:border-slate-700/60 dark:bg-slate-800/30">
            {t("recipe_custom_history_empty")}
          </div>
        ) : (
          history.map((item) => {
            // Prefer the user-intent hex captured at apply time (topmost layer)
            // over the backend's predicted RGB, so the main swatch echoes what
            // the user picked — even when a sparse LUT forced a substitute
            // channel for the actual print.
            // 主色块优先用应用时捕获的用户意图色（顶层），而不是后端预测/代用色，
            // 保证用户选"黑"时历史主色块就是黑。
            const intentHex = item.displayHexes?.[0];
            const swatchColor = ensureHash(intentHex ?? item.hex);
            return (
              <button
                type="button"
                key={item.id}
                data-testid={`recipe-history-row-${item.id}`}
                onClick={() => onApplyHistory(item.id)}
                disabled={!canApplyHistory}
                className="flex flex-col gap-1 rounded-2xl border border-slate-200/80 bg-slate-100/70 p-2 text-left transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700/70 dark:bg-slate-900/40 dark:hover:bg-slate-900/70"
              >
                <div className="flex items-center gap-2">
                  <span
                    className="h-6 w-6 shrink-0 rounded-lg border border-slate-300/80 dark:border-slate-600/80"
                    style={{ backgroundColor: swatchColor }}
                  />
                  <span className="font-mono text-[11px] uppercase text-slate-700 dark:text-slate-200">
                    {swatchColor}
                  </span>
                  {item.fromModel && (
                    <span className="ml-auto rounded-full border border-sky-500/40 bg-sky-500/10 px-1.5 py-0.5 text-[9px] font-medium text-sky-700 dark:text-sky-300">
                      {t("recipe_custom_target_from_model")}
                    </span>
                  )}
                </div>
                <LayerBar
                  recipe={item.recipe}
                  palette={palette}
                  displayHexes={item.displayHexes}
                  displayLabels={item.displayLabels}
                />
                <div className="text-[10px] text-slate-400 dark:text-slate-500">
                  {t("recipe_custom_history_layers").replace(
                    "{count}",
                    String(item.recipe.length),
                  )}
                </div>
              </button>
            );
          })
        )}
        {!canApplyHistory && history.length > 0 && (
          <div className="text-[10px] text-amber-600 dark:text-amber-400">
            {t("recipe_custom_region_required")}
          </div>
        )}
      </div>
    </div>
  );
}
