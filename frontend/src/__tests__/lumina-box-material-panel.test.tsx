import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LuminaBoxMaterialPanel from "../components/LuminaBoxMaterialPanel";
import * as captureApi from "../api/luminaBoxBackedGradient";
import * as materialApi from "../api/luminaBoxMaterials";
import { parseLuminaBoxFrame, type LuminaBoxCaptureResult, type LuminaBoxMeasurement } from "../api/luminaBoxSerial";
import { useLuminaBoxBackedGradientSerialStore } from "../stores/luminaBoxBackedGradientSerialStore";
import { createLuminaBoxSerialStore } from "../stores/luminaBoxSerialStore";
import { useLuminaBoxMaterialNavigation } from "../stores/luminaBoxMaterialNavigation";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import { BACKED_GRADIENT_DRAFT_KEY } from "../utils/luminaBoxBackedGradientCapture";
import { appendGradientCapture, completeGradientDataset, gradientDataset, gradientRun } from "./fixtures/backedGradient";
import wire from "./fixtures/lumina-box-seven-thickness-v3.jsonl?raw";

vi.mock("../api/luminaBoxBackedGradient", async (original) => ({ ...(await original<typeof captureApi>()),
  listBackedGradientDatasets: vi.fn(), loadBackedGradientDataset: vi.fn(), saveBackedGradientCapture: vi.fn(),
  selectBackedGradientCapture: vi.fn(), importBackedGradientDataset: vi.fn(),
}));
vi.mock("../api/luminaBoxMaterials", async (original) => ({ ...(await original<typeof materialApi>()),
  listLuminaBoxBackingReferences: vi.fn(), createLuminaBoxMaterialDataset: vi.fn(), createLuminaBoxBackingDataset: vi.fn(),
  listLuminaBoxBackingMaterials: vi.fn(), createLuminaBoxBackingMaterialDataset: vi.fn(),
  listLuminaBoxMaterialFits: vi.fn(), startLuminaBoxMaterialFit: vi.fn(), loadLuminaBoxMaterialFit: vi.fn(),
  loadLuminaBoxMaterialFitResult: vi.fn(), saveLuminaBoxMaterialArchive: vi.fn(),
}));

type Receiver = (value: LuminaBoxMeasurement) => LuminaBoxCaptureResult | Promise<LuminaBoxCaptureResult>;
let dataset: materialApi.LuminaBoxMaterialDataset;
let receiver: Receiver | null;
let scope = 0;
const reference = { reference_id: "reference-1", name: "PETG white / black", white_name: "KYNIX PETG White", black_name: "KYNIX PETG Black",
  source_dataset_id: "dataset-1", created_at: "2026-10-07T00:00:00Z" };
const whiteBacking: materialApi.LuminaBoxBackingMaterial = { material_id: "white-1", role: "W", name: "KYNIX PETG White", status: "ready" };
const blackBacking: materialApi.LuminaBoxBackingMaterial = { material_id: "black-1", role: "K", name: "KYNIX PETG Black", status: "ready" };
const chooseBackings = (white = "KYNIX PETG White", black = "KYNIX PETG Black") => {
  fireEvent.click(screen.getByRole("combobox", { name: "白色背板" }));
  fireEvent.click(screen.getByRole("option", { name: white }));
  fireEvent.click(screen.getByRole("combobox", { name: "黑色背板" }));
  fireEvent.click(screen.getByRole("option", { name: black }));
};
const singleMaterial = () => {
  const full = completeGradientDataset();
  const captures = full.captures.filter((record) => record.sample_role === "coated" && record.material_symbol === "R");
  const ids = new Set(captures.map((record) => record.record_id));
  return { ...full, name: "PETG Red", workflow: { kind: "material", material_symbol: "R", reference_id: reference.reference_id },
    captures, selected_capture_ids: Object.fromEntries(Object.entries(full.selected_capture_ids).filter(([, id]) => ids.has(id))) } as materialApi.LuminaBoxMaterialDataset;
};
const separateWhiteBacking = (): materialApi.LuminaBoxMaterialDataset => {
  const full = completeGradientDataset();
  const captures = full.captures.filter((record) => record.sample_role === "bare_backing" && record.backing === "W"
    || record.material_symbol === "W" && record.backing === "K");
  const ids = new Set(captures.map((record) => record.record_id));
  return { ...full, dataset_id: "white-capture", name: whiteBacking.name,
    workflow: { kind: "backing_material", material_symbol: "W", backing_material_id: whiteBacking.material_id,
      opposite_material_id: blackBacking.material_id, opposite_name: blackBacking.name }, captures,
    selected_capture_ids: Object.fromEntries(Object.entries(full.selected_capture_ids).filter(([, id]) => ids.has(id))) };
};
const originalSerial = Object.getOwnPropertyDescriptor(navigator, "serial");

beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear(); dataset = singleMaterial(); receiver = null;
  useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  useLuminaBoxMaterialNavigation.setState({ captureRequest: { datasetId: dataset.dataset_id, materialSymbol: "R" }, lastCaptureArchive: null, libraryProfileKind: "stage_a" });
  Object.defineProperty(navigator, "serial", { configurable: true, value: { requestPort: vi.fn() } });
  useLuminaBoxBackedGradientSerialStore.setState({ status: "disconnected", mode: "unknown", issue: null, captureId: "scope-0", pendingCount: 0,
    connect: vi.fn((callback: Receiver) => { receiver = callback; useLuminaBoxBackedGradientSerialStore.setState({ status: "connected", mode: "reliable" }); }),
    disconnect: vi.fn(async () => undefined), replay: vi.fn(),
    resetCapture: vi.fn(() => useLuminaBoxBackedGradientSerialStore.setState({ captureId: `scope-${++scope}`, pendingCount: 0 })),
  });
  vi.mocked(captureApi.listBackedGradientDatasets).mockImplementation(async () => [dataset]);
  vi.mocked(captureApi.loadBackedGradientDataset).mockImplementation(async () => dataset);
  vi.mocked(captureApi.saveBackedGradientCapture).mockImplementation(async (_id, request) => {
    const response = appendGradientCapture(dataset, request); dataset = { ...response.dataset, workflow: dataset.workflow }; return { ...response, dataset };
  });
  vi.mocked(materialApi.listLuminaBoxBackingReferences).mockResolvedValue([reference]);
  vi.mocked(materialApi.listLuminaBoxBackingMaterials).mockResolvedValue([whiteBacking, blackBacking]);
  vi.mocked(materialApi.listLuminaBoxMaterialFits).mockResolvedValue([]);
  vi.mocked(materialApi.startLuminaBoxMaterialFit).mockImplementation(async () => ({ ...gradientRun, dataset_id: dataset.dataset_id,
    dataset_revision: dataset.revision, fit_mode: "material", material_symbol: "R", reference_id: reference.reference_id, status: "complete" }));
  vi.mocked(materialApi.loadLuminaBoxMaterialFitResult).mockImplementation(async () => ({ status: "complete", estimated_rgb: [180, 50, 60], rmse_pp: 1,
    selected_record_ids: Object.values(dataset.selected_capture_ids) }));
  vi.mocked(materialApi.saveLuminaBoxMaterialArchive).mockResolvedValue({ status: "ok", message: "Material saved", material: {
    material_name: "PETG Red", directory_name: "petg-red", material_file_url: "/api/files/red", estimated_rgb: [180, 50, 60],
  } });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); if (originalSerial) Object.defineProperty(navigator, "serial", originalSerial); else Reflect.deleteProperty(navigator, "serial"); });

