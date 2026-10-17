import { beforeEach, describe, expect, it, vi } from "vitest";
import { CONVERTER_ERROR_KEYS, useConverterStore } from "../stores/converter";
import type { ExportMaterialSelection } from "../api/types";

vi.mock("../api/converter", async () => {
  const actual =
    await vi.importActual<typeof import("../api/converter")>(
      "../api/converter",
    );
  return {
    ...actual,
    convertGenerate: vi.fn(),
    convertGenerateLargeFormat: vi.fn(),
    convertGeneratePuzzle: vi.fn(),
    fetchExportMaterialSelection: vi.fn(),
  };
});

import {
  convertGenerate,
  convertGenerateLargeFormat,
  convertGeneratePuzzle,
  fetchExportMaterialSelection,
} from "../api/converter";

const mockedConvertGenerate = vi.mocked(convertGenerate);
const mockedConvertGenerateLargeFormat = vi.mocked(convertGenerateLargeFormat);
const mockedConvertGeneratePuzzle = vi.mocked(convertGeneratePuzzle);
const mockedFetchExportMaterialSelection = vi.mocked(fetchExportMaterialSelection);

let sessionCounter = 0;

function seedReadySession(modes: {
  largeFormatEnabled: boolean;
  modelSurfaceEnabled: boolean;
}): void {
  sessionCounter += 1;
  useConverterStore.setState({
    sessionId: `large-format-surface-${sessionCounter}`,
    selectionDocument: null,
    contentCommitStatus: "idle",
    contentCommitOperationId: null,
    replacement_regions: [],
    recipe_overrides: [],
    free_color_set: new Set<string>(),
    error: null,
    isGenerating: false,
    enable_relief: false,
    puzzleEnabled: false,
    batchMode: false,
    source_version: "legacy",
    lut_name: "test-lut",
    target_width_mm: 60,
    target_height_mm: 30,
    tileWidthMm: 240,
    tileHeightMm: 240,
    downloadUrl: null,
    ...modes,
  } as never);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedFetchExportMaterialSelection.mockResolvedValue({
    ready: true,
    slicer_id: "BambuStudio",
    machine_uid: "bbl:bambu-lab-h2d",
    nozzle_uid: "nozzle:0.4mm",
    device_profile_id: "BambuStudio:bbl:bambu-lab-h2d:0.4",
    machine_profile_id: "bbl:bambu-lab-h2d",
    build_plate_uid: "plate:textured-pei",
    materials: [],
    build_plates: [],
    issues: [],
  } satisfies ExportMaterialSelection);
  mockedConvertGenerate.mockResolvedValue({
    status: "ok",
    message: "generated",
    download_url: "/api/files/result.3mf",
  } as never);
  mockedConvertGenerateLargeFormat.mockResolvedValue({
    status: "ok",
    message: "generated",
    download_url: "/api/files/tiles.zip",
    warnings: [],
  } as never);
});

describe("large format with model texture", () => {
  it("refuses before material preflight or any export request", async () => {
    seedReadySession({ largeFormatEnabled: true, modelSurfaceEnabled: true });

    const result = await useConverterStore.getState().submitGenerate();

    expect(result).toBeNull();
    expect(mockedFetchExportMaterialSelection).not.toHaveBeenCalled();
    expect(mockedConvertGenerateLargeFormat).not.toHaveBeenCalled();
    expect(mockedConvertGenerate).not.toHaveBeenCalled();
    expect(mockedConvertGeneratePuzzle).not.toHaveBeenCalled();
    expect(useConverterStore.getState().error).toBe(
      "large_format_model_surface_conflict",
    );
    expect(CONVERTER_ERROR_KEYS.largeFormatModelSurfaceConflict).toBe(
      "large_format_model_surface_conflict",
    );
    expect(useConverterStore.getState().isGenerating).toBe(false);
    expect(useConverterStore.getState().modelSurfaceEnabled).toBe(true);
  });

  it("keeps ordinary large-format generation available without model texture", async () => {
    seedReadySession({ largeFormatEnabled: true, modelSurfaceEnabled: false });

    await useConverterStore.getState().submitGenerate();

    expect(mockedFetchExportMaterialSelection).toHaveBeenCalledOnce();
    expect(mockedConvertGenerateLargeFormat).toHaveBeenCalledOnce();
    expect(useConverterStore.getState().error).toBeNull();
    expect(useConverterStore.getState().downloadUrl).toBe("/api/files/tiles.zip");
  });

  it("keeps ordinary model-texture generation available without large format", async () => {
    seedReadySession({ largeFormatEnabled: false, modelSurfaceEnabled: true });

    await useConverterStore.getState().submitGenerate();

    expect(mockedFetchExportMaterialSelection).toHaveBeenCalledOnce();
    expect(mockedConvertGenerate).toHaveBeenCalledOnce();
    expect(mockedConvertGenerateLargeFormat).not.toHaveBeenCalled();
    expect(useConverterStore.getState().error).toBeNull();
  });
});
