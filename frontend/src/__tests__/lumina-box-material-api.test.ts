import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import * as api from "../api/luminaBoxMaterials";
import { gradientDataset, gradientRun } from "./fixtures/backedGradient";

vi.mock("../api/client", async (original) => ({ ...(await original<typeof import("../api/client")>()), default: { get: vi.fn(), post: vi.fn() } }));
const get = vi.mocked(apiClient.get);
const post = vi.mocked(apiClient.post);
const base = "/extractor/lumina-box/backed-gradient";
beforeEach(() => vi.clearAllMocks());

describe("Lumina Box product API contracts", () => {
  it("lists one latest option per backing group", async () => {
    const old = { reference_id: "ref-1", backing_id: "backing-a", version: 1, name: "White / Black", created_at: "2026-10-07T00:00:00Z" };
    const current = { ...old, reference_id: "ref-2", version: 2, created_at: "2026-10-07T01:00:00Z" };
    const other = { ...old, reference_id: "ref-other", backing_id: "backing-b", name: "Other" };
    get.mockResolvedValueOnce({ data: { references: [old, other, current] } });
    expect(await api.listLuminaBoxBackingReferences()).toEqual([current, other]);
  });
  it("uses a saved backing reference when creating one material", async () => {
    const dataset = gradientDataset();
    const request = { name: "Blue PETG", material_symbol: "B" as const, reference_id: "reference-1" };
    post.mockResolvedValueOnce({ data: { dataset } });
    expect(await api.createLuminaBoxMaterialDataset(request)).toEqual(dataset);
    expect(post).toHaveBeenCalledWith(`${base}/material-datasets`, request, { timeout: 15000 });
  });
  it("creates an arbitrary named material without sending a preset color", async () => {
    const dataset = gradientDataset();
    const request = { name: "Lavender PLA", white_backing_id: "white-a", black_backing_id: "black-b" };
    post.mockResolvedValueOnce({ data: { dataset } });
    await api.createLuminaBoxMaterialDataset(request);
    expect(post).toHaveBeenCalledWith(`${base}/material-datasets`, request, { timeout: 15000 });
  });
  it("lists and creates a backing material independently", async () => {
    const backings = [{ material_id: "white-a", name: "White A", role: "W", status: "ready" }];
    get.mockResolvedValueOnce({ data: { backings } });
    expect(await api.listLuminaBoxBackingMaterials()).toEqual(backings);
    expect(get).toHaveBeenCalledWith(`${base}/backing-materials`, { timeout: 15000 });
    const request = { name: "Black B", role: "K" as const, opposite_material_id: "white-a" };
    post.mockResolvedValueOnce({ data: { dataset: gradientDataset() } });
    await api.createLuminaBoxBackingMaterialDataset(request);
    expect(post).toHaveBeenCalledWith(`${base}/backing-material-datasets`, request, { timeout: 15000 });
  });
  it("separates backing calibration and single-material fit jobs", async () => {
    post.mockResolvedValue({ data: { run: gradientRun } });
    await api.startLuminaBoxMaterialFit("data/1", false, "M", "reference-1");
    expect(post).toHaveBeenLastCalledWith(`${base}/material-datasets/data%2F1/fit-runs`, { material_symbol: "M", reference_id: "reference-1" }, { timeout: 15000 });
    await api.startLuminaBoxMaterialFit("data/2", true, "W", "");
    expect(post).toHaveBeenLastCalledWith(`${base}/backing-datasets/data%2F2/fit-runs`, {}, { timeout: 15000 });
    await api.startLuminaBoxMaterialFit("data/3", "backing_material", "W", "");
    expect(post).toHaveBeenLastCalledWith(`${base}/backing-material-datasets/data%2F3/fit-runs`, {}, { timeout: 15000 });
  });
  it("unwraps fit results and preserves the saved archive identity", async () => {
    const result = { status: "complete", selected_record_ids: ["r1"], rmse_pp: .5 };
    get.mockResolvedValueOnce({ data: { result } });
    expect(await api.loadLuminaBoxMaterialFitResult("fit-1")).toEqual(result);
    const response = { status: "ok", message: "Material saved", material: { directory_name: "brand/blue" } };
    post.mockResolvedValueOnce({ data: response });
    const request = { name: "Blue", brand: "brand", material_type: "PETG", notes: "", overwrite: true };
    expect(await api.saveLuminaBoxMaterialArchive("fit-1", request)).toEqual(response);
    expect(post).toHaveBeenCalledWith(`${base}/material-fit-runs/fit-1/archive`, request, { timeout: 15000 });
  });
});
