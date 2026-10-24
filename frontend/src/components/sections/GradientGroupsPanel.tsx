import CloseButton from "../ui/CloseButton";
import { memo, useCallback, useState, type ChangeEvent } from "react";
import { useConverterStore } from "../../stores/converter";
import { useSettingsStore } from "../../stores/settingsStore";
import { useI18n } from "../../i18n/context";
import {
  StatusBanner,
  cardDividerClass,
  cx,
} from "../ui/panelPrimitives";
import type {
  GradientGroupItem,
  GradientRegionItem,
  GradientSelectionSource,
} from "../../api/types";
import { apiErrorToVisibleMessage } from "../../api/client";
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
 * Hard bounds matching ``MIN_LOCAL_QUANTIZE_COLORS`` and
 * ``MAX_LOCAL_QUANTIZE_COLORS`` in :mod:`core.gradient_region_requantize`.
 * The backend rejects values outside this range with HTTP 422, so the
 * slider + input in the dialog are clamped here to fail fast in the UI.
 * 二次量化弹窗滑块的上下界，必须与后端 core 常量一致，超出范围会被
 * FastAPI 422 校验拒绝。
 */
const REQUANTIZE_COLORS_MIN = 12;
const REQUANTIZE_COLORS_MAX = 256;
const REQUANTIZE_COLORS_DEFAULT = 64;

/**
 * Explicit list of targets for the re-quantise dialog. The dialog is
 * driven by this list rather than by a single ``groupIndex`` so the same
 * component can serve:
 *   - per-region buttons (``targets.length === 1``),
 *   - the external batch button (may span multiple groups).
 * 明确保存 targets 而非单个 group：让同一个 dialog 同时服务"单 region"
 * 与"外部批量"两种触发路径。
 */
interface RequantizeDialogState {
  targets: ReadonlyArray<{ groupIndex: number; regionIndex: number }>;
  /** Currently-configured colour budget in the slider/input. */
  value: number;
  /**
   * When true, clear the checkbox-based selection after a successful
   * submit. Set by the batch path (the dialog already snapshotted the
   * selection into ``targets`` so clearing is safe), cleared for the
   * per-region path so the user's in-progress selection survives.
   * 批量路径提交后清空勾选；单 region 路径保留勾选。
   */
  clearSelectionOnSubmit: boolean;
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
  const selectedGradientRegions = useConverterStore(
    (s) => s.selectedGradientRegions,
  );
  const toggleGradientRegionSelection = useConverterStore(
    (s) => s.toggleGradientRegionSelection,
  );
  const flattenSelectedGradientRegions = useConverterStore(
    (s) => s.flattenSelectedGradientRegions,
  );
  const requantizeSelectedGradientRegions = useConverterStore(
    (s) => s.requantizeSelectedGradientRegions,
  );
  const clearGradientRegionSelection = useConverterStore(
    (s) => s.clearGradientRegionSelection,
  );
  const autoReplaceEnabled = useSettingsStore(
    (s) => s.autoReplaceGradientBanding,
  );

