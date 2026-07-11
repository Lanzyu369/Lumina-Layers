import type { MaterialLayerBenefitPoint } from "../../api/types";
import { useI18n } from "../../i18n/context";
import { cx, workstationInsetCardClass } from "../ui/panelPrimitives";

interface MaterialLayerBenefitCurveProps {
  points: MaterialLayerBenefitPoint[];
}

/** Compact, accessible summary of exact Delta-E00 gains by layer cap. */
export default function MaterialLayerBenefitCurve({
  points,
}: MaterialLayerBenefitCurveProps) {
  const { t } = useI18n();
  if (points.length === 0) {
    return null;
  }

  const title = t("palette_dynamic_benefit_title");
  return (
    <section
      className={cx(workstationInsetCardClass, "shrink-0 px-3 py-2.5")}
      role="region"
      aria-label={title}
    >
      <h3 className="text-[11px] font-semibold text-slate-700 dark:text-slate-200">
        {title}
      </h3>
      <ul className="mt-1.5 grid grid-cols-[repeat(auto-fit,minmax(8.5rem,1fr))] gap-1.5">
        {points.map((point, index) => {
          const layerText = t("palette_dynamic_benefit_layer").replace(
            "{count}",
            String(point.max_effective_layer_count),
          );
          const meanText = t("palette_dynamic_benefit_mean").replace(
            "{value}",
            point.weighted_mean_delta_e00.toFixed(2),
          );
          const marginalText =
            index === 0
              ? t("palette_dynamic_benefit_baseline")
              : point.marginal_delta_e00_reduction > 0
                ? t("palette_dynamic_benefit_marginal").replace(
                    "{value}",
                    point.marginal_delta_e00_reduction.toFixed(2),
                  )
                : t("palette_dynamic_benefit_no_improvement");
          return (
            <li
              key={`${point.max_effective_layer_count}-${index}`}
              className="rounded-xl border border-slate-200/70 bg-[var(--surface-panel)] px-2 py-1.5 text-[10px] dark:border-slate-700/70"
            >
              <div className="font-semibold text-slate-700 dark:text-slate-200">
                {layerText}
              </div>
              <div className="tabular-nums text-slate-500 dark:text-slate-400">
                {meanText}
              </div>
              <div className="tabular-nums text-slate-500 dark:text-slate-400">
                {marginalText}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
