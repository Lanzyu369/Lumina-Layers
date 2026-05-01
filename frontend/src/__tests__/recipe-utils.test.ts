import { afterEach, describe, it, expect, vi } from "vitest";
import { sha256Hex, sha256String, fileToBase64, base64ToFile, buildAssetEntry } from "../recipe/utils";

describe("recipe/utils", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("sha256Hex", () => {
    it("computes correct SHA-256 for empty buffer", async () => {
      const hash = await sha256Hex(new ArrayBuffer(0));
      expect(hash).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    });

    it("computes correct SHA-256 for known input", async () => {
      const encoder = new TextEncoder();
      const hash = await sha256Hex(encoder.encode("hello").buffer as ArrayBuffer);
      expect(hash).toBe("2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824");
    });

    it("falls back when Web Crypto digest is unavailable", async () => {
      const originalCrypto = globalThis.crypto;
      Object.defineProperty(globalThis, "crypto", {
        configurable: true,
        value: {},
      });

      try {
        const encoder = new TextEncoder();
        const hash = await sha256Hex(encoder.encode("hello").buffer as ArrayBuffer);
        expect(hash).toBe("2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824");
      } finally {
        Object.defineProperty(globalThis, "crypto", {
          configurable: true,
          value: originalCrypto,
        });
      }
    });

    it("falls back when Web Crypto digest rejects", async () => {
      const originalCrypto = globalThis.crypto;
      Object.defineProperty(globalThis, "crypto", {
        configurable: true,
        value: {
          subtle: {
            digest: vi.fn().mockRejectedValue(new Error("blocked")),
          },
        },
      });

      try {
        const encoder = new TextEncoder();
        const hash = await sha256Hex(encoder.encode("hello").buffer as ArrayBuffer);
        expect(hash).toBe("2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824");
      } finally {
        Object.defineProperty(globalThis, "crypto", {
          configurable: true,
          value: originalCrypto,
        });
      }
    });
  });

  describe("sha256String", () => {
    it("computes SHA-256 of a UTF-8 string", async () => {
      const hash = await sha256String("hello");
      expect(hash).toBe("2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824");
    });
  });

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
    it("builds correct AssetEntry with sha256 and base64", async () => {
      const content = new TextEncoder().encode("test content");
      const file = new File([content], "test.txt", { type: "text/plain" });

      const entry = await buildAssetEntry(file);
      expect(entry.filename).toBe("test.txt");
      expect(entry.mime_type).toBe("text/plain");
      expect(entry.byte_size).toBe(file.size);
      expect(entry.encoding).toBe("base64");
      expect(entry.sha256).toHaveLength(64);
      expect(entry.payload_b64.length).toBeGreaterThan(0);

      // Verify sha256 matches content
      const expectedHash = await sha256Hex(content.buffer as ArrayBuffer);
      expect(entry.sha256).toBe(expectedHash);
    });
  });
});
