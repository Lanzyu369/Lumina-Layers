export interface CoatingPreviewLayer {
  zMin: number;
  zMax: number;
}

function finiteNonNegative(value: number, fallback = 0): number {
  return Number.isFinite(value) ? Math.max(0, value) : fallback;
}

function roundMillimetres(value: number): number {
  return Math.round(value * 1_000_000) / 1_000_000;
}

function roundHalfToEven(value: number): number {
  const lower = Math.floor(value);
  const fraction = value - lower;
  if (Math.abs(fraction - 0.5) <= 1e-9) {
    return lower % 2 === 0 ? lower : lower + 1;
  }
  return Math.round(value);
}

/** Match Python's print-layer quantization for a positive coating request. */
export function quantizeCoatingHeightMm(
  coatingHeightMm: number,
  layerHeightMm: number,
): number {
  const requested = finiteNonNegative(coatingHeightMm);
  if (requested <= 0) return 0;
  const layerHeight = Number.isFinite(layerHeightMm) && layerHeightMm > 0
    ? layerHeightMm
    : 0.08;
  const layerCount = Math.max(1, roundHalfToEven(requested / layerHeight));
  return roundMillimetres(layerCount * layerHeight);
}

/** Map lightweight grayscale samples to the same physical height range as print. */
export function mapHeightmapGrayscaleToHeights(
  grayscale: Uint8Array,
  minimumHeightMm: number,
  maximumHeightMm: number,
): Float32Array {
  const minimum = finiteNonNegative(minimumHeightMm);
  const maximum = Math.max(minimum, finiteNonNegative(maximumHeightMm, minimum));
  const span = maximum - minimum;
  const heights = new Float32Array(grayscale.length);
  for (let index = 0; index < grayscale.length; index += 1) {
    heights[index] = minimum + ((grayscale[index] ?? 0) / 255) * span;
  }
  return heights;
}

/** Resolve the thin translucent layers shown around the lightweight model. */
export function computeCoatingPreviewLayers({
  coatingHeightMm,
  layerHeightMm,
  structureMode,
  enableRelief,
  spacerThickMm,
  visibleColorHeightMm,
}: {
  coatingHeightMm: number;
  layerHeightMm: number;
  structureMode: string;
  enableRelief: boolean;
  spacerThickMm: number;
  visibleColorHeightMm: number;
}): CoatingPreviewLayer[] {
  const coatingHeight = quantizeCoatingHeightMm(
    coatingHeightMm,
    layerHeightMm,
  );
  if (coatingHeight <= 0) return [];

  const colorHeight = finiteNonNegative(visibleColorHeightMm);
  const spacerHeight = finiteNonNegative(spacerThickMm);
  const doubleSided = structureMode.includes("Double") && !enableRelief;
  const lowerSurface = doubleSided ? -colorHeight : 0;
  const layers: CoatingPreviewLayer[] = [{
    zMin: roundMillimetres(lowerSurface - coatingHeight),
    zMax: roundMillimetres(lowerSurface),
  }];
  if (doubleSided) {
    const upperSurface = spacerHeight + colorHeight;
    layers.push({
      zMin: roundMillimetres(upperSurface),
      zMax: roundMillimetres(upperSurface + coatingHeight),
    });
  }
  return layers;
}
