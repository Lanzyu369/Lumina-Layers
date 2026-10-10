import { useEffect, useRef, useState, type FormEvent } from "react";
import type { BackedGradientSymbol } from "../api/luminaBoxBackedGradient";
import {
  createLuminaBoxBackingMaterialDataset, createLuminaBoxMaterialDataset,
  listLuminaBoxBackingReferences, listLuminaBoxBackingMaterials,
  type LuminaBoxBackingReference, type LuminaBoxMaterialDataset, type LuminaBoxBackingMaterial, type LuminaBoxBackingMaterialRequest,
} from "../api/luminaBoxMaterials";
import { getLuminaBoxSerialApi } from "../api/luminaBoxSerial";
import { useLuminaBoxBackedGradient } from "../hooks/useLuminaBoxBackedGradient";
import { useLuminaBoxMaterialFit } from "../hooks/useLuminaBoxMaterialFit";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { useI18n } from "../i18n/context";
import { useLuminaBoxMaterialNavigation } from "../stores/luminaBoxMaterialNavigation";
import { savedBackedGradientMaterialSymbols } from "../utils/luminaBoxBackedGradientCapture";
import LuminaBoxMaterialCapture, { boxMaterialInputClass, luminaBoxMaterialProgress } from "./LuminaBoxMaterialCapture";
import LuminaBoxBackingSetup from "./LuminaBoxBackingSetup";
import LuminaBoxConnectionDiagnostics from "./LuminaBoxConnectionDiagnostics";
import Button from "./ui/Button";
import Dropdown from "./ui/Dropdown";
import { cardClass, cardDividerClass, resolvePanelSurfaceClass, StatusBanner, wellClass } from "./ui/panelPrimitives";

const initialForm = { name: "", brand: "", material_type: "" };

