/**
 * Share-card PNG import must accept every PNG textual chunk type.
 * 分享卡 PNG 导入需兼容所有 PNG 文本块类型（tEXt / zTXt / iTXt）。
 *
 * Our writer emits tEXt, but external tools (e.g. ImageMagick resizing a card)
 * re-save long tEXt values as zlib-compressed zTXt. These tests rewrite the
 * recipe chunk the same way and run the full parseRecipeFile() path, which
 * retains attachment decoding and declared byte-size validation.
 */

import { crc32, deflateSync } from "node:zlib";
import { describe, it, expect } from "vitest";
import { buildFullRecipe, buildRecipeAssets, exportConverterRecipe } from "../recipe/exportRecipe";
import { parseRecipeFile } from "../recipe/importRecipe";
import {
  embedRecipeInPng,
  extractCoverFromPng,
  extractRecipeFromPng,
  hasLuminaRecipe,
} from "../recipe/pngMetadata";
import { DEFAULT_STATE } from "../stores/converter";
import type { ConverterState } from "../stores/converter/store";
import { DEFAULT_SETTINGS } from "../stores/settingsStore";
import type { LuminaRecipe } from "../recipe/types";

const KEY_FORMAT = "lumina:format";
const KEY_RECIPE_JSON = "lumina:recipe_json";

type TextualChunkKind = "tEXt" | "zTXt" | "iTXt" | "iTXt-compressed";

/** Minimal valid 1x1 PNG for cover images. */
function createMinimalPng(): Blob {
  const data = new Uint8Array([
    137, 80, 78, 71, 13, 10, 26, 10,
    0, 0, 0, 13, 73, 72, 68, 82,
    0, 0, 0, 1, 0, 0, 0, 1, 8, 2, 0, 0, 0, 144, 119, 83, 222,
    0, 0, 0, 12, 73, 68, 65, 84,
    8, 215, 99, 248, 207, 192, 0, 0, 0, 4, 0, 1, 2, 127, 225, 72,
    0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130,
  ]);
  return new Blob([data], { type: "image/png" });
}

async function buildShareCardRecipe(imageBytes: Uint8Array): Promise<LuminaRecipe> {
  const state = { ...DEFAULT_STATE, lut_name: "TestLUT", target_width_mm: 123 } as ConverterState;
  const converterRecipe = exportConverterRecipe(state, { ...DEFAULT_SETTINGS }, "fp_test");
  const imageFile = new File([imageBytes], "photo.png", { type: "image/png" });
  const assets = await buildRecipeAssets(imageFile, null);
  return buildFullRecipe(
    converterRecipe,
    { width: 1, height: 1, mime_type: "image/png" },
    assets,
    state.workshopSource,
  );
}

function concatBytes(parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let pos = 0;
  for (const part of parts) {
    out.set(part, pos);
    pos += part.length;
  }
  return out;
}

function latin1(str: string): Uint8Array {
  return Uint8Array.from(str, (ch) => ch.charCodeAt(0));
}

function buildChunk(type: string, data: Uint8Array): Uint8Array {
  const typeBytes = latin1(type);
  const header = new Uint8Array(8);
  new DataView(header.buffer).setUint32(0, data.length);
  header.set(typeBytes, 4);
  const crc = new Uint8Array(4);
  new DataView(crc.buffer).setUint32(0, crc32(concatBytes([typeBytes, data])));
  return concatBytes([header, data, crc]);
}

