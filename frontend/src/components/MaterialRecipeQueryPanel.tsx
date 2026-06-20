import { motion, AnimatePresence } from "framer-motion";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  listGradientCardMaterials,
  previewMaterialRecipe,
  generateMaterialRecipeSwatch,
} from "../api/extractor";
import {
  apiErrorToVisibleMessage,
  buildApiResourceUrl,
  downloadResourceBlob,
} from "../api/client";
import type {
  MaterialRecipeLayer,
  MaterialRecipePreviewResponse,
  SavedMaterialLibraryItem,
} from "../api/types";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { useI18n } from "../i18n/context";
import { tRuntime } from "../i18n/runtime";
import { useSettingsStore } from "../stores/settingsStore";
import Button from "./ui/Button";
import {
  StatusBanner,
  resolvePanelSurfaceClass,
  resolveSectionCardClass,
} from "./ui/panelPrimitives";

const SUBSTRATE_OPTIONS: ("white" | "black")[] = ["white", "black"];
const ALLOWED_LAYER_HEIGHTS_MM = [0.04, 0.08, 0.1] as const;
const DEFAULT_LAYER_HEIGHT_MM = 0.08;
const UNASSIGNED_BRAND_GROUP_KEY = "__unassigned__";

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

const resolveMaterialRecipeError = (err: unknown, fallback: string): string =>
  apiErrorToVisibleMessage(err, fallback);

interface PaletteEntry {
  directoryName: string;
  materialName: string;
  brand: string;
  hex: string;
  rgbCss: string;
}

interface CollectedRecipe {
  id: string;
  directoryNames: string[];
  materialNames: string[];
  materialHexes: string[];
  resultHex: string;
  label: string;
  layerHeightMm: number;
  substrate: string;
}

type PaletteBrandGroup = {
  brand: string | null;
  items: PaletteEntry[];
};

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

const getPaletteBrand = (entry: PaletteEntry): string | null => {
  const brand = entry.brand.trim();
  return brand ? brand : null;
};

const getPaletteBrandGroupKey = (brand: string | null): string =>
  brand ?? UNASSIGNED_BRAND_GROUP_KEY;