export default function LuminaBoxMaterialPanel() {
  const { t, lang } = useI18n();
  const workspace = useWorkspaceMode();
  const navigation = useLuminaBoxMaterialNavigation();
  const initialRequest = useRef(navigation.captureRequest);
  const capture = useLuminaBoxBackedGradient({ researchFits: false,
    initialDatasetId: initialRequest.current?.datasetId,
    initialTarget: initialRequest.current ? { material_symbol: initialRequest.current.materialSymbol, backing: "W", sample_role: "coated" } : undefined,
  });
  const dataset = capture.dataset as LuminaBoxMaterialDataset | null;
  const [references, setReferences] = useState<LuminaBoxBackingReference[]>([]);
  const [backingMaterials, setBackingMaterials] = useState<LuminaBoxBackingMaterial[]>([]);
  const [backingSelection, setBackingSelection] = useState({ W: "", K: "" });
  const [backingSetupSelection, setBackingSetupSelection] = useState<LuminaBoxBackingMaterial | null>(null);
  const [form, setForm] = useState(initialForm);
  const [creating, setCreating] = useState<"material" | "backing" | null>(initialRequest.current ? null : "material");
  const [confirmDiscardPending, setConfirmDiscardPending] = useState(false);
  const [referenceError, setReferenceError] = useState(false);
  const [referenceLoading, setReferenceLoading] = useState(true);
  const [referenceAttempt, setReferenceAttempt] = useState(0);
  const legacyBacking = dataset?.workflow?.kind === "backing_reference";
  const backingWorkflow = dataset?.workflow?.kind === "backing_material" ? dataset.workflow : undefined;
  const backing = legacyBacking || !!backingWorkflow;
  const materialWorkflow = dataset?.workflow?.kind === "material" ? dataset.workflow : undefined;
  const savedSymbols = dataset ? savedBackedGradientMaterialSymbols(dataset) : [];
  const symbol = materialWorkflow?.material_symbol ?? backingWorkflow?.material_symbol ?? (legacyBacking ? "K"
    : savedSymbols.includes(capture.draft.target.material_symbol) ? capture.draft.target.material_symbol
      : savedSymbols[0] ?? capture.draft.target.material_symbol);
  const listedReference = materialWorkflow
    ? references.find((item) => item.reference_id === materialWorkflow.reference_id
      || !!materialWorkflow.backing_id && item.backing_id === materialWorkflow.backing_id)
    : references.find((item) => item.source_dataset_id === dataset?.dataset_id);
  const boundReference = materialWorkflow?.backing_reference ? { ...listedReference, ...materialWorkflow.backing_reference,
    white_name: materialWorkflow.backing_reference.white_name || listedReference?.white_name,
    black_name: materialWorkflow.backing_reference.black_name || listedReference?.black_name } : listedReference;
  const boundReferenceId = materialWorkflow ? materialWorkflow.reference_id : backing ? "" : boundReference?.reference_id ?? "";
  const backingId = dataset?.workflow?.kind === "material" ? dataset.workflow.backing_id : boundReference?.backing_id;
  const fit = useLuminaBoxMaterialFit(dataset?.dataset_id ?? "", symbol, boundReferenceId, backingWorkflow ? "backing_material" : backing, backingId);
  const progress = luminaBoxMaterialProgress(dataset, symbol, legacyBacking);
  const complete = progress.count === progress.total;
  const locked = capture.contextBlocked || !!capture.datasetBusy;
  const selectionLocked = locked || capture.hasUnsavedManual;
  const formMode = creating ?? (!dataset && !capture.datasetBusy ? "material" : null);
  const materialLabel = (item: LuminaBoxMaterialDataset, selected: BackedGradientSymbol) => {
    if (item.workflow) return item.name;
    const name = item.materials[selected]?.trim();
    return name && name !== selected ? name
      : [item.material_type, t(`lumina_box_material_color_${selected.toLowerCase()}`)].filter(Boolean).join(lang === "zh" ? "" : " ");
  };
  const archiveRequest = initialRequest.current?.archive ? initialRequest.current : navigation.lastCaptureArchive;
  const archiveIdentity = archiveRequest?.datasetId === dataset?.dataset_id && archiveRequest?.materialSymbol === symbol
    ? archiveRequest.archive : undefined;
  const materialName = archiveIdentity?.name ?? (dataset ? materialLabel(dataset, symbol) : "");

  useEffect(() => { useLuminaBoxMaterialNavigation.setState({ captureRequest: null }); }, []);

  useEffect(() => {
    let active = true;
    setReferenceLoading(true);
    setReferenceError(false);
    void Promise.all([listLuminaBoxBackingReferences(), listLuminaBoxBackingMaterials()]).then(([items, materials]) => {
      if (!active) return;
      setReferences(items);
      setBackingMaterials(materials);
      setBackingSelection((selected) => ({ W: materials.some((item) => item.material_id === selected.W && item.status === "ready") ? selected.W : "",
        K: materials.some((item) => item.material_id === selected.K && item.status === "ready") ? selected.K : "" }));
    }).catch(() => { if (active) setReferenceError(true); })
      .finally(() => { if (active) setReferenceLoading(false); });
    return () => { active = false; };
  }, [referenceAttempt]);

  useEffect(() => {
    if (fit.run?.status === "complete") setReferenceAttempt((value) => value + 1);
  }, [fit.run?.fit_id, fit.run?.status]);

  const backingLabel = (item: LuminaBoxBackingReference, color: "white" | "black") => {
    const name = item[`${color}_name`];
    const symbol = color === "white" ? "W" : "K";
    return name && name !== symbol ? name : `${item.name} · ${t(`lumina_box_material_color_${symbol.toLowerCase()}`)}`;
  };
  const beginMaterial = (reuseIdentity = false) => {
    setForm(reuseIdentity ? { ...initialForm, name: materialName, brand: archiveIdentity?.brand ?? dataset?.brand ?? "",
      material_type: archiveIdentity?.material_type ?? dataset?.material_type ?? "" } : initialForm);
    setBackingSelection({ W: "", K: "" });
    setCreating("material");
  };
  const beginBacking = (material: LuminaBoxBackingMaterial | null = null) => {
    setBackingSetupSelection(material);
    setCreating("backing");
  };

  const openBacking = async (material: LuminaBoxBackingMaterial) => {
    const id = material.active_dataset_id ?? (material.source === "legacy_reference" ? undefined : material.dataset_id);
    if (!id) {
      if (material.opposite_material_id) await createBacking({ name: material.name, brand: material.brand, material_type: material.material_type,
        role: material.role, material_id: material.material_id, opposite_material_id: material.opposite_material_id });
      else beginBacking(material);
      return;
    }
    const loaded = await capture.loadDataset(id, { material_symbol: material.role, backing: material.role === "W" ? "K" : "W", sample_role: "coated" });
    if (loaded) setCreating(null);
  };

  const createBacking = async (payload: LuminaBoxBackingMaterialRequest) => {
    const created = await capture.createDataset(payload, () => createLuminaBoxBackingMaterialDataset(payload));
    if (created) { setCreating(null); setReferenceAttempt((value) => value + 1); }
  };

  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (selectionLocked || !backingSelection.W || !backingSelection.K) return;
    const payload = { name: form.name.trim(), brand: form.brand.trim(), material_type: form.material_type.trim() };
    const created = await capture.createDataset(payload, () => createLuminaBoxMaterialDataset({ ...payload,
      white_backing_id: backingSelection.W, black_backing_id: backingSelection.K }));
    if (created) { setCreating(null); setForm(initialForm); }
  };
  const selectedConnectionKey = capture.serial.status === "connected" ? "lumina_box_material_connected"
    : capture.serial.status === "connecting" ? "lumina_box_material_connecting" : "lumina_box_material_disconnected";
  const selectedRecordIds = Object.entries(dataset?.selected_capture_ids ?? {})
    .filter(([slot]) => backingWorkflow ? slot === `bare:${symbol}` || slot.startsWith(`${symbol}:`)
      : legacyBacking ? slot.startsWith("bare:") || slot.startsWith("W:") || slot.startsWith("K:") : slot.startsWith(`${symbol}:`))
    .map(([, id]) => id).sort();
  const fittedRecordIds = fit.result?.selected_record_ids?.slice().sort();
  const stale = fit.run?.status === "complete" && (fittedRecordIds
    ? selectedRecordIds.length !== fittedRecordIds.length || selectedRecordIds.some((id, index) => id !== fittedRecordIds[index])
    : fit.run.dataset_revision !== dataset?.revision);
  const previewRgb = fit.result?.estimated_rgb;
  const hasFreshResult = !!fit.result && fit.result.status !== "not_converged" && !stale;
  const oppositeMaterial = backingWorkflow ? backingMaterials.find((item) => item.material_id === backingWorkflow.opposite_material_id) : undefined;
  const activeBackingMaterial = backingWorkflow ? backingMaterials.find((item) => item.material_id === backingWorkflow.backing_material_id) : undefined;
  const backingReadyForThisCapture = !stale && activeBackingMaterial?.status === "ready" && activeBackingMaterial.dataset_id === dataset?.dataset_id;
  const awaitingOpposite = fit.result?.status === "awaiting_opposite" && !backingReadyForThisCapture;

  return <section className={resolvePanelSurfaceClass(workspace.mode)} data-testid="lumina-box-material-panel">
    <div className="mx-auto flex max-w-6xl flex-col gap-5 pb-6 text-slate-900 dark:text-slate-100">
      <section className={`${cardClass} space-y-5 p-5`}>
        <div className="flex flex-wrap items-center justify-between gap-3" data-testid="box-material-toolbar">
          <div className="flex flex-wrap items-center gap-3">
            <Button label={t("lumina_box_material_new")} variant={formMode === "material" ? "primary" : "secondary"} disabled={selectionLocked} onClick={() => beginMaterial()} />
            <Button label={t("lumina_box_backing_collect")} variant={formMode === "backing" || !formMode && backing ? "primary" : "secondary"}
              disabled={selectionLocked} onClick={() => beginBacking()} />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm text-slate-500 dark:text-slate-400" role="status">{t(selectedConnectionKey)}</span>
            {capture.serial.status === "disconnected" ? <Button label={t("lumina_box_serial_connect")} size="sm" disabled={!dataset || !!formMode || !getLuminaBoxSerialApi() || locked}
              onClick={capture.connect} /> : <Button label={t("lumina_box_serial_disconnect")} size="sm" variant="secondary"
              disabled={capture.serial.status === "disconnecting"} onClick={() => void capture.serial.disconnect()} />}
          </div>
        </div>
        {formMode === "backing" ? <LuminaBoxBackingSetup key={backingSetupSelection?.material_id ?? "new"} materials={backingMaterials}
          initialMaterial={backingSetupSelection} locked={selectionLocked || referenceLoading}
          busy={capture.datasetBusy === "create"} onStart={createBacking} onOpen={(item) => void openBacking(item)} /> : null}
        {formMode === "material" ? <form className={`${cardDividerClass} space-y-4 pt-4`} onSubmit={(event) => void create(event)} data-testid="box-material-create-form">
          <div className="grid gap-4 sm:grid-cols-2">
            {(["name", "brand", "material_type"] as const).map((field) => <label key={field} className="space-y-1.5 text-sm font-medium">{t(`lumina_box_material_${field}`)}
              <input className={boxMaterialInputClass} required={field === "name"} maxLength={200} value={form[field]} disabled={locked} onChange={(event) => setForm({ ...form, [field]: event.target.value })} />
            </label>)}
          </div>
          <div className={`${wellClass} space-y-3 p-4`}>
            <h4 className="text-sm font-semibold">{t("lumina_box_material_backing_pair")}</h4>
            <div className="grid gap-4 sm:grid-cols-2">
              {(["W", "K"] as const).map((role) => <Dropdown key={role} label={t(role === "W" ? "lumina_box_backing_white" : "lumina_box_backing_black")}
                value={backingSelection[role]} disabled={locked || referenceLoading} placeholder={t("lumina_box_backing_select")}
                options={backingMaterials.filter((item) => item.role === role && item.status === "ready").map((item) => ({ value: item.material_id,
                  label: [item.name, item.brand, item.material_type].filter(Boolean).join(" · ") }))}
                onChange={(id) => setBackingSelection((selected) => ({ ...selected, [role]: id }))} />)}
            </div>
            {!referenceLoading && (["W", "K"] as const).some((role) => !backingMaterials.some((item) => item.role === role && item.status === "ready"))
              ? <p className="text-sm text-slate-500 dark:text-slate-400">{t("lumina_box_backing_missing")}</p> : null}
          </div>
          <div className="flex gap-2"><Button type="submit" label={t("lumina_box_material_start_capture")} loading={capture.datasetBusy === "create"}
            disabled={selectionLocked || !form.name.trim() || !backingSelection.W || !backingSelection.K} />
            {dataset ? <Button variant="secondary" label={t("lumina_box_material_cancel")} onClick={() => setCreating(null)} /> : null}</div>
        </form> : null}
        {capture.error && !capture.failedPending.length ? <StatusBanner tone="error">{capture.error}</StatusBanner> : null}
        {capture.serial.issue && ["connection_failed", "connection_lost", "operation_timeout", "wrong_device", "device_not_functioning"].includes(capture.serial.issue)
          ? <><StatusBanner tone="error">{t(`lumina_box_serial_${capture.serial.issue}`)}</StatusBanner>
            <LuminaBoxConnectionDiagnostics snapshot={capture.serial} /></> : null}
        {referenceError ? <StatusBanner tone="error" action={<Button size="sm" variant="secondary" label={t("lumina_box_material_retry")} onClick={() => setReferenceAttempt((value) => value + 1)} />}>
          {t("lumina_box_material_load_failed")}</StatusBanner> : null}
        {capture.captureNotice ? <StatusBanner tone="warning">{t(capture.captureNotice)}</StatusBanner> : null}
        {!capture.storageAvailable ? <StatusBanner tone="error">{t("lumina_box_material_storage_failed")}</StatusBanner> : null}
        {capture.failedPending.length ? <StatusBanner tone="error" action={<Button size="sm" label={t("lumina_box_material_retry")}
          onClick={() => { for (const item of capture.failedPending) void capture.retry(item.key); }} />}>{t("lumina_box_material_pending_save")}</StatusBanner> : null}
        {capture.pending.length > 0 || capture.serial.pendingCount > 0 ? <StatusBanner tone="warning" title={t("lumina_box_bg_pending_title")}>
          <p>{t("lumina_box_bg_pending_description")}</p>
          <div className="mt-3 space-y-2">{confirmDiscardPending ? <>
            <p>{t("lumina_box_bg_discard_confirm")}</p>
            <div className="flex flex-wrap gap-2"><Button size="sm" variant="secondary" label={t("lumina_box_bg_discard_confirm_button")}
              disabled={capture.savingCount > 0} onClick={() => { capture.discardPending(); setConfirmDiscardPending(false); }} />
              <Button size="sm" variant="secondary" label={t("lumina_box_bg_cancel")} onClick={() => setConfirmDiscardPending(false)} /></div>
          </> : <Button size="sm" variant="secondary" label={t("lumina_box_bg_discard")} disabled={capture.savingCount > 0}
            onClick={() => setConfirmDiscardPending(true)} />}</div>
        </StatusBanner> : null}
        {dataset && !formMode ? <>
          <div className={`${cardDividerClass} flex flex-wrap items-end justify-between gap-3 pt-4`}>
            <h3 className="text-base font-semibold">{backing ? dataset.name : materialName}</h3>
            <span className="text-sm tabular-nums text-slate-500 dark:text-slate-400" data-testid="box-material-progress">{t("lumina_box_material_progress").replace("{count}", String(progress.count)).replace("{total}", String(progress.total))}</span>
          </div>
          {!backing ? <div className={`${wellClass} flex flex-wrap items-center justify-between gap-3 p-4`} data-testid="box-material-bound-backings">
            <div className="space-y-1 text-sm"><p className="font-medium">{[t("lumina_box_material_backing_pair"), boundReference?.brand, boundReference?.material_type].filter(Boolean).join(" · ")}</p>
              {materialWorkflow?.backing_materials ? <p className="text-slate-500 dark:text-slate-400">
                {t("lumina_box_material_white_backing")}：{materialWorkflow.backing_materials.W.name} · {t("lumina_box_material_black_backing")}：{materialWorkflow.backing_materials.K.name}
              </p> : boundReference ? <p className="text-slate-500 dark:text-slate-400">
                {t("lumina_box_material_white_backing")}：{backingLabel(boundReference, "white")} · {t("lumina_box_material_black_backing")}：{backingLabel(boundReference, "black")}
              </p> : <p className="text-slate-500 dark:text-slate-400">{t(referenceLoading ? "lumina_box_material_loading" : "lumina_box_material_bound_backing_unavailable")}</p>}
            </div>
            <Button size="sm" variant="secondary" label={t("lumina_box_material_change_backing")} disabled={selectionLocked} onClick={() => beginMaterial(true)} />
          </div> : null}
          {backingWorkflow ? <p className="text-sm text-slate-500 dark:text-slate-400">{t("lumina_box_backing_sample_base")}：{oppositeMaterial?.name ?? backingWorkflow.opposite_name}</p> : null}
          <LuminaBoxMaterialCapture capture={capture} symbol={symbol} reference={legacyBacking} />
          <div className={`${cardDividerClass} flex flex-wrap items-center justify-between gap-3 pt-4`}>
            <span className="text-sm text-slate-500 dark:text-slate-400">{t("lumina_box_material_total_thickness")}</span>
            <Button label={t(hasFreshResult ? "lumina_box_material_regenerate" : backing ? "lumina_box_material_save_backing" : "lumina_box_material_generate")}
              variant={hasFreshResult ? "secondary" : "primary"} loading={fit.busy === "start" || fit.running}
              disabled={!complete || locked || capture.hasUnsavedManual || (!backing && !boundReferenceId) || !!fit.busy || fit.running} onClick={() => void fit.start()} />
          </div>
        </> : null}
      </section>
      {dataset && !formMode && (fit.run || fit.error) ? <section className={`${cardClass} space-y-4 p-5`} data-testid="box-material-result">
        {fit.error ? <StatusBanner tone="error">{fit.error}</StatusBanner> : null}
        {fit.running ? <div className="space-y-2" role="status"><p className="text-sm">{t("lumina_box_material_generating")} · {Math.round((fit.run?.progress ?? 0) * 100)}%</p>
          <progress className="h-2 w-full accent-blue-500" value={fit.run?.progress ?? 0} max={1} /></div> : null}
        {fit.run?.status === "failed" || fit.result?.status === "not_converged" ? <StatusBanner tone="error">{t("lumina_box_material_fit_failed")}</StatusBanner> : null}
        {stale ? <StatusBanner tone="info">{t("lumina_box_material_updated")}</StatusBanner> : null}
        {fit.result && fit.result.status !== "not_converged" && !stale ? backing ? <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="font-medium">{awaitingOpposite
            ? t("lumina_box_backing_awaiting").replace("{name}", oppositeMaterial?.name ?? backingWorkflow?.opposite_name ?? "")
            : t("lumina_box_backing_saved")}</p>
          {awaitingOpposite ? <Button label={t("lumina_box_backing_continue_other")} disabled={selectionLocked}
            onClick={() => oppositeMaterial?.active_dataset_id ? void openBacking(oppositeMaterial) : beginBacking(oppositeMaterial ?? null)} />
            : <Button label={t("lumina_box_material_back_to_material")} disabled={selectionLocked} onClick={() => setCreating("material")} />}
        </div>
          : <div className="flex flex-wrap items-center gap-4">
            {previewRgb?.length === 3 ? <div className="h-20 w-20 shrink-0 rounded-[10px]" aria-hidden="true" style={{ backgroundColor: `rgb(${previewRgb.map((value) => Math.max(0, Math.min(255, Math.round(value)))).join(",")})` }} /> : null}
            <div className="min-w-0 flex-1"><h3 className="text-base font-semibold">{materialName}</h3><p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t(fit.saved ? "lumina_box_material_saved" : "lumina_box_material_ready")}</p></div>
            {fit.saved ? <div className="flex flex-wrap gap-2"><Button variant="secondary" label={t("lumina_box_material_view_library")} onClick={navigation.showLibrary} />
              <Button label={t("lumina_box_material_use_conversion")} onClick={() => navigation.useForConversion(fit.saved!.material.directory_name, symbol)} /></div>
              : <Button label={t("lumina_box_material_save_archive")} loading={fit.busy === "save"} disabled={!!fit.busy}
                onClick={() => void fit.save({ name: materialName, brand: archiveIdentity?.brand ?? dataset.brand,
                  material_type: archiveIdentity?.material_type ?? dataset.material_type, notes: dataset.notes })} />}
          </div> : null}
      </section> : null}
    </div>
  </section>;
}
