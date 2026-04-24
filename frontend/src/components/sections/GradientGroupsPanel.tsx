import { memo, useCallback, useState } from "react";
import { useConverterStore } from "../../stores/converter";
import { useSettingsStore } from "../../stores/settingsStore";
import { useI18n } from "../../i18n/context";
import {
  cx,
  workstationInsetCardClass,
} from "../ui/panelPrimitives";
import type {
  GradientGroupItem,
  GradientRegionItem,
  GradientSelectionSource,
} from "../../api/types";
import {
  colorHighlight,
  type ColorHighlightScope,
} from "../../api/converter";
import { normalizeResourceUrl } from "../../utils/resourceUrl";

/**
 * State for the "View highlight" side-by-side preview dialog. Kept separate
 * from the main converter store so opening the dialog is a read-only probe
 * into the backend highlight endpoint — it must *not* mutate
 * ``previewImageUrl``, ``selectedColors`` or ``gradientSelection``.
 * 查看高亮图对话框的本地状态；不会触碰主 store 的预览图/选中状态，确保
 * 仅作为只读诊断窗口。
 */
interface HighlightDialogState {
  title: string;
  imageUrl: string;
}

/**
 * Gradient Groups Panel — material-archive only.
 * 渐变分组面板（仅材料档案模式）。
 *
 * Surfaces gradient banding clusters the backend detected during preview:
 * smooth source gradients that got quantised across multiple material
 * colours. Users can:
 *   - One-click select every colour in a gradient group → then pick a
 *     replacement target in :file:`MaterialColorPicker` for one-shot
 *     multi-replace.
 *   - Expand a group to see its spatial regions and select a region's
 *     material breakdown instead (affects colours in that region; may
 *     bleed into other regions sharing the same material hex — first
 *     iteration intentionally simple).
 *   - Run :func:`applyAutoGradientReplace` on demand (even when the
 *     advanced auto-replace toggle is off) via the "Flatten all gradients"
 *     action.
 *
 * Hidden (renders ``null``) when not in material-archive mode or when the
 * backend reported no banding to avoid adding dead UI chrome.
 */
