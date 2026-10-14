import { beforeEach, describe, expect, it, vi } from "vitest";

import apiClient from "../api/client";
import { parseLuminaBoxFrame } from "../api/luminaBoxSerial";
import {
  deleteLuminaBoxStackSample,
  exportLuminaBoxStackSamples,
  listLuminaBoxStackSamples,
  loadLuminaBoxStackSample,
  saveLuminaBoxStackSample,
} from "../api/luminaBoxStackSamples";
import reliableFirmwareWire from "./fixtures/lumina-box-reliable-firmware.jsonl?raw";

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

const mockGet = vi.mocked(apiClient.get);
const mockPost = vi.mocked(apiClient.post);
const mockDelete = vi.mocked(apiClient.delete);
const endpoint = "/extractor/lumina-box/stack-samples";

const delivery = reliableFirmwareWire.trimEnd().split(/\r?\n/)
  .map(parseLuminaBoxFrame)
  .find((frame) => frame.kind === "delivery"
    && frame.measurement.mode === "reflect"
    && frame.measurement.thickness_mm === 3);

if (delivery?.kind !== "delivery" || delivery.measurement.mode !== "reflect") {
  throw new Error("Missing 3 mm reflection delivery in the firmware wire fixture");
}

const payload = {
  recipe_top_to_bottom: "CCMMM",
  measurement: delivery.measurement,
  capture_id: delivery.captureId,
  sample_name: "CMYW stack 01",
  notes: "Keep the original reflection frame",
  material_batch: "KYNIX-PETG-batch-A",
  reference_directory_name: "KYNIX/reference-white",
  measurement_backing_percent_xyz: [19.8, 19.7, 24.7],
} satisfies Parameters<typeof saveLuminaBoxStackSample>[0];

const record = {
  schema_version: "1.0",
  kind: "lumina_box_stack_sample",
  data_role: "actual_measured_multimaterial_reflectance",
  record_id: "7d4a6c9b-13de-44c0-8bfe-14283d607b65",
  created_at: "2026-10-05T16:00:00Z",
  capture_id: payload.capture_id,
  recipe_top_to_bottom: payload.recipe_top_to_bottom,
  sample_name: payload.sample_name,
  notes: payload.notes,
  material_batch: payload.material_batch,
  reference_directory_name: payload.reference_directory_name,
  measurement_backing_percent_xyz: payload.measurement_backing_percent_xyz,
  geometry: {
    upper_layer_count: 5,
    upper_layer_height_mm: 0.08,
    first_layer_height_mm: 0.2,
    total_layer_count: 36,
    upper_mm: 0.4,
    white_base_mm: 2.6,
    total_mm: 3,
    full_recipe_top_to_bottom: `${payload.recipe_top_to_bottom}${"W".repeat(31)}`,
    layer_heights_mm_top_to_bottom: [...Array<number>(35).fill(0.08), 0.2],
  },
  reflectance_percent_xyz: [103.25, 48.25, 51.125],
  reflectance_relative_xyz: [1.0325, 0.4825, 0.51125],
  display_rgb: [255, 153, 190],
  display_hex: "#FF99BE",
  device_measurement: payload.measurement,
  reference_context: {
    status: "captured",
    archive_id: "archive-white",
    revision_id: "revision-white-1",
    reference_id: "reference-white-1",
    sidecar_sha256: { parameters: "a".repeat(64), measurements: "b".repeat(64) },
  },
} satisfies Awaited<ReturnType<typeof loadLuminaBoxStackSample>>;

beforeEach(() => {
  vi.resetAllMocks();
});