describe("Lumina Box material workflow", () => {
  it("defaults to a new profile even after restoring the previous material's selection", async () => {
    useLuminaBoxMaterialNavigation.setState({ captureRequest: null });
    localStorage.setItem(BACKED_GRADIENT_DRAFT_KEY, JSON.stringify({ datasetId: dataset.dataset_id,
      target: { material_symbol: "R", backing: "W", sample_role: "coated" }, manualThickness: "0.08",
      manualXYZ: ["", "", ""], sampleName: "", notes: "" }));
    const view = render(<LuminaBoxMaterialPanel />);
    expect(screen.getByTestId("box-material-create-form")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Lumina Box 耗材采集" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "新建耗材档案" })).not.toBeInTheDocument();
    const toolbar = within(screen.getByTestId("box-material-toolbar"));
    expect(toolbar.getByRole("button", { name: "新建耗材档案" })).toBeInTheDocument();
    expect(toolbar.getByRole("button", { name: "连接 Lumina Box" })).toBeInTheDocument();
    await waitFor(() => expect(captureApi.loadBackedGradientDataset).toHaveBeenCalledWith(dataset.dataset_id));
    expect(screen.getByLabelText("耗材名称")).toHaveValue("");
    expect(screen.queryByTestId("box-material-measurements")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "连接 Lumina Box" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "重采耗材档案" }));
    expect(screen.queryByTestId("box-material-create-form")).not.toBeInTheDocument();
    fireEvent.click(within(screen.getByTestId("box-material-continue-list")).getByRole("button", { name: /PETG Red/ }));
    await screen.findByTestId("box-material-measurements");
    view.unmount();
    render(<LuminaBoxMaterialPanel />);
    expect(screen.getByTestId("box-material-create-form")).toBeInTheDocument();
    expect(screen.queryByTestId("box-material-measurements")).not.toBeInTheDocument();
  });

  it("retains unsaved manual readings while opening the new-profile form by default", async () => {
    useLuminaBoxMaterialNavigation.setState({ captureRequest: null });
    localStorage.setItem(BACKED_GRADIENT_DRAFT_KEY, JSON.stringify({ datasetId: dataset.dataset_id,
      target: { material_symbol: "R", backing: "K", sample_role: "coated" }, manualThickness: "0.64",
      manualXYZ: ["0", "102.4", "3.2"], sampleName: "", notes: "" }));
    render(<LuminaBoxMaterialPanel />);
    await screen.findByRole("button", { name: "取消" });
    expect(screen.getByTestId("box-material-create-form")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    await screen.findByTestId("box-material-measurements");
    expect(screen.getByLabelText("X")).toHaveValue(0);
    expect(screen.getByLabelText("Y")).toHaveValue(102.4);
    expect(screen.getByLabelText("Z")).toHaveValue(3.2);
  });

  it("shows the original unsaved material instead of assigning its readings or identity to a requested archive", async () => {
    const requested = { ...singleMaterial(), dataset_id: "other-material", name: "Other dataset" };
    useLuminaBoxMaterialNavigation.setState({ captureRequest: { datasetId: requested.dataset_id, materialSymbol: "R",
      archive: { name: "Other archive", brand: "Other brand", material_type: "PLA", directoryName: "other-archive" } } });
    vi.mocked(captureApi.listBackedGradientDatasets).mockResolvedValue([dataset, requested]);
    vi.mocked(captureApi.loadBackedGradientDataset).mockImplementation(async (id) => id === requested.dataset_id ? requested : dataset);
    localStorage.setItem(BACKED_GRADIENT_DRAFT_KEY, JSON.stringify({ datasetId: dataset.dataset_id,
      target: { material_symbol: "R", backing: "K", sample_role: "coated" }, manualThickness: "0.64",
      manualXYZ: ["0", "102.4", "3.2"], sampleName: "", notes: "" }));
    render(<LuminaBoxMaterialPanel />);
    await screen.findByTestId("box-material-measurements");
    expect(screen.getByRole("heading", { name: "PETG Red" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Other archive" })).not.toBeInTheDocument();
    expect(screen.getByTestId("box-material-current-sample")).toHaveTextContent("黑底 · 0.64 mm");
    expect(screen.getByLabelText("X")).toHaveValue(0);
    expect(screen.getByText("手工读数尚未保存。请先保存或清空输入，再换样片或生成色卡。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存读数" }));
    await waitFor(() => expect(captureApi.saveBackedGradientCapture).toHaveBeenCalledWith("dataset-1",
      expect.objectContaining({ material_symbol: "R", backing: "K", overlay_mm: .64, reflectance_percent_xyz: [0, 102.4, 3.2] })));
    await waitFor(() => expect(JSON.parse(localStorage.getItem(BACKED_GRADIENT_DRAFT_KEY)!).manualXYZ).toEqual(["", "", ""]));
    fireEvent.click(screen.getByRole("button", { name: "重采耗材档案" }));
    fireEvent.click(within(screen.getByTestId("box-material-continue-list")).getByRole("button", { name: /Other dataset/ }));
    await screen.findByRole("heading", { name: "Other archive" });
  });

  it("allows one material's fourteen readings to generate and save an archive", async () => {
    render(<LuminaBoxMaterialPanel />);
    await screen.findByTestId("box-material-measurements");
    await waitFor(() => expect(screen.getByRole("button", { name: "生成耗材档案" })).not.toBeDisabled());
    expect(screen.getByTestId("box-material-progress")).toHaveTextContent("14 / 14");
    expect(within(screen.getByTestId("box-material-measurements")).getAllByRole("button")).toHaveLength(14);
    expect(screen.queryByText("补收未确认数据")).not.toBeInTheDocument();
    expect(screen.queryByText("查看连接诊断")).not.toBeInTheDocument();
    expect(screen.queryByText("内部验证档")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "生成耗材档案" }));
    await screen.findByRole("button", { name: "保存到耗材库" });
    expect(screen.getByRole("button", { name: "重新生成" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "生成耗材档案" })).not.toBeInTheDocument();
    expect(materialApi.startLuminaBoxMaterialFit).toHaveBeenCalledWith(dataset.dataset_id, false, "R", reference.reference_id);
    fireEvent.click(screen.getByRole("button", { name: "保存到耗材库" }));
    await screen.findByText("已保存到耗材库");
    expect(materialApi.saveLuminaBoxMaterialArchive).toHaveBeenCalledWith(gradientRun.fit_id, expect.objectContaining({ name: "PETG Red", overwrite: false }));
  });

  it("does not flash a failed-save alert while a manual reading is being saved", async () => {
    let finish!: (response: Awaited<ReturnType<typeof captureApi.saveBackedGradientCapture>>) => void;
    vi.mocked(captureApi.saveBackedGradientCapture).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    render(<LuminaBoxMaterialPanel />);
    await screen.findByTestId("box-material-measurements");
    fireEvent.click(screen.getByRole("button", { name: "手动输入" }));
    ["20", "10", "3"].forEach((value, index) => fireEvent.change(screen.getByLabelText(["X", "Y", "Z"][index]), { target: { value } }));
    fireEvent.click(screen.getByRole("button", { name: "保存读数" }));
    expect(screen.queryByText("读数尚未保存成功，请重试。")).not.toBeInTheDocument();
    const request = vi.mocked(captureApi.saveBackedGradientCapture).mock.calls[0][1];
    await act(async () => { finish(appendGradientCapture(dataset, request)); });
    expect(screen.queryByText("读数尚未保存成功，请重试。")).not.toBeInTheDocument();
  });

  it("blocks discarding an in-flight save and still permits retrying the original failed reading", async () => {
    let rejectSave!: (reason: Error) => void;
    vi.mocked(captureApi.saveBackedGradientCapture).mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectSave = reject; }));
    render(<LuminaBoxMaterialPanel />);
    await screen.findByTestId("box-material-measurements");
    fireEvent.click(screen.getByRole("button", { name: "手动输入" }));
    ["20", "10", "3"].forEach((value, index) => fireEvent.change(screen.getByLabelText(["X", "Y", "Z"][index]), { target: { value } }));
    fireEvent.click(screen.getByRole("button", { name: "保存读数" }));
    const originalScope = useLuminaBoxBackedGradientSerialStore.getState().captureId;
    const originalRequest = vi.mocked(captureApi.saveBackedGradientCapture).mock.calls[0][1];
    expect(screen.getByRole("button", { name: "放弃待读数…" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "放弃待读数…" }));
    expect(screen.queryByRole("button", { name: "确认放弃待读数" })).not.toBeInTheDocument();
    expect(useLuminaBoxBackedGradientSerialStore.getState().captureId).toBe(originalScope);
    await act(async () => { rejectSave(new Error("offline")); });
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(JSON.parse(localStorage.getItem(BACKED_GRADIENT_DRAFT_KEY)!).manualXYZ).toEqual(["", "", ""]));
    expect(captureApi.saveBackedGradientCapture).toHaveBeenCalledTimes(2);
    expect(captureApi.saveBackedGradientCapture).toHaveBeenLastCalledWith(dataset.dataset_id, originalRequest);
    expect(useLuminaBoxBackedGradientSerialStore.getState().captureId).toBe(originalScope);
    expect(screen.getByLabelText("X")).toHaveValue(null);
  });

  it("recovers from a rejected device reading after confirmation without ACKing it or deleting saved samples", async () => {
    let stream!: ReadableStreamDefaultController<Uint8Array>;
    const commands: Record<string, unknown>[] = [];
    const port = {
      readable: new ReadableStream<Uint8Array>({ start(controller) { stream = controller; } }),
      writable: new WritableStream<Uint8Array>({ write(bytes) { commands.push(JSON.parse(new TextDecoder().decode(bytes))); } }),
      open: vi.fn(async () => undefined), close: vi.fn(async () => undefined),
    };
    const transport = createLuminaBoxSerialStore(() => ({ requestPort: async () => port }), { storageNamespace: "public-rejection-recovery" });
    useLuminaBoxBackedGradientSerialStore.setState(transport.getState());
    const unsubscribe = transport.subscribe((state) => useLuminaBoxBackedGradientSerialStore.setState(state));
    const send = (frame: unknown) => stream.enqueue(new TextEncoder().encode(`${JSON.stringify(frame)}\n`));
    const pong = (pendingCount: number) => send({ protocol: "lumina-box", version: 3, type: "pong",
      capture_id: transport.getState().captureId, boot_id: "fixture-device-boot", pending_count: pendingCount, dropped_count: 0 });
    const rejected = wire.trim().split(/\r?\n/).map(parseLuminaBoxFrame)
      .find((frame) => frame.kind === "delivery" && frame.measurement.mode === "transmit");
    if (rejected?.kind !== "delivery") throw new Error("Missing transmit firmware fixture");
    const savedCaptures = structuredClone(dataset.captures);
    const view = render(<LuminaBoxMaterialPanel />);
    try {
      await screen.findByTestId("box-material-measurements");
      fireEvent.click(screen.getByRole("button", { name: "连接 Lumina Box" }));
      await waitFor(() => expect(transport.getState().status).toBe("handshaking"));
      await act(async () => { pong(0); });
      const originalScope = transport.getState().captureId;
      await act(async () => {
        send({ protocol: "lumina-box", version: 3, type: "delivery", capture_id: originalScope, measurement: rejected.measurement });
      });
      await waitFor(() => expect(commands.some((command) => command.type === "reject")).toBe(true));
      await act(async () => { pong(1); });
      expect(screen.getByRole("button", { name: "黑底 0.08 mm" })).toBeDisabled();
      fireEvent.click(screen.getByRole("button", { name: "放弃待读数…" }));
      expect(transport.getState().captureId).toBe(originalScope);
      fireEvent.click(screen.getByRole("button", { name: "确认放弃待读数" }));
      expect(transport.getState().captureId).not.toBe(originalScope);
      await waitFor(() => expect(commands.some((command) => command.type === "hello" && command.capture_id === transport.getState().captureId)).toBe(true));
      await act(async () => { pong(0); });
      expect(screen.getByRole("button", { name: "黑底 0.08 mm" })).not.toBeDisabled();
      expect(screen.getByTestId("box-material-progress")).toHaveTextContent("14 / 14");
      expect(dataset.captures).toEqual(savedCaptures);
      expect(captureApi.saveBackedGradientCapture).not.toHaveBeenCalled();
      expect(commands.some((command) => command.type === "ack")).toBe(false);
      fireEvent.click(screen.getByRole("button", { name: "黑底 0.08 mm" }));
      expect(screen.getByTestId("box-material-current-sample")).toHaveTextContent("黑底 · 0.08 mm");
    } finally {
      view.unmount();
      await transport.getState().disconnect();
      unsubscribe();
    }
  });

  it("resumes a run after its backing parameters advance to a newer version", async () => {
    dataset.workflow = { kind: "material", material_symbol: "R", reference_id: "reference-1", backing_id: "backing-a" };
    vi.mocked(materialApi.listLuminaBoxBackingReferences).mockResolvedValue([{ ...reference, reference_id: "reference-2", backing_id: "backing-a", version: 2 }]);
    vi.mocked(materialApi.listLuminaBoxMaterialFits).mockResolvedValue([{ ...gradientRun, dataset_id: dataset.dataset_id, dataset_revision: dataset.revision,
      fit_mode: "material", material_symbol: "R", reference_id: "reference-1", capture_reference_id: "reference-1",
      fitted_reference_id: "reference-2", backing_id: "backing-a" }]);
    render(<LuminaBoxMaterialPanel />);
    await screen.findByRole("button", { name: "保存到耗材库" });
    expect(screen.getByRole("button", { name: "重新生成" })).toBeInTheDocument();
  });

  it("keeps the generated material available when completing it publishes a new backing version", async () => {
    dataset.workflow = { kind: "material", material_symbol: "R", reference_id: "reference-1", backing_id: "backing-a" };
    vi.mocked(materialApi.listLuminaBoxBackingReferences)
      .mockResolvedValueOnce([{ ...reference, backing_id: "backing-a", version: 1 }])
      .mockResolvedValue([{ ...reference, reference_id: "reference-2", backing_id: "backing-a", version: 2 }]);
    vi.mocked(materialApi.startLuminaBoxMaterialFit).mockResolvedValue({ ...gradientRun,
      dataset_id: dataset.dataset_id, dataset_revision: dataset.revision, fit_mode: "material", material_symbol: "R",
      reference_id: "reference-1", capture_reference_id: "reference-1", fitted_reference_id: "reference-2", backing_id: "backing-a",
    });
    render(<LuminaBoxMaterialPanel />);
    await waitFor(() => expect(screen.getByRole("button", { name: "生成耗材档案" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "生成耗材档案" }));
    await screen.findByRole("button", { name: "保存到耗材库" });
    await waitFor(() => expect(materialApi.listLuminaBoxBackingReferences).toHaveBeenCalledTimes(2));
    expect(materialApi.startLuminaBoxMaterialFit).toHaveBeenCalledWith(dataset.dataset_id, false, "R", "reference-1");
    expect(materialApi.listLuminaBoxMaterialFits).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "保存到耗材库" }));
    await screen.findByText("已保存到耗材库");
  });

  it("does not replace a newly generated result with a late historical-fit response", async () => {
    let finishListing!: (runs: materialApi.LuminaBoxMaterialFitRun[]) => void;
    vi.mocked(materialApi.listLuminaBoxMaterialFits).mockImplementationOnce(() => new Promise((resolve) => { finishListing = resolve; }));
    render(<LuminaBoxMaterialPanel />);
    await waitFor(() => expect(screen.getByRole("button", { name: "生成耗材档案" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "生成耗材档案" }));
    await screen.findByRole("button", { name: "保存到耗材库" });
    await act(async () => { finishListing([]); });
    expect(screen.getByRole("button", { name: "保存到耗材库" })).toBeInTheDocument();
  });

  it("preserves the saved archive identity when measuring it again", async () => {
    useLuminaBoxMaterialNavigation.setState({ captureRequest: { datasetId: dataset.dataset_id, materialSymbol: "R",
      archive: { name: "PETG红色", brand: "KYNIX", material_type: "PETG", directoryName: "renamed-existing" } } });
    render(<LuminaBoxMaterialPanel />);
    await waitFor(() => expect(screen.getByRole("button", { name: "生成耗材档案" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "生成耗材档案" }));
    fireEvent.click(await screen.findByRole("button", { name: "保存到耗材库" }));
    await waitFor(() => expect(materialApi.saveLuminaBoxMaterialArchive).toHaveBeenCalledWith(gradientRun.fit_id,
      expect.objectContaining({ name: "PETG红色", brand: "KYNIX", material_type: "PETG" })));
  });

  it("creates a single named filament without asking for other colors", async () => {
    useLuminaBoxMaterialNavigation.setState({ captureRequest: null });
    vi.mocked(captureApi.listBackedGradientDatasets).mockResolvedValue([]);
    vi.mocked(materialApi.createLuminaBoxMaterialDataset).mockResolvedValue({ ...dataset, dataset_id: "new-arbitrary-color",
      name: "Orange PETG", materials: { material: "Orange PETG" }, captures: [], selected_capture_ids: {},
      workflow: { kind: "material", material_symbol: "material", reference_id: reference.reference_id } });
    render(<LuminaBoxMaterialPanel />);
    await screen.findByTestId("box-material-create-form");
    fireEvent.change(screen.getByLabelText("耗材名称"), { target: { value: "Orange PETG" } });
    expect(screen.queryByRole("combobox", { name: "颜色" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始采集" })).toBeDisabled();
    await waitFor(() => expect(screen.getByRole("combobox", { name: "白色背板" })).not.toBeDisabled());
    chooseBackings();
    await waitFor(() => expect(screen.getByRole("button", { name: "开始采集" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "开始采集" }));
    await screen.findByTestId("box-material-measurements");
    expect(materialApi.createLuminaBoxMaterialDataset).toHaveBeenCalledWith({ name: "Orange PETG", brand: "", material_type: "", white_backing_id: whiteBacking.material_id, black_backing_id: blackBacking.material_id });
    expect(screen.getByTestId("box-material-cell-material:W:0.08")).toBeInTheDocument();
    expect(screen.queryByLabelText("白色背板耗材名称")).not.toBeInTheDocument();
  });

  it("offers separate backing capture at the same level as new and remeasure", async () => {
    useLuminaBoxMaterialNavigation.setState({ captureRequest: null });
    vi.mocked(captureApi.listBackedGradientDatasets).mockResolvedValue([]);
    vi.mocked(materialApi.listLuminaBoxBackingReferences).mockResolvedValue([]);
    vi.mocked(materialApi.listLuminaBoxBackingMaterials).mockResolvedValue([]);
    render(<LuminaBoxMaterialPanel />);
    await screen.findByText(/缺少可用背板时/);
    const setup = within(screen.getByTestId("box-material-toolbar")).getByRole("button", { name: "采集背板信息" });
    fireEvent.click(setup);
    expect(screen.getByLabelText("耗材名称")).toBeInTheDocument();
    expect(screen.getByLabelText("样片底材名称")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "颜色" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("box-material-create-form")).not.toBeInTheDocument();
  });

  it("keeps unfinished backing materials out of ordinary material choices", async () => {
    useLuminaBoxMaterialNavigation.setState({ captureRequest: null });
    vi.mocked(materialApi.listLuminaBoxBackingMaterials).mockResolvedValue([
      whiteBacking, blackBacking, { ...whiteBacking, material_id: "draft-white", name: "Unmeasured white", status: "draft" },
      { ...blackBacking, material_id: "measured-black", name: "Awaiting black", status: "measured" },
    ]);
    render(<LuminaBoxMaterialPanel />);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "白色背板" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("combobox", { name: "白色背板" }));
    expect(screen.queryByRole("option", { name: "Unmeasured white" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("option", { name: "KYNIX PETG White" }));
    fireEvent.click(screen.getByRole("combobox", { name: "黑色背板" }));
    expect(screen.queryByRole("option", { name: "Awaiting black" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("option", { name: "KYNIX PETG Black" }));
    fireEvent.click(screen.getByRole("button", { name: "采集背板信息" }));
    expect(screen.getByRole("button", { name: /Unmeasured white/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Awaiting black/ })).toBeInTheDocument();
  });

  it("opens the latest separate backing capture instead of its historical source dataset", async () => {
    useLuminaBoxMaterialNavigation.setState({ captureRequest: null });
    const material = { ...blackBacking, active_dataset_id: "black-active", dataset_id: "old-full", source: "legacy_reference", opposite_material_id: whiteBacking.material_id };
    vi.mocked(materialApi.listLuminaBoxBackingMaterials).mockResolvedValue([whiteBacking, material]);
    dataset = { ...gradientDataset("black-active"), name: "KYNIX PETG Black", workflow: { kind: "backing_material", material_symbol: "K",
      backing_material_id: blackBacking.material_id, opposite_material_id: whiteBacking.material_id } };
    render(<LuminaBoxMaterialPanel />);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "黑色背板" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "采集背板信息" }));
    fireEvent.click(screen.getByRole("button", { name: /KYNIX PETG Black/ }));
    await screen.findByTestId("box-material-measurements");
    expect(captureApi.loadBackedGradientDataset).toHaveBeenCalledWith("black-active");
    expect(captureApi.loadBackedGradientDataset).not.toHaveBeenCalledWith("old-full");
    expect(screen.getByTestId("box-material-progress")).toHaveTextContent("0 / 8");
    expect(screen.getByTestId("box-material-cell-K:W:0.08")).toBeInTheDocument();
    expect(screen.getByTestId("box-material-cell-bare:K")).toBeInTheDocument();
    expect(screen.queryByTestId("box-material-cell-bare:W")).not.toBeInTheDocument();
  });

  it("remeasures one projected backing into its own new capture without reopening the old full table", async () => {
    useLuminaBoxMaterialNavigation.setState({ captureRequest: null });
    const material = { ...whiteBacking, source: "legacy_reference", dataset_id: "old-full", opposite_material_id: blackBacking.material_id };
    vi.mocked(materialApi.listLuminaBoxBackingMaterials).mockResolvedValue([material, blackBacking]);
    vi.mocked(materialApi.createLuminaBoxBackingMaterialDataset).mockResolvedValue({ ...gradientDataset("white-remeasure"),
      name: whiteBacking.name, workflow: { kind: "backing_material", material_symbol: "W", backing_material_id: whiteBacking.material_id,
        opposite_material_id: blackBacking.material_id } });
    render(<LuminaBoxMaterialPanel />);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "白色背板" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "采集背板信息" }));
    fireEvent.click(screen.getByRole("button", { name: /KYNIX PETG White/ }));
    await screen.findByTestId("box-material-measurements");
    expect(materialApi.createLuminaBoxBackingMaterialDataset).toHaveBeenCalledWith(expect.objectContaining({
      material_id: whiteBacking.material_id, name: whiteBacking.name, role: "W", opposite_material_id: blackBacking.material_id,
    }));
    expect(captureApi.loadBackedGradientDataset).not.toHaveBeenCalledWith("old-full");
    expect(screen.getByTestId("box-material-progress")).toHaveTextContent("0 / 8");
  });

  it("offers new material and continue without choosing a saved collection first", async () => {
    useLuminaBoxMaterialNavigation.setState({ captureRequest: null });
    render(<LuminaBoxMaterialPanel />);
    await screen.findByRole("button", { name: "重采耗材档案" });
    expect(screen.queryByRole("combobox", { name: "采集记录" })).not.toBeInTheDocument();
    expect(captureApi.loadBackedGradientDataset).not.toHaveBeenCalled();
    expect(screen.getByLabelText("耗材名称")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重采耗材档案" }));
    fireEvent.click(within(screen.getByTestId("box-material-continue-list")).getByRole("button", { name: /PETG Red/ }));
    await screen.findByTestId("box-material-measurements");
    expect(captureApi.loadBackedGradientDataset).toHaveBeenCalledWith(dataset.dataset_id);
    expect(screen.queryByRole("combobox", { name: "颜色" })).not.toBeInTheDocument();
  });

  it("requires two explicit independent backing choices and permits cross-brand combinations", async () => {
    const alternative = { ...reference, reference_id: "reference-2", source_dataset_id: "other-backings", name: "Other PETG",
      white_name: "Brand B White", black_name: "Brand C Black" };
    vi.mocked(materialApi.listLuminaBoxBackingReferences).mockResolvedValue([reference, alternative]);
    const otherWhite = { ...whiteBacking, material_id: "white-2", name: "Brand B White" };
    const otherBlack = { ...blackBacking, material_id: "black-2", name: "Brand C Black" };
    vi.mocked(materialApi.listLuminaBoxBackingMaterials).mockResolvedValue([whiteBacking, blackBacking, otherWhite, otherBlack]);
    vi.mocked(materialApi.createLuminaBoxMaterialDataset).mockResolvedValue({ ...dataset, dataset_id: "new-orange",
      name: "Orange", workflow: { kind: "material", material_symbol: "material", reference_id: alternative.reference_id,
        backing_materials: { W: whiteBacking, K: otherBlack } } });
    render(<LuminaBoxMaterialPanel />);
    await screen.findByTestId("box-material-measurements");
    expect(screen.getByTestId("box-material-bound-backings")).toHaveTextContent("KYNIX PETG White");
    expect(screen.getByTestId("box-material-bound-backings")).not.toHaveTextContent("Brand B White");
    fireEvent.click(screen.getByRole("button", { name: "新建耗材档案" }));
    fireEvent.change(screen.getByLabelText("耗材名称"), { target: { value: "Orange" } });
    expect(screen.getByRole("combobox", { name: "白色背板" })).toHaveTextContent("请选择实际使用的耗材");
    expect(screen.getByRole("button", { name: "开始采集" })).toBeDisabled();
    fireEvent.click(screen.getByRole("combobox", { name: "白色背板" }));
    fireEvent.click(screen.getByRole("option", { name: "KYNIX PETG White" }));
    expect(screen.getByRole("button", { name: "开始采集" })).toBeDisabled();
    fireEvent.click(screen.getByRole("combobox", { name: "黑色背板" }));
    fireEvent.click(screen.getByRole("option", { name: "Brand C Black" }));
    expect(screen.getByRole("button", { name: "开始采集" })).not.toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "新建耗材档案" }));
    expect(screen.getByLabelText("耗材名称")).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "白色背板" })).toHaveTextContent("请选择实际使用的耗材");
    expect(screen.getByRole("combobox", { name: "黑色背板" })).toHaveTextContent("请选择实际使用的耗材");
    fireEvent.change(screen.getByLabelText("耗材名称"), { target: { value: "Orange" } });
    chooseBackings("KYNIX PETG White", "Brand C Black");
    fireEvent.click(screen.getByRole("button", { name: "开始采集" }));
    await screen.findByTestId("box-material-measurements");
    expect(materialApi.createLuminaBoxMaterialDataset).toHaveBeenCalledWith(expect.objectContaining({ name: "Orange", white_backing_id: "white-1", black_backing_id: "black-2" }));
    expect(screen.getByTestId("box-material-bound-backings")).toHaveTextContent("Brand C Black");
  });

  it("starts a separate capture when changing a saved material's backings", async () => {
    const selectedBefore = { ...dataset.selected_capture_ids };
    render(<LuminaBoxMaterialPanel />);
    await screen.findByTestId("box-material-measurements");
    fireEvent.click(screen.getByRole("button", { name: "换背板并开始新采集" }));
    expect(screen.getByLabelText("耗材名称")).toHaveValue("PETG Red");
    expect(screen.getByRole("combobox", { name: "白色背板" })).toHaveTextContent("请选择实际使用的耗材");
    expect(screen.getByRole("combobox", { name: "黑色背板" })).toHaveTextContent("请选择实际使用的耗材");
    expect(screen.getByRole("button", { name: "开始采集" })).toBeDisabled();
    expect(dataset.selected_capture_ids).toEqual(selectedBefore);
    expect(materialApi.createLuminaBoxMaterialDataset).not.toHaveBeenCalled();
  });

  it("keeps explicit independent choices when a backing's fitted version changes", async () => {
    const original = { ...reference, backing_id: "backing-a", version: 1 };
    const updated = { ...original, reference_id: "reference-2", version: 2 };
    const unrelated = { ...reference, reference_id: "other-reference", backing_id: "backing-b", source_dataset_id: "other-backings",
      white_name: "Unrelated White", black_name: "Unrelated Black" };
    dataset.workflow = { kind: "material", material_symbol: "R", reference_id: reference.reference_id, backing_id: "backing-a" };
    let finishRefresh!: (items: materialApi.LuminaBoxBackingMaterial[]) => void;
    vi.mocked(materialApi.listLuminaBoxBackingReferences).mockResolvedValue([original, unrelated, updated]);
    vi.mocked(materialApi.listLuminaBoxBackingMaterials).mockResolvedValueOnce([whiteBacking, blackBacking])
      .mockImplementation(() => new Promise((resolve) => { finishRefresh = resolve; }));
    vi.mocked(materialApi.listLuminaBoxMaterialFits).mockResolvedValue([{ ...gradientRun,
      dataset_id: dataset.dataset_id, dataset_revision: dataset.revision, fit_mode: "material", material_symbol: "R",
      reference_id: reference.reference_id, backing_id: "backing-a" }]);
    vi.mocked(materialApi.createLuminaBoxMaterialDataset).mockResolvedValue(dataset);
    render(<LuminaBoxMaterialPanel />);
    await screen.findByRole("button", { name: "保存到耗材库" });
    await waitFor(() => expect(materialApi.listLuminaBoxBackingReferences).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("button", { name: "新建耗材档案" }));
    fireEvent.change(screen.getByLabelText("耗材名称"), { target: { value: "Purple" } });
    await act(async () => { finishRefresh([whiteBacking, blackBacking]); });
    chooseBackings();
    expect(screen.getByRole("combobox", { name: "白色背板" })).toHaveTextContent("KYNIX PETG White");
    expect(screen.getByRole("combobox", { name: "黑色背板" })).toHaveTextContent("KYNIX PETG Black");
    fireEvent.click(screen.getByRole("button", { name: "开始采集" }));
    await waitFor(() => expect(materialApi.createLuminaBoxMaterialDataset).toHaveBeenCalledWith(expect.objectContaining({ white_backing_id: "white-1", black_backing_id: "black-1" })));
  });

  it("distinguishes same-name independent backings by brand and material type", async () => {
    const first = { ...reference, brand: "Brand A", material_type: "PLA", white_name: "White", black_name: "Black" };
    const second = { ...reference, reference_id: "reference-2", brand: "Brand B", material_type: "PETG", white_name: "White", black_name: "Black" };
    vi.mocked(materialApi.listLuminaBoxBackingReferences).mockResolvedValue([first, second]);
    vi.mocked(materialApi.listLuminaBoxBackingMaterials).mockResolvedValue([
      { ...whiteBacking, name: "White", brand: "Brand A", material_type: "PLA" },
      { ...whiteBacking, material_id: "white-2", name: "White", brand: "Brand B", material_type: "PETG" }, blackBacking,
    ]);
    render(<LuminaBoxMaterialPanel />);
    await screen.findByTestId("box-material-measurements");
    fireEvent.click(screen.getByRole("button", { name: "新建耗材档案" }));
    fireEvent.click(screen.getByRole("combobox", { name: "白色背板" }));
    expect(screen.getByRole("option", { name: /White.*Brand A.*PLA/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /White.*Brand B.*PETG/ })).toBeInTheDocument();
  });

  it("saves one backing's eight readings without collecting the opposite material", async () => {
    useLuminaBoxMaterialNavigation.setState({ captureRequest: null });
    vi.mocked(captureApi.listBackedGradientDatasets).mockResolvedValue([]);
    vi.mocked(materialApi.listLuminaBoxBackingMaterials).mockResolvedValue([]);
    vi.mocked(materialApi.createLuminaBoxBackingMaterialDataset).mockImplementation(async (payload) => {
      const full = completeGradientDataset();
      const captures = full.captures.filter((item) => item.sample_role === "bare_backing" && item.backing === "W"
        || item.material_symbol === "W" && item.backing === "K");
      const ids = new Set(captures.map((item) => item.record_id));
      dataset = { ...full, ...payload, dataset_id: "white-only", materials: { W: payload.name },
        workflow: { kind: "backing_material", material_symbol: "W", backing_material_id: "new-white",
          opposite_material_id: "new-black", opposite_name: "New Black" }, captures,
        selected_capture_ids: Object.fromEntries(Object.entries(full.selected_capture_ids).filter(([, id]) => ids.has(id))) };
      return dataset;
    });
    vi.mocked(materialApi.startLuminaBoxMaterialFit).mockImplementation(async () => ({ ...gradientRun,
      dataset_id: dataset.dataset_id, dataset_revision: dataset.revision, fit_mode: "backing_material" }));
    vi.mocked(materialApi.loadLuminaBoxMaterialFitResult).mockImplementation(async () => ({ status: "awaiting_opposite",
      backing_material_id: "new-white", selected_record_ids: Object.values(dataset.selected_capture_ids) }));
    render(<LuminaBoxMaterialPanel />);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "白色背板" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "采集背板信息" }));
    fireEvent.change(screen.getByLabelText("耗材名称"), { target: { value: "New White" } });
    fireEvent.change(screen.getByLabelText("样片底材名称"), { target: { value: "New Black" } });
    fireEvent.click(screen.getByRole("button", { name: "开始采集" }));
    await screen.findByTestId("box-material-measurements");
    expect(materialApi.createLuminaBoxBackingMaterialDataset).toHaveBeenCalledWith({ name: "New White", brand: "", material_type: "",
      role: "W", opposite_name: "New Black" });
    expect(screen.getByTestId("box-material-progress")).toHaveTextContent("8 / 8");
    expect(within(screen.getByTestId("box-material-measurements")).getAllByRole("button")).toHaveLength(7);
    expect(screen.getByTestId("box-material-cell-bare:W")).toBeInTheDocument();
    expect(screen.queryByTestId("box-material-cell-bare:K")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存背板资料" }));
    await screen.findByText("背板资料已保存；完成“New Black”的测量后即可用于建模。");
    expect(materialApi.startLuminaBoxMaterialFit).toHaveBeenCalledWith(dataset.dataset_id, "backing_material", "W", "");
    expect(screen.queryByText("生成失败，请重试。")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "继续采集另一种背板" }));
    expect(screen.getByTestId("box-backing-setup")).toBeInTheDocument();
  });

  it("shows the first saved backing as ready once the second backing completes without rewriting its old job", async () => {
    dataset = separateWhiteBacking();
    useLuminaBoxMaterialNavigation.setState({ captureRequest: { datasetId: dataset.dataset_id, materialSymbol: "W" } });
    let finishRefresh!: (items: materialApi.LuminaBoxBackingMaterial[]) => void;
    vi.mocked(materialApi.listLuminaBoxBackingMaterials)
      .mockResolvedValueOnce([{ ...whiteBacking, dataset_id: dataset.dataset_id, status: "measured" }, blackBacking])
      .mockImplementation(() => new Promise((resolve) => { finishRefresh = resolve; }));
    vi.mocked(materialApi.listLuminaBoxMaterialFits).mockResolvedValue([{ ...gradientRun, dataset_id: dataset.dataset_id,
      dataset_revision: dataset.revision, fit_mode: "backing_material" }]);
    vi.mocked(materialApi.loadLuminaBoxMaterialFitResult).mockResolvedValue({ status: "awaiting_opposite",
      selected_record_ids: Object.values(dataset.selected_capture_ids) });
    render(<LuminaBoxMaterialPanel />);
    await screen.findByText(/完成“KYNIX PETG Black”的测量后即可用于建模/);
    await waitFor(() => expect(materialApi.listLuminaBoxBackingMaterials).toHaveBeenCalledTimes(2));
    await act(async () => { finishRefresh([{ ...whiteBacking, dataset_id: dataset.dataset_id }, blackBacking]); });
    expect(screen.getByText("背板资料已保存。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "继续采集另一种背板" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "返回耗材信息" })).toBeInTheDocument();
    expect(materialApi.startLuminaBoxMaterialFit).not.toHaveBeenCalled();
  });

  it("does not use a ready model from another capture to complete an unfinished backing", async () => {
    dataset = separateWhiteBacking();
    useLuminaBoxMaterialNavigation.setState({ captureRequest: { datasetId: dataset.dataset_id, materialSymbol: "W" } });
    vi.mocked(materialApi.listLuminaBoxBackingMaterials).mockResolvedValue([{ ...whiteBacking, dataset_id: "other-white-capture" }, blackBacking]);
    vi.mocked(materialApi.listLuminaBoxMaterialFits).mockResolvedValue([{ ...gradientRun, dataset_id: dataset.dataset_id,
      dataset_revision: dataset.revision, fit_mode: "backing_material" }]);
    vi.mocked(materialApi.loadLuminaBoxMaterialFitResult).mockResolvedValue({ status: "awaiting_opposite",
      selected_record_ids: Object.values(dataset.selected_capture_ids) });
    render(<LuminaBoxMaterialPanel />);
    await screen.findByRole("button", { name: "继续采集另一种背板" });
    expect(screen.queryByText("背板资料已保存。")).not.toBeInTheDocument();
  });

  it("does not call changed backing readings ready before fitting them again", async () => {
    dataset = separateWhiteBacking();
    useLuminaBoxMaterialNavigation.setState({ captureRequest: { datasetId: dataset.dataset_id, materialSymbol: "W" } });
    vi.mocked(materialApi.listLuminaBoxBackingMaterials).mockResolvedValue([{ ...whiteBacking, dataset_id: dataset.dataset_id }, blackBacking]);
    vi.mocked(materialApi.listLuminaBoxMaterialFits).mockResolvedValue([{ ...gradientRun, dataset_id: dataset.dataset_id,
      dataset_revision: dataset.revision - 1, fit_mode: "backing_material" }]);
    vi.mocked(materialApi.loadLuminaBoxMaterialFitResult).mockResolvedValue({ status: "awaiting_opposite", selected_record_ids: ["older-reading"] });
    render(<LuminaBoxMaterialPanel />);
    await screen.findByText("读数已更新，请重新生成耗材档案。");
    expect(screen.queryByText("背板资料已保存。")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "返回耗材信息" })).not.toBeInTheDocument();
  });

  it("opens each actually measured legacy filament without a fixed color selector or placeholder materials", async () => {
    dataset = { ...completeGradientDataset(), name: "KYNIX",
      materials: { R: "R", Y: "Y", B: "B", W: "W", K: "K", C: "C", M: "M", G: "G" } };
    const originalCaptures = structuredClone(dataset.captures);
    const originalSelections = { ...dataset.selected_capture_ids };
    const otherReference = { ...reference, reference_id: "another-group", source_dataset_id: "different-dataset", white_name: "Other White" };
    vi.mocked(materialApi.listLuminaBoxBackingReferences).mockResolvedValue([otherReference, reference]);
    render(<LuminaBoxMaterialPanel />);
    await screen.findByTestId("box-material-measurements");
    expect(screen.getByRole("heading", { name: "PETG红色" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getByTestId("box-material-bound-backings")).toHaveTextContent("KYNIX PETG White");
    expect(screen.getByTestId("box-material-bound-backings")).not.toHaveTextContent("Other White");
    fireEvent.click(screen.getByRole("button", { name: "连接 Lumina Box" }));
    fireEvent.click(screen.getByRole("button", { name: "重采耗材档案" }));
    const choices = within(screen.getByTestId("box-material-continue-list"));
    expect(choices.getAllByRole("button")).toHaveLength(5);
    for (const color of ["红色", "黄色", "蓝色", "白色", "黑色"]) expect(choices.getByRole("button", { name: new RegExp(`PETG${color}`) })).toBeInTheDocument();
    expect(choices.queryByRole("button", { name: /青色|品红|绿色/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新建耗材档案" })).toBeInTheDocument();
    fireEvent.click(choices.getByRole("button", { name: /PETG蓝色/ }));
    await screen.findByRole("heading", { name: "PETG蓝色" });
    expect(screen.getByTestId("box-material-progress")).toHaveTextContent("14 / 14");
    expect(screen.getByTestId("box-material-cell-B:W:0.08")).toHaveTextContent("10.00");
    expect(dataset.captures).toEqual(originalCaptures);
    expect(dataset.selected_capture_ids).toEqual(originalSelections);
    expect(captureApi.saveBackedGradientCapture).not.toHaveBeenCalled();
    expect(useLuminaBoxBackedGradientSerialStore.getState().disconnect).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "手动输入" }));
    ["20", "10", "3"].forEach((value, index) => fireEvent.change(screen.getByLabelText(["X", "Y", "Z"][index]), { target: { value } }));
    fireEvent.click(screen.getByRole("button", { name: "保存读数" }));
    await waitFor(() => expect(captureApi.saveBackedGradientCapture).toHaveBeenCalledWith(dataset.dataset_id,
      expect.objectContaining({ material_symbol: "B", backing: "W", overlay_mm: .08 })));
  });

  it("lists named filaments across brands without exposing old paired backing workflows", async () => {
    dataset = { ...gradientDataset(), materials: { R: "Sunset Orange", B: "B" } };
    const otherMaterial: materialApi.LuminaBoxMaterialDataset = { ...singleMaterial(), dataset_id: "another-brand", name: "Lavender", brand: "Other brand" };
    const backingDataset: materialApi.LuminaBoxMaterialDataset = { ...gradientDataset("backing-dataset"), name: "Print backings", workflow: { kind: "backing_reference" } };
    vi.mocked(captureApi.listBackedGradientDatasets).mockImplementation(async () => [dataset, otherMaterial, backingDataset]);
    vi.mocked(captureApi.loadBackedGradientDataset).mockImplementation(async (id) => id === otherMaterial.dataset_id ? otherMaterial : dataset);
    render(<LuminaBoxMaterialPanel />);
    await screen.findByTestId("box-material-measurements");
    fireEvent.click(screen.getByRole("button", { name: "重采耗材档案" }));
    const choices = within(screen.getByTestId("box-material-continue-list"));
    expect(choices.getAllByRole("button")).toHaveLength(2);
    expect(choices.getByRole("button", { name: /Sunset Orange.*KYNIX/ })).toBeInTheDocument();
    expect(choices.getByRole("button", { name: /Lavender.*Other brand/ })).toBeInTheDocument();
    expect(choices.queryByRole("button", { name: /Print backings/ })).not.toBeInTheDocument();
    fireEvent.click(choices.getByRole("button", { name: /Lavender/ }));
    await screen.findByRole("heading", { name: "Lavender" });
    expect(screen.getByTestId("box-material-progress")).toHaveTextContent("14 / 14");
  });

  it("has no backup, restore, import, export, or more controls in either capture or material creation", async () => {
    const { container } = render(<LuminaBoxMaterialPanel />);
    await screen.findByTestId("box-material-measurements");
    expect(screen.queryByText(/更多|备份|导入|导出/)).not.toBeInTheDocument();
    expect(container.querySelector("input[type=file]")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "新建耗材档案" }));
    expect(screen.queryByText(/更多|备份|导入|导出/)).not.toBeInTheDocument();
    expect(container.querySelector("input[type=file]")).toBeNull();
    expect(screen.getByRole("combobox", { name: "白色背板" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "黑色背板" })).toBeInTheDocument();
  });

  it("shows only cross-backed samples and two bare references for first backing setup", async () => {
    dataset = { ...gradientDataset(), workflow: { kind: "backing_reference" } };
    render(<LuminaBoxMaterialPanel />);
    await screen.findByTestId("box-material-measurements");
    expect(screen.getByTestId("box-material-progress")).toHaveTextContent("0 / 16");
    expect(screen.getByRole("button", { name: "3.00 mm 纯白参考片" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "3.00 mm 纯黑参考片" })).toBeInTheDocument();
    expect(screen.getByText("白色耗材 · 黑底")).toBeInTheDocument();
    expect(screen.getByText("黑色耗材 · 白底")).toBeInTheDocument();
  });

  it("changes backing on the same connection and keeps zero and above-100 readings", async () => {
    render(<LuminaBoxMaterialPanel />);
    await screen.findByTestId("box-material-measurements");
    fireEvent.click(screen.getByRole("button", { name: "连接 Lumina Box" }));
    expect(receiver).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "黑底 0.24 mm" }));
    fireEvent.click(screen.getByRole("button", { name: "手动输入" }));
    ["0", "103.25", "2.5"].forEach((value, index) => fireEvent.change(screen.getByLabelText(["X", "Y", "Z"][index]), { target: { value } }));
    fireEvent.click(screen.getByRole("button", { name: "保存读数" }));
    await waitFor(() => expect(captureApi.saveBackedGradientCapture).toHaveBeenCalled());
    expect(captureApi.saveBackedGradientCapture).toHaveBeenCalledWith(dataset.dataset_id, expect.objectContaining({ material_symbol: "R", backing: "K", overlay_mm: .24, reflectance_percent_xyz: [0, 103.25, 2.5] }));
    expect(useLuminaBoxBackedGradientSerialStore.getState().connect).toHaveBeenCalledOnce();
    expect(useLuminaBoxBackedGradientSerialStore.getState().disconnect).not.toHaveBeenCalled();
  });

  it("marks generated results outdated when a measurement changes", async () => {
    const run = { ...gradientRun, dataset_id: dataset.dataset_id, dataset_revision: dataset.revision - 1, fit_mode: "material" as const, material_symbol: "R" as const, reference_id: reference.reference_id };
    vi.mocked(materialApi.listLuminaBoxMaterialFits).mockResolvedValue([run]);
    vi.mocked(materialApi.loadLuminaBoxMaterialFitResult).mockResolvedValue({ status: "complete", selected_record_ids: ["older-reading"] });
    render(<LuminaBoxMaterialPanel />);
    await screen.findByText("读数已更新，请重新生成耗材档案。");
    expect(screen.queryByRole("button", { name: "保存到耗材库" })).not.toBeInTheDocument();
  });

  it("keeps a material result usable when only another material's readings changed", async () => {
    dataset = completeGradientDataset();
    const ownIds = dataset.captures.filter((record) => record.material_symbol === "R" && record.sample_role === "coated").map((record) => record.record_id);
    vi.mocked(materialApi.listLuminaBoxMaterialFits).mockResolvedValue([{ ...gradientRun, dataset_id: dataset.dataset_id, dataset_revision: dataset.revision - 1,
      fit_mode: "material", material_symbol: "R", reference_id: reference.reference_id }]);
    vi.mocked(materialApi.loadLuminaBoxMaterialFitResult).mockResolvedValue({ status: "complete", selected_record_ids: ownIds });
    render(<LuminaBoxMaterialPanel />);
    await screen.findByRole("button", { name: "保存到耗材库" });
    expect(screen.queryByText("读数已更新，请重新生成耗材档案。")).not.toBeInTheDocument();
  });

  it.each([true, false])("updates an existing profile only after confirmation: %s", async (confirmed) => {
    vi.spyOn(window, "confirm").mockReturnValue(confirmed);
    vi.mocked(materialApi.saveLuminaBoxMaterialArchive).mockRejectedValueOnce({ response: { status: 409 } });
    render(<LuminaBoxMaterialPanel />);
    await waitFor(() => expect(screen.getByRole("button", { name: "生成耗材档案" })).not.toBeDisabled());
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "生成耗材档案" })); });
    expect(materialApi.startLuminaBoxMaterialFit).toHaveBeenCalledOnce();
    expect(materialApi.loadLuminaBoxMaterialFitResult).toHaveBeenCalledWith(gradientRun.fit_id);
    fireEvent.click(within(screen.getByTestId("box-material-result")).getByRole("button", { name: "保存到耗材库" }));
    await waitFor(() => expect(window.confirm).toHaveBeenCalledOnce());
    if (confirmed) {
      await screen.findByText("已保存到耗材库");
      expect(materialApi.saveLuminaBoxMaterialArchive).toHaveBeenLastCalledWith(gradientRun.fit_id, expect.objectContaining({ overwrite: true }));
    } else expect(materialApi.saveLuminaBoxMaterialArchive).toHaveBeenCalledOnce();
  });
});
