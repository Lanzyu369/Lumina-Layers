import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { translations } from "../i18n/translations";

// Only network boundaries and two heavy presentational children are mocked;
// ActionBar, SlicerSelector and the converter/slicer stores are real.
const mocks = vi.hoisted(() => ({
  convertPreview: vi.fn(),
  convertGenerate: vi.fn(),
  convertGenerateLargeFormat: vi.fn(),
  convertGeneratePuzzle: vi.fn(),
  fetchExportMaterialSelection: vi.fn(),
  assertResourceDownloadAvailable: vi.fn(),
  detectSlicers: vi.fn(),
  launchSlicer: vi.fn(),
}));

vi.mock("../api/converter", async () => {
  const actual = await vi.importActual<typeof import("../api/converter")>("../api/converter");
  return {
    ...actual,
    convertPreview: mocks.convertPreview,
    convertGenerate: mocks.convertGenerate,
    convertGenerateLargeFormat: mocks.convertGenerateLargeFormat,
    convertGeneratePuzzle: mocks.convertGeneratePuzzle,
    fetchExportMaterialSelection: mocks.fetchExportMaterialSelection,
  };
});

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, assertResourceDownloadAvailable: mocks.assertResourceDownloadAvailable };
});

vi.mock("../api/slicer", async () => {
  const actual = await vi.importActual<typeof import("../api/slicer")>("../api/slicer");
  return { ...actual, detectSlicers: mocks.detectSlicers, launchSlicer: mocks.launchSlicer };
});

vi.mock("../components/sections/BedSizeSelector", () => ({ default: () => null }));
vi.mock("../components/ui/CanvasPreviewSurface", () => ({ default: () => null }));

import ActionBar from "../components/sections/ActionBar";
import { useConverterStore } from "../stores/converter";
import { useSlicerStore } from "../stores/slicerStore";
import { useSettingsStore } from "../stores/settingsStore";

const BAMBU = { id: "bambu_studio", display_name: "Bambu Studio" };

// Synthetic uploaded model with a selected face; ids only.
const SELECTED_SURFACE = {
  modelSurfaceModelFileId: "model-1",
  modelSurfaceSelectionId: "selection-1",
  modelSurfaceSelection: {
    face_indices: [4, 6],
    normal: [0, 0, 1],
    plane_origin: [0, 0, 2.5],
    area_mm2: 460800,
    face_count: 2,
  },
  modelSurfaceFootprint: {
    bounds_width_mm: 960,
    bounds_height_mm: 480,
    hole_count: 0,
    outer: [],
    holes: [],
  },
};

function requestCounts() {
  return {
    preview: mocks.convertPreview.mock.calls.length,
    exportMaterials: mocks.fetchExportMaterialSelection.mock.calls.length,
    generate: mocks.convertGenerate.mock.calls.length,
    largeFormat: mocks.convertGenerateLargeFormat.mock.calls.length,
    puzzle: mocks.convertGeneratePuzzle.mock.calls.length,
  };
}

const NO_REQUESTS = { preview: 0, exportMaterials: 0, generate: 0, largeFormat: 0, puzzle: 0 };

function enable(order: "large-format-first" | "model-surface-first"): void {
  const store = useConverterStore.getState();
  act(() => {
    if (order === "large-format-first") {
      store.setLargeFormatEnabled(true);
      useConverterStore.getState().setModelSurfaceEnabled(true);
    } else {
      store.setModelSurfaceEnabled(true);
      useConverterStore.getState().setLargeFormatEnabled(true);
    }
    useConverterStore.setState(SELECTED_SURFACE as never);
  });
}

function outputButton(label: string): HTMLButtonElement {
  return screen.getByText(label).closest("button") as HTMLButtonElement;
}

async function renderActionBar(slicers: typeof BAMBU[] = []) {
  mocks.detectSlicers.mockResolvedValue({ slicers });
  render(<ActionBar />);
  await waitFor(() => expect(useSlicerStore.getState().isDetecting).toBe(false));
  if (slicers.length) {
    await waitFor(() => expect(useSlicerStore.getState().slicers).toHaveLength(slicers.length));
  }
}

async function click(button: HTMLElement): Promise<void> {
  await act(async () => {
    fireEvent.click(button);
  });
  await new Promise((resolve) => setTimeout(resolve, 20));
}

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:mock") });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  mocks.convertPreview.mockResolvedValue({
    session_id: "fresh-preview",
    status: "ok",
    message: "ok",
    preview_url: "/api/files/preview.png",
    preview_glb_url: null,
    palette: [],
    contours: {},
    dimensions: { width: 9600, height: 4800, preview_raw_url: "/api/files/raw.png" },
  });
  mocks.fetchExportMaterialSelection.mockResolvedValue({
    ready: true,
    slicer_id: "BambuStudio",
    machine_uid: "machine",
    nozzle_uid: "nozzle",
    device_profile_id: "device",
    machine_profile_id: "machine",
    build_plate_uid: "plate",
    materials: [],
    build_plates: [],
    issues: [],
  });
  mocks.convertGenerate.mockResolvedValue({ status: "ok", message: "ok", download_url: "/api/files/model.3mf" });
  mocks.convertGenerateLargeFormat.mockResolvedValue({
    status: "ok",
    message: "ok",
    download_url: "/api/files/tiles.zip",
    warnings: [],
  });
  mocks.assertResourceDownloadAvailable.mockResolvedValue(undefined);
  mocks.launchSlicer.mockResolvedValue({ status: "ok", message: "launched" });
  useSlicerStore.setState({ slicers: [], selectedSlicerId: null, isDetecting: false, isLaunching: false, error: null });
  useSettingsStore.setState({ slicerSoftware: "bambu_studio", lastSlicerId: null, customSlicerPath: "" } as never);
  useConverterStore.setState({
    imageFile: new File(["png"], "art.png", { type: "image/png" }),
    source_version: "legacy",
    lut_name: "test_lut",
    batchMode: false,
    batchFiles: [],
    puzzleEnabled: false,
    enable_fridge_magnet: false,
    enable_relief: false,
    separate_backing: false,
    isLoading: false,
    isGenerating: false,
    error: null,
    contentCommitStatus: "idle",
    largeFormatEnabled: false,
    modelSurfaceEnabled: false,
    sessionId: null,
    downloadUrl: null,
    threemfDiskPath: null,
  } as never);
});

