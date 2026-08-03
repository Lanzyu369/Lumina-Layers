const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const {
  MAX_WORKSHOP_IMAGE_BYTES,
  loadWorkshopImageFile,
} = require("../workshop-file-picker.cjs");

describe("Workshop desktop image picker", () => {
  it("returns only a basename, MIME type, and bytes", async () => {
    const bytes = Buffer.from([137, 80, 78, 71]);
    let closed = 0;
    const result = await loadWorkshopImageFile(
      "/private/tmp/pattern.PNG",
      {
        open: async () => ({
          stat: async () => ({
            isFile: () => true,
            size: bytes.byteLength,
          }),
          read: async (target, offset, length, position) => {
            bytes.copy(target, offset, position, position + length);
            return { bytesRead: length };
          },
          close: async () => {
            closed += 1;
          },
        }),
      },
    );

    assert.deepEqual(result, {
      name: "pattern.PNG",
      mimeType: "image/png",
      bytes: new Uint8Array(bytes),
    });
    assert.equal("path" in result, false);
    assert.equal(closed, 1);
  });

  it("rejects unsupported extensions and oversized files before reading", async () => {
    let opens = 0;
    let reads = 0;
    let closes = 0;
    const dependencies = {
      open: async () => {
        opens += 1;
        return {
          stat: async () => ({
            isFile: () => true,
            size: MAX_WORKSHOP_IMAGE_BYTES + 1,
          }),
          read: async () => {
            reads += 1;
            return { bytesRead: 0 };
          },
          close: async () => {
            closes += 1;
          },
        };
      },
    };

    await assert.rejects(
      loadWorkshopImageFile("/private/tmp/pattern.svg", dependencies),
      /supported image/i,
    );
    assert.equal(opens, 0);
    await assert.rejects(
      loadWorkshopImageFile("/private/tmp/pattern.png", dependencies),
      /64 MiB/i,
    );
    assert.equal(opens, 1);
    assert.equal(reads, 0);
    assert.equal(closes, 1);
  });

  it("fails closed if the selected file shrinks during a bounded read", async () => {
    let closed = 0;
    await assert.rejects(
      loadWorkshopImageFile("/private/tmp/pattern.png", {
        open: async () => ({
          stat: async () => ({
            isFile: () => true,
            size: 4,
          }),
          read: async () => ({ bytesRead: 0 }),
          close: async () => {
            closed += 1;
          },
        }),
      }),
      /changed while it was being read/i,
    );
    assert.equal(closed, 1);
  });
});
