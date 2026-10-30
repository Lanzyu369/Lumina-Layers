import { MARK_HEIGHT, MARK_WIDTH } from './splash-markSize.mjs';

/**
 * One water ripple that lays the next printed layer over the previous one, spreading from the
 * mark's bottom-left corner. The surface is a ring-shaped wave packet: a leading crest followed
 * by two fading rings. Crests refract the print below like a lens and catch light on one face.
 * The moving water also tints the print a faint cool blue and reflects the pale sky, so every wave
 * shows on white and on busy colour alike, whether or not the two layers differ much. The water
 * moves and settles within the time the original wipe took, and the mark then holds still for the
 * rest of the reveal, so the frame at progress 0 is exactly the previous layer and every frame of
 * that pause is exactly the next one.
 * Distances are in print pixels; the output is drawn at device resolution.
 */
const FRONT_WIDTH = 5;
const TRAIL_LENGTH = 15;
const FRONT_CUTOFF = 3 * FRONT_WIDTH;
/** Faster water carries longer waves, so the rings start wide and tighten as the front slows. */
const WAVELENGTH_FAST = 26;
const WAVELENGTH_SLOW = 16;
/** The two layers blend over this width at the front, so its pixels do not flicker. */
const EDGE = 2;
/**
 * The front keeps the shape of the original soft-edged wipe, a cubic ease-out, spread over a longer
 * sweep: it clears the mark at about 0.56 of the reveal instead of 0.47, and the water has settled
 * by about 0.72, leaving a pause of roughly 0.45 s, half of the original's.
 */
const SWEEP = Math.hypot(MARK_WIDTH, MARK_HEIGHT) + 24;
const MOTION = 0.735;
/** Where the front is when the water settles: just past the far corner of the mark. */
const CLEARANCE = 12;
/** Shares of the sweep: the water rises over the first, and fades out after the second. */
const IMPACT = 0.05;
const FADE_FROM = 0.75;
/** Displacement of the print, in print pixels per unit of surface slope. */
const REFRACTION = 14;
/** Per-channel transmission of the water at full strength: a faint cool blue. */
const WATER = [0.8, 0.89, 0.98];
/**
 * The cool tint disappears on blue print and in busy, saturated colour, so where the print is
 * colourful or dark the water also reflects the pale sky, calming the pattern under the wave.
 * The reflection trails further behind the front than the rings, so on busy layers a whole sheet
 * of water follows each wave. Faces turned away from the light reflect less of it, so they can
 * still darken below the print.
 */
const VEIL = 0.8;
const VEIL_LENGTH = 30;
const SKY = [226, 236, 250];
const FACING = 2;
/** The packet ends where both the rings and the reflection have faded. */
const TRAIL_CUTOFF = 4 * VEIL_LENGTH;
/** Light and shadow on every slope, plus a glint where a face turns to the light. */
const LIGHT = 0.5;
const GLINT_FROM = 0.15;
const GLINT = 1;
/**
 * Shaded faces deepen towards a dark blue rather than black. Busy, saturated layers hide a light
 * shade, while on white even a light one reads as a grey ring, so bright print keeps only part of it.
 */
const SHADE = 0.55;
const SHADE_ON_WHITE = 0.35;
const DEEP = [40, 64, 110];
/** Light from the upper right, so every ring catches it along the visible quarter arc. */
const LIGHT_X = 0.45;
const LIGHT_Y = -0.89;

const reachCache = new WeakMap();
/** Distance from the corner to the farthest corner of any opaque print pixel. */
function reachOf(pixels) {
  let reach = reachCache.get(pixels);
  if (reach !== undefined) return reach;
  reach = 0;
  for (let y = 0; y < MARK_HEIGHT; y++) {
    for (let x = 0; x < MARK_WIDTH; x++) {
      if (!pixels[(y * MARK_WIDTH + x) * 4 + 3]) continue;
      const dy = MARK_HEIGHT - y;
      reach = Math.max(reach, Math.sqrt((x + 1) * (x + 1) + dy * dy));
    }
  }
  reachCache.set(pixels, reach);
  return reach;
}

/**
 * Draws one frame into `target` ({ data, width, height } at MARK_WIDTH * cell by MARK_HEIGHT * cell).
 * `from` and `to` are RGBA print pixels (MARK_WIDTH x MARK_HEIGHT); `from` may be null, which
 * leaves the area ahead of the wave transparent. Pixels outside the mark are always transparent.
 */
