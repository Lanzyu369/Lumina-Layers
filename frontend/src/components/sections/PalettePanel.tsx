import { useState } from "react";
import { useConverterStore } from "../../stores/converter";
import type { PaletteEntry } from "../../api/types";
import Slider from "../ui/Slider";
import Button from "../ui/Button";
import Switch from "../ui/Switch";
import CustomRecipeDialog from "../ui/CustomRecipeDialog";
import { useI18n } from "../../i18n/context";
import { cx, workstationInsetCardClass, workstationPanelCardClass } from "../ui/panelPrimitives";
import { normalizeResourceUrl } from "../../utils/resourceUrl";

// ========== PaletteItem ==========

interface PaletteItemProps {
  entry: PaletteEntry;
  isSelected: boolean;
  remappedHex: string | undefined;
  heightMm: number | undefined;
  showHeightSlider: boolean;
  maxHeight: number;
  isFreeColor?: boolean;
  onSelect: () => void;
  onHeightChange: (h: number) => void;
}

function PaletteItem({
  entry,
  isSelected,
  remappedHex,
  heightMm,
  showHeightSlider,
  maxHeight,
  isFreeColor = false,
  onSelect,
  onHeightChange,
}: PaletteItemProps) {
  const { t } = useI18n();
  const displayHex = remappedHex ?? entry.matched_hex;
  const isRemapped = !!remappedHex;

  // Border priority: isFreeColor > isRemapped > default
  const borderClass = isFreeColor
    ? "border-2 border-dashed border-red-400"
    : isRemapped
      ? "border border-yellow-500"
      : "border border-gray-600";

  // Compact block mode (no height slider)
  if (!showHeightSlider) {
    return (
      <div
        role="button"
        tabIndex={0}
        aria-label={`${t("lut_grid_color_label").replace("{hex}", entry.matched_hex)}，${entry.percentage.toFixed(1)}%${isRemapped ? `，${t("palette_replaced_label").replace("{hex}", `#${remappedHex}`)}` : ""}`}
        aria-pressed={isSelected}
        onClick={onSelect}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onSelect();
          }
        }}
        className={`relative flex w-full min-w-0 flex-col items-center gap-1 rounded-2xl px-1.5 py-2 cursor-pointer border transition-all duration-150 ${
          isSelected
            ? "border-amber-400 bg-amber-400/10 ring-2 ring-amber-400/30"
            : "border-transparent bg-white/35 hover:border-slate-300 hover:bg-white/65 dark:bg-slate-900/35 dark:hover:border-slate-600 dark:hover:bg-slate-900/75"
        }`}
      >
        <span
          className={`inline-block h-[clamp(1.4rem,2vw,1.75rem)] w-[clamp(1.4rem,2vw,1.75rem)] rounded-xl ${borderClass}`}
          style={{ backgroundColor: `#${displayHex}` }}
          title={`#${displayHex}`}
        />
        <span className="text-[clamp(0.55rem,0.75vw,0.625rem)] tabular-nums leading-none text-slate-500 dark:text-slate-400">
          {entry.percentage.toFixed(1)}%
        </span>
      </div>
    );
  }

  // Vertical compact block with height slider (relief mode, 3-col grid)
  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`${t("lut_grid_color_label").replace("{hex}", entry.matched_hex)}，${entry.percentage.toFixed(1)}%${isRemapped ? `，${t("palette_replaced_label").replace("{hex}", `#${remappedHex}`)}` : ""}`}
      aria-pressed={isSelected}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={`relative flex h-full min-h-0 flex-col gap-2 rounded-[20px] px-2.5 py-2 cursor-pointer border transition-all duration-150 ${
        isSelected
          ? "border-amber-400 bg-amber-400/10 ring-2 ring-amber-400/30"
          : "border-transparent bg-white/35 hover:border-slate-300 hover:bg-white/65 dark:bg-slate-900/35 dark:hover:border-slate-600 dark:hover:bg-slate-900/75"
      }`}
    >
      {/* Top row: swatch + percentage */}
      <div className="flex items-center gap-1.5">
        <span
          className={`inline-block h-[clamp(1.25rem,1.7vw,1.5rem)] w-[clamp(1.25rem,1.7vw,1.5rem)] shrink-0 rounded-xl ${borderClass}`}
          style={{ backgroundColor: `#${displayHex}` }}
          title={`#${displayHex}`}
        />
        <span className="truncate text-[clamp(0.55rem,0.75vw,0.625rem)] tabular-nums text-slate-500 dark:text-slate-400">
          {entry.percentage.toFixed(1)}%
        </span>
      </div>
      {/* Height slider */}
      <div
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        <Slider
          label=""
          value={heightMm ?? maxHeight * 0.5}
          min={0.08}
          max={maxHeight}
          step={0.04}
          unit="mm"
          onChange={onHeightChange}
        />
      </div>
    </div>
  );
}

