import { ModelingMode } from "../api/types";
import { isSvgImageFile } from "./imageRotation";

export type VectorPreviewRenderer = "vector_analytic" | "segmented";

export interface VectorPreviewRendererState {
  imageFile: File | null;
  modeling_mode: ModelingMode;
  modelSurfaceEnabled: boolean;
  largeFormatEnabled: boolean;
  batchPreviewItems: ReadonlyArray<unknown>;
}

/**
 * Resolve the lightweight SVG renderer, or null when another flow owns its view.
 * 解析当前轻量 SVG renderer；若画面由其他流程负责则返回 null。
 */
export function resolveVectorPreviewRenderer(
  state: VectorPreviewRendererState,
  enableSmoothVectorPreview: boolean,
): VectorPreviewRenderer | null {
  if (
    !isSvgImageFile(state.imageFile) ||
    state.modeling_mode !== ModelingMode.VECTOR ||
    state.modelSurfaceEnabled ||
    state.largeFormatEnabled ||
    state.batchPreviewItems.length > 0
  ) {
    return null;
  }
  return enableSmoothVectorPreview ? "vector_analytic" : "segmented";
}