export function renderRipple(target, from, to, progress, cell) {
  const { data, width, height } = target;
  const p = Math.min(1, Math.max(0, progress));
  // The original ease-out, stretched so the front just clears the mark as the sweep ends.
  const clearance = (reachOf(to) + CLEARANCE) / (SWEEP - 24);
  const eased = (1 - (1 - p / MOTION) ** 3) / (1 - (1 - MOTION) ** 3);
  const radius = eased * (clearance * (SWEEP - 24)) - CLEARANCE;
  const fade = Math.min(1, Math.max(0, (p / MOTION - FADE_FROM) / (1 - FADE_FROM)));
  const amplitude = Math.min(1, p / MOTION / IMPACT) * (1 - fade * fade * (3 - 2 * fade));
  const k = (2 * Math.PI) / (WAVELENGTH_SLOW + (WAVELENGTH_FAST - WAVELENGTH_SLOW) * (1 - p) ** 2);
  // The surface depends only on the distance to the front, so sample its slope once per frame.
  const step = 1 / (4 * cell);
  const samples = Math.ceil((TRAIL_CUTOFF + FRONT_CUTOFF) / step) + 1;
  const slopes = new Float32Array(samples);
  const depths = new Float32Array(samples);
  const sheets = new Float32Array(samples);
  if (amplitude > 0) {
    for (let n = 0; n < samples; n++) {
      const s = n * step - TRAIL_CUTOFF;
      const ahead = Math.exp(-((s / FRONT_WIDTH) ** 2));
      const envelope = s > 0 ? ahead : Math.exp(s / TRAIL_LENGTH);
      const growth = s > 0 ? (-2 * s) / FRONT_WIDTH ** 2 : 1 / TRAIL_LENGTH;
      slopes[n] = amplitude * envelope * (growth * Math.cos(k * s) - k * Math.sin(k * s));
      depths[n] = amplitude * envelope;
      sheets[n] = amplitude * (s > 0 ? ahead : Math.exp(s / VEIL_LENGTH));
    }
  }
  for (let y = 0, i = 0; y < height; y++) {
    const py = (y + 0.5) / cell;
    const dy = py - MARK_HEIGHT;
    const row = Math.min(MARK_HEIGHT - 1, Math.floor(py)) * MARK_WIDTH;
    for (let x = 0; x < width; x++, i += 4) {
      const px = (x + 0.5) / cell;
      let source = (row + Math.min(MARK_WIDTH - 1, Math.floor(px))) * 4;
      if (!to[source + 3]) {
        data[i] = data[i + 1] = data[i + 2] = data[i + 3] = 0;
        continue;
      }
      const distance = Math.sqrt(px * px + dy * dy);
      const s = distance - radius;
      const inPacket = s > -TRAIL_CUTOFF && s < FRONT_CUTOFF;
      const sample = inPacket ? Math.floor((s + TRAIL_CUTOFF) / step) : 0;
      const slope = inPacket ? slopes[sample] : 0;
      const depth = inPacket ? depths[sample] : 0;
      const sheet = inPacket ? sheets[sample] : 0;
      // A crest magnifies the print around it: sample along the ring's radius, towards the crest.
      const shift = (slope * REFRACTION) / distance;
      if (shift !== 0) {
        const sx = Math.floor(px * (1 + shift));
        const sy = Math.floor(py + dy * shift);
        if (sx >= 0 && sy >= 0 && sx < MARK_WIDTH && sy < MARK_HEIGHT && to[(sy * MARK_WIDTH + sx) * 4 + 3]) {
          source = (sy * MARK_WIDTH + sx) * 4;
        }
      }
      // The front itself is refracted, so the new layer starts where the sampled point is behind it.
      const behind = s + slope * REFRACTION;
      const mix = behind <= -EDGE / 2 ? 1 : behind >= EDGE / 2 ? 0 : 0.5 - behind / EDGE;
      if (!from && mix === 0) {
        data[i] = data[i + 1] = data[i + 2] = data[i + 3] = 0;
        continue;
      }
      let r = to[source], g = to[source + 1], b = to[source + 2];
      if (from && mix < 1) {
        r = from[source] + (r - from[source]) * mix;
        g = from[source + 1] + (g - from[source + 1]) * mix;
        b = from[source + 2] + (b - from[source + 2]) * mix;
      }
      // Tilt towards the light, normalised by the wave number so wider rings keep their highlights.
      const tilt = (-slope * (px * LIGHT_X + dy * LIGHT_Y)) / (distance * k);
      if (sheet > 0) {
        const facing = Math.min(1, Math.max(0, 1 + FACING * tilt));
        const veil = VEIL * sheet * facing * (1 - Math.min(r, g, b) / 255);
        r *= 1 - (1 - WATER[0]) * depth;
        g *= 1 - (1 - WATER[1]) * depth;
        b *= 1 - (1 - WATER[2]) * depth;
        r += (SKY[0] - r) * veil;
        g += (SKY[1] - g) * veil;
        b += (SKY[2] - b) * veil;
      }
      if (tilt > 0) {
        const glint = Math.max(0, tilt - GLINT_FROM) / (1 - GLINT_FROM);
        const lift = Math.min(0.9, LIGHT * tilt + GLINT * glint * glint);
        r += (255 - r) * lift;
        g += (255 - g) * lift;
        b += (255 - b) * lift;
      } else if (tilt < 0) {
        const brightness = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
        const shade = SHADE * Math.min(1, -tilt) * (1 - (1 - SHADE_ON_WHITE) * brightness);
        r += (DEEP[0] - r) * shade;
        g += (DEEP[1] - g) * shade;
        b += (DEEP[2] - b) * shade;
      }
      data[i] = r;
      data[i + 1] = g;
      data[i + 2] = b;
      data[i + 3] = from ? 255 : 255 * mix;
    }
  }
}