export default function GradientGroupsPanel() {
  const { t } = useI18n();
  const sourceVersion = useConverterStore((s) => s.source_version);
  const groups = useConverterStore((s) => s.gradientGroups);
  const loading = useConverterStore((s) => s.gradientGroupsLoading);
  const error = useConverterStore((s) => s.gradientGroupsError);
  const selectedColors = useConverterStore((s) => s.selectedColors);
  const selectionMode = useConverterStore((s) => s.selectionMode);
  const gradientSelection = useConverterStore((s) => s.gradientSelection);
  const sessionId = useConverterStore((s) => s.sessionId);
  const replacePreviewLoading = useConverterStore(
    (s) => s.replacePreviewLoading,
  );
  const selectGradientGroupColors = useConverterStore(
    (s) => s.selectGradientGroupColors,
  );
  const applyAutoGradientReplace = useConverterStore(
    (s) => s.applyAutoGradientReplace,
  );
  const applyGradientReplaceForGroup = useConverterStore(
    (s) => s.applyGradientReplaceForGroup,
  );
  const autoReplaceEnabled = useSettingsStore(
    (s) => s.autoReplaceGradientBanding,
  );

  // Diagnostic "View highlight" dialog: users can peek at the exact cyan
  // mask the backend returns for a given group/region without going through
  // the main preview path. This is invaluable when the main canvas looks
  // wrong — they can compare the dialog's image (direct API output) against
  // the canvas render to localise whether a bug lives in the backend mask
  // computation or in the frontend preview pipeline.
  // 诊断用途的高亮对比对话框：直接展示后端返回的 cyan 图，不走主预览
  // 管线，方便区分"后端 mask 算错"和"前端预览渲染错"。
  const [highlightDialog, setHighlightDialog] =
    useState<HighlightDialogState | null>(null);
  const [highlightLoading, setHighlightLoading] = useState(false);
  const [highlightError, setHighlightError] = useState<string | null>(null);

  const handleOpenHighlight = useCallback(
    async (params: {
      title: string;
      hexes: string[];
      scope?: ColorHighlightScope;
    }) => {
      if (!sessionId) return;
      setHighlightLoading(true);
      setHighlightError(null);
      setHighlightDialog({ title: params.title, imageUrl: "" });
      try {
        const res = await colorHighlight(
          sessionId,
          params.hexes,
          params.scope,
        );
        const url = normalizeResourceUrl(res.preview_url);
        if (!url) {
          throw new Error("empty preview_url");
        }
        setHighlightDialog({ title: params.title, imageUrl: url });
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setHighlightError(message);
      } finally {
        setHighlightLoading(false);
      }
    },
    [sessionId],
  );

  const closeHighlightDialog = useCallback(() => {
    setHighlightDialog(null);
    setHighlightError(null);
    setHighlightLoading(false);
  }, []);

  if (sourceVersion !== "material") {
    return null;
  }

  if (loading) {
    return (
      <div
        className={cx(
          workstationInsetCardClass,
          "flex flex-col gap-1 px-3 py-2",
        )}
      >
        <p className="text-[clamp(0.6rem,0.75vw,0.65rem)] text-slate-500 dark:text-slate-400">
          {t("gradient_groups_loading")}
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div
        role="alert"
        className={cx(
          workstationInsetCardClass,
          "flex flex-col gap-1 border-rose-400/50 bg-rose-500/10 px-3 py-2 dark:border-rose-600/50",
        )}
      >
        <p className="text-[clamp(0.6rem,0.75vw,0.65rem)] text-rose-600 dark:text-rose-300">
          {t("gradient_groups_error").replace("{message}", error)}
        </p>
      </div>
    );
  }

  // ``null`` means we haven't fetched yet for this session; ``[]`` means the
  // backend ran but found nothing. Hide the panel in both cases to keep the
  // Color Workstation clutter-free for images without banding.
  if (!groups || groups.length === 0) {
    return null;
  }

  return (
    <div
      className={cx(workstationInsetCardClass, "flex flex-col gap-2 p-3")}
      data-testid="gradient-groups-panel"
    >
      <header className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-0.5">
          <h4 className="text-[clamp(0.7rem,0.85vw,0.75rem)] font-semibold text-slate-700 dark:text-slate-200">
            {t("gradient_groups_title")}
          </h4>
          <p className="text-[clamp(0.6rem,0.75vw,0.65rem)] leading-tight text-slate-500 dark:text-slate-400">
            {t("gradient_groups_hint").replace(
              "{count}",
              String(groups.length),
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            void applyAutoGradientReplace();
          }}
          disabled={replacePreviewLoading}
          className="shrink-0 rounded-full bg-emerald-600 px-2.5 py-1 text-[10px] font-medium text-white transition-colors hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {t("gradient_groups_apply_now")}
        </button>
      </header>

      {autoReplaceEnabled && (
        <p className="rounded-lg bg-emerald-500/10 px-2 py-1 text-[10px] text-emerald-700 dark:text-emerald-300">
          {t("gradient_groups_auto_banner")}
        </p>
      )}

      <ul className="flex max-h-[220px] flex-col gap-1.5 overflow-y-auto pr-1">
        {groups.map((group) => (
          <GradientGroupRow
            key={group.group_index}
            group={group}
            selectedColors={selectedColors}
            selectionMode={selectionMode}
            gradientSelection={gradientSelection}
            disabled={replacePreviewLoading}
            onSelectGroup={(groupIndex, hexes) =>
              selectGradientGroupColors(hexes, {
                kind: "group",
                groupIndex,
              })
            }
            onSelectRegion={(groupIndex, regionIndex, hexes) =>
              selectGradientGroupColors(hexes, {
                kind: "region",
                groupIndex,
                regionIndex,
              })
            }
            onFlattenGroup={(groupIndex) =>
              void applyGradientReplaceForGroup(groupIndex)
            }
            onFlattenRegion={(groupIndex, regionIndex) =>
              void applyGradientReplaceForGroup(groupIndex, regionIndex)
            }
            onOpenGroupHighlight={(groupIndex, hexes) =>
              void handleOpenHighlight({
                title: t(
                  "gradient_groups_view_highlight_group_title",
                ).replace("{index}", String(groupIndex)),
                hexes,
                // Whole group: no scope → endpoint scans the full canvas
                // for any matching colour (matches the "Select all" button
                // semantics).
                // 整组：不传 scope → 全图匹配该组所有色（与"选中整组"一致）。
                scope: undefined,
              })
            }
            onOpenRegionHighlight={(groupIndex, regionIndex, hexes) =>
              void handleOpenHighlight({
                title: t(
                  "gradient_groups_view_highlight_region_title",
                )
                  .replace("{group}", String(groupIndex))
                  .replace("{region}", String(regionIndex)),
                hexes,
                scope: {
                  gradientGroupIndex: groupIndex,
                  gradientRegionIndex: regionIndex,
                },
              })
            }
          />
        ))}
      </ul>

      {highlightDialog && (
        <HighlightPreviewDialog
          title={highlightDialog.title}
          imageUrl={highlightDialog.imageUrl}
          loading={highlightLoading}
          error={highlightError}
          onClose={closeHighlightDialog}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Highlight preview dialog
// 高亮对比对话框
// ---------------------------------------------------------------------------

interface HighlightPreviewDialogProps {
  title: string;
  imageUrl: string;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}

/**
 * Modal overlay that renders the raw cyan-highlight image the backend
 * produced for a given group/region. Deliberately stateless & independent
 * of :func:`useConverterStore` so it can double as a visual ground truth
 * when the main preview canvas disagrees with expectations.
 * 全屏 modal，直接渲染后端 /color-highlight 返回的 cyan 预览图；与主 store
 * 解耦，作为视觉 ground truth 供比对。
 */
function HighlightPreviewDialog({
  title,
  imageUrl,
  loading,
  error,
  onClose,
}: HighlightPreviewDialogProps) {
  const { t } = useI18n();
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 flex items-center justify-center p-4 backdrop-blur-sm"
      style={{ background: "var(--surface-scrim)" }}
      onClick={onClose}
    >
      <div
        className="flex max-h-[90vh] w-[min(90vw,1200px)] flex-col gap-2 rounded-xl border p-4 shadow-2xl"
        style={{
          borderColor: "var(--surface-outline)",
          background: "var(--surface-panel-strong)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
            {title}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full bg-slate-700 px-3 py-1 text-xs font-medium text-slate-50 transition-colors hover:bg-slate-600 dark:bg-slate-200 dark:text-slate-900 dark:hover:bg-slate-50"
          >
            {t("gradient_groups_view_highlight_close")}
          </button>
        </div>
        <div
          className="flex min-h-[320px] flex-1 items-center justify-center overflow-hidden rounded-lg"
          style={{ background: "var(--surface-panel-inset)" }}
        >
          {loading && (
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {t("gradient_groups_view_highlight_loading")}
            </p>
          )}
          {!loading && error && (
            <p className="px-4 text-center text-xs text-rose-600 dark:text-rose-300">
              {t("gradient_groups_view_highlight_error").replace(
                "{message}",
                error,
              )}
            </p>
          )}
          {!loading && !error && imageUrl && (
            <img
              src={imageUrl}
              alt={title}
              className="max-h-[80vh] max-w-full object-contain"
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Row components
// ---------------------------------------------------------------------------

interface GradientGroupRowProps {
  group: GradientGroupItem;
  selectedColors: Set<string>;
  selectionMode: string;
  gradientSelection: GradientSelectionSource | null;
  disabled: boolean;
  onSelectGroup: (groupIndex: number, hexes: string[]) => void;
  onSelectRegion: (
    groupIndex: number,
    regionIndex: number,
    hexes: string[],
  ) => void;
  onFlattenGroup: (groupIndex: number) => void;
  onFlattenRegion: (groupIndex: number, regionIndex: number) => void;
  onOpenGroupHighlight: (groupIndex: number, hexes: string[]) => void;
  onOpenRegionHighlight: (
    groupIndex: number,
    regionIndex: number,
    hexes: string[],
  ) => void;
}

const GradientGroupRow = memo(function GradientGroupRow({
  group,
  selectedColors,
  selectionMode,
  gradientSelection,
  disabled,
  onSelectGroup,
  onSelectRegion,
  onFlattenGroup,
  onFlattenRegion,
  onOpenGroupHighlight,
  onOpenRegionHighlight,
}: GradientGroupRowProps) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);

  const groupHexes = group.material_colours.map((mc) => mc.hex);
  const normalisedGroupHexes = groupHexes.map((hex) =>
    hex.replace(/^#/, "").toLowerCase(),
  );

  const handleSelectGroup = useCallback(() => {
    onSelectGroup(group.group_index, groupHexes);
  }, [group.group_index, groupHexes, onSelectGroup]);

  const handleFlattenGroup = useCallback(() => {
    onFlattenGroup(group.group_index);
  }, [group.group_index, onFlattenGroup]);

  const handleOpenGroupHighlight = useCallback(() => {
    onOpenGroupHighlight(group.group_index, groupHexes);
  }, [group.group_index, groupHexes, onOpenGroupHighlight]);

  const toggleExpanded = useCallback(() => {
    setExpanded((prev) => !prev);
  }, []);

  // Two-sided check for exclusive highlighting:
  //   (1) the last panel click identified *this* group as the origin,
  //   (2) selectedColors still matches the group's full material set.
  // This disambiguates the "region breakdown equals group materials" case
  // and also auto-dims the button if the user has since edited the multi-
  // select manually (via the LUT grid), without needing explicit cleanup.
  // 双重判断：点击来源是本组 + selectedColors 仍与本组完全一致。既能区分
  // 区域选中 vs 整组选中，也能在用户手动改动多选后自然失活按钮高亮。
  const allSelected =
    gradientSelection?.kind === "group" &&
    gradientSelection.groupIndex === group.group_index &&
    selectionMode === "select-all" &&
    selectedColors.size === normalisedGroupHexes.length &&
    normalisedGroupHexes.every((hex) => selectedColors.has(hex));

  return (
    <li
      className={cx(
        "flex flex-col gap-1 rounded-xl border px-2 py-1.5 transition-colors",
        allSelected
          ? "border-blue-500/80 bg-blue-500/10"
          : "border-slate-200/60 bg-slate-100/60 dark:border-slate-700/60 dark:bg-slate-900/50",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <SwatchRow colors={group.material_colours.map((mc) => mc.hex)} max={10} />
          <span className="text-[10px] text-slate-500 dark:text-slate-400">
            {t("gradient_groups_materials_count").replace(
              "{count}",
              String(group.material_colour_count),
            )}
            {" · "}
            {t("gradient_groups_pixels_count").replace(
              "{count}",
              formatCount(group.total_pixel_count),
            )}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={handleSelectGroup}
            disabled={disabled}
            className={cx(
              "rounded-full px-2.5 py-0.5 text-[10px] font-medium transition-colors",
              allSelected
                ? "bg-blue-600 text-white hover:bg-blue-500"
                : "bg-slate-800 text-white hover:bg-slate-700 dark:bg-slate-200 dark:text-slate-900 dark:hover:bg-slate-50",
              "disabled:cursor-not-allowed disabled:opacity-60",
            )}
          >
            {t("gradient_groups_select_group")}
          </button>
          <button
            type="button"
            onClick={handleFlattenGroup}
            disabled={disabled}
            className="rounded-full bg-emerald-600 px-2.5 py-0.5 text-[10px] font-medium text-white transition-colors hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {t("gradient_groups_flatten_group")}
          </button>
          <HighlightEyeButton
            onClick={handleOpenGroupHighlight}
            ariaLabel={t("gradient_groups_view_highlight")}
            disabled={disabled}
          />
        </div>
      </div>

      {group.regions.length > 0 && (
        <button
          type="button"
          onClick={toggleExpanded}
          className="self-start text-[10px] text-slate-500 transition-colors hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
        >
          {expanded
            ? t("gradient_groups_collapse_regions")
            : t("gradient_groups_expand_regions").replace(
                "{count}",
                String(group.regions.length),
              )}
        </button>
      )}

      {expanded && group.regions.length > 0 && (
        <ul className="flex flex-col gap-1 pl-1">
          {group.regions.map((region) => (
            <GradientRegionRow
              key={region.region_index}
              groupIndex={group.group_index}
              region={region}
              selectedColors={selectedColors}
              selectionMode={selectionMode}
              gradientSelection={gradientSelection}
              disabled={disabled}
              onSelectRegion={onSelectRegion}
              onFlattenRegion={onFlattenRegion}
              onOpenRegionHighlight={onOpenRegionHighlight}
            />
          ))}
        </ul>
      )}
    </li>
  );
});

interface GradientRegionRowProps {
  groupIndex: number;
  region: GradientRegionItem;
  selectedColors: Set<string>;
  selectionMode: string;
  gradientSelection: GradientSelectionSource | null;
  disabled: boolean;
  onSelectRegion: (
    groupIndex: number,
    regionIndex: number,
    hexes: string[],
  ) => void;
  onFlattenRegion: (groupIndex: number, regionIndex: number) => void;
  onOpenRegionHighlight: (
    groupIndex: number,
    regionIndex: number,
    hexes: string[],
  ) => void;
}

const GradientRegionRow = memo(function GradientRegionRow({
  groupIndex,
  region,
  selectedColors,
  selectionMode,
  gradientSelection,
  disabled,
  onSelectRegion,
  onFlattenRegion,
  onOpenRegionHighlight,
}: GradientRegionRowProps) {
  const { t } = useI18n();

  const hexes = region.material_breakdown.map((mb) => mb.hex);
  const normalisedHexes = hexes.map((hex) =>
    hex.replace(/^#/, "").toLowerCase(),
  );
  const handleSelect = useCallback(() => {
    onSelectRegion(groupIndex, region.region_index, hexes);
  }, [groupIndex, region.region_index, hexes, onSelectRegion]);
  const handleFlatten = useCallback(() => {
    onFlattenRegion(groupIndex, region.region_index);
  }, [groupIndex, region.region_index, onFlattenRegion]);
  const handleOpenHighlight = useCallback(() => {
    onOpenRegionHighlight(groupIndex, region.region_index, hexes);
  }, [groupIndex, region.region_index, hexes, onOpenRegionHighlight]);

  // Mirrors the group-row logic: only this exact region should light up as
  // the selection origin, so clicking a region does *not* leave the parent
  // group button still highlighted (the original bug).
  // 与整组同理：只有该区域自己按钮高亮，避免父分组按钮错误地继续保持选中态。
  const regionSelected =
    gradientSelection?.kind === "region" &&
    gradientSelection.groupIndex === groupIndex &&
    gradientSelection.regionIndex === region.region_index &&
    selectionMode === "select-all" &&
    selectedColors.size === normalisedHexes.length &&
    normalisedHexes.every((hex) => selectedColors.has(hex));

  return (
    <li
      className={cx(
        "flex items-center justify-between gap-2 rounded-lg px-2 py-1 transition-colors",
        regionSelected
          ? "bg-blue-500/15 ring-1 ring-blue-500/50"
          : "bg-slate-200/50 dark:bg-slate-800/50",
      )}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        <SwatchRow colors={hexes} max={6} />
        <span className="text-[10px] text-slate-500 dark:text-slate-400">
          {t("gradient_groups_region_label").replace(
            "{index}",
            String(region.region_index),
          )}
          {" · "}
          {t("gradient_groups_pixels_count").replace(
            "{count}",
            formatCount(region.pixel_count),
          )}
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <button
          type="button"
          onClick={handleSelect}
          disabled={disabled}
          className={cx(
            "rounded-full px-2 py-0.5 text-[10px] font-medium transition-colors",
            regionSelected
              ? "bg-blue-600 text-white hover:bg-blue-500"
              : "bg-slate-700 text-white hover:bg-slate-600 dark:bg-slate-300 dark:text-slate-900 dark:hover:bg-slate-50",
            "disabled:cursor-not-allowed disabled:opacity-60",
          )}
        >
          {t("gradient_groups_select_region")}
        </button>
        <button
          type="button"
          onClick={handleFlatten}
          disabled={disabled}
          className="rounded-full bg-emerald-600 px-2 py-0.5 text-[10px] font-medium text-white transition-colors hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {t("gradient_groups_flatten_region")}
        </button>
        <HighlightEyeButton
          onClick={handleOpenHighlight}
          ariaLabel={t("gradient_groups_view_highlight")}
          disabled={disabled}
        />
      </div>
    </li>
  );
});

// ---------------------------------------------------------------------------
// Eye-icon button used by both group and region rows to open the diagnostic
// highlight preview dialog. Tiny dedicated component keeps the two row
// components free of duplicated SVG markup and a11y attributes.
// 诊断按钮（眼睛图标），复用在整组行和区域行上以打开高亮预览对话框。
// ---------------------------------------------------------------------------

interface HighlightEyeButtonProps {
  onClick: () => void;
  ariaLabel: string;
  disabled: boolean;
}

function HighlightEyeButton({
  onClick,
  ariaLabel,
  disabled,
}: HighlightEyeButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      title={ariaLabel}
      className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-200 text-slate-700 transition-colors hover:bg-slate-300 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-slate-700 dark:text-slate-200 dark:hover:bg-slate-600"
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="h-3 w-3"
        aria-hidden="true"
      >
        <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface SwatchRowProps {
  colors: string[];
  /** Maximum swatches to render; the rest collapse into a "+N" chip. */
  max: number;
}

function SwatchRow({ colors, max }: SwatchRowProps) {
  const visible = colors.slice(0, max);
  const overflow = colors.length - visible.length;
  return (
    <div className="flex items-center gap-0.5">
      {visible.map((hex, i) => (
        <span
          key={`${hex}-${i}`}
          className="inline-block h-4 w-4 rounded border border-slate-400/60 dark:border-slate-500/60"
          style={{ backgroundColor: hex }}
          title={hex}
        />
      ))}
      {overflow > 0 && (
        <span className="ml-0.5 text-[9px] text-slate-500 dark:text-slate-400">
          +{overflow}
        </span>
      )}
    </div>
  );
}

/** Format pixel counts with thousand separators for UI compactness. */
function formatCount(n: number): string {
  if (n >= 1_000_000) {
    return `${(n / 1_000_000).toFixed(1)}M`;
  }
  if (n >= 10_000) {
    return `${(n / 1_000).toFixed(1)}k`;
  }
  return new Intl.NumberFormat().format(n);
}
