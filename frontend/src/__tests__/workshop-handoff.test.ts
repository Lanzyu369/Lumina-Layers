import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_STATE, useConverterStore } from "../stores/converter";
import { useWidgetStore } from "../stores/widgetStore";
import {
  handoffWorkshopPngToConverter,
  WORKSHOP_HANDOFF_MAX_BINARY_BYTES,
  type WorkshopPngDecoder,
} from "../workshop/converterHandoff";
import { buildWorkshopColorLibrary } from "../workshop/colorLibrary";
import type {
  WorkshopImageHandoff as SdkWorkshopImageHandoff,
  WorkshopRecipeSource as SdkWorkshopRecipeSource,
} from "../workshop/contracts";

const SDK_SOURCE: SdkWorkshopRecipeSource = {
  manifestSchemaVersion: 1,
  moduleId: "fixture.hello",
  moduleVersion: "1.0.0",
  projectSchemaVersion: "fixture-project/v1",
  renderSchemaVersion: "fixture-render/v1",
  payload: { mode: "bead" },
};

function pngHeader(width: number, height: number): ArrayBuffer {
  const bytes = new Uint8Array(24);
  bytes.set([137, 80, 78, 71, 13, 10, 26, 10], 0);
  bytes.set([73, 72, 68, 82], 12);
  const view = new DataView(bytes.buffer);
  view.setUint32(8, 13);
  view.setUint32(16, width);
  view.setUint32(20, height);
  return bytes.buffer;
}

function sdkHandoff(
  overrides: Partial<SdkWorkshopImageHandoff> = {},
): SdkWorkshopImageHandoff {
  return {
    moduleId: "fixture.hello",
    moduleVersion: "1.0.0",
    projectId: "project-1",
    pngBytes: pngHeader(64, 32),
    pixelWidth: 64,
    pixelHeight: 32,
    recommendedWidthMm: 5.2,
    recommendedHeightMm: 2.6,
    preserveCanvasBounds: true,
    layout: {
      kind: "square-grid",
      rows: 1,
      columns: 2,
      pitchMm: 2.6,
    },
    colorLibraryId: buildWorkshopColorLibrary()?.id ?? null,
    recipeSource: SDK_SOURCE,
    ...overrides,
  };
}

function decoder(
  width = 64,
  height = 32,
  hasVisiblePixels = true,
): WorkshopPngDecoder {
  return {
    decode: vi.fn().mockResolvedValue({
      width,
      height,
      hasVisiblePixels,
    }),
  };
}

