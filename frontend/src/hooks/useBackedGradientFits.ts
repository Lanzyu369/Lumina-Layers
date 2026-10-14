import { useEffect, useRef, useState } from "react";
import { backedGradientErrorKey } from "../utils/luminaBoxBackedGradientCapture";
import {
  downloadBackedGradientFit, getBackedGradientFitExportUrl, listBackedGradientFits, loadBackedGradientFit,
  loadBackedGradientFitResult, loadBackedGradientValidation, startBackedGradientFit, validateBackedGradient024,
  type BackedGradientDataset, type BackedGradientFitResult, type BackedGradientFitRun,
} from "../api/luminaBoxBackedGradient";
import { useI18n } from "../i18n/context";

/** Manage independent frozen-input fit runs and their asynchronous results.
 * 管理相互独立的冻结输入拟合及异步结果。 */
export function useBackedGradientFits(dataset: BackedGradientDataset | null) {
  const { t } = useI18n();
  const [runs, setRuns] = useState<BackedGradientFitRun[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [result, setResult] = useState<BackedGradientFitResult | null>(null);
  const [loadingResult, setLoadingResult] = useState(false);
  const [starting, setStarting] = useState(false);
  const [validating, setValidating] = useState(false);
  const [downloading, setDownloading] = useState<"json" | "csv" | "png" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const datasetId = dataset?.dataset_id ?? "";
  const datasetIdRef = useRef(datasetId);
  datasetIdRef.current = datasetId;
  const mountedRef = useRef(false);
  const loadVersionRef = useRef(0);
  const tRef = useRef(t);
  tRef.current = t;

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; loadVersionRef.current += 1; };
  }, []);

  useEffect(() => {
    let active = true;
    setRuns([]);
    setSelectedId("");
    setResult(null);
    setError(null);
    setStarting(false);
    setValidating(false);
    setDownloading(null);
    if (datasetId) void listBackedGradientFits(datasetId).then((loaded) => {
      if (!active) return;
      setRuns(loaded);
      setSelectedId(loaded[0]?.fit_id ?? "");
    }).catch((cause: unknown) => {
      if (active) setError(tRef.current(backedGradientErrorKey(cause, "lumina_box_bg_fit_list_failed")));
    });
    return () => { active = false; };
  }, [datasetId]);

  const selectedRun = runs.find((run) => run.fit_id === selectedId) ?? null;
  const running = selectedRun?.status === "queued" || selectedRun?.status === "running";
  const selectedFitId = selectedRun?.fit_id;
  const selectedStatus = selectedRun?.status;

  useEffect(() => {
    if (!selectedId || !running) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const updated = await loadBackedGradientFit(selectedId);
        if (!active) return;
        setRuns((previous) => previous.map((run) => run.fit_id === updated.fit_id ? updated : run));
        setError(null);
        if (updated.status === "queued" || updated.status === "running") timer = setTimeout(() => void poll(), 1200);
      } catch (cause: unknown) {
        if (!active) return;
        setError(tRef.current(backedGradientErrorKey(cause, "lumina_box_bg_fit_poll_failed")));
        timer = setTimeout(() => void poll(), 3000);
      }
    };
    void poll();
    return () => { active = false; if (timer) clearTimeout(timer); };
  }, [selectedId, running]);

  useEffect(() => {
    const version = ++loadVersionRef.current;
    setResult(null);
    setLoadingResult(false);
    if (!selectedFitId || selectedStatus !== "complete") return;
    setLoadingResult(true);
    void Promise.all([
      loadBackedGradientFitResult(selectedFitId),
      loadBackedGradientValidation(selectedFitId).catch(() => null),
    ]).then(([loaded, validation]) => {
      if (validation) loaded = { ...loaded, validation_024: validation };
      if (mountedRef.current && loadVersionRef.current === version) setResult(loaded);
    }).catch((cause: unknown) => {
      if (mountedRef.current && loadVersionRef.current === version) setError(tRef.current(backedGradientErrorKey(cause, "lumina_box_bg_fit_result_failed")));
    }).finally(() => {
      if (mountedRef.current && loadVersionRef.current === version) setLoadingResult(false);
    });
    return () => { loadVersionRef.current += 1; };
  }, [selectedFitId, selectedStatus]);

  const start = async (includeValidationThickness: boolean) => {
    if (!datasetId || starting || runs.some((run) => run.status === "queued" || run.status === "running")) return;
    const owner = datasetId;
    setStarting(true);
    setError(null);
    try {
      const run = await startBackedGradientFit(owner, includeValidationThickness);
      if (!mountedRef.current || datasetIdRef.current !== owner) return;
      setRuns((previous) => [run, ...previous.filter((item) => item.fit_id !== run.fit_id)]);
      setSelectedId(run.fit_id);
    } catch (cause: unknown) {
      if (mountedRef.current && datasetIdRef.current === owner) setError(tRef.current(backedGradientErrorKey(cause, "lumina_box_bg_fit_start_failed")));
    } finally {
      if (mountedRef.current && datasetIdRef.current === owner) setStarting(false);
    }
  };

  const download = async (format: "json" | "csv" | "png") => {
    if (!selectedRun || selectedRun.status !== "complete" || downloading) return;
    const owner = datasetId;
    const fitId = selectedRun.fit_id;
    setDownloading(format);
    setError(null);
    try {
      if ((window as Window & { electronAPI?: unknown }).electronAPI) {
        window.open(getBackedGradientFitExportUrl(fitId, format), "_blank", "noopener");
        return;
      }
      const blob = await downloadBackedGradientFit(fitId, format);
      if (!mountedRef.current || datasetIdRef.current !== owner) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `lumina-box-backed-gradient-${fitId}.${format}`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch (cause: unknown) {
      if (mountedRef.current && datasetIdRef.current === owner) setError(tRef.current(backedGradientErrorKey(cause, "lumina_box_bg_export_failed")));
    } finally {
      if (mountedRef.current && datasetIdRef.current === owner) setDownloading(null);
    }
  };

  const validate024 = async () => {
    if (!selectedRun || selectedRun.fit_mode !== "frozen_six" || selectedRun.status !== "complete" || validating) return;
    const owner = datasetId;
    const version = loadVersionRef.current;
    setValidating(true);
    setError(null);
    try {
      const validation = await validateBackedGradient024(selectedRun.fit_id);
      if (mountedRef.current && datasetIdRef.current === owner && loadVersionRef.current === version) {
        setResult((previous) => previous ? { ...previous, validation_024: validation } : previous);
      }
    } catch (cause: unknown) {
      if (mountedRef.current && datasetIdRef.current === owner) setError(tRef.current(backedGradientErrorKey(cause, "lumina_box_bg_validate_failed")));
    } finally {
      if (mountedRef.current && datasetIdRef.current === owner) setValidating(false);
    }
  };

  return {
    runs, selectedRun: selectedRun?.dataset_id === datasetId ? selectedRun : null,
    selectedId, selectRun: setSelectedId, result: selectedRun?.dataset_id === datasetId ? result : null, loadingResult,
    starting, running: runs.some((run) => run.status === "queued" || run.status === "running"),
    hasFrozenRun: runs.some((run) => run.fit_mode === "frozen_six" && run.status === "complete"),
    staleResult: !!selectedRun && selectedRun.dataset_revision !== dataset?.revision,
    start, download, downloading, error, validate024, validating,
    runError: selectedRun?.status === "failed" ? t(backedGradientErrorKey(selectedRun.error, "lumina_box_bg_fit_failed")) : null,
  };
}
