import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api/luminaBoxMaterials";
import { useLuminaBoxMaterialFit } from "../hooks/useLuminaBoxMaterialFit";
import { gradientRun } from "./fixtures/backedGradient";

vi.mock("../api/luminaBoxMaterials", async (original) => ({ ...(await original<typeof api>()),
  listLuminaBoxMaterialFits: vi.fn(), loadLuminaBoxMaterialFit: vi.fn(), loadLuminaBoxMaterialFitResult: vi.fn(),
  startLuminaBoxMaterialFit: vi.fn(), saveLuminaBoxMaterialArchive: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

const materialRun = (fitId: string, datasetId = "dataset-1"): api.LuminaBoxMaterialFitRun => ({
  ...gradientRun, fit_id: fitId, dataset_id: datasetId, fit_mode: "material", material_symbol: "material", reference_id: "backing-1",
});
const newResult: api.LuminaBoxMaterialFitResult = { status: "complete", estimated_rgb: [125, 75, 30] };

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.listLuminaBoxMaterialFits).mockResolvedValue([]);
  vi.mocked(api.startLuminaBoxMaterialFit).mockResolvedValue(materialRun("new-fit"));
  vi.mocked(api.loadLuminaBoxMaterialFitResult).mockResolvedValue(newResult);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("single-material fit ownership", () => {
  it("restores an independently saved backing awaiting its opposite material", async () => {
    vi.mocked(api.listLuminaBoxMaterialFits).mockResolvedValue([{ ...gradientRun, fit_mode: "backing_material" }]);
    vi.mocked(api.loadLuminaBoxMaterialFitResult).mockResolvedValue({ status: "awaiting_opposite", backing_material_id: "white-a" });
    const { result } = renderHook(() => useLuminaBoxMaterialFit("dataset-1", "W", "", "backing_material"));
    await waitFor(() => expect(result.current.result?.status).toBe("awaiting_opposite"));
    expect(result.current.error).toBeNull();
    expect(result.current.running).toBe(false);
  });
  it.each([{ runs: [] }, { runs: [materialRun("historical-fit")] }])("keeps a newly completed fit when late history returns $runs", async ({ runs }) => {
    const history = deferred<api.LuminaBoxMaterialFitRun[]>();
    vi.mocked(api.listLuminaBoxMaterialFits).mockReturnValue(history.promise);
    const { result } = renderHook(() => useLuminaBoxMaterialFit("dataset-1", "material", "backing-1", false));
    await act(async () => { await result.current.start(); });
    await waitFor(() => expect(result.current.result).toEqual(newResult));
    await act(async () => { history.resolve(runs); });
    expect(result.current.run?.fit_id).toBe("new-fit");
    expect(result.current.result).toEqual(newResult);
    expect(api.loadLuminaBoxMaterialFitResult).toHaveBeenCalledExactlyOnceWith("new-fit");
  });

  it("ignores a late historical-list error after a new fit succeeds", async () => {
    const history = deferred<api.LuminaBoxMaterialFitRun[]>();
    vi.mocked(api.listLuminaBoxMaterialFits).mockReturnValue(history.promise);
    const { result } = renderHook(() => useLuminaBoxMaterialFit("dataset-1", "material", "backing-1", false));
    await act(async () => { await result.current.start(); });
    await waitFor(() => expect(result.current.result).toEqual(newResult));
    await act(async () => { history.reject(new Error("Historical list failed")); });
    expect(result.current.run?.fit_id).toBe("new-fit");
    expect(result.current.error).toBeNull();
  });

  it("keeps a new result when the previous result arrives afterwards", async () => {
    const oldResult = deferred<api.LuminaBoxMaterialFitResult>();
    vi.mocked(api.listLuminaBoxMaterialFits).mockResolvedValue([materialRun("historical-fit")]);
    vi.mocked(api.loadLuminaBoxMaterialFitResult).mockImplementation((id) => id === "historical-fit" ? oldResult.promise : Promise.resolve(newResult));
    const { result } = renderHook(() => useLuminaBoxMaterialFit("dataset-1", "material", "backing-1", false));
    await waitFor(() => expect(api.loadLuminaBoxMaterialFitResult).toHaveBeenCalledWith("historical-fit"));
    await act(async () => { await result.current.start(); });
    await waitFor(() => expect(result.current.result).toEqual(newResult));
    await act(async () => { oldResult.resolve({ status: "complete", estimated_rgb: [250, 250, 250] }); });
    expect(result.current.run?.fit_id).toBe("new-fit");
    expect(result.current.result).toEqual(newResult);
  });

  it("discards the old material's history after switching to another material", async () => {
    const firstHistory = deferred<api.LuminaBoxMaterialFitRun[]>();
    vi.mocked(api.listLuminaBoxMaterialFits).mockImplementation((id) => id === "dataset-1" ? firstHistory.promise : Promise.resolve([materialRun("other-fit", id)]));
    const { result, rerender } = renderHook(({ datasetId }) => useLuminaBoxMaterialFit(datasetId, "material", "backing-1", false),
      { initialProps: { datasetId: "dataset-1" } });
    rerender({ datasetId: "dataset-2" });
    await waitFor(() => expect(result.current.run?.fit_id).toBe("other-fit"));
    await act(async () => { firstHistory.resolve([materialRun("historical-fit")]); });
    expect(result.current.run?.dataset_id).toBe("dataset-2");
    expect(result.current.run?.fit_id).toBe("other-fit");
  });

  it.each(["switch", "unmount", "return"] as const)("ignores an old overwrite conflict after leaving its capture context (%s)", async (transition) => {
    const pendingSave = deferred<api.LuminaBoxSavedMaterial>();
    vi.mocked(api.saveLuminaBoxMaterialArchive).mockReturnValueOnce(pendingSave.promise);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { result, rerender, unmount } = renderHook(({ datasetId }) => useLuminaBoxMaterialFit(datasetId, "material", "backing-1", false),
      { initialProps: { datasetId: "dataset-1" } });
    await act(async () => { await result.current.start(); });
    let saving!: Promise<void>;
    act(() => { saving = result.current.save({ name: "Original archive", brand: "Brand", material_type: "PETG", notes: "" }); });
    expect(api.saveLuminaBoxMaterialArchive).toHaveBeenCalledTimes(1);
    if (transition === "unmount") unmount();
    else {
      rerender({ datasetId: "dataset-2" });
      if (transition === "return") rerender({ datasetId: "dataset-1" });
    }
    await act(async () => { pendingSave.reject({ response: { status: 409 } }); await saving; });
    expect(confirm).not.toHaveBeenCalled();
    expect(api.saveLuminaBoxMaterialArchive).toHaveBeenCalledTimes(1);
  });

  it("confirms and saves an overwrite when the original capture context is still active", async () => {
    const archive: api.LuminaBoxSavedMaterial = { status: "ok", message: "saved", material: {
      material_name: "Original archive", directory_name: "original", material_file_url: "/api/files/original", estimated_rgb: [125, 75, 30],
    } };
    vi.mocked(api.saveLuminaBoxMaterialArchive).mockRejectedValueOnce({ response: { status: 409 } }).mockResolvedValueOnce(archive);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { result } = renderHook(() => useLuminaBoxMaterialFit("dataset-1", "material", "backing-1", false));
    await act(async () => { await result.current.start(); });
    const metadata = { name: "Original archive", brand: "Brand", material_type: "PETG", notes: "" };
    await act(async () => { await result.current.save(metadata); });
    expect(confirm).toHaveBeenCalledOnce();
    expect(api.saveLuminaBoxMaterialArchive).toHaveBeenNthCalledWith(1, "new-fit", { ...metadata, overwrite: false });
    expect(api.saveLuminaBoxMaterialArchive).toHaveBeenNthCalledWith(2, "new-fit", { ...metadata, overwrite: true });
    expect(result.current.saved).toEqual(archive);
  });

  it("keeps the new run after returning to the same material before an older start completes", async () => {
    const pendingStart = deferred<api.LuminaBoxMaterialFitRun>();
    vi.mocked(api.startLuminaBoxMaterialFit).mockReturnValueOnce(pendingStart.promise).mockResolvedValueOnce(materialRun("latest-fit"));
    const { result, rerender } = renderHook(({ datasetId }) => useLuminaBoxMaterialFit(datasetId, "material", "backing-1", false),
      { initialProps: { datasetId: "dataset-1" } });
    let starting!: Promise<void>;
    act(() => { starting = result.current.start(); });
    rerender({ datasetId: "dataset-2" });
    rerender({ datasetId: "dataset-1" });
    await act(async () => { await result.current.start(); });
    expect(result.current.run?.fit_id).toBe("latest-fit");
    await act(async () => { pendingStart.resolve(materialRun("old-fit")); await starting; });
    expect(result.current.run?.fit_id).toBe("latest-fit");
    expect(result.current.result).toEqual(newResult);
    expect(result.current.error).toBeNull();
  });
});
