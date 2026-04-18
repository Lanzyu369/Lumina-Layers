import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

/**
 * Guard against mojibake markers sneaking into user-facing tooltip strings
 * in `LutColorGrid.tsx`.
 *
 * Background: the two `title={...}` template literals in this file use a
 * middle-dot separator (`·`, U+00B7). A past non-UTF-8 write had corrupted
 * that separator into the glyph `路` (U+8DEF, Chinese "road"), which then
 * surfaced as a stray Chinese character in the color-swatch tooltip. Per
 * `AGENTS.md`, we should treat such glyphs as real data corruption.
 *
 * 守护 `LutColorGrid.tsx` 里面向用户的 tooltip 字符串，避免乱码再次潜入。
 * 背景：文件中两处 `title={...}` 模板字符串使用的是中间点分隔符（`·`，
 * U+00B7）。之前一次非 UTF-8 写入把分隔符破坏成了「路」（U+8DEF），结果
 * 色块 tooltip 里会出现一个没来由的中文字。按 `AGENTS.md` 的要求，这类字
 * 符应当被视为真实的编码损坏。
 */
const MOJIBAKE_MARKERS: ReadonlyArray<{ char: string; why: string }> = [
  { char: "路", why: "known 0xB7 corruption of middle-dot separator" },
  { char: "锟", why: "classic GBK-as-UTF-8 replacement glyph" },
  { char: "鎷", why: "classic GBK-as-UTF-8 replacement glyph" },
  { char: "鍙", why: "classic GBK-as-UTF-8 replacement glyph" },
  { char: "涓", why: "classic GBK-as-UTF-8 replacement glyph" },
];

describe("LutColorGrid source encoding", () => {
  it("contains no known mojibake markers", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const source = readFileSync(
      resolve(here, "../components/sections/LutColorGrid.tsx"),
      "utf-8",
    );

    const hits = MOJIBAKE_MARKERS.filter((m) => source.includes(m.char));
    expect(
      hits,
      `Mojibake markers found in LutColorGrid.tsx: ${hits
        .map((h) => `${h.char} (${h.why})`)
        .join(", ")}`,
    ).toEqual([]);
  });

  it("keeps the middle-dot separator intact in tooltip templates", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const source = readFileSync(
      resolve(here, "../components/sections/LutColorGrid.tsx"),
      "utf-8",
    );

    // The file has two `title={...}` template literals whose human-readable
    // form uses `·` between the hex value and the description. If someone
    // reintroduces the broken separator, this assertion will fail.
    // 该文件有两处 `title={...}` 模板字符串，用 `·` 分隔 hex 与描述。
    // 如果有人再次引入错误的分隔符，本断言会失败。
    const middleDotCount = (source.match(/·/g) ?? []).length;
    expect(middleDotCount).toBeGreaterThanOrEqual(2);
  });
});
