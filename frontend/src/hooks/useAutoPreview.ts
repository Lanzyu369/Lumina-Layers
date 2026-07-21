import { useEffect, useRef } from "react";
import {
  resolveConverterSourceSelection,
  useConverterStore,
} from "../stores/converter";
import { useSettingsStore } from "../stores/settingsStore";

type AutoPreviewSnapshot = {
  imageFile: File;
  inputKey: string;
  settingsKey: string;
};

function sameSnapshot(
  left: AutoPreviewSnapshot,
  right: AutoPreviewSnapshot,
): boolean {
  return (
    left.imageFile === right.imageFile &&
    left.inputKey === right.inputKey &&
    left.settingsKey === right.settingsKey
  );
}

/**
 * Auto-trigger preview when preconditions are met.
 * 当图片已上传、颜色来源已就绪、裁剪模态框已关闭、且当前图片已手动预览过时，
 * 后续所有会改变预览请求的参数变化都会先失效旧结果，再自动触发预览（300ms 防抖）。
 *
 * 新上传的图片必须先手动点击"预览"按钮，之后参数变化才会自动触发。
 */
export function useAutoPreview(): void {
  const imageFile = useConverterStore((state) => state.imageFile);
  const cropModalOpen = useConverterStore((state) => state.cropModalOpen);
  const hasManualPreview = useConverterStore((state) => state.hasManualPreview);
  const submitPreview = useConverterStore((state) => state.submitPreview);
  const invalidatePreview = useConverterStore(
    (state) => state.invalidatePreviewForAutoRefresh,
  );
  const isSourceReady = useConverterStore(
    (state) => resolveConverterSourceSelection(state).isReady,
  );
  const inputKey = useConverterStore((state) =>
    JSON.stringify([
      state.source_version,
      state.lut_name,
      state.lut_names,
      state.selectedNativeBrandKey,
      state.selectedNativeDbNames,
      state.color_layers,
      state.layer_height_mm,
      state.model_enable,
      state.model_only,
      state.model_threshold,
      state.model_margin,
      state.selectedMaterialDirNames,
      state.materialLayerCount,
      state.materialLayerHeightMm,
      state.materialBackingMaterialDirName,
      state.target_width_mm,
      state.color_mode,
      state.modeling_mode,
      state.quantize_colors,
      state.high_precision_3d_preview,
      state.enable_cleanup,
      state.enable_outline,
      state.outline_width,
      state.hue_enable,
      state.chroma_gate,
      state.use_lut_constrained,
      state.auto_dynamic_range,
      state.largeFormatEnabled,
    ]),
  );
  const settingsKey = useSettingsStore((state) =>
    JSON.stringify([
      state.svgPixelsPerMm,
      state.theme,
      state.enableSolverCacheGridSelection,
      state.solverCacheGridResolution,
    ]),
  );

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastTriggeredRef = useRef<AutoPreviewSnapshot | null>(null);
  const hadManualPreviewRef = useRef(false);

  useEffect(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }

    const previouslyHadManualPreview = hadManualPreviewRef.current;
    hadManualPreviewRef.current = hasManualPreview;

    if (!imageFile || cropModalOpen) {
      return;
    }

    const currentSnapshot: AutoPreviewSnapshot = {
      imageFile,
      inputKey,
      settingsKey,
    };
    const previousSnapshot = lastTriggeredRef.current;
    const hasBaselineForCurrentImage =
      previousSnapshot?.imageFile === imageFile;

    // A false -> true transition means a manual preview just established a
    // new authoritative baseline. Seed it without immediately submitting a
    // duplicate request, including after the source selection changed.
    // false -> true 表示手动预览刚建立了新的权威基线；只记录，不重复提交。
    if (
      hasManualPreview &&
      (!previouslyHadManualPreview || previousSnapshot === null)
    ) {
      lastTriggeredRef.current = currentSnapshot;
      return;
    }

    // Source/material setters clear hasManualPreview together with the stale
    // session. Keep auto-refresh eligibility for the same image, while a new
    // File object still requires its first explicit preview.
    // 来源参数会随旧会话一起清掉 hasManualPreview；同一图片仍保留自动刷新资格。
    if (
      (!hasManualPreview && !hasBaselineForCurrentImage) ||
      previousSnapshot === null
    ) {
      return;
    }

    if (sameSnapshot(previousSnapshot, currentSnapshot)) {
      return;
    }

    // Do this before the debounce so an old 2D/3D/session can never appear
    // to represent the newly-selected parameters while regeneration waits.
    // 防抖等待期间立即隐藏旧 2D/3D/session，避免旧结果冒充新参数结果。
    invalidatePreview();

    if (!isSourceReady) {
      return;
    }

    timerRef.current = setTimeout(() => {
      lastTriggeredRef.current = currentSnapshot;
      void submitPreview();
    }, 300);

    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [
    cropModalOpen,
    hasManualPreview,
    imageFile,
    inputKey,
    invalidatePreview,
    isSourceReady,
    settingsKey,
    submitPreview,
  ]);
}
