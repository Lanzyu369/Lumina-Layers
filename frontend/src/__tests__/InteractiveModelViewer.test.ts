import { describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import {
  applyPreviewMeshDisplayColor,
  buildBatchedPaletteUvEncoding,
  buildBatchedReliefPositionArray,
  computeOutlinePreviewHeight,
  configureBatchedPaletteTexture,
  extractHexFromMeshName,
  isBatchedMaterialAppearanceMeshName,
  isBatchedMaterialPhysicalMeshName,
  isLayeredMaterialColorMeshName,
  resolveLayeredMaterialPreviewTransform,
  resolvePreviewColorLayerHeightMm,
  shouldMirrorPreview,
  shouldApplyColorRemapToMeshName,
} from "../components/InteractiveModelViewer";
import { materializePositionAttributeForGeometryBake } from "../utils/threeQuantizedGeometry";
import { disposeMaterial } from "../utils/threeDisposal";

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

  it("does not force a short relief region back to the flat recipe-stack height", () => {
    expect(
      computeOutlinePreviewHeight(1.2, "Single-sided", true, { ff0000: 0.1 }, 12, 0.4),
    ).toBeCloseTo(1.3, 5);
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

  it("recognizes the bounded batched material mesh contract", () => {
    expect(
      isBatchedMaterialAppearanceMeshName(
        "color_layered_appearance_l000",
      ),
    ).toBe(true);
    expect(
      isBatchedMaterialPhysicalMeshName("color_layered_physical_l009"),
    ).toBe(true);
    expect(
      isLayeredMaterialColorMeshName("color_layered_appearance_l000"),
    ).toBe(true);
  });
});

describe("batched material appearance relief", () => {
  it("keeps two source heights distinct after both regions reach one display colour", () => {
    const original = new Float32Array([
      0, 0, 0.32,
      0, 0, 0.4,
      1, 0, 0.32,
      1, 0, 0.4,
    ]);
    const deformed = buildBatchedReliefPositionArray({
      originalPositions: original,
      heightSegments: [
        { vertex_start: 0, vertex_count: 2, height_key: "bee6f8", display_hex: "f46429" },
        { vertex_start: 2, vertex_count: 2, height_key: "112233", display_hex: "f46429" },
      ],
      nativeMinZ: 0.32,
      nativeMaxZ: 0.4,
      colorHeightMap: { bee6f8: 0.48, "112233": 2.0 },
      fallbackHeightMm: 0.4,
    });

    expect(Array.from(deformed.slice(0, 5))).toEqual([0, 0, 0, 0, 0]);
    expect(deformed[5]).toBeCloseTo(0.48, 5);
    expect(Array.from(deformed.slice(6, 11))).toEqual([1, 0, 0, 1, 0]);
    expect(deformed[11]).toBeCloseTo(2, 5);
  });

  it("keeps changed and unchanged pixels at one source height for a local replace", () => {
    const original = new Float32Array([
      0, 0, 0.32,
      0, 0, 0.4,
      1, 0, 0.32,
      1, 0, 0.4,
    ]);
    const deformed = buildBatchedReliefPositionArray({
      originalPositions: original,
      heightSegments: [
        { vertex_start: 0, vertex_count: 2, height_key: "bee6f8", display_hex: "f46429" },
        { vertex_start: 2, vertex_count: 2, height_key: "bee6f8", display_hex: "bee6f8" },
      ],
      nativeMinZ: 0.32,
      nativeMaxZ: 0.4,
      colorHeightMap: { bee6f8: 0.48 },
      fallbackHeightMm: 0.4,
    });

    expect(deformed[5]).toBeCloseTo(0.48, 5);
    expect(deformed[11]).toBeCloseTo(0.48, 5);
  });

  it("encodes exact palette indexes with one coverage per vertex", () => {
    const encoding = buildBatchedPaletteUvEncoding(4, [
      { vertex_start: 0, vertex_count: 2, display_hex: "d24854" },
      { vertex_start: 2, vertex_count: 2, display_hex: "bee6f8" },
    ]);

    expect(encoding.valid).toBe(true);
    expect(encoding.paletteHex).toEqual(["d24854", "bee6f8"]);
    expect(encoding.componentBits).toBe(8);
    expect(encoding.uvData).toBeInstanceOf(Uint8Array);
    const uv = encoding.uvData as Uint8Array;
    expect(Math.floor((uv[0] / 255) * 2)).toBe(0);
    expect(Math.floor((uv[4] / 255) * 2)).toBe(1);
  });

  it.each([
    { paletteSize: 128, componentBits: 8, componentMax: 0xff },
    { paletteSize: 129, componentBits: 16, componentMax: 0xffff },
  ])(
    "uses a lossless $componentBits-bit palette index at the $paletteSize-colour boundary",
    ({ paletteSize, componentBits, componentMax }) => {
      const segments = Array.from({ length: paletteSize }, (_, index) => ({
        vertex_start: index,
        vertex_count: 1,
        display_hex: index.toString(16).padStart(6, "0"),
      }));

      const encoding = buildBatchedPaletteUvEncoding(paletteSize, segments);

      expect(encoding.valid).toBe(true);
      expect(encoding.componentBits).toBe(componentBits);
      expect(encoding.uvData).toBeInstanceOf(
        componentBits === 8 ? Uint8Array : Uint16Array,
      );
      const uv = encoding.uvData!;
      const decodedIndexes = Array.from(
        { length: paletteSize },
        (_, vertexIndex) => Math.min(
          paletteSize - 1,
          Math.floor((uv[vertexIndex * 2] / componentMax) * paletteSize),
        ),
      );
      expect(decodedIndexes).toEqual(
        Array.from({ length: paletteSize }, (_, index) => index),
      );
      expect(decodedIndexes[0]).toBe(0);
      expect(decodedIndexes.at(-1)).toBe(paletteSize - 1);
    },
  );

  it("keeps the real-cache palette attribute below the former Float32 RGB budget", () => {
    const vertexCount = 484_416;
    const paletteSize = 48;
    const verticesPerColour = Math.floor(vertexCount / paletteSize);
    let vertexStart = 0;
    const segments = Array.from({ length: paletteSize }, (_, index) => {
      const vertexCountForSegment = index === paletteSize - 1
        ? vertexCount - vertexStart
        : verticesPerColour;
      const segment = {
        vertex_start: vertexStart,
        vertex_count: vertexCountForSegment,
        display_hex: (index * 5_302_423 % 0x1000000)
          .toString(16)
          .padStart(6, "0"),
      };
      vertexStart += vertexCountForSegment;
      return segment;
    });

    const encoding = buildBatchedPaletteUvEncoding(vertexCount, segments);

    expect(encoding.valid).toBe(true);
    expect(encoding.componentBits).toBe(8);
    expect(encoding.uvData?.byteLength).toBe(vertexCount * 2);
    expect(encoding.uvData!.byteLength + encoding.paletteHex.length * 4)
      .toBeLessThan(vertexCount * 3 * Float32Array.BYTES_PER_ELEMENT);
  });

  it("fails closed for overlapping, incomplete, or corrupt palette metadata", () => {
    expect(
      buildBatchedPaletteUvEncoding(4, [
        { vertex_start: 0, vertex_count: 3, display_hex: "d24854" },
        { vertex_start: 2, vertex_count: 2, display_hex: "bee6f8" },
      ]),
    ).toMatchObject({ valid: false, error: "overlapping_palette_segments" });
    expect(
      buildBatchedPaletteUvEncoding(4, [
        { vertex_start: 0, vertex_count: 2, display_hex: "not-a-hex" },
      ]),
    ).toMatchObject({ valid: false, error: "invalid_palette_segment" });
    expect(
      buildBatchedPaletteUvEncoding(4, [
        { vertex_start: 0, vertex_count: 2, display_hex: "d24854" },
      ]),
    ).toMatchObject({ valid: false, error: "incomplete_palette_segments" });
  });

  it("reconstructs an exact-sRGB disposable palette texture without vertex RGBA", () => {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(new Float32Array(12), 3),
    );
    geometry.setAttribute(
      "color",
      new THREE.Uint8BufferAttribute(new Uint8Array(16), 4, true),
    );
    const material = new THREE.MeshBasicMaterial({ vertexColors: true });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.name = "color_layered_appearance_l000";
    mesh.userData.height_segments = [
      { vertex_start: 0, vertex_count: 2, display_hex: "d24854" },
      { vertex_start: 2, vertex_count: 2, display_hex: "bee6f8" },
    ];

    expect(configureBatchedPaletteTexture(mesh)).toBe(true);

    expect(geometry.getAttribute("color")).toBeUndefined();
    expect(geometry.getAttribute("uv")).toBeInstanceOf(
      THREE.Uint8BufferAttribute,
    );
    expect(material.vertexColors).toBe(false);
    expect(material.map).toBeInstanceOf(THREE.DataTexture);
    expect(material.map?.colorSpace).toBe(THREE.SRGBColorSpace);
    const texture = material.map as THREE.DataTexture;
    const textureImage = texture.image as { data: Uint8Array };
    expect(Array.from(textureImage.data)).toEqual([
      210, 72, 84, 255,
      190, 230, 248, 255,
    ]);
    const disposeSpy = vi.spyOn(texture, "dispose");
    disposeMaterial(material);
    expect(disposeSpy).toHaveBeenCalledTimes(1);
  });

  it("replaces old palette resources on reload and has a deterministic white fallback", () => {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(new Float32Array(6), 3),
    );
    const material = new THREE.MeshBasicMaterial();
    const mesh = new THREE.Mesh(geometry, material);
    mesh.name = "color_layered_physical_l001";
    mesh.userData.material_segments = [
      { vertex_start: 0, vertex_count: 2, display_hex: "d24854" },
    ];
    expect(configureBatchedPaletteTexture(mesh)).toBe(true);
    const oldTexture = material.map!;
    const oldDisposeSpy = vi.spyOn(oldTexture, "dispose");

    mesh.userData.material_segments = [];
    expect(configureBatchedPaletteTexture(mesh)).toBe(false);

    expect(oldDisposeSpy).toHaveBeenCalledTimes(1);
    expect(material.map).toBeNull();
    expect(geometry.getAttribute("uv")).toBeUndefined();
    expect(geometry.userData.luminaPaletteError).toBe(
      "incomplete_palette_segments",
    );
    expect(material.color.getHexString(THREE.SRGBColorSpace)).toBe("ffffff");
  });
});

