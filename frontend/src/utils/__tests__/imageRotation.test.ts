import { describe, expect, it, vi } from "vitest";
import {
  drawRotatedImageToCanvas,
  rotateImageFile,
  resolveRotatedImageSize,
} from "../imageRotation";

describe("image rotation helpers", () => {
  it("swaps exported canvas dimensions for 90 and 270 degree rotations", () => {
    expect(resolveRotatedImageSize(120, 80, 90)).toEqual({ width: 80, height: 120 });
    expect(resolveRotatedImageSize(120, 80, 180)).toEqual({ width: 120, height: 80 });
    expect(resolveRotatedImageSize(120, 80, 270)).toEqual({ width: 80, height: 120 });
  });

  it("draws 90 degree rotation around the top-right output corner", () => {
    const context = {
      translate: vi.fn(),
      rotate: vi.fn(),
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D;
    const image = {} as CanvasImageSource;

    drawRotatedImageToCanvas(context, image, 120, 80, 90);

    expect(context.translate).toHaveBeenCalledWith(80, 0);
    expect(context.rotate).toHaveBeenCalledWith(Math.PI / 2);
    expect(context.drawImage).toHaveBeenCalledWith(image, 0, 0, 120, 80);
  });

  it("draws 180 and 270 degree rotations with expected transforms", () => {
    const image = {} as CanvasImageSource;
    const context180 = {
      translate: vi.fn(),
      rotate: vi.fn(),
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D;
    const context270 = {
      translate: vi.fn(),
      rotate: vi.fn(),
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D;

    drawRotatedImageToCanvas(context180, image, 120, 80, 180);
    drawRotatedImageToCanvas(context270, image, 120, 80, 270);

    expect(context180.translate).toHaveBeenCalledWith(120, 80);
    expect(context180.rotate).toHaveBeenCalledWith(Math.PI);
    expect(context270.translate).toHaveBeenCalledWith(0, 120);
    expect(context270.rotate).toHaveBeenCalledWith((3 * Math.PI) / 2);
  });

  it("keeps SVG inputs as SVG files after rotation", async () => {
    const source = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 80"><rect width="120" height="80" /></svg>`;
    const file = new File([source], "vector.svg", { type: "image/svg+xml" });

    const rotated = await rotateImageFile(file, "blob:unused-for-svg", 90);
    const rotatedText = await rotated.text();

    expect(rotated.name).toBe("vector_rotated_90.svg");
    expect(rotated.type).toBe("image/svg+xml");
    expect(rotatedText).toContain('viewBox="0 0 80 120"');
    expect(rotatedText).toContain("rotate(90)");
    expect(rotatedText).toContain("<rect");
    expect(rotatedText.match(/viewBox=/g)).toHaveLength(2);
    expect(rotatedText.match(/preserveAspectRatio=/g)).toHaveLength(1);
    expect(rotatedText).not.toContain("data:image/svg+xml");
  });

  it("uses SVG width and height when viewBox is absent", async () => {
    const source = `<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80"><rect width="120" height="80" /></svg>`;
    const file = new File([source], "no-viewbox.svg", { type: "image/svg+xml" });

    const rotated = await rotateImageFile(file, "blob:unused-for-svg", 90);
    const rotatedText = await rotated.text();

    expect(rotatedText).toContain('viewBox="0 0 80 120"');
    expect(rotatedText).toContain('viewBox="0 0 120 80"');
  });
});
