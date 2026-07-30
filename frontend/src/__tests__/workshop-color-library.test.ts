import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ColorMode,
  type SavedMaterialLibraryItem,
} from "../api/types";
import {
  DEFAULT_STATE,
  useConverterStore,
} from "../stores/converter";
import {
  buildWorkshopColorLibrary,
  clearWorkshopMaterialCatalog,
  readWorkshopColorLibrary,
  updateWorkshopMaterialCatalog,
} from "../workshop/colorLibrary";

const originalFetchLutCatalog =
  useConverterStore.getState().fetchLutCatalog;
const originalFetchLutColors =
  useConverterStore.getState().fetchLutColors;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("buildWorkshopColorLibrary", () => {
  beforeEach(() => {
    useConverterStore.setState({
      ...DEFAULT_STATE,
      fetchLutCatalog: originalFetchLutCatalog,
      fetchLutColors: originalFetchLutColors,
    });
    clearWorkshopMaterialCatalog();
  });

  it("normalizes the active legacy LUT without mixing source colors", () => {
    useConverterStore.setState({
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
            hex_color: "#fff",
            color_name: "White",
          },
          {
            color: "R",
            material: "PLA",
            hex_color: "#ff0000",
            color_name: "Red",
          },
        ],
      },
      palette: [
        {
          quantized_hex: "#00FF00",
          matched_hex: "#0000FF",
          pixel_count: 100,
          percentage: 100,
        },
      ],
    });

    const library = buildWorkshopColorLibrary();

    expect(library?.id).toMatch(/^lut:/);
    expect(library?.sourceKind).toBe("lut");
    expect(library?.colors).toEqual([
      {
        id: "slot:0",
        label: "White",
        hex: "#FFFFFF",
        materialId: null,
      },
      {
        id: "slot:1",
        label: "Red",
        hex: "#FF0000",
        materialId: null,
      },
    ]);
    expect(JSON.stringify(library)).not.toContain("#00FF00");
    expect(JSON.stringify(library)).not.toContain("#0000FF");
  });

  it("returns only public material fields and no local paths", () => {
    updateWorkshopMaterialCatalog([
      {
        material_name: "Bambu PLA Basic White",
        directory_name: "private-white-directory",
        brand: "Bambu Lab",
        material_type: "PLA",
        material_product_id: "bambu-pla-white",
        material_profile_id: "profile-white",
        material_file_url: "/api/files/private-material",
        stage_a_params_url: "/api/files/private-stage-a",
        estimated_rgb: [254, 253, 250],
        archive_path: "/Users/example/material.zip",
        cache_file_path: "/private/cache.npy",
      } as SavedMaterialLibraryItem,
      {
        material_name: "eSUN Red",
        directory_name: "private-red-directory",
        brand: "eSUN",
        material_type: "PLA",
        material_file_url: null,
        estimated_rgb: [241, 35, 45],
      },
    ]);
    useConverterStore.setState({
      source_version: "material",
      selectedMaterialDirNames: [
        "private-white-directory",
        "private-red-directory",
      ],
    });

    const library = buildWorkshopColorLibrary();
    const serialized = JSON.stringify(library);

    expect(library?.sourceKind).toBe("material-archive");
    expect(library?.colors).toEqual([
      {
        id: "material:bambu-pla-white",
        label: "Bambu PLA Basic White",
        hex: "#FEFDFA",
        materialId: "bambu-pla-white",
      },
      {
        id: expect.stringMatching(/^material:local-/),
        label: "eSUN Red",
        hex: "#F1232D",
        materialId: null,
      },
    ]);
    expect(serialized).not.toMatch(
      /directory_name|archive_path|cache_file_path|stage_a_params_path/,
    );
    expect(serialized).not.toContain("/Users/");
    expect(serialized).not.toContain("/private/");
    expect(
      library?.colors.every((entry) =>
        /^#[0-9A-F]{6}$/.test(entry.hex),
      ),
    ).toBe(true);
  });

  it("normalizes a selected native bundle under its public brand identity", () => {
    useConverterStore.setState({
      source_version: "native",
      nativeBrandGroups: [
        {
          brand_key: "fixture-pla",
          material_type: "PLA",
          vendor: "Fixture",
          display_name: "Fixture Native PLA",
          db_options: [
            {
              name: "fixture-white",
              path: "/private/native/white.msgpack",
              color_mode: "4-Color",
              fingerprint: "private-fingerprint",
            },
          ],
          default_db_names: ["fixture-white"],
          supported_modes: [
            { color_layers: 5, layer_height_mm: 0.08 },
          ],
        },
      ],
      selectedNativeBrandKey: "fixture-pla",
      selectedNativeDbNames: ["fixture-white"],
      color_layers: 5,
      layer_height_mm: 0.08,
      selectedLutInfo: {
        name: "Fixture Native",
        color_mode: "4-Color",
        color_count: 2,
        source_kind: "native_bundle",
        palette: [
          {
            color: "C",
            material: "PLA",
            hex_color: "#00aacc",
            color_name: "Cyan",
          },
          {
            color: "M",
            material: "PLA",
            hex_color: "#dd1177",
            color_name: "Magenta",
          },
        ],
      },
    });

    const library = buildWorkshopColorLibrary();

    expect(library).toMatchObject({
      id: expect.stringMatching(/^native:/),
      label: "Fixture Native PLA",
      sourceKind: "native-bundle",
      colors: [
        {
          id: "slot:0",
          label: "Cyan",
          hex: "#00AACC",
          materialId: null,
        },
        {
          id: "slot:1",
          label: "Magenta",
          hex: "#DD1177",
          materialId: null,
        },
      ],
    });
    expect(JSON.stringify(library)).not.toContain("/private/native");
    expect(JSON.stringify(library)).not.toContain(
      "private-fingerprint",
    );
  });

  it("returns null until the selected source has public colors", () => {
    useConverterStore.setState({
      source_version: "legacy",
      lut_name: "Not loaded",
      lut_names: ["Not loaded"],
      selectedLutInfo: null,
      lutColors: [],
      lutColorsLutName: "",
    });

    expect(buildWorkshopColorLibrary()).toBeNull();
  });

  it("hydrates a remembered legacy LUT when Workshop opens before the converter", async () => {
    const fetchLutCatalog = vi.fn(async () => {
      useConverterStore.setState({
        lutListFull: [
          {
            name: "Remembered RYBW",
            path: "/fixture/remembered.npy",
            color_mode: ColorMode.FOUR_COLOR_RYBW,
            fingerprint: "remembered-fingerprint",
          },
        ],
      });
    });
    const fetchLutColors = vi.fn(async (lutName: string) => {
      useConverterStore.setState({
        lutColorsLutName: lutName,
        lutColors: [
          { rgb: [255, 255, 255], hex: "#FFFFFF" },
          { rgb: [255, 0, 0], hex: "#FF0000" },
        ],
      });
    });
    useConverterStore.setState({
      source_version: "legacy",
      lut_name: "Remembered RYBW",
      lut_names: ["Remembered RYBW"],
      lutListFull: [],
      selectedLutInfo: null,
      lutColors: [],
      lutColorsLutName: "",
      fetchLutCatalog,
      fetchLutColors,
    });

    const library = await readWorkshopColorLibrary();

    expect(fetchLutCatalog).toHaveBeenCalledTimes(1);
    expect(fetchLutColors).toHaveBeenCalledWith(
      "Remembered RYBW",
      expect.any(AbortSignal),
    );
    expect(library).toMatchObject({
      label: "Remembered RYBW",
      sourceKind: "lut",
      colors: [
        { hex: "#FFFFFF" },
        { hex: "#FF0000" },
      ],
    });
  });

  it("does not refetch a color library that is already ready", async () => {
    const fetchLutCatalog = vi.fn();
    const fetchLutColors = vi.fn();
    useConverterStore.setState({
      source_version: "legacy",
      lut_name: "Ready RYBW",
      lut_names: ["Ready RYBW"],
      lutListFull: [
        {
          name: "Ready RYBW",
          path: "/fixture/ready.npy",
          color_mode: ColorMode.FOUR_COLOR_RYBW,
          fingerprint: "ready-fingerprint",
        },
      ],
      lutColorsLutName: "Ready RYBW",
      lutColors: [
        { rgb: [255, 255, 255], hex: "#FFFFFF" },
      ],
      fetchLutCatalog,
      fetchLutColors,
    });

    expect(await readWorkshopColorLibrary()).not.toBeNull();
    expect(fetchLutCatalog).not.toHaveBeenCalled();
    expect(fetchLutColors).not.toHaveBeenCalled();
  });

  it("rejects an already-cancelled RPC read even when colors are cached", async () => {
    useConverterStore.setState({
      source_version: "legacy",
      lut_name: "Ready RYBW",
      lut_names: ["Ready RYBW"],
      lutListFull: [
        {
          name: "Ready RYBW",
          path: "/fixture/ready.npy",
          color_mode: ColorMode.FOUR_COLOR_RYBW,
          fingerprint: "ready-fingerprint",
        },
      ],
      lutColorsLutName: "Ready RYBW",
      lutColors: [
        { rgb: [255, 255, 255], hex: "#FFFFFF" },
      ],
    });
    const controller = new AbortController();
    controller.abort();

    await expect(
      readWorkshopColorLibrary({ signal: controller.signal }),
    ).rejects.toMatchObject({
      name: "AbortError",
    });
  });

  it("hydrates the selected material archive without mounting converter settings", async () => {
    const loadMaterialCatalog = vi.fn().mockResolvedValue({
      materials: [
        {
          material_name: "Fixture Red",
          directory_name: "fixture-red",
          brand: "Fixture",
          material_type: "PLA",
          estimated_rgb: [240, 20, 30],
        },
      ],
    });
    useConverterStore.setState({
      source_version: "material",
      selectedMaterialDirNames: ["fixture-red"],
    });

    const library = await readWorkshopColorLibrary({
      loadMaterialCatalog,
    });

    expect(loadMaterialCatalog).toHaveBeenCalledTimes(1);
    expect(library).toMatchObject({
      sourceKind: "material-archive",
      colors: [
        {
          label: "Fixture Red",
          hex: "#F0141E",
        },
      ],
    });
  });

  it("hydrates the selected native database after loading its catalog", async () => {
    const fetchLutCatalog = vi.fn(async () => {
      useConverterStore.setState({
        nativeBrandGroups: [
          {
            brand_key: "fixture-native",
            material_type: "PLA",
            vendor: "Fixture",
            display_name: "Fixture Native",
            db_options: [
              {
                name: "fixture-native-db",
                path: "/fixture/native.msgpack",
                color_mode: ColorMode.FOUR_COLOR_RYBW,
                fingerprint: "fixture-native-fingerprint",
              },
            ],
            default_db_names: ["fixture-native-db"],
            supported_modes: [
              { color_layers: 5, layer_height_mm: 0.08 },
            ],
          },
        ],
        selectedNativeBrandKey: "fixture-native",
        selectedNativeDbNames: ["fixture-native-db"],
        color_layers: 5,
        layer_height_mm: 0.08,
      });
    });
    const fetchLutColors = vi.fn(async (lutName: string) => {
      useConverterStore.setState({
        lutColorsLutName: lutName,
        lutColors: [
          { rgb: [0, 170, 204], hex: "#00AACC" },
        ],
      });
    });
    useConverterStore.setState({
      source_version: "native",
      nativeBrandGroups: [],
      selectedNativeBrandKey: "fixture-native",
      selectedNativeDbNames: ["fixture-native-db"],
      selectedLutInfo: null,
      lutColors: [],
      lutColorsLutName: "",
      fetchLutCatalog,
      fetchLutColors,
    });

    const library = await readWorkshopColorLibrary();

    expect(fetchLutCatalog).toHaveBeenCalledTimes(1);
    expect(fetchLutColors).toHaveBeenCalledWith(
      "fixture-native-db",
      expect.any(AbortSignal),
    );
    expect(library).toMatchObject({
      label: "Fixture Native",
      sourceKind: "native-bundle",
      colors: [{ hex: "#00AACC" }],
    });
  });

  it("does not load the material catalog without a selected material", async () => {
    const loadMaterialCatalog = vi.fn();
    useConverterStore.setState({
      source_version: "material",
      selectedMaterialDirNames: [],
    });

    expect(
      await readWorkshopColorLibrary({ loadMaterialCatalog }),
    ).toBeNull();
    expect(loadMaterialCatalog).not.toHaveBeenCalled();
  });

  it("shares one in-flight hydration for concurrent reads", async () => {
    const catalogResponse = deferred<void>();
    const fetchLutCatalog = vi.fn(() => catalogResponse.promise);
    const fetchLutColors = vi.fn(async (lutName: string) => {
      useConverterStore.setState({
        lutColorsLutName: lutName,
        lutColors: [
          { rgb: [255, 255, 255], hex: "#FFFFFF" },
        ],
      });
    });
    useConverterStore.setState({
      source_version: "legacy",
      lut_name: "Concurrent RYBW",
      lut_names: ["Concurrent RYBW"],
      lutListFull: [],
      lutColors: [],
      lutColorsLutName: "",
      fetchLutCatalog,
      fetchLutColors,
    });

    const first = readWorkshopColorLibrary();
    const second = readWorkshopColorLibrary();
    expect(fetchLutCatalog).toHaveBeenCalledTimes(1);
    useConverterStore.setState({
      lutListFull: [
        {
          name: "Concurrent RYBW",
          path: "/fixture/concurrent.npy",
          color_mode: ColorMode.FOUR_COLOR_RYBW,
          fingerprint: "concurrent-fingerprint",
        },
      ],
    });
    catalogResponse.resolve();

    const [firstLibrary, secondLibrary] = await Promise.all([
      first,
      second,
    ]);
    expect(firstLibrary).toEqual(secondLibrary);
    expect(fetchLutColors).toHaveBeenCalledTimes(1);
  });

  it("aborts hydration when the last RPC reader is cancelled", async () => {
    const hydrationSignal: { value: AbortSignal | null } = {
      value: null,
    };
    const fetchLutCatalog = vi.fn(
      (signal?: AbortSignal) =>
        new Promise<void>((resolve) => {
          hydrationSignal.value = signal ?? null;
          signal?.addEventListener("abort", () => resolve(), {
            once: true,
          });
        }),
    );
    useConverterStore.setState({
      source_version: "legacy",
      lut_name: "Cancelled RYBW",
      lut_names: ["Cancelled RYBW"],
      lutListFull: [],
      lutColors: [],
      lutColorsLutName: "",
      fetchLutCatalog,
    });
    const controller = new AbortController();

    const pending = readWorkshopColorLibrary({
      signal: controller.signal,
    });
    controller.abort();

    await expect(pending).rejects.toMatchObject({
      name: "AbortError",
    });
    expect(hydrationSignal.value?.aborted).toBe(true);
    await Promise.resolve();
  });
});
