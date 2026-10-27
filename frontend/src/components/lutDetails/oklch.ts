export interface OklchColor {
  l: number;
  c: number;
  h: number;
}

interface OklabColor {
  l: number;
  a: number;
  b: number;
}

function srgbToLinear(channel: number): number {
  const normalized = channel / 255;
  if (normalized <= 0.04045) {
    return normalized / 12.92;
  }
  return ((normalized + 0.055) / 1.055) ** 2.4;
}

function linearToSrgb(channel: number): number {
  if (channel <= 0.0031308) {
    return 12.92 * channel;
  }
  return (1.055 * (channel ** (1 / 2.4))) - 0.055;
}

function rgbToOklab(r: number, g: number, b: number): OklabColor {
  const lr = srgbToLinear(r);
  const lg = srgbToLinear(g);
  const lb = srgbToLinear(b);

  const l = Math.cbrt((0.4122214708 * lr) + (0.5363325363 * lg) + (0.0514459929 * lb));
  const m = Math.cbrt((0.2119034982 * lr) + (0.6806995451 * lg) + (0.1073969566 * lb));
  const s = Math.cbrt((0.0883024619 * lr) + (0.2817188376 * lg) + (0.6299787005 * lb));

  return {
    l: (0.2104542553 * l) + (0.793617785 * m) - (0.0040720468 * s),
    a: (1.9779984951 * l) - (2.428592205 * m) + (0.4505937099 * s),
    b: (0.0259040371 * l) + (0.7827717662 * m) - (0.808675766 * s),
  };
}

function oklabToOklch(color: OklabColor): OklchColor {
  const c = Math.sqrt((color.a * color.a) + (color.b * color.b));
  const h = ((Math.atan2(color.b, color.a) * 180) / Math.PI + 360) % 360;
  return {
    l: color.l,
    c,
    h,
  };
}

function oklchToOklab(color: OklchColor): OklabColor {
  const radians = (color.h * Math.PI) / 180;
  return {
    l: color.l,
    a: color.c * Math.cos(radians),
    b: color.c * Math.sin(radians),
  };
}

function oklabToLinearRgb(color: OklabColor): { r: number; g: number; b: number } {
  const l = color.l + (0.3963377774 * color.a) + (0.2158037573 * color.b);
  const m = color.l - (0.1055613458 * color.a) - (0.0638541728 * color.b);
  const s = color.l - (0.0894841775 * color.a) - (1.291485548 * color.b);

  const l3 = l ** 3;
  const m3 = m ** 3;
  const s3 = s ** 3;

  return {
    r: (4.0767416621 * l3) - (3.3077115913 * m3) + (0.2309699292 * s3),
    g: (-1.2684380046 * l3) + (2.6097574011 * m3) - (0.3413193965 * s3),
    b: (-0.0041960863 * l3) - (0.7034186147 * m3) + (1.707614701 * s3),
  };
}

export function rgbToOklch(r: number, g: number, b: number): OklchColor {
  return oklabToOklch(rgbToOklab(r, g, b));
}

export function isOklchInSrgbGamut(color: OklchColor): boolean {
  const rgb = oklabToLinearRgb(oklchToOklab(color));
  return rgb.r >= 0 && rgb.r <= 1
    && rgb.g >= 0 && rgb.g <= 1
    && rgb.b >= 0 && rgb.b <= 1;
}

export function maxOklchChromaForHueLightness(
  hue: number,
  lightness: number,
  upperBound: number,
): number {
  let low = 0;
  let high = upperBound;
  for (let iteration = 0; iteration < 9; iteration += 1) {
    const mid = (low + high) / 2;
    if (isOklchInSrgbGamut({ l: lightness, c: mid, h: hue })) {
      low = mid;
    } else {
      high = mid;
    }
  }
  return low;
}

export function oklchToHexClamped(color: OklchColor): string {
  const linear = oklabToLinearRgb(oklchToOklab(color));
  const toChannel = (value: number) => {
    const srgb = linearToSrgb(Math.min(1, Math.max(0, value)));
    return Math.round(Math.min(255, Math.max(0, srgb * 255)));
  };
  return `#${toChannel(linear.r).toString(16).padStart(2, "0")}${toChannel(linear.g).toString(16).padStart(2, "0")}${toChannel(linear.b).toString(16).padStart(2, "0")}`;
}
