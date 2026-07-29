import { beforeEach, describe, expect, it, vi } from "vitest";

import { ModelingMode } from "../api/types";
import { DEFAULT_STATE, useConverterStore } from "../stores/converter";
import { useWidgetStore } from "../stores/widgetStore";
import {
  handoffWorkshopImageToConverter,
} from "../workshop/converterHandoff";
import {
  WorkshopHostError,
  createWorkshopHostServices,
} from "../workshop/host";
import type {
  WorkshopHostDependencies,
} from "../workshop/host";
import type {
  WorkshopImageHandoff,
  WorkshopModuleManifest,
  WorkshopRecipeSource,
} from "../workshop/types";

const MANIFEST: WorkshopModuleManifest = {
  manifestSchemaVersion: 1,
  id: "lumina.bead-pattern",
  name: { zh: "拼豆模式", en: "Bead Pattern" },
  description: { zh: "拼豆", en: "Bead" },
  author: "Lumina Studio",
  version: "1.0.0",
  icon: "bead-grid",
  minLuminaVersion: "2.0.0",
  inputKinds: ["image/png"],
  outputKinds: ["image/png"],
  capabilities: [
    "file.pick-image",
    "project.read-write",
    "handoff.image",
    "ui.theme",
    "ui.locale",
    "status.progress",
    "status.error",
  ],
};

const SOURCE: WorkshopRecipeSource = {
  manifestSchemaVersion: 1,
  moduleId: "lumina.bead-pattern",
  moduleVersion: "1.0.0",
  projectSchemaVersion: "bead-project/v1",
  renderSchemaVersion: "bead-render/v1",
  payload: { payloadVersion: "bead-recipe/v1" },
};

function handoff(
  overrides: Partial<WorkshopImageHandoff> = {},
): WorkshopImageHandoff {
  return {
    moduleId: "lumina.bead-pattern",
    moduleVersion: "1.0.0",
    projectId: "project-1",
    file: new File(["png"], "bead.png", { type: "image/png" }),
    pixelWidth: 64,
    pixelHeight: 32,
    recommendedWidthMm: 5.2,
    recommendedHeightMm: 2.6,
    rows: 1,
    columns: 2,
    beadPitchMm: 2.6,
    preserveCanvasBounds: true,
    recipeSource: SOURCE,
    ...overrides,
  };
}

function dependencies(
  decodedAlpha = 255,
): WorkshopHostDependencies {
  return {
    storage: {
      save: vi.fn(),
      load: vi.fn(),
      latest: vi.fn(),
      remove: vi.fn(),
    },
    files: {
      pickImage: vi.fn(),
      decodeImage: vi.fn().mockResolvedValue({
        width: 64,
        height: 32,
        data: Uint8ClampedArray.from(
          { length: 64 * 32 * 4 },
          (_, index) => (index % 4 === 3 ? decodedAlpha : 0),
        ),
      }),
      encodePng: vi.fn(),
    },
    getLocale: () => "zh",
    getTheme: () => "light",
    translate: (key) => key,
    onProgress: vi.fn(),
    onError: vi.fn(),
    onDiagnostics: vi.fn(),
    handoffImage: vi.fn().mockResolvedValue({ status: "completed" }),
  };
}

describe("workshop image handoff", () => {
  beforeEach(() => {
    useConverterStore.setState({ ...DEFAULT_STATE });
    useWidgetStore.setState({ activeTab: "workshop" });
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:bead");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  });

  it("validates exact 32 px cells, dimensions, and non-empty alpha before delegating", async () => {
    const deps = dependencies();
    const host = createWorkshopHostServices(MANIFEST, deps);
    const input = handoff();

    await expect(host.handoffImage(input)).resolves.toEqual({
      status: "completed",
    });
    expect(deps.files.decodeImage).toHaveBeenCalledWith(input.file);
    expect(deps.handoffImage).toHaveBeenCalledWith(input, undefined);
  });

  it("rejects mismatched pixels, physical dimensions, and all-transparent PNGs", async () => {
    const host = createWorkshopHostServices(
      MANIFEST,
      dependencies(),
    );
    await expect(
      host.handoffImage(handoff({ pixelWidth: 63 })),
    ).rejects.toMatchObject<Partial<WorkshopHostError>>({
      code: "invalid-handoff-pixels",
    });
    await expect(
      host.handoffImage(handoff({ recommendedWidthMm: 5.3 })),
    ).rejects.toMatchObject<Partial<WorkshopHostError>>({
      code: "invalid-handoff-size",
    });

    const transparentHost = createWorkshopHostServices(
      MANIFEST,
      dependencies(0),
    );
    await expect(
      transparentHost.handoffImage(handoff()),
    ).rejects.toMatchObject<Partial<WorkshopHostError>>({
      code: "empty-handoff-image",
    });
  });

  it("does not mutate an occupied converter until replacement is explicit", async () => {
    const oldFile = new File(["old"], "old.png", {
      type: "image/png",
    });
    useConverterStore.setState({
      imageFile: oldFile,
      modeling_mode: ModelingMode.VECTOR,
      target_width_mm: 90,
    });
    const input = handoff();

    await expect(
      handoffWorkshopImageToConverter(input),
    ).resolves.toEqual({ status: "needs-confirmation" });
    expect(useConverterStore.getState().imageFile).toBe(oldFile);
    expect(useConverterStore.getState().target_width_mm).toBe(90);
    expect(useWidgetStore.getState().activeTab).toBe("workshop");

    await expect(
      handoffWorkshopImageToConverter(input, {
        replaceExisting: true,
      }),
    ).resolves.toEqual({ status: "completed" });
    const state = useConverterStore.getState();
    expect(state.imageFile).toBe(input.file);
    expect(state.target_width_mm).toBe(5.2);
    expect(state.target_height_mm).toBe(2.6);
    expect(state.modeling_mode).toBe(ModelingMode.HIGH_FIDELITY);
    expect(state.workshopSource).toEqual(SOURCE);
    expect(useWidgetStore.getState().activeTab).toBe("converter");
  });
});
