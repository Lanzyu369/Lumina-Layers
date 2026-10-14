import type { LuminaBoxStackSampleRecord } from "../api/luminaBoxStackSamples";
import { getLuminaBoxSerialApi } from "../api/luminaBoxSerial";
import { useLuminaBoxStackSamples } from "../hooks/useLuminaBoxStackSamples";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { useI18n } from "../i18n/context";
import LuminaBoxConnectionDiagnostics from "./LuminaBoxConnectionDiagnostics";
import Button from "./ui/Button";
import HelpDot from "./ui/HelpDot";
import {
  cardClass, cardDividerClass, PanelIntro, resolvePanelSurfaceClass, StatusBanner, wellClass,
} from "./ui/panelPrimitives";

const inputClass = "min-h-11 w-full rounded-[10px] border border-[var(--surface-card-outline)] bg-[var(--surface-panel-strong)] px-3 py-2 text-sm text-slate-900 outline-none transition focus:ring-4 focus:ring-[var(--focus-ring)] disabled:cursor-not-allowed disabled:opacity-50 dark:text-slate-100";
const labelClass = "flex flex-col gap-2 text-sm font-medium text-slate-700 dark:text-slate-200";
const mutedClass = "text-sm text-slate-500 dark:text-slate-400";
const dateText = (value: string, language: "zh" | "en") =>
  new Date(value).toLocaleString(language === "zh" ? "zh-CN" : "en-US");

function MeasuredXYZ({ record, scope }: { record: LuminaBoxStackSampleRecord; scope: string }) {
  const { t } = useI18n();
  const transmission = record.device_measurement.mode === "reflect" ? null : record.device_measurement.transmittance_xyz;
  return (
    <div className={`${wellClass} space-y-4 px-4 py-3`}>
      <div>
        <p className={`${mutedClass} mb-2`}>{t("lumina_box_stack_reflection_xyz")}</p>
        <div className="grid grid-cols-3 gap-3 font-mono text-base tabular-nums" data-testid={`${scope}-measured-xyz`}>
          {record.reflectance_percent_xyz.map((value, index) => <span key={index}>{["X", "Y", "Z"][index]} {value.toFixed(4)}</span>)}
        </div>
      </div>
      <div>
        <p className={`${mutedClass} mb-2`}>{t("lumina_box_stack_transmission_xyz")}</p>
        {transmission ? (
          <div className="grid grid-cols-3 gap-3 font-mono text-base tabular-nums" data-testid={`${scope}-transmitted-xyz`}>
            {transmission.map((value, index) => <span key={index}>{["X", "Y", "Z"][index]} {value.toFixed(6)}</span>)}
          </div>
        ) : <p className={mutedClass}>{t("lumina_box_stack_transmission_not_measured")}</p>}
      </div>
    </div>
  );
}

function MeasuredReadout({ record, receivedAt }: { record: LuminaBoxStackSampleRecord; receivedAt?: string }) {
  const { t, lang } = useI18n();
  const capturedAt = record.received_at ?? receivedAt;
  return (
    <div className="flex flex-col gap-4" data-testid="lumina-box-stack-readout">
      <div className="flex items-center gap-5">
        <div className="h-24 w-24 shrink-0 rounded-[10px]" data-testid="lumina-box-stack-color-swatch"
          style={{ backgroundColor: `rgb(${record.display_rgb.join(", ")})` }} />
        <div className="min-w-0">
          <p className={mutedClass}>{t("lumina_box_stack_measured_color")}</p>
          <p className="mt-1 font-mono text-2xl font-semibold tracking-tight" data-testid="lumina-box-stack-measured-hex">{record.display_hex}</p>
          <p className="mt-1 break-all font-mono text-sm" data-testid="lumina-box-stack-saved-recipe">{record.recipe_top_to_bottom}</p>
          {record.sample_name ? <p className="mt-1 break-words text-sm">{record.sample_name}</p> : null}
        </div>
      </div>
      <MeasuredXYZ record={record} scope="lumina-box-stack" />
      <p className="text-xs text-slate-500 dark:text-slate-400" data-testid="lumina-box-stack-capture-time">
        {t(capturedAt ? "lumina_box_stack_received_at" : "lumina_box_stack_saved_at")}{" · "}
        {dateText(capturedAt ?? record.created_at, lang)}
      </p>
    </div>
  );
}

