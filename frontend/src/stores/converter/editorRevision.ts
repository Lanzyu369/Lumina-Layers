/**
 * Editor content revision helpers shared by generation and edit responses.
 * 生成与编辑响应共用的编辑内容版本工具函数。
 *
 * The backend advances `editor_content_revision` monotonically on every
 * committed output-affecting edit. Every value the client receives is a
 * server-confirmed snapshot, so the newest known value is always the largest.
 * 后端在每次已提交的编辑后单调递增编辑内容版本；客户端收到的每个值都是服务端
 * 确认过的快照，因此已知的最新值总是最大值。
 */

function finiteRevision(value: number | null | undefined): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

/**
 * Return the newest server-confirmed editor content revision.
 * 返回服务端已确认的最新编辑内容版本。
 *
 * A selection document can be replaced by a late GET, an optimistic
 * selection, or a history restore that still carries an older revision;
 * taking the maximum prevents such a document from rolling the value back.
 * 选区文档可能被晚到的 GET、乐观选区或历史恢复替换成旧版本；取最大值可避免回退。
 *
 * @param revisions - Candidate revisions; non-finite values are ignored.
 *   (候选版本号，非有限值会被忽略)
 * @returns The largest finite revision, or undefined when none is known.
 *   (最大的有限版本号；都未知时返回 undefined)
 */
export function newestEditorContentRevision(
  ...revisions: Array<number | null | undefined>
): number | undefined {
  let newest: number | undefined;
  for (const value of revisions) {
    const revision = finiteRevision(value);
    if (revision !== undefined && (newest === undefined || revision > newest)) {
      newest = revision;
    }
  }
  return newest;
}

const GENERATE_REVISION_CONFLICT_RE =
  /(?:visible|editor) content changed (?:before|while) .*generation/i;

/**
 * Whether a generate error is the backend editor-revision conflict (HTTP 409).
 * 判断生成错误是否为后端编辑版本冲突（HTTP 409）。
 *
 * @param error - Error thrown by a generate API call. (生成接口抛出的错误)
 * @returns True when the client may refresh its revision and retry once.
 *   (客户端可以刷新版本后重试一次时返回 true)
 */
export function isGenerateRevisionConflict(error: unknown): boolean {
  if (!error || typeof error !== "object" || !("response" in error)) return false;
  const response = (error as { response?: { status?: unknown; data?: unknown } })
    .response;
  if (!response || response.status !== 409) return false;
  const data = response.data;
  const detail =
    data && typeof data === "object" && "detail" in data
      ? (data as { detail?: unknown }).detail
      : data;
  return typeof detail === "string" && GENERATE_REVISION_CONFLICT_RE.test(detail);
}
