import { useState, useMemo, useCallback, useEffect, memo } from "react";
import {
  isMaterialArchiveSourceVersion,
  useConverterStore,
} from "../../stores/converter";
import { useSettingsStore } from "../../stores/settingsStore";
import { hexToRgb, sortByColorDistance } from "../../utils/colorUtils";
import { isCardModeAvailable } from "../../utils/cardUtils";
import type { LutColorEntry, LutColorsCard } from "../../api/types";
import { useI18n } from "../../i18n/context";
import { cx, cardClass, compactFieldClass, wellClass, wellPadClass } from "../ui/panelPrimitives";
import MaterialColorPicker from "./MaterialColorPicker";

export type HueCategory =
  | "all"
  | "fav"
  | "red"
  | "orange"
  | "yellow"
  | "green"
  | "cyan"
  | "blue"
  | "purple"
  | "neutral";

// HUE_FILTERS moved inside component for i18n

export function classifyHue(r: number, g: number, b: number): HueCategory {
  const rf = r / 255;
  const gf = g / 255;
  const bf = b / 255;
  const max = Math.max(rf, gf, bf);
  const min = Math.min(rf, gf, bf);
  const d = max - min;
  const s = max === 0 ? 0 : d / max;
  const v = max;

  // 提高一致性色阈值，减少低饱和度颜色的误分类
  if (s < 0.2 || v < 0.15) return "neutral";

  let h = 0;
  if (d !== 0) {
    if (max === rf) h = ((gf - bf) / d) % 6;
    else if (max === gf) h = (bf - rf) / d + 2;
    else h = (rf - gf) / d + 4;
  }
  h = ((h * 60) + 360) % 360;

  // 使用更宽松的色相范围，减少边界色块
  // 核心策略：扩大每个色相类别的范围，让边界区域有更大容错空间
  if (h < 20 || h >= 340) return "red";      // 红色: 340-20掳 (扩大 10掳)
  if (h < 50) return "orange";                // 橙色: 20-50掳 (扩大 20掳)
  if (h < 80) return "yellow";                // 黄色: 50-80掳 (扩大 20掳)
  if (h < 170) return "green";                // 绿色: 80-170掳 (扩大 20掳)
  if (h < 200) return "cyan";                 // 青色: 170-200掳 (扩大 10掳)
  if (h < 270) return "blue";                 // 蓝色: 200-270掳 (扩大 20掳)
  if (h < 340) return "purple";               // 紫色: 270-340° (扩大 10°)
  return "neutral";
}

/**
 * Check if a LUT color entry matches a search query.
 * 检查 LUT 颜色条目是否匹配搜索查询。
 */
export function matchesSearch(entry: LutColorEntry, query: string): boolean {
  const q = query.toLowerCase().trim();
  if (!q) return true;
  const hexNoHash = entry.hex.replace("#", "").toLowerCase();
  if (hexNoHash.includes(q.replace("#", ""))) return true;
  const rgbMatch = q.match(/(\d{1,3})\s*[,\s]\s*(\d{1,3})\s*[,\s]\s*(\d{1,3})/);
  if (rgbMatch) {
    const [, rs, gs, bs] = rgbMatch;
    const [r, g, b] = entry.rgb;
    if (r === Number(rs) && g === Number(gs) && b === Number(bs)) return true;
  }
  return false;
}

// ========== Favorites persistence ==========

function loadFavorites(lutKey: string): Set<string> {
  try {
    const stored = localStorage.getItem(`lut_favorites_${lutKey}`);
    return stored ? new Set(JSON.parse(stored) as string[]) : new Set();
  } catch { return new Set(); }
}

function saveFavorites(lutKey: string, favs: Set<string>) {
  try {
    localStorage.setItem(`lut_favorites_${lutKey}`, JSON.stringify([...favs]));
  } catch { /* noop */ }
}

// ========== Compact ColorSwatch ==========

const SWATCH_GRID_CLASS = "grid grid-cols-[repeat(auto-fit,minmax(3rem,1fr))] gap-1.5";
const CARD_CELL_SIZE = "clamp(14px, 1vw, 18px)";

