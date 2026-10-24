import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import * as systemApi from "../api/system";
import { DEFAULT_STATE, isValidImageType, useConverterStore } from "../stores/converter";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import { buildFullRecipe, buildRecipeAssets, exportConverterRecipe } from "../recipe/exportRecipe";
import { prepareImport } from "../recipe/importFlow";
import { parseRecipeFile, restoreConverterRecipe } from "../recipe/importRecipe";
import { embedRecipeInPng } from "../recipe/pngMetadata";
import { createLegacyRecipeV1 } from "./fixtures/legacyRecipeV1";
import { RECIPE_SCHEMA_VERSION, type LuminaRecipe } from "../recipe/types";

const FORMATS = [
  { name: "heightmap.png", mime: "image/png" },
  { name: "heightmap.jpg", mime: "image/jpeg" },
  { name: "heightmap.bmp", mime: "image/bmp" },
  { name: "heightmap.tiff", mime: "image/tiff" },
] as const;

function fixtureFile(name: string, mime: string): File {
  const bytes = readFileSync(resolve("src/__tests__/fixtures/heightmap", name));
  return new File([new Uint8Array(bytes)], name, { type: mime });
}

async function heightmapRecipe(heightmap: File, version: number) {
  const primary = fixtureFile("heightmap.png", "image/png");
  const assets = await buildRecipeAssets(primary, heightmap);
  const converter = exportConverterRecipe(
    { ...DEFAULT_STATE, enable_relief: true, autoHeightMode: "use-heightmap", heightmap_max_height: 7 },
    DEFAULT_SETTINGS,
  );
  const recipe = await buildFullRecipe(converter, { width: 2, height: 2, mime_type: "image/png" }, assets);
  if (version === 1) {
    const legacy = createLegacyRecipeV1();
    legacy.recipe.converter.relief = { ...legacy.recipe.converter.relief, enable_relief: true, auto_height_mode: "use-heightmap", heightmap_max_height: 7 };
    return { ...legacy, asset: assets };
  }
  return { ...recipe, schema_version: version, compat: { min_schema_version: version } };
}

async function importFile(recipe: unknown, container: string): Promise<File> {
  if (container === "json") return new File([JSON.stringify(recipe)], "project.lumina.json", { type: "application/json" });
  const cover = fixtureFile("heightmap.png", "image/png");
  return new File([await embedRecipeInPng(cover, recipe as LuminaRecipe)], "project.png", { type: "image/png" });
}

