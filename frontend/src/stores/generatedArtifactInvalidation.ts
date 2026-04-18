type InvalidateGeneratedArtifacts = () => void;

let invalidateGeneratedArtifactsHandler: InvalidateGeneratedArtifacts | null = null;

export function registerGeneratedArtifactInvalidator(
  handler: InvalidateGeneratedArtifacts,
): void {
  invalidateGeneratedArtifactsHandler = handler;
}

export function invalidateGeneratedArtifacts(): void {
  invalidateGeneratedArtifactsHandler?.();
}
