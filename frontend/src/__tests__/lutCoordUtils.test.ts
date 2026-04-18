import { describe, it, expect, vi } from "vitest";
import {
  getObjectFitRect,
  lutClickToCell,
  getCellOverlayStyle,
  sampleCellHexColor,
  type RenderedImageRect,
} from "../utils/lutCoordUtils";

// ========== getObjectFitRect ==========

describe("getObjectFitRect", () => {
  it("正方形图像在正方形容器中 → 无偏移，尺寸填满", () => {
    const result = getObjectFitRect(512, 512, 512, 512);
    expect(result).toEqual({ offsetX: 0, offsetY: 0, width: 512, height: 512 });
  });

  it("宽图像在正方形容器中 → 上下留白 (offsetY > 0)", () => {
    // 1000x500 image in 400x400 container
    // ratio = min(400/1000, 400/500) = min(0.4, 0.8) = 0.4
    // renderedW = 1000 * 0.4 = 400, renderedH = 500 * 0.4 = 200
    // offsetX = (400 - 400) / 2 = 0, offsetY = (400 - 200) / 2 = 100
    const result = getObjectFitRect(1000, 500, 400, 400);
    expect(result.offsetX).toBe(0);
    expect(result.offsetY).toBe(100);
    expect(result.width).toBe(400);
    expect(result.height).toBe(200);
  });

  it("窄/高图像在正方形容器中 → 左右留白 (offsetX > 0)", () => {
    // 500x1000 image in 400x400 container
    // ratio = min(400/500, 400/1000) = min(0.8, 0.4) = 0.4
    // renderedW = 500 * 0.4 = 200, renderedH = 1000 * 0.4 = 400
    // offsetX = (400 - 200) / 2 = 100, offsetY = (400 - 400) / 2 = 0
    const result = getObjectFitRect(500, 1000, 400, 400);
    expect(result.offsetX).toBe(100);
    expect(result.offsetY).toBe(0);
    expect(result.width).toBe(200);
    expect(result.height).toBe(400);
  });

  it("naturalWidth 为 0 → 返回零尺寸区域", () => {
    const result = getObjectFitRect(0, 500, 400, 400);
    expect(result).toEqual({ offsetX: 0, offsetY: 0, width: 0, height: 0 });
  });

  it("clientHeight 为 0 → 返回零尺寸区域", () => {
    const result = getObjectFitRect(512, 512, 400, 0);
    expect(result).toEqual({ offsetX: 0, offsetY: 0, width: 0, height: 0 });
  });
});

// ========== lutClickToCell ==========

describe("lutClickToCell", () => {
  // 4x4 grid on a 400x400 rendered image with no offset
  const rendered: RenderedImageRect = { offsetX: 0, offsetY: 0, width: 400, height: 400 };
  const gridSize = 4;

  it("点击第一个单元格 (0,0) 中心 → 返回 [0, 0]", () => {
    // Cell (0,0) center: x = 50, y = 50
    const result = lutClickToCell(50, 50, rendered, gridSize);
    expect(result).toEqual([0, 0]);
  });

  it("点击最后一个单元格 (3,3) 中心 → 返回 [3, 3]", () => {
    // Cell (3,3) center: x = 350, y = 350
    const result = lutClickToCell(350, 350, rendered, gridSize);
    expect(result).toEqual([3, 3]);
  });

  it("点击左侧留白区域 → 返回 null", () => {
    const withOffset: RenderedImageRect = { offsetX: 100, offsetY: 0, width: 200, height: 400 };
    // Click at x=50, which is in the left letterbox (offsetX=100)
    const result = lutClickToCell(50, 200, withOffset, gridSize);
    expect(result).toBeNull();
  });

  it("点击底部留白区域 → 返回 null", () => {
    const withOffset: RenderedImageRect = { offsetX: 0, offsetY: 0, width: 400, height: 200 };
    // Click at y=300, which is below the rendered image (height=200)
    const result = lutClickToCell(200, 300, withOffset, gridSize);
    expect(result).toBeNull();
  });

  it("gridSize 为 0 → 返回 null", () => {
    const result = lutClickToCell(50, 50, rendered, 0);
    expect(result).toBeNull();
  });
});

// ========== getCellOverlayStyle ==========

describe("getCellOverlayStyle", () => {
  // 4x4 grid on a 400x400 rendered image with offset
  const rendered: RenderedImageRect = { offsetX: 50, offsetY: 50, width: 400, height: 400 };
  const gridSize = 4;
  const cellSize = 400 / 4; // 100

  it("单元格 (0,0) → 正确的 left、top、width、height", () => {
    const style = getCellOverlayStyle(0, 0, rendered, gridSize);
    expect(style).toEqual({
      left: 50,   // offsetX + 0 * 100
      top: 50,    // offsetY + 0 * 100
      width: cellSize,
      height: cellSize,
    });
  });

  it("单元格 (1,2) → 正确的位置偏移", () => {
    const style = getCellOverlayStyle(1, 2, rendered, gridSize);
    expect(style).toEqual({
      left: 50 + 2 * cellSize,   // offsetX + col * cellWidth = 250
      top: 50 + 1 * cellSize,    // offsetY + row * cellHeight = 150
      width: cellSize,
      height: cellSize,
    });
  });
});

// ========== sampleCellHexColor ==========

describe("sampleCellHexColor", () => {
  function makeFakeImage(
    naturalWidth: number,
    naturalHeight: number,
    pixelAt: (x: number, y: number) => [number, number, number],
  ): HTMLImageElement {
    // Stub getContext on a real canvas so drawImage + getImageData work in jsdom.
    const img = { naturalWidth, naturalHeight } as unknown as HTMLImageElement;
    const originalCreate = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      if (tag !== "canvas") return originalCreate(tag);
      const canvas = originalCreate("canvas");
      canvas.getContext = (() => ({
        drawImage: () => {},
        getImageData: (x: number, y: number) => {
          const [r, g, b] = pixelAt(x, y);
          return { data: new Uint8ClampedArray([r, g, b, 255]) };
        },
      })) as unknown as HTMLCanvasElement["getContext"];
      return canvas;
    });
    return img;
  }

  it("返回被点击色块中心像素的十六进制颜色", () => {
    // 4×4 grid 的图像，每个 cell 中心 (x=(col+0.5)*W/4) 的像素设置成不同颜色
    const img = makeFakeImage(40, 40, (x, y) => {
      // cell (1, 2) 中心 = (25, 15)
      if (x === 25 && y === 15) return [255, 128, 0];
      return [0, 0, 0];
    });
    const hex = sampleCellHexColor(img, 1, 2, 4);
    expect(hex).toBe("#ff8000");
    vi.restoreAllMocks();
  });

  it("gridSize 非法时返回 null", () => {
    const img = { naturalWidth: 40, naturalHeight: 40 } as HTMLImageElement;
    expect(sampleCellHexColor(img, 0, 0, 0)).toBeNull();
    expect(sampleCellHexColor(img, 0, 0, -1)).toBeNull();
  });

  it("图像尚未加载 (naturalWidth=0) 时返回 null", () => {
    const img = { naturalWidth: 0, naturalHeight: 0 } as HTMLImageElement;
    expect(sampleCellHexColor(img, 0, 0, 32)).toBeNull();
  });
});
