import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import Button from "../../../components/ui/Button";
import {
  CropModal,
  type CropData,
} from "../../../components/ui/CropModal";
import {
  PanelIntro,
  StatusBanner,
  mutedSectionCardClass,
} from "../../../components/ui/panelPrimitives";
import type {
  WorkshopImageHandoff,
  WorkshopModuleProps,
  WorkshopPickedImage,
  WorkshopRaster,
} from "../../types";
import {
  BeadCalibrationStep,
  type BeadCalibrationDraft,
} from "./BeadCalibrationStep";
import { BeadEditorStep } from "./BeadEditorStep";
import {
  beadEditorReducer,
  createBeadEditorState,
  type BeadEditorAction,
  type BeadEditorState,
} from "./editorReducer";
import {
  calculatePhysicalSize,
  createBeadRecipeSource,
  createBeadProject,
  restoreBeadProjectFromRecipeSource,
  validateBeadProject,
} from "./project";
import {
  cropRaster,
  suggestGrid,
} from "./recognition";
import type { BeadRenderResult } from "./renderer";
import {
  BEAD_MODULE_VERSION,
  type BeadProject,
  type PatternClassification,
  type RecognitionRequest,
  type RecognitionResult,
} from "./types";
import {
  BeadWorkerClient,
  BeadWorkerClientError,
} from "./workerClient";
import type { BeadWorkerTask } from "./workerClient";
import { BeadHandoffConfirmDialog } from "./BeadHandoffConfirmDialog";

type BeadWorkflowStage = "upload" | "calibration" | "editor";

export interface BeadProcessingEngine {
  classify(
    source: WorkshopRaster,
  ): BeadWorkerTask<PatternClassification>;
  recognize(
    request: RecognitionRequest,
  ): BeadWorkerTask<RecognitionResult>;
  render(
    project: BeadProject,
    compression: number,
    pixelsPerCell: number,
  ): BeadWorkerTask<BeadRenderResult>;
  cancelBefore(requestId: number): void;
  cancel(requestId: number): void;
  dispose(): void;
}

interface BeadWorkshopModuleProps extends WorkshopModuleProps {
  createEngine?: () => BeadProcessingEngine;
  autosaveDelayMs?: number;
}

function defaultEngine(): BeadProcessingEngine {
  return new BeadWorkerClient();
}