describe("sandbox Workshop PNG handoff", () => {
  beforeEach(() => {
    useConverterStore.setState({
      ...DEFAULT_STATE,
      source_version: "legacy",
      lut_name: "Fixture RYBW",
      lut_names: ["Fixture RYBW"],
      selectedLutInfo: {
        name: "Fixture RYBW",
        color_mode: "4-Color",
        color_count: 2,
        palette: [
          {
            color: "W",
            material: "PLA",
            hex_color: "#FFFFFF",
            color_name: "White",
          },
          {
            color: "R",
            material: "PLA",
            hex_color: "#FF0000",
            color_name: "Red",
          },
        ],
      },
    });
    useWidgetStore.setState({ activeTab: "workshop" });
    vi.spyOn(URL, "createObjectURL").mockReturnValue(
      "blob:workshop-png",
    );
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(
      () => undefined,
    );
  });

  it("validates a square-grid handoff and preserves the print library", async () => {
    const before = useConverterStore.getState();
    const input = sdkHandoff({
      colorLibraryId: buildWorkshopColorLibrary()?.id ?? null,
    });

    await expect(
      handoffWorkshopPngToConverter(input, undefined, {
        decoder: decoder(),
      }),
    ).resolves.toEqual({ status: "completed" });

    const after = useConverterStore.getState();
    expect(after.imageFile).toMatchObject({
      name: "fixture.hello-project-1.png",
      type: "image/png",
    });
    expect(after.target_width_mm).toBe(5.2);
    expect(after.target_height_mm).toBe(2.6);
    expect(after.workshopSource).toEqual(SDK_SOURCE);
    expect(after.source_version).toBe(before.source_version);
    expect(after.lut_name).toBe(before.lut_name);
    expect(after.lut_names).toEqual(before.lut_names);
    expect(useWidgetStore.getState().activeTab).toBe("converter");
  });

  it("rejects bytes above 64 MiB and malformed PNG signatures", async () => {
    const pngDecoder = decoder();
    await expect(
      handoffWorkshopPngToConverter(
        sdkHandoff({
          pngBytes: new ArrayBuffer(
            WORKSHOP_HANDOFF_MAX_BINARY_BYTES + 1,
          ),
        }),
        undefined,
        { decoder: pngDecoder },
      ),
    ).rejects.toMatchObject({
      code: "handoff-binary-too-large",
    });
    await expect(
      handoffWorkshopPngToConverter(
        sdkHandoff({ pngBytes: new ArrayBuffer(24) }),
        undefined,
        { decoder: pngDecoder },
      ),
    ).rejects.toMatchObject({
      code: "handoff-invalid-png",
    });
    expect(pngDecoder.decode).not.toHaveBeenCalled();
  });

  it("rejects decoded dimension mismatch, edge overflow, and pixel overflow", async () => {
    await expect(
      handoffWorkshopPngToConverter(
        sdkHandoff(),
        undefined,
        { decoder: decoder(63, 32) },
      ),
    ).rejects.toMatchObject({
      code: "handoff-dimensions-invalid",
    });
    await expect(
      handoffWorkshopPngToConverter(
        sdkHandoff({
          pngBytes: pngHeader(16_385, 1),
          pixelWidth: 16_385,
          pixelHeight: 1,
        }),
        undefined,
        { decoder: decoder(16_385, 1) },
      ),
    ).rejects.toMatchObject({
      code: "handoff-dimensions-invalid",
    });
    await expect(
      handoffWorkshopPngToConverter(
        sdkHandoff({
          pngBytes: pngHeader(10_000, 10_000),
          pixelWidth: 10_000,
          pixelHeight: 10_000,
        }),
        undefined,
        { decoder: decoder(10_000, 10_000) },
      ),
    ).rejects.toMatchObject({
      code: "handoff-dimensions-invalid",
    });
  });

  it("allows transparency but rejects an entirely empty image", async () => {
    await expect(
      handoffWorkshopPngToConverter(
        sdkHandoff(),
        undefined,
        { decoder: decoder(64, 32, true) },
      ),
    ).resolves.toEqual({ status: "completed" });
    useConverterStore.getState().setImageFile(null);
    await expect(
      handoffWorkshopPngToConverter(
        sdkHandoff(),
        undefined,
        { decoder: decoder(64, 32, false) },
      ),
    ).rejects.toMatchObject({
      code: "handoff-image-empty",
    });
  });

  it("validates square-grid pitch and exact physical dimensions", async () => {
    await expect(
      handoffWorkshopPngToConverter(
        sdkHandoff({
          recommendedWidthMm: 5.200002,
        }),
        undefined,
        { decoder: decoder() },
      ),
    ).rejects.toMatchObject({
      code: "handoff-physical-size-invalid",
    });
    await expect(
      handoffWorkshopPngToConverter(
        sdkHandoff({
          layout: {
            kind: "square-grid",
            rows: 1.5,
            columns: 2,
            pitchMm: 2.6,
          },
        }),
        undefined,
        { decoder: decoder() },
      ),
    ).rejects.toMatchObject({
      code: "handoff-layout-invalid",
    });
  });

  it("supports a bounded generic non-grid handoff", async () => {
    const input = sdkHandoff({
      layout: undefined,
      recommendedWidthMm: 25,
      recommendedHeightMm: 12.5,
    });

    await expect(
      handoffWorkshopPngToConverter(input, undefined, {
        decoder: decoder(),
      }),
    ).resolves.toEqual({ status: "completed" });
    expect(useConverterStore.getState().target_width_mm).toBe(25);
  });

  it("rejects oversized recipe envelopes and a changed color library", async () => {
    await expect(
      handoffWorkshopPngToConverter(
        sdkHandoff({
          recipeSource: {
            ...SDK_SOURCE,
            payload: {
              value: "x".repeat(1024 * 1024 + 1),
            },
          },
        }),
        undefined,
        { decoder: decoder() },
      ),
    ).rejects.toMatchObject({
      code: "handoff-recipe-too-large",
    });
    await expect(
      handoffWorkshopPngToConverter(
        sdkHandoff({ colorLibraryId: "lut:stale" }),
        undefined,
        { decoder: decoder() },
      ),
    ).rejects.toMatchObject({
      code: "handoff-color-library-changed",
    });
  });
});