describe("ActionBar output entry with large format + model texture", () => {
  it.each(["large-format-first", "model-surface-first"] as const)(
    "blocks the output entry before any preview when enabled %s with no session",
    async (order) => {
      enable(order);
      await renderActionBar();

      const output = outputButton(translations.slicer_generate_download_zip.zh);
      expect(screen.queryByRole("button", { name: "生成" })).not.toBeInTheDocument();
      expect(output).toBeDisabled();
      await click(output);

      expect(requestCounts()).toEqual(NO_REQUESTS);
      const state = useConverterStore.getState();
      expect(state.largeFormatEnabled).toBe(true);
      expect(state.modelSurfaceEnabled).toBe(true);
      expect(state.modelSurfaceSelectionId).toBe("selection-1");
    },
  );

  it("blocks the output entry while a preview session already exists", async () => {
    enable("large-format-first");
    act(() => useConverterStore.setState({ sessionId: "existing-session" } as never));
    await renderActionBar();

    const output = outputButton(translations.slicer_generate_download_zip.zh);
    expect(output).toBeDisabled();
    await click(output);

    expect(requestCounts()).toEqual(NO_REQUESTS);
    expect(useConverterStore.getState().sessionId).toBe("existing-session");
  });

  it("blocks both the split main action and the menu when a slicer is detected", async () => {
    enable("large-format-first");
    await renderActionBar([BAMBU]);

    const main = outputButton(translations.slicer_download_zip.zh);
    const toggle = screen.getByRole("button", { name: translations.slicer_toggle_list.zh });
    expect(main).toBeDisabled();
    expect(toggle).toBeDisabled();
    await click(main);
    await click(toggle);

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(requestCounts()).toEqual(NO_REQUESTS);
  });

  it("keeps a retained ZIP download usable during the conflict", async () => {
    enable("large-format-first");
    act(() => useConverterStore.setState({ downloadUrl: "/api/files/retained.zip" } as never));
    await renderActionBar();

    const output = outputButton(translations.slicer_download_zip.zh);
    expect(output).toBeEnabled();
    await click(output);

    expect(mocks.assertResourceDownloadAvailable).toHaveBeenCalledWith("/api/files/retained.zip");
    expect(requestCounts()).toEqual(NO_REQUESTS);
    expect(useConverterStore.getState().downloadUrl).toBe("/api/files/retained.zip");
  });

  it("keeps a retained 3MF disk path launchable when model texture is used alone", async () => {
    act(() => {
      useConverterStore.getState().setModelSurfaceEnabled(true);
      useConverterStore.setState({ ...SELECTED_SURFACE, threemfDiskPath: "C:/out/model.3mf" } as never);
    });
    await renderActionBar([BAMBU]);

    const main = outputButton(translations.slicer_open_in.zh.replace("{name}", BAMBU.display_name));
    expect(main).toBeEnabled();
    await click(main);

    expect(mocks.launchSlicer).toHaveBeenCalledWith(
      expect.objectContaining({ file_path: "C:/out/model.3mf", slicer_id: BAMBU.id }),
    );
    expect(requestCounts()).toEqual(NO_REQUESTS);
  });

  it("still previews and generates large format without model texture", async () => {
    act(() => useConverterStore.getState().setLargeFormatEnabled(true));
    await renderActionBar();

    const output = outputButton(translations.slicer_generate_download_zip.zh);
    expect(output).toBeEnabled();
    await click(output);

    await waitFor(() => expect(mocks.convertGenerateLargeFormat).toHaveBeenCalledOnce());
    expect(requestCounts()).toEqual({ ...NO_REQUESTS, preview: 1, exportMaterials: 1, largeFormat: 1 });
  });

  it("still previews and generates model texture output without large format", async () => {
    act(() => {
      useConverterStore.getState().setModelSurfaceEnabled(true);
      useConverterStore.setState(SELECTED_SURFACE as never);
    });
    await renderActionBar();

    const output = outputButton(translations.slicer_generate_download.zh);
    expect(output).toBeEnabled();
    await click(output);

    await waitFor(() => expect(mocks.convertGenerate).toHaveBeenCalledOnce());
    expect(requestCounts()).toEqual({ ...NO_REQUESTS, preview: 1, exportMaterials: 1, generate: 1 });
  });

  it("leaves the manual preview button available during the conflict", async () => {
    enable("large-format-first");
    await renderActionBar();

    expect(outputButton("预览")).toBeEnabled();
  });
});
