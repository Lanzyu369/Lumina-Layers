import { motion, AnimatePresence } from "framer-motion";
import { useCallback, useEffect, useMemo, useState } from "react";

import { listGradientCardMaterials, previewMaterialRecipe } from "../api/extractor";
import type {
  MaterialRecipeLayer,
  MaterialRecipePreviewResponse,
  SavedMaterialLibraryItem,
} from "../api/types";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { useI18n } from "../i18n/context";
import { tRuntime } from "../i18n/runtime";
import Button from "./ui/Button";
import {
  StatusBanner,
  resolvePanelSurfaceClass,
  resolveSectionCardClass,
} from "./ui/panelPrimitives";

const SUBSTRATE_OPTIONS: ("white" | "black")[] = ["white", "black"];
const ALLOWED_LAYER_HEIGHTS_MM = [0.04, 0.08, 0.1] as const;
const DEFAULT_LAYER_HEIGHT_MM = 0.08;

const isRgbTriplet = (value: number[] | null | undefined): value is [number, number, number] =>
  Array.isArray(value) && value.length === 3;

const clampChannel = (channel: number): number =>
  Math.max(0, Math.min(255, Math.round(Number.isFinite(channel) ? channel : 0)));

const toHex = (rgb: [number, number, number]) =>
  `#${rgb
    .map((channel) => clampChannel(channel).toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase()}`;

const toRgbCss = (rgb: [number, number, number]) =>
  `rgb(${clampChannel(rgb[0])}, ${clampChannel(rgb[1])}, ${clampChannel(rgb[2])})`;

interface PaletteEntry {
  directoryName: string;
  materialName: string;
  brand: string;
  hex: string;
  rgbCss: string;
}

const buildPaletteEntries = (items: SavedMaterialLibraryItem[]): PaletteEntry[] => {
  const entries: PaletteEntry[] = [];
  for (const item of items) {
    if (!item.directory_name) continue;
    const rgb = isRgbTriplet(item.estimated_rgb) ? item.estimated_rgb : null;
    const hex = rgb ? toHex(rgb) : "#808080";
    const rgbCss = rgb ? toRgbCss(rgb) : "#808080";
    entries.push({
      directoryName: item.directory_name,
      materialName: item.material_name || item.directory_name,
      brand: item.brand?.trim() ?? "",
      hex,
      rgbCss,
    });
  }
  return entries;
};

const matchesQuery = (entry: PaletteEntry, query: string): boolean => {
  if (!query) return true;
  const haystack = `${entry.materialName} ${entry.brand} ${entry.directoryName} ${entry.hex}`.toLowerCase();
  return haystack.includes(query);
};

export default function MaterialRecipeQueryPanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  const [palette, setPalette] = useState<PaletteEntry[]>([]);
  const [paletteLoading, setPaletteLoading] = useState(true);
  const [paletteError, setPaletteError] = useState<string | null>(null);
  const [layers, setLayers] = useState<PaletteEntry[]>([]);
  const [substrate, setSubstrate] = useState<"white" | "black">("white");
  const [layerHeightMm, setLayerHeightMm] = useState<number>(DEFAULT_LAYER_HEIGHT_MM);
  const [result, setResult] = useState<MaterialRecipePreviewResponse | null>(null);
  const [isComputing, setIsComputing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const loadPalette = useCallback(async () => {
    setPaletteLoading(true);
    setPaletteError(null);
    try {
      const response = await listGradientCardMaterials();
      setPalette(buildPaletteEntries(response.materials ?? []));
    } catch (err) {
      const message = err instanceof Error ? err.message : t("material_recipe_palette_load_failed");
      setPaletteError(message);
      setPalette([]);
    } finally {
      setPaletteLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadPalette();
  }, [loadPalette]);

  const handleAppendLayer = useCallback((entry: PaletteEntry) => {
    setLayers((prev) => [...prev, entry]);
    setResult(null);
    setError(null);
  }, []);

  const handleRemoveLayer = useCallback((index: number) => {
    setLayers((prev) => prev.filter((_, i) => i !== index));
    setResult(null);
    setError(null);
  }, []);

  const handleUndo = useCallback(() => {
    setLayers((prev) => prev.slice(0, -1));
    setResult(null);
    setError(null);
  }, []);

  const handleClear = useCallback(() => {
    setLayers([]);
    setResult(null);
    setError(null);
  }, []);

  const handleReverse = useCallback(() => {
    setLayers((prev) => (prev.length > 1 ? [...prev].reverse() : prev));
    setResult(null);
    setError(null);
  }, []);

  const filteredPalette = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return palette;
    return palette.filter((entry) => matchesQuery(entry, query));
  }, [palette, searchQuery]);

  const handleCompute = useCallback(async () => {
    if (layers.length === 0) return;
    setIsComputing(true);
    setError(null);
    try {
      const response = await previewMaterialRecipe({
        directory_names: layers.map((l) => l.directoryName),
        layer_height_mm: layerHeightMm,
        substrate,
      });
      setResult(response);
    } catch (err) {
      const message = err instanceof Error ? err.message : t("material_recipe_query_failed");
      setError(message);
      setResult(null);
    } finally {
      setIsComputing(false);
    }
  }, [layers, layerHeightMm, substrate, t]);

  const layerCountLabel = useMemo(
    () => tRuntime("material_recipe_layers_count", { count: layers.length }),
    [layers.length],
  );

  const predictedRgb: [number, number, number] | null = result
    ? [result.predicted_rgb[0], result.predicted_rgb[1], result.predicted_rgb[2]]
    : null;

  return (
    <motion.div
      initial={{ opacity: 0, x: -30 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className="flex h-full w-full min-h-0"
      data-testid="material-recipe-query-panel"
    >
      <aside
        className={`${resolvePanelSurfaceClass(
          workspace.mode,
        )} h-auto w-full overflow-y-auto xl:h-full xl:w-[400px] xl:shrink-0 2xl:w-[480px]`}
      >
        <div className="flex flex-col gap-5">
          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-2`}>
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
              {t("material_recipe_title")}
            </h3>
            <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
              {t("material_recipe_desc")}
            </p>
          </section>

          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
            <div className="grid grid-cols-2 gap-3">
              <label className="flex flex-col gap-1.5">
                <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
                  {t("material_recipe_substrate_label")}
                </span>
                <div className="grid grid-cols-2 gap-1.5">
                  {SUBSTRATE_OPTIONS.map((option) => {
                    const isActive = substrate === option;
                    return (
                      <button
                        key={option}
                        type="button"
                        onClick={() => {
                          setSubstrate(option);
                          setResult(null);
                          setError(null);
                        }}
                        className={`h-9 rounded-lg border text-xs font-medium transition-all ${
                          isActive
                            ? "border-blue-400 bg-blue-500/10 text-blue-600 ring-1 ring-blue-500/20 dark:border-blue-500 dark:text-blue-400"
                            : "border-slate-200 bg-slate-50 text-slate-600 hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-slate-600"
                        }`}
                        data-testid={`material-recipe-substrate-${option}`}
                      >
                        {t(
                          option === "white"
                            ? "material_recipe_substrate_white"
                            : "material_recipe_substrate_black",
                        )}
                      </button>
                    );
                  })}
                </div>
              </label>

              <label className="flex flex-col gap-1.5">
                <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
                  {t("material_recipe_layer_height_label")}
                </span>
                <select
                  value={layerHeightMm}
                  onChange={(event) => {
                    setLayerHeightMm(Number(event.target.value));
                    setResult(null);
                    setError(null);
                  }}
                  className="min-h-9 rounded-lg border border-slate-200 bg-slate-50 px-2 text-sm text-slate-700 shadow-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                  data-testid="material-recipe-layer-height"
                >
                  {ALLOWED_LAYER_HEIGHTS_MM.map((value) => (
                    <option key={value} value={value}>
                      {value.toFixed(2)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </section>

          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                {t("material_recipe_layers_heading")}
              </h3>
              <span className="text-xs text-slate-500 dark:text-slate-400">{layerCountLabel}</span>
            </div>

            {layers.length === 0 ? (
              <p className="py-4 text-center text-xs text-slate-400 dark:text-slate-500">
                {t("material_recipe_layers_empty")}
              </p>
            ) : (
              <div
                className="flex flex-col gap-2 max-h-72 overflow-y-auto"
                data-testid="material-recipe-layer-list"
              >
                <AnimatePresence initial={false}>
                  {layers.map((layer, index) => (
                    <motion.div
                      key={`${layer.directoryName}-${index}`}
                      initial={{ opacity: 0, y: -4 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -4 }}
                      transition={{ duration: 0.15 }}
                      className="group flex items-center gap-2 rounded-xl border border-slate-200/80 bg-slate-50/80 p-2 shadow-sm dark:border-slate-700/80 dark:bg-slate-900/70"
                      data-testid="material-recipe-layer-item"
                    >
                      <span className="w-10 shrink-0 text-center font-mono text-[10px] text-slate-500 dark:text-slate-400">
                        {tRuntime("material_recipe_layer_label", { index: index + 1 })}
                      </span>
                      <div
                        className="h-8 w-8 shrink-0 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm"
                        style={{ backgroundColor: layer.rgbCss }}
                      />
                      <div className="flex flex-1 flex-col min-w-0">
                        <span className="truncate text-xs font-medium text-slate-700 dark:text-slate-200">
                          {layer.materialName}
                        </span>
                        <span className="font-mono text-[10px] text-slate-400 dark:text-slate-500">
                          {layer.hex}
                        </span>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleRemoveLayer(index)}
                        className="shrink-0 rounded-full p-1 text-slate-400 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-red-500/10 hover:text-red-500 dark:text-slate-500 dark:hover:text-red-400"
                        aria-label={t("material_recipe_remove_layer")}
                      >
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          width="14"
                          height="14"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        >
                          <line x1="18" y1="6" x2="6" y2="18" />
                          <line x1="6" y1="6" x2="18" y2="18" />
                        </svg>
                      </button>
                    </motion.div>
                  ))}
                </AnimatePresence>
              </div>
            )}

            <div className="grid grid-cols-2 gap-2">
              <Button
                onClick={() => void handleCompute()}
                disabled={layers.length === 0 || isComputing}
                loading={isComputing}
                label={
                  isComputing ? t("material_recipe_query_loading") : t("material_recipe_query")
                }
                className="col-span-2"
              />
              <Button
                onClick={handleUndo}
                disabled={layers.length === 0}
                label={t("material_recipe_undo")}
                variant="secondary"
              />
              <Button
                onClick={handleReverse}
                disabled={layers.length < 2}
                label={t("material_recipe_reverse")}
                variant="secondary"
              />
              <Button
                onClick={handleClear}
                disabled={layers.length === 0}
                label={t("material_recipe_clear")}
                variant="secondary"
                className="col-span-2"
              />
            </div>
          </section>

          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
              {t("material_recipe_palette_heading")}
            </h3>
            {paletteError && (
              <StatusBanner tone="error">{paletteError}</StatusBanner>
            )}
            {!paletteLoading && palette.length > 0 && (
              <div className="relative">
                <input
                  type="search"
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder={t("material_recipe_search_placeholder")}
                  className="h-9 w-full rounded-lg border border-slate-200 bg-slate-50 px-3 pr-8 text-sm text-slate-700 shadow-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                  data-testid="material-recipe-search-input"
                />
                {searchQuery && (
                  <button
                    type="button"
                    onClick={() => setSearchQuery("")}
                    aria-label={t("material_recipe_search_clear")}
                    className="absolute inset-y-0 right-2 my-auto h-6 w-6 rounded-full text-slate-400 hover:bg-slate-200 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-300"
                    data-testid="material-recipe-search-clear"
                  >
                    ×
                  </button>
                )}
              </div>
            )}
            {paletteLoading ? (
              <p className="py-4 text-center text-xs text-slate-400 dark:text-slate-500">
                {t("material_recipe_palette_loading")}
              </p>
            ) : palette.length === 0 ? (
              <p className="py-4 text-center text-xs text-slate-400 dark:text-slate-500">
                {t("material_recipe_palette_empty")}
              </p>
            ) : filteredPalette.length === 0 ? (
              <p className="py-4 text-center text-xs text-slate-400 dark:text-slate-500">
                {t("material_recipe_search_empty")}
              </p>
            ) : (
              <div
                className={`grid gap-2 ${
                  workspace.isCompact
                    ? "grid-cols-2"
                    : "grid-cols-2 sm:grid-cols-3 xl:grid-cols-2 2xl:grid-cols-3"
                }`}
                data-testid="material-recipe-palette"
              >
                {filteredPalette.map((entry) => (
                  <button
                    key={entry.directoryName}
                    type="button"
                    onClick={() => handleAppendLayer(entry)}
                    className="group relative flex flex-col items-center gap-1 rounded-[20px] border border-transparent bg-slate-100/60 p-2 transition-all hover:border-slate-300 hover:bg-slate-100/80 dark:bg-slate-900/45 dark:hover:border-slate-600 dark:hover:bg-slate-900/75"
                    data-testid="material-recipe-palette-item"
                    aria-label={entry.materialName}
                  >
                    <div
                      className="h-11 w-11 rounded-2xl border border-slate-200/80 shadow-[var(--shadow-control)] transition-transform group-hover:scale-105 dark:border-slate-700/80"
                      style={{ backgroundColor: entry.rgbCss }}
                    />
                    <span className="w-full truncate text-center text-[11px] leading-tight text-slate-500 dark:text-slate-400">
                      {entry.materialName}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </section>
        </div>
      </aside>

      <div
        className={`relative min-h-0 flex-1 overflow-hidden border-slate-200/70 dark:border-slate-800/80 flex flex-col bg-slate-50 dark:bg-slate-950 ${
          workspace.isWide ? "border-t 2xl:border-l 2xl:border-t-0" : "border-t"
        }`}
      >
        {error && (
          <div className="flex-none border-b border-slate-200/70 bg-slate-100/70 p-4 sm:p-5 lg:p-7 dark:border-slate-800/80 dark:bg-slate-900/50">
            <StatusBanner
              tone="error"
              action={
                <button
                  onClick={() => setError(null)}
                  aria-label={t("material_recipe_close_error")}
                  className="rounded-full border border-current/20 px-2 py-1 text-xs text-red-600 transition-colors hover:bg-red-500/10 dark:text-red-300"
                >
                  ×
                </button>
              }
            >
              {error}
            </StatusBanner>
          </div>
        )}

        <div className="relative flex-1 min-h-0 flex flex-col items-center justify-center overflow-hidden p-4 sm:p-8">
          <h4 className="mb-4 text-sm font-medium text-slate-500 dark:text-slate-400">
            {t("material_recipe_result_heading")}
          </h4>

          {result && predictedRgb ? (
            <div className="flex flex-col items-center gap-4">
              <div
                data-testid="material-recipe-result-swatch"
                className="h-40 w-40 rounded-3xl border border-slate-200/80 shadow-lg dark:border-slate-700/80"
                style={{ backgroundColor: toRgbCss(predictedRgb) }}
              />
              <div className="flex flex-col items-center gap-1">
                <span
                  data-testid="material-recipe-result-hex"
                  className="font-mono text-lg font-semibold text-slate-900 dark:text-slate-50"
                >
                  {result.predicted_hex}
                </span>
                <span className="font-mono text-xs text-slate-500 dark:text-slate-400">
                  {tRuntime("material_recipe_result_rgb_value", {
                    value: predictedRgb.join(", "),
                  })}
                </span>
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  {tRuntime("material_recipe_result_meta", {
                    count: result.layer_count,
                    height: result.layer_height_mm.toFixed(2),
                    substrate: t(
                      result.substrate === "black"
                        ? "material_recipe_substrate_black"
                        : "material_recipe_substrate_white",
                    ),
                  })}
                </span>
              </div>

              {result.layers.length > 0 && (
                <div
                  className="grid w-full max-w-md gap-1"
                  data-testid="material-recipe-result-layers"
                  style={{
                    gridTemplateColumns: `repeat(${Math.min(result.layers.length, 8)}, minmax(0, 1fr))`,
                  }}
                >
                  {result.layers.map((layer: MaterialRecipeLayer) => (
                    <div
                      key={`${layer.directory_name}-${layer.layer_index}`}
                      className="flex flex-col items-center gap-1 rounded-lg border border-slate-200/70 bg-slate-100/70 p-1.5 dark:border-slate-700/70 dark:bg-slate-950/40"
                    >
                      <div
                        className="h-6 w-full rounded-md border border-slate-200/80 dark:border-slate-700/80"
                        style={{ backgroundColor: toRgbCss(layer.estimated_rgb) }}
                      />
                      <span className="truncate text-[10px] text-slate-500 dark:text-slate-400">
                        {layer.material_name}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p className="max-w-md text-center text-sm text-slate-500 dark:text-slate-400">
              {t("material_recipe_result_pending")}
            </p>
          )}
        </div>
      </div>
    </motion.div>
  );
}
