import { useEffect, useRef, useState } from "react";
import {
  BACKED_GRADIENT_SYMBOLS,
  createBackedGradientDataset, deleteBackedGradientCapture, exportBackedGradientDataset,
  getBackedGradientExportUrl, importBackedGradientDataset, listBackedGradientDatasets, loadBackedGradientDataset,
  saveBackedGradientCapture, selectBackedGradientCapture,
  type BackedGradientCapture, type BackedGradientCaptureRequest, type BackedGradientDataset,
  type BackedGradientDatasetRequest,
} from "../api/luminaBoxBackedGradient";
import type { LuminaBoxCaptureResult, LuminaBoxMeasurement } from "../api/luminaBoxSerial";
import type { LuminaBoxMaterialDataset } from "../api/luminaBoxMaterials";
import { useI18n } from "../i18n/context";
import { useLuminaBoxBackedGradientSerialStore } from "../stores/luminaBoxBackedGradientSerialStore";
import {
  BACKED_GRADIENT_DRAFT_KEY, BACKED_GRADIENT_JOURNAL_KEY, BACKED_GRADIENT_MAX_IMPORT_BYTES, backedGradientCaptureSlot,
  backedGradientErrorKey,
  backedGradientManualXYZ, backedGradientSlotKey, backedGradientTargetKey, backedGradientThickness,
  compactBackedGradientJournal, isBackedGradientExport, restoreBackedGradientDraft,
  restoreBackedGradientJournal, routeBackedGradientMeasurement,
  savedBackedGradientMaterialSymbols,
  type BackedGradientDraft, type BackedGradientJournal, type BackedGradientJournalEntry,
  type BackedGradientTarget,
} from "../utils/luminaBoxBackedGradientCapture";
import { useBackedGradientFits } from "./useBackedGradientFits";

const captureKey = (datasetId: string, captureId: string, measurementId: string) =>
  JSON.stringify([datasetId, captureId, measurementId]);

function captureTargetForDataset(dataset: BackedGradientDataset, previous: BackedGradientTarget, savedOnly = false): BackedGradientTarget {
  const workflow = (dataset as LuminaBoxMaterialDataset).workflow;
  if (workflow?.kind === "material") {
    return { material_symbol: workflow.material_symbol, backing: previous.backing, sample_role: "coated" };
  }
  if (workflow?.kind === "backing_material") {
    const role = workflow.material_symbol;
    return previous.sample_role === "bare_backing" && previous.material_symbol === role
      ? { material_symbol: role, backing: role, sample_role: "bare_backing" }
      : { material_symbol: role, backing: role === "W" ? "K" : "W", sample_role: "coated" };
  }
  if (workflow?.kind === "backing_reference" && previous.material_symbol !== "W" && previous.material_symbol !== "K") {
    return { material_symbol: "K", backing: "W", sample_role: "coated" };
  }
  const savedSymbols = savedBackedGradientMaterialSymbols(dataset);
  if (!workflow && (savedOnly ? !savedSymbols.includes(previous.material_symbol) : !dataset.materials[previous.material_symbol])) {
    const symbol = savedSymbols[0] ?? BACKED_GRADIENT_SYMBOLS[0];
    return { material_symbol: symbol, backing: previous.backing, sample_role: "coated" };
  }
  return previous;
}

/** Own gradient acquisition, frozen retries, datasets and active reading selection.
 * 管理梯度采集、冻结重试、数据集及当前读数选择。 */