function SavedRecordDetails({ record }: { record: LuminaBoxStackSampleRecord }) {
  const { t, lang } = useI18n();
  return (
    <div className="space-y-4" data-testid="lumina-box-stack-selected-detail">
      <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2 xl:grid-cols-5">
        <div><dt className={mutedClass}>{t("lumina_box_stack_recipe_label")}</dt><dd className="mt-1 break-all font-mono font-semibold">{record.recipe_top_to_bottom}</dd></div>
        <div><dt className={mutedClass}>{t("lumina_box_stack_measured_color")}</dt><dd className="mt-1 font-mono">{record.display_hex}</dd></div>
        <div><dt className={mutedClass}>{t("lumina_box_stack_batch")}</dt><dd className="mt-1 break-words">{record.material_batch || t("lumina_box_stack_not_provided")}</dd></div>
        <div><dt className={mutedClass}>{t("lumina_box_stack_received_at")}</dt><dd className="mt-1">{dateText(record.received_at ?? record.created_at, lang)}</dd></div>
        <div><dt className={mutedClass}>{t("lumina_box_stack_saved_at")}</dt><dd className="mt-1">{dateText(record.created_at, lang)}</dd></div>
      </dl>
      <p className="text-sm" data-testid="lumina-box-stack-detail-geometry">
        {t("lumina_box_stack_geometry_summary").replace("{layers}", String(record.geometry.upper_layer_count))
          .replace("{upper}", record.geometry.upper_mm.toFixed(2)).replace("{base}", record.geometry.white_base_mm.toFixed(2))}
      </p>
      <MeasuredXYZ record={record} scope="lumina-box-stack-detail" />
      {record.notes ? <p className="whitespace-pre-wrap break-words text-sm">{record.notes}</p> : null}
      <details>
        <summary className="cursor-pointer text-sm font-medium text-blue-700 dark:text-blue-300">{t("lumina_box_stack_raw_details")}</summary>
        <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-all font-mono text-xs" data-testid="lumina-box-stack-raw-record">{JSON.stringify(record, null, 2)}</pre>
      </details>
    </div>
  );
}

