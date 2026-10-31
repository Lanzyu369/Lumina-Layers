const { test } = require('node:test');
const assert = require('node:assert/strict');

const WIDTH = 150, HEIGHT = 207;
const inMark = (x, y) => x < 50 || y > 150;

// An L-shaped mark like the real artwork, striped so refraction moves visible detail.
function layer(red, blue) {
  const pixels = new Uint8ClampedArray(WIDTH * HEIGHT * 4);
  for (let y = 0; y < HEIGHT; y++) {
    for (let x = 0; x < WIDTH; x++) {
      if (!inMark(x, y)) continue;
      pixels.set([red, 40 + ((x + y) % 8) * 20, blue, 255], (y * WIDTH + x) * 4);
    }
  }
  return pixels;
}
const from = layer(200, 40), to = layer(40, 200);
// A single colour, so any change on screen comes from the water rather than from the layers.
function flat(rgb) {
  const pixels = new Uint8ClampedArray(WIDTH * HEIGHT * 4);
  for (let y = 0; y < HEIGHT; y++) {
    for (let x = 0; x < WIDTH; x++) if (inMark(x, y)) pixels.set([...rgb, 255], (y * WIDTH + x) * 4);
  }
  return pixels;
}
const luminance = (data, i) => 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];

async function frame(previous, progress, cell = 1, next = to) {
  const { renderRipple } = await import('../splash-ripple.mjs');
  const target = { data: new Uint8ClampedArray(WIDTH * cell * HEIGHT * cell * 4), width: WIDTH * cell, height: HEIGHT * cell };
  renderRipple(target, previous, next, progress, cell);
  return target;
}
function printPixelAt(target, cell, x, y, pixels) {
  const i = ((y * cell) * target.width + x * cell) * 4;
  return { shown: Array.from(target.data.slice(i, i + 4)), print: Array.from(pixels.slice((y * WIDTH + x) * 4, (y * WIDTH + x) * 4 + 4)) };
}
const isNew = (data, i) => data[i + 3] > 0 && data[i + 2] > data[i];

test('a wave starts on the previous layer and settles exactly on the next one, so swapping layers never jumps', async () => {
  for (const cell of [1, 2]) {
    const start = await frame(from, 0, cell), end = await frame(from, 1, cell);
    for (let y = 0; y < HEIGHT; y += 3) {
      for (let x = 0; x < WIDTH; x += 3) {
        const before = printPixelAt(start, cell, x, y, from);
        assert.deepEqual(before.shown, before.print, `start differs at ${x},${y}`);
        const after = printPixelAt(end, cell, x, y, to);
        assert.deepEqual(after.shown, after.print, `end differs at ${x},${y}`);
      }
    }
  }
});

test('the wave sweeps the mark at roughly the original pace, then holds still for half the pause the original left', async () => {
  let markPixels = 0;
  for (let i = 3; i < to.length; i += 4) if (to[i]) markPixels++;
  const coverage = async progress => {
    const { data } = await frame(from, progress);
    let count = 0;
    for (let i = 0; i < data.length; i += 4) if (isNew(data, i)) count++;
    return count / markPixels;
  };
  // The original covered half of the mark after about 0.26 s and all of it after about 0.62 s of 1.6 s.
  assert.ok(await coverage(0.1) < 0.5, 'not half covered after 0.16 s');
  assert.ok(await coverage(0.2) > 0.5, 'half covered after 0.32 s');
  assert.ok(await coverage(0.4) < 1, 'still sweeping after 0.64 s');
  assert.equal(await coverage(0.62), 1, 'covered after 1 s');
  const moving = await frame(from, 0.6);
  assert.ok(moving.data.some((value, i) => value !== to[i]), 'the water still moves after 0.96 s');
  // It settles at about 0.73 of the reveal, leaving roughly 0.43 s still, half the original's 0.85 s.
  for (const progress of [0.75, 0.8, 0.9, 1]) {
    const { data } = await frame(from, progress);
    assert.ok(data.every((value, i) => value === to[i]), `the mark holds still at ${progress}`);
  }
});

test('the ripple stays inside the mark at every point of the wave', async () => {
  for (let progress = 0; progress <= 1; progress += 0.05) {
    const { data } = await frame(from, progress);
    for (let y = 0; y < HEIGHT; y++) {
      for (let x = 0; x < WIDTH; x++) {
        const alpha = data[(y * WIDTH + x) * 4 + 3];
        assert.equal(alpha > 0, inMark(x, y), `pixel ${x},${y} at ${progress.toFixed(2)}`);
      }
    }
  }
});

test('the next layer spreads from the bottom-left corner and keeps growing until it covers the mark', async () => {
  const middle = await frame(from, 0.15);
  assert.ok(isNew(middle.data, ((HEIGHT - 3) * WIDTH + 3) * 4), 'the corner is covered first');
  assert.ok(!isNew(middle.data, (3 * WIDTH + 25) * 4), 'the top of the stem is covered last');
  let markPixels = 0;
  for (let i = 3; i < to.length; i += 4) if (to[i]) markPixels++;
  let covered = 0;
  for (let progress = 0.05; progress <= 1.0001; progress += 0.05) {
    const { data } = await frame(from, progress);
    let count = 0;
    for (let i = 0; i < data.length; i += 4) if (isNew(data, i)) count++;
    assert.ok(covered === markPixels ? count === markPixels : count > covered, `coverage grows at ${progress.toFixed(2)}`);
    covered = count;
  }
  assert.equal(covered, markPixels);
});

