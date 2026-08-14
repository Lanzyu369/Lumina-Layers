import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import * as fc from "fast-check";
import {
  calibrationGenerate,
  generateSingleStageKit,
} from "../api/calibration";
import { CalibrationColorMode } from "../api/types";
import {
  BACKING_THICKNESS_DEFAULT_MM,
  BACKING_THICKNESS_MAX_MM,
  BACKING_THICKNESS_MIN_MM,
  useCalibrationStore,
} from "../stores/calibrationStore";
import { clampValue } from "../stores/converter";
import { useConverterStore } from "../stores/converter";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";

// **Validates: Requirements 6.3**
describe("Feature: calibration-tab-integration, Property 4: clampValue 通用正确性", () => {
  it("clampValue always returns a value within [min, max] for any (value, min, max) where min ≤ max", () => {
    fc.assert(
      fc.property(
        fc
          .tuple(
            fc.double({ noNaN: true, noDefaultInfinity: true }),
            fc.double({ noNaN: true, noDefaultInfinity: true }),
          )
          .map(([a, b]) => (a <= b ? ([a, b] as const) : ([b, a] as const))),
        fc.double({ noNaN: true, noDefaultInfinity: true }),
        ([min, max], value) => {
          const result = clampValue(value, min, max);
          return result >= min && result <= max;
        },
      ),
      { numRuns: 100 },
    );
  });
});

