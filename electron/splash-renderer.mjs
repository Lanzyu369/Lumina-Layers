import { createPacer, LAYERS } from './splash-launchProgress.mjs';
import { fitMark, snapOffset } from './splash-markSize.mjs';

if (!window.studioSplash && new URLSearchParams(location.search).has('preview')) {
  window.studioSplash = await (await import('./splash-preview.mjs')).createPreview();
}

const canvas = document.querySelector('canvas');
const box = document.querySelector('#art');
const context = canvas.getContext('2d');
const layerCanvas = document.createElement('canvas');
const layerContext = layerCanvas.getContext('2d');
const progressBar = document.querySelector('progress');
const status = document.querySelector('#status');
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const images = Array.from({ length: LAYERS }, (_, i) => {
  const image = new Image();
  image.src = `./splash-art/B${String(i + 1).padStart(2, '0')}.png`;
  return image;
});
let state, pacer, origin, size, base = 0, current = 0, reveal = null, finishStarted = null;
let lastTick = null, readyStep = null;
const REVEAL_MS = 1600, HOLD_MS = 1000;
const imageAt = layer => images[layer - 1]?.complete && images[layer - 1].naturalWidth ? images[layer - 1] : null;

function layout() {
  const dpr = window.devicePixelRatio || 1;
  size = fitMark(210, 290, dpr, .2);
  box.style.width = `${size.cssWidth}px`;
  box.style.height = `${size.cssHeight}px`;
  const rect = box.getBoundingClientRect();
  canvas.style.left = `${snapOffset(rect.left, dpr)}px`;
  canvas.style.top = `${snapOffset(rect.top, dpr)}px`;
  canvas.style.width = `${size.cssWidth}px`;
  canvas.style.height = `${size.cssHeight}px`;
  canvas.width = layerCanvas.width = size.deviceWidth;
  canvas.height = layerCanvas.height = size.deviceHeight;
}
function draw() {
  const { deviceWidth: w, deviceHeight: h, cell } = size;
  context.clearRect(0, 0, w, h);
  context.imageSmoothingEnabled = false;
  const final = imageAt(LAYERS);
  if (final) { context.globalAlpha = .08; context.drawImage(final, 0, 0, w, h); context.globalAlpha = 1; }
  if (imageAt(base)) context.drawImage(imageAt(base), 0, 0, w, h);
  if (reveal && imageAt(reveal.layer)) {
    const progress = reveal.progress;
    const feather = 24 * cell;
    const radius = (1 - (1 - progress) ** 3) * (Math.hypot(w, h) + feather);
    layerContext.clearRect(0, 0, w, h);
    layerContext.imageSmoothingEnabled = false;
    layerContext.drawImage(imageAt(reveal.layer), 0, 0, w, h);
    const gradient = () => layerContext.createRadialGradient(0, h, Math.max(0, radius - feather), 0, h, Math.max(.01, radius));
    const mask = gradient();
    mask.addColorStop(0, 'rgba(255,255,255,1)'); mask.addColorStop(1, 'rgba(255,255,255,0)');
    layerContext.globalCompositeOperation = 'destination-in';
    layerContext.fillStyle = mask; layerContext.fillRect(0, 0, w, h);
    const crest = gradient();
    crest.addColorStop(0, 'rgba(100,116,139,0)'); crest.addColorStop(.5, 'rgba(100,116,139,.35)'); crest.addColorStop(1, 'rgba(100,116,139,0)');
    layerContext.globalCompositeOperation = 'source-atop';
    layerContext.globalAlpha = Math.sin(Math.PI * progress);
    layerContext.fillStyle = crest; layerContext.fillRect(0, 0, w, h);
    layerContext.globalAlpha = 1; layerContext.globalCompositeOperation = 'source-over';
    context.drawImage(layerCanvas, 0, 0);
  }
}
function tick() {
  if (!state) { requestAnimationFrame(tick); return; }
  const now = performance.now() - origin;
  const elapsed = lastTick === null ? 0 : Math.max(0, now - lastTick);
  lastTick = now;
  if (reveal) {
    // Startup progress selects layers; it never changes a wave's playback speed.
    reveal.progress = Math.min(1, reveal.progress + elapsed / REVEAL_MS);
    if (reveal.progress === 1) { base = reveal.layer; reveal = null; }
  }
  // Spread the remaining artwork over up to three waves, rather than fading to the final image.
  if (state.ready && readyStep === null) readyStep = Math.max(1, Math.ceil((LAYERS - current) / 3));
  const target = Math.floor(pacer.step(now));
  if (!reveal && current < target) {
    const stride = readyStep ?? Math.max(1, Math.min(3, Math.ceil((target - current) / 2)));
    current = Math.min(target, current + stride);
    if (reduced) base = current;
    else reveal = { layer: current, progress: 0 };
  }
  // Hold only after the actual final image is available; a failed asset cannot block startup.
  if (state.ready && base === LAYERS && finishStarted === null && imageAt(LAYERS)) finishStarted = now;
  progressBar.value = base;
  draw();
  if (finishStarted !== null && now >= finishStarted + HOLD_MS) {
    window.studioSplash.finished(); return;
  }
  requestAnimationFrame(tick);
}
async function poll() {
  try {
    state = await window.studioSplash.read();
    if (state) {
      if (!pacer) {
        pacer = createPacer(state.history); pacer.reach(state.checkpoint);
        pacer.fastForward(state.elapsedMs); origin = performance.now() - state.elapsedMs;
        document.querySelector('#version').textContent = state.version;
      }
      pacer.reach(state.checkpoint);
      const key = state.ready ? 'ready' : state.checkpoint >= 5 ? 'window' : state.checkpoint >= 2 ? 'backend' : 'starting';
      status.textContent = state.text[`desktop_startup_${key}`];
    }
  } finally { setTimeout(poll, 80); }
}
layout(); window.addEventListener('resize', layout);
void poll(); requestAnimationFrame(tick);