// ========== FreeColorSummary ==========

function FreeColorSummary({ freeColors }: { freeColors: Set<string> }) {
  const { t } = useI18n();
  if (freeColors.size === 0) return null;
  return (
    <div className={cx(workstationInsetCardClass, "flex flex-wrap items-center gap-2 px-3 py-2.5")}>
      <span className="text-[clamp(0.65rem,0.8vw,0.7rem)] font-medium text-slate-500 dark:text-slate-400">{t("conv_free_color_label")}:</span>
      {Array.from(freeColors).sort().map(hex => (
        <span
          key={hex}
          className="h-6 w-6 rounded-xl border-2 border-dashed border-red-400"
          style={{ backgroundColor: `#${hex}` }}
          title={`#${hex}`}
        />
      ))}
    </div>
  );
}

// ========== PalettePanel ==========

interface PalettePanelProps {
  showHoverMagnifier?: boolean;
  showHoverLayerDetails?: boolean;
  onToggleHoverMagnifier?: (checked: boolean) => void;
  onToggleHoverLayerDetails?: (checked: boolean) => void;
}

export default function PalettePanel({
  showHoverMagnifier = true,
  showHoverLayerDetails = true,
  onToggleHoverMagnifier,
  onToggleHoverLayerDetails,
}: PalettePanelProps) {
  const { t } = useI18n();
  const [recipeDialogOpen, setRecipeDialogOpen] = useState(false);
  const palette = useConverterStore((s) => s.palette);
  const selectedLutInfo = useConverterStore((s) => s.selectedLutInfo);
  const sessionId = useConverterStore((s) => s.sessionId);
  const color_layers = useConverterStore((s) => s.color_layers);
  const layer_height_mm = useConverterStore((s) => s.layer_height_mm);
  const selectedColor = useConverterStore((s) => s.selectedColor);
  const setSelectedColor = useConverterStore((s) => s.setSelectedColor);
  const selectedColors = useConverterStore((s) => s.selectedColors);
  const toggleColorInSelection = useConverterStore((s) => s.toggleColorInSelection);
  const enable_relief = useConverterStore((s) => s.enable_relief);
  const color_height_map = useConverterStore((s) => s.color_height_map);
  const updateColorHeight = useConverterStore((s) => s.updateColorHeight);
  const colorRemapMap = useConverterStore((s) => s.colorRemapMap);
  const remapHistory = useConverterStore((s) => s.remapHistory);
  const undoColorRemap = useConverterStore((s) => s.undoColorRemap);
  const clearAllRemaps = useConverterStore((s) => s.clearAllRemaps);
  const heightmap_max_height = useConverterStore((s) => s.heightmap_max_height);
  const selectionMode = useConverterStore((s) => s.selectionMode);
  const setSelectionMode = useConverterStore((s) => s.setSelectionMode);
  const selectedRegions = useConverterStore((s) => s.selectedRegions);
  const regionData = useConverterStore((s) => s.regionData);
  const removeRegionFromSelection = useConverterStore((s) => s.removeRegionFromSelection);
  const free_color_set = useConverterStore((s) => s.free_color_set);
  const toggleFreeColor = useConverterStore((s) => s.toggleFreeColor);
  const clearFreeColors = useConverterStore((s) => s.clearFreeColors);
  const regionReplacementCount = useConverterStore((s) => s.regionReplacementCount);
  const canUseCustomRecipe =
    !!selectedLutInfo?.supports_custom_recipe &&
    (selectedRegions.length > 0 || !!regionData?.regionId);

  const hasRemaps = Object.keys(colorRemapMap).length > 0 || regionReplacementCount > 0;
  const hasHistory = remapHistory.length > 0;

  const handleSelect = (hex: string) => {
    switch (selectionMode) {
      case 'current':
      case 'multi-select':
      case 'region':
        break;
      case 'select-all':
        toggleColorInSelection(hex);
        // Keep selectedColor in sync for detail display & recommendations
        if (selectedColors.has(hex)) {
          // Was selected, now toggled off
          const remaining = Array.from(selectedColors).filter((c) => c !== hex);
          setSelectedColor(remaining.length > 0 ? remaining[remaining.length - 1] : null);
        } else {
          // Newly selected
          setSelectedColor(hex);
        }
        break;
    }
  };

  // Multi-select highlights colors that have at least one region selected
  const multiSelectHexSet = selectionMode === 'multi-select'
    ? new Set(selectedRegions.map((r) => r.colorHex.replace(/^#/, "")))
    : null;

  const getIsSelected = (hex: string): boolean => {
    if (multiSelectHexSet) {
      return multiSelectHexSet.has(hex);
    }
    if (selectionMode === 'select-all' && selectedColors.size > 0) {
      return selectedColors.has(hex);
    }
    return selectedColor === hex;
  };

  return (
    <div className={cx(workstationPanelCardClass, "flex h-full min-h-0 flex-col")}>
      {palette.length === 0 ? (
        <p className="py-4 text-sm text-slate-500 dark:text-slate-400">
          {t("palette_no_data")}
        </p>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-1.5">
          {/* Toolbar: selected color detail + action buttons + mode buttons (single row) */}
          <div className="shrink-0 flex flex-wrap items-center gap-2">
            {/* Inline selected color swatches */}
            {selectedColor && (() => {
              const selectedEntry = palette.find(
                (e) => e.matched_hex === selectedColor
              );
              if (!selectedEntry) return null;
              const remapped = colorRemapMap[selectedColor];
              return (
                <>
                  <span
                    className="inline-block h-5 w-5 shrink-0 rounded-lg border border-slate-300/80 dark:border-slate-600/80"
                    style={{ backgroundColor: `#${selectedEntry.quantized_hex}` }}
                    title={`${t("palette_quantized")}: #${selectedEntry.quantized_hex}`}
                  />
                  <span className="text-[10px] text-slate-400">{"\u2192"}</span>
                  <span
                    className="inline-block h-5 w-5 shrink-0 rounded-lg border border-slate-300/80 dark:border-slate-600/80"
                    style={{ backgroundColor: `#${selectedEntry.matched_hex}` }}
                    title={`${t("palette_matched")}: #${selectedEntry.matched_hex}`}
                  />
                  {remapped && (
                    <>
                      <span className="text-[10px] text-slate-400">{"\u2192"}</span>
                      <span
                        className="inline-block h-5 w-5 shrink-0 rounded-lg border-2 border-yellow-500"
                        style={{ backgroundColor: `#${remapped}` }}
                        title={`${t("palette_replaced_label")}: #${remapped}`}
                      />
                    </>
                  )}
                  <span className="mr-1 h-4 w-px bg-slate-300 dark:bg-slate-700" />
                </>
              );
            })()}

            <Button
              label={t("palette_undo")}
              variant="secondary"
              onClick={undoColorRemap}
              disabled={!hasHistory}
            />
            <Button
              label={t("palette_clear_remaps")}
              variant="secondary"
              onClick={clearAllRemaps}
              disabled={!hasRemaps}
            />
            <Button
              label={t("palette_mode_select_all")}
              variant={selectionMode === 'select-all' ? 'primary' : 'secondary'}
              onClick={() => setSelectionMode('select-all')}
            />
            <Button
              label={t("palette_mode_current")}
              variant={selectionMode === 'current' ? 'primary' : 'secondary'}
              onClick={() => setSelectionMode('current')}
            />
            <Button
              label={t("palette_mode_multi_select")}
              variant={selectionMode === 'multi-select' ? 'primary' : 'secondary'}
              onClick={() => setSelectionMode('multi-select')}
            />
            <Button
              label={t("palette_mode_region")}
              variant={selectionMode === 'region' ? 'primary' : 'secondary'}
              onClick={() => setSelectionMode('region')}
            />
            <Button
              label={t("conv_free_color_btn")}
              variant="secondary"
              onClick={() => {
                if (selectedColor) toggleFreeColor(selectedColor);
              }}
              disabled={selectedColor === null}
            />
            <Button
              label={t("conv_free_color_clear_btn")}
              variant="secondary"
              onClick={clearFreeColors}
              disabled={free_color_set.size === 0}
            />
            <Button
              label={t("recipe_custom_button")}
              variant="secondary"
              onClick={() => setRecipeDialogOpen(true)}
              disabled={!canUseCustomRecipe}
            />
            <div className={cx(workstationInsetCardClass, "w-full flex flex-wrap items-center gap-2 px-2 py-1.5")}>
              <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400">
                {t("viewer_hover_toggle_group")}
              </span>
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] text-slate-500 dark:text-slate-400">
                  {t("viewer_hover_toggle_magnifier")}
                </span>
                <Switch
                  checked={showHoverMagnifier}
                  onChange={(checked) => onToggleHoverMagnifier?.(checked)}
                  ariaLabel={t("viewer_hover_toggle_magnifier")}
                />
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] text-slate-500 dark:text-slate-400">
                  {t("viewer_hover_toggle_layers")}
                </span>
                <Switch
                  checked={showHoverLayerDetails}
                  onChange={(checked) => onToggleHoverLayerDetails?.(checked)}
                  ariaLabel={t("viewer_hover_toggle_layers")}
                />
              </div>
            </div>
          </div>

          <div className="shrink-0 flex flex-col gap-1.5">
            {/* Select-all multi-color indicator */}
            {selectionMode === 'select-all' && selectedColors.size > 0 && (
            <div className={cx(workstationInsetCardClass, "flex flex-wrap items-center gap-2 px-3 py-2.5")}>
              <span className="text-[clamp(0.55rem,0.75vw,0.625rem)] font-medium text-amber-500 dark:text-amber-400">
                {t("palette_multi_select_count").replace("{count}", String(selectedColors.size))}
              </span>
              {Array.from(selectedColors).map((hex) => (
                <button
                  key={hex}
                  type="button"
                  onClick={() => handleSelect(hex)}
                  className="h-5 w-5 rounded-lg border-2 border-amber-400 shadow-sm transition-transform hover:scale-110"
                  style={{ backgroundColor: `#${hex}` }}
                  title={`#${hex} — ${t("palette_multi_select_click_remove")}`}
                />
              ))}
            </div>
          )}

            {/* Multi-select region indicator */}
            {selectionMode === 'multi-select' && selectedRegions.length > 0 && (
            <div className={cx(workstationInsetCardClass, "flex flex-wrap items-center gap-2 px-3 py-2.5")}>
              <span className="text-[clamp(0.55rem,0.75vw,0.625rem)] font-medium text-amber-500 dark:text-amber-400">
                {t("palette_multi_select_region_count").replace("{count}", String(selectedRegions.length))}
              </span>
              {selectedRegions.map((region) => {
                const hex = region.colorHex.replace(/^#/, "");
                return (
                  <button
                    key={region.regionId}
                    type="button"
                    onClick={() => removeRegionFromSelection(region.regionId)}
                    className="h-5 w-5 rounded-lg border-2 border-amber-400 shadow-sm transition-transform hover:scale-110"
                    style={{ backgroundColor: `#${hex}` }}
                    title={`#${hex} (${region.pixelCount}px) — ${t("palette_multi_select_click_remove")}`}
                  />
                );
              })}
            </div>
          )}

            {/* Free color summary */}
            <FreeColorSummary freeColors={free_color_set} />
          </div>

          {/* Palette items */}
          <div
            className="dock-scrollbar min-h-0 flex-1 overflow-y-auto pr-1"
            role="listbox"
            aria-label={t("palette_list_label")}
          >
            <div
              className={
                enable_relief
                  ? "grid grid-cols-[repeat(auto-fit,minmax(7rem,1fr))] gap-2"
                  : "grid grid-cols-[repeat(auto-fit,minmax(3.4rem,1fr))] gap-2"
              }
            >
              {palette.map((entry) => (
                <PaletteItem
                  key={entry.matched_hex}
                  entry={entry}
                  isSelected={getIsSelected(entry.matched_hex)}
                  remappedHex={colorRemapMap[entry.matched_hex]}
                  heightMm={color_height_map[entry.matched_hex]}
                  showHeightSlider={enable_relief}
                  maxHeight={heightmap_max_height}
                  isFreeColor={free_color_set.has(entry.matched_hex)}
                  onSelect={() => handleSelect(entry.matched_hex)}
                  onHeightChange={(h) => updateColorHeight(entry.matched_hex, h)}
                />
              ))}
            </div>
          </div>
        </div>
      )}
      <CustomRecipeDialog
        open={recipeDialogOpen}
        sessionId={sessionId ?? ""}
        palette={(selectedLutInfo?.palette ?? []).map((entry) => ({
          color: entry.color_name ?? entry.color,
          material: entry.material,
        }))}
        regionIds={
          selectedRegions.length > 0
            ? selectedRegions.map((region) => region.regionId)
            : (regionData?.regionId ? [regionData.regionId] : [])
        }
        colorLayers={color_layers ?? selectedLutInfo?.max_color_layers ?? 5}
        layerHeightMm={layer_height_mm ?? selectedLutInfo?.layer_height_mm ?? 0.08}
        layerOrder={selectedLutInfo?.layer_order ?? "Top2Bottom"}
        baseChannelIdx={selectedLutInfo?.base_channel_idx ?? 0}
        onClose={() => setRecipeDialogOpen(false)}
        onApplied={(response, recipe, nextLayers, nextLayerHeightMm) => {
          const activeRegionIds =
            selectedRegions.length > 0
              ? selectedRegions.map((region) => region.regionId)
              : (regionData?.regionId ? [regionData.regionId] : []);
          useConverterStore.setState((state) => ({
            previewImageUrl: normalizeResourceUrl(response.preview_url) ?? response.preview_url,
            previewBaseImageUrl: normalizeResourceUrl(response.preview_url) ?? response.preview_url,
            previewGlbUrl: response.preview_glb_url
              ? normalizeResourceUrl(response.preview_glb_url)
              : state.previewGlbUrl,
            color_layers: Math.max(state.color_layers ?? 0, nextLayers),
            layer_height_mm: nextLayerHeightMm,
            recipe_overrides: [
              ...state.recipe_overrides.filter(
                (item) => !activeRegionIds.includes(item.region_id),
              ),
              ...activeRegionIds.map((regionId) => ({
                region_id: regionId,
                recipe: [...recipe],
                layer_order: selectedLutInfo?.layer_order ?? "Top2Bottom",
              })),
            ],
            lutMatchMode: "predictive",
            lutMatchInfo: {
              ...(state.lutMatchInfo ?? {}),
              match_mode: "predictive",
              runtime_mode_key: response.runtime_mode_key ?? null,
              source: response.source,
              override: true,
            },
          }));
        }}
      />
    </div>
  );
}
