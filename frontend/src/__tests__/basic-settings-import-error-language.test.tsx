import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import BasicSettings from "../components/sections/BasicSettings";
import { I18nProvider } from "../i18n/context";
import { DEFAULT_STATE, useConverterStore } from "../stores/converter";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import * as importFlow from "../recipe/importFlow";
import { buildFullRecipe, exportConverterRecipe } from "../recipe/exportRecipe";

vi.mock("../i18n/context", async () => vi.importActual("../i18n/context"));

vi.mock("../api/converter", async () => {
  const actual = await vi.importActual<typeof import("../api/converter")>(
    "../api/converter",
  );
  return {
    ...actual,
    fetchLutList: vi.fn().mockResolvedValue({ luts: [] }),
  };
});

vi.mock("../api/lut", async () => {
  const actual = await vi.importActual<typeof import("../api/lut")>(
    "../api/lut",
  );
  return {
    ...actual,
    fetchLutCatalog: vi.fn().mockResolvedValue({
      legacy_groups: [],
      native_brand_groups: [],
    }),
    fetchLutDetailsCatalog: vi.fn().mockResolvedValue({ groups: [] }),
  };
});

vi.mock("../api/extractor", async () => {
  const actual = await vi.importActual<typeof import("../api/extractor")>(
    "../api/extractor",
  );
  return {
    ...actual,
    listGradientCardMaterials: vi.fn().mockResolvedValue({
      status: "success",
      message: "ok",
      materials: [],
    }),
  };
});

const RAW_HTTP_STATUS_PATTERN =
  /Request failed with status code|status code\s+\d{3}/i;
const PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4DwQACfsD/fteaysAAAAASUVORK5CYII=";

function getShareCardInput(): HTMLInputElement {
  const input = Array.from(
    document.querySelectorAll<HTMLInputElement>('input[type="file"]'),
  ).find((candidate) => candidate.accept.includes("image/png"));
  if (!input) {
    throw new Error("share-card input not found");
  }
  return input;
}

describe("BasicSettings recipe import visible errors", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSettingsStore.setState({ ...DEFAULT_SETTINGS, language: "zh" });
    useConverterStore.setState({
      ...DEFAULT_STATE,
      imageFile: null,
      imagePreviewUrl: null,
      previewImageUrl: null,
      batchMode: false,
      batchFiles: [],
      error: null,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("normalizes raw HTTP status text when recipe import preparation fails", async () => {
    const mockPrepareImport = vi.spyOn(importFlow, "prepareImport");
    mockPrepareImport.mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    render(<I18nProvider><BasicSettings /></I18nProvider>);

    const file = new File(["{}"], "broken.lumina.json", {
      type: "application/json",
    });
    fireEvent.change(getShareCardInput(), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(mockPrepareImport).toHaveBeenCalledWith(file);
    });
    await waitFor(() => {
      const error = useConverterStore.getState().error;
      expect(error).toBeTruthy();
      expect(error).not.toMatch(RAW_HTTP_STATUS_PATTERN);
      expect(error).toBe("导入失败：服务器发生内部错误。请稍后重试；如果问题持续，请提交反馈。");
    });
  });

  it("hides local recipe import parser errors behind readable user language", async () => {
    const mockPrepareImport = vi.spyOn(importFlow, "prepareImport");
    mockPrepareImport.mockRejectedValueOnce(
      new Error("Invalid .lumina.json: failed to parse JSON"),
    );

    render(<I18nProvider><BasicSettings /></I18nProvider>);

    const file = new File(["not-json"], "broken.lumina.json", {
      type: "application/json",
    });
    fireEvent.change(getShareCardInput(), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(mockPrepareImport).toHaveBeenCalledWith(file);
    });
    await waitFor(() => {
      const error = useConverterStore.getState().error;
      expect(error).toBe("导入失败：无法读取这个分享卡文件，请确认文件未损坏且来自 Lumina。");
      expect(error).not.toContain("Invalid .lumina.json");
      expect(error).not.toContain("failed to parse JSON");
    });
  });

  it.each([
    {
      language: "zh" as const,
      expected: "导入失败：此项目使用当前暂不可用的反推 LUT。请改用传统 LUT 或耗材档案。",
    },
    {
      language: "en" as const,
      expected: "Import failed: This project uses an inferred LUT, which is currently unavailable. Use a legacy LUT or material archive instead.",
    },
  ])("explains an unavailable inferred LUT through file replacement in $language", async ({ language, expected }) => {
    useSettingsStore.setState({ language });
    const imageFile = new File(
      [Uint8Array.from(atob(PNG_BASE64), (character) => character.charCodeAt(0))],
      "current.png",
      { type: "image/png" },
    );
    const imagePreviewUrl = `data:image/png;base64,${PNG_BASE64}`;
    const currentLut = {
      name: "current-lut",
      path: "lut-ref/current.npy",
      color_mode: DEFAULT_STATE.color_mode,
    };
    useConverterStore.setState({
      imageFile,
      imagePreviewUrl,
      lut_name: currentLut.name,
      lutListFull: [currentLut],
      selectedLegacyManufacturer: "Current brand",
      legacyCatalogGroups: [{
        manufacturer: "Current brand",
        items: [{
          ...currentLut,
          compatibility_key: "current",
          source_kind: "legacy_lookup",
          manufacturer: "Current brand",
          material_type: "PLA",
          manufacturer_source: "metadata",
          material_source: "metadata",
          search_tokens: ["current"],
        }],
      }],
      target_width_mm: 23,
      target_height_mm: 23,
    });
    const recipe = await buildFullRecipe(
      exportConverterRecipe({
        ...useConverterStore.getState(),
        source_version: "native",
        selectedNativeBrandKey: "bambulab_pla",
        selectedNativeDbNames: ["RYBW_008_5L.json"],
        target_width_mm: 16,
        target_height_mm: 16,
      }, useSettingsStore.getState()),
      { width: 1, height: 1, mime_type: "image/png" },
      { primary: {
        filename: "incoming.png",
        mime_type: "image/png",
        byte_size: imageFile.size,
        encoding: "base64",
        payload_b64: PNG_BASE64,
      } },
    );
    const file = new File([JSON.stringify(recipe)], "native.lumina.json", {
      type: "application/json",
    });

    render(<I18nProvider><BasicSettings /></I18nProvider>);
    const settingsBeforeImport = useSettingsStore.getState();
    fireEvent.change(getShareCardInput(), { target: { files: [file] } });

    await waitFor(() => {
      expect(useConverterStore.getState().error).toBe(expected);
    });
    expect(useConverterStore.getState()).toMatchObject({
      imageFile,
      imagePreviewUrl,
      source_version: "legacy",
      lut_name: "current-lut",
      target_width_mm: 23,
      target_height_mm: 23,
    });
    expect(useSettingsStore.getState()).toBe(settingsBeforeImport);
  });
});