test('the ripple shows as lit and shaded rings instead of a flat wipe', async () => {
  const grey = flat([128, 128, 128]);
  for (const progress of [0.15, 0.3, 0.45]) {
    const { data } = await frame(grey, progress, 1, grey);
    let lighter = 0, darker = 0;
    for (let i = 0; i < data.length; i += 4) {
      if (!data[i + 3]) continue;
      if (luminance(data, i) > 128 + 8) lighter++;
      if (luminance(data, i) < 128 - 8) darker++;
    }
    assert.ok(lighter > 20 && darker > 20, `at ${progress}: lighter ${lighter}, darker ${darker}`);
  }
});

test('on a white layer the ripple reads as pale blue water, not dark grey rings', async () => {
  const white = flat([255, 255, 255]);
  for (const progress of [0.08, 0.2, 0.35, 0.5]) {
    const { data } = await frame(white, progress, 1, white);
    let visible = 0;
    for (let i = 0; i < data.length; i += 4) {
      if (!data[i + 3] || data[i] + data[i + 1] + data[i + 2] > 3 * 255 - 12) continue;
      visible++;
      assert.ok(luminance(data, i) > 190, `too dark at ${progress}: ${Array.from(data.slice(i, i + 3))}`);
      assert.ok(data[i + 2] > data[i], `not water-coloured at ${progress}: ${Array.from(data.slice(i, i + 3))}`);
    }
    assert.ok(visible > 300, `the ripple is visible at ${progress}: ${visible} pixels`);
  }
});

test('on busy, saturated print the water still stands out from the pattern, not only on white', async () => {
  // Diagonal bands of blue, green and magenta a few pixels wide, like the late layers of the mark.
  const bands = [[30, 100, 220], [60, 170, 90], [200, 50, 160], [40, 60, 150]];
  const busy = new Uint8ClampedArray(WIDTH * HEIGHT * 4);
  for (let y = 0; y < HEIGHT; y++) {
    for (let x = 0; x < WIDTH; x++) if (inMark(x, y)) busy.set([...bands[Math.floor((x + 2 * y) / 5) % bands.length], 255], (y * WIDTH + x) * 4);
  }
  // Pixels where the water changes the colour by more than the print already varies around them.
  async function standsOut(print) {
    const variation = new Float32Array(WIDTH * HEIGHT);
    for (let y = 0; y < HEIGHT; y++) {
      for (let x = 0; x < WIDTH; x++) {
        if (!inMark(x, y)) continue;
        const near = [];
        for (let v = Math.max(0, y - 3); v <= Math.min(HEIGHT - 1, y + 3); v++) {
          for (let u = Math.max(0, x - 3); u <= Math.min(WIDTH - 1, x + 3); u++) if (inMark(u, v)) near.push((v * WIDTH + u) * 4);
        }
        const mean = [0, 1, 2].map(c => near.reduce((sum, j) => sum + print[j + c], 0) / near.length);
        variation[y * WIDTH + x] = near.reduce((sum, j) => sum + Math.hypot(print[j] - mean[0], print[j + 1] - mean[1], print[j + 2] - mean[2]), 0) / near.length;
      }
    }
    let count = 0;
    for (const progress of [0.15, 0.3, 0.45]) {
      const { data } = await frame(print, progress, 1, print);
      for (let i = 0; i < WIDTH * HEIGHT; i++) {
        const j = i * 4;
        if (data[j + 3] && Math.hypot(data[j] - print[j], data[j + 1] - print[j + 1], data[j + 2] - print[j + 2]) > 8 + 0.6 * variation[i]) count++;
      }
    }
    return count;
  }
  const white = await standsOut(flat([255, 255, 255])), colour = await standsOut(busy);
  assert.ok(colour >= 0.5 * white, `busy colour: ${colour} pixels stand out, white: ${white}`);
});

test('a ripple carries at most three rings at a time', async () => {
  const grey = flat([128, 128, 128]);
  for (let progress = 0.08; progress < 0.55; progress += 0.03) {
    const { data } = await frame(grey, progress, 1, grey);
    // Walk up the stem from the corner and count the brightness peaks that stand clear of the dips beside them.
    const profile = [];
    for (let y = HEIGHT - 1; y >= 0; y--) profile.push(luminance(data, (y * WIDTH + 25) * 4));
    let rings = 0;
    for (let i = 1; i < profile.length - 1; i++) {
      if (!(profile[i] > profile[i - 1] && profile[i] >= profile[i + 1])) continue;
      let left = profile[i], right = profile[i];
      for (let j = i - 1; j >= 0 && profile[j] <= profile[i]; j--) left = Math.min(left, profile[j]);
      for (let j = i + 1; j < profile.length && profile[j] <= profile[i]; j++) right = Math.min(right, profile[j]);
      if (profile[i] - Math.max(left, right) > 6) rings++;
    }
    assert.ok(rings >= 1 && rings <= 3, `${rings} rings at ${progress.toFixed(2)}`);
  }
});

test('the first wave leaves the area ahead of it transparent so the faint final mark shows through', async () => {
  const { data } = await frame(null, 0.15);
  assert.equal(data[(3 * WIDTH + 25) * 4 + 3], 0);
  assert.ok(isNew(data, ((HEIGHT - 3) * WIDTH + 3) * 4));
});