/** Encode keyword + UTF-8 value as the requested PNG textual chunk. */
function encodeTextualChunk(kind: TextualChunkKind, keyword: string, value: string): Uint8Array {
  const keyBytes = latin1(keyword);
  const valueBytes = new TextEncoder().encode(value);
  const nul = new Uint8Array([0]);
  switch (kind) {
    case "tEXt":
      return buildChunk("tEXt", concatBytes([keyBytes, nul, valueBytes]));
    case "zTXt":
      return buildChunk("zTXt", concatBytes([keyBytes, nul, new Uint8Array([0]), deflateSync(valueBytes)]));
    case "iTXt":
    case "iTXt-compressed": {
      const compressed = kind === "iTXt-compressed";
      const text = compressed ? deflateSync(valueBytes) : valueBytes;
      // keyword NUL flag method language NUL translated-keyword NUL text
      return buildChunk(
        "iTXt",
        concatBytes([keyBytes, nul, new Uint8Array([compressed ? 1 : 0, 0]), nul, nul, text]),
      );
    }
  }
}

/**
 * Rewrite every tEXt chunk whose keyword is in `keywords` into `kind`,
 * mimicking an external re-save of a share card.
 */
async function rewriteTextChunks(
  png: Blob,
  keywords: ReadonlySet<string>,
  kind: TextualChunkKind,
): Promise<Blob> {
  const bytes = new Uint8Array(await png.arrayBuffer());
  const view = new DataView(bytes.buffer);
  const parts: Uint8Array[] = [bytes.subarray(0, 8)];
  let pos = 8;
  while (pos < bytes.length) {
    const length = view.getUint32(pos);
    const type = String.fromCharCode(...bytes.subarray(pos + 4, pos + 8));
    const data = bytes.subarray(pos + 8, pos + 8 + length);
    const nullIdx = data.indexOf(0);
    const keyword = type === "tEXt" && nullIdx >= 0 ? String.fromCharCode(...data.subarray(0, nullIdx)) : "";
    if (keywords.has(keyword)) {
      const value = new TextDecoder().decode(data.subarray(nullIdx + 1));
      parts.push(encodeTextualChunk(kind, keyword, value));
    } else {
      parts.push(bytes.subarray(pos, pos + 12 + length));
    }
    pos += 12 + length;
  }
  return new Blob([concatBytes(parts)], { type: "image/png" });
}

async function listChunkTypes(png: Blob): Promise<string[]> {
  const bytes = new Uint8Array(await png.arrayBuffer());
  const view = new DataView(bytes.buffer);
  const types: string[] = [];
  for (let pos = 8; pos < bytes.length; pos += 12 + view.getUint32(pos)) {
    types.push(String.fromCharCode(...bytes.subarray(pos + 4, pos + 8)));
  }
  return types;
}

