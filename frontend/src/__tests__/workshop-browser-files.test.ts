import { describe, expect, it, vi } from "vitest";

import {
  WorkshopFileError,
  chooseWorkshopImageFile,
  createBrowserWorkshopFileServices,
  isSupportedWorkshopImage,
} from "../workshop/browserFiles";
import type { WorkshopRaster } from "../workshop/types";

const RASTER: WorkshopRaster = {
  width: 1,
  height: 1,
  data: new Uint8ClampedArray([10, 20, 30, 255]),
};

describe("browser workshop file services", () => {
  it("uses the narrow Electron picker without exposing a filesystem path", async () => {
    const bytes = new Uint8Array([137, 80, 78, 71]);
    const pickWorkshopImage = vi.fn().mockResolvedValue({
      name: "pattern.png",
      mimeType: "image/png",
      bytes,
    });

    const file = await chooseWorkshopImageFile({
      pickWorkshopImage,
    });

    expect(pickWorkshopImage).toHaveBeenCalledOnce();
    expect(file).toBeInstanceOf(File);
    expect(file).toMatchObject({
      name: "pattern.png",
      type: "image/png",
      size: bytes.byteLength,
    });
    expect(file).not.toHaveProperty("path");
  });

  it("accepts only PNG, JPEG, and WebP source images", () => {
    expect(
      isSupportedWorkshopImage(
        new File(["png"], "pattern.png", { type: "image/png" }),
      ),
    ).toBe(true);
    expect(
      isSupportedWorkshopImage(
        new File(["jpg"], "pattern.jpg", { type: "image/jpeg" }),
      ),
    ).toBe(true);
    expect(
      isSupportedWorkshopImage(
        new File(["webp"], "pattern.webp", { type: "image/webp" }),
      ),
    ).toBe(true);
    expect(
      isSupportedWorkshopImage(
        new File(["svg"], "pattern.svg", { type: "image/svg+xml" }),
      ),
    ).toBe(false);
  });

  it("returns null without decoding when the picker is cancelled", async () => {
    const decode = vi.fn();
    const services = createBrowserWorkshopFileServices({
      chooseImageFile: vi.fn().mockResolvedValue(null),
      decodeImage: decode,
      encodePng: vi.fn(),
    });

    await expect(services.pickImage()).resolves.toBeNull();
    expect(decode).not.toHaveBeenCalled();
  });

  it("decodes a selected supported file and preserves its File identity", async () => {
    const file = new File(["png"], "pattern.png", { type: "image/png" });
    const decode = vi.fn().mockResolvedValue(RASTER);
    const services = createBrowserWorkshopFileServices({
      chooseImageFile: vi.fn().mockResolvedValue(file),
      decodeImage: decode,
      encodePng: vi.fn(),
    });

    await expect(services.pickImage()).resolves.toEqual({
      file,
      raster: RASTER,
    });
    expect(decode).toHaveBeenCalledWith(file);
  });

  it("rejects an unsupported selected file before decoding", async () => {
    const file = new File(["svg"], "pattern.svg", {
      type: "image/svg+xml",
    });
    const decode = vi.fn();
    const services = createBrowserWorkshopFileServices({
      chooseImageFile: vi.fn().mockResolvedValue(file),
      decodeImage: decode,
      encodePng: vi.fn(),
    });

    await expect(services.pickImage()).rejects.toMatchObject({
      code: "unsupported-image-type",
    } satisfies Partial<WorkshopFileError>);
    expect(decode).not.toHaveBeenCalled();
  });

  it("delegates deterministic PNG encoding through the same service", async () => {
    const png = new File(["png"], "beads.png", { type: "image/png" });
    const encode = vi.fn().mockResolvedValue(png);
    const services = createBrowserWorkshopFileServices({
      chooseImageFile: vi.fn(),
      decodeImage: vi.fn(),
      encodePng: encode,
    });

    await expect(services.encodePng(RASTER, "beads.png")).resolves.toBe(png);
    expect(encode).toHaveBeenCalledWith(RASTER, "beads.png");
  });
});