export function useLuminaBoxBackedGradient(options: {
  researchFits?: boolean;
  initialDatasetId?: string;
  initialTarget?: BackedGradientTarget;
} = {}) {
  const { t } = useI18n();
  const serial = useLuminaBoxBackedGradientSerialStore();
  const [initialSelection] = useState(() => {
    const restored = restoreBackedGradientDraft();
    const requested = options.initialDatasetId ? { ...restored, datasetId: options.initialDatasetId,
      target: options.initialTarget ?? restored.target } : restored;
    const blocked = restored.manualXYZ.some((value) => value.trim() !== "")
      && backedGradientTargetKey(restored.datasetId, restored.target)
        !== backedGradientTargetKey(requested.datasetId, requested.target);
    return { draft: blocked ? restored : requested, blocked };
  });
  const [draft, setDraft] = useState(initialSelection.draft);
  const draftRef = useRef(draft);
  const [journal, setJournal] = useState(restoreBackedGradientJournal);
  const journalRef = useRef(journal);
  const [datasets, setDatasets] = useState<BackedGradientDataset[]>([]);
  const [dataset, setDataset] = useState<BackedGradientDataset | null>(null);
  const datasetRef = useRef(dataset);
  const [datasetBusy, setDatasetBusy] = useState<"load" | "create" | "import" | "export" | null>(null);
  const [savingCount, setSavingCount] = useState(0);
  const [recordBusy, setRecordBusy] = useState<string | null>(null);
  const [storageAvailable, setStorageAvailable] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [captureNotice, setCaptureNotice] = useState<string | null>(initialSelection.blocked ? "lumina_box_bg_manual_unsaved" : null);
  const [lastCapture, setLastCapture] = useState<BackedGradientCapture | null>(null);
  const lastCaptureRef = useRef<BackedGradientCapture | null>(null);
  const captureOrderRef = useRef(new Map<string, number>());
  const nextCaptureOrderRef = useRef(0);
  const [inspectedSlot, setInspectedSlot] = useState(() => backedGradientSlotKey(draft.target, Number(draft.manualThickness)));
  const [inspectedRecordId, setInspectedRecordId] = useState("");
  const mountedRef = useRef(false);
  const epochRef = useRef(0);
  const loadRequestRef = useRef(0);
  const inFlightRef = useRef(new Map<string, Promise<LuminaBoxCaptureResult>>());
  const deletedIdsRef = useRef(new Set<string>());
  const tRef = useRef(t);
  tRef.current = t;
  const fits = useBackedGradientFits(options.researchFits === false ? null : dataset);
  const current = (epoch: number) => mountedRef.current && epochRef.current === epoch;

  const compareCaptureOrder = (left: BackedGradientCapture, right: BackedGradientCapture) => {
    const timeDifference = Date.parse(left.received_at) - Date.parse(right.received_at);
    const localOrder = (record: BackedGradientCapture) => captureOrderRef.current.get(
      captureKey(record.dataset_id, record.capture_id, record.measurement_id),
    ) ?? 0;
    return timeDifference || localOrder(left) - localOrder(right);
  };

  const persistDraft = (next: BackedGradientDraft) => {
    try {
      localStorage.setItem(BACKED_GRADIENT_DRAFT_KEY, JSON.stringify(next));
      draftRef.current = next;
      if (mountedRef.current) setDraft(next);
      if (mountedRef.current) setStorageAvailable(true);
      return true;
    } catch {
      if (mountedRef.current) setStorageAvailable(false);
      return false;
    }
  };

  const persistJournal = (value: BackedGradientJournal) => {
    const next = compactBackedGradientJournal(value);
    journalRef.current = next;
    if (mountedRef.current) setJournal(next);
    try {
      localStorage.setItem(BACKED_GRADIENT_JOURNAL_KEY, JSON.stringify(next));
      if (mountedRef.current) setStorageAvailable(true);
      return true;
    } catch {
      if (mountedRef.current) setStorageAvailable(false);
      return false;
    }
  };

  const inspectDraftTarget = () => {
    const { target, manualThickness } = draftRef.current;
    setInspectedSlot(backedGradientSlotKey(target, target.sample_role === "bare_backing" ? 0 : Number(manualThickness)));
    setInspectedRecordId("");
  };

  const applyDataset = (incoming: BackedGradientDataset) => {
    setDatasets((previous) => [incoming, ...previous.filter((item) => item.dataset_id !== incoming.dataset_id)]
      .sort((left, right) => right.updated_at.localeCompare(left.updated_at)));
    if (draftRef.current.datasetId !== incoming.dataset_id) return;
    const previous = datasetRef.current;
    if (previous?.dataset_id === incoming.dataset_id && previous.revision > incoming.revision) return;
    const captures = incoming.captures.filter((record) => !deletedIdsRef.current.has(record.record_id));
    const next = { ...incoming, captures, selected_capture_ids: Object.fromEntries(
      Object.entries(incoming.selected_capture_ids).filter(([, id]) => !deletedIdsRef.current.has(id)),
    ) };
    datasetRef.current = next;
    setDataset(next);
    const latest = [...captures].sort((left, right) => compareCaptureOrder(right, left))[0] ?? null;
    lastCaptureRef.current = latest;
    setLastCapture(latest);
    setInspectedRecordId((id) => captures.some((record) => record.record_id === id) ? id : "");
  };

  const contextBlocked = () => inFlightRef.current.size > 0
    || journalRef.current.entries.some((entry) => entry.outcome === "pending")
    || useLuminaBoxBackedGradientSerialStore.getState().pendingCount > 0;

  const hasUnsavedManual = () => draftRef.current.manualXYZ.some((value) => value.trim() !== "");
  const canChangeSelection = () => {
    if (contextBlocked()) { setCaptureNotice("lumina_box_bg_finish_pending"); return false; }
    if (hasUnsavedManual()) { setCaptureNotice("lumina_box_bg_manual_unsaved"); return false; }
    return true;
  };

  const armScope = (datasetId: string, target: BackedGradientTarget, forceNew = false) => {
    const store = useLuminaBoxBackedGradientSerialStore.getState();
    const old = journalRef.current.scope;
    if (!forceNew && old?.captureId === store.captureId
      && backedGradientTargetKey(old.datasetId, old.target) === backedGradientTargetKey(datasetId, target)) return true;
    store.resetCapture();
    return persistJournal({ ...journalRef.current, scope: {
      captureId: useLuminaBoxBackedGradientSerialStore.getState().captureId,
      datasetId, target: { ...target },
    } });
  };

  const loadDataset = async (datasetId: string, requestedTarget?: BackedGradientTarget) => {
    if (!datasetId) return;
    const existing = datasetId === draftRef.current.datasetId && datasetRef.current?.dataset_id === datasetId
      ? datasetRef.current : null;
    if (existing && (!requestedTarget || backedGradientTargetKey(datasetId, requestedTarget)
      === backedGradientTargetKey(datasetId, draftRef.current.target))) return true;
    if (!canChangeSelection()) return;
    const epoch = epochRef.current;
    const requestId = ++loadRequestRef.current;
    setDatasetBusy("load");
    setError(null);
    try {
      const loaded = existing ?? await loadBackedGradientDataset(datasetId);
      if (!current(epoch) || requestId !== loadRequestRef.current) return;
      if (!canChangeSelection()) return;
      if (!persistDraft({ ...draftRef.current, datasetId,
        target: captureTargetForDataset(loaded, requestedTarget ?? draftRef.current.target, options.researchFits === false),
        manualThickness: requestedTarget ? "0.08" : draftRef.current.manualThickness, manualXYZ: ["", "", ""] })) return;
      armScope(datasetId, draftRef.current.target);
      applyDataset(loaded);
      setCaptureNotice(null);
      inspectDraftTarget();
      return true;
    } catch (cause: unknown) {
      if (current(epoch) && requestId === loadRequestRef.current) setError(tRef.current(backedGradientErrorKey(cause, "lumina_box_bg_load_failed")));
    } finally {
      if (current(epoch) && requestId === loadRequestRef.current) setDatasetBusy(null);
    }
  };

  const refresh = async () => {
    const epoch = epochRef.current;
    const requestId = ++loadRequestRef.current;
    const owner = draftRef.current.datasetId;
    setDatasetBusy("load");
    setError(null);
    try {
      const all = await listBackedGradientDatasets();
      if (!current(epoch) || requestId !== loadRequestRef.current) return;
      setDatasets(all);
      const nextId = owner || (options.researchFits === false ? undefined : all[0]?.dataset_id);
      if (!nextId) return;
      const loaded = await loadBackedGradientDataset(nextId);
      if (!current(epoch) || requestId !== loadRequestRef.current || draftRef.current.datasetId !== owner) return;
      const target = captureTargetForDataset(loaded, draftRef.current.target, options.researchFits === false);
      if ((!owner || target.material_symbol !== draftRef.current.target.material_symbol
        || target.sample_role !== draftRef.current.target.sample_role)
        && !persistDraft({ ...draftRef.current, datasetId: nextId, target })) return;
      applyDataset(loaded);
      inspectDraftTarget();
    } catch (cause: unknown) {
      if (current(epoch) && requestId === loadRequestRef.current) setError(tRef.current(backedGradientErrorKey(cause, "lumina_box_bg_load_failed")));
    } finally {
      if (current(epoch) && requestId === loadRequestRef.current) setDatasetBusy(null);
    }
  };

  useEffect(() => {
    mountedRef.current = true;
    epochRef.current += 1;
    persistDraft(draftRef.current);
    void refresh();
    return () => {
      mountedRef.current = false;
      epochRef.current += 1;
      void useLuminaBoxBackedGradientSerialStore.getState().disconnect();
    };
    // One mounted panel owns the current acquisition and its pending targets.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectSlot = (next: BackedGradientTarget, thickness = Number(draftRef.current.manualThickness)): boolean => {
    const normalized = next.sample_role === "bare_backing" ? 0 : backedGradientThickness(thickness);
    if (normalized === null || !datasetRef.current) return false;
    const targetChanged = backedGradientTargetKey(draftRef.current.datasetId, draftRef.current.target)
      !== backedGradientTargetKey(draftRef.current.datasetId, next);
    const thicknessChanged = next.sample_role !== "bare_backing" && normalized !== Number(draftRef.current.manualThickness);
    if ((targetChanged || thicknessChanged) && !canChangeSelection()) return false;
    if (targetChanged || thicknessChanged) {
      if (!persistDraft({ ...draftRef.current, target: { ...next },
        manualThickness: next.sample_role === "bare_backing" ? draftRef.current.manualThickness : normalized.toFixed(2),
        manualXYZ: ["", "", ""] })) return false;
      if (targetChanged) armScope(draftRef.current.datasetId, next);
      setCaptureNotice(null);
    }
    setInspectedSlot(backedGradientSlotKey(next, normalized));
    setInspectedRecordId("");
    return true;
  };

  const changeTarget = (next: BackedGradientTarget) => selectSlot(next);

  const discardManual = () => {
    if (inFlightRef.current.size > 0) return;
    if (!persistDraft({ ...draftRef.current, manualXYZ: ["", "", ""] })) return;
    setCaptureNotice((notice) => notice === "lumina_box_bg_manual_unsaved" ? null : notice);
  };

  const updateDraft = (patch: Partial<Pick<BackedGradientDraft, "manualThickness" | "manualXYZ" | "sampleName" | "notes">>) => {
    if (inFlightRef.current.size > 0 || !mountedRef.current) return;
    if (patch.manualThickness !== undefined && patch.manualThickness !== draftRef.current.manualThickness && hasUnsavedManual()) {
      setCaptureNotice("lumina_box_bg_manual_unsaved"); return;
    }
    persistDraft({ ...draftRef.current, ...patch });
  };

  const clearSavedManual = (entry: BackedGradientJournalEntry) => {
    const request = entry.request;
    if (!request || request.measurement || !request.reflectance_percent_xyz) return;
    const currentDraft = draftRef.current;
    if (backedGradientTargetKey(currentDraft.datasetId, currentDraft.target)
      !== backedGradientTargetKey(entry.datasetId, request)) return;
    const thickness = currentDraft.target.sample_role === "bare_backing" ? 0 : Number(currentDraft.manualThickness);
    const xyz = backedGradientManualXYZ(currentDraft.manualXYZ);
    if (thickness !== request.overlay_mm || !xyz || xyz.some((value, index) => value !== request.reflectance_percent_xyz![index])) return;
    persistDraft({ ...currentDraft, manualXYZ: ["", "", ""] });
  };

  const saveEntry = (entry: BackedGradientJournalEntry): Promise<LuminaBoxCaptureResult> => {
    const existing = inFlightRef.current.get(entry.key);
    if (existing) return existing;
    if (!entry.request || !mountedRef.current || !persistJournal(journalRef.current)) return Promise.resolve("storage_unavailable");
    if (!captureOrderRef.current.has(entry.key)) captureOrderRef.current.set(entry.key, ++nextCaptureOrderRef.current);
    const epoch = epochRef.current;
    const request = entry.request;
    const operation = (async (): Promise<LuminaBoxCaptureResult> => {
      try {
        const response = await saveBackedGradientCapture(entry.datasetId, request);
        if (!current(epoch)) return "storage_unavailable";
        persistJournal({ ...journalRef.current, entries: journalRef.current.entries.map((item) => item.key === entry.key
          ? { ...item, outcome: "saved" as const, recordId: response.record.record_id } : item) });
        if (!deletedIdsRef.current.has(response.record.record_id)) {
          applyDataset(response.dataset);
          if (draftRef.current.datasetId === entry.datasetId) {
            clearSavedManual(entry);
            const latest = lastCaptureRef.current;
            if (!latest || latest.dataset_id !== entry.datasetId || compareCaptureOrder(response.record, latest) >= 0) {
              lastCaptureRef.current = response.record;
              setLastCapture(response.record);
              setInspectedSlot(backedGradientCaptureSlot(response.record));
              setInspectedRecordId("");
              if (request.measurement && request.overlay_mm > 0 && !hasUnsavedManual()
                && backedGradientTargetKey(draftRef.current.datasetId, draftRef.current.target)
                  === backedGradientTargetKey(entry.datasetId, request)) {
                persistDraft({ ...draftRef.current, manualThickness: request.overlay_mm.toFixed(2) });
              }
            }
          }
        }
        if (!journalRef.current.entries.some((item) => item.outcome === "pending")) setError(null);
        return "applied";
      } catch (cause: unknown) {
        if (current(epoch)) setError(tRef.current(backedGradientErrorKey(cause, "lumina_box_bg_save_failed")));
        return "storage_unavailable";
      } finally {
        inFlightRef.current.delete(entry.key);
        if (current(epoch)) setSavingCount(inFlightRef.current.size);
      }
    })();
    inFlightRef.current.set(entry.key, operation);
    setSavingCount(inFlightRef.current.size);
    return operation;
  };

  const receiveMeasurement = async (measurement: LuminaBoxMeasurement): Promise<LuminaBoxCaptureResult> => {
    if (!mountedRef.current) return "storage_unavailable";
    const store = useLuminaBoxBackedGradientSerialStore.getState();
    const scope = journalRef.current.scope;
    if (!scope || scope.captureId !== store.captureId) { setCaptureNotice("lumina_box_bg_target_not_armed"); return "invalid_recipe"; }
    const key = captureKey(scope.datasetId, scope.captureId, measurement.measurement_id);
    const existing = journalRef.current.entries.find((entry) => entry.key === key);
    if (existing?.outcome === "saved") return "applied";
    if (existing?.outcome === "pending") return saveEntry(existing);
    if (existing) return existing.rejection ?? "storage_unavailable";
    const oldPending = journalRef.current.entries.find((entry) => entry.measurementId === measurement.measurement_id
      && (entry.outcome === "pending" || entry.outcome === "abandoned"));
    if (oldPending) return oldPending.outcome === "pending" ? saveEntry(oldPending) : "storage_unavailable";
    const receivedAt = new Date().toISOString();
    const routed = routeBackedGradientMeasurement(scope.target, scope.captureId, measurement, receivedAt, draftRef.current);
    if (routed.result !== "ready") {
      persistJournal({ ...journalRef.current, entries: [...journalRef.current.entries, {
        key, datasetId: scope.datasetId, measurementId: measurement.measurement_id, receivedAt,
        outcome: "rejected", rejection: routed.result, request: null,
      }] });
      setCaptureNotice(routed.result === "unsupported_mode" ? "lumina_box_bg_reflection_required" : "lumina_box_bg_thickness_mismatch");
      return routed.result;
    }
    const entry: BackedGradientJournalEntry = {
      key, datasetId: scope.datasetId, measurementId: measurement.measurement_id, receivedAt,
      outcome: "pending", request: routed.request,
    };
    if (!persistJournal({ ...journalRef.current, entries: [...journalRef.current.entries, entry] })) return "storage_unavailable";
    setCaptureNotice(null);
    return saveEntry(entry);
  };

  const connect = () => {
    if (!datasetRef.current || datasetRef.current.dataset_id !== draftRef.current.datasetId) return;
    const old = journalRef.current.scope;
    const correctScope = old?.captureId === serial.captureId
      && backedGradientTargetKey(old.datasetId, old.target) === backedGradientTargetKey(draftRef.current.datasetId, draftRef.current.target);
    if (!correctScope && contextBlocked()) { setCaptureNotice("lumina_box_bg_finish_pending"); return; }
    if (!armScope(draftRef.current.datasetId, draftRef.current.target)) return;
    useLuminaBoxBackedGradientSerialStore.getState().connect(receiveMeasurement);
  };

  const saveManual = async () => {
    if (!datasetRef.current || inFlightRef.current.size > 0) return;
    const snapshot = draftRef.current;
    const xyz = backedGradientManualXYZ(snapshot.manualXYZ);
    const thickness = snapshot.target.sample_role === "bare_backing" ? 0 : backedGradientThickness(Number(snapshot.manualThickness));
    if (!xyz || thickness === null) { setCaptureNotice("lumina_box_bg_manual_invalid"); return; }
    if (!armScope(snapshot.datasetId, snapshot.target)) return;
    const scope = journalRef.current.scope!;
    const receivedAt = new Date().toISOString();
    const measurementId = `manual-${crypto.randomUUID()}`;
    const request: BackedGradientCaptureRequest = {
      capture_id: scope.captureId, ...scope.target, overlay_mm: thickness,
      reflectance_percent_xyz: xyz, measurement_id: measurementId, received_at: receivedAt,
      sample_name: snapshot.sampleName.trim(), notes: snapshot.notes,
    };
    const entry: BackedGradientJournalEntry = {
      key: captureKey(scope.datasetId, scope.captureId, measurementId), datasetId: scope.datasetId,
      measurementId, receivedAt, outcome: "pending", request,
    };
    if (!persistJournal({ ...journalRef.current, entries: [...journalRef.current.entries, entry] })) return;
    setCaptureNotice(null);
    await saveEntry(entry);
  };

  const retry = async (key: string) => {
    const entry = journalRef.current.entries.find((item) => item.key === key && item.outcome === "pending");
    if (entry && await saveEntry(entry) === "applied" && mountedRef.current) serial.replay();
  };

  const discardPending = () => {
    if (inFlightRef.current.size > 0) return;
    if (!persistJournal({ ...journalRef.current, entries: journalRef.current.entries.map((entry) => entry.outcome === "pending"
      ? { ...entry, outcome: "abandoned" as const } : entry) })) return;
    if (draftRef.current.datasetId) armScope(draftRef.current.datasetId, draftRef.current.target, true);
    setCaptureNotice(null);
    setError(null);
  };

  const createDataset = async (
    payload: BackedGradientDatasetRequest,
    create: (input: BackedGradientDatasetRequest) => Promise<BackedGradientDataset> = createBackedGradientDataset,
  ): Promise<boolean> => {
    if (!canChangeSelection()) return false;
    const epoch = epochRef.current;
    setDatasetBusy("create");
    setError(null);
    try {
      const created = await create(payload);
      if (!current(epoch)) return false;
      if (!canChangeSelection()) { setDatasets((previous) => [created, ...previous]); return false; }
      if (!persistDraft({ ...draftRef.current, datasetId: created.dataset_id,
        target: captureTargetForDataset(created, { ...draftRef.current.target, backing: "W", sample_role: "coated" }, options.researchFits === false),
        manualThickness: "0.08", manualXYZ: ["", "", ""] })) {
        setDatasets((previous) => [created, ...previous]); return false;
      }
      armScope(created.dataset_id, draftRef.current.target);
      applyDataset(created);
      inspectDraftTarget();
      setCaptureNotice(null);
      return true;
    } catch (cause: unknown) {
      if (current(epoch)) setError(tRef.current(backedGradientErrorKey(cause, "lumina_box_bg_create_failed")));
      return false;
    } finally { if (current(epoch)) setDatasetBusy(null); }
  };

  const importDataset = async (file: File) => {
    if (!canChangeSelection()) return;
    if (file.size > BACKED_GRADIENT_MAX_IMPORT_BYTES) { setError(tRef.current("lumina_box_bg_import_too_large")); return; }
    const epoch = epochRef.current;
    setDatasetBusy("import");
    setError(null);
    try {
      const parsed: unknown = JSON.parse(await file.text());
      if (!isBackedGradientExport(parsed)) { setError(tRef.current("lumina_box_bg_import_invalid")); return; }
      const imported = await importBackedGradientDataset(parsed);
      if (!current(epoch)) return;
      if (!canChangeSelection()) { setDatasets((previous) => [imported, ...previous.filter((item) => item.dataset_id !== imported.dataset_id)]); return; }
      if (!persistDraft({ ...draftRef.current, datasetId: imported.dataset_id,
        target: captureTargetForDataset(imported, draftRef.current.target, options.researchFits === false), manualXYZ: ["", "", ""] })) {
        setDatasets((previous) => [imported, ...previous.filter((item) => item.dataset_id !== imported.dataset_id)]); return;
      }
      armScope(imported.dataset_id, draftRef.current.target);
      applyDataset(imported);
      inspectDraftTarget();
      return true;
    } catch (cause: unknown) {
      if (current(epoch)) setError(tRef.current(backedGradientErrorKey(cause, cause instanceof SyntaxError ? "lumina_box_bg_import_invalid" : "lumina_box_bg_import_failed")));
    } finally { if (current(epoch)) setDatasetBusy(null); }
  };

  const exportDataset = async () => {
    const owner = draftRef.current.datasetId;
    if (!owner) return;
    const epoch = epochRef.current;
    setDatasetBusy("export");
    setError(null);
    try {
      if ((window as Window & { electronAPI?: unknown }).electronAPI) {
        window.open(getBackedGradientExportUrl(owner), "_blank", "noopener");
        return;
      }
      const exported = await exportBackedGradientDataset(owner);
      if (!current(epoch)) return;
      const url = URL.createObjectURL(new Blob([JSON.stringify(exported, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `lumina-box-backed-gradient-${owner}.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch (cause: unknown) {
      if (current(epoch)) setError(tRef.current(backedGradientErrorKey(cause, "lumina_box_bg_export_failed")));
    } finally { if (current(epoch)) setDatasetBusy(null); }
  };

  const chooseCapture = async (record: BackedGradientCapture) => {
    if (recordBusy) return;
    const epoch = epochRef.current;
    setRecordBusy(record.record_id);
    setError(null);
    try {
      const updated = await selectBackedGradientCapture(record.dataset_id, record.record_id);
      if (current(epoch)) applyDataset(updated);
    } catch (cause: unknown) {
      if (current(epoch)) setError(tRef.current(backedGradientErrorKey(cause, "lumina_box_bg_select_failed")));
    } finally { if (current(epoch)) setRecordBusy(null); }
  };

  const removeCapture = async (record: BackedGradientCapture) => {
    if (recordBusy) return;
    const epoch = epochRef.current;
    setRecordBusy(record.record_id);
    setError(null);
    try {
      const updated = await deleteBackedGradientCapture(record.dataset_id, record.record_id);
      if (!current(epoch)) return;
      deletedIdsRef.current.add(record.record_id);
      const key = captureKey(record.dataset_id, record.capture_id, record.measurement_id);
      persistJournal({ ...journalRef.current, entries: journalRef.current.entries.map((entry) => entry.key === key
        ? { ...entry, outcome: "saved" as const, recordId: record.record_id } : entry) });
      applyDataset(updated);
    } catch (cause: unknown) {
      if (current(epoch)) setError(tRef.current(backedGradientErrorKey(cause, "lumina_box_bg_delete_failed")));
    } finally { if (current(epoch)) setRecordBusy(null); }
  };

  const pending = journal.entries.filter((entry) => entry.outcome === "pending");
  const failedPending = pending.filter((entry) => !inFlightRef.current.has(entry.key));
  const slotRecords = dataset?.captures.filter((record) => backedGradientCaptureSlot(record) === inspectedSlot)
    .sort((left, right) => right.received_at.localeCompare(left.received_at)) ?? [];
  const inspectedRecord = dataset?.captures.find((record) => record.record_id === inspectedRecordId)
    ?? slotRecords.find((record) => record.record_id === dataset?.selected_capture_ids[inspectedSlot]) ?? slotRecords[0] ?? null;

  return {
    draft, updateDraft, changeTarget, selectSlot, discardManual, hasUnsavedManual: hasUnsavedManual(), serial, connect, dataset, datasets, datasetBusy,
    loadDataset, refresh, createDataset, importDataset, exportDataset,
    savingCount, pending, failedPending, retry, discardPending, contextBlocked: savingCount > 0 || pending.length > 0 || serial.pendingCount > 0,
    storageAvailable, error, captureNotice, lastCapture, saveManual,
    manualValid: backedGradientManualXYZ(draft.manualXYZ) !== null,
    inspectedSlot, inspectSlot: (slot: string) => { setInspectedSlot(slot); setInspectedRecordId(""); },
    slotRecords, inspectedRecord, inspectRecord: setInspectedRecordId, chooseCapture, removeCapture, recordBusy,
    fits,
  };
}
