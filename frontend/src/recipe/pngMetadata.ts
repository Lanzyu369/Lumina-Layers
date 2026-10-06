/**
 * PNG tEXt metadata chunk reader/writer for Lumina recipe embedding.
 * PNG tEXt 元数据块读写器，用于 Lumina 配方嵌入。
 *
 * The writer emits standard PNG tEXt chunks (Latin-1 key + UTF-8 value).
 * The reader also accepts zTXt and iTXt, because external tools (e.g.
 * ImageMagick) re-save long tEXt values as compressed zTXt.
 * 写入端使用标准 PNG tEXt 块；读取端同时兼容 zTXt / iTXt，
 * 因为外部工具（如 ImageMagick）重新保存时会把长文本压缩为 zTXt。
 */

import type { LuminaRecipe } from "./types";
import { RECIPE_FORMAT } from "./types";

// ========== PNG Constants ==========

const PNG_SIGNATURE = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);
const CHUNK_TYPE_IEND = "IEND";
const CHUNK_TYPE_TEXT = "tEXt";
const CHUNK_TYPE_ZTXT = "zTXt";
const CHUNK_TYPE_ITXT = "iTXt";
const TEXTUAL_CHUNK_TYPES = new Set([CHUNK_TYPE_TEXT, CHUNK_TYPE_ZTXT, CHUNK_TYPE_ITXT]);
/** The only compression method defined by the PNG spec (zlib/deflate). */
const PNG_COMPRESSION_ZLIB = 0;

// Lumina metadata keys
const KEY_FORMAT = "lumina:format";
const KEY_SCHEMA_VERSION = "lumina:schema_version";
const KEY_RECIPE_JSON = "lumina:recipe_json";

// ========== Low-level PNG helpers ==========

/** Read a 4-byte big-endian unsigned integer from a DataView. */
function readU32(view: DataView, offset: number): number {
  return view.getUint32(offset, false);
}

/** Write a 4-byte big-endian unsigned integer into a DataView. */
function writeU32(view: DataView, offset: number, value: number): void {
  view.setUint32(offset, value, false);
}

/** Encode a string to Latin-1 (ISO 8859-1) bytes. */
function latin1Encode(str: string): Uint8Array {
  const bytes = new Uint8Array(str.length);
  for (let i = 0; i < str.length; i++) {
    bytes[i] = str.charCodeAt(i) & 0xff;
  }
  return bytes;
}

/** Decode Latin-1 bytes to a string. */
function latin1Decode(bytes: Uint8Array): string {
  let str = "";
  for (let i = 0; i < bytes.length; i++) {
    str += String.fromCharCode(bytes[i]);
  }
  return str;
}

// CRC32 lookup table
let _crc32Table: Uint32Array | null = null;

function getCrc32Table(): Uint32Array {
  if (_crc32Table) return _crc32Table;
  _crc32Table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) {
      if (c & 1) {
        c = 0xedb88320 ^ (c >>> 1);
      } else {
        c = c >>> 1;
      }
    }
    _crc32Table[n] = c;
  }
  return _crc32Table;
}