  // Re-quantise dialog: user must pick a quantize count (12-256) before the
  // action submits. State is panel-local because the dialog lives inside
  // this tree; the store-level action only takes the final chosen count.
  // 二次量化弹窗：用户先选定量化色数（12-256）再提交；状态仅在面板内部。
  const [requantizeDialog, setRequantizeDialog] =
    useState<RequantizeDialogState | null>(null);

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
          setHighlightError(t("api_error_http_default"));
          return;
        }
        setHighlightDialog({ title: params.title, imageUrl: url });
      } catch (err) {
        setHighlightError(
          apiErrorToVisibleMessage(err, t("api_error_http_default")),
        );
      } finally {
        setHighlightLoading(false);
      }
    },
    [sessionId, t],
  );

  const closeHighlightDialog = useCallback(() => {
    setHighlightDialog(null);
    setHighlightError(null);
    setHighlightLoading(false);
  }, []);

  /**
   * Open the requantize dialog for a single region, independently of the
   * batch checkbox list. Wired to the per-region button so power users can
   * correct one region without touching their in-progress merge set.
   * 单 region 二次量化入口；不依赖勾选列表，避免破坏批量选择态。
   */
  const handleOpenSingleRegionRequantize = useCallback(
    (groupIndex: number, regionIndex: number) => {
      setRequantizeDialog({
        targets: [{ groupIndex, regionIndex }],
        value: REQUANTIZE_COLORS_DEFAULT,
        // Per-region path: keep the in-progress checkbox list intact.
        // 单 region 入口：保留勾选列表。
        clearSelectionOnSubmit: false,
      });
    },
    [],
  );

  /**
   * Open the requantize dialog for every region currently ticked across
   * all groups. This powers the external batch button that lives in the
   * panel header so users don't need to scroll back into a group row to
   * find the action.
   * 外部批量按钮：拿全部已勾选 regions（可能跨组）一次性二次量化。
   */
  const handleOpenBatchRequantize = useCallback(() => {
    if (selectedGradientRegions.length === 0) return;
    setRequantizeDialog({
      targets: selectedGradientRegions.map((t) => ({
        groupIndex: t.groupIndex,
        regionIndex: t.regionIndex,
      })),
      value: REQUANTIZE_COLORS_DEFAULT,
      // Batch path: snapshot the selection into targets, then clear the
      // checkbox list on submit so the panel returns to a clean state
      // matching the flatten/merge UX.
      // 批量入口：快照勾选，提交后清空多选与 flatten 保持一致。
      clearSelectionOnSubmit: true,
    });
  }, [selectedGradientRegions]);

  const closeRequantizeDialog = useCallback(() => {
    setRequantizeDialog(null);
  }, []);
  const submitRequantize = useCallback(() => {
    if (!requantizeDialog) return;
    const value = Math.max(
      REQUANTIZE_COLORS_MIN,
      Math.min(REQUANTIZE_COLORS_MAX, Math.round(requantizeDialog.value)),
    );
    // Always pass explicit targets: the dialog owns the list so the store
    // action does not accidentally bulldoze the user's in-progress merge
    // selection when a per-region button triggered the dialog.
    // Dialog 始终显式传 targets，避免 per-region 调用清掉用户勾选。
    void requantizeSelectedGradientRegions(value, requantizeDialog.targets);
    if (requantizeDialog.clearSelectionOnSubmit) {
      clearGradientRegionSelection();
    }
    setRequantizeDialog(null);
  }, [
    requantizeDialog,
    requantizeSelectedGradientRegions,
    clearGradientRegionSelection,
  ]);

  if (sourceVersion !== "material") {
    return null;
  }

  if (loading) {
    return (
      <p className="text-[clamp(0.6rem,0.75vw,0.65rem)] text-slate-500 dark:text-slate-400">
        {t("gradient_groups_loading")}
      </p>
    );
  }

  if (error) {
    return (
      <StatusBanner role="alert" tone="error">
        {t("gradient_groups_error").replace("{message}", error)}
      </StatusBanner>
    );
  }

  // ``null`` means we haven't fetched yet for this session; ``[]`` means the
  // backend ran but found nothing. Hide the panel in both cases to keep the
  // Color Workstation clutter-free for images without banding.
  if (!groups || groups.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-col gap-2" data-testid="gradient-groups-panel">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-0.5">
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
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          {/* External batch re-quantize button.
              Lives in the header so the user never has to scroll back to
              the group a checked region belongs to after assembling the
              selection. Disabled + explanatory tooltip when nothing is
              checked so the button is always discoverable.
              外置批量二次量化按钮：勾完 regions 后直接在顶部点击，
              无需回到对应 group 行；未勾选时禁用并给出 tooltip 提示。 */}
          <button
            type="button"
            onClick={handleOpenBatchRequantize}
            disabled={
              replacePreviewLoading || selectedGradientRegions.length === 0
            }
            title={
              selectedGradientRegions.length === 0
                ? t("gradient_groups_batch_requantize_empty")
                : undefined
            }
            className="action-control rounded-full px-2.5 py-1 text-[10px] font-medium"
            data-testid="gradient-groups-batch-requantize"
          >
            {t("gradient_groups_batch_requantize").replace(
              "{count}",
              String(selectedGradientRegions.length),
            )}
          </button>
          <button
            type="button"
            onClick={() => {
              void applyAutoGradientReplace();
            }}
            disabled={replacePreviewLoading}
            className="action-control action-control-primary rounded-lg px-2.5 py-1 text-[10px] font-medium"
          >
            {t("gradient_groups_apply_now")}
          </button>
        </div>
      </header>

      {autoReplaceEnabled && (
        <StatusBanner tone="success">
          {t("gradient_groups_auto_banner")}
        </StatusBanner>
      )}

      <div className={cardDividerClass} aria-hidden="true" />

      <ul className="flex max-h-[220px] flex-col gap-1.5 overflow-y-auto pr-1">
        {groups.map((group) => (
          <GradientGroupRow
            key={group.group_index}
            group={group}
            selectedColors={selectedColors}
            selectionMode={selectionMode}
            gradientSelection={gradientSelection}
            selectedGradientRegions={selectedGradientRegions}
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
            onToggleRegionCheck={(groupIndex, regionIndex) =>
              toggleGradientRegionSelection(groupIndex, regionIndex)
            }
            onFlattenSelected={() => void flattenSelectedGradientRegions()}
            onOpenRegionRequantize={handleOpenSingleRegionRequantize}
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

      {requantizeDialog && (
        <RequantizeDialog
          state={requantizeDialog}
          onChangeValue={(value) =>
            setRequantizeDialog((prev) =>
              prev ? { ...prev, value } : prev,
            )
          }
          onSubmit={submitRequantize}
          onClose={closeRequantizeDialog}
          submitting={replacePreviewLoading}
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
          <CloseButton label={t("gradient_groups_view_highlight_close")} onClick={onClose} />
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
// Requantise dialog
// 二次量化弹窗：选择 12-256 的量化色数后提交
// ---------------------------------------------------------------------------

interface RequantizeDialogProps {
  state: RequantizeDialogState;
  onChangeValue: (value: number) => void;
  onSubmit: () => void;
  onClose: () => void;
  submitting: boolean;
}

/**
 * Modal that asks the user for a per-region quantise count (12-256) before
 * submitting the re-quantise action. Larger values preserve more colour
 * detail (closer to the source gradient), smaller values are closer to a
 * flatten. The slider + numeric input share state so power users can type
 * an exact value while most users slide. The confirm button is disabled
 * while ``submitting`` to prevent double submissions during the backend
 * round-trip.
 * 量化色数（12-256）选择弹窗：滑块 + 输入框联动；12 偏 flatten，256 最大
 * 保留原图色阶；提交中禁用确认避免重复请求。
 */
function RequantizeDialog({
  state,
  onChangeValue,
  onSubmit,
  onClose,
  submitting,
}: RequantizeDialogProps) {
  const { t } = useI18n();
  const handleSliderChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      onChangeValue(Number(event.target.value));
    },
    [onChangeValue],
  );
  const handleNumberChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const raw = Number(event.target.value);
      if (Number.isNaN(raw)) return;
      onChangeValue(
        Math.max(
          REQUANTIZE_COLORS_MIN,
          Math.min(REQUANTIZE_COLORS_MAX, Math.round(raw)),
        ),
      );
    },
    [onChangeValue],
  );

  // Derive display-only strings from the targets list. The description
  // copy reads naturally for both the "one region in group N" case and
  // the "several regions across multiple groups" case without growing a
  // second i18n entry — the shared sentinel string (多组 / multiple) swaps
  // in when the selection spans more than one gradient group.
  // 文案派生：目标跨组时把 {group} 填成本地化的"多组"哨兵，避免新增第二条
  // i18n key。单组 + 多 region 与单 region 都能读通。
  const regionCount = state.targets.length;
  const groupIndices = Array.from(
    new Set(state.targets.map((t) => t.groupIndex)),
  );
  const groupLabel =
    groupIndices.length === 1
      ? String(groupIndices[0])
      : t("gradient_groups_requantize_dialog_multi_group");

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t("gradient_groups_requantize_dialog_title")}
      className="fixed inset-0 z-50 flex items-center justify-center p-4 backdrop-blur-sm"
      style={{ background: "var(--surface-scrim)" }}
      onClick={onClose}
    >
      <div
        className="flex w-[min(88vw,420px)] flex-col gap-3 rounded-xl border p-4 shadow-2xl"
        style={{
          borderColor: "var(--surface-outline)",
          background: "var(--surface-panel-strong)",
        }}
        onClick={(e) => e.stopPropagation()}
        data-testid="requantize-dialog"
      >
        <div className="flex flex-col gap-1">
          <p className="text-[11px] leading-tight text-slate-500 dark:text-slate-400">
            {t("gradient_groups_requantize_dialog_description")
              .replace("{count}", String(regionCount))
              .replace("{group}", groupLabel)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="range"
            min={REQUANTIZE_COLORS_MIN}
            max={REQUANTIZE_COLORS_MAX}
            step={1}
            value={state.value}
            onChange={handleSliderChange}
            aria-label={t("gradient_groups_requantize_dialog_slider_label")}
            className="flex-1 cursor-pointer accent-purple-600"
            data-testid="requantize-dialog-slider"
          />
          <input
            type="number"
            min={REQUANTIZE_COLORS_MIN}
            max={REQUANTIZE_COLORS_MAX}
            step={1}
            value={state.value}
            onChange={handleNumberChange}
            aria-label={t("gradient_groups_requantize_dialog_slider_label")}
            className="w-16 rounded-md border px-2 py-1 text-center text-xs"
            style={{
              borderColor: "var(--surface-outline)",
              background: "var(--surface-panel-inset)",
              color: "var(--text-primary)",
            }}
            data-testid="requantize-dialog-input"
          />
        </div>
        <p className="text-[10px] leading-tight text-slate-500 dark:text-slate-400">
          {t("gradient_groups_requantize_dialog_hint")
            .replace("{min}", String(REQUANTIZE_COLORS_MIN))
            .replace("{max}", String(REQUANTIZE_COLORS_MAX))}
        </p>
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-full bg-slate-300 px-3 py-1 text-xs font-medium text-slate-800 transition-colors hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-100 dark:hover:bg-slate-600"
          >
            {t("gradient_groups_requantize_dialog_cancel")}
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={submitting}
            className="action-control action-control-primary rounded-lg px-3 py-1 text-xs font-medium"
            data-testid="requantize-dialog-submit"
          >
            {submitting
              ? t("gradient_groups_requantize_dialog_submitting")
              : t("gradient_groups_requantize_dialog_submit")}
          </button>
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
  selectedGradientRegions: ReadonlyArray<{
    groupIndex: number;
    regionIndex: number;
  }>;
  disabled: boolean;
  onSelectGroup: (groupIndex: number, hexes: string[]) => void;
  onSelectRegion: (
    groupIndex: number,
    regionIndex: number,
    hexes: string[],
  ) => void;
  onFlattenGroup: (groupIndex: number) => void;
  onFlattenRegion: (groupIndex: number, regionIndex: number) => void;
  onToggleRegionCheck: (groupIndex: number, regionIndex: number) => void;
  onFlattenSelected: () => void;
  /**
   * Opens the requantize dialog for a single region. Wired into the
   * per-region row so the user can re-quantize without touching the
   * checkbox-based merge list. Called on the child row via the pass-
   * through; the group row itself no longer exposes a requantize button.
   * 每个 region 行的二次量化入口，不干扰已有的多选勾选。
   */
  onOpenRegionRequantize: (groupIndex: number, regionIndex: number) => void;
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
  selectedGradientRegions,
  disabled,
  onSelectGroup,
  onSelectRegion,
  onFlattenGroup,
  onFlattenRegion,
  onToggleRegionCheck,
  onFlattenSelected,
  onOpenRegionRequantize,
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

  // Count of this group's regions that are currently ticked in the merge
  // checklist. Drives the conditional 'Merge flatten' button: shown only
  // when ≥2 regions of *this specific* group are checked, because the
  // flow is a no-op (or indistinguishable from the per-region flatten)
  // for a single checked row.
  // 本 group 内被勾选的 region 数量；仅当 ≥2 时显示"合并去海带纹"按钮。
  const mergeCount = selectedGradientRegions.filter(
    (r) => r.groupIndex === group.group_index,
  ).length;
  const handleFlattenSelected = useCallback(() => {
    onFlattenSelected();
  }, [onFlattenSelected]);

  return (
    <li
      className={cx(
        "flex flex-col gap-1 border-t border-[color:var(--surface-divider)] px-2 py-1.5 transition-colors first:border-t-0",
        allSelected && "bg-blue-500/10",
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
            aria-pressed={allSelected}
            className="ghost-control rounded-lg px-2.5 py-0.5 text-[10px] font-medium text-slate-700 dark:text-slate-200"
          >
            {t("gradient_groups_select_group")}
          </button>
          <button
            type="button"
            onClick={handleFlattenGroup}
            disabled={disabled}
            className="action-control rounded-full px-2.5 py-0.5 text-[10px] font-medium"
          >
            {t("gradient_groups_flatten_group")}
          </button>
          {mergeCount >= 2 && (
            <button
              type="button"
              onClick={handleFlattenSelected}
              disabled={disabled}
              className="action-control rounded-full px-2.5 py-0.5 text-[10px] font-medium"
              data-testid={`merge-flatten-${group.group_index}`}
            >
              {t("gradient_groups_merge_flatten").replace(
                "{count}",
                String(mergeCount),
              )}
            </button>
          )}
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
          {group.regions.map((region) => {
            const isChecked = selectedGradientRegions.some(
              (r) =>
                r.groupIndex === group.group_index &&
                r.regionIndex === region.region_index,
            );
            return (
              <GradientRegionRow
                key={region.region_index}
                groupIndex={group.group_index}
                region={region}
                selectedColors={selectedColors}
                selectionMode={selectionMode}
                gradientSelection={gradientSelection}
                isChecked={isChecked}
                disabled={disabled}
                onSelectRegion={onSelectRegion}
                onFlattenRegion={onFlattenRegion}
                onToggleCheck={onToggleRegionCheck}
                onOpenRegionHighlight={onOpenRegionHighlight}
                onOpenRegionRequantize={onOpenRegionRequantize}
              />
            );
          })}
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
  isChecked: boolean;
  disabled: boolean;
  onSelectRegion: (
    groupIndex: number,
    regionIndex: number,
    hexes: string[],
  ) => void;
  onFlattenRegion: (groupIndex: number, regionIndex: number) => void;
  onToggleCheck: (groupIndex: number, regionIndex: number) => void;
  onOpenRegionHighlight: (
    groupIndex: number,
    regionIndex: number,
    hexes: string[],
  ) => void;
  /**
   * Opens the requantize dialog for this one region. Independent of the
   * checkbox list so the user can correct one region without losing an
   * in-progress batch selection.
   * 单 region 二次量化弹窗入口，与多选状态无关。
   */
  onOpenRegionRequantize: (groupIndex: number, regionIndex: number) => void;
}

const GradientRegionRow = memo(function GradientRegionRow({
  groupIndex,
  region,
  selectedColors,
  selectionMode,
  gradientSelection,
  isChecked,
  disabled,
  onSelectRegion,
  onFlattenRegion,
  onToggleCheck,
  onOpenRegionHighlight,
  onOpenRegionRequantize,
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
  const handleToggleCheck = useCallback(() => {
    onToggleCheck(groupIndex, region.region_index);
  }, [groupIndex, region.region_index, onToggleCheck]);
  const handleOpenRequantize = useCallback(() => {
    onOpenRegionRequantize(groupIndex, region.region_index);
  }, [groupIndex, region.region_index, onOpenRegionRequantize]);

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
          ? "bg-blue-500/15"
          : "bg-slate-200/50 dark:bg-slate-800/50",
      )}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        <input
          type="checkbox"
          checked={isChecked}
          onChange={handleToggleCheck}
          disabled={disabled}
          aria-label={t("gradient_groups_merge_checkbox_label").replace(
            "{index}",
            String(region.region_index),
          )}
          data-testid={`merge-check-${groupIndex}-${region.region_index}`}
          className="h-3 w-3 cursor-pointer accent-indigo-600 disabled:cursor-not-allowed"
        />
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
          aria-pressed={regionSelected}
          className="ghost-control rounded-lg px-2 py-0.5 text-[10px] font-medium text-slate-700 dark:text-slate-200"
        >
          {t("gradient_groups_select_region")}
        </button>
        <button
          type="button"
          onClick={handleFlatten}
          disabled={disabled}
          className="action-control rounded-full px-2 py-0.5 text-[10px] font-medium"
        >
          {t("gradient_groups_flatten_region")}
        </button>
        {/* Per-region re-quantize button.
            Runs through ``handleOpenSingleRegionRequantize`` at the panel
            level with an explicit 1-region target list, so it does NOT
            disturb an in-progress checkbox selection. Purple styling
            matches the external batch button to signal "same action".
            单 region 二次量化：与外部批量按钮同色区分，内部不依赖勾选列表。 */}
        <button
          type="button"
          onClick={handleOpenRequantize}
          disabled={disabled}
          className="action-control rounded-full px-2 py-0.5 text-[10px] font-medium"
          data-testid={`requantize-region-${groupIndex}-${region.region_index}`}
        >
          {t("gradient_groups_requantize_region")}
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
      className="action-control flex h-5 w-5 items-center justify-center rounded-full transition-colors"
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
