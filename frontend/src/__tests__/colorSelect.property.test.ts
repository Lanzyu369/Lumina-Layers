import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import {
  extractHexFromMeshName,
} from "../components/InteractiveModelViewer";

// ========== Generators ==========

/** Generate a valid 6-character lowercase hex string */
const hexColor = fc
  .stringMatching(/^[0-9a-f]{6}$/)
  .filter((s) => s.length === 6);

// ========== Tests ==========

describe("Color Selection Interaction — Property-Based Tests", () => {
  // Validates: Requirements 2.1
  describe("P1: hex extraction roundtrip — color_ prefix + slice(6)", () => {
    it("for any valid 6-char hex h, extractHexFromMeshName('color_' + h) === h", () => {
      fc.assert(
        fc.property(hexColor, (h) => {
          const meshName = "color_" + h;
          const extracted = extractHexFromMeshName(meshName);
          expect(extracted).toBe(h);
        }),
        { numRuns: 200 },
      );
    });
  });
});
