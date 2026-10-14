import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import * as api from "../api/luminaBoxBackedGradient";
import { gradientDataset, gradientRun } from "./fixtures/backedGradient";

vi.mock("../api/client", async (original) => ({ ...(await original<typeof import("../api/client")>()),
  default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));
const get = vi.mocked(apiClient.get); const post = vi.mocked(apiClient.post); const remove = vi.mocked(apiClient.delete);
const base = "/extractor/lumina-box/backed-gradient";
const dataset = gradientDataset();
beforeEach(() => vi.clearAllMocks());

describe("backed-gradient API", () => {
  it("encodes dataset identifiers and uses the bounded request timeout", async () => {
    get.mockResolvedValueOnce({ data: { dataset } });
    await expect(api.loadBackedGradientDataset("data/a b?revision=2#part")).resolves.toEqual(dataset);
    expect(get).toHaveBeenCalledExactlyOnceWith(`${base}/datasets/data%2Fa%20b%3Frevision%3D2%23part`, { timeout: 15000 });
  });

  it("preserves raw device fields and values for bare-backing captures", async () => {
    const payload: api.BackedGradientCaptureRequest = { capture_id: "scope", material_symbol: "K", backing: "K", sample_role: "bare_backing", overlay_mm: 0,
      measurement: { protocol: "lumina-box", version: 2, type: "measurement", measurement_id: "reading", mode: "reflect", thickness_mm: 2,
        reflectance_xyz: [103.25, 48.25, 51.125], thickness_schedule_id: "backed_gradient_7/v1" } };
    const before = structuredClone(payload); post.mockResolvedValueOnce({ data: { record: { id: "record" }, deduplicated: true, dataset } });
    expect(await api.saveBackedGradientCapture("dataset-1", payload)).toMatchObject({ deduplicated: true, dataset });
    expect(post).toHaveBeenCalledWith(`${base}/datasets/dataset-1/captures`, before, { timeout: 15000 });
    expect(payload).toEqual(before);
  });

  it("starts the complete one-click flow with the seven-thickness flag", async () => {
    post.mockResolvedValueOnce({ data: { run: gradientRun } });
    await expect(api.startBackedGradientFit("dataset-1", true)).resolves.toEqual(gradientRun);
    expect(post).toHaveBeenCalledExactlyOnceWith(`${base}/datasets/dataset-1/fit-runs`, { include_validation_thickness: true }, { timeout: 15000 });
  });

  it("retains the full portable import/export envelope", async () => {
    const envelope = { schema_version: "1.0", kind: "lumina_box_backed_gradient_export", dataset } as const;
    get.mockResolvedValueOnce({ data: envelope }); post.mockResolvedValueOnce({ data: { dataset } });
    await expect(api.exportBackedGradientDataset("dataset-1")).resolves.toEqual(envelope);
    await expect(api.importBackedGradientDataset(envelope)).resolves.toEqual(dataset);
    expect(post).toHaveBeenCalledWith(`${base}/import`, envelope, { timeout: 15000 });
  });

  it("keeps selection separate from deletion and escapes record paths", async () => {
    post.mockResolvedValueOnce({ data: { dataset } }); remove.mockResolvedValueOnce({ data: { dataset } });
    await api.selectBackedGradientCapture("dataset-1", "reading/1");
    await api.deleteBackedGradientCapture("dataset-1", "reading/1");
    expect(post).toHaveBeenCalledWith(`${base}/datasets/dataset-1/selection`, { record_id: "reading/1" }, { timeout: 15000 });
    expect(remove).toHaveBeenCalledWith(`${base}/datasets/dataset-1/captures/reading%2F1`, { timeout: 15000 });
  });

  it("requests a Blob only for browser fit exports", async () => {
    const blob = new Blob(["data"]); get.mockResolvedValueOnce({ data: blob });
    await expect(api.downloadBackedGradientFit("fit/a", "png")).resolves.toBe(blob);
    expect(get).toHaveBeenCalledWith(`${base}/fit-runs/fit%2Fa/exports/png`, { timeout: 15000, responseType: "blob" });
    expect(api.getBackedGradientExportUrl("data/a")).toContain("/api/extractor/lumina-box/backed-gradient/datasets/data%2Fa/export");
    expect(api.getBackedGradientFitExportUrl("fit/a", "json")).toContain("/api/extractor/lumina-box/backed-gradient/fit-runs/fit%2Fa/exports/json");
  });

  it("propagates save failures without returning a success receipt", async () => {
    const error = new Error("database unavailable"); post.mockRejectedValueOnce(error);
    await expect(api.saveBackedGradientCapture("dataset-1", { capture_id: "scope", material_symbol: "R", backing: "W", sample_role: "coated",
      overlay_mm: .08, measurement_id: "manual", reflectance_percent_xyz: [1, 2, 3] })).rejects.toBe(error);
  });
});
