import { describe, expect, it } from "vitest";
import * as THREE from "three";
import {
  computeOutlinePreviewHeight,
  extractHexFromMeshName,
  isLayeredMaterialColorMeshName,
  resolvePreviewColorLayerHeightMm,
  shouldApplyColorRemapToMeshName,
} from "../components/InteractiveModelViewer";
import { materializePositionAttributeForGeometryBake } from "../utils/threeQuantizedGeometry";

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

  it("extracts the original hex from chunked V2 color mesh names", () => {
    expect(extractHexFromMeshName("color_ff0000_chunk001")).toBe("ff0000");
    expect(extractHexFromMeshName("color_00ff00_1")).toBe("00ff00");
  });
});

describe("computeOutlinePreviewHeight", () => {
  it("uses live single-sided spacer thickness for fridge-magnet outline preview", () => {
    expect(
      computeOutlinePreviewHeight(3.44, "Single-sided", false, {}, 12),
    ).toBeCloseTo(3.84, 5);
  });

  it("keeps double-sided color layers in the outline preview height", () => {
    expect(
      computeOutlinePreviewHeight(1.2, "Double-sided", false, {}, 12),
    ).toBeCloseTo(2.0, 5);
  });

  it("uses the tallest relief color height when relief preview is enabled", () => {
    expect(
      computeOutlinePreviewHeight(1.2, "Single-sided", true, { ff0000: 2.5, "00ff00": 1.5 }, 12),
    ).toBeCloseTo(3.7, 5);
  });

  it("uses the active material layer stack height for single-sided preview", () => {
    expect(
      computeOutlinePreviewHeight(1.2, "Single-sided", false, {}, 12, 0.8),
    ).toBeCloseTo(2.0, 5);
  });

  it("keeps double-sided dynamic material layer stacks in the outline height", () => {
    expect(
      computeOutlinePreviewHeight(1.2, "Double-sided", false, {}, 12, 0.8),
    ).toBeCloseTo(2.8, 5);
  });
});

describe("resolvePreviewColorLayerHeightMm", () => {
  it("falls back to the legacy five-layer height for invalid values", () => {
    expect(resolvePreviewColorLayerHeightMm(undefined)).toBeCloseTo(0.4, 5);
    expect(resolvePreviewColorLayerHeightMm(0)).toBeCloseTo(0.4, 5);
  });

  it("returns the caller-provided positive material stack height", () => {
    expect(resolvePreviewColorLayerHeightMm(0.8)).toBeCloseTo(0.8, 5);
  });
});

describe("isLayeredMaterialColorMeshName", () => {
  it("recognizes material archive layer mesh names", () => {
    expect(isLayeredMaterialColorMeshName("color_ff0000_m000_l009")).toBe(true);
  });

  it("does not classify legacy color meshes as material archive layer meshes", () => {
    expect(isLayeredMaterialColorMeshName("color_ff0000")).toBe(false);
    expect(isLayeredMaterialColorMeshName("color_ff0000_chunk001")).toBe(false);
  });
});

describe("shouldApplyColorRemapToMeshName", () => {
  it("keeps legacy color mesh optimistic remaps enabled", () => {
    expect(shouldApplyColorRemapToMeshName("color_ff0000")).toBe(true);
  });

  it("does not apply matched-hex remaps to physical material layer meshes", () => {
    expect(shouldApplyColorRemapToMeshName("color_ff0000_m000_l009")).toBe(false);
  });
});

describe("materializePositionAttributeForGeometryBake", () => {
  it("converts normalized quantized positions to Float32 before matrix baking", () => {
    const geometry = new THREE.BufferGeometry();
    const positions = new Uint16Array([
      0, 0, 0,
      65535, 32768, 65535,
    ]);
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3, true));

    materializePositionAttributeForGeometryBake(geometry);
    geometry.applyMatrix4(new THREE.Matrix4().makeScale(80, 60, 2));

    const posAttr = geometry.getAttribute("position") as THREE.BufferAttribute;
    expect(posAttr.array).toBeInstanceOf(Float32Array);
    expect(posAttr.normalized).toBe(false);
    expect(posAttr.getX(0)).toBeCloseTo(0, 5);
    expect(posAttr.getY(0)).toBeCloseTo(0, 5);
    expect(posAttr.getZ(0)).toBeCloseTo(0, 5);
    expect(posAttr.getX(1)).toBeCloseTo(80, 5);
    expect(posAttr.getY(1)).toBeCloseTo(60 * (32768 / 65535), 5);
    expect(posAttr.getZ(1)).toBeCloseTo(2, 5);
  });

  it("preserves quantized GLB node translation and scale during matrix baking", () => {
    const geometry = new THREE.BufferGeometry();
    const positions = new Uint16Array([
      0, 0, 0,
      65535, 65535, 65535,
    ]);
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3, true));
    const mesh = new THREE.Mesh(geometry);
    mesh.position.set(-40, -30, 1.2);
    mesh.scale.set(80, 60, 0.4);
    mesh.updateWorldMatrix(true, false);

    materializePositionAttributeForGeometryBake(geometry);
    geometry.applyMatrix4(mesh.matrixWorld);

    const posAttr = geometry.getAttribute("position") as THREE.BufferAttribute;
    expect(posAttr.array).toBeInstanceOf(Float32Array);
    expect(posAttr.normalized).toBe(false);
    expect(posAttr.getX(0)).toBeCloseTo(-40, 5);
    expect(posAttr.getY(0)).toBeCloseTo(-30, 5);
    expect(posAttr.getZ(0)).toBeCloseTo(1.2, 5);
    expect(posAttr.getX(1)).toBeCloseTo(40, 5);
    expect(posAttr.getY(1)).toBeCloseTo(30, 5);
    expect(posAttr.getZ(1)).toBeCloseTo(1.6, 5);
  });

  it("leaves ordinary Float32 positions unchanged", () => {
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array([0, 0, 0, 2, 3, 4]);
    const attr = new THREE.BufferAttribute(positions, 3);
    geometry.setAttribute("position", attr);

    materializePositionAttributeForGeometryBake(geometry);

    expect(geometry.getAttribute("position")).toBe(attr);
  });
});
