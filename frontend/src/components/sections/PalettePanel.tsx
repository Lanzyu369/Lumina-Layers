import { useState, type ReactNode } from "react";
import { useConverterStore } from "../../stores/converter";
import type { PaletteEntry } from "../../api/types";
import Slider from "../ui/Slider";
import Button from "../ui/Button";
import Switch from "../ui/Switch";
import CustomRecipeDialog from "../ui/CustomRecipeDialog";
import { useI18n } from "../../i18n/context";
import { cx, workstationInsetCardClass, workstationPanelCardClass } from "../ui/panelPrimitives";
import { normalizeResourceUrl } from "../../utils/resourceUrl";

// ========== ToolbarGroup ==========

type ToolbarGroupTint = "slate" | "sky" | "rose" | "amber" | "emerald";

const TOOLBAR_GROUP_TINT_CLASS: Record<ToolbarGroupTint, string> = {
  slate:
    "bg-slate-100/70 border-slate-200/70 dark:bg-slate-800/40 dark:border-slate-700/50",
  sky:
    "bg-sky-50/80 border-sky-200/70 dark:bg-sky-950/30 dark:border-sky-900/50",
  rose:
    "bg-rose-50/80 border-rose-200/70 dark:bg-rose-950/30 dark:border-rose-900/50",
  amber:
    "bg-amber-50/80 border-amber-200/70 dark:bg-amber-950/30 dark:border-amber-900/50",
  emerald:
    "bg-emerald-50/80 border-emerald-200/70 dark:bg-emerald-950/25 dark:border-emerald-900/50",
};

const TOOLBAR_GROUP_LABEL_TINT_CLASS: Record<ToolbarGroupTint, string> = {
  slate: "text-slate-500 dark:text-slate-400",
  sky: "text-sky-700 dark:text-sky-300",
  rose: "text-rose-700 dark:text-rose-300",
  amber: "text-amber-700 dark:text-amber-300",
  emerald: "text-emerald-700 dark:text-emerald-300",
};

interface ToolbarGroupProps {
  label: string;
  tint: ToolbarGroupTint;
  children: ReactNode;
  contentClassName?: string;
}

/**
 * Toolbar group card: tinted background + a small header label on top,
 * followed by a row of compact controls aligned to a shared baseline.
 * 工具栏分组：淡色背景 + 顶部小标题 + 同一基线的紧凑按钮行。
 */
