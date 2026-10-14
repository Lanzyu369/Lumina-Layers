/**
 * SelectionToolPicker — shared selection tool buttons plus the active tool's
 * size control (colour-range tolerance or brush size). Renders grid children,
 * so the parent decides the column layout. Used by Color Adjustment and the
 * Color Workspace so both pages offer the same tools.
 * 共享的选择工具按钮及当前工具的参数滑块；渲染为网格子元素，由父级决定列布局。
 * 「颜色调整」与「颜色工作台」共用，保证两个页面的工具一致。
 */

import { useShallow } from "zustand/react/shallow";
import { useI18n } from "../../i18n/context";
import {
  MAX_COLOR_RANGE_TOLERANCE,
  useConverterStore,
  type SelectionTool,
} from "../../stores/converter";
import Button from "../ui/Button";

const TOOLS: { tool: SelectionTool; labelKey: string; titleKey?: string }[] = [
  { tool: "same-color", labelKey: "palette_mode_select_all", titleKey: "palette_mode_select_all" },
  { tool: "color-range", labelKey: "palette_mode_color_range", titleKey: "selection_color_range_hint" },
  { tool: "point", labelKey: "palette_mode_multi_select" },
  { tool: "brush", labelKey: "palette_mode_brush" },
];

const CONTROL_ROW_CLASS =
  "col-span-full flex items-center gap-2 px-1 text-[11px] text-slate-600 dark:text-slate-300";

export default function SelectionToolPicker() {
  const { t } = useI18n();
  const {
    selectionTool,
    setSelectionTool,
    colorRangeTolerance,
    setColorRangeTolerance,
    brushSizePx,
    setBrushSizePx,
  } = useConverterStore(
    useShallow((s) => ({
      selectionTool: s.selectionTool,
      setSelectionTool: s.setSelectionTool,
      colorRangeTolerance: s.colorRangeTolerance,
      setColorRangeTolerance: s.setColorRangeTolerance,
      brushSizePx: s.brushSizePx,
      setBrushSizePx: s.setBrushSizePx,
    })),
  );

  return (
    <>
      {TOOLS.map(({ tool, labelKey, titleKey }) => (
        <Button
          key={tool}
          label={t(labelKey)}
          variant="ghost"
          size="sm"
          active={selectionTool === tool}
          onClick={() => setSelectionTool(tool)}
          className="w-full"
          title={titleKey ? t(titleKey) : undefined}
        />
      ))}
      {selectionTool === "color-range" && (
        <label className={CONTROL_ROW_CLASS} data-testid="color-range-tolerance-control">
          <span className="shrink-0">{t("selection_color_range_tolerance")}</span>
          <input
            aria-label={t("selection_color_range_tolerance")}
            type="range"
            min={0}
            max={MAX_COLOR_RANGE_TOLERANCE}
            step={0.5}
            value={colorRangeTolerance}
            onChange={(event) => setColorRangeTolerance(Number(event.target.value))}
            className="min-w-0 flex-1 accent-sky-500"
          />
          <span className="shrink-0 tabular-nums">
            {t("quick_replace_delta_e_value").replace("{value}", colorRangeTolerance.toFixed(1))}
          </span>
        </label>
      )}
      {selectionTool === "brush" && (
        <label className={CONTROL_ROW_CLASS}>
          <span className="shrink-0">{t("selection_brush_size")}</span>
          <input
            aria-label={t("selection_brush_size")}
            type="range"
            min={2}
            max={160}
            value={brushSizePx}
            onChange={(event) => setBrushSizePx(Number(event.target.value))}
            className="min-w-0 flex-1 accent-pink-500"
          />
          <span className="w-10 text-right tabular-nums">{brushSizePx}px</span>
        </label>
      )}
    </>
  );
}
