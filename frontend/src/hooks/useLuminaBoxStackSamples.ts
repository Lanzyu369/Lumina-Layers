import { useEffect, useRef, useState } from "react";
import { apiErrorToVisibleMessage } from "../api/client";
import { listLuminaBoxMaterials } from "../api/extractor";
import {
  deleteLuminaBoxStackSample, exportLuminaBoxStackSamples,
  listLuminaBoxStackSamples, loadLuminaBoxStackSample, saveLuminaBoxStackSample,
  type LuminaBoxStackSampleRecord, type LuminaBoxStackSampleRequest,
} from "../api/luminaBoxStackSamples";
import type { LuminaBoxCaptureResult, LuminaBoxMeasurement } from "../api/luminaBoxSerial";
import type { LuminaBoxSavedMaterial } from "../api/types";
import { useI18n } from "../i18n/context";
import { useLuminaBoxStackSerialStore } from "../stores/luminaBoxStackSerialStore";
import { useSettingsStore } from "../stores/settingsStore";
import {
  compactStackCaptureJournal, isValidStackRecipe, LUMINA_BOX_STACK_CAPTURE_KEY,
  LUMINA_BOX_STACK_DRAFT_KEY, normalizeStackRecipe, restoreStackCaptureJournal,
  restoreStackDraft, stackCaptureKey, stackMeasurementBacking,
  type LuminaBoxStackCaptureEntry, type LuminaBoxStackDraft,
} from "../utils/luminaBoxStackCapture";

const orderedRecords = (records: LuminaBoxStackSampleRecord[]) =>
  [...records].sort((left, right) => right.created_at.localeCompare(left.created_at));

/** Coordinate durable stack captures and independent historical record browsing.
 * 管理可重试的叠色采集，并独立浏览历史记录。 */
