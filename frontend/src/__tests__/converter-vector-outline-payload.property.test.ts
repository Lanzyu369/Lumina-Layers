/**
 * Spec: svg-vector-outline-support / Task 1.2
 * Property 1 anchor: 在 vector + enable_outline=true 下，store.submitGenerate
 * 的 generate body 必须忠实携带 enable_outline=true 与精确的 outline_width。
 *
 * 当前 main 上 store 不裁剪这两个字段（参考 store.ts submitGenerate
 * 第 5586/5587 行），所以本测试**预期 PASS**，作为 anchor 防请求层未来回潮。
 *
 * 工单引用: LUM-20260527-001 ("svg 加不了描边")。
 *
 * Validates: Requirements 1.2, 1.4, 2.2, 2.3, 2.4
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import * as fc from "fast-check";

import * as converterApi from "../api/converter";
import * as lutApi from "../api/lut";
import { useConverterStore } from "../stores/converter";
import { useSettingsStore } from "../stores/settingsStore";
import { ColorMode, ModelingMode, StructureMode } from "../api/types";
import { READY_EXPORT_MATERIAL_SELECTION } from "./fixtures/exportMaterialSelection";

/**
 * Reset the converter store to a deterministic baseline so each property
 * iteration starts from the same starting point. We seed `sessionId` and
 * `imageFile` so `submitGenerate` skips the implicit preview branch and
 * directly calls `apiConvertGenerate`.
 * 重置 store 到确定基线；把 sessionId / imageFile 置好，让 submitGenerate
 * 走 generate 分支而不是触发隐式 preview。
 */
function seedVectorGenerateState(outlineWidth: number): void {
  const file = new File(["<svg/>"], "anchor.svg", { type: "image/svg+xml" });
  useSettingsStore.setState({
    deviceProfileId: "BambuStudio:bbl:bambu-lab-h2d:0.4",
  } as never);
  // Merge update (do NOT pass `replace=true` — that would wipe the
  // store's action methods including submitGenerate).
  // 合并更新；不能用 replace=true，否则会把 submitGenerate 等 actions 一起抹掉。
  useConverterStore.setState({
    sessionId: "stub-sess",
    imageFile: file,
    source_version: "legacy",
    // legacy_single + non-empty lut_name 满足 resolveConverterSourceSelection.isReady。
    lut_name: "stub-lut",
    modeling_mode: ModelingMode.VECTOR,
    color_mode: ColorMode.EIGHT_COLOR,
    structure_mode: StructureMode.DOUBLE_SIDED,
    enable_outline: true,
    outline_width: outlineWidth,
    // 关掉所有可能触发额外异步分支的 toggle
    enable_relief: false,
    color_height_map: {},
    autoHeightMode: null,
    puzzleEnabled: false,
    largeFormatEnabled: false,
    enable_cloisonne: false,
    enable_coating: false,
    enable_fridge_magnet: false,
    fridge_magnets: [],
    replacement_regions: [],
    recipe_overrides: [],
    free_color_set: new Set<string>(),
    colorRemapMap: {},
    regionReplacementCount: 0,
  } as never);
}

function seedVectorPreviewState(outlineWidth: number): void {
  seedVectorGenerateState(outlineWidth);
  useConverterStore.setState({
    sessionId: null,
    target_width_mm: 60,
    target_height_mm: 60,
    color_layers: 5,
    layer_height_mm: 0.08,
    quantize_colors: 48,
    enable_cleanup: true,
    hue_enable: false,
    use_lut_constrained: false,
    auto_dynamic_range: false,
  } as never);
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(converterApi, "fetchExportMaterialSelection").mockResolvedValue(READY_EXPORT_MATERIAL_SELECTION);
});

describe("submitGenerate vector outline payload anchor (Task 1.2)", () => {
  it("forwards enable_outline=true and outline_width across [0.5, 10.0]", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.double({
          min: 0.5,
          max: 10.0,
          noNaN: true,
          noDefaultInfinity: true,
        }),
        async (outlineWidth) => {
          const generateSpy = vi
            .spyOn(converterApi, "convertGenerate")
            .mockResolvedValueOnce({
              status: "ok",
              message: "stub",
              download_url: "/api/files/stub.3mf",
            } as never);

          seedVectorGenerateState(outlineWidth);

          await useConverterStore.getState().submitGenerate();

          expect(generateSpy).toHaveBeenCalledTimes(1);
          const [sessionIdArg, paramsArg] = generateSpy.mock.calls[0];
          expect(sessionIdArg).toBe("stub-sess");
          // Property 1 (anchor): store 必须把 vector 用户的 outline 意图
          // 原样透传到 generate body。
          expect(paramsArg.modeling_mode).toBe(ModelingMode.VECTOR);
          expect(paramsArg.enable_outline).toBe(true);
          expect(paramsArg.outline_width).toBe(outlineWidth);
          expect(paramsArg.device_profile_id).toBe("BambuStudio:bbl:bambu-lab-h2d:0.4");

          generateSpy.mockRestore();
        },
      ),
      { numRuns: 100 },
    );
  });

  it("LUM-20260527-001 anchor: outline_width=2.0 vector + 8-Color Max", async () => {
    const generateSpy = vi
      .spyOn(converterApi, "convertGenerate")
      .mockResolvedValueOnce({
        status: "ok",
        message: "stub",
        download_url: "/api/files/anchor.3mf",
      } as never);

    seedVectorGenerateState(2.0);
    await useConverterStore.getState().submitGenerate();

    expect(generateSpy).toHaveBeenCalledTimes(1);
    const [, paramsArg] = generateSpy.mock.calls[0];
    expect(paramsArg.modeling_mode).toBe(ModelingMode.VECTOR);
    expect(paramsArg.color_mode).toBe(ColorMode.EIGHT_COLOR);
    expect(paramsArg.enable_outline).toBe(true);
    expect(paramsArg.outline_width).toBe(2.0);
    expect(paramsArg.device_profile_id).toBe("BambuStudio:bbl:bambu-lab-h2d:0.4");

    generateSpy.mockRestore();
  });

  it("preview anchor: forwards enable_outline=true and outline_width=2.0", async () => {
    const previewSpy = vi
      .spyOn(converterApi, "convertPreview")
      .mockResolvedValueOnce({
        session_id: "preview-sess",
        status: "ok",
        message: "stub",
        preview_url: "/api/files/preview.png",
        palette: [],
        dimensions: { width: 16, height: 16 },
      } as never);
    vi.spyOn(converterApi, "fetchGradientGroups").mockResolvedValueOnce({
      groups: [],
    } as never);
    vi.spyOn(lutApi, "fetchSessionLutInfo").mockRejectedValueOnce(
      new Error("session LUT info unavailable"),
    );

    seedVectorPreviewState(2.0);
    await useConverterStore.getState().submitPreview();

    expect(previewSpy).toHaveBeenCalledTimes(1);
    const [, paramsArg] = previewSpy.mock.calls[0];
    expect(paramsArg.modeling_mode).toBe(ModelingMode.VECTOR);
    expect(paramsArg.color_mode).toBe(ColorMode.EIGHT_COLOR);
    expect(paramsArg.enable_outline).toBe(true);
    expect(paramsArg.outline_width).toBe(2.0);
  });
});