describe("resolveLayeredMaterialPreviewTransform", () => {
  const transformBounds = (
    nativeMinZ: number,
    nativeMaxZ: number,
    scaleZ: number,
    positionZ: number,
  ) => ({
    minZ: nativeMinZ * scaleZ + positionZ,
    maxZ: nativeMaxZ * scaleZ + positionZ,
  });

  it("keeps every physical layer at its native height outside relief mode", () => {
    expect(
      resolveLayeredMaterialPreviewTransform({
        meshName: "color_d24854_m009_l004",
        nativeMinZ: 0,
        nativeMaxZ: 0.08,
        spacerThick: 1.2,
        enableRelief: false,
        colorHeightMap: { d24854: 3 },
        colorLayerHeightMm: 0.4,
      }),
    ).toEqual({ visible: true, scaleZ: 1, positionZ: 1.2 });
  });

  it("hides internal physical slices in material-archive relief preview", () => {
    expect(
      resolveLayeredMaterialPreviewTransform({
        meshName: "color_fefefe_m001_l001",
        nativeMinZ: 0.24,
        nativeMaxZ: 0.32,
        spacerThick: 1.2,
        enableRelief: true,
        colorHeightMap: { fefefe: 3 },
        colorLayerHeightMm: 0.4,
      }),
    ).toEqual({ visible: false, scaleZ: 1, positionZ: 1.2 });
  });

  it("maps each composite top slice from the spacer to its requested relief height", () => {
    const transform = resolveLayeredMaterialPreviewTransform({
      meshName: "color_d24854_m009_l000",
      nativeMinZ: 0.32,
      nativeMaxZ: 0.4,
      spacerThick: 1.2,
      enableRelief: true,
      colorHeightMap: { d24854: 3 },
      colorLayerHeightMm: 0.4,
    });
    const transformed = transformBounds(
      0.32,
      0.4,
      transform.scaleZ,
      transform.positionZ,
    );

    expect(transform.visible).toBe(true);
    expect(transformed.minZ).toBeCloseTo(1.2, 5);
    expect(transformed.maxZ).toBeCloseTo(4.2, 5);
  });

  it("normalizes imported hash-prefixed uppercase relief colour keys", () => {
    const transform = resolveLayeredMaterialPreviewTransform({
      meshName: "color_d24854_m009_l000",
      nativeMinZ: 0.32,
      nativeMaxZ: 0.4,
      spacerThick: 1.2,
      enableRelief: true,
      colorHeightMap: { "#D24854": 2.2 },
      colorLayerHeightMm: 0.4,
    });
    const transformed = transformBounds(
      0.32,
      0.4,
      transform.scaleZ,
      transform.positionZ,
    );

    expect(transformed.minZ).toBeCloseTo(1.2, 5);
    expect(transformed.maxZ).toBeCloseTo(3.4, 5);
  });

  it("honours a relief-extra height smaller than the physical recipe stack", () => {
    const transform = resolveLayeredMaterialPreviewTransform({
      meshName: "color_d24854_m009_l000",
      nativeMinZ: 0.32,
      nativeMaxZ: 0.4,
      spacerThick: 1.2,
      enableRelief: true,
      colorHeightMap: { d24854: 0.1 },
      colorLayerHeightMm: 0.4,
    });
    const transformed = transformBounds(
      0.32,
      0.4,
      transform.scaleZ,
      transform.positionZ,
    );

    expect(transformed.minZ).toBeCloseTo(1.2, 5);
    expect(transformed.maxZ).toBeCloseTo(1.3, 5);
  });

  it("falls back to the active recipe-stack height while a relief map is empty", () => {
    const transform = resolveLayeredMaterialPreviewTransform({
      meshName: "color_d24854_m009_l000",
      nativeMinZ: 0.4,
      nativeMaxZ: 0.5,
      spacerThick: 1.2,
      enableRelief: true,
      colorHeightMap: {},
      colorLayerHeightMm: 0.5,
    });
    const transformed = transformBounds(
      0.4,
      0.5,
      transform.scaleZ,
      transform.positionZ,
    );

    expect(transformed.minZ).toBeCloseTo(1.2, 5);
    expect(transformed.maxZ).toBeCloseTo(1.7, 5);
  });

  it("restores a composite top slice to its native transform when relief is switched off", () => {
    const options = {
      meshName: "color_d24854_m009_l000",
      nativeMinZ: 0.32,
      nativeMaxZ: 0.4,
      spacerThick: 1.2,
      colorHeightMap: { d24854: 3 },
      colorLayerHeightMm: 0.4,
    };

    expect(
      resolveLayeredMaterialPreviewTransform({ ...options, enableRelief: true }),
    ).not.toEqual({ visible: true, scaleZ: 1, positionZ: 1.2 });
    expect(
      resolveLayeredMaterialPreviewTransform({ ...options, enableRelief: false }),
    ).toEqual({ visible: true, scaleZ: 1, positionZ: 1.2 });
  });

  it("fully restores an internal slice after relief is switched off", () => {
    const options = {
      meshName: "color_fefefe_m001_l001",
      nativeMinZ: 0.24,
      nativeMaxZ: 0.32,
      spacerThick: 1.2,
      colorHeightMap: { fefefe: 3 },
      colorLayerHeightMm: 0.4,
    };

    expect(
      resolveLayeredMaterialPreviewTransform({ ...options, enableRelief: true }),
    ).toEqual({ visible: false, scaleZ: 1, positionZ: 1.2 });
    expect(
      resolveLayeredMaterialPreviewTransform({ ...options, enableRelief: false }),
    ).toEqual({ visible: true, scaleZ: 1, positionZ: 1.2 });
  });
});

describe("shouldMirrorPreview", () => {
  it("mirrors flat double-sided models", () => {
    expect(shouldMirrorPreview("Double-sided", false)).toBe(true);
  });

  it("fails safe to single-sided rendering when an imported relief recipe says double-sided", () => {
    expect(shouldMirrorPreview("Double-sided", true)).toBe(false);
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

describe("applyPreviewMeshDisplayColor", () => {
  it("decodes a layered GLB material hex through the sRGB working space", () => {
    const material = new THREE.MeshStandardMaterial();

    applyPreviewMeshDisplayColor(
      material,
      "color_d24854_m009_l000",
      { d24854: "ffffff" },
    );

    expect(material.color.getHexString(THREE.SRGBColorSpace)).toBe("d24854");
    expect(material.vertexColors).toBe(false);
  });

  it("keeps optimistic remapping for legacy matched-colour meshes", () => {
    const material = new THREE.MeshBasicMaterial();

    applyPreviewMeshDisplayColor(
      material,
      "color_d24854",
      { d24854: "3188d6" },
    );

    expect(material.color.getHexString(THREE.SRGBColorSpace)).toBe("3188d6");
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
