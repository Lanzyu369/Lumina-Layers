import { useEffect, useRef, useState } from "react";
import {
  listLuminaBoxMaterialFits, loadLuminaBoxMaterialFit, loadLuminaBoxMaterialFitResult,
  startLuminaBoxMaterialFit, saveLuminaBoxMaterialArchive,
  type LuminaBoxMaterialFitResult, type LuminaBoxMaterialFitRun, type LuminaBoxSavedMaterial,
} from "../api/luminaBoxMaterials";
import type { BackedGradientSymbol } from "../api/luminaBoxBackedGradient";
import { useI18n } from "../i18n/context";
import { backedGradientErrorKey } from "../utils/luminaBoxBackedGradientCapture";

/** Own one material's asynchronous fit and archive save.
 * 管理单种耗材的异步拟合和档案保存。 */
export function useLuminaBoxMaterialFit(
  datasetId: string, materialSymbol: BackedGradientSymbol, referenceId: string, backing: boolean | "backing_material", backingId?: string,
) {
  const { t } = useI18n();
  const [run, setRun] = useState<LuminaBoxMaterialFitRun | null>(null);
  const [result, setResult] = useState<LuminaBoxMaterialFitResult | null>(null);
  const [saved, setSaved] = useState<LuminaBoxSavedMaterial | null>(null);
  const [busy, setBusy] = useState<"start" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const context = `${datasetId}:${materialSymbol}:${referenceId}:${backing}`;
  const contextRef = useRef(context);
  contextRef.current = context;
  const mountedRef = useRef(true);
  const operationRevision = useRef(0);
  const tRef = useRef(t);
  tRef.current = t;
  const isCurrentOperation = (owner: string, revision: number) => mountedRef.current
    && contextRef.current === owner && operationRevision.current === revision;
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  useEffect(() => {
    let active = true;
    const revision = ++operationRevision.current;
    setRun(null); setResult(null); setSaved(null); setError(null); setBusy(null);
    if (datasetId) void listLuminaBoxMaterialFits(datasetId).then((runs) => {
      if (!active || operationRevision.current !== revision) return;
      const historicalRun = runs.find((item) => backing ? item.fit_mode === (backing === "backing_material" ? "backing_material" : "backing_reference")
        : item.fit_mode === "material" && (!item.material_symbol || item.material_symbol === materialSymbol)
          && ((!item.reference_id && !item.capture_reference_id) || item.reference_id === referenceId
            || item.capture_reference_id === referenceId || (!!backingId && item.backing_id === backingId))) ?? null;
      // History initializes an empty context; an explicitly started run takes precedence.
      setRun((currentRun) => currentRun ?? historicalRun);
    }).catch((cause: unknown) => {
      if (active && operationRevision.current === revision) setError(tRef.current(backedGradientErrorKey(cause, "lumina_box_material_load_failed")));
    });
    return () => { active = false; };
  }, [datasetId, materialSymbol, referenceId, backing, backingId]);

  const fitId = run?.fit_id;
  const running = run?.status === "queued" || run?.status === "running";
  useEffect(() => {
    if (!fitId || !running) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const next = await loadLuminaBoxMaterialFit(fitId);
        if (!active) return;
        setRun(next); setError(null);
        if (next.status === "queued" || next.status === "running") timer = setTimeout(() => void poll(), 1500);
      } catch (cause: unknown) {
        if (!active) return;
        setError(tRef.current(backedGradientErrorKey(cause, "lumina_box_material_load_failed")));
        timer = setTimeout(() => void poll(), 4000);
      }
    };
    void poll();
    return () => { active = false; if (timer) clearTimeout(timer); };
  }, [fitId, running]);

  const complete = run?.status === "complete";
  useEffect(() => {
    if (!fitId || !complete) return;
    let active = true;
    const revision = operationRevision.current;
    void loadLuminaBoxMaterialFitResult(fitId).then((loaded) => {
      if (active && operationRevision.current === revision) setResult(loaded);
    }).catch((cause: unknown) => {
      if (active && operationRevision.current === revision) setError(tRef.current(backedGradientErrorKey(cause, "lumina_box_material_load_failed")));
    });
    return () => { active = false; };
  }, [fitId, complete]);

  const start = async () => {
    if (!datasetId || busy || running) return;
    const owner = context;
    const revision = ++operationRevision.current;
    setBusy("start"); setError(null); setResult(null); setSaved(null);
    try {
      const next = await startLuminaBoxMaterialFit(datasetId, backing, materialSymbol, referenceId);
      if (isCurrentOperation(owner, revision)) setRun(next);
    } catch (cause: unknown) {
      if (isCurrentOperation(owner, revision)) setError(tRef.current(backedGradientErrorKey(cause, "lumina_box_material_fit_failed")));
    } finally {
      if (isCurrentOperation(owner, revision)) setBusy(null);
    }
  };

  const save = async (metadata: { name: string; brand: string; material_type: string; notes: string }) => {
    if (!fitId || !complete || busy) return;
    const owner = context;
    const revision = operationRevision.current;
    setBusy("save"); setError(null);
    try {
      let archive: LuminaBoxSavedMaterial;
      try {
        archive = await saveLuminaBoxMaterialArchive(fitId, { ...metadata, overwrite: false });
      } catch (cause: unknown) {
        const status = cause && typeof cause === "object" ? (cause as { response?: { status?: number } }).response?.status : undefined;
        if (status !== 409) throw cause;
        if (!isCurrentOperation(owner, revision)) return;
        if (!window.confirm(tRef.current("lumina_box_material_update_confirm"))) return;
        archive = await saveLuminaBoxMaterialArchive(fitId, { ...metadata, overwrite: true });
      }
      if (isCurrentOperation(owner, revision)) setSaved(archive);
    } catch (cause: unknown) {
      if (isCurrentOperation(owner, revision)) setError(tRef.current(backedGradientErrorKey(cause, "lumina_box_material_save_failed")));
    } finally {
      if (isCurrentOperation(owner, revision)) setBusy(null);
    }
  };

  return { run, result, saved, busy, running, error, start, save };
}