const ColorSwatch = memo(function ColorSwatch({
  entry,
  isTarget,
  isFav,
  onClick,
  onDoubleClick,
}: {
  entry: LutColorEntry;
  isTarget: boolean;
  isFav: boolean;
  onClick: () => void;
  onDoubleClick: () => void;
}) {
  const { t } = useI18n();
  return (
    <button
      type="button"
      aria-label={`${t("lut_grid_color_label").replace("{hex}", entry.hex)}${isFav ? ` (${t("lut_grid_color_fav")})` : ""}`}
      aria-selected={isTarget}
      onClick={onClick}
      onDoubleClick={(e) => { e.stopPropagation(); onDoubleClick(); }}
      className={`relative flex w-full min-w-0 flex-col items-center rounded-[10px] border px-1 py-1.5 transition-colors ${
        isTarget
          ? "border-amber-400 bg-amber-400/10"
          : "border-transparent hover:border-[color:var(--surface-card-outline)] hover:bg-[var(--nav-chip-hover)]"
      }`}
      title={`${entry.hex} · ${isFav ? t("lut_grid_dblclick_unfav") : t("lut_grid_dblclick_fav")}`}
    >
      <span
        className="block h-[clamp(1.1rem,1.7vw,1.3rem)] w-[clamp(1.1rem,1.7vw,1.3rem)] rounded-md border border-slate-300/80 dark:border-slate-600/80"
        style={{ backgroundColor: entry.hex }}
      />
      {isFav && (
        <span className="absolute -top-0.5 -right-0.5 text-[8px] leading-none text-yellow-400">★</span>
      )}
      <span className="mt-0.5 w-full truncate text-center font-mono text-[clamp(0.45rem,0.6vw,0.5rem)] leading-none text-slate-500 dark:text-slate-400">
        {entry.hex}
      </span>
    </button>
  );
});

// Card mode helpers have been moved inside the main component to access state variables.

/**
 * Dispatcher: renders :class:`MaterialColorPicker` in material-archive mode
 * and :class:`LutColorGridInner` otherwise. Keeping this split avoids calling
 * :func:`useState`/:func:`useMemo` conditionally in the LUT implementation.
 * 调度组件：材料档案模式转到 MaterialColorPicker，否则渲染 LUT 内部实现。
 * 拆分用以避免在条件分支前后调用 hook。
 */
export default function LutColorGrid() {
  const sourceVersion = useConverterStore((s) => s.source_version);
  if (isMaterialArchiveSourceVersion(sourceVersion)) {
    return <MaterialColorPicker />;
  }
  return <LutColorGridInner />;
}

