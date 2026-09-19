import { describe, expect, it } from "vitest";
import type { ModelSurfacePlacement } from "../../stores/converter";
import {
  getModelSurfaceArtworkAssetKey,
  resolveModelSurfaceArtworkAsset,
  resolveModelSurfaceArtworkSourceDimensions,
} from "./artworkAsset";

const placement: ModelSurfacePlacement = {
  mode: "edge_to_edge",
  offset_x_mm: 0,
  offset_y_mm: 0,
  scale: 1,
  rotation_deg: 0,
  inset_mm: 0,
};

describe("model surface artwork asset contract", () => {
  it("marks a current processed preview as surface-uv with complete provenance", () => {
    const asset = resolveModelSurfaceArtworkAsset({
      sourceImageUrl: "blob:source",
      processedPreviewUrl: "/api/files/surface-preview.png",
      sourceAspectRatio: 1.75,
      modelSurfaceEnabled: true,
      modelFileId: "model-1",
      selectionId: "selection-1",
      sessionId: "session-1",
      previewRequestRevision: 12,
      placement,
    });

    expect(asset).toEqual({
      kind: "surface-uv",
      url: "/api/files/surface-preview.png",
      sourceAspectRatio: 1.75,
      identity: {
        sourceImageUrl: "blob:source",
        modelFileId: "model-1",
        selectionId: "selection-1",
        sessionId: "session-1",
        previewRequestRevision: 12,
        placement,
      },
    });
  });

  it("falls back to source-image while a surface preview is invalidated", () => {
    const asset = resolveModelSurfaceArtworkAsset({
      sourceImageUrl: "blob:source",
      processedPreviewUrl: null,
      sourceAspectRatio: 1.75,
      modelSurfaceEnabled: true,
      modelFileId: "model-1",
      selectionId: "selection-1",
      sessionId: null,
      previewRequestRevision: 13,
      placement,
    });

    expect(asset).toEqual({
      kind: "source-image",
      url: "blob:source",
      sourceAspectRatio: 1.75,
    });
  });

  it("changes identity when the preview revision changes, preventing stale image reuse", () => {
    const baseInput = {
      sourceImageUrl: "blob:source",
      processedPreviewUrl: "/api/files/surface-preview.png",
      sourceAspectRatio: 1.75,
      modelSurfaceEnabled: true,
      modelFileId: "model-1",
      selectionId: "selection-1",
      sessionId: "session-1",
      placement,
    };
    const first = resolveModelSurfaceArtworkAsset({ ...baseInput, previewRequestRevision: 1 });
    const second = resolveModelSurfaceArtworkAsset({ ...baseInput, previewRequestRevision: 2 });

    expect(getModelSurfaceArtworkAssetKey(first)).not.toBe(getModelSurfaceArtworkAssetKey(second));
  });

  it("never uses a surface-uv canvas ratio as the source artwork ratio", () => {
    const surfaceAsset = resolveModelSurfaceArtworkAsset({
      sourceImageUrl: "blob:source",
      processedPreviewUrl: "/api/files/surface-preview.png",
      sourceAspectRatio: null,
      modelSurfaceEnabled: true,
      modelFileId: "model-1",
      selectionId: "selection-1",
      sessionId: "session-1",
      previewRequestRevision: 12,
      placement,
    });

    expect(surfaceAsset).not.toBeNull();
    expect(
      resolveModelSurfaceArtworkSourceDimensions(surfaceAsset!, {
        naturalWidth: 40,
        naturalHeight: 80,
        width: 40,
        height: 80,
      }),
    ).toBeNull();
  });

  it("uses loaded source-image pixels only for a source-image asset without metadata", () => {
    const sourceAsset = resolveModelSurfaceArtworkAsset({
      sourceImageUrl: "blob:source",
      processedPreviewUrl: null,
      sourceAspectRatio: null,
      modelSurfaceEnabled: false,
      modelFileId: null,
      selectionId: null,
      sessionId: null,
      previewRequestRevision: 0,
      placement,
    });

    expect(
      resolveModelSurfaceArtworkSourceDimensions(sourceAsset!, {
        naturalWidth: 80,
        naturalHeight: 40,
        width: 80,
        height: 40,
      }),
    ).toEqual({ width: 80, height: 40 });
  });
});