describe("Lumina Box stack sample API client", () => {
  it.each([false, true])("preserves the saved record and deduplicated=%s result", async (deduplicated) => {
    const response = { status: "success", record, deduplicated };
    const originalPayload = structuredClone(payload);
    mockPost.mockResolvedValueOnce({ data: response });

    const result = await saveLuminaBoxStackSample(payload);

    expect(mockPost).toHaveBeenCalledExactlyOnceWith(endpoint, originalPayload, { timeout: 15_000 });
    expect(payload).toEqual(originalPayload);
    expect(result).toEqual(response);
    expect(result.record.device_measurement).toEqual(delivery.measurement);
    expect(result.record.reflectance_percent_xyz[0]).toBe(103.25);
  });

  it("accepts the required capture fields without adding optional provenance", async () => {
    const minimalPayload = {
      recipe_top_to_bottom: payload.recipe_top_to_bottom,
      measurement: payload.measurement,
      capture_id: payload.capture_id,
    } satisfies Parameters<typeof saveLuminaBoxStackSample>[0];
    mockPost.mockResolvedValueOnce({ data: { status: "success", record, deduplicated: false } });

    await saveLuminaBoxStackSample(minimalPayload);

    expect(mockPost).toHaveBeenCalledExactlyOnceWith(endpoint, minimalPayload, { timeout: 15_000 });
  });

  it("unwraps the list while preserving measurement and reference details", async () => {
    mockGet.mockResolvedValueOnce({ data: { status: "success", records: [record] } });

    const result = await listLuminaBoxStackSamples();

    expect(mockGet).toHaveBeenCalledExactlyOnceWith(endpoint, { timeout: 15_000 });
    expect(result).toEqual([record]);
  });

  it("returns an empty list for an empty sample archive", async () => {
    mockGet.mockResolvedValueOnce({ data: { status: "success", records: [] } });

    await expect(listLuminaBoxStackSamples()).resolves.toEqual([]);
  });

  it.each([
    [record.record_id, record.record_id],
    ["capture/a b?revision=2#part", "capture%2Fa%20b%3Frevision%3D2%23part"],
  ])("loads only the encoded record path for %s", async (id, encodedId) => {
    mockGet.mockResolvedValueOnce({ data: { status: "success", record, deduplicated: false } });

    const result = await loadLuminaBoxStackSample(id);

    expect(mockGet).toHaveBeenCalledExactlyOnceWith(`${endpoint}/${encodedId}`, { timeout: 15_000 });
    expect(result).toEqual(record);
  });

  it.each([
    [record.record_id, record.record_id],
    ["capture/a b?revision=2#part", "capture%2Fa%20b%3Frevision%3D2%23part"],
  ])("deletes only the encoded record path for %s", async (id, encodedId) => {
    mockDelete.mockResolvedValueOnce({ data: { status: "success", record_id: record.record_id } });

    const result = await deleteLuminaBoxStackSample(id);

    expect(mockDelete).toHaveBeenCalledExactlyOnceWith(`${endpoint}/${encodedId}`, { timeout: 15_000 });
    expect(result).toBeUndefined();
  });

  it("returns the complete versioned JSON export within the shared 15-second timeout", async () => {
    const exported = {
      schema_version: "1.0",
      kind: "lumina_box_stack_samples_export",
      exported_at: "2026-10-05T16:05:00Z",
      records: [record],
    } satisfies Awaited<ReturnType<typeof exportLuminaBoxStackSamples>>;
    mockGet.mockResolvedValueOnce({ data: exported });

    const result = await exportLuminaBoxStackSamples();

    expect(mockGet).toHaveBeenCalledExactlyOnceWith(`${endpoint}/export`, { timeout: 15_000 });
    expect(result).toEqual(exported);
    expect(JSON.parse(JSON.stringify(result))).toEqual(exported);
  });

  it.each([
    { operation: "save", request: () => saveLuminaBoxStackSample(payload), mock: mockPost },
    { operation: "list", request: listLuminaBoxStackSamples, mock: mockGet },
    { operation: "load", request: () => loadLuminaBoxStackSample(record.record_id), mock: mockGet },
    { operation: "delete", request: () => deleteLuminaBoxStackSample(record.record_id), mock: mockDelete },
    { operation: "export", request: exportLuminaBoxStackSamples, mock: mockGet },
  ])("propagates $operation failures without reporting a successful capture", async ({ request, mock }) => {
    const error = new Error("Sample request failed");
    mock.mockRejectedValueOnce(error);

    await expect(request()).rejects.toBe(error);
    expect(mock).toHaveBeenCalledTimes(1);
  });
});