function ToolbarGroup({ label, tint, children, contentClassName }: ToolbarGroupProps) {
  return (
    <div
      className={cx(
        "flex flex-col gap-1 rounded-xl border px-2.5 py-1.5",
        TOOLBAR_GROUP_TINT_CLASS[tint],
      )}
      role="group"
      aria-label={label}
    >
      <span
        className={cx(
          "text-[10px] font-semibold uppercase tracking-[0.1em]",
          TOOLBAR_GROUP_LABEL_TINT_CLASS[tint],
        )}
      >
        {label}
      </span>
      <div className={contentClassName ?? "flex min-h-9 flex-wrap items-center gap-1.5"}>{children}</div>
    </div>
  );
}

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
  const gradientSelection = useConverterStore((s) => s.gradientSelection);
  const selectedRegions = useConverterStore((s) => s.selectedRegions);
  const regionData = useConverterStore((s) => s.regionData);
  const removeRegionFromSelection = useConverterStore((s) => s.removeRegionFromSelection);
  const free_color_set = useConverterStore((s) => s.free_color_set);
  const toggleFreeColor = useConverterStore((s) => s.toggleFreeColor);
  const clearFreeColors = useConverterStore((s) => s.clearFreeColors);
  const regionReplacementCount = useConverterStore((s) => s.regionReplacementCount);
  // Custom recipe lets users manually compose the layer stack for a region;
  // it is LUT-agnostic. Forward-model prediction is an optional add-on that
  // degrades gracefully inside the dialog when the LUT has no predictor.
  // 自定义配方是手动指定区域的叠层耗材，与 LUT 预测能力无关；预测按钮
  // 在无预测模型的 LUT 下会在对话框内优雅降级提示。
  const hasRegionTarget =
    selectedRegions.length > 0 || !!regionData?.regionId;
  const canUseCustomRecipe = hasRegionTarget;
  const customRecipeDisabledHint = !hasRegionTarget
    ? t("recipe_custom_disabled_region")
    : undefined;

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

  // When the current select-all set was populated from a gradient *region*
  // (not a whole group), the palette must NOT draw its usual "selected"
  // borders on those colour tiles. Each of the region's colours typically
  // appears elsewhere on the canvas too, so lighting up the tiles falsely
  // suggests "every instance of this colour is selected across the whole
  // image" — which is exactly the confusion users ran into: the preview
  // correctly showed only the region, but the palette made it look like a
  // whole-image multi-select.
  // 来源是"区域"的 select-all 不应把调色板色块渲染为选中态：同色在图上
  // 通常出现在多处，点亮色块会误导用户以为"全图这些色都被选中"，和预览
  // 上只点亮单个区域的事实不符。
  const isRegionScopedSelection = gradientSelection?.kind === 'region';

  const getIsSelected = (hex: string): boolean => {
    if (multiSelectHexSet) {
      return multiSelectHexSet.has(hex);
    }
    if (
      selectionMode === 'select-all' &&
      selectedColors.size > 0 &&
      !isRegionScopedSelection
    ) {
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
          {/* Toolbar: selected color detail + grouped action buttons */}
          <div className="shrink-0 flex flex-col gap-1.5">
            {/* Inline selected color swatches */}
            {selectedColor && (() => {
              const selectedEntry = palette.find(
                (e) => e.matched_hex === selectedColor
              );
              if (!selectedEntry) return null;
              const remapped = colorRemapMap[selectedColor];
              return (
                <div className="flex flex-wrap items-center gap-1.5">
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
                </div>
              );
            })()}

            {/* Grouped toolbar: auto-fit grid keeps every group card the same width */}
            <div className="grid grid-cols-[repeat(auto-fit,minmax(14rem,1fr))] gap-2">
              <ToolbarGroup label={t("palette_group_history")} tint="slate">
                <Button
                  label={t("palette_undo")}
                  variant="secondary"
                  size="sm"
                  onClick={undoColorRemap}
                  disabled={!hasHistory}
                />
                <Button
                  label={t("palette_clear_remaps")}
                  variant="secondary"
                  size="sm"
                  onClick={clearAllRemaps}
                  disabled={!hasRemaps}
                />
              </ToolbarGroup>

              <ToolbarGroup
                label={t("palette_group_mode")}
                tint="sky"
                contentClassName="grid min-h-9 grid-cols-[repeat(auto-fit,minmax(4.75rem,1fr))] items-center gap-1.5"
              >
                <Button
                  label={t("palette_mode_select_all")}
                  variant={selectionMode === 'select-all' ? 'primary' : 'secondary'}
                  size="sm"
                  onClick={() => setSelectionMode('select-all')}
                  className="w-full"
                />
                <Button
                  label={t("palette_mode_current")}
                  variant={selectionMode === 'current' ? 'primary' : 'secondary'}
                  size="sm"
                  onClick={() => setSelectionMode('current')}
                  className="w-full"
                />
                <Button
                  label={t("palette_mode_multi_select")}
                  variant={selectionMode === 'multi-select' ? 'primary' : 'secondary'}
                  size="sm"
                  onClick={() => setSelectionMode('multi-select')}
                  className="w-full"
                />
                <Button
                  label={t("palette_mode_region")}
                  variant={selectionMode === 'region' ? 'primary' : 'secondary'}
                  size="sm"
                  onClick={() => setSelectionMode('region')}
                  className="w-full"
                />
              </ToolbarGroup>

              <ToolbarGroup label={t("palette_group_free")} tint="rose">
                <Button
                  label={t("conv_free_color_btn")}
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    if (selectedColor) toggleFreeColor(selectedColor);
                  }}
                  disabled={selectedColor === null}
                />
                <Button
                  label={t("conv_free_color_clear_btn")}
                  variant="secondary"
                  size="sm"
                  onClick={clearFreeColors}
                  disabled={free_color_set.size === 0}
                />
              </ToolbarGroup>

              <ToolbarGroup label={t("palette_group_recipe")} tint="amber">
                <Button
                  label={t("recipe_custom_button")}
                  variant="secondary"
                  size="sm"
                  onClick={() => setRecipeDialogOpen(true)}
                  disabled={!canUseCustomRecipe}
                  title={customRecipeDisabledHint}
                />
              </ToolbarGroup>

              <ToolbarGroup label={t("viewer_hover_toggle_group")} tint="emerald">
                <label className="flex items-center gap-1.5 whitespace-nowrap text-[11px] text-slate-600 dark:text-slate-300">
                  <Switch
                    checked={showHoverMagnifier}
                    onChange={(checked) => onToggleHoverMagnifier?.(checked)}
                    ariaLabel={t("viewer_hover_toggle_magnifier")}
                  />
                  {t("viewer_hover_toggle_magnifier")}
                </label>
                <label className="flex items-center gap-1.5 whitespace-nowrap text-[11px] text-slate-600 dark:text-slate-300">
                  <Switch
                    checked={showHoverLayerDetails}
                    onChange={(checked) => onToggleHoverLayerDetails?.(checked)}
                    ariaLabel={t("viewer_hover_toggle_layers")}
                  />
                  {t("viewer_hover_toggle_layers")}
                </label>
              </ToolbarGroup>
            </div>
          </div>

          <div className="shrink-0 flex flex-col gap-1.5">
            {/* Select-all multi-color indicator. Hidden when the selection
                came from a gradient region — the amber "N colours selected"
                chip strip duplicates the already-confusing selection-border
                rendering on the palette and reinforces the wrong impression
                that the whole image will be acted on. The Gradient Groups
                panel itself still shows which region is active. */}
            {selectionMode === 'select-all' &&
              selectedColors.size > 0 &&
              !isRegionScopedSelection && (
            <div className={cx(workstationInsetCardClass, "flex min-h-11 flex-nowrap items-center gap-2 overflow-hidden px-3 py-2.5")}>
              <span className="shrink-0 whitespace-nowrap text-[clamp(0.55rem,0.75vw,0.625rem)] font-medium text-amber-500 dark:text-amber-400">
                {t("palette_multi_select_count").replace("{count}", String(selectedColors.size))}
              </span>
              <div className="dock-scrollbar flex min-w-0 flex-1 flex-nowrap items-center gap-1.5 overflow-x-auto overflow-y-hidden py-0.5">
                {Array.from(selectedColors).map((hex) => (
                  <button
                    key={hex}
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => handleSelect(hex)}
                    className="h-5 w-5 shrink-0 rounded-lg border-2 border-amber-400 shadow-sm transition-transform hover:scale-110"
                    style={{ backgroundColor: `#${hex}` }}
                    title={`#${hex} — ${t("palette_multi_select_click_remove")}`}
                  />
                ))}
              </div>
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
          hex: entry.hex_color ?? null,
        }))}
        regionIds={
          selectedRegions.length > 0
            ? selectedRegions.map((region) => region.regionId)
            : (regionData?.regionId ? [regionData.regionId] : [])
        }
        currentRegionColorHex={
          selectedRegions.length > 0
            ? selectedRegions[selectedRegions.length - 1]?.colorHex ?? null
            : regionData?.colorHex ?? null
        }
        colorLayers={color_layers ?? selectedLutInfo?.max_color_layers ?? 5}
        layerHeightMm={layer_height_mm ?? selectedLutInfo?.layer_height_mm ?? 0.08}
        layerOrder={selectedLutInfo?.layer_order ?? "Top2Bottom"}
        baseChannelIdx={selectedLutInfo?.base_channel_idx ?? 0}
        onClose={() => setRecipeDialogOpen(false)}
        onApplied={(response, recipe, nextLayers, nextLayerHeightMm, virtualMaterials) => {
          const activeRegionIds =
            selectedRegions.length > 0
              ? selectedRegions.map((region) => region.regionId)
              : (regionData?.regionId ? [regionData.regionId] : []);
          // Persist the virtual_materials declared at apply time alongside
          // the recipe. ``submitGenerate`` later forwards
          // ``state.recipe_overrides`` verbatim to ``/generate``; dropping
          // virtuals here makes the worker pipeline unable to extend the
          // palette, so S07 emits no mesh for the virtual-index pixels and
          // the 3MF loses that filament / object (表现为透明失效 / 方块 /
          // 3MF 缺对象). Only attach the key when the list is non-empty so
          // legacy non-virtual overrides keep their existing serialized
          // shape for recipe bundle round-trips.
          // 把 apply 时声明的虚拟耗材和 recipe 一起存进 store，后续
          // ``submitGenerate`` 会原样转发给 ``/generate``；丢掉 virtuals
          // 会让 worker 无法扩展调色板，S07 为虚拟索引像素生成不出 mesh，
          // 3MF 里也缺少对应的耗材 / 对象。只在非空时带 key，以免污染旧
          // recipe bundle 的序列化格式。
          const clonedVirtuals = virtualMaterials.map((material) => ({
            name: material.name,
            hex: material.hex,
          }));
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
                ...(clonedVirtuals.length > 0
                  ? {
                      virtual_materials: clonedVirtuals.map((material) => ({
                        ...material,
                      })),
                    }
                  : {}),
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
            // Invalidate the cached per-layer preview images so the next
            // hover / ActionBar render re-fetches against the post-apply
            // ``material_matrix``. Without this the stale pre-apply
            // layer list survives (it was sized to the original
            // ``color_layers``) and only the layers the override touched
            // look fresh — users see it as "分层预览只显示更改配方的那几
            // 层". Store-level ``applyCustomRecipeOverride`` already does
            // this via ``INVALIDATE_LAYER_IMAGES_AFTER_REPLACE``; the
            // dialog-driven path must stay consistent.
            // 刷新分层预览缓存：apply 后 material_matrix 的层数和内容都会
            // 变，继续沿用旧的 layerImages 会出现 "只显示更改配方的层，
            // 其它灰"。store 的 applyCustomRecipeOverride 本来就会通过
            // INVALIDATE_LAYER_IMAGES_AFTER_REPLACE 做同样的事，dialog
            // 路径也必须保持一致。
            layerImages: [] as typeof state.layerImages,
            layerImagesSourceKey: null,
          }));
        }}
      />
    </div>
  );
}
