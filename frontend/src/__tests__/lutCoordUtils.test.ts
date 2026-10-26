import { describe, expect, it } from "vitest";
import { getObjectFitRect } from "../utils/lutCoordUtils";

describe("getObjectFitRect", () => {
  it("正方形图像在正方形容器中无偏移并填满容器", () => {
    expect(getObjectFitRect(512, 512, 512, 512)).toEqual({
      offsetX: 0,
      offsetY: 0,
      width: 512,
      height: 512,
    });
  });

  it("宽图像在正方形容器中保留上下留白", () => {
    expect(getObjectFitRect(1000, 500, 400, 400)).toEqual({
      offsetX: 0,
      offsetY: 100,
      width: 400,
      height: 200,
    });
  });

  it("高图像在正方形容器中保留左右留白", () => {
    expect(getObjectFitRect(500, 1000, 400, 400)).toEqual({
      offsetX: 100,
      offsetY: 0,
      width: 200,
      height: 400,
    });
  });

  it("任一输入尺寸无效时返回零尺寸区域", () => {
    expect(getObjectFitRect(0, 500, 400, 400)).toEqual({
      offsetX: 0,
      offsetY: 0,
      width: 0,
      height: 0,
    });
    expect(getObjectFitRect(512, 512, 400, 0)).toEqual({
      offsetX: 0,
      offsetY: 0,
      width: 0,
      height: 0,
    });
  });
});
