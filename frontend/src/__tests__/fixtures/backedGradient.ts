import type { BackedGradientCapture, BackedGradientCaptureRequest, BackedGradientDataset, BackedGradientFitRun } from "../../api/luminaBoxBackedGradient";
import { BACKED_GRADIENT_PRIORITY_SYMBOLS, BACKED_GRADIENT_THICKNESSES } from "../../api/luminaBoxBackedGradient";
import { backedGradientCaptureSlot } from "../../utils/luminaBoxBackedGradientCapture";

export function gradientDataset(id = "dataset-1"): BackedGradientDataset {
  return { schema_version: "1.0", kind: "lumina_box_backed_gradient", dataset_id: id, name: id, brand: "KYNIX", material_type: "PETG", batch: "A", notes: "",
    materials: { R: "red", Y: "yellow", B: "blue", W: "white", K: "black", C: "cyan", M: "magenta", G: "green" },
    created_at: "2026-10-07T00:00:00Z", updated_at: "2026-10-07T00:00:00Z", revision: 0, total_mm: 3, observation_face: "bed_contact",
    thicknesses_mm: [...BACKED_GRADIENT_THICKNESSES], captures: [], selected_capture_ids: {} };
}

export function appendGradientCapture(dataset: BackedGradientDataset, request: BackedGradientCaptureRequest, id?: string) {
  const measurement = request.measurement;
  const record: BackedGradientCapture = { record_id: id ?? `record-${dataset.captures.length + 1}`, dataset_id: dataset.dataset_id,
    capture_id: request.capture_id, measurement_id: request.measurement_id ?? measurement!.measurement_id,
    created_at: "2026-10-07T00:00:00Z", received_at: request.received_at ?? "2026-10-07T00:00:00Z",
    material_symbol: request.material_symbol, backing: request.backing, sample_role: request.sample_role,
    overlay_mm: request.overlay_mm, backing_mm: 3 - request.overlay_mm, total_mm: 3,
    reflectance_percent_xyz: request.reflectance_percent_xyz ?? (measurement?.mode !== "transmit" ? measurement!.reflectance_xyz : [0, 0, 0]),
    device_measurement: measurement ?? null, source: measurement ? "device" : "manual", sample_name: request.sample_name ?? "", notes: request.notes ?? "",
    capture_context: {}, selected: true };
  const next = { ...dataset, revision: dataset.revision + 1, captures: [...dataset.captures, record],
    selected_capture_ids: { ...dataset.selected_capture_ids, [backedGradientCaptureSlot(record)]: record.record_id } };
  return { record, dataset: next, deduplicated: false };
}

export function completeGradientDataset(): BackedGradientDataset {
  let dataset = gradientDataset();
  for (const backing of ["W", "K"] as const) {
    dataset = appendGradientCapture(dataset, { capture_id: "ready", measurement_id: `bare-${backing}`, material_symbol: backing, backing,
      sample_role: "bare_backing", overlay_mm: 0, reflectance_percent_xyz: [10, 11, 12] }).dataset;
    for (const material_symbol of BACKED_GRADIENT_PRIORITY_SYMBOLS) for (const overlay_mm of BACKED_GRADIENT_THICKNESSES) {
      dataset = appendGradientCapture(dataset, { capture_id: "ready", measurement_id: `${material_symbol}-${backing}-${overlay_mm}`, material_symbol, backing,
        sample_role: "coated", overlay_mm, reflectance_percent_xyz: [10, 11, 12] }).dataset;
    }
  }
  return dataset;
}

export const gradientRun: BackedGradientFitRun = { fit_id: "fit-1", dataset_id: "dataset-1", dataset_revision: 72, input_hash: "hash", fit_mode: "full_seven",
  status: "complete", progress: 1, stage: "done", error: null, created_at: "2026-10-07T00:00:00Z", updated_at: "2026-10-07T00:00:01Z" };