function LutColorGridInner() {
  const { t } = useI18n();
  const paletteMode = useSettingsStore((s) => s.paletteMode);
  const setPaletteMode = useSettingsStore((s) => s.setPaletteMode);

  const HUE_FILTERS: { key: HueCategory; label: string; dot: string }[] = [
    { key: "all", label: t("lut_grid_hue_all_short"), dot: "" },
    { key: "fav", label: t("lut_grid_hue_fav_short"), dot: "" },
    { key: "red", label: t("lut_grid_hue_red_short"), dot: "#e53935" },
    { key: "orange", label: t("lut_grid_hue_orange_short"), dot: "#fb8c00" },
    { key: "yellow", label: t("lut_grid_hue_yellow_short"), dot: "#fdd835" },
    { key: "green", label: t("lut_grid_hue_green_short"), dot: "#43a047" },
    { key: "cyan", label: t("lut_grid_hue_cyan_short"), dot: "#00acc1" },
    { key: "blue", label: t("lut_grid_hue_blue_short"), dot: "#1e88e5" },
    { key: "purple", label: t("lut_grid_hue_purple_short"), dot: "#8e24aa" },
    { key: "neutral", label: t("lut_grid_hue_neutral_short"), dot: "#9e9e9e" },
  ];

  const palette = useConverterStore((s) => s.palette);
  const selectedColor = useConverterStore((s) => s.selectedColor);
  const colorRemapMap = useConverterStore((s) => s.colorRemapMap);
  const lutColors = useConverterStore((s) => s.lutColors);
  const lutColorCards = useConverterStore((s) => s.lutColorCards);
  const lutColorsLoading = useConverterStore((s) => s.lutColorsLoading);
  const lutColorsLutName = useConverterStore((s) => s.lutColorsLutName);
  const selectionMode = useConverterStore((s) => s.selectionMode);
  const selectedColors = useConverterStore((s) => s.selectedColors);
  const selectedRegions = useConverterStore((s) => s.selectedRegions);
  const replacePreviewLoading = useConverterStore((s) => s.replacePreviewLoading);
  const setPendingReplacement = useConverterStore((s) => s.setPendingReplacement);
  const pendingReplacement = useConverterStore((s) => s.pendingReplacement);
  const confirmReplacement = useConverterStore((s) => s.confirmReplacement);
  const colorMode = useConverterStore((s) => s.color_mode);
  const [hueFilter, setHueFilter] = useState<HueCategory>("all");
  const [searchText, setSearchText] = useState("");
  const [favorites, setFavorites] = useState<Set<string>>(new Set());

  const cardAvailable = useMemo(
    () => isCardModeAvailable(colorMode) && lutColorCards.length > 0,
    [colorMode, lutColorCards.length],
  );

  // --- Local Components ---
  const CardSection = ({
    colors,
    cols,
    title,
    selectedColor,
    colorRemapMap,
    onColorClick,
  }: {
    colors: LutColorEntry[];
    cols: number;
    title?: string;
    selectedColor: string | null;
    colorRemapMap: Record<string, string>;
    onColorClick: (hex: string) => void;
  }) => {
    return (
      <div>
        {title && (
          <p className="mb-2 text-[clamp(0.65rem,0.8vw,0.7rem)] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{title}</p>
        )}
        <div
          className={cx(wellClass, "p-2")}
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(${cols}, ${CARD_CELL_SIZE})`,
            gap: "clamp(1px, 0.2vw, 2px)",
          }}
        >
          {colors.map((c, i) => {
            const hexNoHash = c.hex.replace("#", "");
            const isTarget = selectedColor
              ? colorRemapMap[selectedColor] === hexNoHash
              : false;
            const [r, g, b] = c.rgb;
            return (
              <button
                key={`${c.hex}-${i}`}
                type="button"
                title={`${c.hex} · RGB(${r}, ${g}, ${b})`}
                onClick={() => onColorClick(c.hex)}
                className={`cursor-pointer rounded-[8px] border transition-colors ${
                  isTarget
                    ? "border-amber-500"
                    : "border-transparent hover:border-slate-400"
                }`}
                style={{
                  width: CARD_CELL_SIZE,
                  height: CARD_CELL_SIZE,
                  backgroundColor: c.hex,
                }}
              />
            );
          })}
        </div>
      </div>
    );
  };

  const CardGrid = ({
    cards,
    selectedColor,
    colorRemapMap,
    onColorClick,
  }: {
    cards: LutColorsCard[];
    selectedColor: string | null;
    colorRemapMap: Record<string, string>;
    onColorClick: (hex: string) => void;
  }) => {
    const visibleCards = cards.filter((card) => card.colors.length > 0);
    if (visibleCards.length === 0) return null;
    const cardTitle = (card: LutColorsCard) => {
      if (card.page.card_label === "A") return t("lut_grid_card_a");
      if (card.page.card_label === "B") return t("lut_grid_card_b");
      return t("lut_grid_card_label").replace("{card}", card.page.card_label);
    };
    return (
      <div className="flex gap-3 overflow-auto">
        {visibleCards.map((card) => (
          <CardSection
            key={`${card.page.page_index}-${card.page.card_label}`}
            colors={card.colors}
            cols={card.page.data_cols}
            title={visibleCards.length > 1 ? cardTitle(card) : undefined}
            selectedColor={selectedColor}
            colorRemapMap={colorRemapMap}
            onColorClick={onColorClick}
          />
        ))}
      </div>
    );
  };

  // Load favorites when LUT changes
  useEffect(() => {
    if (lutColorsLutName) {
      setFavorites(loadFavorites(lutColorsLutName));
    } else {
      setFavorites(new Set());
    }
  }, [lutColorsLutName]);

  const toggleFav = useCallback((hex: string) => {
    const key = hex.toLowerCase();
    setFavorites((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      if (lutColorsLutName) saveFavorites(lutColorsLutName, next);
      return next;
    });
  }, [lutColorsLutName]);

  const usedHexSet = useMemo(() => {
    const s = new Set<string>();
    for (const e of palette) s.add(`#${e.matched_hex}`.toLowerCase());
    return s;
  }, [palette]);

  const { usedColors, otherColors, visibleCount } = useMemo(() => {
    const used: LutColorEntry[] = [];
    const other: LutColorEntry[] = [];

    for (const c of lutColors) {
      const hex = c.hex.toLowerCase();
      const [r, g, b] = c.rgb;

      // Favorites filter
      if (hueFilter === "fav") {
        if (!favorites.has(hex)) continue;
        if (searchText && !matchesSearch(c, searchText)) continue;
      } else {
        if (hueFilter !== "all" && classifyHue(r, g, b) !== hueFilter) continue;
        if (searchText && !matchesSearch(c, searchText)) continue;
      }

      if (usedHexSet.has(hex)) used.push(c);
      else other.push(c);
    }
    return { usedColors: used, otherColors: other, visibleCount: used.length + other.length };
  }, [lutColors, hueFilter, searchText, usedHexSet, favorites]);

  const recommendations = useMemo(() => {
    if (!selectedColor || lutColors.length === 0) return null;
    return sortByColorDistance(hexToRgb(selectedColor), lutColors, 12);
  }, [selectedColor, lutColors]);

  const handleColorClick = (clickedHex: string) => {
    if (replacePreviewLoading) return;

    const hexNoHash = clickedHex.replace("#", "");

    // Gradient-region-aware routing lives in ``confirmReplacement`` so
    // the user still sees the familiar source→target preview bar and can
    // cancel before committing. See store.ts :func:`confirmReplacement`.
    // 区域精确替换的分岔放在 confirmReplacement 里，让用户保留"确认替换"
    // 按钮的交互；此处仍走既有 setPendingReplacement 流程。
    switch (selectionMode) {
      case 'select-all': {
        // 全选模式：支持多选源色批量替换
        const colors = selectedColors.size > 0
          ? Array.from(selectedColors)
          : selectedColor ? [selectedColor] : [];
        if (colors.length === 0) return;
        setPendingReplacement({
          sourceHex: colors[0],
          targetHex: hexNoHash,
          mode: 'select-all',
          sourceColors: colors.length > 1 ? colors : undefined,
        });
        break;
      }
      case 'multi-select': {
        // 多选模式（多区域）：需要先在 3D 模型上选中至少一个连通区域
        if (selectedRegions.length === 0) return;
        setPendingReplacement({
          sourceHex: selectedColor ?? '',
          targetHex: hexNoHash,
          mode: 'multi-select',
          sourceRegions: [...selectedRegions],
        });
        break;
      }
      case 'current':
      case 'region': {
        // 当前/区域模式：设置 pending 状态
        setPendingReplacement({
          sourceHex: selectedColor ?? '',
          targetHex: hexNoHash,
          mode: selectionMode,
        });
        break;
      }
    }
  };

  return (
    <div className="relative h-full">
      {replacePreviewLoading && (
        <div className="absolute inset-0 z-10 flex items-center justify-center rounded-2xl bg-slate-950/40">
          <p className="text-xs text-slate-100">{t("lut_grid_loading")}</p>
        </div>
      )}
      {lutColorsLoading ? (
        <p className="py-4 text-sm text-slate-500 dark:text-slate-400">{t("lut_grid_loading")}</p>
      ) : lutColors.length === 0 ? (
        <p className="py-4 text-sm text-slate-500 dark:text-slate-400">{t("lut_grid_select_lut")}</p>
      ) : (
        <div className={cx(cardClass, "panel-default-surface flex h-full flex-col gap-3 px-4 py-4")}>
          {/* Confirmation preview bar */}
          {pendingReplacement && (
            <div className={cx(wellPadClass, "flex flex-col gap-2")}>
              <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                {/* Source color swatch(es) */}
                <div className="flex min-w-0 flex-wrap items-center gap-0.5">
                  {pendingReplacement.mode === 'select-all' && pendingReplacement.sourceColors && pendingReplacement.sourceColors.length > 1 ? (
                    pendingReplacement.sourceColors.map((hex) => (
                      <span
                        key={hex}
                        className="inline-block h-5 w-5 rounded-md border border-slate-400/80 dark:border-slate-500/80"
                        style={{ backgroundColor: `#${hex}` }}
                        title={`#${hex}`}
                      />
                    ))
                  ) : pendingReplacement.mode === 'multi-select' && pendingReplacement.sourceRegions ? (
                    pendingReplacement.sourceRegions.map((region) => {
                      const hex = region.colorHex.replace(/^#/, "");
                      return (
                        <span
                          key={region.regionId}
                          className="inline-block h-5 w-5 rounded-md border border-slate-400/80 dark:border-slate-500/80"
                          style={{ backgroundColor: `#${hex}` }}
                          title={`#${hex} (${region.pixelCount}px)`}
                        />
                      );
                    })
                  ) : (
                    <span
                      className="inline-block h-5 w-5 rounded-md border border-slate-400/80 dark:border-slate-500/80"
                      style={{ backgroundColor: `#${pendingReplacement.sourceHex}` }}
                      title={`#${pendingReplacement.sourceHex}`}
                    />
                  )}
                </div>
                {/* Arrow */}
                <span className="text-xs text-slate-400">→</span>
                {/* Target color swatch */}
                <span
                  className="inline-block h-5 w-5 shrink-0 rounded-md border border-slate-400/80 dark:border-slate-500/80"
                  style={{ backgroundColor: `#${pendingReplacement.targetHex}` }}
                  title={`#${pendingReplacement.targetHex}`}
                />
              </div>
              <div className="flex flex-wrap justify-end gap-1.5">
                {/* Confirm button */}
                <button
                  type="button"
                  onClick={() => confirmReplacement()}
                  className="action-control rounded-full px-2.5 py-1 text-[10px] font-medium transition-colors"
                >
                  {t("replace_confirm_btn")}
                </button>
                {/* Cancel button */}
                <button
                  type="button"
                  onClick={() => setPendingReplacement(null)}
                  className="ghost-control rounded-full px-2.5 py-1 text-[10px] font-medium text-slate-700 dark:text-slate-200"
                >
                  {t("replace_cancel_btn")}
                </button>
              </div>
            </div>
          )}

          {/* Status line */}
          <p className="text-[clamp(0.65rem,0.8vw,0.7rem)] leading-tight text-slate-500 dark:text-slate-400">
            {t("lut_grid_total_colors")
              .replace("{total}", String(lutColors.length))
              .replace("{visible}", String(visibleCount))}
            {favorites.size > 0 && ` · ★${favorites.size}`}
            {selectedColor && (
              // Keep deletion ownership on an element if external tools replace its text.
              <span>
                {` · ${t("lut_grid_selected")} `}
                <span
                  className="inline-block h-2.5 w-2.5 rounded-md border border-slate-400/80 align-middle dark:border-slate-500/80"
                  style={{ backgroundColor: `#${selectedColor}` }}
                />
                <span className="font-mono text-[clamp(0.55rem,0.75vw,0.625rem)]"> #{selectedColor}</span>
              </span>
            )}
          </p>

          {/* Search */}
          <input
            type="text"
            placeholder={t("lut_grid_search_placeholder_short")}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            className={cx(compactFieldClass, "text-[clamp(0.65rem,0.85vw,0.75rem)]")}
          />

          {/* Hue filter bar + mode toggle */}
          <div className="flex items-center gap-0.5">
            <div className="flex flex-wrap gap-0.5">
              {HUE_FILTERS.map((f) => (
                <button
                  key={f.key}
                  type="button"
                  onClick={() => setHueFilter(f.key)}
                  className={`ghost-control flex items-center gap-0.5 rounded-full px-2 py-1 text-[clamp(0.55rem,0.75vw,0.625rem)] ${
                    hueFilter === f.key ? "" : "text-slate-500 dark:text-slate-400"
                  }`}
                  data-active={hueFilter === f.key ? "true" : undefined}
                >
                  {f.key === "fav" ? (
                    <span className="text-yellow-400 text-[9px]">★</span>
                  ) : f.dot ? (
                    <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ backgroundColor: f.dot }} />
                  ) : null}
                  {f.label}
                </button>
              ))}
            </div>
            {cardAvailable && (
              <>
                <div className="flex-1" />
                <div className="flex items-center gap-0.5 shrink-0">
                  <button
                    type="button"
                    onClick={() => setPaletteMode("swatch")}
                    className={`ghost-control rounded-full px-2 py-1 text-[clamp(0.55rem,0.75vw,0.625rem)] ${
                      paletteMode === "swatch" ? "" : "text-slate-500 dark:text-slate-400"
                    }`}
                    data-active={paletteMode === "swatch" ? "true" : undefined}
                  >
                    {t("lut_grid_mode_swatch")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setPaletteMode("card")}
                    className={`ghost-control rounded-full px-2 py-1 text-[clamp(0.55rem,0.75vw,0.625rem)] ${
                      paletteMode === "card" ? "" : "text-slate-500 dark:text-slate-400"
                    }`}
                    data-active={paletteMode === "card" ? "true" : undefined}
                  >
                    {t("lut_grid_mode_card")}
                  </button>
                </div>
              </>
            )}
          </div>

          {/* Color grid: conditional swatch vs card rendering */}
          {paletteMode === "card" && cardAvailable ? (
            <CardGrid
              cards={lutColorCards}
              selectedColor={selectedColor}
              colorRemapMap={colorRemapMap}
              onColorClick={handleColorClick}
            />
          ) : (
            <div className="dock-scrollbar min-h-0 flex-1 flex flex-col gap-2 overflow-y-auto pr-1" role="listbox" aria-label={t("palette_list_label")}>
              {recommendations && recommendations.length > 0 && (
                <div>
                  <p className="mb-1 text-[clamp(0.65rem,0.8vw,0.7rem)] font-semibold text-amber-500">
                    {t("lut_grid_recommendations")} ({recommendations.length})
                  </p>
                  <div className={SWATCH_GRID_CLASS}>
                    {recommendations.map((c) => {
                      const hexNoHash = c.hex.replace("#", "");
                      const isTarget = selectedColor ? colorRemapMap[selectedColor] === hexNoHash : false;
                      return (
                        <div key={c.hex}>
                          <ColorSwatch
                            entry={c}
                            isTarget={isTarget}
                            isFav={favorites.has(c.hex.toLowerCase())}
                            onClick={() => handleColorClick(c.hex)}
                            onDoubleClick={() => toggleFav(c.hex)}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
              {/* Used Colors Section */}
              {usedColors.length > 0 && (
                <div>
                  <p className="mb-1 text-[clamp(0.65rem,0.8vw,0.7rem)] font-semibold text-emerald-500">
                    {t("lut_grid_used_in_image")} ({usedColors.length})
                  </p>
                  <div className={SWATCH_GRID_CLASS}>
                    {usedColors.map((c) => {
                      const hexNoHash = c.hex.replace("#", "");
                      const isTarget = selectedColor ? colorRemapMap[selectedColor] === hexNoHash : false;
                      return (
                        <div key={c.hex}>
                          <ColorSwatch
                            entry={c}
                            isTarget={isTarget}
                            isFav={favorites.has(c.hex.toLowerCase())}
                            onClick={() => handleColorClick(c.hex)}
                            onDoubleClick={() => toggleFav(c.hex)}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Other/All Colors Section */}
              {otherColors.length > 0 && (
                <div>
                  <p className="mb-1 text-[clamp(0.65rem,0.8vw,0.7rem)] font-semibold text-slate-500 dark:text-slate-400">
                    {usedColors.length > 0 ? `${t("lut_grid_other_available")} (${otherColors.length})` : `${t("lut_grid_all_available")} (${otherColors.length})`}
                  </p>
                  <div className={SWATCH_GRID_CLASS}>
                    {otherColors.map((c) => {
                      const hexNoHash = c.hex.replace("#", "");
                      const isTarget = selectedColor ? colorRemapMap[selectedColor] === hexNoHash : false;
                      return (
                        <div key={c.hex}>
                          <ColorSwatch
                            entry={c}
                            isTarget={isTarget}
                            isFav={favorites.has(c.hex.toLowerCase())}
                            onClick={() => handleColorClick(c.hex)}
                            onDoubleClick={() => toggleFav(c.hex)}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {visibleCount === 0 && (
                <p className="py-1 text-xs text-slate-500 dark:text-slate-400">{t("lut_grid_no_match")}</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
