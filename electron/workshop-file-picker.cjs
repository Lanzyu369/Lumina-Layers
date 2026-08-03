"use strict";

const fs = require("node:fs/promises");
const path = require("node:path");

const MAX_WORKSHOP_IMAGE_BYTES = 64 * 1024 * 1024;
const MIME_BY_EXTENSION = new Map([
  [".jpeg", "image/jpeg"],
  [".jpg", "image/jpeg"],
  [".png", "image/png"],
  [".webp", "image/webp"],
]);

async function loadWorkshopImageFile(
  filePath,
  dependencies = {
    open: fs.open,
  },
) {
  if (typeof filePath !== "string" || !path.isAbsolute(filePath)) {
    throw new Error("Workshop image selection must be an absolute path.");
  }
  const mimeType = MIME_BY_EXTENSION.get(
    path.extname(filePath).toLowerCase(),
  );
  if (mimeType === undefined) {
    throw new Error("Select a supported image: PNG, JPEG, or WebP.");
  }

  const handle = await dependencies.open(filePath, "r");
  try {
    const fileStat = await handle.stat();
    if (
      !fileStat.isFile() ||
      !Number.isSafeInteger(fileStat.size) ||
      fileStat.size <= 0 ||
      fileStat.size > MAX_WORKSHOP_IMAGE_BYTES
    ) {
      throw new Error(
        "Workshop images must be files no larger than 64 MiB.",
      );
    }
    const bytes = Buffer.alloc(fileStat.size);
    let offset = 0;
    while (offset < bytes.byteLength) {
      const { bytesRead } = await handle.read(
        bytes,
        offset,
        bytes.byteLength - offset,
        offset,
      );
      if (bytesRead <= 0) {
        throw new Error(
          "Workshop image changed while it was being read.",
        );
      }
      offset += bytesRead;
    }
    return {
      name: path.basename(filePath),
      mimeType,
      bytes: Uint8Array.from(bytes),
    };
  } finally {
    await handle.close();
  }
}

module.exports = {
  MAX_WORKSHOP_IMAGE_BYTES,
  loadWorkshopImageFile,
};
