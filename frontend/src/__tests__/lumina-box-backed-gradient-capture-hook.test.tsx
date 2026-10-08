import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api/luminaBoxBackedGradient";
import { parseLuminaBoxFrame, type LuminaBoxCaptureResult, type LuminaBoxMeasurement } from "../api/luminaBoxSerial";
import { useLuminaBoxBackedGradient } from "../hooks/useLuminaBoxBackedGradient";
import type { LuminaBoxMaterialDataset } from "../api/luminaBoxMaterials";
import { useLuminaBoxBackedGradientSerialStore } from "../stores/luminaBoxBackedGradientSerialStore";
import { useSettingsStore, DEFAULT_SETTINGS } from "../stores/settingsStore";
import { BACKED_GRADIENT_MAX_IMPORT_BYTES, BACKED_GRADIENT_DRAFT_KEY } from "../utils/luminaBoxBackedGradientCapture";
import { appendGradientCapture, gradientDataset } from "./fixtures/backedGradient";
import wire from "./fixtures/lumina-box-seven-thickness-v3.jsonl?raw";

vi.mock("../api/luminaBoxBackedGradient", async (original) => ({ ...(await original<typeof api>()),
  listBackedGradientDatasets: vi.fn(), loadBackedGradientDataset: vi.fn(), saveBackedGradientCapture: vi.fn(),
  createBackedGradientDataset: vi.fn(), importBackedGradientDataset: vi.fn(),
}));

type Receiver = (measurement: LuminaBoxMeasurement) => LuminaBoxCaptureResult | Promise<LuminaBoxCaptureResult>;
let receiver: Receiver | null;
let dataset = gradientDataset();
let scope = 0;
const redWhite = { material_symbol: "R", backing: "W", sample_role: "coated" } as const;
const yellowBlack = { material_symbol: "Y", backing: "K", sample_role: "coated" } as const;

beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear(); receiver = null; dataset = gradientDataset(); scope = 0;
  useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  useLuminaBoxBackedGradientSerialStore.setState({ status: "disconnected", mode: "unknown", captureId: "scope-0",
    pendingCount: 0, issue: null, disconnect: vi.fn(async () => undefined), replay: vi.fn(),
    resetCapture: vi.fn(() => useLuminaBoxBackedGradientSerialStore.setState({ captureId: `scope-${++scope}`, pendingCount: 0 })),
    connect: vi.fn((callback: Receiver) => { receiver = callback; useLuminaBoxBackedGradientSerialStore.setState({ status: "connected", mode: "reliable" }); }),
  });
  vi.mocked(api.listBackedGradientDatasets).mockResolvedValue([dataset]);
  vi.mocked(api.loadBackedGradientDataset).mockResolvedValue(dataset);
  vi.mocked(api.saveBackedGradientCapture).mockImplementation(async (_id, payload) => {
    const result = appendGradientCapture(dataset, payload); dataset = result.dataset; return result;
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

async function ready() {
  const hook = renderHook(() => useLuminaBoxBackedGradient());
  await waitFor(() => expect(hook.result.current.dataset?.dataset_id).toBe("dataset-1"));
  return hook;
}

describe("backed-gradient user input protection", () => {
  it.each(["W", "K"] as const)("arms a separate %s backing and keeps its own bare sample distinct", async (role) => {
    const hook = await ready();
    const opposite = role === "W" ? "K" : "W";
    const next: LuminaBoxMaterialDataset = { ...gradientDataset("one-backing"), materials: { [role]: "Measured backing" },
      workflow: { kind: "backing_material", material_symbol: role, backing_material_id: "backing-a", opposite_material_id: "backing-b" } };
    vi.mocked(api.loadBackedGradientDataset).mockResolvedValueOnce(next);
    await act(async () => { await hook.result.current.loadDataset(next.dataset_id); });
    dataset = next;
    expect(hook.result.current.draft.target).toEqual({ material_symbol: role, backing: opposite, sample_role: "coated" });
    act(() => hook.result.current.updateDraft({ manualXYZ: ["0", "102.5", "3"] }));
    await act(async () => { await hook.result.current.saveManual(); });
    expect(api.saveBackedGradientCapture).toHaveBeenLastCalledWith(next.dataset_id,
      expect.objectContaining({ material_symbol: role, backing: opposite, overlay_mm: .08, reflectance_percent_xyz: [0, 102.5, 3] }));
    act(() => hook.result.current.selectSlot({ material_symbol: role, backing: role, sample_role: "bare_backing" }, 0));
    act(() => hook.result.current.updateDraft({ manualXYZ: ["0.2", "1", "2"] }));
    await act(async () => { await hook.result.current.saveManual(); });
    expect(api.saveBackedGradientCapture).toHaveBeenLastCalledWith(next.dataset_id,
      expect.objectContaining({ material_symbol: role, backing: role, sample_role: "bare_backing", overlay_mm: 0 }));
  });
  it("opens another measured material in the same historical collection without reconnecting", async () => {
    const hook = await ready();
    act(() => hook.result.current.connect());
    const oldCaptureId = useLuminaBoxBackedGradientSerialStore.getState().captureId;
    await act(async () => { await hook.result.current.loadDataset(dataset.dataset_id, yellowBlack); });
    expect(hook.result.current.draft.target).toEqual(yellowBlack);
    expect(hook.result.current.inspectedSlot).toBe("Y:K:0.08");
    expect(useLuminaBoxBackedGradientSerialStore.getState().captureId).not.toBe(oldCaptureId);
    expect(useLuminaBoxBackedGradientSerialStore.getState().disconnect).not.toHaveBeenCalled();
    act(() => hook.result.current.updateDraft({ manualXYZ: ["1", "2", "3"] }));
    await act(async () => { await hook.result.current.saveManual(); });
    expect(api.saveBackedGradientCapture).toHaveBeenLastCalledWith(dataset.dataset_id, expect.objectContaining(yellowBlack));
    expect(api.loadBackedGradientDataset).toHaveBeenCalledTimes(1);
  });

  it("keeps unfinished manual readings when another material is chosen from the same collection", async () => {
    const hook = await ready();
    act(() => hook.result.current.updateDraft({ manualXYZ: ["1", "2", "3"] }));
    await act(async () => { expect(await hook.result.current.loadDataset(dataset.dataset_id, yellowBlack)).toBeUndefined(); });
    expect(hook.result.current.draft.target).toEqual(redWhite);
    expect(hook.result.current.draft.manualXYZ).toEqual(["1", "2", "3"]);
  });

  it.each([
    { datasetId: "other-brand", target: redWhite },
    { datasetId: "dataset-1", target: redWhite },
    { datasetId: "dataset-1", target: yellowBlack },
  ])("preserves manual draft ownership when an initial request changes to $datasetId / $target", async ({ datasetId, target }) => {
    const original = { datasetId: dataset.dataset_id, target: { ...redWhite, backing: "K" },
      manualThickness: "0.64", manualXYZ: ["0", "102.4", "3"], sampleName: "Unsaved sample", notes: "Original notes" };
    localStorage.setItem(BACKED_GRADIENT_DRAFT_KEY, JSON.stringify(original));
    vi.mocked(api.loadBackedGradientDataset).mockImplementation(async (id) => id === dataset.dataset_id ? dataset : gradientDataset(id));
    const hook = renderHook(() => useLuminaBoxBackedGradient({ researchFits: false, initialDatasetId: datasetId, initialTarget: target }));
    expect(hook.result.current.draft).toEqual(original);
    await waitFor(() => expect(hook.result.current.dataset?.dataset_id).toBe(original.datasetId));
    expect(hook.result.current.captureNotice).toBe("lumina_box_bg_manual_unsaved");
    expect(hook.result.current.inspectedSlot).toBe("R:K:0.64");
    expect(JSON.parse(localStorage.getItem(BACKED_GRADIENT_DRAFT_KEY)!)).toEqual(original);
    await act(async () => { await hook.result.current.saveManual(); });
    expect(api.saveBackedGradientCapture).toHaveBeenCalledWith(original.datasetId, expect.objectContaining({
      ...original.target, overlay_mm: .64, reflectance_percent_xyz: [0, 102.4, 3], sample_name: original.sampleName, notes: original.notes,
    }));
    await act(async () => { await hook.result.current.loadDataset(datasetId, target); });
    expect(hook.result.current.draft.datasetId).toBe(datasetId);
    expect(hook.result.current.draft.target).toEqual(target);
  });

  it("uses the requested material immediately when opening a different historical collection", async () => {
    const hook = await ready();
    const next = gradientDataset("other-brand");
    vi.mocked(api.loadBackedGradientDataset).mockResolvedValueOnce(next);
    await act(async () => { await hook.result.current.loadDataset(next.dataset_id, yellowBlack); });
    dataset = next;
    expect(hook.result.current.draft.datasetId).toBe(next.dataset_id);
    expect(hook.result.current.draft.target).toEqual(yellowBlack);
    expect(hook.result.current.inspectedSlot).toBe("Y:K:0.08");
  });

  it("starts a fresh product visit without silently opening the most recent material", async () => {
    const hook = renderHook(() => useLuminaBoxBackedGradient({ researchFits: false }));
    await waitFor(() => expect(hook.result.current.datasetBusy).toBe(null));
    expect(hook.result.current.datasets).toHaveLength(1);
    expect(hook.result.current.dataset).toBeNull();
    expect(api.loadBackedGradientDataset).not.toHaveBeenCalled();
  });

  it("restores a real saved material instead of an unused historical color placeholder", async () => {
    dataset.materials = { R: "R", Y: "Y", B: "Existing blue", W: "W", K: "K", C: "C", M: "M", G: "G" };
    localStorage.setItem(BACKED_GRADIENT_DRAFT_KEY, JSON.stringify({ datasetId: dataset.dataset_id,
      target: { material_symbol: "C", backing: "W", sample_role: "coated" }, manualThickness: "0.08",
      manualXYZ: ["", "", ""], sampleName: "", notes: "" }));
    const hook = renderHook(() => useLuminaBoxBackedGradient({ researchFits: false }));
    await waitFor(() => expect(hook.result.current.dataset?.dataset_id).toBe(dataset.dataset_id));
    expect(hook.result.current.draft.target.material_symbol).toBe("B");
    expect(hook.result.current.inspectedSlot).toBe("B:W:0.08");
  });

  it.each(["load", "create", "import"])("arms the actual independent material immediately after %s", async (operation) => {
    const hook = await ready();
    act(() => hook.result.current.connect());
    const oldScope = useLuminaBoxBackedGradientSerialStore.getState().captureId;
    const next: LuminaBoxMaterialDataset = { ...gradientDataset("arbitrary-material"),
      name: "Apricot PETG", materials: { material: "Apricot PETG" },
      workflow: { kind: "material", material_symbol: "material", reference_id: "explicit-backing-pair" } };
    if (operation === "load") vi.mocked(api.loadBackedGradientDataset).mockResolvedValueOnce(next);
    if (operation === "create") vi.mocked(api.createBackedGradientDataset).mockResolvedValueOnce(next);
    if (operation === "import") vi.mocked(api.importBackedGradientDataset).mockResolvedValueOnce(next);
    await act(async () => {
      if (operation === "load") await hook.result.current.loadDataset(next.dataset_id);
      if (operation === "create") await hook.result.current.createDataset({ name: next.name });
      if (operation === "import") await hook.result.current.importDataset({ size: 100,
        text: async () => JSON.stringify({ kind: "lumina_box_backed_gradient_export", schema_version: "1.0", dataset: next }),
      } as File);
    });
    dataset = next;
    expect(hook.result.current.draft.target.material_symbol).toBe("material");
    expect(hook.result.current.inspectedSlot).toBe("material:W:0.08");
    expect(useLuminaBoxBackedGradientSerialStore.getState().captureId).not.toBe(oldScope);
    expect(useLuminaBoxBackedGradientSerialStore.getState().disconnect).not.toHaveBeenCalled();
    const parsed = wire.trim().split(/\r?\n/).map(parseLuminaBoxFrame)
      .find((frame) => frame.kind === "delivery" && frame.measurement.mode === "reflect" && frame.measurement.thickness_mm === .08);
    if (parsed?.kind !== "delivery") throw new Error("Missing device fixture");
    await act(async () => { expect(await receiver!({ ...parsed.measurement, measurement_id: "first-generic-reading" })).toBe("applied"); });
    expect(api.saveBackedGradientCapture).toHaveBeenLastCalledWith(next.dataset_id, expect.objectContaining({
      material_symbol: "material", backing: "W", sample_role: "coated",
    }));
  });

  it("restores generic material drafts and pending readings without relabeling them", async () => {
    const target = { material_symbol: "material", backing: "K", sample_role: "coated" } as const;
    const next: LuminaBoxMaterialDataset = { ...gradientDataset("arbitrary-material"), materials: { material: "Warm gray" },
      workflow: { kind: "material", material_symbol: "material", reference_id: "original-backing" } };
    dataset = next;
    vi.mocked(api.loadBackedGradientDataset).mockResolvedValue(next);
    localStorage.setItem(BACKED_GRADIENT_DRAFT_KEY, JSON.stringify({ datasetId: next.dataset_id, target,
      manualThickness: "0.64", manualXYZ: ["0", "102.4", "3"], sampleName: "", notes: "" }));
    const hook = renderHook(() => useLuminaBoxBackedGradient({ researchFits: false }));
    await waitFor(() => expect(hook.result.current.dataset?.dataset_id).toBe(next.dataset_id));
    vi.mocked(api.saveBackedGradientCapture).mockRejectedValueOnce(new Error("disconnected"));
    await act(async () => { await hook.result.current.saveManual(); });
    const request = vi.mocked(api.saveBackedGradientCapture).mock.calls[0][1];
    hook.unmount();
    const restored = renderHook(() => useLuminaBoxBackedGradient({ researchFits: false }));
    await waitFor(() => expect(restored.result.current.dataset?.dataset_id).toBe(next.dataset_id));
    expect(restored.result.current.draft.target).toEqual(target);
    expect(restored.result.current.draft.manualThickness).toBe("0.64");
    expect(restored.result.current.inspectedSlot).toBe("material:K:0.64");
    expect(restored.result.current.pending).toHaveLength(1);
    await act(async () => { await restored.result.current.retry(restored.result.current.pending[0].key); });
    expect(api.saveBackedGradientCapture).toHaveBeenLastCalledWith(next.dataset_id, request);
    expect(request.reflectance_percent_xyz).toEqual([0, 102.4, 3]);
    expect(restored.result.current.pending).toEqual([]);
  });

  it("resolves a historical material before arming when returning from an independent capture", async () => {
    const hook = await ready();
    const next: LuminaBoxMaterialDataset = { ...gradientDataset("generic"), materials: { material: "Gray" },
      workflow: { kind: "material", material_symbol: "material", reference_id: "pair" } };
    vi.mocked(api.loadBackedGradientDataset).mockResolvedValueOnce(next);
    await act(async () => { await hook.result.current.loadDataset(next.dataset_id); });
    vi.mocked(api.loadBackedGradientDataset).mockResolvedValueOnce(dataset);
    await act(async () => { await hook.result.current.loadDataset(dataset.dataset_id); });
    expect(hook.result.current.draft.target.material_symbol).toBe("R");
    expect(hook.result.current.inspectedSlot).toBe("R:W:0.08");
  });

  it("keeps failed readings distinct from another in-flight save", async () => {
    const hook = await ready();
    vi.mocked(api.saveBackedGradientCapture).mockRejectedValueOnce(new Error("save failed"));
    act(() => hook.result.current.updateDraft({ manualXYZ: ["1", "2", "3"] }));
    await act(async () => { await hook.result.current.saveManual(); });
    expect(hook.result.current.failedPending).toHaveLength(1);
    let finish!: (value: Awaited<ReturnType<typeof api.saveBackedGradientCapture>>) => void;
    vi.mocked(api.saveBackedGradientCapture).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    act(() => hook.result.current.updateDraft({ manualXYZ: ["4", "5", "6"] }));
    let saving!: Promise<void>;
    act(() => { saving = hook.result.current.saveManual(); });
    expect(hook.result.current.pending).toHaveLength(2);
    expect(hook.result.current.failedPending).toHaveLength(1);
    expect(hook.result.current.savingCount).toBe(1);
    const request = vi.mocked(api.saveBackedGradientCapture).mock.calls[1][1];
    await act(async () => { finish(appendGradientCapture(dataset, request)); await saving; });
    expect(hook.result.current.failedPending).toHaveLength(1);
  });
  it("restores the inspected cell from the saved manual thickness", async () => {
    localStorage.setItem(BACKED_GRADIENT_DRAFT_KEY, JSON.stringify({
      datasetId: "dataset-1", target: yellowBlack, manualThickness: "0.64", manualXYZ: ["", "", ""], sampleName: "", notes: "",
    }));
    const hook = await ready();
    expect(hook.result.current.inspectedSlot).toBe("Y:K:0.64");
    expect(hook.result.current.draft.manualThickness).toBe("0.64");
  });

  it("keeps the original target and device scope when draft storage fails", async () => {
    const hook = await ready();
    act(() => hook.result.current.connect());
    const before = { draft: structuredClone(hook.result.current.draft), captureId: useLuminaBoxBackedGradientSerialStore.getState().captureId };
    const originalSet = localStorage.setItem.bind(localStorage);
    const storage = vi.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
      if (key === BACKED_GRADIENT_DRAFT_KEY) throw new DOMException("Storage full", "QuotaExceededError");
      originalSet(key, value);
    });
    act(() => expect(hook.result.current.selectSlot(yellowBlack, .64)).toBe(false));
    expect(hook.result.current.draft).toEqual(before.draft);
    expect(useLuminaBoxBackedGradientSerialStore.getState().captureId).toBe(before.captureId);
    expect(hook.result.current.inspectedSlot).toBe("R:W:0.08");
    storage.mockRestore();
    const parsed = wire.trim().split(/\r?\n/).map(parseLuminaBoxFrame)
      .find((frame) => frame.kind === "delivery" && frame.measurement.mode === "reflect" && frame.measurement.thickness_mm === .08);
    if (parsed?.kind !== "delivery") throw new Error("Missing device fixture");
    await act(async () => { expect(await receiver!({ ...parsed.measurement, measurement_id: "after-storage-recovery" })).toBe("applied"); });
    expect(vi.mocked(api.saveBackedGradientCapture).mock.calls[0][1]).toMatchObject({ ...redWhite, capture_id: before.captureId });
  });

  it.each(["load", "create", "import"])("does not change record or device scope after a failed draft save during %s", async (operation) => {
    const hook = await ready();
    act(() => hook.result.current.connect());
    const captureId = useLuminaBoxBackedGradientSerialStore.getState().captureId;
    const next = gradientDataset("dataset-2");
    if (operation === "load") vi.mocked(api.loadBackedGradientDataset).mockResolvedValueOnce(next);
    if (operation === "create") vi.mocked(api.createBackedGradientDataset).mockResolvedValueOnce(next);
    if (operation === "import") vi.mocked(api.importBackedGradientDataset).mockResolvedValueOnce(next);
    const originalSet = localStorage.setItem.bind(localStorage);
    const storage = vi.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
      if (key === BACKED_GRADIENT_DRAFT_KEY) throw new DOMException("Storage full", "QuotaExceededError");
      originalSet(key, value);
    });
    await act(async () => {
      if (operation === "load") await hook.result.current.loadDataset("dataset-2");
      if (operation === "create") await hook.result.current.createDataset({ name: "next" });
      if (operation === "import") await hook.result.current.importDataset({ size: 20, text: async () => JSON.stringify({
        kind: "lumina_box_backed_gradient_export", schema_version: "1.0", dataset: next,
      }) } as File);
    });
    expect(hook.result.current.dataset?.dataset_id).toBe("dataset-1");
    expect(hook.result.current.draft.datasetId).toBe("dataset-1");
    expect(useLuminaBoxBackedGradientSerialStore.getState().captureId).toBe(captureId);
    expect(hook.result.current.storageAvailable).toBe(false);
    storage.mockRestore();
  });

  it.each([false, true])("does not move the selected cell backwards when older saves finish later (same timestamp: %s)", async (sameTimestamp) => {
    const hook = await ready();
    act(() => hook.result.current.connect());
    const operations: Array<{ request: Parameters<typeof api.saveBackedGradientCapture>[1]; resolve: (value: Awaited<ReturnType<typeof api.saveBackedGradientCapture>>) => void }> = [];
    vi.mocked(api.saveBackedGradientCapture).mockImplementation((_id, request) => new Promise((resolve) => { operations.push({ request, resolve }); }));
    const rows = wire.trim().split(/\r?\n/).map(parseLuminaBoxFrame);
    const first = rows.find((frame) => frame.kind === "delivery" && frame.measurement.mode === "reflect" && frame.measurement.thickness_mm === .08);
    const second = rows.find((frame) => frame.kind === "delivery" && frame.measurement.mode === "reflect" && frame.measurement.thickness_mm === .16);
    if (first?.kind !== "delivery" || second?.kind !== "delivery") throw new Error("Missing device fixture");
    vi.spyOn(Date.prototype, "toISOString").mockReturnValueOnce("2026-10-07T01:00:00.000Z")
      .mockReturnValueOnce(sameTimestamp ? "2026-10-07T01:00:00.000Z" : "2026-10-07T01:00:01.000Z");
    let firstPromise!: Promise<LuminaBoxCaptureResult>;
    let secondPromise!: Promise<LuminaBoxCaptureResult>;
    act(() => {
      firstPromise = Promise.resolve(receiver!({ ...first.measurement, measurement_id: "early-008" }));
      secondPromise = Promise.resolve(receiver!({ ...second.measurement, measurement_id: "later-016" }));
    });
    const oldResponse = appendGradientCapture(dataset, operations[0].request, "old-record");
    const newResponse = appendGradientCapture(oldResponse.dataset, operations[1].request, "new-record");
    await act(async () => { operations[1].resolve(newResponse); expect(await secondPromise).toBe("applied"); });
    await act(async () => { operations[0].resolve(oldResponse); expect(await firstPromise).toBe("applied"); });
    expect(hook.result.current.lastCapture?.measurement_id).toBe("later-016");
    expect(hook.result.current.inspectedSlot).toBe("R:W:0.16");
    expect(hook.result.current.draft.manualThickness).toBe("0.16");
    expect(hook.result.current.dataset?.captures).toHaveLength(2);
  });

  it("retains unsaved manual values, target and selection during every context switch", async () => {
    const hook = await ready();
    act(() => hook.result.current.updateDraft({ manualXYZ: ["31", "", "42"] }));
    const before = { ...hook.result.current.draft };
    act(() => expect(hook.result.current.selectSlot(yellowBlack, .64)).toBe(false));
    expect(hook.result.current.draft).toEqual(before);
    expect(hook.result.current.inspectedSlot).toBe("R:W:0.08");
    expect(hook.result.current.captureNotice).toBe("lumina_box_bg_manual_unsaved");
    await act(async () => {
      await hook.result.current.loadDataset("dataset-2");
      await hook.result.current.createDataset({ name: "next" });
      await hook.result.current.importDataset({ size: 10, text: vi.fn() } as unknown as File);
    });
    expect(api.loadBackedGradientDataset).toHaveBeenCalledTimes(1);
    expect(api.createBackedGradientDataset).not.toHaveBeenCalled();
    expect(api.importBackedGradientDataset).not.toHaveBeenCalled();
    act(() => hook.result.current.updateDraft({ manualThickness: "0.16", manualXYZ: ["", "", ""] }));
    expect(hook.result.current.draft).toEqual(before);
    expect(JSON.parse(localStorage.getItem(BACKED_GRADIENT_DRAFT_KEY)!).manualXYZ).toEqual(before.manualXYZ);
    act(() => hook.result.current.discardManual());
    act(() => expect(hook.result.current.selectSlot(yellowBlack, .64)).toBe(true));
    expect(hook.result.current.draft.target).toEqual(yellowBlack);
    expect(hook.result.current.draft.manualThickness).toBe("0.64");
    expect(hook.result.current.inspectedSlot).toBe("Y:K:0.64");
  });

  it("clears successful manual inputs while preserving stored zero and over-100 values", async () => {
    const hook = await ready();
    act(() => hook.result.current.updateDraft({ manualXYZ: ["101.25", "0", "3.4"] }));
    await act(async () => { await hook.result.current.saveManual(); });
    expect(hook.result.current.draft.manualXYZ).toEqual(["", "", ""]);
    expect(hook.result.current.hasUnsavedManual).toBe(false);
    expect(hook.result.current.lastCapture?.reflectance_percent_xyz).toEqual([101.25, 0, 3.4]);
    act(() => expect(hook.result.current.selectSlot(yellowBlack, .64)).toBe(true));
    expect(hook.result.current.draft.target).toEqual(yellowBlack);
  });

  it("keeps a failed request and clears matching inputs only after a successful retry", async () => {
    const hook = await ready();
    vi.mocked(api.saveBackedGradientCapture).mockRejectedValueOnce(new Error("Internal worker detail"));
    act(() => hook.result.current.updateDraft({ manualXYZ: ["31", "40", "42"] }));
    await act(async () => { await hook.result.current.saveManual(); });
    const request = structuredClone(vi.mocked(api.saveBackedGradientCapture).mock.calls[0]);
    expect(hook.result.current.draft.manualXYZ).toEqual(["31", "40", "42"]);
    expect(hook.result.current.error).not.toContain("Internal worker detail");
    act(() => expect(hook.result.current.selectSlot(yellowBlack, .64)).toBe(false));
    await act(async () => { await hook.result.current.retry(hook.result.current.pending[0].key); });
    expect(vi.mocked(api.saveBackedGradientCapture).mock.calls[1]).toEqual(request);
    expect(hook.result.current.draft.manualXYZ).toEqual(["", "", ""]);
    expect(hook.result.current.pending).toEqual([]);
  });

  it("uses actual device thickness after choosing a different table cell", async () => {
    const hook = await ready();
    act(() => hook.result.current.connect());
    act(() => expect(hook.result.current.selectSlot(redWhite, .24)).toBe(true));
    const parsed = wire.trim().split(/\r?\n/).map(parseLuminaBoxFrame)
      .find((frame) => frame.kind === "delivery" && frame.measurement.mode === "reflect" && frame.measurement.thickness_mm === .08);
    if (parsed?.kind !== "delivery") throw new Error("Missing device fixture");
    await act(async () => { expect(await receiver!({ ...parsed.measurement, measurement_id: "actual-008" })).toBe("applied"); });
    expect(vi.mocked(api.saveBackedGradientCapture).mock.calls[0][1]).toMatchObject({ overlay_mm: .08, measurement: { thickness_mm: .08 } });
    expect(hook.result.current.inspectedSlot).toBe("R:W:0.08");
    expect(hook.result.current.draft.manualThickness).toBe("0.08");
  });

  it("rejects oversized imports before reading the file or sending it", async () => {
    const hook = await ready();
    const text = vi.fn();
    await act(async () => { await hook.result.current.importDataset({ size: BACKED_GRADIENT_MAX_IMPORT_BYTES + 1, text } as unknown as File); });
    expect(text).not.toHaveBeenCalled();
    expect(api.importBackedGradientDataset).not.toHaveBeenCalled();
    expect(hook.result.current.dataset?.dataset_id).toBe("dataset-1");
  });
});
