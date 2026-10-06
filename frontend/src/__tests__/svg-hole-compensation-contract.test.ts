import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  preview: vi.fn(), generate: vi.fn(), batch: vi.fn(),
  uploadImagePreview: vi.fn(),
}));
vi.mock("../api/converter", async () => ({
  ...await vi.importActual<typeof import("../api/converter")>("../api/converter"),
  convertPreview: api.preview,
  convertGenerate: api.generate,
  convertBatch: api.batch,
  fetchGradientGroups: vi.fn().mockResolvedValue({ status: "ok", groups: [] }),
  getEditorSelection: vi.fn().mockResolvedValue(null),
}));
vi.mock("../api/system", async () => ({
  ...await vi.importActual<typeof import("../api/system")>("../api/system"),
  uploadImagePreview: api.uploadImagePreview,
}));

import { ModelingMode } from "../api/types";
import { DEFAULT_STATE, useConverterStore } from "../stores/converter";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import { exportConverterRecipe } from "../recipe/exportRecipe";
import { restoreConverterRecipe } from "../recipe/importRecipe";
import type { LuminaRecipe } from "../recipe/types";
import { buildAdvancedParams } from "../utils/advancedParamsBuilder";

const OPTIONS = {
  svg_hole_compensation_enabled: true,
  svg_hole_max_area_mm2: 0.75,
  svg_hole_max_width_mm: 0,
};
function svgFile() {
  return new File(['<svg xmlns="http://www.w3.org/2000/svg"/>'], "holes.svg", {
    type: "image/svg+xml",
  });
}
function previewResponse() {
  return {
    status: "ok", message: "Preview generated", session_id: "hole-session",
    preview_url: "/api/files/holes.png", preview_glb_url: "/api/files/holes.glb",
    palette: [], dimensions: { width: 200, height: 200 }, warnings: [],
  };
}
function wrapRecipe(base = exportConverterRecipe(useConverterStore.getState(), DEFAULT_SETTINGS, "")): LuminaRecipe {
  return {
    format: "lumina-recipe", schema_version: 3, app_version: "0.0.0",
    created_at: "2026-09-13T00:00:00.000Z", source: "converter",
    cover: { width: 1, height: 1, mime_type: "image/png" },
    asset: { primary: {
      filename: "holes.svg", mime_type: "image/svg+xml", byte_size: 6,
      encoding: "base64", payload_b64: "PHN2Zy8+",
    } },
    recipe: { converter: base },
    compat: { min_schema_version: 1 }, warnings: [],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  useConverterStore.setState({
    ...DEFAULT_STATE, imageFile: svgFile(), modeling_mode: ModelingMode.VECTOR,
    source_version: "legacy", lut_name: "test-lut", lut_names: ["test-lut"],
    ...OPTIONS,
  });
  api.preview.mockResolvedValue(previewResponse());
  api.generate.mockResolvedValue({
    status: "ok", message: "Generated", download_url: "/api/files/model.3mf",
    preview_3d_url: "/api/files/model.glb",
  });
  api.batch.mockResolvedValue({
    status: "ok", message: "Batch generated", download_url: "/api/files/models.zip",
    preview_items: [], results: [], warnings: [],
  });
});
afterEach(() => { useConverterStore.setState({ ...DEFAULT_STATE }); });

