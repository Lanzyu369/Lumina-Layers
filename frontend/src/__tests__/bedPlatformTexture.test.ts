import { describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import {
  computeCenteredGridLinePositions,
  computeBedTextureLayout,
  mapBedUvY,
} from "../components/bedPlatformTexture";
import * as bedPlatformTextureModule from "../components/bedPlatformTexture";
import * as bedPlatformGeometryModule from "../components/bedPlatformGeometry";
import * as themeConfigModule from "../components/themeConfig";
import type { ThemeColors } from "../components/themeConfig";

const { THEME_CONFIG } = themeConfigModule;

type BedSurfaceColors = Pick<
  ThemeColors,
  | "bedBase"
  | "bedInner"
  | "bedFineGrid"
  | "bedBoldGrid"
  | "bedBorder"
  | "bedBrand"
>;

type BedColorResolver = (
  theme: "light" | "dark",
  printerId?: string | null,
  bedLabel?: string,
  buildPlateId?: string | null,
) => BedSurfaceColors & { bedAccent?: string };

function hexToRgb(hex: string): { red: number; green: number; blue: number } {
  return {
    red: Number.parseInt(hex.slice(1, 3), 16),
    green: Number.parseInt(hex.slice(3, 5), 16),
    blue: Number.parseInt(hex.slice(5, 7), 16),
  };
}

describe("virtual build plate texture", () => {
  it("uses a file-relative Lumina mark", () => {
    expect(bedPlatformTextureModule.LUMINA_BED_MARK_URL).toBe("./favicon.ico");
  });

  it("keeps the current renderable bed texture until a theme replacement is ready", async () => {
    const stageBedTextureReplacement = (
      bedPlatformTextureModule as unknown as {
        stageBedTextureReplacement?: (
          material: THREE.MeshStandardMaterial,
          request: {
            ready: Promise<THREE.Texture | null>;
            cancel: () => void;
          },
          fallbackColor: string,
        ) => () => void;
      }
    ).stageBedTextureReplacement;

    expect(stageBedTextureReplacement).toBeTypeOf("function");
    if (!stageBedTextureReplacement) return;

    const currentTexture = new THREE.Texture({ width: 1, height: 1 });
    currentTexture.needsUpdate = true;
    const nextTexture = new THREE.Texture({ width: 2, height: 2 });
    nextTexture.needsUpdate = true;
    const material = new THREE.MeshStandardMaterial({ map: currentTexture });
    const cancel = vi.fn();
    let resolveReady!: (texture: THREE.Texture | null) => void;
    const ready = new Promise<THREE.Texture | null>((resolve) => {
      resolveReady = resolve;
    });
    const currentDispose = vi.fn();
    currentTexture.addEventListener("dispose", currentDispose);

    const stop = stageBedTextureReplacement(
      material,
      { ready, cancel },
      THEME_CONFIG.dark.bedInner,
    );

    expect(material.map).toBe(currentTexture);
    expect(material.map?.version).toBeGreaterThan(0);
    expect(currentDispose).not.toHaveBeenCalled();

    resolveReady(nextTexture);
    await ready;
    await Promise.resolve();

    expect(material.map).toBe(nextTexture);
    expect(currentDispose).toHaveBeenCalledOnce();
    stop();
    expect(cancel).not.toHaveBeenCalled();

    nextTexture.dispose();
    material.dispose();
  });

  it("renders an H2D SVG texture at four times the legacy raster density", () => {
    const computeBedTextureRasterSize = (
      bedPlatformTextureModule as unknown as {
        computeBedTextureRasterSize?: (
          widthMm: number,
          heightMm: number,
        ) => {
          rasterWidthPx: number;
          rasterHeightPx: number;
          rasterScale: number;
        };
      }
    ).computeBedTextureRasterSize;

    expect(computeBedTextureRasterSize).toBeTypeOf("function");
    if (!computeBedTextureRasterSize) return;

    expect(computeBedTextureRasterSize(350, 320)).toEqual({
      rasterWidthPx: 2800,
      rasterHeightPx: 2560,
      rasterScale: 4,
    });
  });

  it("caps oversized SVG textures without stretching their aspect ratio", () => {
    const computeBedTextureRasterSize = (
      bedPlatformTextureModule as unknown as {
        computeBedTextureRasterSize?: (
          widthMm: number,
          heightMm: number,
        ) => {
          rasterWidthPx: number;
          rasterHeightPx: number;
          rasterScale: number;
        };
      }
    ).computeBedTextureRasterSize;

    expect(computeBedTextureRasterSize).toBeTypeOf("function");
    if (!computeBedTextureRasterSize) return;

    const raster = computeBedTextureRasterSize(1200, 800);

    expect(Math.max(raster.rasterWidthPx, raster.rasterHeightPx)).toBeLessThanOrEqual(
      4096,
    );
    expect(raster.rasterWidthPx / raster.rasterHeightPx).toBeCloseTo(1.5, 2);
    expect(raster.rasterScale).toBeLessThan(4);
  });

  it("builds the bed artwork as a precision SVG with an enlarged raster target", () => {
    const buildBedTextureSvg = (
      bedPlatformTextureModule as unknown as {
        buildBedTextureSvg?: (options: {
          widthMm: number;
          heightMm: number;
          colors: BedSurfaceColors;
          gridVisible: boolean;
          luminaMarkDataUrl: string | null;
          slicerLogoDataUrl: string | null;
          slicerLogoAspectRatio: number;
        }) => string;
      }
    ).buildBedTextureSvg;

    expect(buildBedTextureSvg).toBeTypeOf("function");
    if (!buildBedTextureSvg) return;

    const svg = buildBedTextureSvg({
      widthMm: 350,
      heightMm: 320,
      colors: {
        bedBase: THEME_CONFIG.light.bedBase,
        bedInner: THEME_CONFIG.light.bedInner,
        bedFineGrid: THEME_CONFIG.light.bedFineGrid,
        bedBoldGrid: THEME_CONFIG.light.bedBoldGrid,
        bedBorder: THEME_CONFIG.light.bedBorder,
        bedBrand: THEME_CONFIG.light.bedBrand,
      },
      gridVisible: true,
      luminaMarkDataUrl: "data:image/png;base64,lumina",
      slicerLogoDataUrl: "data:image/png;base64,slicer",
      slicerLogoAspectRatio: 2,
    });

    expect(svg).toContain('<svg xmlns="http://www.w3.org/2000/svg"');
    expect(svg).toContain('width="2800"');
    expect(svg).toContain('height="2560"');
    expect(svg).toContain('viewBox="0 0 700 640"');
    expect(svg).toContain('shape-rendering="geometricPrecision"');
    expect(svg).toContain('stroke-dasharray="2 8"');
    expect(svg).toContain('stroke-linecap="round"');
    expect(svg.match(/stroke-dashoffset="6"/g)).toHaveLength(2);
    expect(svg).toContain("<line ");
    expect(svg).toContain(">350 × 320 mm</text>");
    expect(svg).toContain('href="data:image/png;base64,lumina"');
    expect(svg).toContain('href="data:image/png;base64,slicer"');
  });

  it("keeps the printable grid within 5 mm of every plate edge", () => {
    const layout = computeBedTextureLayout(256, 256);

    expect(layout.gridInsetMm).toBe(5);
    expect(layout.gridBoundsPx).toEqual({
      left: 10,
      top: 10,
      right: 502,
      bottom: 502,
    });
    expect(
      (layout.gridBoundsPx.right - layout.gridBoundsPx.left) /
        (256 * layout.pixelsPerMm),
    ).toBeGreaterThan(0.95);
  });

  it.each([
    [350, 320],
    [426, 420],
    [256, 256],
  ])(
    "keeps every %i × %i mm fine-grid junction at the center of a dash gap",
    (widthMm, heightMm) => {
      const layout = computeBedTextureLayout(widthMm, heightMm) as ReturnType<
        typeof computeBedTextureLayout
      > & {
        fineGridDashOffsetPx?: {
          horizontal: number;
          vertical: number;
        };
      };
      const [dashPx, gapPx] = layout.fineGridDashPx;
      const dashPeriodPx = dashPx + gapPx;
      const fineGridStepPx = 10 * layout.pixelsPerMm;
      const clearJunctionPhasePx = dashPx + gapPx / 2;

      expect(fineGridStepPx % dashPeriodPx).toBe(0);
      expect(layout.fineGridDashOffsetPx).toBeDefined();
      if (!layout.fineGridDashOffsetPx) return;

      const normalizePhase = (value: number) =>
        ((value % dashPeriodPx) + dashPeriodPx) % dashPeriodPx;
      const verticalGridLines = computeCenteredGridLinePositions(
        widthMm,
        layout.gridInsetMm,
        10,
        layout.pixelsPerMm,
      );
      const horizontalGridLines = computeCenteredGridLinePositions(
        heightMm,
        layout.gridInsetMm,
        10,
        layout.pixelsPerMm,
      );

      for (const xPx of verticalGridLines) {
        expect(
          normalizePhase(
            xPx -
              layout.gridBoundsPx.left +
              layout.fineGridDashOffsetPx.horizontal,
          ),
        ).toBe(clearJunctionPhasePx);
      }
      for (const yPx of horizontalGridLines) {
        expect(
          normalizePhase(
            yPx -
              layout.gridBoundsPx.top +
              layout.fineGridDashOffsetPx.vertical,
          ),
        ).toBe(clearJunctionPhasePx);
      }
    },
  );

  it("keeps the inset surface corners concentric with the outer plate", () => {
    const layout = computeBedTextureLayout(180, 180);

    expect(layout.surface).toEqual({
      insetPx: 4,
      outerRadiusPx: 16,
      innerRadiusPx: 12,
      borderWidthPx: 2,
    });
    expect(layout.surface.outerRadiusPx - layout.surface.innerRadiusPx).toBe(
      layout.surface.insetPx,
    );
  });

  it("centers both 10 mm and 50 mm lines symmetrically on any bed size", () => {
    const fineLines = computeCenteredGridLinePositions(180, 5, 10, 2);
    const boldLines = computeCenteredGridLinePositions(180, 5, 50, 2);

    expect(fineLines).toEqual([
      20, 40, 60, 80, 100, 120, 140, 160, 180,
      200, 220, 240, 260, 280, 300, 320, 340,
    ]);
    expect(boldLines).toEqual([80, 180, 280]);
    expect(fineLines.map((position, index) =>
      position + fineLines.at(-(index + 1))!,
    )).toEqual(Array(fineLines.length).fill(360));
  });

  it("aligns the brand wordmark and dimensions in one inset footer", () => {
    const layout = computeBedTextureLayout(256, 256);

    expect(layout.branding).toMatchObject({
      wordmark: "lumina",
      dimensionLabel: "256 × 256 mm",
    });
    expect(layout.branding.baselinePx).toBe(layout.branding.dimensionBaselinePx);
    expect(layout.branding.watermarkYpx).toBe(layout.branding.slicerLogoYpx);
    expect(layout.branding.baselinePx).toBeLessThan(512 - 4);
    expect(layout.branding.fontSizePx).toBeGreaterThanOrEqual(10);
  });

  it("keeps the slicer brand mark small and tucked into a corner", () => {
    const layout = computeBedTextureLayout(256, 256);

    expect(layout.branding.slicerLogoSizePx).toBeLessThanOrEqual(24);
    expect(layout.branding.slicerLogoXpx).toBeGreaterThan(512 * 0.8);
    expect(layout.branding.slicerLogoYpx).toBeGreaterThan(512 * 0.8);
    expect(layout.branding).not.toHaveProperty("accentRailWidthPx");
  });

  it.each([
    [180, 180],
    [256, 256],
    [426, 420],
  ])(
    "keeps corner branding at least 12 mm inside a %i × %i mm plate",
    (widthMm, heightMm) => {
      const layout = computeBedTextureLayout(widthMm, heightMm);
      const textureWidthPx = widthMm * layout.pixelsPerMm;
      const textureHeightPx = heightMm * layout.pixelsPerMm;
      const safeInsetPx = 12 * layout.pixelsPerMm;

      expect(layout.branding.slicerLogoXpx).toBeGreaterThanOrEqual(
        safeInsetPx,
      );
      expect(
        textureHeightPx -
          (layout.branding.slicerLogoYpx +
            layout.branding.slicerLogoSizePx),
      ).toBeGreaterThanOrEqual(safeInsetPx);
      expect(
        textureWidthPx - layout.branding.dimensionRightPx,
      ).toBeGreaterThanOrEqual(safeInsetPx);
      expect(
        textureHeightPx - layout.branding.dimensionBaselinePx,
      ).toBeGreaterThanOrEqual(safeInsetPx);
    },
  );

  it.each([
    [180, 180],
    [256, 256],
    [426, 420],
  ])(
    "keeps corner branding above a 24 mm irregular-bed cutout on a %i × %i mm plate",
    (widthMm, heightMm) => {
      const layout = computeBedTextureLayout(widthMm, heightMm);
      const textureHeightPx = heightMm * layout.pixelsPerMm;
      const cutoutClearancePx = 24 * layout.pixelsPerMm;

      expect(
        textureHeightPx -
          (layout.branding.slicerLogoYpx +
            layout.branding.slicerLogoSizePx),
      ).toBeGreaterThanOrEqual(cutoutClearancePx);
      expect(
        textureHeightPx - layout.branding.dimensionBaselinePx,
      ).toBeGreaterThanOrEqual(cutoutClearancePx);
    },
  );

  it("keeps canvas artwork upright with the branded rim facing the viewer", () => {
    expect(mapBedUvY(-128, 256)).toBe(0);
    expect(mapBedUvY(128, 256)).toBe(1);
  });

  it("provides a dedicated low-contrast brand color in both themes", () => {
    expect(THEME_CONFIG.light.bedBrand).toMatch(/^#[0-9a-f]{6}$/i);
    expect(THEME_CONFIG.dark.bedBrand).toMatch(/^#[0-9a-f]{6}$/i);
    expect(THEME_CONFIG.light.bedBrand).not.toBe(THEME_CONFIG.dark.bedBrand);
  });

  it("mutes the official slicer logo by opacity without recoloring it", () => {
    const svg = bedPlatformTextureModule.buildBedTextureSvg({
      widthMm: 256,
      heightMm: 256,
      colors: THEME_CONFIG.light,
      gridVisible: true,
      luminaMarkDataUrl: null,
      slicerLogoDataUrl: "data:image/png;base64,slicer",
      slicerLogoAspectRatio: 1,
    });
    const slicerLogoTag = svg.match(
      /<image href="data:image\/png;base64,slicer"[^>]*>/,
    )?.[0];

    expect(slicerLogoTag).toContain('opacity="0.55"');
    expect(slicerLogoTag).not.toContain("filter:");
  });

  it("uses neutral cool surfaces instead of a champagne light plate", () => {
    const lightInner = hexToRgb(THEME_CONFIG.light.bedInner);
    const darkInner = hexToRgb(THEME_CONFIG.dark.bedInner);

    expect(lightInner.blue).toBeGreaterThanOrEqual(lightInner.red);
    expect(
      Math.max(lightInner.red, lightInner.green, lightInner.blue) -
        Math.min(lightInner.red, lightInner.green, lightInner.blue),
    ).toBeLessThanOrEqual(12);
    expect(darkInner.blue).toBeGreaterThan(darkInner.red);
  });

  it("resolves distinct low-saturation palettes for printer bed families", () => {
    const resolveBedPlatformColors = (
      themeConfigModule as unknown as {
        resolveBedPlatformColors?: BedColorResolver;
      }
    ).resolveBedPlatformColors;

    expect(resolveBedPlatformColors).toBeTypeOf("function");
    if (!resolveBedPlatformColors) return;

    const bambuA = resolveBedPlatformColors(
      "light",
      "bambu-a1-mini",
      "Bambu Lab A1 mini",
    );
    const bambuP = resolveBedPlatformColors(
      "light",
      "bambu-p1s",
      "Bambu Lab P1S",
    );
    const anycubic = resolveBedPlatformColors(
      "light",
      "anycubic-kobra-s1",
      "Anycubic Kobra S1",
    );
    const generic = resolveBedPlatformColors("light", null, "256×256 mm");

    expect(bambuA).not.toEqual(bambuP);
    expect(bambuA).not.toEqual(anycubic);
    expect(anycubic).not.toEqual(generic);
    expect(
      resolveBedPlatformColors("light", null, "Bambu Lab A1 mini"),
    ).toEqual(bambuA);
    for (const palette of [bambuA, bambuP, anycubic, generic]) {
      expect(Object.values(palette)).toEqual(
        expect.arrayContaining([
          expect.stringMatching(/^#[0-9a-f]{6}$/i),
        ]),
      );
    }
  });

  it("gives every supported build plate family its own restrained palette", () => {
    const resolveBedPlatformColors = (
      themeConfigModule as unknown as {
        resolveBedPlatformColors?: BedColorResolver;
      }
    ).resolveBedPlatformColors;

    expect(resolveBedPlatformColors).toBeTypeOf("function");
    if (!resolveBedPlatformColors) return;

    const plateIds = [
      "smooth-high-temp-plate",
      "cool-plate",
      "engineering-plate",
      "textured-pei-plate",
      "textured-cool-plate",
      "supertack-plate",
    ];
    const palettes = plateIds.map((plateId) =>
      resolveBedPlatformColors(
        "light",
        "bambu-a1-mini",
        "Bambu Lab A1 mini",
        plateId,
      ),
    );

    expect(new Set(palettes.map((palette) => palette.bedInner)).size).toBe(
      plateIds.length,
    );
    expect(hexToRgb(palettes[1].bedInner).blue).toBeGreaterThan(
      hexToRgb(palettes[1].bedInner).red,
    );
    expect(hexToRgb(palettes[2].bedBoldGrid).red).toBeGreaterThan(
      hexToRgb(palettes[2].bedBoldGrid).blue,
    );
    expect(hexToRgb(palettes[5].bedInner).green).toBeGreaterThan(
      hexToRgb(palettes[5].bedInner).red,
    );
  });

  it("keeps the surface material-led without a loud machine-color rail", () => {
    const resolveBedPlatformColors = (
      themeConfigModule as unknown as {
        resolveBedPlatformColors?: BedColorResolver;
      }
    ).resolveBedPlatformColors;

    expect(resolveBedPlatformColors).toBeTypeOf("function");
    if (!resolveBedPlatformColors) return;

    const bambu = resolveBedPlatformColors(
      "light",
      "bambu-a1-mini",
      "Bambu Lab A1 mini",
      "textured-pei-plate",
    );
    const anycubic = resolveBedPlatformColors(
      "light",
      "anycubic-kobra-s1",
      "Anycubic Kobra S1",
      "textured-pei-plate",
    );

    expect(bambu).not.toHaveProperty("bedAccent");
    expect(anycubic).not.toHaveProperty("bedAccent");
    expect(bambu).toEqual(anycubic);
  });

  it("prepares a native slicer bed model with visible thickness and centered UVs", () => {
    const prepareNativeBedGeometry = (
      bedPlatformGeometryModule as unknown as {
        prepareNativeBedGeometry?: (
          geometry: THREE.BufferGeometry,
          widthMm: number,
          heightMm: number,
        ) => THREE.BufferGeometry;
      }
    ).prepareNativeBedGeometry;

    expect(prepareNativeBedGeometry).toBeTypeOf("function");
    if (!prepareNativeBedGeometry) return;

    const geometry = prepareNativeBedGeometry(
      new THREE.BoxGeometry(184, 197, 0.6),
      180,
      180,
    );
    geometry.computeBoundingBox();
    const bounds = geometry.boundingBox!;

    expect(bounds.max.x + bounds.min.x).toBeCloseTo(0, 5);
    expect(bounds.max.y + bounds.min.y).toBeCloseTo(0, 5);
    expect(bounds.max.z).toBeCloseTo(0, 5);
    expect(bounds.max.z - bounds.min.z).toBeGreaterThanOrEqual(3.2);
    expect(geometry.getAttribute("uv")).toBeDefined();
    geometry.dispose();
  });

  it("parses desktop-proxied STL bytes without making a renderer HTTP request", async () => {
    const loadNativeBedGeometrySource = (
      bedPlatformGeometryModule as unknown as {
        loadNativeBedGeometrySource?: (options: {
          desktopModelReader?: (
            deviceProfileId: string,
          ) => Promise<ArrayBuffer | Uint8Array | null>;
          deviceProfileId: string;
          loader: {
            load: (...args: unknown[]) => void;
            parse: (bytes: ArrayBuffer) => THREE.BufferGeometry;
          };
          modelUrl: string;
        }) => Promise<THREE.BufferGeometry | null>;
      }
    ).loadNativeBedGeometrySource;

    expect(loadNativeBedGeometrySource).toBeTypeOf("function");
    if (!loadNativeBedGeometrySource) return;

    const parsedGeometry = new THREE.BoxGeometry(180, 180, 0.6);
    const desktopModelReader = vi.fn(async () =>
      new Uint8Array([1, 2, 3, 4]),
    );
    const loader = {
      load: vi.fn(),
      parse: vi.fn(() => parsedGeometry),
    };

    const result = await loadNativeBedGeometrySource({
      desktopModelReader,
      deviceProfileId: "OrcaSlicer:bbl:bambu-lab-h2d:0.4",
      loader,
      modelUrl:
        "http://127.0.0.1:8000/api/system/machine-registry/bed-model" +
        "?device_profile_id=OrcaSlicer%3Abbl%3Abambu-lab-h2d%3A0.4",
    });

    expect(result).toBe(parsedGeometry);
    expect(desktopModelReader).toHaveBeenCalledWith(
      "OrcaSlicer:bbl:bambu-lab-h2d:0.4",
    );
    expect(loader.parse).toHaveBeenCalledOnce();
    expect(loader.load).not.toHaveBeenCalled();
    parsedGeometry.dispose();
  });

  it("maps native-bed UVs in printable millimeters instead of stretching to the STL bounds", () => {
    const source = new THREE.BoxGeometry(184, 197, 0.6);
    const geometry = bedPlatformGeometryModule.prepareNativeBedGeometry(
      source,
      180,
      180,
    );
    const uv = geometry.getAttribute("uv");
    let minU = Number.POSITIVE_INFINITY;
    let maxU = Number.NEGATIVE_INFINITY;
    let minV = Number.POSITIVE_INFINITY;
    let maxV = Number.NEGATIVE_INFINITY;
    for (let index = 0; index < uv.count; index += 1) {
      minU = Math.min(minU, uv.getX(index));
      maxU = Math.max(maxU, uv.getX(index));
      minV = Math.min(minV, uv.getY(index));
      maxV = Math.max(maxV, uv.getY(index));
    }

    expect((maxU - minU) * 180).toBeCloseTo(184, 4);
    expect((maxV - minV) * 180).toBeCloseTo(197, 4);
    source.dispose();
    geometry.dispose();
  });

  it("keeps a centered printable origin when a native bed has a one-sided locator tab", () => {
    const source = new THREE.BoxGeometry(180, 190, 0.6);
    source.translate(0, 5, 0);

    const geometry = bedPlatformGeometryModule.prepareNativeBedGeometry(
      source,
      180,
      180,
    );
    geometry.computeBoundingBox();

    expect(geometry.boundingBox!.min.y).toBeCloseTo(-90, 4);
    expect(geometry.boundingBox!.max.y).toBeCloseTo(100, 4);
    source.dispose();
    geometry.dispose();
  });

  it("uses an extruded irregular fallback plate instead of a flat rounded rectangle", () => {
    const createFallbackBedGeometry = (
      bedPlatformGeometryModule as unknown as {
        createFallbackBedGeometry?: (
          widthMm: number,
          heightMm: number,
        ) => THREE.BufferGeometry;
      }
    ).createFallbackBedGeometry;

    expect(createFallbackBedGeometry).toBeTypeOf("function");
    if (!createFallbackBedGeometry) return;

    const geometry = createFallbackBedGeometry(180, 180);
    geometry.computeBoundingBox();
    const size = new THREE.Vector3();
    geometry.boundingBox!.getSize(size);

    expect(size.y).toBeGreaterThan(180);
    expect(size.z).toBeGreaterThanOrEqual(3.2);
    geometry.dispose();
  });

  it("frames an empty bed close enough and obliquely enough to reveal its side wall", () => {
    const computeBedPreviewCameraPose = (
      bedPlatformGeometryModule as unknown as {
        computeBedPreviewCameraPose?: (
          widthMm: number,
          heightMm: number,
          fovDeg: number,
        ) => {
          position: readonly [number, number, number];
          target: readonly [number, number, number];
        };
      }
    ).computeBedPreviewCameraPose;

    expect(computeBedPreviewCameraPose).toBeTypeOf("function");
    if (!computeBedPreviewCameraPose) return;

    const pose = computeBedPreviewCameraPose(180, 180, 45);
    expect(pose.position[2]).toBeGreaterThan(330);
    expect(pose.position[2]).toBeLessThan(430);
    expect(Math.abs(pose.position[1])).toBeGreaterThan(
      pose.position[2] * 0.35,
    );
    expect(pose.target).toEqual([0, 0, 0]);
  });
});