function generatedProjectId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `bead-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function draftForRaster(
  source: WorkshopRaster,
  mode: BeadCalibrationDraft["inputMode"],
): BeadCalibrationDraft {
  const suggestion = suggestGrid(source, mode);
  return {
    inputMode: mode,
    rows: suggestion.rows,
    columns: suggestion.columns,
    geometry: suggestion.geometry,
    orientation: {
      rotation: 0,
      flipHorizontal: false,
      flipVertical: false,
    },
    emptySelection: null,
    transparentSupportSampleCellIndex: null,
  };
}

function normalizedCrop(
  source: WorkshopRaster,
  crop: CropData,
): CropData {
  const x = Math.min(
    source.width - 1,
    Math.max(0, Math.round(crop.x)),
  );
  const y = Math.min(
    source.height - 1,
    Math.max(0, Math.round(crop.y)),
  );
  return {
    x,
    y,
    width: Math.min(
      source.width - x,
      Math.max(1, Math.round(crop.width)),
    ),
    height: Math.min(
      source.height - y,
      Math.max(1, Math.round(crop.height)),
    ),
  };
}

function isCancellation(error: unknown): boolean {
  return (
    error instanceof BeadWorkerClientError &&
    error.code === "request-cancelled"
  );
}

export function BeadWorkshopModule({
  manifest,
  host,
  pendingRecipeSource,
  clearPendingRecipe,
  createEngine = defaultEngine,
  autosaveDelayMs = 250,
}: BeadWorkshopModuleProps) {
  const t = host.ui.translate;
  const locale = host.ui.getLocale();
  const [stage, setStage] =
    useState<BeadWorkflowStage>("upload");
  const [isPicking, setIsPicking] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [visibleError, setVisibleError] =
    useState<string | null>(null);
  const [classification, setClassification] =
    useState<PatternClassification | null>(null);
  const [calibrationDraft, setCalibrationDraft] =
    useState<BeadCalibrationDraft | null>(null);
  const [originalRaster, setOriginalRaster] =
    useState<WorkshopRaster | null>(null);
  const [workingRaster, setWorkingRaster] =
    useState<WorkshopRaster | null>(null);
  const [sourceBlob, setSourceBlob] = useState<Blob | null>(null);
  const [sourceFileName, setSourceFileName] = useState("");
  const [sourceMimeType, setSourceMimeType] = useState("");
  const [crop, setCrop] = useState<CropData | null>(null);
  const [cropOpen, setCropOpen] = useState(false);
  const [sourceUrl, setSourceUrl] = useState<string | null>(null);
  const [editorState, setEditorState] =
    useState<BeadEditorState | null>(null);
  const [renderResult, setRenderResult] =
    useState<BeadRenderResult | null>(null);
  const [renderBusy, setRenderBusy] = useState(false);
  const [handoffBusy, setHandoffBusy] = useState(false);
  const [pendingHandoff, setPendingHandoff] =
    useState<WorkshopImageHandoff | null>(null);
  const [resumed, setResumed] = useState(false);
  const engineRef = useRef<BeadProcessingEngine | null>(null);
  const latestProjectRef = useRef<BeadProject | null>(null);
  const interactionStartedRef = useRef(false);
  const editorProject = editorState?.present ?? null;

  const getEngine = useCallback(() => {
    engineRef.current ??= createEngine();
    return engineRef.current;
  }, [createEngine]);

  const dispatchEditor = useCallback(
    (action: BeadEditorAction) => {
      setEditorState((current) =>
        current ? beadEditorReducer(current, action) : current,
      );
    },
    [],
  );

  const reportProcessingError = useCallback(
    (code: string) => {
      const message = t("workshop.bead.processingError");
      setVisibleError(message);
      host.status.reportError({
        code,
        message,
        retryable: true,
      });
    },
    [host.status, t],
  );

  const saveProject = useCallback(
    async (project: BeadProject) => {
      try {
        await host.projects.save({
          projectId: project.projectId,
          schemaVersion: project.schemaVersion,
          createdAt: project.createdAt,
          updatedAt: project.updatedAt,
          project,
        });
      } catch {
        const message = t("workshop.bead.saveError");
        setVisibleError(message);
        host.status.reportError({
          code: "project-save-failed",
          message,
          retryable: true,
        });
      }
    },
    [host.projects, host.status, t],
  );

  useEffect(() => {
    if (!sourceBlob || typeof URL.createObjectURL !== "function") {
      setSourceUrl(null);
      return;
    }
    const url = URL.createObjectURL(sourceBlob);
    setSourceUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [sourceBlob]);

  useEffect(() => {
    let cancelled = false;
    const restore = async () => {
      try {
        let project: BeadProject | null = null;
        if (pendingRecipeSource) {
          project = restoreBeadProjectFromRecipeSource(
            pendingRecipeSource,
          );
          clearPendingRecipe();
        } else {
          const latest =
            await host.projects.latest<BeadProject>();
          project = latest
            ? validateBeadProject(latest.project)
            : null;
        }
        if (
          cancelled ||
          interactionStartedRef.current ||
          !project
        ) {
          return;
        }
        setEditorState(createBeadEditorState(project));
        setStage("editor");
        setResumed(true);
        latestProjectRef.current = project;
        if (project.source) {
          setSourceBlob(project.source.blob);
          setSourceFileName(project.source.fileName);
          setSourceMimeType(project.source.mimeType);
          try {
            const decoded = await host.files.decodeImage(
              project.source.blob,
            );
            if (cancelled) {
              return;
            }
            setOriginalRaster(decoded);
            setCrop(project.calibration.crop);
            setWorkingRaster(
              project.calibration.crop
                ? cropRaster(decoded, project.calibration.crop)
                : decoded,
            );
          } catch {
            setOriginalRaster(null);
            setWorkingRaster(null);
          }
        }
      } catch {
        if (!cancelled) {
          reportProcessingError("project-restore-failed");
          clearPendingRecipe();
        }
      }
    };
    void restore();
    return () => {
      cancelled = true;
    };
  }, [
    clearPendingRecipe,
    host.files,
    host.projects,
    pendingRecipeSource,
    reportProcessingError,
  ]);

  useEffect(() => {
    latestProjectRef.current = editorProject;
    if (!editorProject) {
      return;
    }
    const timer = window.setTimeout(() => {
      void saveProject(editorProject);
    }, autosaveDelayMs);
    return () => window.clearTimeout(timer);
  }, [autosaveDelayMs, editorProject, saveProject]);

  useEffect(
    () => () => {
      engineRef.current?.dispose();
      const latest = latestProjectRef.current;
      if (latest) {
        void saveProject(latest);
      }
    },
    [saveProject],
  );

  useEffect(() => {
    if (!editorProject) {
      setRenderResult(null);
      setRenderBusy(false);
      return;
    }
    let cancelled = false;
    const engine = getEngine();
    const project = editorProject;
    const previewTask = engine.render(
      project,
      project.compression,
      12,
    );
    engine.cancelBefore(previewTask.id);
    setRenderBusy(true);
    previewTask.promise
      .then((result) => {
        if (!cancelled) {
          setRenderResult(result);
        }
      })
      .catch((error) => {
        if (!cancelled && !isCancellation(error)) {
          reportProcessingError("preview-render-failed");
        }
      });

    let fullTask: BeadWorkerTask<BeadRenderResult> | null = null;
    const timer = window.setTimeout(() => {
      if (cancelled) {
        return;
      }
      fullTask = engine.render(project, project.compression, 32);
      engine.cancelBefore(fullTask.id);
      fullTask.promise
        .then((result) => {
          if (!cancelled) {
            setRenderResult(result);
            setRenderBusy(false);
          }
        })
        .catch((error) => {
          if (!cancelled && !isCancellation(error)) {
            setRenderBusy(false);
            reportProcessingError("full-render-failed");
          }
        });
    }, 180);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      engine.cancel(previewTask.id);
      if (fullTask) {
        engine.cancel(fullTask.id);
      }
    };
  }, [
    editorProject,
    getEngine,
    reportProcessingError,
  ]);

  useEffect(() => {
    if (!editorProject) {
      return;
    }
    const project = editorProject;
    host.status.reportDiagnostics({
      projectSchemaVersion: project.schemaVersion,
      inputMode: project.calibration.inputMode,
      rows: project.rows,
      columns: project.columns,
      compression: project.compression,
      errorCode: null,
    });
  }, [editorProject, host.status]);

  const preparePickedImage = async (
    picked: WorkshopPickedImage,
  ) => {
    setOriginalRaster(picked.raster);
    setWorkingRaster(picked.raster);
    setSourceBlob(picked.file);
    setSourceFileName(picked.file.name);
    setSourceMimeType(picked.file.type);
    setCrop(null);
    setClassification(null);
    setCalibrationDraft(
      draftForRaster(picked.raster, "hard-pixel"),
    );
    setStage("calibration");
    setIsProcessing(true);

    try {
      const engine = getEngine();
      const task = engine.classify(picked.raster);
      engine.cancelBefore(task.id);
      const result = await task.promise;
      setClassification(result);
      const mode =
        result.mode === "ambiguous" ? "hard-pixel" : result.mode;
      setCalibrationDraft(draftForRaster(picked.raster, mode));
    } catch (error) {
      if (!isCancellation(error)) {
        reportProcessingError("pattern-classification-failed");
      }
    } finally {
      setIsProcessing(false);
      host.status.reportProgress(null);
    }
  };

  const handlePickImage = async () => {
    interactionStartedRef.current = true;
    setIsPicking(true);
    setVisibleError(null);
    setResumed(false);
    host.status.reportProgress({
      phase: "pick-image",
      completed: 0,
      total: 1,
    });
    try {
      const picked = await host.files.pickImage();
      if (picked) {
        await preparePickedImage(picked);
      } else {
        host.status.reportProgress(null);
      }
    } catch {
      const message = t("workshop.bead.pickerError");
      setVisibleError(message);
      host.status.reportError({
        code: "image-pick-failed",
        message,
        retryable: true,
      });
      host.status.reportProgress(null);
    } finally {
      setIsPicking(false);
    }
  };

  const handleCalibrationChange = (
    next: BeadCalibrationDraft,
  ) => {
    if (
      workingRaster &&
      calibrationDraft &&
      next.inputMode !== calibrationDraft.inputMode
    ) {
      setCalibrationDraft(
        draftForRaster(workingRaster, next.inputMode),
      );
      return;
    }
    setCalibrationDraft(next);
  };

  const applyCrop = (nextCrop: CropData | null) => {
    if (!originalRaster) {
      return;
    }
    const nextRaster = nextCrop
      ? cropRaster(originalRaster, nextCrop)
      : originalRaster;
    setCrop(nextCrop);
    setWorkingRaster(nextRaster);
    setCalibrationDraft(
      draftForRaster(
        nextRaster,
        calibrationDraft?.inputMode ?? "hard-pixel",
      ),
    );
    setCropOpen(false);
  };

  const handleRecognize = async () => {
    if (!workingRaster || !calibrationDraft) {
      return;
    }
    setIsProcessing(true);
    setVisibleError(null);
    host.status.reportProgress({
      phase: "recognize-pattern",
      completed: 0,
      total: 1,
    });
    try {
      const engine = getEngine();
      const task = engine.recognize({
        source: workingRaster,
        mode: calibrationDraft.inputMode,
        rows: calibrationDraft.rows,
        columns: calibrationDraft.columns,
        geometry: calibrationDraft.geometry,
        emptySelection:
          calibrationDraft.emptySelection ?? { kind: "none" },
        transparentSupportSampleCellIndex:
          calibrationDraft.transparentSupportSampleCellIndex,
        orientation: calibrationDraft.orientation,
      });
      engine.cancelBefore(task.id);
      const result = await task.promise;
      const now = new Date().toISOString();
      const project = createBeadProject({
        projectId: generatedProjectId(),
        moduleVersion: BEAD_MODULE_VERSION,
        now,
        rows: result.rows,
        columns: result.columns,
        palette:
          result.palette.length > 0
            ? result.palette
            : [[0, 0, 0]],
        cells: result.cells,
        source:
          sourceBlob && originalRaster
            ? {
                fileName: sourceFileName,
                mimeType:
                  sourceMimeType || "application/octet-stream",
                blob: sourceBlob,
                pixelWidth: originalRaster.width,
                pixelHeight: originalRaster.height,
              }
            : null,
        calibration: {
          inputMode: result.mode,
          crop,
          origin: {
            x: calibrationDraft.geometry.originX,
            y: calibrationDraft.geometry.originY,
          },
          orientation: calibrationDraft.orientation,
          emptySelection:
            calibrationDraft.emptySelection ?? { kind: "none" },
          transparentSupportSampleCellIndex:
            calibrationDraft.transparentSupportSampleCellIndex,
        },
        confidenceIssues: result.confidenceIssues,
      });
      setEditorState(createBeadEditorState(project));
      setStage("editor");
      setResumed(false);
      latestProjectRef.current = project;
      host.status.reportProgress(null);
    } catch (error) {
      if (!isCancellation(error)) {
        reportProcessingError("pattern-recognition-failed");
      }
      host.status.reportProgress(null);
    } finally {
      setIsProcessing(false);
    }
  };

  const reportHandoffError = () => {
    const message = t("workshop.bead.handoffError");
    setVisibleError(message);
    host.status.reportError({
      code: "bead-handoff-failed",
      message,
      retryable: true,
    });
  };

  const handleHandoff = async () => {
    const project = editorState?.present;
    if (
      !project ||
      !project.cells.some((cell) => cell.kind === "color")
    ) {
      reportHandoffError();
      return;
    }

    setHandoffBusy(true);
    setVisibleError(null);
    host.status.reportProgress({
      phase: "render-handoff",
      completed: 0,
      total: 1,
    });
    try {
      const engine = getEngine();
      const task = engine.render(project, project.compression, 32);
      engine.cancelBefore(task.id);
      const raster = await task.promise;
      const file = await host.files.encodePng(
        raster,
        `bead-${project.projectId}.png`,
      );
      const size = calculatePhysicalSize(
        project,
        project.beadPitchMm,
      );
      const handoff: WorkshopImageHandoff = {
        moduleId: project.moduleId,
        moduleVersion: project.moduleVersion,
        projectId: project.projectId,
        file,
        pixelWidth: raster.width,
        pixelHeight: raster.height,
        recommendedWidthMm: size.widthMm,
        recommendedHeightMm: size.heightMm,
        rows: project.rows,
        columns: project.columns,
        beadPitchMm: project.beadPitchMm,
        preserveCanvasBounds: true,
        recipeSource: createBeadRecipeSource(project),
      };
      const result = await host.handoffImage(handoff);
      setPendingHandoff(
        result.status === "needs-confirmation" ? handoff : null,
      );
    } catch (error) {
      if (!isCancellation(error)) {
        reportHandoffError();
      }
    } finally {
      setHandoffBusy(false);
      host.status.reportProgress(null);
    }
  };

  const confirmHandoff = async () => {
    if (!pendingHandoff) {
      return;
    }
    setHandoffBusy(true);
    setVisibleError(null);
    try {
      await host.handoffImage(pendingHandoff, {
        replaceExisting: true,
      });
      setPendingHandoff(null);
    } catch {
      reportHandoffError();
    } finally {
      setHandoffBusy(false);
    }
  };

  const handleNewProject = () => {
    const latest = latestProjectRef.current;
    if (latest) {
      void saveProject(latest);
    }
    engineRef.current?.cancelBefore(Number.MAX_SAFE_INTEGER);
    interactionStartedRef.current = true;
    setEditorState(null);
    setStage("upload");
    setClassification(null);
    setCalibrationDraft(null);
    setOriginalRaster(null);
    setWorkingRaster(null);
    setSourceBlob(null);
    setSourceFileName("");
    setSourceMimeType("");
    setCrop(null);
    setRenderResult(null);
    setPendingHandoff(null);
    setHandoffBusy(false);
    setVisibleError(null);
    setResumed(false);
    latestProjectRef.current = null;
  };

  return (
    <div className="mx-auto flex w-full max-w-[96rem] flex-col gap-5">
      {visibleError && (
        <StatusBanner tone="error">{visibleError}</StatusBanner>
      )}
      {resumed && stage === "editor" && (
        <StatusBanner tone="success">
          {t("workshop.bead.resumeReady")}
        </StatusBanner>
      )}

      {stage === "upload" && (
        <>
          <PanelIntro
            eyebrow={t("workshop.official")}
            title={manifest.name[locale]}
            description={t("workshop.bead.intro")}
          />
          <section
            className={`${mutedSectionCardClass} flex flex-col gap-4`}
          >
            <div className="flex flex-col gap-1">
              <p className="text-sm font-medium text-slate-800 dark:text-slate-100">
                {t("workshop.bead.supportedInputs")}
              </p>
              <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
                {t("workshop.bead.localPrivacy")}
              </p>
            </div>
            <Button
              label={t("workshop.bead.choosePattern")}
              loading={isPicking}
              onClick={handlePickImage}
              className="self-start"
            />
          </section>
        </>
      )}

      {stage === "calibration" &&
        workingRaster &&
        calibrationDraft && (
          <BeadCalibrationStep
            source={workingRaster}
            fileName={sourceFileName}
            classification={classification}
            draft={calibrationDraft}
            busy={isProcessing}
            translate={t}
            onChange={handleCalibrationChange}
            onRecognize={handleRecognize}
            onOpenCrop={() => setCropOpen(true)}
            canCrop={Boolean(sourceUrl)}
          />
        )}

      {stage === "editor" && editorState && (
        <BeadEditorStep
          state={editorState}
          renderResult={renderResult}
          renderBusy={renderBusy}
          sourceRaster={workingRaster}
          translate={t}
          dispatch={dispatchEditor}
          onNewProject={handleNewProject}
          onHandoff={handleHandoff}
          handoffBusy={handoffBusy}
        />
      )}

      <BeadHandoffConfirmDialog
        open={pendingHandoff !== null}
        busy={handoffBusy}
        translate={t}
        onCancel={() => setPendingHandoff(null)}
        onConfirm={confirmHandoff}
      />

      {sourceUrl && (
        <CropModal
          open={cropOpen}
          imageSrc={sourceUrl}
          onConfirm={(cropData) =>
            applyCrop(
              normalizedCrop(
                originalRaster ?? workingRaster!,
                cropData,
              ),
            )
          }
          onUseOriginal={() => applyCrop(null)}
          onClose={() => setCropOpen(false)}
        />
      )}
    </div>
  );
}
