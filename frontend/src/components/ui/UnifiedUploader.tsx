import { useState, useRef, useCallback } from "react";
import { useI18n } from "../../i18n/context";
import { isShareCardFile } from "../../recipe/importFlow";
import { ArrowPathIcon, PlusIcon } from "@heroicons/react/24/outline";
import Button from "./Button";
import { useApplicationMenuCommand } from "../../integrations/applicationMenu";

const VISIBLE_BATCH_FILE_LIMIT = 40;
interface UnifiedUploaderProps {
  /** 当前单图模式的预览 URL */
  singlePreview?: string;
  /** 批量模式下的文件列表 */
  batchFiles: File[];
  /** 是否处于批量模式 */
  isBatchMode: boolean;
  /** 处理文件选择（单张或多张） */
  onFilesSelect: (files: File[]) => void;
  /** 替换当前单图 */
  onFileReplace?: (file: File) => void;
  /** 删除批量文件 */
  onBatchFileRemove: (index: number) => void;
  /** 接受的文件格式 */
  accept: string;
  /** Called when a share card or .lumina.json file is detected */
  onShareCardDetected?: (file: File) => void;
}

export default function UnifiedUploader({
  singlePreview,
  batchFiles,
  isBatchMode,
  onFilesSelect,
  onFileReplace,
  onBatchFileRemove,
  accept,
  onShareCardDetected,
}: UnifiedUploaderProps) {
  const { t } = useI18n();
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const addMoreInputRef = useRef<HTMLInputElement>(null);
  const acceptedFormats = onShareCardDetected ? `${accept},.json` : accept;
  useApplicationMenuCommand('import', () => {
    (isBatchMode ? addMoreInputRef.current : inputRef.current)?.click();
  });

  /**
   * Check files for share cards before passing to normal handler.
   * If a single file is a share card (.lumina.json or PNG with recipe), route it.
   */
  const filterShareCards = useCallback(
    async (files: File[], mode: "select" | "replace" = "select") => {
      if (files.length === 1 && onShareCardDetected) {
        const file = files[0];
        const name = file.name.toLowerCase();
        // Fast path: .lumina.json is always a share card
        if (name.endsWith(".lumina.json")) {
          onShareCardDetected(file);
          return;
        }
        // Validate renamed JSON projects or embedded PNG recipes.
        if (name.endsWith(".png") || name.endsWith(".json")) {
          try {
            const isCard = await isShareCardFile(file);
            if (isCard) {
              onShareCardDetected(file);
              return;
            }
          } catch {
            // Detection failed — treat as normal file
          }
        }
      }
      if (mode === "replace" && files[0] && onFileReplace) {
        onFileReplace(files[0]);
        return;
      }
      // Not a share card — pass through normally
      onFilesSelect(files);
    },
    [onFileReplace, onFilesSelect, onShareCardDetected],
  );

  const handleDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) {
        void filterShareCards(files);
      }
    },
    [filterShareCards],
  );

  const handleReplaceDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) {
        void filterShareCards(files, "replace");
      }
    },
    [filterShareCards],
  );

  const handleClick = useCallback(() => {
    inputRef.current?.click();
  }, []);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files ?? []);
      if (files.length > 0) {
        void filterShareCards(files);
      }
      e.target.value = "";
    },
    [filterShareCards],
  );

  const handleReplaceChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files ?? []);
      if (files.length > 0) {
        void filterShareCards(files, "replace");
      }
      e.target.value = "";
    },
    [filterShareCards],
  );

  const handleAddMoreClick = useCallback(() => {
    addMoreInputRef.current?.click();
  }, []);

  const handleAddMoreChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files ?? []);
      if (files.length > 0) {
        void filterShareCards(files);
      }
      e.target.value = "";
    },
    [filterShareCards],
  );

  const borderClass = isDragging
    ? "border-blue-500 bg-blue-500/10"
    : "border-slate-300/80 dark:border-slate-600/80 border-dashed";

  // BatchMode: file list + "add more" area
  if (isBatchMode && batchFiles.length > 0) {
    const visibleBatchFiles = batchFiles.slice(0, VISIBLE_BATCH_FILE_LIMIT);
    const hiddenBatchFileCount = Math.max(0, batchFiles.length - visibleBatchFiles.length);

    return (
      <div className="flex flex-col gap-2">
        {/* File count */}
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {t("upload_file_count").replace("{count}", String(batchFiles.length))}
        </p>

        {/* File list: plain rows, hairlines instead of a box per file */}
        <ul
          className="flex max-h-64 flex-col overflow-y-auto pr-1"
          aria-label={t("upload_file_list_label")}
        >
          {visibleBatchFiles.map((file, index) => (
            <li
              key={`${file.name}-${index}`}
              className="flex items-center justify-between gap-2 border-t border-[color:var(--surface-divider)] px-2 py-1.5 text-sm text-slate-700 first:border-t-0 dark:text-slate-200"
            >
              <span className="truncate">{file.name}</span>
              <button
                type="button"
                aria-label={t("upload_delete_file").replace("{name}", file.name)}
                onClick={() => onBatchFileRemove(index)}
                className="ghost-control shrink-0 rounded-md p-1 text-slate-400"
                data-tone="danger"
              >
                ✕
              </button>
            </li>
          ))}
          {hiddenBatchFileCount > 0 && (
            <li className="border-t border-[color:var(--surface-divider)] px-2 py-1.5 text-xs text-slate-500 dark:text-slate-400">
              {t("upload_file_list_truncated").replace(
                "{count}",
                String(hiddenBatchFileCount),
              )}
            </li>
          )}
        </ul>

        {/* Add more area */}
        <div
          data-unified-uploader-drop-zone="true"
          role="button"
          tabIndex={0}
          aria-label={t("upload_add_more")}
          onClick={handleAddMoreClick}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") handleAddMoreClick();
          }}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={`flex min-h-[60px] items-center justify-center rounded-[10px] border-2 cursor-pointer transition-colors ${borderClass}`}
        >
          <input
            ref={addMoreInputRef}
            type="file"
            accept={acceptedFormats}
            multiple
            onChange={handleAddMoreChange}
            className="hidden"
            aria-hidden="true"
          />
          <span className="text-sm text-slate-500 dark:text-slate-400 select-none">
            {t("upload_add_more")}
          </span>
        </div>
      </div>
    );
  }

  if (singlePreview) {
    return (
      <div className="flex flex-col gap-2">
        <div
          data-unified-uploader-drop-zone="true"
          role="button"
          tabIndex={0}
          aria-label={t("upload_replace_current")}
          onClick={handleClick}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") handleClick();
          }}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleReplaceDrop}
          className={`flex min-h-[120px] items-center justify-center rounded-[10px] border-2 cursor-pointer transition-colors ${borderClass}`}
        >
          <input
            ref={inputRef}
            type="file"
            accept={acceptedFormats}
            onChange={handleReplaceChange}
            className="hidden"
            aria-hidden="true"
          />
          <div className="flex w-full items-center justify-center rounded-[10px] p-2 bg-[length:16px_16px] bg-[image:linear-gradient(45deg,_#e0e0e0_25%,_transparent_25%),linear-gradient(-45deg,_#e0e0e0_25%,_transparent_25%),linear-gradient(45deg,_transparent_75%,_#e0e0e0_75%),linear-gradient(-45deg,_transparent_75%,_#e0e0e0_75%)] dark:bg-[image:linear-gradient(45deg,_#374151_25%,_transparent_25%),linear-gradient(-45deg,_#374151_25%,_transparent_25%),linear-gradient(45deg,_transparent_75%,_#374151_75%),linear-gradient(-45deg,_transparent_75%,_#374151_75%)] bg-[position:0_0,0_8px,8px_-8px,-8px_0px]">
            <img
              src={singlePreview}
              alt={t("common_preview_alt")}
              className="block max-w-full rounded-[10px] object-contain"
              style={{ maxHeight: "clamp(10rem, 22vh, 18rem)" }}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <Button
            label={t("upload_replace_current")}
            variant="secondary"
            size="sm"
            leadingIcon={<ArrowPathIcon className="size-4" />}
            onClick={handleClick}
          />
          <Button
            label={t("upload_add_more")}
            variant="secondary"
            size="sm"
            leadingIcon={<PlusIcon className="size-4" />}
            onClick={handleAddMoreClick}
          />
          <input
            ref={addMoreInputRef}
            type="file"
            accept={acceptedFormats}
            multiple
            onChange={handleAddMoreChange}
            className="hidden"
            aria-hidden="true"
          />
        </div>
      </div>
    );
  }

  // Empty state or SingleMode: main drop zone
  return (
    <div
      data-unified-uploader-drop-zone="true"
      role="button"
      tabIndex={0}
      aria-label={t("upload_unified_aria")}
      onClick={handleClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") handleClick();
      }}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={`flex min-h-[120px] items-center justify-center rounded-[10px] border-2 px-4 py-5 text-center cursor-pointer transition-colors ${borderClass}`}
    >
      <input
        ref={inputRef}
        type="file"
        accept={acceptedFormats}
        multiple
        onChange={handleChange}
        className="hidden"
        aria-hidden="true"
      />
      <span className="min-w-0 text-sm leading-relaxed text-slate-500 dark:text-slate-400 select-none">
        <span className="block text-balance">{t("upload_unified_hint")}</span>
        <span className="mt-1 block text-balance">{t("upload_unified_multiselect_hint")}</span>
      </span>
    </div>
  );
}