export function useLuminaBoxStackSamples() {
  const { t } = useI18n();
  const serial = useLuminaBoxStackSerialStore();
  const backingText = useSettingsStore((state) => state.luminaBoxMeasurementBackingPercentXYZ);
  const [draft, setDraft] = useState(restoreStackDraft);
  const draftRef = useRef(draft);
  const [journal, setJournal] = useState(restoreStackCaptureJournal);
  const journalRef = useRef(journal);
  const inFlightRef = useRef(new Map<string, Promise<LuminaBoxCaptureResult>>());
  const [savingCount, setSavingCount] = useState(0);
  const [storageAvailable, setStorageAvailable] = useState(true);
  const [captureError, setCaptureError] = useState<string | null>(null);
  const [captureIssue, setCaptureIssue] = useState<"invalid_recipe" | "unsupported_mode" | null>(null);
  const [lastSaved, setLastSaved] = useState<LuminaBoxStackSampleRecord | null>(null);
  const [records, setRecords] = useState<LuminaBoxStackSampleRecord[]>([]);
  const recordsRef = useRef(records);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [recordsError, setRecordsError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [selectedRecord, setSelectedRecord] = useState<LuminaBoxStackSampleRecord | null>(null);
  const [recordAction, setRecordAction] = useState<"load" | "delete" | null>(null);
  const [exporting, setExporting] = useState(false);
  const [referenceMaterials, setReferenceMaterials] = useState<LuminaBoxSavedMaterial[]>([]);
  const mountedRef = useRef(false);
  const epochRef = useRef(0);
  const listRequestRef = useRef(0);
  const detailRequestRef = useRef(0);
  const recordMutationRef = useRef(0);
  const deletedRecordIdsRef = useRef(new Set<string>());
  const deletedCaptureKeysRef = useRef(new Set<string>());
  const tRef = useRef(t);
  tRef.current = t;

  const defaultReference = new Set(referenceMaterials.map((item) => item.reference_id)).size === 1
    ? referenceMaterials[0]?.directory_name ?? "" : "";
  const referenceDirectoryName = draft.referenceDirectoryName || defaultReference;
  const referenceRef = useRef(referenceDirectoryName);
  referenceRef.current = referenceDirectoryName;
  const current = (epoch: number) => mountedRef.current && epochRef.current === epoch;

  const persistJournal = (entries: LuminaBoxStackCaptureEntry[]) => {
    const next = compactStackCaptureJournal(entries);
    journalRef.current = next;
    if (mountedRef.current) setJournal(next);
    try {
      localStorage.setItem(LUMINA_BOX_STACK_CAPTURE_KEY, JSON.stringify(next));
      if (mountedRef.current) setStorageAvailable(true);
      return true;
    } catch {
      if (mountedRef.current) setStorageAvailable(false);
      return false;
    }
  };

  const updateDraft = (field: keyof LuminaBoxStackDraft, value: string) => {
    if (!mountedRef.current || inFlightRef.current.size > 0) return;
    const next = { ...draftRef.current, [field]: field === "recipe" ? normalizeStackRecipe(value) : value };
    draftRef.current = next;
    setDraft(next);
    try {
      localStorage.setItem(LUMINA_BOX_STACK_DRAFT_KEY, JSON.stringify(next));
      setStorageAvailable(true);
    } catch { setStorageAvailable(false); }
  };

  const rememberDeletedRecord = (record: LuminaBoxStackSampleRecord) => {
    deletedRecordIdsRef.current.add(record.record_id);
    const key = stackCaptureKey(record.capture_id, record.device_measurement.measurement_id);
    deletedCaptureKeysRef.current.add(key);
    if (journalRef.current.some((entry) => entry.key === key && entry.outcome === "pending")) {
      persistJournal(journalRef.current.map((entry) => entry.key === key ? { ...entry, outcome: "saved" } : entry));
    }
  };

  const refreshRecords = async () => {
    const epoch = epochRef.current;
    const requestId = ++listRequestRef.current;
    const mutation = recordMutationRef.current;
    setRecordsLoading(true);
    setRecordsError(null);
    try {
      const loaded = await listLuminaBoxStackSamples();
      if (!current(epoch) || listRequestRef.current !== requestId || recordMutationRef.current !== mutation) return;
      const loadedIds = new Set(loaded.map((record) => record.record_id));
      recordsRef.current.filter((record) => !loadedIds.has(record.record_id)).forEach(rememberDeletedRecord);
      const ordered = orderedRecords(loaded.filter((record) => !deletedRecordIdsRef.current.has(record.record_id)));
      recordsRef.current = ordered;
      setRecords(ordered);
      setLastSaved((previous) => ordered.find((record) => record.record_id === previous?.record_id) ?? ordered[0] ?? null);
      setSelectedId((previous) => ordered.some((record) => record.record_id === previous) ? previous : "");
      setSelectedRecord((previous) => ordered.find((record) => record.record_id === previous?.record_id) ?? null);
    } catch (error: unknown) {
      if (current(epoch) && listRequestRef.current === requestId) {
        setRecordsError(apiErrorToVisibleMessage(error, tRef.current("lumina_box_stack_list_failed")));
      }
    } finally {
      if (current(epoch) && listRequestRef.current === requestId) setRecordsLoading(false);
    }
  };

  useEffect(() => {
    mountedRef.current = true;
    const epoch = ++epochRef.current;
    try {
      localStorage.setItem(LUMINA_BOX_STACK_DRAFT_KEY, JSON.stringify(draftRef.current));
    } catch { setStorageAvailable(false); }
    void refreshRecords();
    void listLuminaBoxMaterials().then((response) => {
      if (current(epoch)) setReferenceMaterials(response.materials.filter((material) => material.is_reference_white));
    }).catch(() => { /* Reference context is optional for storing a raw reflection. */ });
    return () => {
      mountedRef.current = false;
      epochRef.current += 1;
      void useLuminaBoxStackSerialStore.getState().disconnect();
    };
    // Capture ownership and pending targets belong to this mounted panel instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const saveEntry = (entry: LuminaBoxStackCaptureEntry): Promise<LuminaBoxCaptureResult> => {
    const running = inFlightRef.current.get(entry.key);
    if (running) return running;
    if (!entry.request || !mountedRef.current) return Promise.resolve("storage_unavailable");
    if (!persistJournal(journalRef.current)) return Promise.resolve("storage_unavailable");
    const epoch = epochRef.current;
    const payload = entry.request;
    const operation = (async (): Promise<LuminaBoxCaptureResult> => {
      try {
        const result = await saveLuminaBoxStackSample(payload);
        if (!current(epoch)) return "storage_unavailable";
        if (deletedRecordIdsRef.current.has(result.record.record_id) || deletedCaptureKeysRef.current.has(entry.key)) {
          rememberDeletedRecord(result.record);
          return "applied";
        }
        recordMutationRef.current += 1;
        const nextRecords = orderedRecords([
          result.record, ...recordsRef.current.filter((record) => record.record_id !== result.record.record_id),
        ]);
        recordsRef.current = nextRecords;
        setRecords(nextRecords);
        setLastSaved(result.record);
        const next = journalRef.current.map((item) => item.key === entry.key ? { ...item, outcome: "saved" as const } : item);
        persistJournal(next);
        if (!next.some((item) => item.outcome === "pending")) setCaptureError(null);
        return "applied";
      } catch (error: unknown) {
        if (current(epoch)) setCaptureError(apiErrorToVisibleMessage(error, tRef.current("lumina_box_stack_save_failed")));
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
    const captureId = useLuminaBoxStackSerialStore.getState().captureId;
    const key = stackCaptureKey(captureId, measurement.measurement_id);
    const existing = journalRef.current.find((entry) => entry.key === key);
    if (existing?.outcome === "saved") return "applied";
    if (existing?.outcome === "pending") return saveEntry(existing);
    if (existing) {
      setCaptureIssue(existing.outcome);
      return existing.outcome;
    }
    const receivedAt = new Date().toISOString();
    const snapshot = { ...draftRef.current };
    const issue = measurement.mode === "transmit" ? "unsupported_mode"
      : !isValidStackRecipe(snapshot.recipe) ? "invalid_recipe" : null;
    if (issue) {
      persistJournal([...journalRef.current, { key, receivedAt, outcome: issue, request: null }]);
      setCaptureIssue(issue);
      return issue;
    }
    // Freeze the complete frame and form before the first HTTP await.
    const payload: LuminaBoxStackSampleRequest = {
      recipe_top_to_bottom: snapshot.recipe,
      sample_name: snapshot.sampleName.trim(), material_batch: snapshot.materialBatch.trim(), notes: snapshot.notes,
      capture_id: captureId,
      received_at: receivedAt,
      measurement: JSON.parse(JSON.stringify(measurement)) as LuminaBoxMeasurement,
      reference_directory_name: referenceRef.current || null,
      measurement_backing_percent_xyz: stackMeasurementBacking(
        useSettingsStore.getState().luminaBoxMeasurementBackingPercentXYZ,
      ),
    };
    const entry: LuminaBoxStackCaptureEntry = { key, receivedAt, outcome: "pending", request: payload };
    const persisted = persistJournal([...journalRef.current, entry]);
    setCaptureIssue(null);
    if (!persisted) return "storage_unavailable";
    return saveEntry(entry);
  };

  const retryCapture = async (key: string) => {
    const entry = journalRef.current.find((item) => item.key === key && item.outcome === "pending");
    if (entry && await saveEntry(entry) === "applied" && mountedRef.current) {
      useLuminaBoxStackSerialStore.getState().replay();
    }
  };

  const viewRecord = async (recordId: string) => {
    const epoch = epochRef.current;
    const requestId = ++detailRequestRef.current;
    setSelectedId(recordId);
    setSelectedRecord(null);
    setRecordAction("load");
    setRecordsError(null);
    try {
      const loaded = await loadLuminaBoxStackSample(recordId);
      if (current(epoch) && detailRequestRef.current === requestId && !deletedRecordIdsRef.current.has(loaded.record_id)) setSelectedRecord(loaded);
    } catch (error: unknown) {
      if (current(epoch) && detailRequestRef.current === requestId) {
        setRecordsError(apiErrorToVisibleMessage(error, tRef.current("lumina_box_stack_load_failed")));
      }
    } finally {
      if (current(epoch) && detailRequestRef.current === requestId) setRecordAction(null);
    }
  };

  const deleteSelected = async () => {
    if (!selectedRecord || recordAction) return;
    const epoch = epochRef.current;
    const recordToDelete = selectedRecord;
    const recordId = recordToDelete.record_id;
    const requestId = ++detailRequestRef.current;
    setRecordAction("delete");
    setRecordsError(null);
    try {
      await deleteLuminaBoxStackSample(recordId);
      if (!current(epoch)) return;
      recordMutationRef.current += 1;
      rememberDeletedRecord(recordToDelete);
      const remaining = recordsRef.current.filter((record) => record.record_id !== recordId);
      recordsRef.current = remaining;
      setRecords(remaining);
      setLastSaved((previous) => previous?.record_id === recordId ? remaining[0] ?? null : previous);
      if (detailRequestRef.current === requestId) {
        setSelectedId("");
        setSelectedRecord(null);
      }
    } catch (error: unknown) {
      if (current(epoch)) setRecordsError(apiErrorToVisibleMessage(error, tRef.current("lumina_box_stack_delete_failed")));
    } finally {
      if (current(epoch) && detailRequestRef.current === requestId) setRecordAction(null);
    }
  };

  const exportRecords = async () => {
    const epoch = epochRef.current;
    setExporting(true);
    setRecordsError(null);
    try {
      const exported = await exportLuminaBoxStackSamples();
      if (!current(epoch)) return;
      const url = URL.createObjectURL(new Blob([JSON.stringify(exported, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "lumina-box-stack-samples.json";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (error: unknown) {
      if (current(epoch)) setRecordsError(apiErrorToVisibleMessage(error, tRef.current("lumina_box_stack_export_failed")));
    } finally {
      if (current(epoch)) setExporting(false);
    }
  };

  return {
    draft, updateDraft, validRecipe: isValidStackRecipe(draft.recipe),
    serial, connect: () => serial.connect(receiveMeasurement),
    savingCount, pendingCaptures: journal.filter((entry) => entry.outcome === "pending"), retryCapture,
    storageAvailable, captureError, captureIssue, lastSaved,
    lastSavedReceivedAt: lastSaved ? journal.find((entry) => entry.key === stackCaptureKey(
      lastSaved.capture_id, lastSaved.device_measurement.measurement_id,
    ))?.receivedAt : undefined,
    records, recordsLoading, recordsError, refreshRecords,
    selectedId, selectedRecord, recordAction, viewRecord, deleteSelected,
    exporting, exportRecords, referenceMaterials, referenceDirectoryName, backingText,
  };
}
