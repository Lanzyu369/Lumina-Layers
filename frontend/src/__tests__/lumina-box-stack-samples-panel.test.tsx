import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LuminaBoxStackSamplesPanel from "../components/LuminaBoxStackSamplesPanel";
import {
  deleteLuminaBoxStackSample, exportLuminaBoxStackSamples, listLuminaBoxStackSamples,
  loadLuminaBoxStackSample, saveLuminaBoxStackSample,
  type LuminaBoxStackSampleRecord, type LuminaBoxStackSampleRequest, type LuminaBoxStackSampleResponse,
} from "../api/luminaBoxStackSamples";
import { listLuminaBoxMaterials } from "../api/extractor";
import type { LuminaBoxCaptureResult, LuminaBoxMeasurement } from "../api/luminaBoxSerial";
import { useLuminaBoxStackSerialStore } from "../stores/luminaBoxStackSerialStore";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import { LUMINA_BOX_STACK_CAPTURE_KEY, LUMINA_BOX_STACK_DRAFT_KEY } from "../utils/luminaBoxStackCapture";

vi.mock("../api/luminaBoxStackSamples", () => ({
  deleteLuminaBoxStackSample: vi.fn(), exportLuminaBoxStackSamples: vi.fn(),
  listLuminaBoxStackSamples: vi.fn(), loadLuminaBoxStackSample: vi.fn(), saveLuminaBoxStackSample: vi.fn(),
}));
vi.mock("../api/extractor", () => ({ listLuminaBoxMaterials: vi.fn() }));

type Receiver = (measurement: LuminaBoxMeasurement) => LuminaBoxCaptureResult | Promise<LuminaBoxCaptureResult>;
let receive: Receiver | null = null;
let recordSequence = 0;
const originalSerial = Object.getOwnPropertyDescriptor(navigator, "serial");
const connect = vi.fn((callback: Receiver) => {
  receive = callback;
  useLuminaBoxStackSerialStore.setState({ status: "connected", mode: "reliable" });
});
const disconnect = vi.fn(async () => { useLuminaBoxStackSerialStore.setState({ status: "disconnected", mode: "unknown" }); });
const replay = vi.fn();

function frame(id = "measurement-1", thickness = .08): LuminaBoxMeasurement {
  return { protocol: "lumina-box", version: 2, type: "measurement", measurement_id: id,
    mode: "auto", thickness_mm: thickness, reflectance_xyz: [103.25, 48.25, 51.125], transmittance_xyz: [12, 13, 14] };
}

