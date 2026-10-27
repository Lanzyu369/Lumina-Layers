import type {
  MaterialLayerBenefitPoint,
  MaterialLayerBenefitScope,
} from "../../api/types";
import { useI18n } from "../../i18n/context";
import { cx, groupHeaderClass, wellPadClass } from "../ui/panelPrimitives";

interface MaterialLayerBenefitCurveProps {
  points: MaterialLayerBenefitPoint[];
  scope: MaterialLayerBenefitScope;
  pixelCount: number;
}

/** Compact, accessible summary of exact Delta-E00 gains by layer cap. */
export default function MaterialLayerBenefitCurve({
  points,
  scope,
  pixelCount,
}: MaterialLayerBenefitCurveProps) {
  const { t } = useI18n();
  if (points.length === 0) {
    return null;
  }

  const title = t("palette_dynamic_benefit_title");
  return (
    <section
      className={cx(wellPadClass, "shrink-0")}
      role="region"
      aria-label={title}
    >
      <h3 className={groupHeaderClass}>
        {title}
      </h3>
      {scope === "automatic_pixels" && (
        <p className="mt-0.5 text-[10px] text-slate-500 dark:text-slate-400">
          {t("palette_dynamic_benefit_scope_automatic").replace(
            "{count}",
            String(pixelCount),
          )}
        </p>
      )}
      <ul className="mt-2 grid grid-cols-[repeat(auto-fit,minmax(8.5rem,1fr))] divide-x divide-[color:var(--surface-divider)]">
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
              className="px-2 py-1 text-[10px]"
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
