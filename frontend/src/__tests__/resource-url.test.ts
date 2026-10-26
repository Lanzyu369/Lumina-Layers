import { describe, expect, it } from "vitest";
import * as fc from "fast-check";
import { normalizeResourceUrl } from "../utils/resourceUrl";

describe("normalizeResourceUrl", () => {
  it("converts absolute backend /api and /output URLs to relative", () => {
    expect(
      normalizeResourceUrl("http://localhost:8000/api/files/a.png"),
    ).toBe("/api/files/a.png");
    expect(
      normalizeResourceUrl("https://example.com/output/batch.zip?x=1#d"),
    ).toBe("/output/batch.zip?x=1#d");
  });

  it("keeps relative URLs unchanged", () => {
    expect(normalizeResourceUrl("/api/files/a.png")).toBe("/api/files/a.png");
    expect(normalizeResourceUrl("/output/batch.zip")).toBe("/output/batch.zip");
    expect(normalizeResourceUrl("api/files/a.png")).toBe("api/files/a.png");
  });

  it("keeps non-resource absolute URLs unchanged", () => {
    expect(normalizeResourceUrl("https://cdn.example.com/image.png")).toBe(
      "https://cdn.example.com/image.png",
    );
  });

  it("preserves query and hash when converting", () => {
    expect(
      normalizeResourceUrl("http://localhost:8000/api/files/a.png?foo=1#bar"),
    ).toBe("/api/files/a.png?foo=1#bar");
  });

  it("property: any absolute /api path normalizes to relative pathname", () => {
    fc.assert(
      fc.property(
        fc.constantFrom("localhost", "api.local", "example", "lumina-dev"),
        fc.stringMatching(/^[a-z0-9_-]{1,20}$/),
        (hostLabel, pathRaw) => {
          const safePath = `/api/${pathRaw.replace(/^\/+/, "")}`;
          const absolute = `https://${hostLabel}.test${safePath}`;

          return normalizeResourceUrl(absolute) === safePath;
        },
      ),
      { numRuns: 100 },
    );
  });
});