describe("source SVG compensation product contract", () => {
  it("is disabled by default with physical area and width defaults", () => {
    expect(DEFAULT_STATE).toMatchObject({
      svg_hole_compensation_enabled: false,
      svg_hole_max_area_mm2: 0.5,
      svg_hole_max_width_mm: 0.1,
    });
  });

  it("sends identical source compensation settings for preview, generate and batch", async () => {
    await useConverterStore.getState().submitPreview();
    expect(api.preview.mock.calls[0][1]).toMatchObject(OPTIONS);
    await useConverterStore.getState().submitGenerate();
    expect(api.generate.mock.calls[0][1]).toMatchObject(OPTIONS);
    useConverterStore.setState({ batchMode: true, batchFiles: [svgFile(), svgFile()] });
    await useConverterStore.getState().submitBatch();
    expect(api.batch.mock.calls[0][1]).toMatchObject(OPTIONS);
  });

  it.each(["toggle", "area", "width"])("invalidates old preview authority when %s changes", (kind) => {
    useConverterStore.setState({
      sessionId: "old-session", previewImageUrl: "/api/files/old.png",
      downloadUrl: "/api/files/old.3mf", modelUrl: "/api/files/old.glb",
      hasManualPreview: true,
    });
    const oldRevision = useConverterStore.getState().previewRequestRevision;
    const state = useConverterStore.getState();
    if (kind === "toggle") state.setSvgHoleCompensationEnabled(false);
    if (kind === "area") state.setSvgHoleMaxAreaMm2(1);
    if (kind === "width") state.setSvgHoleMaxWidthMm(0.2);
    expect(useConverterStore.getState()).toMatchObject({
      sessionId: null, previewImageUrl: null, downloadUrl: null, modelUrl: null,
      hasManualPreview: true, previewAutoRefreshPending: true,
      previewRequestRevision: oldRevision + 1,
    });
  });

  it("discards a pending preview after compensation changes", async () => {
    let resolve!: (value: ReturnType<typeof previewResponse>) => void;
    api.preview.mockImplementationOnce(() => new Promise((r) => { resolve = r; }));
    const pending = useConverterStore.getState().submitPreview();
    await Promise.resolve();
    expect(api.preview).toHaveBeenCalledOnce();
    useConverterStore.getState().setSvgHoleMaxAreaMm2(1);
    resolve(previewResponse());
    await pending;
    expect(useConverterStore.getState()).toMatchObject({
      sessionId: null, previewImageUrl: null, svg_hole_max_area_mm2: 1,
    });
  });

  it("discards a pending generated model after compensation changes", async () => {
    let resolve!: (value: object) => void;
    api.generate.mockImplementationOnce(() => new Promise((r) => { resolve = r; }));
    useConverterStore.setState({ sessionId: "hole-session" });
    const pending = useConverterStore.getState().submitGenerate();
    await Promise.resolve();
    expect(api.generate).toHaveBeenCalledOnce();
    useConverterStore.getState().setSvgHoleCompensationEnabled(false);
    resolve({ status: "ok", message: "Generated", download_url: "/api/files/stale.3mf" });
    await pending;
    expect(useConverterStore.getState()).toMatchObject({ downloadUrl: null, isGenerating: false });
  });

  it("discards a pending batch after compensation changes", async () => {
    let resolve!: (value: object) => void;
    api.batch.mockImplementationOnce(() => new Promise((r) => { resolve = r; }));
    useConverterStore.setState({ batchMode: true, batchFiles: [svgFile(), svgFile()] });
    const pending = useConverterStore.getState().submitBatch();
    await Promise.resolve();
    expect(api.batch).toHaveBeenCalledOnce();
    useConverterStore.getState().setSvgHoleMaxWidthMm(0.2);
    resolve({ status: "ok", message: "Generated", results: [], preview_items: [], download_url: "/api/files/stale.zip" });
    await pending;
    expect(useConverterStore.getState()).toMatchObject({ downloadUrl: null, batchResult: null, batchLoading: false });
  });

  it.each(["width", "height"])("invalidates compensated geometry immediately when linked %s changes", (axis) => {
    useConverterStore.setState({
      aspectRatio: 2, target_width_mm: 60, target_height_mm: 30,
      sessionId: "small-session", previewImageUrl: "/api/files/small.png",
      previewGlbUrl: "/api/files/small.glb", downloadUrl: "/api/files/small.3mf",
      hasManualPreview: true,
    });
    const state = useConverterStore.getState();
    if (axis === "width") state.setTargetWidthMm(220);
    else state.setTargetHeightMm(110);
    expect(useConverterStore.getState()).toMatchObject({
      target_width_mm: 220, target_height_mm: 110,
      sessionId: null, previewImageUrl: null, previewGlbUrl: null, downloadUrl: null,
      hasManualPreview: true, previewAutoRefreshPending: true,
      previewRequestRevision: state.previewRequestRevision + 1,
    });
  });

  it("keeps compensated geometry when linked dimensions do not actually change", () => {
    useConverterStore.setState({
      aspectRatio: 2, target_width_mm: 60, target_height_mm: 30,
      sessionId: "same-size-session", previewImageUrl: "/api/files/same-size.png",
      hasManualPreview: true,
    });
    const oldRevision = useConverterStore.getState().previewRequestRevision;
    useConverterStore.getState().setTargetWidthMm(60);
    useConverterStore.getState().setTargetHeightMm(30);
    expect(useConverterStore.getState()).toMatchObject({
      sessionId: "same-size-session", previewImageUrl: "/api/files/same-size.png",
      previewAutoRefreshPending: false, previewRequestRevision: oldRevision,
    });
  });

  it("discards a pending compensated preview after a size change", async () => {
    let resolve!: (value: ReturnType<typeof previewResponse>) => void;
    api.preview.mockImplementationOnce(() => new Promise((r) => { resolve = r; }));
    const pending = useConverterStore.getState().submitPreview();
    await Promise.resolve();
    expect(api.preview).toHaveBeenCalledOnce();
    useConverterStore.getState().setTargetWidthMm(220);
    resolve(previewResponse());
    await pending;
    expect(useConverterStore.getState()).toMatchObject({
      target_width_mm: 220, sessionId: null, previewImageUrl: null,
      isLoading: false, previewAutoRefreshPending: true,
    });
  });

  it("discards a pending compensated generation after a linked height change", async () => {
    let resolve!: (value: object) => void;
    api.generate.mockImplementationOnce(() => new Promise((r) => { resolve = r; }));
    useConverterStore.setState({ sessionId: "small-session", aspectRatio: 2 });
    const pending = useConverterStore.getState().submitGenerate();
    await Promise.resolve();
    expect(api.generate).toHaveBeenCalledOnce();
    useConverterStore.getState().setTargetHeightMm(110);
    resolve({ status: "ok", message: "Generated", download_url: "/api/files/stale-size.3mf" });
    await pending;
    expect(useConverterStore.getState()).toMatchObject({
      target_width_mm: 220, target_height_mm: 110,
      sessionId: null, downloadUrl: null, isGenerating: false,
    });
  });

  it("invalidates completed all-SVG batch results when compensation dimensions change", async () => {
    useConverterStore.setState({ imageFile: null, batchMode: true, batchFiles: [svgFile(), svgFile()] });
    await useConverterStore.getState().submitBatch();
    expect(useConverterStore.getState().batchResult).not.toBeNull();
    useConverterStore.getState().setTargetWidthMm(120);
    expect(useConverterStore.getState()).toMatchObject({ batchResult: null, batchPreviewItems: [], downloadUrl: null });
  });

  it("discards pending all-SVG batch results and submits the next batch at the new compensation size", async () => {
    useConverterStore.setState({ imageFile: null, batchMode: true, batchFiles: [svgFile(), svgFile()] });
    let resolve!: (value: object) => void;
    api.batch.mockImplementationOnce(() => new Promise((r) => { resolve = r; }));
    const pending = useConverterStore.getState().submitBatch();
    await Promise.resolve();
    expect(api.batch).toHaveBeenCalledOnce();
    useConverterStore.getState().setTargetWidthMm(220);
    resolve({ status: "ok", message: "Generated", results: [], preview_items: [], download_url: "/api/files/stale-size.zip" });
    await pending;
    expect(useConverterStore.getState()).toMatchObject({
      target_width_mm: 220, batchResult: null, batchPreviewItems: [], downloadUrl: null, batchLoading: false,
    });
    await useConverterStore.getState().submitBatch();
    expect(api.batch.mock.calls[1][1]).toMatchObject({ target_width_mm: 220, ...OPTIONS });
  });

  it("retains saved thresholds and choice when loading another SVG", () => {
    useConverterStore.getState().setSvgHoleMaxAreaMm2(1.25);
    useConverterStore.getState().setSvgHoleCompensationEnabled(false);
    useConverterStore.getState().setSvgHoleCompensationEnabled(true);
    useConverterStore.setState({ ...DEFAULT_STATE });
    useConverterStore.getState().setImageFile(svgFile());
    expect(useConverterStore.getState()).toMatchObject({
      svg_hole_compensation_enabled: true, svg_hole_max_area_mm2: 1.25,
      svg_hole_max_width_mm: 0,
    });
  });

  it("disables compensation for mixed raster/SVG batches", () => {
    useConverterStore.setState({ batchMode: true, batchFiles: [svgFile(), new File(["png"], "image.png")] });
    expect(useConverterStore.getState().svg_hole_compensation_enabled).toBe(false);
  });

  it("allows selecting vector mode for an all-SVG batch", () => {
    useConverterStore.setState({ ...DEFAULT_STATE });
    useConverterStore.getState().handleFilesSelect([svgFile(), svgFile()]);
    useConverterStore.getState().setModelingMode(ModelingMode.VECTOR);
    useConverterStore.getState().setSvgHoleCompensationEnabled(true);
    expect(useConverterStore.getState()).toMatchObject({ modeling_mode: ModelingMode.VECTOR, svg_hole_compensation_enabled: true });
  });

  it("restores saved compensation for a fresh direct SVG batch when vector mode is selected", () => {
    useConverterStore.getState().setSvgHoleMaxAreaMm2(1.25);
    useConverterStore.setState({ ...DEFAULT_STATE });
    useConverterStore.getState().handleFilesSelect([svgFile(), svgFile()]);
    expect(useConverterStore.getState()).toMatchObject({
      svg_hole_compensation_enabled: false,
      modeling_mode: ModelingMode.HIGH_FIDELITY,
    });
    useConverterStore.getState().setModelingMode(ModelingMode.VECTOR);
    expect(useConverterStore.getState()).toMatchObject({
      svg_hole_compensation_enabled: true,
      svg_hole_max_area_mm2: 1.25,
      svg_hole_max_width_mm: 0,
    });
  });

  it.each(["mixed", "raster"])("keeps saved SVG compensation disabled for a fresh %s batch", (kind) => {
    useConverterStore.getState().setSvgHoleMaxAreaMm2(1.25);
    useConverterStore.setState({ ...DEFAULT_STATE });
    const raster = new File(["png"], "image.png", { type: "image/png" });
    useConverterStore.getState().handleFilesSelect([kind === "mixed" ? svgFile() : raster, raster]);
    useConverterStore.getState().setModelingMode(ModelingMode.VECTOR);
    expect(useConverterStore.getState()).toMatchObject({
      modeling_mode: ModelingMode.HIGH_FIDELITY,
      svg_hole_compensation_enabled: false,
    });
  });

  it("discards an earlier batch response when vector mode restores saved compensation", async () => {
    useConverterStore.getState().setSvgHoleMaxAreaMm2(1.25);
    useConverterStore.setState({ ...DEFAULT_STATE, lut_name: "test-lut", lut_names: ["test-lut"] });
    useConverterStore.getState().handleFilesSelect([svgFile(), svgFile()]);
    let resolve!: (value: object) => void;
    api.batch.mockImplementationOnce(() => new Promise((r) => { resolve = r; }));
    const pending = useConverterStore.getState().submitBatch();
    await Promise.resolve();
    expect(api.batch).toHaveBeenCalledOnce();
    useConverterStore.getState().setModelingMode(ModelingMode.VECTOR);
    resolve({ status: "ok", message: "Generated", results: [], preview_items: [], download_url: "/api/files/stale.zip" });
    await pending;
    expect(useConverterStore.getState()).toMatchObject({
      downloadUrl: null, batchResult: null, batchLoading: false,
      svg_hole_compensation_enabled: true,
    });
  });

  it("keeps RAW upload preview valid while disabling SVG compensation", async () => {
    api.uploadImagePreview.mockResolvedValue({ preview_url: "/api/files/raw-preview.png", width: 400, height: 200 });
    useConverterStore.getState().setImageFile(new File(["raw"], "photo.nef", { type: "application/octet-stream" }));
    await Promise.resolve();
    await Promise.resolve();
    expect(useConverterStore.getState()).toMatchObject({
      svg_hole_compensation_enabled: false, imagePreviewUrl: "/api/files/raw-preview.png", aspectRatio: 2,
    });
  });

  it("persists imported compensation preferences for the next SVG", () => {
    const restored = restoreConverterRecipe(wrapRecipe(), []);
    useConverterStore.getState().importRecipeState(restored.state, svgFile());
    useConverterStore.setState({ ...DEFAULT_STATE });
    useConverterStore.getState().setImageFile(svgFile());
    expect(useConverterStore.getState()).toMatchObject(OPTIONS);
  });

  it.each(["upload", "vectorizer"])("restores remembered SVG compensation through %s", (entry) => {
    useConverterStore.getState().setSvgHoleMaxAreaMm2(1.25);
    useConverterStore.setState({ ...DEFAULT_STATE });
    if (entry === "upload") useConverterStore.getState().handleFilesSelect([svgFile()]);
    else useConverterStore.getState().loadVectorizedSvgIntoConverter(svgFile());
    expect(useConverterStore.getState()).toMatchObject({
      svg_hole_compensation_enabled: true, svg_hole_max_area_mm2: 1.25, svg_hole_max_width_mm: 0,
    });
  });

  it("turns compensation off when leaving vector mode but retains physical thresholds", () => {
    useConverterStore.getState().setModelingMode(ModelingMode.HIGH_FIDELITY);
    expect(useConverterStore.getState()).toMatchObject({
      ...OPTIONS, svg_hole_compensation_enabled: false,
    });
  });

  it("turns compensation off for an uploaded raster image", () => {
    useConverterStore.getState().setImageFile(new File(["png"], "photo.png", { type: "image/png" }));
    expect(useConverterStore.getState().svg_hole_compensation_enabled).toBe(false);
  });

  it.each([-1, Number.NaN, Number.POSITIVE_INFINITY])("does not adopt invalid physical thresholds: %s", (value) => {
    useConverterStore.getState().setSvgHoleMaxAreaMm2(value);
    useConverterStore.getState().setSvgHoleMaxWidthMm(value);
    expect(useConverterStore.getState()).toMatchObject(OPTIONS);
  });

  it("preserves compensation settings in project export and restore", () => {
    const recipe = wrapRecipe();
    expect(recipe.recipe.converter?.base).toMatchObject(OPTIONS);
    const restored = restoreConverterRecipe(recipe, []);
    expect(restored.state).toMatchObject(OPTIONS);
  });

  it("restores old projects with compensation disabled", () => {
    const recipe = wrapRecipe();
    delete recipe.recipe.converter!.base.svg_hole_compensation_enabled;
    delete recipe.recipe.converter!.base.svg_hole_max_area_mm2;
    delete recipe.recipe.converter!.base.svg_hole_max_width_mm;
    expect(restoreConverterRecipe(recipe, []).state).toMatchObject({
      svg_hole_compensation_enabled: false, svg_hole_max_area_mm2: 0.5,
      svg_hole_max_width_mm: 0.1,
    });
  });

  it.each([-1, Number.NaN, Number.POSITIVE_INFINITY])("rejects invalid compensation thresholds from projects: %s", (area) => {
    const recipe = wrapRecipe();
    recipe.recipe.converter!.base.svg_hole_max_area_mm2 = area;
    expect(() => restoreConverterRecipe(recipe, [])).toThrow(/SVG/);
  });

  it("includes compensation settings in feedback and action-history snapshots", () => {
    const snapshot = buildAdvancedParams(useConverterStore.getState(), "converter", { maxBytes: 8192 });
    expect(snapshot).toHaveProperty("generation", expect.objectContaining(OPTIONS));
  });
});
