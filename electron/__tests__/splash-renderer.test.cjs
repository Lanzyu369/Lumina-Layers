const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

async function playback({ readyAt = 400, targetAt = () => 3, reduced = false } = {}) {
  let now = 0, ready = false, frame, poll, finished = 0;
  const progress = { value: 0 };
  const context = new Proxy({}, { get: (_, key) => key === 'createRadialGradient'
    ? () => ({ addColorStop() {} }) : () => {} });
  const canvas = () => ({ style: {}, getContext: () => context });
  const elements = {
    canvas: canvas(), progress,
    '#art': { style: {}, getBoundingClientRect: () => ({ left: 0, top: 0 }) },
    '#status': {}, '#version': {},
  };
  const source = fs.readFileSync(path.join(__dirname, '../splash-renderer.mjs'), 'utf8')
    .replace(/^import .*;\n/gm, '');
  await vm.runInNewContext(`(async () => { ${source}\n })()`, {
    LAYERS: 10,
    createPacer: () => ({ reach() {}, fastForward() {}, step: () => ready ? 10 : targetAt(now) }),
    fitMark: () => ({ cssWidth: 150, cssHeight: 207, deviceWidth: 150, deviceHeight: 207, cell: 1 }),
    snapOffset: () => 0,
    document: { querySelector: key => elements[key], createElement: canvas },
    Image: class { complete = true; naturalWidth = 150; },
    matchMedia: () => ({ matches: reduced }),
    performance: { now: () => now },
    requestAnimationFrame: callback => { frame = callback; },
    setTimeout: callback => { poll = callback; },
    window: { devicePixelRatio: 1, addEventListener() {}, studioSplash: {
      read: async () => ({ ready, checkpoint: ready ? 8 : 2, elapsedMs: now, history: null, text: {} }),
      finished: () => { finished++; },
    } },
  });
  const completed = [], completedAt = [];
  let previous = 0, fullAt;
  for (now = 0; now <= readyAt + 8400 && !finished; now += 16) {
    ready = now >= readyAt;
    await poll();
    frame();
    assert.ok(progress.value >= previous, 'progress never rewinds');
    if (progress.value !== previous) { completed.push(progress.value); completedAt.push(now); }
    previous = progress.value;
    if (progress.value === 10) fullAt ??= now;
    if (fullAt !== undefined && now < fullAt + 1000) assert.equal(finished, 0);
  }
  assert.equal(finished, 1);
  return { completed, completedAt, fullAt, finishAt: now - 16 };
}

test('readiness during a ripple retains middle layers and finishes with a wave, then holds for a second', async () => {
  const result = await playback();
  assert.deepEqual(result.completed, [2, 5, 8, 10]);
  assert.ok(result.fullAt > 400 + 1600, 'ready does not immediately display the final logo');
  assert.ok(result.finishAt < 400 + 8000);
  assert.equal(result.completedAt[0], 1600, 'readiness must not accelerate an active wave');
  for (let i = 1; i < result.completedAt.length; i++) {
    assert.equal(result.completedAt[i] - result.completedAt[i - 1], 1600, 'skipped layers retain normal wave duration');
  }
});

test('an immediately ready startup samples the full layer range', async () => {
  const result = await playback({ readyAt: 0 });
  assert.deepEqual(result.completed, [4, 8, 10]);
  assert.deepEqual(result.completedAt, [1600, 3200, 4800]);
});

test('a slow startup retains every layer', async () => {
  const result = await playback({ readyAt: 18000, targetAt: now => Math.min(9, 1 + Math.floor(now / 2000)) });
  assert.deepEqual(result.completed, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
});

test('reduced motion still completes without replaying water waves', async () => {
  const result = await playback({ readyAt: 0, reduced: true });
  assert.ok(result.fullAt < 100);
});

test('actual checkpoints move pacing forward even when a cold-launch estimate is too slow', async () => {
  const { createPacer } = await import('../splash-launchProgress.mjs');
  const pacer = createPacer(null);
  pacer.reach(2);
  assert.equal(pacer.step(0), 2);
  pacer.reach(5);
  assert.ok(pacer.step(100) >= 7);
  pacer.reach(7);
  assert.equal(pacer.step(200), 9);
  pacer.reach(8);
  assert.equal(pacer.step(300), 10);
});