function recordFor(request: LuminaBoxStackSampleRequest, id?: string): LuminaBoxStackSampleRecord {
  const index = ++recordSequence;
  const reflection = request.measurement.mode === "transmit" ? [0, 0, 0] as [number, number, number] : request.measurement.reflectance_xyz;
  return {
    schema_version: "1.0", kind: "lumina_box_stack_sample", data_role: "actual_measured_multimaterial_reflectance",
    record_id: id ?? `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
    created_at: new Date(Date.UTC(2026, 9, 6, 1, 0, index)).toISOString(), received_at: request.received_at ?? "2026-10-06T00:59:00Z",
    capture_id: request.capture_id, recipe_top_to_bottom: request.recipe_top_to_bottom,
    sample_name: request.sample_name ?? "", material_batch: request.material_batch ?? "", notes: request.notes ?? "",
    reference_directory_name: request.reference_directory_name ?? null,
    measurement_backing_percent_xyz: request.measurement_backing_percent_xyz ?? null,
    geometry: { upper_layer_count: request.recipe_top_to_bottom.length, upper_layer_height_mm: .08,
      first_layer_height_mm: .2, total_layer_count: 36, upper_mm: request.recipe_top_to_bottom.length * .08,
      white_base_mm: 3 - request.recipe_top_to_bottom.length * .08, total_mm: 3,
      full_recipe_top_to_bottom: request.recipe_top_to_bottom + "W".repeat(36 - request.recipe_top_to_bottom.length),
      layer_heights_mm_top_to_bottom: [...Array<number>(35).fill(.08), .2] },
    reflectance_percent_xyz: reflection, reflectance_relative_xyz: reflection.map((value) => value / 100) as [number, number, number],
    display_rgb: [255, 153, 190], display_hex: "#FF99BE", device_measurement: request.measurement,
    reference_context: { status: "not_selected", archive_id: null, revision_id: null, reference_id: null, sidecar_sha256: {} },
  };
}

const draftValue = (recipe = "RYBWYY") => ({ recipe, sampleName: "", materialBatch: "", notes: "", referenceDirectoryName: "" });
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

async function ready(recipe = "RYBWYY") {
  const view = render(<LuminaBoxStackSamplesPanel />);
  await waitFor(() => expect(screen.getByTestId("lumina-box-stack-refresh")).not.toBeDisabled());
  fireEvent.change(screen.getByTestId("lumina-box-stack-recipe"), { target: { value: recipe } });
  fireEvent.click(screen.getByTestId("lumina-box-stack-connect"));
  expect(receive).not.toBeNull();
  return view;
}

async function deliver(measurement: LuminaBoxMeasurement) {
  let result: LuminaBoxCaptureResult | undefined;
  await act(async () => { result = await receive!(measurement); });
  return result;
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  receive = null;
  recordSequence = 0;
  Object.defineProperty(navigator, "serial", { configurable: true, value: { requestPort: vi.fn() } });
  useSettingsStore.setState({ ...DEFAULT_SETTINGS, luminaBoxMeasurementBackingPercentXYZ: ["19.8", "19.7", "24.7"] });
  useLuminaBoxStackSerialStore.setState({
    status: "disconnected", mode: "unknown", issue: null, captureId: "stack-session-1",
    receivedCount: 0, lastMeasurement: null, pendingCount: 0,
    connect, disconnect, replay,
  });
  vi.mocked(listLuminaBoxMaterials).mockResolvedValue({ status: "ok", message: "", materials: [], outdated_count: 0 });
  vi.mocked(listLuminaBoxStackSamples).mockResolvedValue([]);
  vi.mocked(saveLuminaBoxStackSample).mockImplementation(async (request) => ({ status: "success", record: recordFor(request), deduplicated: false }));
  vi.mocked(deleteLuminaBoxStackSample).mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  if (originalSerial) Object.defineProperty(navigator, "serial", originalSerial);
  else Reflect.deleteProperty(navigator, "serial");
});

describe("printed stack sample capture", () => {
  it("shows the top-to-bottom 3 mm geometry and validates all supported letters", async () => {
    render(<LuminaBoxStackSamplesPanel />);
    expect(screen.getByTestId("lumina-box-stack-connect")).toBeDisabled();
    expect(screen.getByTestId("lumina-box-stack-serial-status")).toHaveTextContent("任意厚度");
    expect(screen.getByTestId("lumina-box-stack-serial-status")).toHaveTextContent("保存样片");
    fireEvent.change(screen.getByTestId("lumina-box-stack-recipe"), { target: { value: "ry bw yy" } });
    expect(screen.getByTestId("lumina-box-stack-recipe")).toHaveValue("RYBWYY");
    expect(screen.getByTestId("lumina-box-stack-geometry")).toHaveTextContent("0.48 mm + 白底 2.52 mm = 3.00 mm");
    expect(screen.getByTestId("lumina-box-stack-letter-legend")).toHaveTextContent("B 蓝");
    expect(screen.getByTestId("lumina-box-stack-letter-legend")).toHaveTextContent("K 黑");
    fireEvent.change(screen.getByTestId("lumina-box-stack-recipe"), { target: { value: "W".repeat(35) } });
    expect(screen.getByTestId("lumina-box-stack-geometry")).toHaveTextContent("2.80 mm + 白底 0.20 mm");
    fireEvent.change(screen.getByTestId("lumina-box-stack-recipe"), { target: { value: "WRYBCMGK" } });
    expect(screen.getByTestId("lumina-box-stack-connect")).not.toBeDisabled();
    fireEvent.change(screen.getByTestId("lumina-box-stack-recipe"), { target: { value: "RGBX" } });
    expect(screen.getByTestId("lumina-box-stack-connect")).toBeDisabled();
    await waitFor(() => expect(listLuminaBoxStackSamples).toHaveBeenCalledOnce());
  });

  it("waits for durable save, freezes the payload and ignores the device thickness for geometry", async () => {
    const saving = deferred<LuminaBoxStackSampleResponse>();
    vi.mocked(saveLuminaBoxStackSample).mockReturnValueOnce(saving.promise);
    await ready();
    let delivery!: Promise<LuminaBoxCaptureResult>;
    const measurement = frame("auto-1", 1.6);
    act(() => { delivery = Promise.resolve(receive!(measurement)); });
    const payload = vi.mocked(saveLuminaBoxStackSample).mock.calls[0][0];
    expect(payload).toMatchObject({ recipe_top_to_bottom: "RYBWYY", capture_id: "stack-session-1", measurement,
      measurement_backing_percent_xyz: [19.8, 19.7, 24.7] });
    expect(payload.received_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(JSON.parse(localStorage.getItem(LUMINA_BOX_STACK_CAPTURE_KEY)!)[0].receivedAt).toBe(payload.received_at);
    expect(screen.getByTestId("lumina-box-stack-recipe")).toBeDisabled();
    fireEvent.change(screen.getByTestId("lumina-box-stack-recipe"), { target: { value: "CCCCC" } });
    expect(screen.getByTestId("lumina-box-stack-recipe")).toHaveValue("RYBWYY");
    expect(screen.queryByTestId("lumina-box-stack-measured-hex")).not.toBeInTheDocument();
    const saved = recordFor(payload);
    let result: LuminaBoxCaptureResult | undefined;
    await act(async () => { saving.resolve({ status: "success", record: saved, deduplicated: false }); result = await delivery; });
    expect(result).toBe("applied");
    expect(screen.getByTestId("lumina-box-stack-measured-hex")).toHaveTextContent("#FF99BE");
    expect(screen.getByTestId("lumina-box-stack-measured-xyz")).toHaveTextContent("103.2500");
    expect(screen.getByTestId("lumina-box-stack-transmitted-xyz")).toHaveTextContent("X 12.000000");
    expect(screen.getByTestId("lumina-box-stack-transmitted-xyz")).toHaveTextContent("Y 13.000000");
    expect(screen.getByTestId("lumina-box-stack-transmitted-xyz")).toHaveTextContent("Z 14.000000");
    expect(screen.getByTestId("lumina-box-stack-recipe")).not.toBeDisabled();
    expect(saved.geometry.total_mm).toBe(3);
    expect(saved.device_measurement.thickness_mm).toBe(1.6);
  });

  it("keeps one connection while changing recipes and saves three repeats as separate records", async () => {
    await ready("RYBWY");
    for (let index = 0; index < 3; index += 1) expect(await deliver(frame(`repeat-${index}`, .16))).toBe("applied");
    fireEvent.change(screen.getByTestId("lumina-box-stack-recipe"), { target: { value: "CCMMM" } });
    expect(await deliver(frame("next-recipe", 3))).toBe("applied");
    expect(connect).toHaveBeenCalledOnce();
    expect(vi.mocked(saveLuminaBoxStackSample).mock.calls.map(([request]) => request.recipe_top_to_bottom)).toEqual(["RYBWY", "RYBWY", "RYBWY", "CCMMM"]);
    expect(screen.getAllByTestId(/^lumina-box-stack-record-000/)).toHaveLength(4);
  });

  it("retries the original recipe, timestamp and settings after an HTTP failure and a later edit", async () => {
    vi.mocked(saveLuminaBoxStackSample).mockRejectedValueOnce(new Error("network unavailable"));
    await ready("RYBWYY");
    expect(await deliver(frame("retry-original", .08))).toBe("storage_unavailable");
    const first = structuredClone(vi.mocked(saveLuminaBoxStackSample).mock.calls[0][0]);
    expect(screen.getByTestId("lumina-box-stack-pending")).toHaveTextContent("RYBWYY");
    expect(screen.queryByTestId("lumina-box-stack-measured-hex")).not.toBeInTheDocument();
    fireEvent.change(screen.getByTestId("lumina-box-stack-recipe"), { target: { value: "CCMMM" } });
    act(() => { useSettingsStore.setState({ luminaBoxMeasurementBackingPercentXYZ: ["21", "22", "23"] }); });
    fireEvent.click(screen.getByTestId("lumina-box-stack-retry-retry-original"));
    await screen.findByTestId("lumina-box-stack-measured-hex");
    expect(vi.mocked(saveLuminaBoxStackSample).mock.calls[1][0]).toEqual(first);
    expect(screen.getByTestId("lumina-box-stack-recipe")).toHaveValue("CCMMM");
    expect(screen.getByTestId("lumina-box-stack-saved-recipe")).toHaveTextContent("RYBWYY");
    expect(replay).toHaveBeenCalledOnce();
    expect(await deliver(frame("retry-original", .08))).toBe("applied");
    expect(saveLuminaBoxStackSample).toHaveBeenCalledTimes(2);
  });

  it("restores a failed pending target after leaving the page without restoring old settings", async () => {
    vi.mocked(saveLuminaBoxStackSample).mockRejectedValueOnce(new Error("offline"));
    const view = await ready("MMYYY");
    await deliver(frame("pending-roundtrip", .64));
    const original = structuredClone(vi.mocked(saveLuminaBoxStackSample).mock.calls[0][0]);
    fireEvent.change(screen.getByTestId("lumina-box-stack-recipe"), { target: { value: "CCYYY" } });
    view.unmount();
    useSettingsStore.setState({ luminaBoxMeasurementBackingPercentXYZ: ["31", "32", "33"] });
    render(<StrictMode><LuminaBoxStackSamplesPanel /></StrictMode>);
    expect(screen.getByTestId("lumina-box-stack-recipe")).toHaveValue("CCYYY");
    expect(useSettingsStore.getState().luminaBoxMeasurementBackingPercentXYZ).toEqual(["31", "32", "33"]);
    fireEvent.click(screen.getByTestId("lumina-box-stack-retry-pending-roundtrip"));
    await screen.findByTestId("lumina-box-stack-measured-hex");
    expect(vi.mocked(saveLuminaBoxStackSample).mock.calls[1][0]).toEqual(original);
  });

  it("rejects transmission-only captures and never reassigns an invalid-recipe reading on replay", async () => {
    await ready();
    const transmitted: LuminaBoxMeasurement = { protocol: "lumina-box", version: 2, type: "measurement", measurement_id: "transmit-only", mode: "transmit", thickness_mm: .08, transmittance_xyz: [12, 13, 14] };
    expect(await deliver(transmitted)).toBe("unsupported_mode");
    fireEvent.change(screen.getByTestId("lumina-box-stack-recipe"), { target: { value: "" } });
    expect(await deliver(frame("unassigned"))).toBe("invalid_recipe");
    fireEvent.change(screen.getByTestId("lumina-box-stack-recipe"), { target: { value: "CCMMM" } });
    expect(await deliver(frame("unassigned"))).toBe("invalid_recipe");
    expect(saveLuminaBoxStackSample).not.toHaveBeenCalled();
    expect(await deliver(frame("retaken"))).toBe("applied");
  });

  it("accepts reflection-only frames with their original high channels", async () => {
    await ready();
    const measurement: LuminaBoxMeasurement = { protocol: "lumina-box", version: 2, type: "measurement", measurement_id: "reflect-raw", mode: "reflect", thickness_mm: 6.4, reflectance_xyz: [103.25, 48.25, 51.125] };
    expect(await deliver(measurement)).toBe("applied");
    expect(vi.mocked(saveLuminaBoxStackSample).mock.calls[0][0].measurement).toEqual(measurement);
  });

  it("preserves metadata and empty drafts without overwriting the current instrument settings", async () => {
    localStorage.setItem(LUMINA_BOX_STACK_DRAFT_KEY, JSON.stringify({ ...draftValue(""), sampleName: "Card 20", materialBatch: "same-batch", notes: "keep note", referenceDirectoryName: "old-reference" }));
    const view = render(<StrictMode><LuminaBoxStackSamplesPanel /></StrictMode>);
    expect(screen.getByTestId("lumina-box-stack-name")).toHaveValue("Card 20");
    expect(screen.getByTestId("lumina-box-stack-batch")).toHaveValue("same-batch");
    expect(screen.getByTestId("lumina-box-stack-notes")).toHaveValue("keep note");
    expect(screen.getByTestId("lumina-box-stack-recipe")).toHaveValue("");
    view.unmount();
    useSettingsStore.setState({ luminaBoxMeasurementBackingPercentXYZ: ["1", "2", "3"] });
    render(<StrictMode><LuminaBoxStackSamplesPanel /></StrictMode>);
    expect(screen.getByTestId("lumina-box-stack-recipe")).toHaveValue("");
    expect(useSettingsStore.getState().luminaBoxMeasurementBackingPercentXYZ).toEqual(["1", "2", "3"]);
    await waitFor(() => expect(screen.getByTestId("lumina-box-stack-refresh")).not.toBeDisabled());
  });

  it("ignores an old list response after a newer capture is saved", async () => {
    const listing = deferred<LuminaBoxStackSampleRecord[]>();
    vi.mocked(listLuminaBoxStackSamples).mockReturnValueOnce(listing.promise);
    render(<LuminaBoxStackSamplesPanel />);
    fireEvent.change(screen.getByTestId("lumina-box-stack-recipe"), { target: { value: "RYBWYY" } });
    fireEvent.click(screen.getByTestId("lumina-box-stack-connect"));
    await deliver(frame("newer-than-list"));
    await act(async () => { listing.resolve([]); });
    expect(screen.getAllByTestId(/^lumina-box-stack-record-000/)).toHaveLength(1);
  });

  it("does not publish a late save or overwrite the next page's draft after unmount", async () => {
    const saving = deferred<LuminaBoxStackSampleResponse>();
    vi.mocked(saveLuminaBoxStackSample).mockReturnValueOnce(saving.promise);
    const view = await ready("RYBWYY");
    let delivery!: Promise<LuminaBoxCaptureResult>;
    act(() => { delivery = Promise.resolve(receive!(frame("late-after-unmount"))); });
    const oldPayload = vi.mocked(saveLuminaBoxStackSample).mock.calls[0][0];
    view.unmount();
    localStorage.setItem(LUMINA_BOX_STACK_DRAFT_KEY, JSON.stringify(draftValue("CCMMM")));
    render(<LuminaBoxStackSamplesPanel />);
    let outcome: LuminaBoxCaptureResult | undefined;
    await act(async () => { saving.resolve({ status: "success", record: recordFor(oldPayload), deduplicated: false }); outcome = await delivery; });
    expect(outcome).toBe("storage_unavailable");
    expect(screen.getByTestId("lumina-box-stack-recipe")).toHaveValue("CCMMM");
    expect(screen.queryByTestId("lumina-box-stack-measured-hex")).not.toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem(LUMINA_BOX_STACK_DRAFT_KEY)!).recipe).toBe("CCMMM");
    expect(JSON.parse(localStorage.getItem(LUMINA_BOX_STACK_CAPTURE_KEY)!)[0].outcome).toBe("pending");
  });

  it("retains a reading when local storage fails and saves it after storage recovers", async () => {
    await ready();
    const originalSet = localStorage.setItem.bind(localStorage);
    const storage = vi.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
      if (key === LUMINA_BOX_STACK_CAPTURE_KEY) throw new Error("storage full");
      originalSet(key, value);
    });
    expect(await deliver(frame("storage-retry"))).toBe("storage_unavailable");
    expect(saveLuminaBoxStackSample).not.toHaveBeenCalled();
    expect(screen.getByTestId("lumina-box-stack-storage-error")).toBeInTheDocument();
    storage.mockRestore();
    fireEvent.click(screen.getByTestId("lumina-box-stack-retry-storage-retry"));
    await screen.findByTestId("lumina-box-stack-measured-hex");
    expect(saveLuminaBoxStackSample).toHaveBeenCalledOnce();
  });
});

describe("saved stack records", () => {
  it("views and deletes only the selected record while preserving the current recipe", async () => {
    const older = recordFor({ recipe_top_to_bottom: "CCMMM", capture_id: "old", measurement: frame("older") });
    const newer = recordFor({ recipe_top_to_bottom: "RYBWYY", capture_id: "old", measurement: frame("newer") });
    vi.mocked(listLuminaBoxStackSamples).mockResolvedValue([newer, older]);
    vi.mocked(loadLuminaBoxStackSample).mockImplementation(async (id) => id === older.record_id ? older : newer);
    await ready("WCMYGK");
    fireEvent.click(screen.getByTestId(`lumina-box-stack-view-${older.record_id}`));
    await screen.findByTestId("lumina-box-stack-selected-detail");
    expect(screen.getByTestId("lumina-box-stack-recipe")).toHaveValue("WCMYGK");
    expect(screen.getByTestId("lumina-box-stack-saved-recipe")).toHaveTextContent("RYBWYY");
    expect(screen.getByTestId("lumina-box-stack-detail-transmitted-xyz")).toHaveTextContent("X 12.000000");
    expect(screen.getByTestId("lumina-box-stack-detail-transmitted-xyz")).toHaveTextContent("Y 13.000000");
    expect(screen.getByTestId("lumina-box-stack-detail-transmitted-xyz")).toHaveTextContent("Z 14.000000");
    fireEvent.click(screen.getByTestId("lumina-box-stack-delete-selected"));
    await waitFor(() => expect(screen.queryByTestId(`lumina-box-stack-record-${older.record_id}`)).not.toBeInTheDocument());
    expect(deleteLuminaBoxStackSample).toHaveBeenCalledExactlyOnceWith(older.record_id);
    expect(screen.getByTestId(`lumina-box-stack-record-${newer.record_id}`)).toBeInTheDocument();
    expect(screen.getByTestId("lumina-box-stack-recipe")).toHaveValue("WCMYGK");
    fireEvent.click(screen.getByTestId(`lumina-box-stack-view-${newer.record_id}`));
    await screen.findByTestId("lumina-box-stack-selected-detail");
    fireEvent.click(screen.getByTestId("lumina-box-stack-delete-selected"));
    await screen.findByTestId("lumina-box-stack-no-reading");
  });

  it("clears a latest reading removed from the refreshed database list", async () => {
    const existing = recordFor({ recipe_top_to_bottom: "CCMMM", capture_id: "old", measurement: frame() });
    vi.mocked(listLuminaBoxStackSamples).mockResolvedValueOnce([existing]).mockResolvedValue([]);
    await ready("RYBWYY");
    expect(screen.getByTestId("lumina-box-stack-measured-hex")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("lumina-box-stack-refresh"));
    await screen.findByTestId("lumina-box-stack-no-reading");
    expect(screen.getByTestId("lumina-box-stack-recipe")).toHaveValue("RYBWYY");
  });

  it("does not resurrect a committed capture deleted before its POST response returns", async () => {
    const saving = deferred<LuminaBoxStackSampleResponse>();
    vi.mocked(saveLuminaBoxStackSample).mockReturnValueOnce(saving.promise);
    await ready();
    let delivery!: Promise<LuminaBoxCaptureResult>;
    act(() => { delivery = Promise.resolve(receive!(frame("deleted-before-response"))); });
    const payload = vi.mocked(saveLuminaBoxStackSample).mock.calls[0][0];
    const committed = recordFor(payload);
    vi.mocked(listLuminaBoxStackSamples).mockResolvedValueOnce([committed]);
    vi.mocked(loadLuminaBoxStackSample).mockResolvedValueOnce(committed);
    fireEvent.click(screen.getByTestId("lumina-box-stack-refresh"));
    await screen.findByTestId(`lumina-box-stack-record-${committed.record_id}`);
    fireEvent.click(screen.getByTestId(`lumina-box-stack-view-${committed.record_id}`));
    await screen.findByTestId("lumina-box-stack-selected-detail");
    fireEvent.click(screen.getByTestId("lumina-box-stack-delete-selected"));
    await waitFor(() => expect(screen.queryByTestId(`lumina-box-stack-record-${committed.record_id}`)).not.toBeInTheDocument());
    await act(async () => { saving.resolve({ status: "success", record: committed, deduplicated: false }); await delivery; });
    expect(screen.queryByTestId(`lumina-box-stack-record-${committed.record_id}`)).not.toBeInTheDocument();
    expect(screen.queryByTestId("lumina-box-stack-measured-hex")).not.toBeInTheDocument();
    expect(screen.queryByTestId("lumina-box-stack-pending")).not.toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem(LUMINA_BOX_STACK_CAPTURE_KEY)!)[0].outcome).toBe("saved");
    expect(await deliver(frame("deleted-before-response"))).toBe("applied");
    expect(saveLuminaBoxStackSample).toHaveBeenCalledOnce();
  });

  it("ignores an older detail response after another row is selected", async () => {
    const first = recordFor({ recipe_top_to_bottom: "CCMMM", capture_id: "old", measurement: frame("first") });
    const second = recordFor({ recipe_top_to_bottom: "MMYYY", capture_id: "old", measurement: frame("second") });
    const loading = deferred<LuminaBoxStackSampleRecord>();
    vi.mocked(listLuminaBoxStackSamples).mockResolvedValue([second, first]);
    vi.mocked(loadLuminaBoxStackSample).mockReturnValueOnce(loading.promise).mockResolvedValueOnce(second);
    await ready();
    fireEvent.click(screen.getByTestId(`lumina-box-stack-view-${first.record_id}`));
    fireEvent.click(screen.getByTestId(`lumina-box-stack-view-${second.record_id}`));
    await screen.findByTestId("lumina-box-stack-selected-detail");
    await act(async () => { loading.resolve(first); });
    expect(within(screen.getByTestId("lumina-box-stack-selected-detail")).getByText("MMYYY")).toBeInTheDocument();
  });

  it("downloads the complete exported JSON without changing the capture draft", async () => {
    const existing = recordFor({ recipe_top_to_bottom: "CCMMM", capture_id: "old", measurement: frame() });
    vi.mocked(listLuminaBoxStackSamples).mockResolvedValue([existing]);
    vi.mocked(exportLuminaBoxStackSamples).mockResolvedValue({ schema_version: "1.0", kind: "lumina_box_stack_samples_export", exported_at: "2026-10-06T01:00:00Z", records: [existing] });
    const createUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:stack-export");
    const revokeUrl = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    await ready("RYBWYY");
    fireEvent.click(screen.getByTestId("lumina-box-stack-export"));
    await waitFor(() => expect(clicked).toHaveBeenCalledOnce());
    expect(createUrl.mock.calls[0][0]).toBeInstanceOf(Blob);
    expect((clicked.mock.instances[0] as HTMLAnchorElement).download).toBe("lumina-box-stack-samples.json");
    expect(screen.getByTestId("lumina-box-stack-recipe")).toHaveValue("RYBWYY");
    await waitFor(() => expect(revokeUrl).toHaveBeenCalledWith("blob:stack-export"));
  });
});
