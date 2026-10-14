import { useState } from "react";
import { BACKED_GRADIENT_THICKNESSES, type BackedGradientDataset, type BackedGradientSymbol } from "../api/luminaBoxBackedGradient";
import type { LuminaBoxMaterialDataset } from "../api/luminaBoxMaterials";
import type { useLuminaBoxBackedGradient } from "../hooks/useLuminaBoxBackedGradient";
import { useI18n } from "../i18n/context";
import { backedGradientSlotKey, type BackedGradientTarget } from "../utils/luminaBoxBackedGradientCapture";
import Button from "./ui/Button";
import { cardDividerClass, wellClass } from "./ui/panelPrimitives";

type Capture = ReturnType<typeof useLuminaBoxBackedGradient>;
export const boxMaterialInputClass = "min-h-11 w-full rounded-[10px] border border-[var(--surface-card-outline)] bg-[var(--surface-panel-strong)] px-3 py-2 text-sm outline-none focus:ring-4 focus:ring-[var(--focus-ring)] disabled:opacity-50";

const columnTarget = (symbol: BackedGradientSymbol, backing: "W" | "K", reference: boolean): BackedGradientTarget => ({
  material_symbol: reference ? (backing === "W" ? "K" : "W") : symbol,
  backing, sample_role: "coated",
});

/** Count only the samples needed by the active material or backing pair.
 * 仅统计当前耗材或背板组合需要的样片。 */
export function luminaBoxMaterialProgress(dataset: BackedGradientDataset | null, symbol: BackedGradientSymbol, reference: boolean) {
  const selected = new Set(Object.keys(dataset?.selected_capture_ids ?? {}));
  const workflow = (dataset as LuminaBoxMaterialDataset | null)?.workflow;
  if (workflow?.kind === "backing_material") {
    const role = workflow.material_symbol;
    const target: BackedGradientTarget = { material_symbol: role, backing: role === "W" ? "K" : "W", sample_role: "coated" };
    const slots = [...BACKED_GRADIENT_THICKNESSES.map((thickness) => backedGradientSlotKey(target, thickness)), `bare:${role}`];
    return { count: slots.filter((slot) => selected.has(slot)).length, total: slots.length };
  }
  const slots = (["W", "K"] as const).flatMap((backing) => BACKED_GRADIENT_THICKNESSES.map(
    (thickness) => backedGradientSlotKey(columnTarget(symbol, backing, reference), thickness),
  ));
  if (reference) slots.push("bare:W", "bare:K");
  return { count: slots.filter((slot) => selected.has(slot)).length, total: slots.length };
}