/** Compute CRC32 of a byte sequence. */
function crc32(data: Uint8Array): number {
  const table = getCrc32Table();
  let crc = 0xffffffff;
  for (let i = 0; i < data.length; i++) {
    crc = table[(crc ^ data[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

/** Compute CRC32 over the chunk type + chunk data (per PNG spec). */
function chunkCrc(typeBytes: Uint8Array, dataBytes: Uint8Array): number {
  const combined = new Uint8Array(typeBytes.length + dataBytes.length);
  combined.set(typeBytes, 0);
  combined.set(dataBytes, typeBytes.length);
  return crc32(combined);
}

// ========== tEXt chunk construction ==========

/**
 * Build a PNG tEXt chunk: length(4) + "tEXt"(4) + data + crc(4).
 * Data = keyword + null separator + text value.
 */
function buildTextChunk(keyword: string, value: string): Uint8Array {
  const keyBytes = latin1Encode(keyword);
  const valBytes = new TextEncoder().encode(value);
  const dataLen = keyBytes.length + 1 + valBytes.length; // +1 for null separator

  const chunk = new Uint8Array(4 + 4 + dataLen + 4);
  const view = new DataView(chunk.buffer);

  // Length
  writeU32(view, 0, dataLen);

  // Type
  const typeBytes = latin1Encode(CHUNK_TYPE_TEXT);
  chunk.set(typeBytes, 4);

  // Data: keyword + \0 + value
  const dataBytes = new Uint8Array(dataLen);
  dataBytes.set(keyBytes, 0);
  dataBytes[keyBytes.length] = 0; // null separator
  dataBytes.set(valBytes, keyBytes.length + 1);
  chunk.set(dataBytes, 8);

  // CRC (over type + data)
  const crcVal = chunkCrc(typeBytes, dataBytes);
  writeU32(view, 8 + dataLen, crcVal);

  return chunk;
}

// ========== PNG chunk iteration ==========

interface PngChunk {
  type: string;
  data: Uint8Array;
  offset: number; // byte offset of the chunk start (length field) in original buffer
  totalLength: number; // 4 (length) + 4 (type) + dataLength + 4 (crc)
}

/** Iterate over PNG chunks, yielding { type, data, offset, totalLength }. */
function* iterateChunks(buffer: ArrayBuffer): Generator<PngChunk> {
  const view = new DataView(buffer);
  const bytes = new Uint8Array(buffer);
  let pos = 8; // skip PNG signature

  while (pos < buffer.byteLength) {
    const dataLength = readU32(view, pos);
    const typeBytes = bytes.slice(pos + 4, pos + 8);
    const type = latin1Decode(typeBytes);
    const data = bytes.slice(pos + 8, pos + 8 + dataLength);
    const totalLength = 4 + 4 + dataLength + 4;

    yield { type, data, offset: pos, totalLength };

    pos += totalLength;

    if (type === CHUNK_TYPE_IEND) break;
  }
}

/** Parse a tEXt chunk data into { keyword, value }. */
function parseTextChunkData(data: Uint8Array): { keyword: string; value: string } | null {
  const nullIdx = data.indexOf(0);
  if (nullIdx < 0) return null;
  const keyword = latin1Decode(data.slice(0, nullIdx));
  // Value may contain multi-byte UTF-8 encoded as raw bytes
  const value = new TextDecoder().decode(data.slice(nullIdx + 1));
  return { keyword, value };
}

/** Read the null-terminated keyword of any textual chunk without decoding its value. */
function readChunkKeyword(data: Uint8Array): string | null {
  const nullIdx = data.indexOf(0);
  return nullIdx < 0 ? null : latin1Decode(data.subarray(0, nullIdx));
}

/** Inflate a zlib (RFC 1950) stream; returns null when unsupported or corrupt. */
async function inflateZlib(compressed: Uint8Array): Promise<Uint8Array | null> {
  if (typeof DecompressionStream === "undefined") return null;
  try {
    const source = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(compressed);
        controller.close();
      },
    });
    const reader = source.pipeThrough(new DecompressionStream("deflate")).getReader();
    const parts: Uint8Array[] = [];
    let total = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      parts.push(value);
      total += value.length;
    }
    const out = new Uint8Array(total);
    let pos = 0;
    for (const part of parts) {
      out.set(part, pos);
      pos += part.length;
    }
    return out;
  } catch {
    return null;
  }
}

/** Parse zTXt data: keyword NUL compression-method(1) zlib-stream. */
async function parseZtxtChunkData(
  data: Uint8Array,
): Promise<{ keyword: string; value: string } | null> {
  const nullIdx = data.indexOf(0);
  if (nullIdx < 0 || data[nullIdx + 1] !== PNG_COMPRESSION_ZLIB) return null;
  const inflated = await inflateZlib(data.subarray(nullIdx + 2));
  if (!inflated) return null;
  const keyword = latin1Decode(data.subarray(0, nullIdx));
  return { keyword, value: new TextDecoder().decode(inflated) };
}

/**
 * Parse iTXt data: keyword NUL compression-flag(1) compression-method(1)
 * language-tag NUL translated-keyword NUL text (UTF-8, optionally zlib).
 */
async function parseItxtChunkData(
  data: Uint8Array,
): Promise<{ keyword: string; value: string } | null> {
  const keywordEnd = data.indexOf(0);
  if (keywordEnd < 0) return null;
  const compressionFlag = data[keywordEnd + 1];
  const compressionMethod = data[keywordEnd + 2];
  const languageEnd = data.indexOf(0, keywordEnd + 3);
  if (languageEnd < 0) return null;
  const translatedEnd = data.indexOf(0, languageEnd + 1);
  if (translatedEnd < 0) return null;

  let textBytes: Uint8Array | null = data.subarray(translatedEnd + 1);
  if (compressionFlag === 1) {
    if (compressionMethod !== PNG_COMPRESSION_ZLIB) return null;
    textBytes = await inflateZlib(textBytes);
    if (!textBytes) return null;
  }
  const keyword = latin1Decode(data.subarray(0, keywordEnd));
  return { keyword, value: new TextDecoder().decode(textBytes) };
}

/** Decode a tEXt / zTXt / iTXt chunk into { keyword, value }; null for other chunks. */
async function readTextualChunk(
  chunk: PngChunk,
): Promise<{ keyword: string; value: string } | null> {
  switch (chunk.type) {
    case CHUNK_TYPE_TEXT:
      return parseTextChunkData(chunk.data);
    case CHUNK_TYPE_ZTXT:
      return parseZtxtChunkData(chunk.data);
    case CHUNK_TYPE_ITXT:
      return parseItxtChunkData(chunk.data);
    default:
      return null;
  }
}

/**
 * Find the value of the first textual chunk with the given keyword.
 * Only chunks whose keyword matches are decompressed.
 */
async function findTextualValue(buffer: ArrayBuffer, keyword: string): Promise<string | null> {
  for (const chunk of iterateChunks(buffer)) {
    if (!TEXTUAL_CHUNK_TYPES.has(chunk.type)) continue;
    if (readChunkKeyword(chunk.data) !== keyword) continue;
    const parsed = await readTextualChunk(chunk);
    if (parsed) return parsed.value;
  }
  return null;
}

// ========== Public API ==========

/**
 * Embed a LuminaRecipe into a PNG blob by inserting tEXt chunks before IEND.
 * 在 PNG blob 的 IEND 之前插入 tEXt 块以嵌入 LuminaRecipe。
 *
 * @param coverPng - The cover image PNG blob (becomes the visible layer).
 * @param recipe - The full LuminaRecipe to embed.
 * @returns A new PNG Blob with embedded metadata.
 */
export async function embedRecipeInPng(
  coverPng: Blob,
  recipe: LuminaRecipe,
): Promise<Blob> {
  const buffer = await coverPng.arrayBuffer();
  const originalBytes = new Uint8Array(buffer);

  // Validate PNG signature
  for (let i = 0; i < PNG_SIGNATURE.length; i++) {
    if (originalBytes[i] !== PNG_SIGNATURE[i]) {
      throw new Error("Invalid PNG file: signature mismatch");
    }
  }

  const recipeJson = JSON.stringify(recipe);

  // Build metadata chunks
  const formatChunk = buildTextChunk(KEY_FORMAT, RECIPE_FORMAT);
  const versionChunk = buildTextChunk(KEY_SCHEMA_VERSION, String(recipe.schema_version));
  const jsonChunk = buildTextChunk(KEY_RECIPE_JSON, recipeJson);

  // Find IEND chunk offset
  let iendOffset = -1;
  for (const chunk of iterateChunks(buffer)) {
    if (chunk.type === CHUNK_TYPE_IEND) {
      iendOffset = chunk.offset;
      break;
    }
  }

  if (iendOffset < 0) {
    throw new Error("Invalid PNG file: missing IEND chunk");
  }

  // Build new PNG: [before IEND] + [metadata chunks] + [IEND chunk]
  const beforeIend = originalBytes.slice(0, iendOffset);
  const iendAndAfter = originalBytes.slice(iendOffset);

  const totalSize =
    beforeIend.length +
    formatChunk.length +
    versionChunk.length +
    jsonChunk.length +
    iendAndAfter.length;

  const result = new Uint8Array(totalSize);
  let pos = 0;

  result.set(beforeIend, pos);
  pos += beforeIend.length;

  result.set(formatChunk, pos);
  pos += formatChunk.length;

  result.set(versionChunk, pos);
  pos += versionChunk.length;

  result.set(jsonChunk, pos);
  pos += jsonChunk.length;

  result.set(iendAndAfter, pos);

  return new Blob([result], { type: "image/png" });
}

/**
 * Extract a LuminaRecipe from a PNG blob's tEXt / zTXt / iTXt metadata.
 * 从 PNG blob 的 tEXt / zTXt / iTXt 元数据中提取 LuminaRecipe。
 *
 * @returns The parsed recipe, or null if no Lumina metadata found.
 */
export async function extractRecipeFromPng(
  pngBlob: Blob,
): Promise<LuminaRecipe | null> {
  const buffer = await pngBlob.arrayBuffer();
  const bytes = new Uint8Array(buffer);

  // Validate PNG signature
  for (let i = 0; i < PNG_SIGNATURE.length; i++) {
    if (bytes[i] !== PNG_SIGNATURE[i]) {
      return null;
    }
  }

  const recipeJson = await findTextualValue(buffer, KEY_RECIPE_JSON);
  if (!recipeJson) return null;

  try {
    return JSON.parse(recipeJson) as LuminaRecipe;
  } catch {
    return null;
  }
}

/**
 * Quickly check if a PNG blob contains Lumina recipe metadata.
 * 快速检测 PNG blob 是否包含 Lumina 配方元数据。
 */
export async function hasLuminaRecipe(pngBlob: Blob): Promise<boolean> {
  const buffer = await pngBlob.arrayBuffer();
  const bytes = new Uint8Array(buffer);

  // Validate PNG signature
  for (let i = 0; i < PNG_SIGNATURE.length; i++) {
    if (bytes[i] !== PNG_SIGNATURE[i]) {
      return false;
    }
  }

  return (await findTextualValue(buffer, KEY_FORMAT)) === RECIPE_FORMAT;
}

/**
 * Extract the cover image (visible PNG layer) from a share card PNG.
 * This strips all Lumina tEXt / zTXt / iTXt metadata chunks and returns a clean PNG.
 * 从分享卡 PNG 中提取封面图（可视 PNG 层），去掉所有 Lumina 文本元数据块。
 */
export async function extractCoverFromPng(pngBlob: Blob): Promise<Blob> {
  const buffer = await pngBlob.arrayBuffer();
  const originalBytes = new Uint8Array(buffer);

  const parts: BlobPart[] = [new Uint8Array(PNG_SIGNATURE)];

  for (const chunk of iterateChunks(buffer)) {
    if (TEXTUAL_CHUNK_TYPES.has(chunk.type)) {
      const keyword = readChunkKeyword(chunk.data);
      if (keyword?.startsWith("lumina:")) {
        continue; // Skip Lumina metadata chunks
      }
    }
    parts.push(originalBytes.slice(chunk.offset, chunk.offset + chunk.totalLength));
  }

  return new Blob(parts, { type: "image/png" });
}
