/**
 * Global converter drop routing shared by the whole converter tab.
 * 整个图像转换页共享的全局拖放导入路由。
 *
 * Mounted once at the WidgetWorkspace level so STL/OBJ → model-texture
 * upload and image → image upload keep working even when every dock
 * widget (including the model texture panel itself) is hidden, because
 * WidgetPanel unmounts invisible widgets and would otherwise detach the
 * window listeners.
 * 在 WidgetWorkspace 层级挂载一次：即使所有 dock 面板（包括模型贴图面板）
 * 被隐藏（WidgetPanel 会卸载不可见面板），窗口级 STL/OBJ → 模型贴图上传、
 * 图片 → 图片导入依然可用。
 */

import { useCallback, useEffect, useState } from "react";
import { isValidImageType, useConverterStore } from "../stores/converter";
import { useI18n } from "../i18n/context";

const MODEL_SURFACE_FILE_EXTENSIONS = [".stl", ".obj"] as const;

export type ConverterDropImportIntent = "model" | "image" | "mixed" | "files";

/** STL/OBJ files route to the model texture upload flow. STL/OBJ 文件走模型贴图上传。 */
export function isSupportedModelSurfaceFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return MODEL_SURFACE_FILE_EXTENSIONS.some((extension) => name.endsWith(extension));
}

function getDropImportIntent(files: File[]): ConverterDropImportIntent | null {
  if (files.length === 0) {
    return "files";
  }
  const hasModel = files.some(isSupportedModelSurfaceFile);
  const hasImage = files.some((file) => isValidImageType(file.type, file.name));
  if (hasModel && hasImage) {
    return "mixed";
  }
  if (hasModel) {
    return "model";
  }
  if (hasImage) {
    return "image";
  }
  return null;
}

function hasDraggedFiles(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes("Files");
}

function isInsideUnifiedUploaderDropZone(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest("[data-unified-uploader-drop-zone='true']"));
}

function isInsideModelSurfaceDropZone(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest("[data-model-surface-drop-zone='true']"));
}

function isInsideLocalFileDropZone(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest("[data-local-file-drop-zone='true']"));
}

/**
 * Route window-level drops for the converter tab and report the current
 * drag intent for the floating hint banner.
 * 路由转换页的窗口级拖放，并返回当前拖拽意图供浮动提示条展示。
 */
export function useConverterDropRouting(): { dropImportIntent: ConverterDropImportIntent | null } {
  const [dropImportIntent, setDropImportIntent] = useState<ConverterDropImportIntent | null>(null);
  const handleFilesSelect = useConverterStore((s) => s.handleFilesSelect);
  const uploadModelSurfaceFile = useConverterStore((s) => s.uploadModelSurfaceFile);

  const importDroppedFiles = useCallback(
    (files: File[]): boolean => {
      const modelFile = files.find(isSupportedModelSurfaceFile);
      const imageFiles = files.filter((file) => isValidImageType(file.type, file.name));

      if (!modelFile && imageFiles.length === 0) {
        return false;
      }

      if (imageFiles.length > 0) {
        handleFilesSelect(imageFiles);
      }
      if (modelFile) {
        void uploadModelSurfaceFile(modelFile);
      }
      return true;
    },
    [handleFilesSelect, uploadModelSurfaceFile],
  );

  const handleDroppedFiles = useCallback(
    (files: File[], target: EventTarget | null): boolean => {
      const modelFile = files.find(isSupportedModelSurfaceFile);
      const imageFiles = files.filter((file) => isValidImageType(file.type, file.name));

      if (!modelFile && isInsideLocalFileDropZone(target)) {
        return false;
      }

      if (!modelFile && imageFiles.length === 0) {
        return false;
      }

      if (!modelFile && imageFiles.length > 0 && isInsideUnifiedUploaderDropZone(target)) {
        return false;
      }

      if (isInsideModelSurfaceDropZone(target)) {
        return false;
      }

      return importDroppedFiles(files);
    },
    [importDroppedFiles],
  );

  useEffect(() => {
    const handleWindowDragOver = (event: DragEvent) => {
      if (!hasDraggedFiles(event)) return;
      const intent = getDropImportIntent(Array.from(event.dataTransfer?.files ?? []));
      if (isInsideLocalFileDropZone(event.target) && intent !== "model" && intent !== "mixed") {
        setDropImportIntent(null);
        return;
      }
      setDropImportIntent(intent);
      event.preventDefault();
    };
    const handleWindowDragLeave = (event: DragEvent) => {
      if (event.target === window || event.target === document || event.target === document.documentElement) {
        setDropImportIntent(null);
      }
    };
    const handleWindowDrop = (event: DragEvent) => {
      const files = Array.from(event.dataTransfer?.files ?? []);
      setDropImportIntent(null);
      if (!handleDroppedFiles(files, event.target)) return;
      event.preventDefault();
      event.stopPropagation();
    };

    window.addEventListener("dragover", handleWindowDragOver, true);
    window.addEventListener("dragleave", handleWindowDragLeave, true);
    window.addEventListener("drop", handleWindowDrop, true);
    return () => {
      window.removeEventListener("dragover", handleWindowDragOver, true);
      window.removeEventListener("dragleave", handleWindowDragLeave, true);
      window.removeEventListener("drop", handleWindowDrop, true);
    };
  }, [handleDroppedFiles]);

  return { dropImportIntent };
}

/**
 * Floating hint banner shown while files are dragged over the converter tab.
 * 拖拽文件悬停在转换页上时显示的浮动提示条。
 */
export function ConverterDropIntentBanner({
  intent,
}: {
  intent: ConverterDropImportIntent | null;
}) {
  const { t } = useI18n();
  if (!intent) return null;

  const label =
    intent === "model"
      ? t("global_drop_import_model")
      : intent === "image"
        ? t("global_drop_import_image")
        : intent === "mixed"
          ? t("global_drop_import_mixed")
          : t("global_drop_import_files");

  return (
    <div
      role="status"
      aria-label={t("global_drop_import_aria")}
      className="pointer-events-none fixed inset-x-0 top-4 z-[80] flex justify-center px-4"
    >
      <div className="flex max-w-[min(32rem,calc(100vw-2rem))] items-center gap-3 rounded-md border border-blue-300/80 bg-slate-100/94 px-4 py-3 text-sm font-semibold text-slate-800 shadow-xl backdrop-blur-md dark:border-blue-500/50 dark:bg-slate-950/90 dark:text-slate-100">
        <span className="inline-flex size-2.5 rounded-full bg-blue-500 shadow-[0_0_0_4px_rgba(59,130,246,0.16)]" />
        <span>{label}</span>
        <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
          {t("global_drop_import_release")}
        </span>
      </div>
    </div>
  );
}