export default function LuminaBoxMaterialCapture({ capture, symbol, reference }: {
  capture: Capture; symbol: BackedGradientSymbol; reference: boolean;
}) {
  const { t, lang } = useI18n();
  const [manualOpen, setManualOpen] = useState(false);
  const records = new Map(capture.dataset?.captures.map((record) => [record.record_id, record]));
  const locked = capture.contextBlocked || !!capture.datasetBusy;
  const target = capture.draft.target;
  const workflow = (capture.dataset as LuminaBoxMaterialDataset | null)?.workflow;
  const backingRole = workflow?.kind === "backing_material" ? workflow.material_symbol : undefined;
  const columns = backingRole ? [backingRole === "W" ? "K" : "W"] as const : ["W", "K"] as const;
  const record = capture.inspectedRecord;
  const selectedLabel = target.sample_role === "bare_backing"
    ? t(target.backing === "W" ? "lumina_box_material_bare_white" : "lumina_box_material_bare_black")
    : `${reference ? `${t(`lumina_box_material_color_${target.material_symbol.toLowerCase()}`)} · ` : ""}${t(target.backing === "W" ? "lumina_box_material_white_backing" : "lumina_box_material_black_backing")} · ${capture.draft.manualThickness} mm`;

  const cell = (next: BackedGradientTarget, thickness: number) => {
    const slot = backedGradientSlotKey(next, thickness);
    const reading = records.get(capture.dataset?.selected_capture_ids[slot] ?? "");
    const label = next.sample_role === "bare_backing"
      ? t(next.backing === "W" ? "lumina_box_material_bare_white" : "lumina_box_material_bare_black")
      : `${t(next.backing === "W" ? "lumina_box_material_white_backing" : "lumina_box_material_black_backing")} ${thickness.toFixed(2)} mm`;
    const isSelected = capture.inspectedSlot === slot;

    return <button type="button" disabled={locked} aria-label={label} aria-pressed={isSelected}
      className={`group relative min-h-14 w-full rounded-lg px-3 py-2 text-left outline-none transition focus:ring-4 focus:ring-[var(--focus-ring)] ${isSelected
        ? "bg-blue-500/15 ring-1 ring-blue-500" : "bg-[var(--surface-well)] hover:bg-blue-500/10"}`}
      onClick={() => capture.selectSlot(next, thickness)} data-testid={`box-material-cell-${slot}`}>
      {next.sample_role === "bare_backing" ? <span className="mb-1 block text-sm font-medium">{label}</span> : null}
      {reading ? <>
        <span className="flex flex-wrap gap-x-3 font-mono text-xs tabular-nums">{reading.reflectance_percent_xyz.map((value, axis) =>
          <span key={axis}>{["X", "Y", "Z"][axis]} {value.toFixed(2)}</span>)}
        </span>
        <div className="absolute right-2 top-2 h-2 w-2 rounded-full bg-green-500" aria-label={t("lumina_box_cell_measured_badge")} title={t("lumina_box_cell_measured_badge")} />
      </> : <>
        <span className="text-sm text-slate-500 dark:text-slate-400">{t("lumina_box_material_unmeasured")}</span>
        {!locked && !isSelected && (
          <span className="absolute right-2 top-2 text-xs text-slate-400 opacity-0 transition-opacity group-hover:opacity-100 dark:text-slate-500">
            {t("lumina_box_cell_click_hint")}
          </span>
        )}
      </>}
    </button>;
  };

  return <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_18rem]" data-testid="box-material-capture">
    <div className="min-w-0 space-y-4">
      {reference || backingRole ? <div className={backingRole ? "" : "grid gap-3 sm:grid-cols-2"}>{(backingRole ? [backingRole] : ["W", "K"] as const).map((backing) => <div key={backing}>
        {cell({ material_symbol: backing, backing, sample_role: "bare_backing" }, 0)}
      </div>)}</div> : null}
      <table className="w-full table-fixed border-separate border-spacing-x-1 border-spacing-y-2 text-sm" data-testid="box-material-measurements">
        <thead><tr><th className="w-20 px-1 pb-1 text-left font-medium">{t("lumina_box_material_thickness")}</th>
          {columns.map((backing) => <th key={backing} className="px-3 pb-1 text-left font-medium">{reference
            ? t(backing === "W" ? "lumina_box_material_black_on_white" : "lumina_box_material_white_on_black")
            : t(backing === "W" ? "lumina_box_material_white_backing" : "lumina_box_material_black_backing")}</th>)}
        </tr></thead>
        <tbody>{BACKED_GRADIENT_THICKNESSES.map((thickness) => <tr key={thickness}><th className="px-1 text-left font-normal tabular-nums">{thickness.toFixed(2)}&nbsp;mm</th>
          {columns.map((backing) => <td key={backing}>{cell(columnTarget(symbol, backing, reference), thickness)}</td>)}
        </tr>)}</tbody>
      </table>
    </div>
    <div className={`${wellClass} space-y-4 p-4`}>
      <div><h3 className="text-sm font-semibold">{t("lumina_box_material_current_sample")}</h3>
        <p className="mt-2 text-base font-medium" data-testid="box-material-current-sample">{selectedLabel}</p>
      </div>
      <Button variant="secondary" size="sm" label={t(manualOpen ? "lumina_box_material_close_entry" : "lumina_box_material_manual_entry")}
        onClick={() => setManualOpen(!manualOpen)} />
      {manualOpen || capture.hasUnsavedManual ? <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); void capture.saveManual(); }}>
        <div className="grid grid-cols-3 gap-2">{["X", "Y", "Z"].map((axis, index) => <label key={axis} className="space-y-1 text-sm">{axis}
          <input className={boxMaterialInputClass} type="number" min={0} step="any" required value={capture.draft.manualXYZ[index]}
            aria-label={axis} disabled={capture.savingCount > 0} onChange={(event) => {
              const values = [...capture.draft.manualXYZ] as [string, string, string]; values[index] = event.target.value; capture.updateDraft({ manualXYZ: values });
            }} />
        </label>)}</div>
        <div className="flex gap-2"><Button type="submit" size="sm" label={t("lumina_box_material_save_reading")} disabled={!capture.manualValid || capture.savingCount > 0} />
          {capture.hasUnsavedManual ? <Button size="sm" variant="secondary" label={t("lumina_box_material_cancel_entry")} onClick={capture.discardManual} /> : null}</div>
      </form> : null}
      {record ? <div className={`${cardDividerClass} space-y-3 pt-3`}>
        <p className="text-sm">{t("lumina_box_material_saved_reading")}</p>
        <p className="font-mono text-sm tabular-nums">{record.reflectance_percent_xyz.map((value, index) => `${["X", "Y", "Z"][index]} ${value.toFixed(2)}`).join(" · ")}</p>
        <p className="text-xs text-slate-500 dark:text-slate-400">{new Date(record.received_at).toLocaleString(lang === "zh" ? "zh-CN" : "en-US")}</p>
        {capture.slotRecords.length > 1 ? <details><summary className="cursor-pointer text-sm">{t("lumina_box_material_reading_history")}</summary>
          <div className="mt-3 space-y-2">{capture.slotRecords.map((item) => <button key={item.record_id} type="button" disabled={!!capture.recordBusy}
            className="w-full rounded-lg px-2 py-2 text-left text-xs hover:bg-blue-500/10" onClick={() => void capture.chooseCapture(item)}>
            {new Date(item.received_at).toLocaleString(lang === "zh" ? "zh-CN" : "en-US")}
            {item.record_id === capture.dataset?.selected_capture_ids[capture.inspectedSlot] ? ` · ${t("lumina_box_material_selected")}` : ""}
            <span className="mt-1 block font-mono">{item.reflectance_percent_xyz.map((value) => value.toFixed(2)).join(" / ")}</span>
          </button>)}</div>
        </details> : null}
      </div> : null}
    </div>
  </div>;
}
