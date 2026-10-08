import { describe, expect, it } from "vitest";
import {
  BACKED_GRADIENT_MAX_IMPORT_BYTES, backedGradientErrorKey, backedGradientReadiness,
} from "../utils/luminaBoxBackedGradientCapture";
import { completeGradientDataset, gradientDataset } from "./fixtures/backedGradient";

describe("backed-gradient collection guidance", () => {
  it("shows all seven thicknesses equally and locates missing references and samples", () => {
    const dataset = completeGradientDataset();
    const initial = backedGradientReadiness(dataset);
    expect(initial).toMatchObject({ count: 72, total: 72, perBacking: { W: { count: 36, total: 36 }, K: { count: 36, total: 36 } } });
    expect(initial.missingTargets).toEqual([]);
    delete dataset.selected_capture_ids["bare:K"];
    delete dataset.selected_capture_ids["Y:W:0.24"];
    const missing = backedGradientReadiness(dataset);
    expect(missing.count).toBe(70);
    expect(missing.missingTargets).toEqual([
      { target: { material_symbol: "K", backing: "K", sample_role: "bare_backing" }, thickness: 0, slot: "bare:K" },
      { target: { material_symbol: "Y", backing: "W", sample_role: "coated" }, thickness: .24, slot: "Y:W:0.24" },
    ]);
  });

  it("counts started optional materials and ignores selections with no saved reading", () => {
    const dataset = gradientDataset();
    dataset.captures.push({ ...completeGradientDataset().captures[0], record_id: "cyan-reading", material_symbol: "C", backing: "W", overlay_mm: .08, sample_role: "coated" });
    dataset.selected_capture_ids = { "C:W:0.08": "cyan-reading", "R:W:0.08": "deleted-reading" };
    expect(backedGradientReadiness(dataset)).toMatchObject({ count: 1, total: 86,
      perBacking: { W: { count: 1, total: 43 }, K: { count: 0, total: 43 } } });
  });

  it("uses the same ten-mebibyte import limit as the server", () => {
    expect(BACKED_GRADIENT_MAX_IMPORT_BYTES).toBe(10 * 1024 * 1024);
  });

  it.each([
    ["The selected backings use different measurement calibrations. Recollect one against the other backing.", "backing_calibration_mismatch"],
    ["Missing reference readings: bare:W, bare:K", "missing_references"],
    ["Bare white must exceed bare black in each channel", "invalid_references"],
    ["Missing backed-gradient readings: R:K:0.24", "missing_samples"],
    ["Backend restarted during fitting. Start a new fit; readings remain saved.", "calculation_interrupted"],
    ["Fitting timed out. The original data remain saved.", "calculation_timeout"],
    ["An experiment fit is already running. Wait for its result.", "calculation_busy"],
    ["The backed-gradient record was not found.", "record_missing"],
    ["This measurement ID belongs to different data or a different target.", "record_conflict"],
    ["This endpoint is only available from the local Lumina Studio app.", "local_only"],
  ])("maps %s to an actionable translation key", (message, suffix) => {
    const response = { response: { data: { detail: message } } };
    expect(backedGradientErrorKey(response, "lumina_box_bg_save_failed")).toBe(`lumina_box_bg_error_${suffix}`);
    expect(backedGradientErrorKey(message, "lumina_box_bg_fit_failed")).toBe(`lumina_box_bg_error_${suffix}`);
  });

  it("does not leak unknown English diagnostics into the visible message", () => {
    expect(backedGradientErrorKey(new Error("Worker result does not match its frozen experiment; D:/private/path"), "lumina_box_bg_fit_failed"))
      .toBe("lumina_box_bg_fit_failed");
    expect(backedGradientErrorKey({ response: { data: { detail: [{ loc: ["body", "overlay_mm"], msg: "Input should be numeric" }] } } }, "lumina_box_bg_save_failed"))
      .toBe("lumina_box_bg_save_failed");
  });
});