describe("share card heightmap import", () => {
  beforeEach(() => {
    useConverterStore.setState({ ...DEFAULT_STATE, target_width_mm: 99 });
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
    class PrimaryImage {
      src = "";
      naturalWidth = 2;
      naturalHeight = 2;
      decode = vi.fn(async () => {});
    }
    vi.stubGlobal("Image", PrimaryImage);
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:heightmap-import");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    vi.spyOn(systemApi, "getPrinters").mockResolvedValue([]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  for (const version of [1, 3, 4]) {
    for (const container of ["json", "png"]) {
      it.each(FORMATS)(`preserves $name bytes through v${version} ${container} import and current-version re-export`, async ({ name, mime }) => {
        const heightmap = fixtureFile(name, mime);
        const expectedBytes = new Uint8Array(await heightmap.arrayBuffer());
        const post = vi.spyOn(apiClient, "post").mockImplementation(async (url, data, options) => {
          expect(url).toBe("/system/validate-heightmap");
          const uploaded = (data as FormData).get("file") as File;
          expect(uploaded.name).toBe(name);
          expect(uploaded.type).toBe(mime);
          expect(new Uint8Array(await uploaded.arrayBuffer())).toEqual(expectedBytes);
          expect(options?.timeout).toBe(30_000);
          expect(options?.signal).toBeInstanceOf(AbortSignal);
          expect(useConverterStore.getState().heightmapFile).toBeNull();
          return { data: { width: 2, height: 2 } };
        });
        const recipe = await heightmapRecipe(heightmap, version);
        const preview = await prepareImport(await importFile(recipe, container));
        expect(post).toHaveBeenCalledTimes(1);
        expect(preview.recipe.schema_version).toBe(RECIPE_SCHEMA_VERSION);
        expect(preview.restoreResult.state.autoHeightMode).toBe("use-heightmap");
        expect(preview.restoreResult.state.heightmap_max_height).toBe(7);
        const restored = preview.restoreResult.heightmapFile!;
        expect(restored.name).toBe(name);
        expect(restored.type).toBe(mime);
        expect(new Uint8Array(await restored.arrayBuffer())).toEqual(expectedBytes);
        expect(useConverterStore.getState().imageFile).toBeNull();
        expect(useConverterStore.getState().heightmapFile).toBeNull();
        expect(useConverterStore.getState().target_width_mm).toBe(99);

        const assets = await buildRecipeAssets(preview.restoreResult.assetFile, restored);
        const reexported = await buildFullRecipe(preview.recipe.recipe.converter!, preview.recipe.cover, assets);
        const reparsed = await parseRecipeFile(await importFile(reexported, container));
        const restoredAgain = restoreConverterRecipe(reparsed.recipe, []).heightmapFile!;
        expect(restoredAgain.name).toBe(name);
        expect(restoredAgain.type).toBe(mime);
        expect(new Uint8Array(await restoredAgain.arrayBuffer())).toEqual(expectedBytes);
        if (preview.coverUrl) URL.revokeObjectURL(preview.coverUrl);
      });
    }
  }

  it.each(FORMATS)("rejects damaged $name before changing the current project", async ({ name, mime }) => {
    const damaged = new File([new Uint8Array([0, 1, 2, 3])], name, { type: mime });
    const post = vi.spyOn(apiClient, "post").mockRejectedValue(new Error("Heightmap cannot be decoded"));
    const recipe = await heightmapRecipe(damaged, 4);
    await expect(prepareImport(await importFile(recipe, "png"))).rejects.toThrow("Asset data is corrupted");
    expect(post).toHaveBeenCalledTimes(1);
    expect(useConverterStore.getState().heightmapFile).toBeNull();
    expect(useConverterStore.getState().target_width_mm).toBe(99);
    expect(systemApi.getPrinters).not.toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
  });

  it.each(["heightmap.bmp", "heightmap.tiff"])("keeps %s outside the primary image whitelist", async (name) => {
    const mime = name.endsWith("bmp") ? "image/bmp" : "image/tiff";
    expect(isValidImageType(mime, name)).toBe(false);
    const recipe = await heightmapRecipe(fixtureFile(name, mime), 4);
    recipe.asset.primary = recipe.asset.heightmap!;
    const post = vi.spyOn(apiClient, "post");
    await expect(prepareImport(await importFile(recipe, "json"))).rejects.toThrow("Asset data is corrupted");
    expect(post).not.toHaveBeenCalled();
  });

  it("aborts a pending heightmap validation after 30 seconds and leaves the project untouched", async () => {
    let signal: AbortSignal | undefined;
    let markStarted = () => {};
    const started = new Promise<void>((resolve) => { markStarted = resolve; });
    vi.spyOn(apiClient, "post").mockImplementation((_url, _data, options) => {
      signal = options?.signal as AbortSignal;
      markStarted();
      return new Promise(() => {});
    });
    const recipe = await heightmapRecipe(fixtureFile("heightmap.tiff", "image/tiff"), 4);
    const file = await importFile(recipe, "json");
    vi.useFakeTimers();
    let failure: unknown;
    const preparation = prepareImport(file).catch((error: unknown) => { failure = error; });
    await started;
    await vi.advanceTimersByTimeAsync(30_000);
    await preparation;
    expect((failure as Error).message).toContain("Asset data is corrupted");
    expect(signal?.aborted).toBe(true);
    expect(useConverterStore.getState().heightmapFile).toBeNull();
    expect(useConverterStore.getState().target_width_mm).toBe(99);
    expect(systemApi.getPrinters).not.toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });
});
