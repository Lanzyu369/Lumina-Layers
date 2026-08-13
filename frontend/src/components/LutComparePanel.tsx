import { useEffect } from "react";
import { motion } from "framer-motion";
import { useI18n } from "../i18n/context";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { useLutCompareStore } from "../stores/lutCompareStore";
import type { CompareResponse } from "../api/types";
import Dropdown from "./ui/Dropdown";
import Button from "./ui/Button";
import {
  StatusBanner,
  cardPadClass,
  desktopPrimaryColumnClass,
  desktopSecondaryColumnClass,
  resolveDesktopSplitLayoutClass,
  resolvePanelSurfaceClass,
  wellPadClass,
} from "./ui/panelPrimitives";

function formatMetric(value: number): string {
  return value.toFixed(2);
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function replaceTokens(
  template: string,
  values: Record<string, string | number>
): string {
  let text = template;
  for (const [key, value] of Object.entries(values)) {
    text = text.replace(`{${key}}`, String(value));
  }
  return text;
}

function localizeCompareWarning(
  warning: string,
  t: (key: string) => string
): string {
  let match = warning.match(/^color_mode 不一致: (.+) vs (.+)$/);
  if (match) {
    return replaceTokens(t("lut_compare_warning_mode_mismatch"), {
      modeA: match[1],
      modeB: match[2],
    });
  }

  match = warning.match(/^recipe layer count differs: (\d+) vs (\d+)$/);
  if (match) {
    return replaceTokens(t("lut_compare_warning_layer_count_mismatch"), {
      countA: match[1],
      countB: match[2],
    });
  }

  match = warning.match(/^layer_height_mm 不一致: (.+)$/);
  if (match) {
    return replaceTokens(t("lut_compare_warning_layer_height_mismatch"), {
      values: match[1],
    });
  }

  match = warning.match(/^line_width_mm 不一致: (.+)$/);
  if (match) {
    return replaceTokens(t("lut_compare_warning_line_width_mismatch"), {
      values: match[1],
    });
  }

  match = warning.match(/^schema_version differs: (.+) vs (.+)$/);
  if (match) {
    return replaceTokens(t("lut_compare_warning_schema_mismatch"), {
      schemaA: match[1],
      schemaB: match[2],
    });
  }

  match = warning.match(/^predictive support differs: (True|False|true|false) vs (True|False|true|false)$/);
  if (match) {
    return replaceTokens(t("lut_compare_warning_predictive_mismatch"), {
      valueA: match[1],
      valueB: match[2],
    });
  }

  match = warning.match(
    /^dynamic_layer_height support differs: (True|False|true|false) vs (True|False|true|false)$/
  );
  if (match) {
    return replaceTokens(t("lut_compare_warning_dynamic_mismatch"), {
      valueA: match[1],
      valueB: match[2],
    });
  }

  if (warning === "No shared recipes found; comparison metrics are zeroed.") {
    return t("lut_compare_warning_no_shared_recipes");
  }

  match = warning.match(
    /^(LUT [AB]) row mismatch: rgb=(\d+), stacks=(\d+); using first (\d+)$/
  );
  if (match) {
    return replaceTokens(t("lut_compare_warning_row_mismatch"), {
      label: match[1],
      rgb: match[2],
      stacks: match[3],
      used: match[4],
    });
  }

  match = warning.match(
    /^(LUT [AB]) contains (\d+) duplicate recipe rows; kept the first occurrence for each recipe$/
  );
  if (match) {
    return replaceTokens(t("lut_compare_warning_duplicate_recipes"), {
      label: match[1],
      count: match[2],
    });
  }

  return t("lut_compare_warning_generic");
}

function buildLocalizedWarnings(
  compareResult: CompareResponse | null,
  t: (key: string) => string
): string[] {
  if (!compareResult) {
    return [];
  }

  const seen = new Set<string>();
  const localized: string[] = [];
  for (const warning of compareResult.warnings) {
    const translated = localizeCompareWarning(warning, t);
    if (!seen.has(translated)) {
      seen.add(translated);
      localized.push(translated);
    }
  }
  return localized;
}

function localizeLutCapability(
  capability: string,
  t: (key: string) => string,
): string {
  switch (capability) {
    case "legacy_lookup":
      return t("lut_info_capability_legacy_lookup");
    case "predictive_match":
      return t("lut_info_capability_predictive_match");
    case "predictive_model":
      return t("lut_info_capability_predictive_model");
    case "dynamic_layer_height":
      return t("lut_info_capability_dynamic_layer_height");
    case "dynamic_layer_count":
      return t("lut_info_capability_dynamic_layer_count");
    case "custom_recipe":
      return t("lut_info_capability_custom_recipe");
    case "native_reference":
      return t("lut_info_capability_native_reference");
    default:
      return capability;
  }
}

function renderLutInfoDetail(
  info: {
    schema_version?: string;
    capabilities?: string[];
    source_kind?: string;
    supported_modes?: Array<{ color_layers: number; layer_height_mm: number }>;
    supports_predictive_match?: boolean;
    supports_dynamic_layer_height?: boolean;
    supports_dynamic_layer_count?: boolean;
    supports_custom_recipe?: boolean;
  },
  t: (key: string) => string,
): string {
  const capabilityLabels = (info.capabilities ?? []).map((capability) =>
    localizeLutCapability(capability, t),
  );
  const summary = [
    `${t("lut_info_schema_label")}: ${info.schema_version ?? "1.0"}`,
    `${t("lut_info_source_kind_label")}: ${info.source_kind ?? "legacy_lookup"}`,
    info.supports_predictive_match
      ? t("lut_info_predictive_enabled")
      : t("lut_info_predictive_disabled"),
    info.supports_dynamic_layer_height
      ? t("lut_info_dynamic_enabled")
      : t("lut_info_dynamic_disabled"),
  ];
  if (info.supports_dynamic_layer_count) {
    summary.push(t("lut_info_dynamic_count_enabled"));
  }
  if (info.supports_custom_recipe) {
    summary.push(t("lut_info_custom_recipe_enabled"));
  }
  if (capabilityLabels.length > 0) {
    summary.push(
      `${t("lut_info_capabilities_label")}: ${capabilityLabels.join(", ")}`,
    );
  }
  if ((info.supported_modes ?? []).length > 0) {
    summary.push(
      `Modes: ${(info.supported_modes ?? [])
        .map((mode) => `${mode.color_layers}L@${mode.layer_height_mm.toFixed(2)}`)
        .join(", ")}`,
    );
  }
  return summary.join(" | ");
}

export default function LutComparePanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  const {
    lutList,
    lutListLoading,
    lutAName,
    lutBName,
    lutAInfo,
    lutBInfo,
    lutAInfoLoading,
    lutBInfoLoading,
    comparing,
    compareResult,
    error,
    fetchLutList,
    selectLutA,
    selectLutB,
    executeCompare,
    clearError,
  } = useLutCompareStore();

  useEffect(() => {
    void fetchLutList();
  }, [fetchLutList]);

  const lutOptions = lutList.map((lut) => ({
    label: lut.name,
    value: lut.name,
  }));

  const compareDisabled = comparing || !lutAName || !lutBName;
  const stats = compareResult?.stats ?? null;
  const compareSummary =
    compareResult && stats
      ? replaceTokens(t("lut_compare_summary"), {
          lutA: compareResult.lut_a_name,
          lutB: compareResult.lut_b_name,
          count: stats.matched_recipe_count,
        })
      : null;
  const localizedWarnings = buildLocalizedWarnings(compareResult, t);

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      data-testid="lut-compare-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-5`}
    >
      <div className={resolveDesktopSplitLayoutClass(workspace.mode)}>
        <div className={desktopPrimaryColumnClass}>
          <section
            data-testid="lut-compare-lut-a-dropdown"
            className={`${cardPadClass} flex flex-col gap-3`}
          >
            <Dropdown
              label={t("lut_compare_lut_a_label")}
              value={lutAName}
              options={lutOptions}
              onChange={(value) => void selectLutA(value)}
              disabled={lutListLoading || comparing}
              placeholder={t("lut_compare_lut_a_placeholder")}
            />
            {lutAInfoLoading && (
              <StatusBanner tone="info">{t("lut_manager_loading")}</StatusBanner>
            )}
            {lutAInfo && (
              <div className={`${wellPadClass} px-3 py-2 text-sm text-slate-600 dark:text-slate-300`}>
                <div>
                  {t("lut_manager_mode_summary")
                    .replace("{mode}", lutAInfo.color_mode)
                    .replace("{count}", String(lutAInfo.color_count))}
                </div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {renderLutInfoDetail(lutAInfo, t)}
                </div>
              </div>
            )}
          </section>

          <section
            data-testid="lut-compare-lut-b-dropdown"
            className={`${cardPadClass} flex flex-col gap-3`}
          >
            <Dropdown
              label={t("lut_compare_lut_b_label")}
              value={lutBName}
              options={lutOptions}
              onChange={(value) => void selectLutB(value)}
              disabled={lutListLoading || comparing}
              placeholder={t("lut_compare_lut_b_placeholder")}
            />
            {lutBInfoLoading && (
              <StatusBanner tone="info">{t("lut_manager_loading")}</StatusBanner>
            )}
            {lutBInfo && (
              <div className={`${wellPadClass} px-3 py-2 text-sm text-slate-600 dark:text-slate-300`}>
                <div>
                  {t("lut_manager_mode_summary")
                    .replace("{mode}", lutBInfo.color_mode)
                    .replace("{count}", String(lutBInfo.color_count))}
                </div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {renderLutInfoDetail(lutBInfo, t)}
                </div>
              </div>
            )}
          </section>

          <Button
            label={t("lut_compare_compare_btn")}
            variant="primary"
            onClick={() => void executeCompare()}
            disabled={compareDisabled}
            loading={comparing}
            className="w-full xl:w-auto"
          />
        </div>

        <div className={desktopSecondaryColumnClass}>
          {error && (
            <StatusBanner
              data-testid="error-message"
              tone="error"
              action={
                <button
                  onClick={clearError}
                  className="rounded-full border border-current/20 px-2 py-1 text-xs text-red-600 transition-colors hover:bg-red-500/10 dark:text-red-300"
                  aria-label={t("lut_manager_close_error")}
                >
                  ×
                </button>
              }
            >
              {error}
            </StatusBanner>
          )}

          {compareResult && stats && (
            <StatusBanner
              data-testid="compare-result"
              tone="success"
              title={t("lut_compare_result_title")}
            >
              <p>{compareSummary}</p>
              <p>
                {t("lut_compare_matched")}: {stats.matched_recipe_count} |{" "}
                {t("lut_compare_identical")}: {stats.identical_rgb_count}
              </p>
              <p>
                {t("lut_compare_mean")}: {formatMetric(stats.mean_delta_e00)} |{" "}
                {t("lut_compare_p95")}: {formatMetric(stats.p95_delta_e00)} |{" "}
                {t("lut_compare_max")}: {formatMetric(stats.max_delta_e00)}
              </p>
              <p>
                {t("lut_compare_coverage_a")}: {formatPercent(stats.recipe_coverage_a)} |{" "}
                {t("lut_compare_coverage_b")}: {formatPercent(stats.recipe_coverage_b)}
              </p>
            </StatusBanner>
          )}

          {localizedWarnings.length ? (
            <StatusBanner
              data-testid="compare-warnings"
              tone="warning"
              title={t("lut_compare_warnings_title")}
            >
              <ul className="list-disc pl-5">
                {localizedWarnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </StatusBanner>
          ) : null}

          <section
            data-testid="worst-diffs"
            className={`${cardPadClass} flex flex-col gap-4`}
          >
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                {t("lut_compare_worst_title")}
              </h3>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {t("lut_compare_worst_desc")}
              </p>
            </div>

            {compareResult?.worst_diffs.length ? (
              <div className="flex flex-col gap-3">
                {compareResult.worst_diffs.map((item, index) => (
                  <div
                    key={`${item.recipe.join("|")}-${index}`}
                    className={`${wellPadClass} p-4`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-50">
                          {item.recipe.join(" / ")}
                        </p>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                          {t("lut_compare_delta")}: {formatMetric(item.delta_e00)}
                        </p>
                      </div>
                      <div className="shrink-0 text-right text-xs text-slate-500 dark:text-slate-400">
                        <p>{item.hex_a}</p>
                        <p>{item.hex_b}</p>
                      </div>
                    </div>

                    <div className="mt-3 flex items-center gap-3">
                      <div className="flex items-center gap-2">
                        <span
                          className="h-6 w-6 rounded-full border border-slate-200/80 dark:border-slate-700/80"
                          style={{ backgroundColor: item.hex_a }}
                        />
                        <span className="text-xs text-slate-600 dark:text-slate-300">
                          {t("lut_compare_lut_a_label")}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span
                          className="h-6 w-6 rounded-full border border-slate-200/80 dark:border-slate-700/80"
                          style={{ backgroundColor: item.hex_b }}
                        />
                        <span className="text-xs text-slate-600 dark:text-slate-300">
                          {t("lut_compare_lut_b_label")}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className={`${wellPadClass} flex min-h-[220px] flex-col justify-center gap-3`}>
                <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {compareResult ? t("lut_compare_no_diffs") : t("lut_compare_no_result")}
                </p>
                <p className="text-sm leading-6 text-slate-500 dark:text-slate-400">
                  {t("lut_compare_desc")}
                </p>
              </div>
            )}
          </section>
        </div>
      </div>
    </motion.aside>
  );
}