// **Validates: Requirements 6.1, 6.2**
describe("Feature: calibration-tab-integration, Property 5: Store setter 钳制正确性", () => {
  it("setBlockSize always clamps block_size to [3, 10] for any numeric input", () => {
    fc.assert(
      fc.property(
        fc.double({
          min: -1000,
          max: 1000,
          noNaN: true,
          noDefaultInfinity: true,
        }),
        (value) => {
          const store = useCalibrationStore.getState();
          store.setBlockSize(value);
          const { block_size } = useCalibrationStore.getState();
          // Reset to default to avoid state leaking
          useCalibrationStore.setState({ block_size: 5 });
          return block_size >= 3 && block_size <= 10;
        },
      ),
      { numRuns: 100 },
    );
  });

  it("setGap always clamps gap to [0.4, 2.0] for any numeric input", () => {
    fc.assert(
      fc.property(
        fc.double({
          min: -1000,
          max: 1000,
          noNaN: true,
          noDefaultInfinity: true,
        }),
        (value) => {
          const store = useCalibrationStore.getState();
          store.setGap(value);
          const { gap } = useCalibrationStore.getState();
          // Reset to default to avoid state leaking
          useCalibrationStore.setState({ gap: 0.84 });
          return gap >= 0.4 && gap <= 2.0;
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ========== Helpers ==========

/** Extract only data fields from CalibrationStore (no action functions). */
function snapshotCalibrationState() {
  const s = useCalibrationStore.getState();
  return {
    color_mode: s.color_mode,
    block_size: s.block_size,
    gap: s.gap,
    backing_thickness: s.backing_thickness,
    eight_color_full_export: s.eight_color_full_export,
    isLoading: s.isLoading,
    error: s.error,
    downloadUrl: s.downloadUrl,
    previewImageUrl: s.previewImageUrl,
    modelUrl: s.modelUrl,
    statusMessage: s.statusMessage,
  };
}

/** Extract only serializable data fields from ConverterStore (no action functions, no File/Set). */
function snapshotConverterState() {
  const s = useConverterStore.getState();
  return {
    imagePreviewUrl: s.imagePreviewUrl,
    aspectRatio: s.aspectRatio,
    sessionId: s.sessionId,
    lut_name: s.lut_name,
    target_width_mm: s.target_width_mm,
    target_height_mm: s.target_height_mm,
    spacer_thick: s.spacer_thick,
    structure_mode: s.structure_mode,
    color_mode: s.color_mode,
    modeling_mode: s.modeling_mode,
    quantize_colors: s.quantize_colors,
    enable_cleanup: s.enable_cleanup,
    separate_backing: s.separate_backing,
    add_loop: s.add_loop,
    loop_width: s.loop_width,
    loop_length: s.loop_length,
    loop_hole: s.loop_hole,
    enable_relief: s.enable_relief,
    heightmap_max_height: s.heightmap_max_height,
    enable_outline: s.enable_outline,
    outline_width: s.outline_width,
    enable_cloisonne: s.enable_cloisonne,
    wire_width_mm: s.wire_width_mm,
    wire_height_mm: s.wire_height_mm,
    enable_coating: s.enable_coating,
    coating_height_mm: s.coating_height_mm,
    isLoading: s.isLoading,
    error: s.error,
    previewImageUrl: s.previewImageUrl,
    modelUrl: s.modelUrl,
  };
}

// ========== Generators ==========

const arbCalibrationColorMode = fc.constantFrom(
  CalibrationColorMode.BW,
  CalibrationColorMode.FOUR_COLOR_RYBW,
  CalibrationColorMode.SIX_COLOR,
  CalibrationColorMode.EIGHT_COLOR,
);

const arbBackingThickness = fc.double({
  min: -5,
  max: 10,
  noNaN: true,
  noDefaultInfinity: true,
});

const arbCalibrationMutation = fc.record({
  color_mode: arbCalibrationColorMode,
  block_size: fc.double({
    min: -100,
    max: 200,
    noNaN: true,
    noDefaultInfinity: true,
  }),
  gap: fc.double({ min: -10, max: 10, noNaN: true, noDefaultInfinity: true }),
  backing_thickness: arbBackingThickness,
  eight_color_full_export: fc.boolean(),
});

const arbConverterMutation = fc.record({
  lut_name: fc.string({ minLength: 0, maxLength: 20 }),
  target_width_mm: fc.double({
    min: -100,
    max: 500,
    noNaN: true,
    noDefaultInfinity: true,
  }),
  target_height_mm: fc.double({
    min: -100,
    max: 500,
    noNaN: true,
    noDefaultInfinity: true,
  }),
  spacer_thick: fc.double({
    min: -10,
    max: 10,
    noNaN: true,
    noDefaultInfinity: true,
  }),
  quantize_colors: fc.integer({ min: 1, max: 300 }),
  enable_cleanup: fc.boolean(),
  separate_backing: fc.boolean(),
  add_loop: fc.boolean(),
  enable_outline: fc.boolean(),
  outline_width: fc.double({
    min: 0,
    max: 15,
    noNaN: true,
    noDefaultInfinity: true,
  }),
  enable_coating: fc.boolean(),
  coating_height_mm: fc.double({
    min: 0,
    max: 1,
    noNaN: true,
    noDefaultInfinity: true,
  }),
});

// **Validates: Requirements 4.1, 4.2, 4.3**
describe("Feature: calibration-tab-integration, Property 1: 双向状态隔离", () => {
  it("CalibrationStore changes do not affect ConverterStore state", () => {
    fc.assert(
      fc.property(arbCalibrationMutation, (mutation) => {
        // Snapshot ConverterStore before mutation
        const before = snapshotConverterState();

        // Apply random mutations to CalibrationStore
        const calStore = useCalibrationStore.getState();
        calStore.setColorMode(mutation.color_mode);
        calStore.setBlockSize(mutation.block_size);
        calStore.setGap(mutation.gap);
        calStore.setBackingThickness(mutation.backing_thickness);
        calStore.setEightColorFullExport(mutation.eight_color_full_export);

        // Snapshot ConverterStore after mutation
        const after = snapshotConverterState();

        // Reset CalibrationStore to defaults
        useCalibrationStore.setState({
          workflow: "legacy",
          color_mode: CalibrationColorMode.FOUR_COLOR_RYBW,
          block_size: 5,
          gap: 0.84,
          backing_thickness: BACKING_THICKNESS_DEFAULT_MM,
          eight_color_full_export: false,
          singleStageLayerHeightMm: 0.08,
          isLoading: false,
          error: null,
          downloadUrl: null,
          threemfDiskPath: null,
          previewImageUrl: null,
          modelUrl: null,
          statusMessage: null,
        });

        // Verify ConverterStore is unchanged
        return JSON.stringify(before) === JSON.stringify(after);
      }),
      { numRuns: 100 },
    );
  });

  it("ConverterStore changes do not affect CalibrationStore state", () => {
    fc.assert(
      fc.property(arbConverterMutation, (mutation) => {
        // Snapshot CalibrationStore before mutation
        const before = snapshotCalibrationState();

        // Apply random mutations to ConverterStore via setter methods
        const convStore = useConverterStore.getState();
        convStore.setLutName(mutation.lut_name);
        convStore.setTargetWidthMm(mutation.target_width_mm);
        convStore.setTargetHeightMm(mutation.target_height_mm);
        convStore.setSpacerThick(mutation.spacer_thick);
        convStore.setQuantizeColors(mutation.quantize_colors);
        convStore.setEnableCleanup(mutation.enable_cleanup);
        convStore.setSeparateBacking(mutation.separate_backing);
        convStore.setAddLoop(mutation.add_loop);
        convStore.setEnableOutline(mutation.enable_outline);
        convStore.setOutlineWidth(mutation.outline_width);
        convStore.setEnableCoating(mutation.enable_coating);
        convStore.setCoatingHeightMm(mutation.coating_height_mm);

        // Snapshot CalibrationStore after mutation
        const after = snapshotCalibrationState();

        // Reset ConverterStore to defaults
        useConverterStore.setState({
          lut_name: "",
          target_width_mm: 60,
          target_height_mm: 60,
          spacer_thick: 1.2,
          quantize_colors: 48,
          enable_cleanup: true,
          separate_backing: false,
          add_loop: false,
          enable_outline: false,
          outline_width: 2.0,
          enable_coating: false,
          coating_height_mm: 0.08,
        });

        // Verify CalibrationStore is unchanged
        return JSON.stringify(before) === JSON.stringify(after);
      }),
      { numRuns: 100 },
    );
  });
});

vi.mock("../api/calibration", () => ({
  calibrationGenerate: vi.fn(),
  generateSingleStageKit: vi.fn(),
}));

const notificationMocks = vi.hoisted(() => ({
  showBrowserCompletionNotification: vi.fn(),
}));

vi.mock("../utils/browserNotifications", () => ({
  showBrowserCompletionNotification:
    notificationMocks.showBrowserCompletionNotification,
}));

const mockCalibrationGenerate = vi.mocked(calibrationGenerate);
const mockGenerateSingleStageKit = vi.mocked(generateSingleStageKit);

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

// **Validates: Requirements 3.1**
describe("Feature: calibration-tab-integration, Property 6: API 请求载荷与 Store 状态一致性", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset store to defaults before each test
    useSettingsStore.setState({
      ...DEFAULT_SETTINGS,
      printerModel: "bambu-p1s",
      slicerSoftware: "OrcaSlicer",
      nozzleSize: "0.2",
      deviceProfileId: "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
    });
    useCalibrationStore.setState({
      workflow: "legacy",
      color_mode: CalibrationColorMode.FOUR_COLOR_RYBW,
      block_size: 5,
      gap: 0.84,
      backing_thickness: BACKING_THICKNESS_DEFAULT_MM,
      eight_color_full_export: false,
      substrateId: "white",
      substrateDisplayName: "White",
      materialDefault: "PLA Basic",
      singleStageLayerHeightMm: 0.08,
      isLoading: false,
      error: null,
      downloadUrl: null,
      threemfDiskPath: null,
      previewImageUrl: null,
      modelUrl: null,
      statusMessage: null,
      manifestUrl: null,
      singleStageJobs: [],
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const arbValidCalibrationState = fc.record({
    color_mode: arbCalibrationColorMode,
    block_size: fc.double({
      min: 3,
      max: 10,
      noNaN: true,
      noDefaultInfinity: true,
    }),
    gap: fc.double({
      min: 0.4,
      max: 2.0,
      noNaN: true,
      noDefaultInfinity: true,
    }),
    backing_thickness: fc.double({
      min: BACKING_THICKNESS_MIN_MM,
      max: BACKING_THICKNESS_MAX_MM,
      noNaN: true,
      noDefaultInfinity: true,
    }),
    eight_color_full_export: fc.boolean(),
  });

  it("submitGenerate sends API request body matching current store state", async () => {
    await fc.assert(
      fc.asyncProperty(arbValidCalibrationState, async (state) => {
        // Set random valid state in the store
        const store = useCalibrationStore.getState();
        store.setColorMode(state.color_mode);
        store.setBlockSize(state.block_size);
        store.setGap(state.gap);
        store.setBackingThickness(state.backing_thickness);
        store.setEightColorFullExport(state.eight_color_full_export);

        // Mock API to return success
        mockCalibrationGenerate.mockResolvedValueOnce({
          status: "ok",
          message: "success",
          download_url: "/test.3mf",
          threemf_disk_path: "/tmp/test.3mf",
          preview_url: null,
          layer_urls: null,
        });

        // Call submitGenerate
        await useCalibrationStore.getState().submitGenerate();

        // Verify the API was called with the correct payload
        const currentState = useCalibrationStore.getState();
        const callArgs =
          mockCalibrationGenerate.mock.calls[
            mockCalibrationGenerate.mock.calls.length - 1
          ][0];

        return (
          callArgs.color_mode === currentState.color_mode &&
          callArgs.block_size === currentState.block_size &&
          callArgs.gap === currentState.gap &&
          callArgs.backing_thickness === currentState.backing_thickness &&
          callArgs.eight_color_full_export ===
            currentState.eight_color_full_export &&
          callArgs.printer_id === "bambu-p1s" &&
          callArgs.slicer === "OrcaSlicer" &&
          callArgs.nozzle_size === "0.2" &&
          callArgs.device_profile_id === "OrcaSlicer:bbl:bambu-lab-p1s:0.2" &&
          useCalibrationStore.getState().threemfDiskPath === null &&
          useCalibrationStore.getState().downloadUrl === "/test.3mf"
        );
      }),
      { numRuns: 100 },
    );
    expect(
      notificationMocks.showBrowserCompletionNotification,
    ).not.toHaveBeenCalled();
  });

  it("notifies after legacy calibration succeeds", async () => {
    useSettingsStore.setState({
      enableCompletionNotifications: true,
      language: "en",
    });
    mockCalibrationGenerate.mockResolvedValueOnce({
      status: "ok",
      message: "success",
      download_url: "/test.3mf",
      threemf_disk_path: "/tmp/test.3mf",
      preview_url: null,
      layer_urls: null,
    });

    await useCalibrationStore.getState().submitLegacyGenerate();

    expect(
      notificationMocks.showBrowserCompletionNotification,
    ).toHaveBeenCalledWith("calibration", "en");
  });

  it("keeps a newer calibration request active when an old plate response resolves", async () => {
    const stale = deferred<Awaited<ReturnType<typeof calibrationGenerate>>>();
    const fresh = deferred<Awaited<ReturnType<typeof calibrationGenerate>>>();
    mockCalibrationGenerate
      .mockReturnValueOnce(stale.promise)
      .mockReturnValueOnce(fresh.promise);
    useSettingsStore.setState({
      buildPlateId: "textured-pei-plate",
    });

    const staleRequest = useCalibrationStore.getState().submitLegacyGenerate();
    useSettingsStore
      .getState()
      .setBuildPlateForMachine(
        "OrcaSlicer:bbl:bambu-lab-p1s",
        "smooth-pei-plate",
      );
    const stateAfterPlateChange = useCalibrationStore.getState();

    const freshRequest = useCalibrationStore.getState().submitLegacyGenerate();
    expect(mockCalibrationGenerate.mock.calls[0][0].build_plate_id).toBe(
      "textured-pei-plate",
    );
    expect(mockCalibrationGenerate.mock.calls[1][0].build_plate_id).toBe(
      "smooth-pei-plate",
    );

    stale.resolve({
      status: "ok",
      message: "stale",
      download_url: "/api/files/stale-calibration.3mf",
      threemf_disk_path: "/tmp/stale-calibration.3mf",
      preview_url: "/api/files/stale-calibration.png",
      layer_urls: [],
    });
    await staleRequest;
    const stateAfterStaleResponse = useCalibrationStore.getState();

    fresh.resolve({
      status: "ok",
      message: "fresh",
      download_url: "/api/files/fresh-calibration.3mf",
      threemf_disk_path: "/tmp/fresh-calibration.3mf",
      preview_url: "/api/files/fresh-calibration.png",
      layer_urls: [],
    });
    await freshRequest;

    expect(stateAfterPlateChange).toMatchObject({
      isLoading: false,
      downloadUrl: null,
      previewImageUrl: null,
    });
    expect(stateAfterStaleResponse).toMatchObject({
      isLoading: true,
      downloadUrl: null,
      previewImageUrl: null,
    });
    expect(useCalibrationStore.getState()).toMatchObject({
      isLoading: false,
      downloadUrl: "/api/files/fresh-calibration.3mf",
      previewImageUrl: "/api/files/fresh-calibration.png",
    });
  });

  it("keeps calibration previews while clearing build-plate-specific outputs", () => {
    useCalibrationStore.setState({
      downloadUrl: "/api/files/calibration.3mf",
      threemfDiskPath: "/tmp/calibration.3mf",
      previewImageUrl: "/api/files/calibration.png",
      layerImageUrls: ["/api/files/calibration-layer.png"],
      modelUrl: "/api/files/calibration.glb",
      manifestUrl: "/api/files/calibration-manifest.json",
      singleStageJobs: [
        {
          color: "Sample",
          color_name: "Sample",
          material: "PLA Basic",
          substrate_id: "white",
          substrate_display_name: "White",
          filename: "calibration.3mf",
        },
      ],
    });

    useSettingsStore
      .getState()
      .setBuildPlateForMachine(
        "OrcaSlicer:bbl:bambu-lab-p1s",
        "smooth-pei-plate",
      );

    expect(useCalibrationStore.getState()).toMatchObject({
      downloadUrl: null,
      threemfDiskPath: null,
      previewImageUrl: "/api/files/calibration.png",
      layerImageUrls: ["/api/files/calibration-layer.png"],
      modelUrl: "/api/files/calibration.glb",
      manifestUrl: null,
      singleStageJobs: [],
    });
  });

  it("submitGenerate sends single-stage layer height when workflow is single-stage", async () => {
    useCalibrationStore.setState({
      workflow: "single-stage",
      color_mode: CalibrationColorMode.EIGHT_COLOR,
      substrateId: "white",
      substrateDisplayName: "White",
      materialDefault: "PLA Basic",
      singleStageLayerHeightMm: 0.1,
    });
    useSettingsStore.setState({
      enableCompletionNotifications: true,
      language: "zh",
    });

    mockGenerateSingleStageKit.mockResolvedValueOnce({
      status: "ok",
      message: "success",
      kit_download_url: "/test.zip",
      preview_url: null,
      manifest_url: "/manifest.json",
      jobs: [],
    });

    await useCalibrationStore.getState().submitGenerate();

    const callArgs =
      mockGenerateSingleStageKit.mock.calls[
        mockGenerateSingleStageKit.mock.calls.length - 1
      ][0];
    expect(callArgs.layer_height_mm).toBe(0.1);
    expect(callArgs.printer_id).toBe("bambu-p1s");
    expect(callArgs.slicer).toBe("OrcaSlicer");
    expect(callArgs.nozzle_size).toBe("0.2");
    expect(callArgs.device_profile_id).toBe("OrcaSlicer:bbl:bambu-lab-p1s:0.2");
    expect(callArgs.palette.map((entry) => entry.color_name)).toEqual([
      "Sample",
    ]);
    expect(useCalibrationStore.getState().singleStageJobs).toEqual([]);
    expect(
      notificationMocks.showBrowserCompletionNotification,
    ).toHaveBeenCalledWith("calibration", "zh");
  });

  it("does not notify when either calibration workflow fails", async () => {
    useSettingsStore.setState({ enableCompletionNotifications: true });
    mockCalibrationGenerate.mockRejectedValueOnce(new Error("legacy failed"));

    await useCalibrationStore.getState().submitLegacyGenerate();

    useCalibrationStore.setState({
      workflow: "single-stage",
      error: null,
    });
    mockGenerateSingleStageKit.mockRejectedValueOnce(
      new Error("single-stage failed"),
    );

    await useCalibrationStore.getState().submitSingleStageGenerate();

    expect(useCalibrationStore.getState().error).not.toBeNull();
    expect(
      notificationMocks.showBrowserCompletionNotification,
    ).not.toHaveBeenCalled();
  });
});