export default function LuminaBoxStackSamplesPanel() {
  const { t, lang } = useI18n();
  const workspace = useWorkspaceMode();
  const capture = useLuminaBoxStackSamples();
  const serialSupported = getLuminaBoxSerialApi() !== null;
  const locked = capture.savingCount > 0;
  const upperLayers = capture.draft.recipe.length;
  const serialStatusKey = !serialSupported ? "lumina_box_serial_unsupported"
    : capture.serial.status === "disconnected" ? "lumina_box_stack_serial_disconnected"
      : capture.serial.status === "connected" ? capture.serial.mode === "legacy"
        ? "lumina_box_stack_serial_legacy_connected" : "lumina_box_stack_serial_connected"
        : `lumina_box_serial_${capture.serial.status}`;
  const serialIssue = capture.serial.issue === "invalid_recipe" || capture.serial.issue === "unsupported_mode"
    ? null : capture.serial.issue === "storage_unavailable"
      ? capture.captureError || !capture.storageAvailable ? null : t("lumina_box_stack_storage_failed")
      : capture.serial.issue ? t(`lumina_box_serial_${capture.serial.issue}`) : null;

  return (
    <section className={resolvePanelSurfaceClass(workspace.mode)} data-testid="lumina-box-stack-samples-panel">
      <div className="mx-auto flex w-full max-w-[96rem] flex-col gap-5 pb-6 text-slate-900 dark:text-slate-100">
        <PanelIntro title={t("lumina_box_stack_title")} description={t("lumina_box_stack_description")} />

        <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(21rem,0.8fr)]">
          <section className={`${cardClass} flex min-w-0 flex-col gap-5 p-5`}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-lg font-semibold">{t("lumina_box_stack_current_sample")}</h3>
              <span className={`${wellClass} px-3 py-1.5 text-xs font-medium`}>{t("lumina_box_stack_fixed_thickness")}</span>
            </div>
            <label className={labelClass}>
              <span className="flex items-center gap-1.5">{t("lumina_box_stack_recipe_label")}
                <HelpDot title={t("lumina_box_stack_recipe_label")} description={t("lumina_box_stack_recipe_hint")} />
              </span>
              <input className={`${inputClass} font-mono text-lg tracking-[0.15em]`} value={capture.draft.recipe}
                placeholder={t("lumina_box_stack_recipe_placeholder")} spellCheck={false} autoComplete="off" maxLength={35}
                disabled={locked} aria-invalid={capture.draft.recipe.length > 0 && !capture.validRecipe}
                onChange={(event) => capture.updateDraft("recipe", event.target.value)} data-testid="lumina-box-stack-recipe" />
            </label>
            <div className="flex flex-wrap gap-x-4 gap-y-2 text-xs text-slate-600 dark:text-slate-300" data-testid="lumina-box-stack-letter-legend">
              {["W", "R", "Y", "B", "C", "M", "G", "K"].map((letter) => <span key={letter}>{t(`lumina_box_stack_letter_${letter.toLowerCase()}`)}</span>)}
            </div>
            {capture.validRecipe ? (
              <div className={`${wellClass} flex items-center gap-2 px-4 py-3 text-sm`} data-testid="lumina-box-stack-geometry">
                <span>{t("lumina_box_stack_geometry_summary").replace("{layers}", String(upperLayers))
                  .replace("{upper}", (upperLayers * .08).toFixed(2)).replace("{base}", (3 - upperLayers * .08).toFixed(2))}</span>
                <HelpDot title={t("lumina_box_stack_fixed_thickness")} description={t("lumina_box_stack_geometry_hint")} />
              </div>
            ) : <StatusBanner tone="info" data-testid="lumina-box-stack-recipe-validation">{t("lumina_box_stack_invalid_recipe")}</StatusBanner>}

            <details className={`${cardDividerClass} pt-4`}>
              <summary className="cursor-pointer text-sm font-semibold">{t("lumina_box_stack_metadata")}</summary>
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <label className={labelClass}>{t("lumina_box_stack_name")}
                  <input className={inputClass} value={capture.draft.sampleName} maxLength={200} disabled={locked}
                    onChange={(event) => capture.updateDraft("sampleName", event.target.value)} data-testid="lumina-box-stack-name" />
                </label>
                <label className={labelClass}>{t("lumina_box_stack_batch")}
                  <input className={inputClass} value={capture.draft.materialBatch} maxLength={500} disabled={locked}
                    onChange={(event) => capture.updateDraft("materialBatch", event.target.value)} data-testid="lumina-box-stack-batch" />
                </label>
                <label className={`${labelClass} sm:col-span-2`}>{t("lumina_box_stack_notes")}
                  <textarea className={inputClass} rows={2} value={capture.draft.notes} maxLength={4000} disabled={locked}
                    onChange={(event) => capture.updateDraft("notes", event.target.value)} data-testid="lumina-box-stack-notes" />
                </label>
                <label className={labelClass}>{t("lumina_box_stack_reference")}
                  <select className={inputClass} value={capture.draft.referenceDirectoryName} disabled={locked}
                    onChange={(event) => capture.updateDraft("referenceDirectoryName", event.target.value)} data-testid="lumina-box-stack-reference">
                    <option value="">{t("lumina_box_stack_reference_auto")}</option>
                    {capture.referenceMaterials.map((material) => <option key={material.directory_name} value={material.directory_name}>{material.material_name}</option>)}
                    {capture.draft.referenceDirectoryName && !capture.referenceMaterials.some((item) => item.directory_name === capture.draft.referenceDirectoryName)
                      ? <option value={capture.draft.referenceDirectoryName}>{capture.draft.referenceDirectoryName}</option> : null}
                  </select>
                </label>
                <div className={labelClass}>
                  <span>{t("lumina_box_stack_backing_context")}</span>
                  <span className="py-2 font-mono text-sm">{capture.backingText.join(" / ")}</span>
                </div>
              </div>
            </details>

            <div className={`${cardDividerClass} flex flex-col gap-3 pt-4`}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="flex items-center gap-1.5 font-semibold">{t("lumina_box_serial_title")}
                    <HelpDot title={t("lumina_box_serial_title")} description={t("lumina_box_stack_serial_hint")} />
                  </div>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400" role="status" aria-live="polite" data-testid="lumina-box-stack-serial-status">
                    {t(serialStatusKey)}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {capture.serial.status === "disconnected" ? <Button label={t("lumina_box_serial_connect")}
                    onClick={capture.connect} disabled={!serialSupported || !capture.validRecipe || locked} data-testid="lumina-box-stack-connect" />
                    : <Button label={t("lumina_box_serial_disconnect")} variant="secondary"
                      onClick={() => void capture.serial.disconnect()} disabled={capture.serial.status === "disconnecting"} data-testid="lumina-box-stack-disconnect" />}
                  <Button label={t("lumina_box_serial_replay")} variant="secondary"
                    onClick={capture.serial.replay} disabled={capture.serial.status !== "connected" || capture.serial.mode !== "reliable" || capture.serial.pendingCount === 0}
                    data-testid="lumina-box-stack-replay" />
                </div>
              </div>
              {serialIssue ? <StatusBanner tone="warning" data-testid="lumina-box-stack-serial-issue">{serialIssue}</StatusBanner> : null}
              <LuminaBoxConnectionDiagnostics snapshot={capture.serial} />
              {capture.captureIssue ? <StatusBanner tone="warning" data-testid="lumina-box-stack-capture-issue">{t(`lumina_box_stack_${capture.captureIssue}`)}</StatusBanner> : null}
              {!capture.storageAvailable ? <StatusBanner tone="warning" data-testid="lumina-box-stack-storage-error">{t("lumina_box_stack_storage_failed")}</StatusBanner> : null}
              {capture.captureError ? <StatusBanner tone="error" data-testid="lumina-box-stack-save-error">{capture.captureError}</StatusBanner> : null}
              {capture.pendingCaptures.length > 0 ? (
                <StatusBanner tone={locked ? "info" : "warning"} title={t(locked ? "lumina_box_stack_saving" : "lumina_box_stack_pending_title")}
                  data-testid="lumina-box-stack-pending">
                  <p>{t("lumina_box_stack_pending_description")}</p>
                  <ul className="mt-2 space-y-2">
                    {capture.pendingCaptures.map((entry) => entry.request ? <li key={entry.key} className="flex flex-wrap items-center justify-between gap-2">
                      <span className="break-all font-mono text-sm">{entry.request.recipe_top_to_bottom}{" · "}{dateText(entry.receivedAt, lang)}</span>
                      <Button label={t("lumina_box_stack_retry")} variant="secondary" size="sm" disabled={locked}
                        onClick={() => void capture.retryCapture(entry.key)} data-testid={`lumina-box-stack-retry-${entry.request.measurement.measurement_id}`} />
                    </li> : null)}
                  </ul>
                </StatusBanner>
              ) : null}
            </div>
          </section>

          <section className={`${cardClass} flex min-w-0 flex-col gap-5 p-5`}>
            <h3 className="text-lg font-semibold">{t("lumina_box_stack_latest")}</h3>
            {capture.lastSaved ? <MeasuredReadout record={capture.lastSaved} receivedAt={capture.lastSavedReceivedAt} />
              : <div className={`${wellClass} px-5 py-10 text-center text-sm text-slate-500 dark:text-slate-400`} data-testid="lumina-box-stack-no-reading">{t("lumina_box_stack_no_reading")}</div>}
          </section>
        </div>

        <section className={`${cardClass} flex min-w-0 flex-col gap-4 p-5`}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div><h3 className="text-lg font-semibold">{t("lumina_box_stack_records")}</h3>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{t("lumina_box_stack_record_count").replace("{count}", String(capture.records.length))}</p></div>
            <div className="flex flex-wrap gap-2">
              <Button label={t("lumina_box_stack_refresh")} variant="secondary" size="sm" loading={capture.recordsLoading}
                onClick={() => void capture.refreshRecords()} data-testid="lumina-box-stack-refresh" />
              <Button label={t("lumina_box_stack_export")} variant="secondary" size="sm" loading={capture.exporting}
                disabled={capture.records.length === 0} onClick={() => void capture.exportRecords()} data-testid="lumina-box-stack-export" />
            </div>
          </div>
          {capture.recordsError ? <StatusBanner tone="error" data-testid="lumina-box-stack-record-error">{capture.recordsError}</StatusBanner> : null}
          {capture.records.length === 0 ? <p className={`${mutedClass} py-5`}>{t(capture.recordsLoading ? "lumina_box_stack_loading" : "lumina_box_stack_records_empty")}</p>
            : <div className="max-h-[28rem] overflow-auto">
              <table className="w-full min-w-[42rem] text-left text-sm" data-testid="lumina-box-stack-records-table">
                <thead className="text-xs text-slate-500 dark:text-slate-400"><tr>
                  {["name", "recipe_label", "measured_color", "saved_at", "actions"].map((key) => <th key={key} className="px-3 py-2 font-medium">{t(`lumina_box_stack_${key}`)}</th>)}
                </tr></thead>
                <tbody>{capture.records.map((record) => <tr key={record.record_id} data-testid={`lumina-box-stack-record-${record.record_id}`}
                  className={`${cardDividerClass} ${capture.selectedId === record.record_id ? "bg-[var(--surface-well)]" : ""}`}>
                  <td className="max-w-52 break-words px-3 py-3">{record.sample_name || t("lumina_box_stack_unnamed")}</td>
                  <td className="max-w-64 break-all px-3 py-3 font-mono">{record.recipe_top_to_bottom}</td>
                  <td className="px-3 py-3"><div className="flex items-center gap-2"><span className="h-6 w-6 shrink-0 rounded-md" style={{ backgroundColor: `rgb(${record.display_rgb.join(", ")})` }} /><span className="font-mono">{record.display_hex}</span></div></td>
                  <td className="whitespace-nowrap px-3 py-3 text-xs">{dateText(record.created_at, lang)}</td>
                  <td className="px-3 py-3"><Button label={t("lumina_box_stack_view")} variant="secondary" size="sm"
                    disabled={capture.recordAction === "delete"} onClick={() => void capture.viewRecord(record.record_id)} data-testid={`lumina-box-stack-view-${record.record_id}`} /></td>
                </tr>)}</tbody>
              </table>
            </div>}
          {capture.recordAction === "load" ? <p className={mutedClass} role="status">{t("lumina_box_stack_loading")}</p> : null}
          {capture.selectedRecord ? <div className={`${wellClass} space-y-4 p-4`}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div><h4 className="font-semibold">{t("lumina_box_stack_selected_record")}{" · "}{capture.selectedRecord.sample_name || t("lumina_box_stack_unnamed")}</h4>
                <p className="mt-1 font-mono text-xs text-slate-500 dark:text-slate-400">{capture.selectedRecord.record_id}</p></div>
              <Button label={t("lumina_box_stack_delete_selected")} variant="secondary" size="sm" loading={capture.recordAction === "delete"}
                onClick={() => void capture.deleteSelected()} data-testid="lumina-box-stack-delete-selected" />
            </div>
            <SavedRecordDetails record={capture.selectedRecord} />
          </div> : null}
        </section>
      </div>
    </section>
  );
}
