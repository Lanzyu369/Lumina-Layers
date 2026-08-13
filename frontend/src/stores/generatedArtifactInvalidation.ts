type InvalidateGeneratedArtifacts = () => void;
type InvalidatePreviewArtifacts = () => void;
type InvalidateSingleItemDownload = () => void;

let invalidateGeneratedArtifactsHandler: InvalidateGeneratedArtifacts | null = null;
let invalidatePreviewArtifactsHandler: InvalidatePreviewArtifacts | null = null;
let invalidateSingleItemDownloadHandler: InvalidateSingleItemDownload | null = null;

export function registerGeneratedArtifactInvalidator(
  handler: InvalidateGeneratedArtifacts,
): void {
  invalidateGeneratedArtifactsHandler = handler;
}

export function invalidateGeneratedArtifacts(): void {
  invalidateGeneratedArtifactsHandler?.();
}

export function registerPreviewArtifactInvalidator(
  handler: InvalidatePreviewArtifacts,
): void {
  invalidatePreviewArtifactsHandler = handler;
}

export function invalidatePreviewArtifacts(): void {
  invalidatePreviewArtifactsHandler?.();
}

export function registerSingleItemDownloadInvalidator(
  handler: InvalidateSingleItemDownload,
): void {
  invalidateSingleItemDownloadHandler = handler;
}

export function invalidateSingleItemDownload(): void {
  invalidateSingleItemDownloadHandler?.();
}
