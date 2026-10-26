/** Native predictive sources are retained for compatibility, but hidden in the UI. */
export function isPredictiveLutSource(sourceKind: string | undefined): boolean {
  return sourceKind === "colordb_backed"
    || sourceKind === "predictive_stage_model"
    || sourceKind === "predictive_package";
}
