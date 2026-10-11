const originalFiles = new WeakMap<File, File>();
const selectedFiles = new Set<File>();

/** Retain a selected/uploaded file for complete feedback capture.
 * 保留用户选择或上传的文件，用于完整工单采集。
 */
export function rememberFeedbackSource(file: File): void {
  selectedFiles.add(file);
}

/** Preserve the original source behind every derived file.
 * 记录派生文件对应的原始输入，连续变换后仍能找到原图。
 */
export function rememberDerivedImageSource(derivedFile: File, currentFile: File): void {
  originalFiles.set(derivedFile, originalFiles.get(currentFile) ?? currentFile);
  rememberFeedbackSource(currentFile);
  rememberFeedbackSource(derivedFile);
}

/** Resolve the original user input while keeping the current file available.
 * 获取用户原始输入，同时保留当前派生文件。
 */
export function resolveSourceFile(currentFile: File | null): File | null {
  return currentFile ? originalFiles.get(currentFile) ?? currentFile : null;
}

/** Return every source selected during this page session.
 * 返回当前页面会话选择过的全部源文件。
 */
export function getFeedbackSources(): File[] {
  return [...selectedFiles];
}

/** Capture file pickers and drops before local parsing can discard an input.
 * 在本地解析前捕获文件选择和拖放，避免失败后丢失原始输入。
 */
export function installFeedbackSourceCapture(): () => void {
  if (typeof document === "undefined") return () => {};
  const captureChange = (event: Event) => {
    if (event.target instanceof HTMLInputElement && event.target.type === "file") {
      for (const file of event.target.files ?? []) rememberFeedbackSource(file);
    }
  };
  const captureDrop = (event: DragEvent) => {
    for (const file of event.dataTransfer?.files ?? []) rememberFeedbackSource(file);
  };
  document.addEventListener("change", captureChange, true);
  document.addEventListener("drop", captureDrop, true);
  return () => {
    document.removeEventListener("change", captureChange, true);
    document.removeEventListener("drop", captureDrop, true);
  };
}

export function _clearFeedbackSourcesForTests(): void {
  selectedFiles.clear();
}
