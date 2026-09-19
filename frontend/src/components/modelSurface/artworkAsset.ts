import type { ModelSurfacePlacement } from "../../stores/converter";

export interface ModelSurfaceArtworkIdentity {
  sourceImageUrl: string;
  modelFileId: string;
  selectionId: string;
  sessionId: string;
  previewRequestRevision: number;
  placement: ModelSurfacePlacement;
}

export interface SourceImageArtworkAsset {
  kind: "source-image";
  url: string;
  sourceAspectRatio?: number | null;
}

export interface SurfaceUvArtworkAsset {
  kind: "surface-uv";
  url: string;
  sourceAspectRatio?: number | null;
  identity: ModelSurfaceArtworkIdentity;
}

export type ModelSurfaceArtworkAsset = SourceImageArtworkAsset | SurfaceUvArtworkAsset;

export interface ResolveModelSurfaceArtworkAssetInput {
  sourceImageUrl: string | null | undefined;
  processedPreviewUrl: string | null | undefined;
  sourceAspectRatio?: number | null;
  modelSurfaceEnabled: boolean;
  modelFileId: string | null | undefined;
  selectionId: string | null | undefined;
  sessionId: string | null | undefined;
  previewRequestRevision: number;
  placement: ModelSurfacePlacement;
}

function nonEmptyString(value: string | null | undefined): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function validAspectRatio(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

export function resolveModelSurfaceArtworkAsset(
  input: ResolveModelSurfaceArtworkAssetInput,
): ModelSurfaceArtworkAsset | null {
  const sourceImageUrl = nonEmptyString(input.sourceImageUrl);
  if (!sourceImageUrl) {
    return null;
  }

  const sourceAspectRatio = validAspectRatio(input.sourceAspectRatio);
  const processedPreviewUrl = nonEmptyString(input.processedPreviewUrl);
  const modelFileId = nonEmptyString(input.modelFileId);
  const selectionId = nonEmptyString(input.selectionId);
  const sessionId = nonEmptyString(input.sessionId);

  if (
    input.modelSurfaceEnabled
    && processedPreviewUrl
    && modelFileId
    && selectionId
    && sessionId
    && Number.isInteger(input.previewRequestRevision)
    && input.previewRequestRevision >= 0
  ) {
    return {
      kind: "surface-uv",
      url: processedPreviewUrl,
      sourceAspectRatio,
      identity: {
        sourceImageUrl,
        modelFileId,
        selectionId,
        sessionId,
        previewRequestRevision: input.previewRequestRevision,
        placement: input.placement,
      },
    };
  }

  return {
    kind: "source-image",
    url: sourceImageUrl,
    sourceAspectRatio,
  };
}

export function getModelSurfaceArtworkAssetKey(
  asset: ModelSurfaceArtworkAsset | null | undefined,
): string {
  if (!asset) {
    return "none";
  }
  if (asset.kind === "source-image") {
    return `source-image|${asset.url}|${asset.sourceAspectRatio ?? ""}`;
  }
  const { identity } = asset;
  const placement = identity.placement;
  return [
    "surface-uv",
    asset.url,
    asset.sourceAspectRatio ?? "",
    identity.sourceImageUrl,
    identity.modelFileId,
    identity.selectionId,
    identity.sessionId,
    identity.previewRequestRevision,
    placement.mode,
    placement.offset_x_mm,
    placement.offset_y_mm,
    placement.scale,
    placement.rotation_deg,
    placement.inset_mm,
  ].join("|");
}
