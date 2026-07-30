import { beforeEach, describe, expect, it } from "vitest";

import type { SavedMaterialLibraryItem } from "../api/types";
import {
  DEFAULT_STATE,
  useConverterStore,
} from "../stores/converter";
import {
  buildWorkshopColorLibrary,
  clearWorkshopMaterialCatalog,
  updateWorkshopMaterialCatalog,
} from "../workshop/colorLibrary";


describe("buildWorkshopColorLibrary", () => {
  beforeEach(() => {
    useConverterStore.setState({ ...DEFAULT_STATE });
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
});
