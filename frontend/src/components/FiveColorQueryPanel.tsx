import { motion, AnimatePresence } from "framer-motion"
import { useEffect, useMemo, useCallback } from "react"
import { useFiveColorStore } from "../stores/fiveColorStore"
import { useConverterStore } from "../stores/converter"
import Dropdown from "./ui/Dropdown"
import { useWorkspaceMode } from "../hooks/useWorkspaceMode"
import { useI18n } from "../i18n/context"
import FiveColorCanvas from "./FiveColorCanvas"
import Button from "./ui/Button"
import { UI_COLOR_TOKENS } from "../theme/uiTokens"
import {
  StatusBanner,
  resolvePanelSurfaceClass,
  resolveSectionCardClass,
} from "./ui/panelPrimitives"

export default function FiveColorQueryPanel() {
  const { t } = useI18n()
  const workspace = useWorkspaceMode()
  const {
    lutName, baseColors, combinations, selectedIndices, queryResult,
    isLoading, error,
    loadBaseColors, addSelection, removeLastSelection,
    clearSelection, reverseSelection, submitQuery, clearError,
    collectedRecipes, swatchBlockSize, swatchGap, swatchCols, swatchStructureMode,
    isGeneratingSwatch, swatchDownloadUrl, swatchPreviewUrl,
    addToCollection, removeFromCollection, clearCollection,
    setSwatchBlockSize, setSwatchGap, setSwatchCols, setSwatchStructureMode, generateSwatch,
  } = useFiveColorStore()

  const lutList = useConverterStore((s) => s.lutList)
  const fetchLutList = useConverterStore((s) => s.fetchLutList)

  useEffect(() => {
    if (lutList.length === 0) void fetchLutList()
  }, [fetchLutList, lutList.length])

  const handleLutChange = (name: string) => {
    if (name) {
      clearError()
      void loadBaseColors(name)
    }
  }

  const hasSelection = selectedIndices.length > 0
  const isFull = selectedIndices.length === 5

  const canAddToCollection = queryResult?.found && queryResult.result_hex
  const isAlreadyCollected = useMemo(() => {
    if (!queryResult?.found || !queryResult.result_hex) return false
    return collectedRecipes.some(
      (r) =>
        r.selectedIndices.join(",") === selectedIndices.join(",") &&
        r.resultHex === queryResult.result_hex
    )
  }, [collectedRecipes, selectedIndices, queryResult])

  const handleDownloadSwatch = useCallback(() => {
    if (swatchDownloadUrl) {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || ""
      window.open(`${baseUrl}${swatchDownloadUrl}`, "_blank")
    }
  }, [swatchDownloadUrl])

  const validNextIndices = useMemo(() => {
    if (isFull) return null
    if (!combinations || combinations.length === 0) return null

    const len = selectedIndices.length
    const valid = new Set<number>()

    for (const combo of combinations) {
      let match = true
      for (let i = 0; i < len; i++) {
        if (combo[i] !== selectedIndices[i]) {
          match = false
          break
        }
      }
      if (match && len < 5) {
        valid.add(combo[len])
      }
    }
    return Array.from(valid)
  }, [combinations, selectedIndices, isFull])

  const canvasSlices = useMemo(
    () => selectedIndices.map((idx) => {
      const c = baseColors.find((b) => b.index === idx)
      return c ? { hex: c.hex, name: c.name } : { hex: UI_COLOR_TOKENS.fiveColorFallbackHex, name: "?" }
    }),
    [selectedIndices, baseColors],
  )

  return (
    <motion.div
      initial={{ opacity: 0, x: -30 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ type: "spring", damping: 25, stiffness: 300 }}
      className="flex h-full w-full min-h-0"
    >
      <aside className={`${resolvePanelSurfaceClass(workspace.mode)} h-auto w-full overflow-y-auto xl:h-full xl:w-[400px] xl:shrink-0 2xl:w-[480px]`}>
        <div className="flex flex-col gap-5">
          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4`}>
            <div className="flex flex-col gap-3">
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("five_color_palette")}</h3>
              <Dropdown
                label={t("five_color_lut_label")}
                value={lutName}
                options={lutList.map((n) => ({ label: n, value: n }))}
                onChange={handleLutChange}
                placeholder={t("five_color_lut_placeholder")}
              />
            </div>

            <div className="pr-1">
              {baseColors.length > 0 ? (
                <div className="flex flex-col gap-3">
                  {combinations && combinations.length > 0 && (
                    <div className="flex flex-col gap-1 px-2">
                      <div className="text-xs text-blue-600 dark:text-blue-400 font-medium">
                        {t("five_color_combinations_loaded").replace("{count}", String(combinations.length))}
                      </div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">
                        {t("five_color_combinations_hint")}
                      </div>
                    </div>
                  )}
                  <div className={`grid gap-2 ${workspace.isCompact ? "grid-cols-2" : "grid-cols-2 sm:grid-cols-3 xl:grid-cols-2 2xl:grid-cols-3"}`}>
                    {baseColors.map((color) => {
                      const isSelected = selectedIndices.includes(color.index)
                      const selOrder = selectedIndices.indexOf(color.index)
                      const isValidNext = validNextIndices === null || validNextIndices.includes(color.index)
                      const disabled = isFull || !isValidNext

                      return (
                        <button
                          key={color.index}
                          onClick={() => addSelection(color.index)}
                          disabled={disabled}
                          className={`group relative flex flex-col items-center gap-1 rounded-[20px] border p-2 transition-all ${
                            isSelected
                              ? disabled
                                ? "border-blue-400/50 bg-blue-500/5 ring-2 ring-blue-500/10 opacity-60"
                                : "border-blue-400 bg-blue-500/10 ring-2 ring-blue-500/20"
                              : isValidNext
                                ? "border-transparent bg-slate-100/60 hover:border-slate-300 hover:bg-slate-100/80 dark:bg-slate-900/45 dark:hover:border-slate-600 dark:hover:bg-slate-900/75"
                                : "border-transparent bg-slate-100/30 opacity-40 grayscale"
                          } ${disabled ? "cursor-not-allowed" : "cursor-pointer"}`}
                          aria-label={t("five_color_select_color").replace("{name}", color.name).replace("{hex}", color.hex)}
                        >
                          <div
                            className="h-11 w-11 rounded-2xl border border-slate-200/80 shadow-[var(--shadow-control)] transition-transform group-hover:scale-105 dark:border-slate-700/80"
                            style={{ backgroundColor: color.hex }}
                          />
                          {isSelected && (
                            <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-blue-500 text-xs font-bold text-white">
                              {selOrder + 1}
                            </span>
                          )}
                          <span className="w-full truncate text-center text-[11px] leading-tight text-slate-500 dark:text-slate-400">
                            {color.name}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              ) : lutName ? (
                <p className="py-8 text-center text-sm text-slate-500 dark:text-slate-400">{t("five_color_no_base_colors")}</p>
              ) : (
                <p className="py-8 text-center text-sm text-slate-500 dark:text-slate-400">{t("five_color_select_lut_first")}</p>
              )}
            </div>
          </section>

          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("five_color_actions")}</h3>

            <div className={`grid gap-2 ${workspace.isCompact ? "grid-cols-1" : "grid-cols-2"}`}>
              <Button
                onClick={() => void submitQuery()}
                disabled={!isFull || isLoading}
                label={isLoading ? t("five_color_query_loading") : t("five_color_query")}
                className={workspace.isCompact ? "" : "col-span-2"}
              />
              {canAddToCollection && (
                <Button
                  onClick={addToCollection}
                  disabled={isAlreadyCollected}
                  label={isAlreadyCollected ? t("five_color_already_in_list") : t("five_color_add_to_list")}
                  variant={isAlreadyCollected ? "secondary" : "primary"}
                  className={workspace.isCompact ? "" : "col-span-2"}
                />
              )}
              <Button
                onClick={removeLastSelection}
                disabled={!hasSelection}
                label={t("five_color_undo")}
                variant="secondary"
              />
              <Button
                onClick={reverseSelection}
                disabled={!isFull}
                label={t("five_color_reverse")}
                variant="secondary"
              />
              <Button
                onClick={clearSelection}
                disabled={!hasSelection}
                label={t("five_color_clear")}
                variant="secondary"
                className={workspace.isCompact ? "" : "col-span-2"}
              />
            </div>
          </section>

          {/* Recipe Collection Section */}
          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                {t("five_color_collection_title")}
              </h3>
              {collectedRecipes.length > 0 && (
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  {t("five_color_collection_count").replace("{count}", String(collectedRecipes.length))}
                </span>
              )}
            </div>

            {collectedRecipes.length === 0 ? (
              <p className="py-4 text-center text-xs text-slate-400 dark:text-slate-500">
                {t("five_color_collection_empty")}
              </p>
            ) : (
              <div className="flex flex-col gap-2 max-h-64 overflow-y-auto">
                <AnimatePresence initial={false}>
                  {collectedRecipes.map((recipe) => (
                    <motion.div
                      key={recipe.id}
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.2 }}
                      className="group flex items-center gap-2 rounded-xl border border-slate-200/80 bg-slate-50/80 p-2 shadow-sm dark:border-slate-700/80 dark:bg-slate-900/70"
                    >
                      <div
                        className="h-8 w-8 shrink-0 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm"
                        style={{ backgroundColor: recipe.resultHex }}
                      />
                      <div className="flex flex-1 flex-col min-w-0">
                        <span className="truncate text-xs font-medium text-slate-700 dark:text-slate-200">
                          {recipe.label}
                        </span>
                        <span className="font-mono text-[10px] text-slate-400 dark:text-slate-500">
                          {recipe.resultHex}
                        </span>
                      </div>
                      <button
                        onClick={() => removeFromCollection(recipe.id)}
                        className="shrink-0 rounded-full p-1 text-slate-400 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-red-500/10 hover:text-red-500 dark:text-slate-500 dark:hover:text-red-400"
                        aria-label={t("five_color_remove_recipe")}
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <line x1="18" y1="6" x2="6" y2="18" />
                          <line x1="6" y1="6" x2="18" y2="18" />
                        </svg>
                      </button>
                    </motion.div>
                  ))}
                </AnimatePresence>
              </div>
            )}

            {collectedRecipes.length > 0 && (
              <div className="flex flex-col gap-3 pt-1">
                <div className="grid grid-cols-3 gap-2">
                  <label className="flex flex-col gap-1">
                    <span className="text-xs text-slate-500 dark:text-slate-400">{t("five_color_swatch_block_size")}</span>
                    <input
                      type="number"
                      min={5}
                      max={50}
                      step={1}
                      value={swatchBlockSize}
                      onChange={(e) => setSwatchBlockSize(Number(e.target.value))}
                      className="h-9 rounded-lg border border-slate-200 bg-slate-50 px-2 text-sm text-slate-700 shadow-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs text-slate-500 dark:text-slate-400">{t("five_color_swatch_gap")}</span>
                    <input
                      type="number"
                      min={0.5}
                      max={10}
                      step={0.5}
                      value={swatchGap}
                      onChange={(e) => setSwatchGap(Number(e.target.value))}
                      className="h-9 rounded-lg border border-slate-200 bg-slate-50 px-2 text-sm text-slate-700 shadow-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs text-slate-500 dark:text-slate-400">{t("five_color_swatch_cols")}</span>
                    <input
                      type="number"
                      min={0}
                      max={20}
                      step={1}
                      value={swatchCols}
                      onChange={(e) => setSwatchCols(Number(e.target.value))}
                      className="h-9 rounded-lg border border-slate-200 bg-slate-50 px-2 text-sm text-slate-700 shadow-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                    />
                  </label>
                </div>

                <div className="flex flex-col gap-1">
                  <span className="text-xs text-slate-500 dark:text-slate-400">{t("five_color_swatch_structure")}</span>
                  <div className="grid grid-cols-2 gap-1.5">
                    {(["Single-sided", "Double-sided"] as const).map((mode) => {
                      const isActive = swatchStructureMode === mode
                      const labelKey = mode === "Single-sided" ? "five_color_swatch_single_sided" : "five_color_swatch_double_sided"
                      return (
                        <button
                          key={mode}
                          type="button"
                          onClick={() => setSwatchStructureMode(mode)}
                          className={`h-9 rounded-lg border text-xs font-medium transition-all ${
                            isActive
                              ? "border-blue-400 bg-blue-500/10 text-blue-600 ring-1 ring-blue-500/20 dark:border-blue-500 dark:text-blue-400"
                              : "border-slate-200 bg-slate-50 text-slate-600 hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-slate-600"
                          }`}
                        >
                          {t(labelKey)}
                        </button>
                      )
                    })}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <Button
                    onClick={() => void generateSwatch()}
                    disabled={isGeneratingSwatch}
                    loading={isGeneratingSwatch}
                    label={isGeneratingSwatch ? t("five_color_generating_swatch") : t("five_color_generate_swatch")}
                  />
                  {swatchDownloadUrl && (
                    <Button
                      onClick={handleDownloadSwatch}
                      label={t("five_color_download_swatch")}
                      variant="secondary"
                    />
                  )}
                  {!swatchDownloadUrl && (
                    <Button
                      onClick={clearCollection}
                      label={t("five_color_collection_clear")}
                      variant="secondary"
                    />
                  )}
                </div>

                {swatchPreviewUrl && (
                  <div className="rounded-xl border border-slate-200/80 overflow-hidden shadow-sm dark:border-slate-700/80">
                    <img
                      src={`${import.meta.env.VITE_API_BASE_URL || ""}${swatchPreviewUrl}`}
                      alt={t("five_color_swatch_legend_alt")}
                      className="w-full h-auto"
                    />
                  </div>
                )}

                {swatchDownloadUrl && (
                  <Button
                    onClick={clearCollection}
                    label={t("five_color_collection_clear")}
                    variant="secondary"
                  />
                )}
              </div>
            )}
          </section>
        </div>
      </aside>

      <div className={`relative min-h-0 flex-1 overflow-hidden border-slate-200/70 dark:border-slate-800/80 flex flex-col bg-slate-50 dark:bg-slate-950 ${workspace.isWide ? "border-t 2xl:border-l 2xl:border-t-0" : "border-t"}`}>
        {(error || queryResult) && (
          <div className="flex-none border-b border-slate-200/70 bg-slate-100/70 p-4 sm:p-5 lg:p-7 dark:border-slate-800/80 dark:bg-slate-900/50">
            {error && (
              <StatusBanner
                tone="error"
                action={
                  <button
                    onClick={clearError}
                    aria-label={t("five_color_close_error")}
                    className="rounded-full border border-current/20 px-2 py-1 text-xs text-red-600 transition-colors hover:bg-red-500/10 dark:text-red-300"
                  >
                    {t("five_color_error_close_icon")}
                  </button>
                }
              >
                {error}
              </StatusBanner>
            )}

            {queryResult && queryResult.found && (
              <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
                <StatusBanner tone="success" className="w-full sm:w-auto flex-1">
                  {t("five_color_result_panel")}
                </StatusBanner>

                <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-100/80 p-2.5 shadow-sm shrink-0 dark:border-slate-700 dark:bg-slate-900">
                  <div
                    className="h-10 w-16 sm:w-20 rounded-[12px] border border-slate-200 dark:border-slate-700 shadow-[var(--shadow-control)]"
                    style={{ backgroundColor: queryResult.result_hex ?? undefined }}
                  />
                  <div className="flex flex-col">
                    <span className="font-mono text-sm font-semibold text-slate-800 dark:text-slate-100">{queryResult.result_hex}</span>
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {t("five_color_result_row")}: {queryResult.row_index}
                    </span>
                  </div>
                </div>
              </div>
            )}

            {queryResult && !queryResult.found && (
              <div className="flex flex-col gap-2">
                <StatusBanner tone="warning">
                  {t("five_color_not_found")}
                </StatusBanner>
                <div className="text-xs text-slate-600 dark:text-slate-400 bg-slate-50 dark:bg-slate-900/50 rounded-lg p-3 border border-slate-200 dark:border-slate-700">
                  <div className="font-medium mb-1">{t("five_color_not_found_suggestions_title")}</div>
                  <ul className="list-disc list-inside space-y-0.5 ml-1">
                    <li>{t("five_color_not_found_tip_reverse")}</li>
                    <li>{t("five_color_not_found_tip_change")}</li>
                    <li>{t("five_color_not_found_tip_gray")}</li>
                  </ul>
                </div>
              </div>
            )}
          </div>
        )}

        <div className="relative flex-1 min-h-0 flex flex-col items-center justify-center overflow-hidden p-4 sm:p-8 pt-12 sm:pt-16">
          <div className="absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-blue-500/5 to-transparent pointer-events-none" />
          <div className="relative flex w-full max-w-2xl flex-1 items-center justify-center translate-y-4">
            <div className="h-full w-full">
              <FiveColorCanvas
                slices={canvasSlices}
                resultHex={queryResult?.found ? queryResult.result_hex : null}
                isLoading={isLoading}
              />
            </div>
          </div>
          <p className="relative mt-8 mb-4 text-sm font-medium text-slate-500 dark:text-slate-400 bg-slate-100/80 dark:bg-slate-800/80 px-4 py-2 rounded-full shadow-sm backdrop-blur-sm border border-slate-200/50 dark:border-slate-700/50">
            {baseColors.length > 0
              ? t("five_color_selection_progress").replace("{count}", String(selectedIndices.length)).replace("{total}", "5")
              : t("five_color_select_lut_first")}
          </p>
        </div>
      </div>
    </motion.div>
  )
}