describe("share-card PNG textual chunk compatibility", () => {
  it("ignores retired legacy digest chunks and omits them from new cards", async () => {
    const recipe = await buildShareCardRecipe(new Uint8Array([1, 2, 3, 4]));
    const current = await embedRecipeInPng(createMinimalPng(), recipe);
    expect(new TextDecoder().decode(await current.arrayBuffer())).not.toContain("lumina:recipe_sha256");
    const legacy = JSON.parse(JSON.stringify(recipe));
    legacy.schema_version = 3;
    legacy.integrity = { recipe_sha256: "stale", asset_checksums: { primary: "stale" } };
    legacy.asset.primary.sha256 = "stale";
    legacy.recipe.converter.base.target_width_mm = 124;
    const bytes = new Uint8Array(await (await embedRecipeInPng(createMinimalPng(), legacy)).arrayBuffer());
    const staleChunk = encodeTextualChunk("tEXt", "lumina:recipe_sha256", "stale");
    const oldCard = new Blob([concatBytes([bytes.subarray(0, bytes.length - 12), staleChunk, bytes.subarray(bytes.length - 12)])], { type: "image/png" });
    const parsed = await parseRecipeFile(new File([oldCard], "legacy.png", { type: "image/png" }));
    expect(parsed.recipe.recipe.converter!.base.target_width_mm).toBe(124);
    expect(parsed.recipe).not.toHaveProperty("integrity");
    expect(await listChunkTypes(await extractCoverFromPng(oldCard))).toEqual(["IHDR", "IDAT", "IEND"]);
  });

  it.each<TextualChunkKind>(["tEXt", "zTXt", "iTXt", "iTXt-compressed"])(
    "imports a card whose recipe is stored as %s and restores its recipe",
    async (kind) => {
      const recipe = await buildShareCardRecipe(new Uint8Array([1, 2, 3, 4]));
      const embedded = await embedRecipeInPng(createMinimalPng(), recipe);
      const card = await rewriteTextChunks(embedded, new Set([KEY_RECIPE_JSON]), kind);

      const expectedType = kind.startsWith("iTXt") ? "iTXt" : kind;
      expect(await listChunkTypes(card)).toContain(expectedType);

      const parsed = await parseRecipeFile(new File([card], "card.png", { type: "image/png" }));
      expect(parsed.source).toBe("png");
      expect(parsed.recipe.recipe).toEqual(recipe.recipe);
    },
  );

  it("detects a card whose lumina:format marker is compressed", async () => {
    const recipe = await buildShareCardRecipe(new Uint8Array([1, 2, 3, 4]));
    const embedded = await embedRecipeInPng(createMinimalPng(), recipe);
    const card = await rewriteTextChunks(embedded, new Set([KEY_FORMAT, KEY_RECIPE_JSON]), "zTXt");

    expect(await hasLuminaRecipe(card)).toBe(true);
  });

  it("strips compressed Lumina chunks when extracting the cover", async () => {
    const recipe = await buildShareCardRecipe(new Uint8Array([1, 2, 3, 4]));
    const embedded = await embedRecipeInPng(createMinimalPng(), recipe);
    const card = await rewriteTextChunks(embedded, new Set([KEY_RECIPE_JSON]), "zTXt");

    const cover = await extractCoverFromPng(card);
    expect(await listChunkTypes(cover)).toEqual(["IHDR", "IDAT", "IEND"]);
  });

  it("returns null instead of throwing for a corrupt zTXt recipe stream", async () => {
    const recipe = await buildShareCardRecipe(new Uint8Array([1, 2, 3, 4]));
    const embedded = await embedRecipeInPng(createMinimalPng(), recipe);
    const card = await rewriteTextChunks(embedded, new Set([KEY_RECIPE_JSON]), "zTXt");
    const bytes = new Uint8Array(await card.arrayBuffer());
    const typeIdx = bytes.findIndex(
      (_, i) => bytes[i] === 0x7a && String.fromCharCode(...bytes.subarray(i, i + 4)) === "zTXt",
    );
    // Corrupt the zlib header right after "keyword NUL method".
    const zlibStart = typeIdx + 4 + KEY_RECIPE_JSON.length + 2;
    bytes[zlibStart] = 0xff;
    bytes[zlibStart + 1] = 0xff;

    expect(await extractRecipeFromPng(new Blob([bytes], { type: "image/png" }))).toBeNull();
  });

  it(
    "imports a >10 MB recipe stored as zTXt without digest metadata",
    async () => {
      // 8 MB image asset -> ~10.7 MB base64 inside the recipe JSON.
      const imageBytes = new Uint8Array(8 * 1024 * 1024);
      for (let i = 0; i < imageBytes.length; i++) imageBytes[i] = (i * 31 + (i >>> 11)) & 0xff;
      const recipe = await buildShareCardRecipe(imageBytes);
      const recipeJsonBytes = new TextEncoder().encode(JSON.stringify(recipe)).length;
      expect(recipeJsonBytes).toBeGreaterThan(10 * 1024 * 1024);

      const embedded = await embedRecipeInPng(createMinimalPng(), recipe);
      const card = await rewriteTextChunks(embedded, new Set([KEY_RECIPE_JSON]), "zTXt");
      expect(await listChunkTypes(card)).toContain("zTXt");

      const parsed = await parseRecipeFile(new File([card], "large.png", { type: "image/png" }));
      expect(parsed.recipe.asset.primary.byte_size).toBe(imageBytes.length);
      expect(parsed.recipe.asset.primary.payload_b64).toBe(recipe.asset.primary.payload_b64);
    },
    60_000,
  );
});
