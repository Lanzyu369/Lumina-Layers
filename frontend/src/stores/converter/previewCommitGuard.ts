export interface PreviewCommitOwner {
  sessionId: string | null;
  previewRequestRevision: number;
}

export interface PreviewCommitGuard extends PreviewCommitOwner {
  replacementEpoch: number;
  operationId: string;
}

/** Capture every ownership coordinate needed before an async preview write. */
export function capturePreviewCommitGuard(
  owner: PreviewCommitOwner,
  replacementEpoch: number,
  operationId: string,
): PreviewCommitGuard {
  return {
    sessionId: owner.sessionId,
    previewRequestRevision: owner.previewRequestRevision,
    replacementEpoch,
    operationId,
  };
}

/** True only while the response still belongs to the active preview. */
export function canCommitPreviewResponse(
  current: PreviewCommitOwner,
  guard: PreviewCommitGuard,
  replacementEpoch: number,
): boolean {
  return (
    current.sessionId === guard.sessionId &&
    current.previewRequestRevision === guard.previewRequestRevision &&
    replacementEpoch === guard.replacementEpoch
  );
}