const toSubstrateFirstDirectoryNames = (entries: PaletteEntry[]): string[] =>
  entries.map((entry) => entry.directoryName).reverse();

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
  const [collectedRecipes, setCollectedRecipes] = useState<CollectedRecipe[]>([]);
  const [swatchBlockSize, setSwatchBlockSize] = useState(15);
  const [swatchGap, setSwatchGap] = useState(2);
  const [swatchCols, setSwatchCols] = useState(0);
  const [swatchStructureMode, setSwatchStructureMode] = useState("Single-sided");
  const [isGeneratingSwatch, setIsGeneratingSwatch] = useState(false);
  const [isDownloadingSwatch, setIsDownloadingSwatch] = useState(false);
  const [swatchDownloadUrl, setSwatchDownloadUrl] = useState<string | null>(null);
  const [swatchPreviewUrl, setSwatchPreviewUrl] = useState<string | null>(null);
  const [collapsedBrandGroupKeys, setCollapsedBrandGroupKeys] = useState<string[]>([]);

  const canAddToCollection = result !== null && result.predicted_hex !== undefined;
  const isAlreadyCollected = useMemo(() => {
    if (!result) return false;
    const key = layers.map((l) => l.directoryName).join(",") + ":" + result.predicted_hex;
    return collectedRecipes.some(
      (r) => r.directoryNames.join(",") + ":" + r.resultHex === key,
    );
  }, [collectedRecipes, layers, result]);

  const handleAddToCollection = useCallback(() => {
    if (!result || !layers.length) return;
    const dirNames = layers.map((l) => l.directoryName);
    const key = dirNames.join(",") + ":" + result.predicted_hex;
    if (collectedRecipes.some((r) => r.directoryNames.join(",") + ":" + r.resultHex === key)) return;
    const recipe: CollectedRecipe = {
      id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      directoryNames: dirNames,
      materialNames: layers.map((l) => l.materialName),
      materialHexes: layers.map((l) => l.hex),
      resultHex: result.predicted_hex,
      label: layers.map((l) => l.materialName).join(" \u2192 "),
      layerHeightMm: layerHeightMm,
      substrate,
    };
    setCollectedRecipes((prev) => [...prev, recipe]);
  }, [result, layers, collectedRecipes, layerHeightMm, substrate]);

  const handleRemoveFromCollection = useCallback((id: string) => {
    setCollectedRecipes((prev) => prev.filter((r) => r.id !== id));
  }, []);

  const handleClearCollection = useCallback(() => {
    setCollectedRecipes([]);
    setSwatchDownloadUrl(null);
    setSwatchPreviewUrl(null);
    setError(null);
  }, []);

  const handleGenerateSwatch = useCallback(async () => {
    if (collectedRecipes.length === 0) return;
    setIsGeneratingSwatch(true);
    setError(null);
    setSwatchDownloadUrl(null);
    setSwatchPreviewUrl(null);
    try {
      const settings = useSettingsStore.getState();
      const response = await generateMaterialRecipeSwatch({
        recipes: collectedRecipes.map((r) => ({
          directory_names: [...r.directoryNames].reverse(),
          result_hex: r.resultHex,
          layer_height_mm: r.layerHeightMm,
          substrate: r.substrate,
        })),
        block_size_mm: swatchBlockSize,
        gap_mm: swatchGap,
        cols: swatchCols,
        structure_mode: swatchStructureMode,
        printer_id: settings.printerModel,
        slicer: settings.slicerSoftware,
        nozzle_size: settings.nozzleSize,
        device_profile_id: settings.deviceProfileId,
      });
      setSwatchDownloadUrl(response.download_url);
      setSwatchPreviewUrl(response.preview_url ?? null);
    } catch (err) {
      const message = resolveMaterialRecipeError(
        err,
        t("material_recipe_generate_swatch_failed"),
      );
      setError(message);
    } finally {
      setIsGeneratingSwatch(false);
    }
  }, [collectedRecipes, swatchBlockSize, swatchGap, swatchCols, swatchStructureMode, t]);

  const handleDownloadSwatch = useCallback(async () => {
    if (!swatchDownloadUrl || isDownloadingSwatch) return;
    setIsDownloadingSwatch(true);
    setError(null);
    let objectUrl: string | null = null;
    try {
      const blob = await downloadResourceBlob(buildApiResourceUrl(swatchDownloadUrl));
      objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = "material-recipe-swatch.3mf";
      anchor.style.display = "none";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } catch (err) {
      setError(resolveMaterialRecipeError(err, t("material_recipe_download_swatch_failed")));
    } finally {
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
      setIsDownloadingSwatch(false);
    }
  }, [isDownloadingSwatch, swatchDownloadUrl, t]);

  const loadPalette = useCallback(async () => {
    setPaletteLoading(true);
    setPaletteError(null);
    try {
      const response = await listGradientCardMaterials();
      setPalette(buildPaletteEntries(response.materials ?? []));
    } catch (err) {
      const message = resolveMaterialRecipeError(
        err,
        t("material_recipe_palette_load_failed"),
      );
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

  const groupedFilteredPalette = useMemo<PaletteBrandGroup[]>(() => {
    const groups = new Map<string, PaletteEntry[]>();
    const unassigned: PaletteEntry[] = [];
    for (const entry of filteredPalette) {
      const brand = getPaletteBrand(entry);
      if (!brand) {
        unassigned.push(entry);
        continue;
      }
      const existing = groups.get(brand);
      if (existing) {
        existing.push(entry);
      } else {
        groups.set(brand, [entry]);
      }
    }
    const result: PaletteBrandGroup[] = Array.from(groups, ([brand, items]) => ({
      brand,
      items,
    }));
    if (unassigned.length > 0) {
      result.push({ brand: null, items: unassigned });
    }
    return result;
  }, [filteredPalette]);

  const toggleBrandGroupCollapsed = useCallback((groupKey: string) => {
    setCollapsedBrandGroupKeys((previous) =>
      previous.includes(groupKey)
        ? previous.filter((item) => item !== groupKey)
        : [...previous, groupKey],
    );
  }, []);

  const handleCompute = useCallback(async () => {
    if (layers.length === 0) return;
    setIsComputing(true);
    setError(null);
    try {
      const response = await previewMaterialRecipe({
        directory_names: toSubstrateFirstDirectoryNames(layers),
        layer_height_mm: layerHeightMm,
        substrate,
      });
      setResult(response);
    } catch (err) {
      const message = resolveMaterialRecipeError(
        err,
        t("material_recipe_query_failed"),
      );
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
  const visibleResultLayers = result ? [...result.layers].reverse() : [];

  return (
    <motion.div
      initial={{ opacity: 0, x: -30 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className="flex h-full w-full min-h-0 flex-col xl:flex-row"
      data-testid="material-recipe-query-panel"
    >
      <aside
        className={`${resolvePanelSurfaceClass(
          workspace.mode,
        )} h-auto w-full overflow-y-auto xl:h-full xl:w-[380px] xl:shrink-0 2xl:w-[440px]`}
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

          {/* ---- Recipe Collection Queue ---- */}
          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                {t("material_recipe_collection_title")}
              </h3>
              {collectedRecipes.length > 0 && (
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  {tRuntime("material_recipe_collection_count", { count: collectedRecipes.length })}
                </span>
              )}
            </div>

            {collectedRecipes.length === 0 ? (
              <p className="py-4 text-center text-xs text-slate-400 dark:text-slate-500">
                {t("material_recipe_collection_empty")}
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
                        type="button"
                        onClick={() => handleRemoveFromCollection(recipe.id)}
                        className="shrink-0 rounded-full p-1 text-slate-400 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-red-500/10 hover:text-red-500 dark:text-slate-500 dark:hover:text-red-400"
                        aria-label={t("material_recipe_remove_from_collection")}
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
                <>
                  <div className="grid grid-cols-3 gap-2">
                      <label className="flex flex-col gap-1">
                        <span className="text-xs text-slate-500 dark:text-slate-400">{t("material_recipe_swatch_block_size")}</span>
                        <input
                          type="number"
                          min={5}
                          max={50}
                          step={1}
                          value={swatchBlockSize}
                          onChange={(e) => setSwatchBlockSize(Math.max(5, Math.min(50, Number(e.target.value))))}
                          className="h-9 rounded-lg border border-slate-200 bg-slate-50 px-2 text-sm text-slate-700 shadow-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                        />
                      </label>
                      <label className="flex flex-col gap-1">
                        <span className="text-xs text-slate-500 dark:text-slate-400">{t("material_recipe_swatch_gap")}</span>
                        <input
                          type="number"
                          min={0.5}
                          max={10}
                          step={0.5}
                          value={swatchGap}
                          onChange={(e) => setSwatchGap(Math.max(0.5, Math.min(10, Number(e.target.value))))}
                          className="h-9 rounded-lg border border-slate-200 bg-slate-50 px-2 text-sm text-slate-700 shadow-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                        />
                      </label>
                      <label className="flex flex-col gap-1">
                        <span className="text-xs text-slate-500 dark:text-slate-400">{t("material_recipe_swatch_cols")}</span>
                        <input
                          type="number"
                          min={0}
                          max={20}
                          step={1}
                          value={swatchCols}
                          onChange={(e) => setSwatchCols(Math.max(0, Math.min(20, Math.round(Number(e.target.value)))))}
                          className="h-9 rounded-lg border border-slate-200 bg-slate-50 px-2 text-sm text-slate-700 shadow-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                        />
                      </label>
                  </div>

                  <div className="flex flex-col gap-1">
                      <span className="text-xs text-slate-500 dark:text-slate-400">{t("material_recipe_swatch_structure")}</span>
                      <div className="grid grid-cols-2 gap-1.5">
                        {(["Single-sided", "Double-sided"] as const).map((mode) => {
                          const isActive = swatchStructureMode === mode;
                          const labelKey = mode === "Single-sided" ? "material_recipe_swatch_single_sided" : "material_recipe_swatch_double_sided";
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
                          );
                        })}
                      </div>
                  </div>

                  <div className="grid grid-cols-2 gap-2">
                      <Button
                        onClick={() => void handleGenerateSwatch()}
                        disabled={isGeneratingSwatch}
                        loading={isGeneratingSwatch}
                        label={isGeneratingSwatch ? t("material_recipe_generating_swatch") : t("material_recipe_generate_swatch")}
                      />
                      {swatchDownloadUrl ? (
                        <Button
                          onClick={() => void handleDownloadSwatch()}
                          disabled={isDownloadingSwatch}
                          loading={isDownloadingSwatch}
                          label={t("material_recipe_download_swatch")}
                          variant="secondary"
                        />
                      ) : (
                        <Button
                          onClick={handleClearCollection}
                          label={t("material_recipe_collection_clear")}
                          variant="secondary"
                        />
                      )}
                  </div>

                  {swatchPreviewUrl && (
                    <div className="rounded-xl border border-slate-200/80 overflow-hidden shadow-sm dark:border-slate-700/80">
                      <img
                        src={`${import.meta.env.VITE_API_BASE_URL || ""}${swatchPreviewUrl}`}
                        alt={t("material_recipe_swatch_legend_alt")}
                        className="w-full h-auto"
                      />
                    </div>
                  )}
                </>

                {swatchDownloadUrl && (
                  <Button
                    onClick={handleClearCollection}
                    label={t("material_recipe_collection_clear")}
                    variant="secondary"
                  />
                )}
              </div>
            )}
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
              <div className="grid gap-3" data-testid="material-recipe-palette">
                {groupedFilteredPalette.map(({ brand, items }) => {
                  const groupKey = getPaletteBrandGroupKey(brand);
                  const groupLabel = brand ?? t("mat_gradient_library_brand_unassigned");
                  const isCollapsed = collapsedBrandGroupKeys.includes(groupKey);
                  return (
                    <section
                      key={groupKey}
                      data-testid="material-recipe-brand-group"
                      data-brand={brand ?? ""}
                      className="flex flex-col gap-2"
                    >
                      <button
                        type="button"
                        data-testid="material-recipe-brand-group-toggle"
                        aria-expanded={!isCollapsed}
                        onClick={() => toggleBrandGroupCollapsed(groupKey)}
                        className="flex w-full items-center justify-between gap-2 rounded-xl border border-slate-200/80 px-2.5 py-1.5 text-left transition-colors hover:border-slate-300 hover:bg-slate-100/70 dark:border-slate-700/80 dark:hover:border-slate-600 dark:hover:bg-slate-800/70"
                      >
                        <span className="flex min-w-0 flex-wrap items-center gap-2">
                          <span className="truncate text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                            {groupLabel}
                          </span>
                          <span className="rounded-full border border-slate-200/80 px-2 py-0.5 text-[10px] font-semibold text-slate-500 dark:border-slate-700/80 dark:text-slate-400">
                            {items.length}
                          </span>
                        </span>
                        <motion.svg
                          animate={{ rotate: isCollapsed ? 0 : 90 }}
                          transition={{ type: "spring", stiffness: 300, damping: 20 }}
                          className="h-4 w-4 shrink-0 text-slate-500 dark:text-slate-400"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth={2}
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          aria-hidden="true"
                        >
                          <polyline points="9 18 15 12 9 6" />
                        </motion.svg>
                      </button>
                      {isCollapsed ? null : (
                        <div
                          className={`grid gap-2 ${
                            workspace.isCompact
                              ? "grid-cols-2"
                              : "grid-cols-2 sm:grid-cols-3 xl:grid-cols-2 2xl:grid-cols-3"
                          }`}
                        >
                          {items.map((entry) => {
                            const brandLabel = getPaletteBrand(entry) ?? t("mat_gradient_library_brand_unassigned");
                            return (
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
                                <span
                                  data-testid="material-recipe-brand-tag"
                                  className="max-w-full truncate rounded-full border border-slate-200/80 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-500 dark:border-slate-700/80 dark:text-slate-300"
                                >
                                  {brandLabel}
                                </span>
                                <span className="w-full truncate text-center text-[11px] leading-tight text-slate-500 dark:text-slate-400">
                                  {entry.materialName}
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </section>
                  );
                })}
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

        <div className="relative flex-1 min-h-0 overflow-y-auto p-4 sm:p-6 lg:p-8">
          <div className="mx-auto grid w-full max-w-6xl gap-5 lg:grid-cols-[minmax(320px,430px)_minmax(0,1fr)]">
            <section className={`${resolveSectionCardClass(workspace.mode)} flex min-h-[420px] flex-col gap-4`}>
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                  {t("material_recipe_layers_heading")}
                </h3>
                <span className="rounded-full border border-slate-200/80 px-2.5 py-1 text-xs font-medium text-slate-500 dark:border-slate-700/80 dark:text-slate-400">
                  {layerCountLabel}
                </span>
              </div>

              <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 rounded-2xl border border-slate-200/70 bg-slate-100/60 px-3 py-2 text-[11px] font-medium text-slate-500 dark:border-slate-700/70 dark:bg-slate-900/55 dark:text-slate-400">
                <span>{t("material_recipe_visible_face")}</span>
                <span className="text-slate-400 dark:text-slate-500">→</span>
                <span className="text-right">{t("material_recipe_substrate_side")}</span>
              </div>

              {layers.length === 0 ? (
                <div className="flex flex-1 items-center justify-center rounded-[28px] border border-dashed border-slate-300/80 bg-slate-100/50 px-6 py-12 text-center dark:border-slate-700/80 dark:bg-slate-900/40">
                  <p className="max-w-xs text-sm leading-6 text-slate-500 dark:text-slate-400">
                    {t("material_recipe_layers_empty")}
                  </p>
                </div>
              ) : (
                <div
                  className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1"
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
                        className="group flex items-center gap-3 rounded-2xl border border-slate-200/80 bg-slate-50/90 p-2.5 shadow-sm transition-colors hover:border-slate-300 dark:border-slate-700/80 dark:bg-slate-900/75 dark:hover:border-slate-600"
                        data-testid="material-recipe-layer-item"
                      >
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-200/70 font-mono text-[10px] font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                          {index + 1}
                        </span>
                        <div
                          className="h-10 w-10 shrink-0 rounded-2xl border border-slate-200 shadow-sm dark:border-slate-700"
                          style={{ backgroundColor: layer.rgbCss }}
                        />
                        <div className="flex min-w-0 flex-1 flex-col">
                          <span className="truncate text-sm font-medium text-slate-800 dark:text-slate-100">
                            {layer.materialName}
                          </span>
                          <span className="font-mono text-[11px] text-slate-400 dark:text-slate-500">
                            {layer.hex}
                          </span>
                        </div>
                        <button
                          type="button"
                          onClick={() => handleRemoveLayer(index)}
                          className="shrink-0 rounded-full p-1.5 text-slate-400 opacity-100 transition-colors hover:bg-red-500/10 hover:text-red-500 dark:text-slate-500 dark:hover:text-red-400 sm:opacity-0 sm:group-hover:opacity-100"
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
                {canAddToCollection && (
                  <Button
                    onClick={handleAddToCollection}
                    disabled={isAlreadyCollected}
                    label={isAlreadyCollected ? t("material_recipe_already_in_collection") : t("material_recipe_add_to_collection")}
                    variant={isAlreadyCollected ? "secondary" : "primary"}
                    className="col-span-2"
                  />
                )}
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

            <section className={`${resolveSectionCardClass(workspace.mode)} flex min-h-[420px] flex-col items-center justify-center gap-5`}>
              <h4 className="text-sm font-medium text-slate-500 dark:text-slate-400">
                {t("material_recipe_result_heading")}
              </h4>

              {result && predictedRgb ? (
                <div className="flex w-full flex-col items-center gap-5">
                  <div
                    data-testid="material-recipe-result-swatch"
                    className="h-44 w-44 rounded-[36px] border border-slate-200/80 shadow-lg dark:border-slate-700/80 sm:h-52 sm:w-52"
                    style={{ backgroundColor: toRgbCss(predictedRgb) }}
                  />
                  <div className="flex flex-col items-center gap-1">
                    <span
                      data-testid="material-recipe-result-hex"
                      className="font-mono text-xl font-semibold text-slate-900 dark:text-slate-50"
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
                      className="grid w-full max-w-xl gap-1"
                      data-testid="material-recipe-result-layers"
                      style={{
                        gridTemplateColumns: `repeat(${Math.min(result.layers.length, 8)}, minmax(0, 1fr))`,
                      }}
                    >
                      {visibleResultLayers.map((layer: MaterialRecipeLayer) => (
                        <div
                          key={`${layer.directory_name}-${layer.layer_index}`}
                          className="flex flex-col items-center gap-1 rounded-xl border border-slate-200/70 bg-slate-100/70 p-1.5 dark:border-slate-700/70 dark:bg-slate-950/40"
                        >
                          <div
                            className="h-7 w-full rounded-lg border border-slate-200/80 dark:border-slate-700/80"
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
                <p className="max-w-md text-center text-sm leading-6 text-slate-500 dark:text-slate-400">
                  {t("material_recipe_result_pending")}
                </p>
              )}
            </section>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
