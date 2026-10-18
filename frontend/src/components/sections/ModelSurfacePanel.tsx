/**
 * Model texture panel extracted from BasicSettings into its own widget.
 * 从基础设置拆分为独立 Widget 的模型贴图面板。
 *
 * Store-driven like before: enabling forces single-sided structure in the
 * converter store and BasicSettings hides its backing-infill slider and
 * structure selector while this flag is on.
 * 与原先一致，由 store 驱动：开启后转换 store 强制单面结构，
 * 基础设置中的背衬填充密度滑条与结构模式选择器随之隐藏。
 */

import { useCallback, useMemo, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { isValidImageType, useConverterStore } from "../../stores/converter";
import Checkbox from "../ui/Checkbox";
import { StatusBanner } from "../ui/panelPrimitives";
import { useI18n } from "../../i18n/context";
import { isSupportedModelSurfaceFile } from "../../hooks/useConverterDropRouting";

export default function ModelSurfacePanel() {
  const { t } = useI18n();
  const [dropActive, setDropActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const {
    modelSurfaceEnabled,
    modelSurfaceFile,
    modelSurfaceModelFileId,
    modelSurfaceSummary,
    modelSurfaceSelectionId,
    modelSurfaceSelection,
    modelSurfaceFootprint,
    modelSurfaceLoading,
    modelSurfaceSelecting,
    modelSurfaceError,
    modelSurfaceWarnings,
    setModelSurfaceEnabled,
    uploadModelSurfaceFile,
    clearModelSurface,
    handleFilesSelect,
  } = useConverterStore(useShallow((s) => ({
    modelSurfaceEnabled: s.modelSurfaceEnabled,
    modelSurfaceFile: s.modelSurfaceFile,
    modelSurfaceModelFileId: s.modelSurfaceModelFileId,
    modelSurfaceSummary: s.modelSurfaceSummary,
    modelSurfaceSelectionId: s.modelSurfaceSelectionId,
    modelSurfaceSelection: s.modelSurfaceSelection,
    modelSurfaceFootprint: s.modelSurfaceFootprint,
    modelSurfaceLoading: s.modelSurfaceLoading,
    modelSurfaceSelecting: s.modelSurfaceSelecting,
    modelSurfaceError: s.modelSurfaceError,
    modelSurfaceWarnings: s.modelSurfaceWarnings,
    setModelSurfaceEnabled: s.setModelSurfaceEnabled,
    uploadModelSurfaceFile: s.uploadModelSurfaceFile,
    clearModelSurface: s.clearModelSurface,
    handleFilesSelect: s.handleFilesSelect,
  })));

  const extentsLabel = useMemo(() => {
    const extents = modelSurfaceSummary?.extents_mm;
    if (!extents) return null;
    return extents.map((value) => `${value.toFixed(1)}`).join(" × ");
  }, [modelSurfaceSummary?.extents_mm]);
  const footprintLabel = useMemo(() => {
    const width = modelSurfaceFootprint?.bounds_width_mm;
    const height = modelSurfaceFootprint?.bounds_height_mm;
    if (typeof width !== "number" || typeof height !== "number") return null;
    return `${width.toFixed(1)} × ${height.toFixed(1)} mm`;
  }, [modelSurfaceFootprint]);
  const faceCount =
    typeof modelSurfaceSelection?.face_count === "number"
      ? modelSurfaceSelection.face_count
      : null;
  const statusLabel = modelSurfaceLoading
    ? t("model_surface_status_uploading")
    : modelSurfaceSelecting
      ? t("model_surface_status_selecting")
      : modelSurfaceError && !modelSurfaceModelFileId
        ? t("model_surface_status_analysis_failed")
        : modelSurfaceSelectionId
          ? t("model_surface_status_selected")
          : t("model_surface_status_select_face");
  const dropZoneLabel = modelSurfaceFile
    ? t("model_surface_drop_zone_replace")
    : t("model_surface_drop_zone_upload");
  const dropZoneClass =
    "flex min-h-[76px] cursor-pointer flex-col justify-center rounded-md border-2 border-dashed px-3 py-2 text-left transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)] " +
    (dropActive
      ? "border-blue-500 bg-blue-500/10"
      : "border-slate-300/80 bg-slate-100/60 hover:bg-slate-100/90 dark:border-slate-700 dark:bg-slate-900/50 dark:hover:bg-slate-900/80") +
    (modelSurfaceLoading ? " pointer-events-none opacity-60" : "");

  const importDroppedFiles = useCallback(
    (files: File[]) => {
      const modelFile = files.find(isSupportedModelSurfaceFile);
      const imageFiles = files.filter((file) => isValidImageType(file.type, file.name));
      if (imageFiles.length > 0) {
        handleFilesSelect(imageFiles);
      }
      if (modelFile) {
        void uploadModelSurfaceFile(modelFile);
      }
    },
    [handleFilesSelect, uploadModelSurfaceFile],
  );

  const handleUploadChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await uploadModelSurfaceFile(file);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleDropZoneClick = useCallback(() => {
    if (modelSurfaceLoading) {
      return;
    }
    fileInputRef.current?.click();
  }, [modelSurfaceLoading]);

  const handleDropZoneDragOver = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    if (!Array.from(event.dataTransfer?.types ?? []).includes("Files")) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    setDropActive(true);
  }, []);

  const handleDropZoneDragLeave = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setDropActive(false);
  }, []);

  const handleDropZoneDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.stopPropagation();
      setDropActive(false);
      if (modelSurfaceLoading) {
        return;
      }
      importDroppedFiles(Array.from(event.dataTransfer?.files ?? []));
    },
    [importDroppedFiles, modelSurfaceLoading],
  );

  return (
    <div className="flex flex-col gap-3">
      <Checkbox
        label={t("model_surface_enable")}
        tooltip={t("model_surface_enable_hint")}
        checked={modelSurfaceEnabled}
        onChange={setModelSurfaceEnabled}
      />
      {modelSurfaceEnabled && (
        <div className="flex flex-col gap-3">
          <input
            ref={fileInputRef}
            type="file"
            accept=".stl,.obj"
            className="hidden"
            onChange={(e) => void handleUploadChange(e)}
          />
          <div className="flex flex-col gap-2">
            <div
              data-model-surface-drop-zone="true"
              role="button"
              tabIndex={modelSurfaceLoading ? -1 : 0}
              aria-disabled={modelSurfaceLoading ? "true" : undefined}
              aria-label={dropZoneLabel}
              onClick={handleDropZoneClick}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  handleDropZoneClick();
                }
              }}
              onDragOver={handleDropZoneDragOver}
              onDragLeave={handleDropZoneDragLeave}
              onDrop={handleDropZoneDrop}
              className={dropZoneClass}
            >
              <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
                {dropZoneLabel}
              </span>
              <span className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                {t("model_surface_drop_zone_hint")}
              </span>
            </div>
            {modelSurfaceFile && (
              <button
                type="button"
                onClick={clearModelSurface}
                className="self-start rounded-full border border-slate-200/80 px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                {t("model_surface_clear_model")}
              </button>
            )}
          </div>

          {modelSurfaceFile && (
            <div className="grid gap-1.5 text-xs text-slate-500 dark:text-slate-400">
              <div className="flex justify-between gap-3">
                <span>{t("model_surface_model_file")}</span>
                <span className="min-w-0 truncate text-right text-slate-700 dark:text-slate-200">
                  {modelSurfaceFile.name}
                </span>
              </div>
              {extentsLabel && (
                <div className="flex justify-between gap-3">
                  <span>{t("model_surface_model_size")}</span>
                  <span className="text-slate-700 dark:text-slate-200">
                    {extentsLabel} mm
                  </span>
                </div>
              )}
              <div className="flex justify-between gap-3">
                <span>{t("model_surface_status")}</span>
                <span className="text-slate-700 dark:text-slate-200">
                  {statusLabel}
                </span>
              </div>
              {footprintLabel && (
                <div className="flex justify-between gap-3">
                  <span>{t("model_surface_selected_size")}</span>
                  <span className="text-slate-700 dark:text-slate-200">
                    {footprintLabel}
                  </span>
                </div>
              )}
              {faceCount !== null && (
                <div className="flex justify-between gap-3">
                  <span>{t("model_surface_selected_faces")}</span>
                  <span className="text-slate-700 dark:text-slate-200">
                    {faceCount}
                  </span>
                </div>
              )}
            </div>
          )}

          {modelSurfaceError && (
            <StatusBanner tone="error">{modelSurfaceError}</StatusBanner>
          )}
          {modelSurfaceWarnings.map((warning) => (
            <StatusBanner key={warning} tone="warning">
              {warning}
            </StatusBanner>
          ))}

          {modelSurfaceFile && modelSurfaceModelFileId && (
            <StatusBanner tone="info">
              {t("model_surface_adjust_in_viewer")}
            </StatusBanner>
          )}
        </div>
      )}
    </div>
  );
}
