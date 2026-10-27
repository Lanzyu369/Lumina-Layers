export interface ReferenceSliceColorSample {
  rgb: readonly [number, number, number];
  alpha: number;
  inGamut: boolean;
}

const RGB_GAMUT_EPSILON = 1e-6;

function labToXyz(l: number, a: number, b: number): { x: number; y: number; z: number } {
  const fy = (l + 16) / 116;
  const fx = fy + (a / 500);
  const fz = fy - (b / 200);
  const epsilon = 0.008856;
  const kappa = 903.3;
  const invert = (value: number) => {
    const cube = value ** 3;
    return cube > epsilon ? cube : ((116 * value) - 16) / kappa;
  };

  return {
    x: invert(fx) * 0.95047,
    y: invert(fy),
    z: invert(fz) * 1.08883,
  };
}

function xyzToLinearRgb(x: number, y: number, z: number): { r: number; g: number; b: number } {
  return {
    r: (x * 3.2404542) + (y * -1.5371385) + (z * -0.4985314),
    g: (x * -0.969266) + (y * 1.8760108) + (z * 0.041556),
    b: (x * 0.0556434) + (y * -0.2040259) + (z * 1.0572252),
  };
}

function linearToSrgb(channel: number): number {
  if (channel <= 0.0031308) {
    return 12.92 * channel;
  }
  return (1.055 * (channel ** (1 / 2.4))) - 0.055;
}

function clampUnit(channel: number): number {
  return Math.min(1, Math.max(0, channel));
}

function encodeChannel(channel: number): number {
  return Math.round(clampUnit(linearToSrgb(clampUnit(channel))) * 255);
}

export function sampleReferenceSliceColor(
  lightness: number,
  a: number,
  b: number,
): ReferenceSliceColorSample {
  const xyz = labToXyz(lightness, a, b);
  const linear = xyzToLinearRgb(xyz.x, xyz.y, xyz.z);
  const inGamut = linear.r >= -RGB_GAMUT_EPSILON && linear.r <= 1 + RGB_GAMUT_EPSILON
    && linear.g >= -RGB_GAMUT_EPSILON && linear.g <= 1 + RGB_GAMUT_EPSILON
    && linear.b >= -RGB_GAMUT_EPSILON && linear.b <= 1 + RGB_GAMUT_EPSILON;

  return {
    rgb: [
      encodeChannel(linear.r),
      encodeChannel(linear.g),
      encodeChannel(linear.b),
    ] as const,
    alpha: inGamut ? 255 : 0,
    inGamut,
  };
}
