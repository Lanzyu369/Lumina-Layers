import { describe, expect, it } from "vitest";
import {
  extractHexFromMeshName,
} from "../components/InteractiveModelViewer";

describe("extractHexFromMeshName", () => {
  it('extracts hex from "color_ff0000"', () => {
    expect(extractHexFromMeshName("color_ff0000")).toBe("ff0000");
  });

  it('extracts hex from "color_00ff00"', () => {
    expect(extractHexFromMeshName("color_00ff00")).toBe("00ff00");
  });

  it('extracts hex from "color_AABBCC" preserving case', () => {
    expect(extractHexFromMeshName("color_AABBCC")).toBe("AABBCC");
  });

  it("extracts hex from color_ prefix with 6 chars", () => {
    expect(extractHexFromMeshName("color_000000")).toBe("000000");
    expect(extractHexFromMeshName("color_ffffff")).toBe("ffffff");
  });
});

