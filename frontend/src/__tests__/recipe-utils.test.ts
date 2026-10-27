import { describe, it, expect } from "vitest";
import { fileToBase64, base64ToFile, buildAssetEntry } from "../recipe/utils";

describe("recipe/utils", () => {
  describe("fileToBase64 / base64ToFile round-trip", () => {
    it("round-trips a small file correctly", async () => {
      const content = new Uint8Array([0, 1, 2, 255, 128, 64]);
      const originalFile = new File([content], "test.bin", { type: "application/octet-stream" });

      const b64 = await fileToBase64(originalFile);
      expect(typeof b64).toBe("string");
      expect(b64.length).toBeGreaterThan(0);

      const restored = base64ToFile(b64, "test.bin", "application/octet-stream");
      expect(restored.name).toBe("test.bin");
      expect(restored.type).toBe("application/octet-stream");
      expect(restored.size).toBe(originalFile.size);

      const originalBytes = new Uint8Array(await originalFile.arrayBuffer());
      const restoredBytes = new Uint8Array(await restored.arrayBuffer());
      expect(restoredBytes).toEqual(originalBytes);
    });

    it("preserves filename and MIME type", async () => {
      const file = new File(["svg content"], "image.svg", { type: "image/svg+xml" });
      const b64 = await fileToBase64(file);
      const restored = base64ToFile(b64, "image.svg", "image/svg+xml");
      expect(restored.name).toBe("image.svg");
      expect(restored.type).toBe("image/svg+xml");
    });
  });

  describe("buildAssetEntry", () => {
    it("builds correct AssetEntry with its bytes as base64", async () => {
      const content = new TextEncoder().encode("test content");
      const file = new File([content], "test.txt", { type: "text/plain" });

      const entry = await buildAssetEntry(file);
      expect(entry.filename).toBe("test.txt");
      expect(entry.mime_type).toBe("text/plain");
      expect(entry.byte_size).toBe(file.size);
      expect(entry.encoding).toBe("base64");
      expect(entry).not.toHaveProperty("sha256");
      expect(entry.payload_b64.length).toBeGreaterThan(0);

    });
  });
});
