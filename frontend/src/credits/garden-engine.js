import { CreditsAvatarCache } from './avatar-cache.js';

/** The approved bubble renderer, scoped to one mounted credits garden. */
export function createCreditsGarden(root, catalog, labels) {
'use strict';

/* ───────────── utilities ───────────── */
const TAU = Math.PI * 2;
const RECOVERY_DURATION = 1.15;
const $ = (s) => root.querySelector(`[data-credits="${s.slice(1)}"]`);
let disposed = false, frameHandle = 0, blurTimer = 0, started = false;
const removers = [];
function listen(target, type, listener, options) {
  target.addEventListener(type, listener, options);
  removers.push(() => target.removeEventListener(type, listener, options));
}
function schedule() {
  if (!disposed && !document.hidden && !frameHandle) frameHandle = requestAnimationFrame(frame);
}
function localPoint(event) {
  const rect = root.getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}
function releaseSurface(surface) { if (surface) surface.width = surface.height = 1; }
function releaseBubble(b) {
  releaseSurface(b.sprite); releaseSurface(b.nameTexture); releaseSurface(b.nameZoomTexture);
}

const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
const lerp = (a, b, t) => a + (b - a) * t;
const easeOut = (p) => 1 - Math.pow(1 - p, 3);
let DPR = window.devicePixelRatio || 1;
const FONT = getComputedStyle(root).fontFamily || 'MiSans, sans-serif';
const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;

function mulberry(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rand = Math.random;
const wave = (x, s) => Math.sin(x * 1.7 + s) * 0.5 + Math.sin(x * 2.9 + s * 1.3) * 0.3 + Math.sin(x * 5.3 + s * 2.1) * 0.2;
const segmenter = typeof Intl !== 'undefined' && Intl.Segmenter ? new Intl.Segmenter('zh', { granularity: 'grapheme' }) : null;
const graphemes = (s) => (segmenter ? Array.from(segmenter.segment(s), (x) => x.segment) : Array.from(s));

/* ───────────── tiers ─────────────
   One ladder of light: each step adds a layer of optical behaviour. */
const TIERS = [
  { text: '#f3f6ff', rgb: '200,218,255', mult: 1.00, pad: 0.00 },
  { text: '#eef2fb', rgb: '226,234,255', mult: 1.12, pad: 0.04 },
  { text: '#ffe3a4', rgb: '255,200,105', mult: 1.25, pad: 0.07 },
  { text: '#eef6ff', rgb: '170,215,255', mult: 1.38, pad: 0.10 },
  { text: '#d6f2ff', rgb: '110,200,255', mult: 1.52, pad: 0.13 },
  { text: '#d2fff0', rgb: '80,255,190', mult: 1.66, pad: 0.17 },
  { text: '#ffe0c2', rgb: '255,150,70', mult: 1.82, pad: 0.22 },
  { text: '#e8deff', rgb: '165,125,255', mult: 2.00, pad: 0.26 },
];
const DEV = { text: '#d9e9ff', rgb: '90,160,255' };
const styleOf = (p) => (p.dev && p.tier === 0 ? DEV : TIERS[p.tier]);

/* ───────────── independently updated real credits ───────────── */
const data = catalog;
const roster = (() => {
  const r = mulberry(20261003);
  const list = data.records.map((p, index) => ({
    id: index, creditId: p.id, name: p.name, source: p.source,
    tier: p.tier, dev: p.dev, brand: p.brand, aliases: p.aliases || [],
    photo: p.avatar, avatarSize: p.avatar_size,
    preview: p.avatar_preview, previewSize: p.avatar_preview_size,
    hue: (r() * 360) | 0, seed: r(),
    searchName: p.name.toLowerCase(),
  }));
  for (let i = list.length - 1; i > 0; i--) {
    const j = (r() * (i + 1)) | 0; [list[i], list[j]] = [list[j], list[i]];
  }
  return list;
})();
const byTier = (t) => roster.filter((p) => t === 'dev' ? p.dev : t === 'brand' ? p.brand : !p.dev && !p.brand && p.tier === t);

/* ───────────── avatar images ───────────── */
const avatars = new CreditsAvatarCache();
const PALETTES = [[228, 262, 34], [195, 225, 30], [318, 280, 26], [345, 305, 28], [168, 205, 26], [250, 285, 30], [205, 180, 24], [214, 240, 18]];
function drawAvatar(g, p, R, onReady) {
  if (p.photo) {
    const pixels = Math.ceil(R * 2 * DPR * 1.8);
    const preview = p.preview && p.previewSize && pixels <= Math.min(...p.previewSize);
    const url = new URL(preview ? p.preview : p.photo, catalog.assetsBase).href;
    const e = avatars.get(url, preview ? p.previewSize : p.avatarSize,
      pixels, p.brand ? 'contain' : 'cover', onReady);
    if (e.ok) {
      if (p.brand) {
        g.fillStyle = TIERS[0].text; g.fillRect(-R, -R, R * 2, R * 2);
        const width = e.img.width || e.img.naturalWidth, height = e.img.height || e.img.naturalHeight;
        const scale = R * 1.6 / Math.max(width, height);
        g.drawImage(e.img, -width * scale / 2, -height * scale / 2, width * scale, height * scale);
      } else g.drawImage(e.img, -R, -R, R * 2, R * 2);
      return;
    }
  }
  const [h1, h2, sat] = p.dev ? [214, 232, 46] : PALETTES[((p.hue / 45) | 0) % PALETTES.length];
  const lg = g.createLinearGradient(-R, -R, R, R);
  lg.addColorStop(0, `hsl(${h1},${sat}%,34%)`);
  lg.addColorStop(1, `hsl(${h2},${sat + 6}%,14%)`);
  g.fillStyle = lg; g.fillRect(-R, -R, R * 2, R * 2);
  const rg = g.createRadialGradient(R * 0.5, -R * 0.45, 0, R * 0.5, -R * 0.45, R * 1.25);
  rg.addColorStop(0, `hsla(${h2 + 30},${sat + 30}%,62%,.42)`); rg.addColorStop(1, `hsla(${h2 + 30},${sat + 30}%,62%,0)`);
  g.fillStyle = rg; g.fillRect(-R, -R, R * 2, R * 2);
  // 无头像时只用柔和的抽象光斑，不放首字
  const r2 = mulberry((p.seed * 4294967296) >>> 0);
  for (let i = 0; i < 3; i++) {
    const bx = (r2() - 0.5) * R * 1.4, by = (r2() - 0.5) * R * 1.4, br = R * (0.55 + r2() * 0.6);
    const bh = h1 + (r2() - 0.5) * 70;
    const bg = g.createRadialGradient(bx, by, 0, bx, by, br);
    bg.addColorStop(0, `hsla(${bh},${sat + 34}%,${48 + r2() * 14}%,${0.32 + r2() * 0.2})`);
    bg.addColorStop(1, `hsla(${bh},${sat + 34}%,50%,0)`);
    g.fillStyle = bg; g.fillRect(-R, -R, R * 2, R * 2);
  }
}

/* ───────────── nickname layout (inside, along arcs) ───────────── */
const mctx = document.createElement('canvas').getContext('2d');
const nameFont = (fs) => `600 ${fs}px ${FONT}`;
const glyphWidths = new Map();
function measure(gs, fs) {
  return gs.map((x) => {
    const key = fs + ':' + x;
    if (!glyphWidths.has(key)) {
      mctx.font = nameFont(fs);
      glyphWidths.set(key, mctx.measureText(x).width);
    }
    return glyphWidths.get(key);
  });
}
const sum = (a, i = 0, j = a.length) => { let s = 0; for (let k = i; k < j; k++) s += a[k]; return s; };
const arcGeometryCache = new Map();
function arcGeometry(fs, R, top) {
  const key = `${fs}:${R}:${top}`;
  if (arcGeometryCache.has(key)) return arcGeometryCache.get(key);
  const rr = Math.max(12, R * 2.4);
  const ascent = fs * .82, descent = fs * .18;
  const tr = top ? .28 : .2 + fs * fs * .6 / Math.max(12, rr - ascent);
  const startY = top ? -R + ascent + 3.4 : R - 5;
  const endY = top ? -descent - .3 : ascent + .9;
  const positions = [], edges = top ? [rr - descent, rr + ascent] : [rr - ascent, rr + descent];
  for (let step = 0; step <= 12; step++) {
    const y = lerp(startY, endY, step / 12), cy = y + (top ? rr : -rr);
    const angle = Math.min(.82, ...edges.map(edge => Math.acos(clamp((edge * edge + cy * cy - (R - 1.4) ** 2) / Math.max(1, 2 * Math.abs(cy) * edge), -1, 1))));
    positions.push({ y, capacity: rr * angle * 2 - 1 });
  }
  const geometry = { rr, tr, positions };
  // Geometry depends only on size and font, so all nicknames can share it.
  if (arcGeometryCache.size >= 512) arcGeometryCache.delete(arcGeometryCache.keys().next().value);
  arcGeometryCache.set(key, geometry);
  return geometry;
}
function nameArc(gs, fs, R, top = false) {
  const geometry = arcGeometry(fs, R, top), { rr, tr, positions } = geometry, ws = measure(gs, fs);
  const width = sum(ws) + tr * Math.max(0, gs.length - 1);
  const position = positions.find(p => width <= p.capacity) || positions[positions.length - 1];
  return nameArcLine(gs, ws, geometry, position, width, top);
}
function nameArcLine(gs, ws, geometry, position, width, top) {
  const { rr, tr } = geometry;
  return { gs, ws, tr, rr, y: position.y, top, width, halfAngle: width / (rr * 2), fits: width <= position.capacity };
}
function fullNameLines(gs, fs, R) {
  const single = nameArc(gs, fs, R);
  if (single.fits) return [single];
  const ws = single.ws, upper = arcGeometry(fs, R, true), lower = arcGeometry(fs, R, false);
  const upperEdge = upper.rr - fs * .18, lowerEdge = lower.rr - fs * .82;
  let best = null, score = Infinity;
  for (let split = 1; split < gs.length; split++) {
    const topWidth = sum(ws, 0, split) + upper.tr * (split - 1);
    const bottomWidth = sum(ws, split) + lower.tr * (gs.length - split - 1);
    const top = upper.positions.find(p => topWidth <= p.capacity);
    const bottom = lower.positions.find(p => bottomWidth <= p.capacity);
    if (!top || !bottom) continue;
    const x = Math.min(upperEdge * Math.sin(topWidth / (upper.rr * 2)), lowerEdge * Math.sin(bottomWidth / (lower.rr * 2)));
    const upperBottom = top.y + upper.rr - Math.sqrt(Math.max(0, upperEdge ** 2 - x ** 2));
    const lowerTop = bottom.y - lower.rr + Math.sqrt(Math.max(0, lowerEdge ** 2 - x ** 2));
    if (lowerTop - upperBottom < 2.2) continue;
    const prev = gs[split - 1], next = gs[split];
    const natural = /[_\s·的]/.test(prev) || /^[\s_]/.test(next) || (/[A-Za-z0-9]/.test(prev) !== /[A-Za-z0-9]/.test(next));
    const cost = Math.abs(topWidth - bottomWidth) - (natural ? 3 : 0);
    if (cost < score) { score = cost; best = { split, top, bottom, topWidth, bottomWidth }; }
  }
  if (!best) return null;
  // Measure once and create glyph arrays only for the chosen line break.
  return [
    nameArcLine(gs.slice(0, best.split), ws.slice(0, best.split), upper, best.top, best.topWidth, true),
    nameArcLine(gs.slice(best.split), ws.slice(best.split), lower, best.bottom, best.bottomWidth, false),
  ];
}
function layoutName(name, R) {
  const gs = graphemes(name);
  if (R < 16) return { fs: 11, lines: [], truncated: true };
  const preferred = Math.floor(clamp(R * .26, 11, 18) * 2) / 2;
  for (let fs = preferred; fs >= 11; fs -= .5) {
    const lines = fullNameLines(gs, fs, R);
    if (lines) return { fs, lines, truncated: false };
  }
  for (let end = gs.length - 1; end > 0; end--) {
    const lines = fullNameLines([...gs.slice(0, end), '…'], 11, R);
    if (lines) return { fs: 11, lines, truncated: true };
  }
  return { fs: 11, lines: [], truncated: true };
}
const nameRadiusCache = new Map();
function minimumNameRadius(name) {
  if (nameRadiusCache.has(name)) return nameRadiusCache.get(name);
  const gs = graphemes(name);
  let radius = 18;
  if (gs.length <= 24 && sum(measure(gs, 11)) <= 132) {
    while (radius < 40 && !fullNameLines(gs, 11, radius)) radius += .5;
  }
  nameRadiusCache.set(name, radius);
  return radius;
}
function drawArcText(g, L, color, shadowScale = 1) {
  g.font = nameFont(L.fs);
  g.textAlign = 'center'; g.textBaseline = 'alphabetic';
  g.fillStyle = color;
  g.shadowColor = 'rgba(0,0,0,.65)'; g.shadowBlur = Math.max(2, L.fs * 0.35) * shadowScale;
  for (const ln of L.lines) {
    const total = sum(ln.ws) + ln.tr * (ln.gs.length - 1);
    let position = -total / 2;
    for (let i = 0; i < ln.gs.length; i++) {
      const a = (position + ln.ws[i] / 2) / ln.rr;
      g.save();
      g.translate(Math.sin(a) * ln.rr, ln.y + (ln.top ? 1 : -1) * (1 - Math.cos(a)) * ln.rr);
      g.rotate((ln.top ? 1 : -1) * a);
      g.fillText(ln.gs[i], 0, 0);
      g.restore();
      position += ln.ws[i] + ln.tr;
    }
  }
  g.shadowBlur = 0; g.shadowColor = 'transparent';
}

/* ───────────── bubble sprite: avatar + glass ───────────── */
function conic(g, start, x, y, stops) {
  if (!g.createConicGradient) return stops[0][1];
  const c = g.createConicGradient(start, x, y);
  for (const [o, col] of stops) c.addColorStop(o, col);
  return c;
}
const even = (cols) => cols.map((c, i) => [i / (cols.length - 1), c]);
const RINGS = {
  1: { w: 0.07, cols: even(['#6b7286', '#f8fafc', '#9aa3b5', '#eef1f6', '#7b8296', '#e3e7ee', '#6b7286']) },
  2: { w: 0.085, cols: even(['#7a4e10', '#ffe7a3', '#c08a2c', '#fff6d6', '#8a5a14', '#f2c766', '#7a4e10']) },
  3: { w: 0.03, cols: even(['rgba(255,255,255,.7)', 'rgba(255,255,255,.35)', 'rgba(255,255,255,.7)']) },
  4: { w: 0.06, cols: even(['#16365e', '#8fdcff', '#1c4a7a', '#d9f4ff', '#16365e']) },
  5: { w: 0.055, cols: even(['#1de9b6', '#3ad7ff', '#8a6bff', '#ff6bd6', '#1de9b6']) },
  6: { w: 0.07, cols: even(['#ff9a3c', '#fff1c1', '#ff6a1f', '#ffd38a', '#ff9a3c']) },
  7: { w: 0.07, cols: even(['#4b2bd8', '#e2d6ff', '#9b63ff', '#56d6ff', '#4b2bd8']) },
};
const IRIDESCENT = even(['rgba(255,140,200,.55)', 'rgba(120,220,255,.5)', 'rgba(255,240,150,.45)', 'rgba(170,140,255,.55)', 'rgba(120,255,210,.45)', 'rgba(255,140,200,.55)']);

function buildSprite(b, R, loadPhoto = true) {
  const p = b.p, st = styleOf(p);
  const pad = 2, half = R + pad, size = Math.ceil(half * 2 * DPR);
  const c = b.sprite && b.sprite.width === size ? b.sprite : document.createElement('canvas');
  c.width = c.height = size;
  const g = c.getContext('2d');
  g.setTransform(DPR, 0, 0, DPR, half * DPR, half * DPR);
  g.clearRect(-half, -half, half * 2, half * 2);

  g.save();
  g.beginPath(); g.arc(0, 0, R, 0, TAU); g.clip();
  b.avatarReady ||= () => { if (!disposed) b.dirty = true; };
  drawAvatar(g, loadPhoto ? p : { ...p, photo: null }, R, b.avatarReady);
  // spherical volume
  let gr = g.createRadialGradient(-R * 0.28, -R * 0.34, R * 0.1, 0, 0, R * 1.02);
  gr.addColorStop(0, 'rgba(255,255,255,0.06)');
  gr.addColorStop(0.62, 'rgba(6,8,22,0)');
  gr.addColorStop(1, 'rgba(6,8,22,0.5)');
  g.fillStyle = gr; g.fillRect(-R, -R, R * 2, R * 2);
  // specular highlight (soft window reflection)
  g.save();
  g.translate(-R * 0.34, -R * 0.44); g.rotate(-0.62); g.scale(1, 0.5);
  const hg = g.createRadialGradient(0, 0, 0, 0, 0, R * 0.52);
  hg.addColorStop(0, 'rgba(255,255,255,.5)'); hg.addColorStop(0.55, 'rgba(255,255,255,.14)'); hg.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = hg; g.beginPath(); g.arc(0, 0, R * 0.52, 0, TAU); g.fill();
  g.restore();
  // hot spot
  const hs = g.createRadialGradient(-R * 0.46, -R * 0.52, 0, -R * 0.46, -R * 0.52, R * 0.12);
  hs.addColorStop(0, 'rgba(255,255,255,.95)'); hs.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = hs; g.fillRect(-R, -R, R * 2, R * 2);
  // inner bounce light, lower right
  g.lineWidth = Math.max(1, R * 0.05);
  g.strokeStyle = 'rgba(255,255,255,.22)';
  g.beginPath(); g.arc(0, 0, R * 0.9, 0.15, 1.35); g.stroke();
  g.restore();

  // thin-film iridescent rim
  g.lineWidth = Math.max(1, R * 0.05);
  g.strokeStyle = conic(g, -0.6, 0, 0, IRIDESCENT);
  g.beginPath(); g.arc(0, 0, R - g.lineWidth / 2, 0, TAU); g.stroke();
  // tier ring
  const ring = !S.fx || (p.dev && p.tier === 0) ? null : RINGS[p.tier];
  if (ring) {
    const w = Math.max(1.2, R * ring.w);
    g.lineWidth = w; g.strokeStyle = conic(g, -1.1, 0, 0, ring.cols);
    g.beginPath(); g.arc(0, 0, R - w / 2, 0, TAU); g.stroke();
    g.lineWidth = 0.8; g.strokeStyle = 'rgba(0,0,0,.35)';
    g.beginPath(); g.arc(0, 0, R - w - 0.4, 0, TAU); g.stroke();
  }
  if (p.dev && S.fx) {
    g.lineWidth = Math.max(1.4, R * 0.06);
    g.strokeStyle = conic(g, -1.2, 0, 0, even(['#2f7bff', '#bcd8ff', '#2f7bff', '#7fb2ff', '#2f7bff']));
    g.beginPath(); g.arc(0, 0, R - g.lineWidth / 2, 0, TAU); g.stroke();
  }
  g.lineWidth = 0.75; g.strokeStyle = 'rgba(255,255,255,.28)';
  g.beginPath(); g.arc(0, 0, R - 0.4, 0, TAU); g.stroke();

  b.sprite = c; b.sR = R; b.sHalf = half; b.dirty = false;
}

/* ───────────── scene state ───────────── */
const canvas = $('#scene');
const ctx = canvas.getContext('2d');
const S = {
  W: 0, H: 0, scale: 1, pixelRatio: 1, now: 0, t: 0, motion: !reduceMotion, fx: false, warmupRemaining: 0,
  warmupTextureIndex: 0, warmupTextureCount: 0,
  ptr: { x: -1e4, y: -1e4, inside: false, mouse: true },
  hover: null, spot: null,
  pill: { x0: 0, y0: 0, x1: 0, y1: 0, r: 26 }, cx: 0, cy: 0,
};
const bubbles = [];
const bursts = [];
const vacancies = [];
const onScreen = new Set();
const stars = [];
const lights = [
  { rgb: '70,90,220', r: 0.75, a: 0.16, ox: 0.18, oy: 0.30, sp: 0.05, ph: 0 },
  { rgb: '40,160,190', r: 0.62, a: 0.10, ox: 0.82, oy: 0.72, sp: 0.04, ph: 2 },
  { rgb: '150,70,200', r: 0.55, a: 0.10, ox: 0.70, oy: 0.18, sp: 0.06, ph: 4 },
];
for (const L of lights) {
  L.node = document.createElement('div');
  L.node.className = 'ambient-light';
  $('#ambient').appendChild(L.node);
}

function baseRadius(p) {
  const m = p.brand ? 1.5 : p.dev && p.tier === 0 ? 1.38 : TIERS[p.tier].mult;
  return Math.max(25 * m * S.scale, minimumNameRadius(p.name));
}
function padOf(p) { return S.fx ? (p.dev && p.tier === 0 ? 0.1 : TIERS[p.tier].pad) : 0; }

function makeBubble(p, x, y) {
  const sizeSeed = p.seed;
  const r0 = baseRadius(p, sizeSeed);
  const b = {
    p, x, y, vx: 0, vy: 0, r: 0, rv: 0, radiusSpeed: 0, r0, rt: r0, sizeSeed,
    anchorX: x, anchorY: y,
    contactRadius: 0, contactGrowth: 0, wallRadius: 0, inverseMass: 0, contactX: x, contactY: y, fixed: false, seedRecovery: false,
    state: 'live', vis: 1, alpha: 1, boost: 0, ph: rand() * TAU, born: 0, heavyUntil: 0, recoverUntil: 0, recoverAge: 0,
    sprite: null, sR: 0, sHalf: 0, dirty: true, bolts: null, boltT: 0, flash: 0,
    disk: null, motes: null, embers: null, entering: false, swap: null, removing: false,
  };
  if (p.tier === 7) {
    b.disk = Array.from({ length: 150 }, () => {
      const rr = 1.2 + Math.pow(rand(), 1.6) * 0.95;
      return { a: rand() * TAU, rr, sp: 0.8 + rand() * 0.5, sz: 0.6 + rand() * 1.3,
        col: `hsla(${rand() < 0.75 ? 250 + rand() * 60 : 185 + rand() * 25},95%,${68 + (2.2 - rr) * 14}%,`, br: 0.35 + rand() * 0.65 };
    });
  }
  if (p.tier === 2) b.motes = Array.from({ length: 12 }, (_, i) => ({ a: rand() * TAU, s: 0.15 + rand() * 0.25, d: 1.08 + rand() * 0.28, ph: rand() * TAU, sz: 0.8 + rand() * 1.1 }));
  if (p.tier === 6) b.embers = Array.from({ length: 18 }, () => ({ a: -Math.PI / 2 + (rand() - 0.5) * 2.6, L: 1.4 + rand() * 1.3, o: rand() * 3, sw: rand() * TAU, sz: 0.7 + rand() * 1.2 }));
  onScreen.add(p.id);
  bubbles.push(b);
  return b;
}

/* ───────────── layout ───────────── */
function readPill() {
  const rootRect = root.getBoundingClientRect(), r = $('#pill').getBoundingClientRect();
  S.pill = { x0: r.left - rootRect.left, y0: r.top - rootRect.top,
    x1: r.right - rootRect.left, y1: r.bottom - rootRect.top, r: r.height / 2 };
  S.cx = (S.pill.x0 + S.pill.x1) / 2; S.cy = (S.pill.y0 + S.pill.y1) / 2;
  const q = $('#switches').getBoundingClientRect(), margin = 12;
  S.obs = [
    { ...S.pill, x0: S.pill.x0 - 6, x1: S.pill.x1 + 6,
      y0: S.pill.y0 - 6, y1: S.pill.y1 + 6, r: S.pill.r + 6 },
    { x0: q.left - rootRect.left - margin, y0: q.top - rootRect.top - margin,
      x1: q.right - rootRect.left + margin, y1: q.bottom - rootRect.top + margin,
      r: Math.min(q.height / 2 + margin, 28) },
  ];
}
function retainedBubbles(live) {
  const retained = new Set(S.spot ? [S.spot] : []), kinds = new Set();
  const ordered = S.W < 600 ? [...live].sort((a, b) => Math.hypot(a.x - S.cx, a.y - S.cy) - Math.hypot(b.x - S.cx, b.y - S.cy)) : live;
  for (const b of ordered) {
    const key = b.p.dev ? 'dev' : b.p.tier;
    if ((b.p.tier > 1 || b.p.dev) && (S.W >= 600 || !kinds.has(key))) {
      kinds.add(key); retained.add(b);
    }
  }
  return retained;
}
function targetCount() {
  const reserved = S.obs.reduce((area, o) => area
    + Math.max(0, Math.min(S.W, o.x1) - Math.max(0, o.x0))
    * Math.max(0, Math.min(S.H, o.y1) - Math.max(0, o.y0)), 0);
  // Narrow windows need extra free area around the almost full-width search bar.
  const budget = Math.max(0, S.W * S.H - reserved) * (S.W < 600 ? .52 : .68);
  const live = bubbles.filter(b => !b.removing), retained = retainedBubbles(live);
  let count = 0, area = 0;
  const include = p => { const r = baseRadius(p, p.seed); area += Math.PI * r * r; count++; };
  for (const b of retained) include(b.p);
  // Budget actual avatar area, including the room needed for full nicknames.
  // A fixed count or guessed average radius leaves large windows mostly empty.
  for (const b of live) {
    if (area >= budget || count >= 760) break;
    if (!retained.has(b) && b.p.tier <= 1 && !b.p.dev) include(b.p);
  }
  for (let k = 0; area < budget && count < 760 && k < roster.length; k++) {
    const p = roster[(rosterCursor + k) % roster.length];
    if (!onScreen.has(p.id) && p.tier <= 1 && !p.dev) include(p);
  }
  return Math.min(roster.length, Math.max(S.W < 600 ? 18 : 36, count));
}
let rosterCursor = 0;
function nextCommon() {
  for (let k = 0; k < roster.length; k++) {
    const p = roster[(rosterCursor++) % roster.length];
    if (!onScreen.has(p.id) && p.tier <= 1 && !p.dev) return p;
  }
  return roster.find(p => !onScreen.has(p.id)) || null;
}
function freeSpot(r, occupied = bubbles) {
  let best = null, clearance = -Infinity;
  for (let k = 0; k < 40; k++) {
    const x = r + 4 + rand() * Math.max(0, S.W - 2 * r - 8);
    const y = r + 4 + rand() * Math.max(0, S.H - 2 * r - 8);
    if (insidePill(x, y, r + 10)) continue;
    let gap = Infinity;
    for (const b of occupied) {
      if (b.removing) continue;
      const dx = x - b.anchorX, dy = y - b.anchorY;
      gap = Math.min(gap, Math.sqrt(dx * dx + dy * dy) - b.r0);
      if (gap <= clearance) break;
    }
    if (gap > clearance) { clearance = gap; best = [x, y]; }
  }
  return best || [r + rand() * Math.max(0, S.W - 2 * r), r + rand() * Math.max(0, S.H - 2 * r)];
}
function insidePill(x, y, pad) {
  return S.obs.some((O) => {
    const qx = clamp(x, O.x0 + O.r, O.x1 - O.r), qy = clamp(y, O.y0 + O.r, O.y1 - O.r);
    return Math.hypot(x - qx, y - qy) < O.r + pad;
  });
}
function populate() {
  const featured = [];
  const take = (t, n) => byTier(t).slice(0, S.W < 600 ? 1 : n).forEach((p) => {
    if (!onScreen.has(p.id) && !featured.includes(p)) featured.push(p);
  });
  take(7, 3); take(6, 3); take(5, 3); take(4, 3); take(3, 4); take(2, 6); take('dev', 3); take('brand', 4);
  // deal them round-robin so neighbouring tiers never clump together
  const groups = new Map();
  featured.forEach((p) => { const k = p.dev ? 'd' : p.tier; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(p); });
  featured.length = 0;
  for (let more = true; more;) { more = false; for (const g of groups.values()) if (g.length) { featured.push(g.shift()); more = true; } }
  const ring = Math.max(S.pill.x1 - S.pill.x0, 200) * 0.62;
  featured.forEach((p, i) => {
    if (S.W < 600) { const [x, y] = freeSpot(baseRadius(p, p.seed)); makeBubble(p, x, y); return; }
    const a = (i / featured.length) * TAU + rand() * 0.3;
    const d = ring + rand() * 90 * S.scale;
    makeBubble(p, S.cx + Math.cos(a) * d, S.cy + Math.sin(a) * d * 0.62);
  });
  const N = targetCount();
  while (bubbles.length < N) { const p = nextCommon(); if (!p) break; const [x, y] = freeSpot(baseRadius(p, p.seed)); makeBubble(p, x, y); }
  bubbles.forEach((b) => { b.r = b.r0; b.born = Infinity; });
  S.warmupRemaining = 260;
  S.warmupTextureIndex = 0; S.warmupTextureCount = bubbles.length;
}
function preparingScene() {
  return S.warmupRemaining > 0 || S.warmupTextureIndex < S.warmupTextureCount;
}
function prepareBubbleTextures(b) {
  const R = Math.max(minimumNameRadius(b.p.name), Math.floor(b.r0 * 4) / 4);
  const key = b.p.name + ':' + R + ':false';
  b.nameKey = key; b.nameLayout = layoutName(b.p.name, R);
  cacheNickname(b, b.nameLayout, R, key, 1.8);
  buildSprite(b, b.r0 * 1.1, false);
}
function warmScene() {
  const deadline = performance.now() + 4;
  for (let steps = 0; steps < 12 && S.warmupRemaining; steps++) {
    physics(1 / 60, true);
    S.warmupRemaining--;
    if (performance.now() >= deadline) break;
  }
  if (S.warmupRemaining) return;
  for (let count = 0; count < 16 && S.warmupTextureIndex < S.warmupTextureCount; count++) {
    prepareBubbleTextures(bubbles[S.warmupTextureIndex++]);
    if (performance.now() >= deadline) break;
  }
  if (S.warmupTextureIndex < S.warmupTextureCount) return;
  // bloom in from the centre
  bubbles.forEach((b) => {
    b.r = 0.01; b.rv = 0;
    // Load portraits only when their bubble enters. A small decoded cache must
    // not evict hundreds of hidden portraits before their first presentation.
    b.dirty = true;
    b.born = b === S.spot ? 0 : S.now + 0.15 + Math.hypot(b.x - S.cx, b.y - S.cy) * 0.0016 + rand() * 0.12;
  });
}
function resize() {
  if (disposed) return;
  cardSize = null;
  const rootRect = root.getBoundingClientRect();
  const innerWidth = Math.max(1, rootRect.width), innerHeight = Math.max(1, rootRect.height);
  const reflow = S.W >= 600 && innerWidth < 600;
  if (S.W && S.H) {
    const sx = innerWidth / S.W, sy = innerHeight / S.H;
    for (const b of bubbles) {
      b.x *= sx; b.y *= sy; b.vx *= sx; b.vy *= sy;
      b.anchorX *= sx; b.anchorY *= sy;
      if (Number.isFinite(b.hx)) { b.hx *= sx; b.hy *= sy; }
    }
  }
  S.W = innerWidth; S.H = innerHeight;
  S.scale = clamp(Math.min(S.W, S.H * 1.25) / 1000, 0.72, 1.25);
  const nextDPR = window.devicePixelRatio || 1;
  if (DPR !== nextDPR) {
    DPR = nextDPR;
    for (const b of bubbles) { b.dirty = true; b.nameTextureKey = ''; }
  }
  S.pixelRatio = DPR;
  root.dataset.pixelRatio = String(DPR);
  canvas.width = Math.round(S.W * DPR); canvas.height = Math.round(S.H * DPR);
  // Retained CSS gradients rasterize at the display's native resolution.
  // Only their positions change during animation; no scaled background bitmap.
  for (const L of lights) {
    const r = Math.max(S.W, S.H) * L.r, x = S.W * (L.ox + .06), y = S.H * (L.oy + .06);
    L.node.style.backgroundImage = `radial-gradient(circle ${r}px at ${x}px ${y}px,rgba(${L.rgb},${L.a}),rgba(${L.rgb},0))`;
  }
  readPill();
  stars.length = 0;
  const n = Math.round((S.W * S.H) / 5200);
  for (let i = 0; i < n; i++) stars.push({ x: rand() * S.W, y: rand() * S.H, s: rand() < 0.08 ? 1.3 : 0.6 + rand() * 0.5, a: 0.15 + rand() * 0.5, f: 0.5 + rand() * 2, ph: rand() * TAU });
  if (!bubbles.length) return;
  bubbles.forEach((b) => { b.r0 = baseRadius(b.p, b.sizeSeed); if (preparingScene()) b.r = b.r0; });
  const N = targetCount();
  const live = bubbles.filter((b) => !b.removing);
  if (live.length < N) for (let i = live.length; i < N; i++) {
    const p = nextCommon(); if (!p) break;
    const [x, y] = freeSpot(baseRadius(p, p.seed)), b = makeBubble(p, x, y);
    // Fill the new gaps locally. Sending a whole new row in from an arbitrary
    // edge can strand it outside an already packed border for several seconds.
    b.hx = x; b.hy = y; b.state = 'gone'; b.respawnAt = S.now;
  }
  else if (live.length > N) {
    const retained = retainedBubbles(live);
    live.filter((b) => !retained.has(b))
      .sort((a, c) => Math.hypot(c.x - S.cx, c.y - S.cy) - Math.hypot(a.x - S.cx, a.y - S.cy))
      .slice(0, live.length - N).forEach((b) => { b.removing = true; });
  }
  if (reflow) {
    // The narrow layout has different UI obstacles. Reflow its retained bubbles
    // into usable space instead of compressing desktop anchors behind the UI.
    const placed = [];
    // Discard the old desktop occupants before the new compact layout collides.
    for (const b of bubbles) if (b.removing) { b.r = 0; b.dead = true; }
    for (const b of bubbles.filter(b => !b.removing).sort((a, c) => c.r0 - a.r0)) {
      [b.anchorX, b.anchorY] = freeSpot(b.r0, placed); placed.push(b);
      if (b !== S.spot && b.state === 'live' && !recovering(b)) {
        b.x = b.anchorX; b.y = b.anchorY; b.vx = b.vy = 0;
      }
    }
  }
}
function spawnFromEdge(p, ang) {
  const [anchorX, anchorY] = freeSpot(baseRadius(p, p.seed));
  const a = ang ?? rand() * TAU;
  const d = Math.hypot(S.W, S.H) * 0.62;
  const b = makeBubble(p, S.cx + Math.cos(a) * d, S.cy + Math.sin(a) * d);
  b.anchorX = anchorX; b.anchorY = anchorY;
  b.r = b.r0; b.entering = true;
  b.vx = -Math.cos(a) * 260; b.vy = -Math.sin(a) * 260;
  return b;
}

/* ───────────── physics ───────────── */
const collisionGrid = new Map(), collisionBuckets = [], collisionPairs = [];
const cellKey = (x, y) => ((x & 65535) << 16) | (y & 65535);
function collectContacts(live, cell, skin) {
  collisionGrid.clear(); collisionPairs.length = 0;
  for (const bucket of collisionBuckets) bucket.length = 0;
  let usedBuckets = 0;
  for (const b of live) {
    if (b.state !== 'live' || b.r < .5 && !b.seedRecovery) continue;
    b.contactX = b.x; b.contactY = b.y;
    const k = cellKey(Math.floor(b.x / cell), Math.floor(b.y / cell));
    let arr = collisionGrid.get(k);
    if (!arr) {
      arr = collisionBuckets[usedBuckets] || (collisionBuckets[usedBuckets] = []);
      usedBuckets++; collisionGrid.set(k, arr);
    }
    arr.push(b);
  }
  for (const a of live) {
    if (a.state !== 'live' || a.r < .5 && !a.seedRecovery) continue;
    // The larger circle owns each pair, so its local query covers both radii.
    const reach = a.contactRadius * 2 + 1.2 * S.scale + skin;
    const x0 = Math.floor((a.x - reach) / cell), x1 = Math.floor((a.x + reach) / cell);
    const y0 = Math.floor((a.y - reach) / cell), y1 = Math.floor((a.y + reach) / cell);
    for (let ix = x0; ix <= x1; ix++) for (let iy = y0; iy <= y1; iy++) {
      const arr = collisionGrid.get(cellKey(ix, iy)); if (!arr) continue;
      for (const c of arr) {
        if (c === a || c.contactRadius > a.contactRadius || c.contactRadius === a.contactRadius && c.p.id < a.p.id) continue;
        const dx = c.x - a.x, dy = c.y - a.y, reach = a.contactRadius + c.contactRadius + 1.2 * S.scale + skin;
        if (dx * dx + dy * dy < reach * reach) collisionPairs.push(a, c);
      }
    }
  }
}
function advanceRadius(b, dt) {
  const previous = b.r;
  if (recovering(b)) {
    if (b.recoverAge >= 0) {
      b.recoverAge += dt;
      const p = clamp(b.recoverAge / RECOVERY_DURATION, 0, 1);
      b.r = lerp(.01, b.rt, p * p * (3 - 2 * p));
    }
    b.rv = 0;
  } else {
    b.rv += ((b.rt - b.r) * 190 - b.rv * 17) * dt;
    b.r = Math.max(0, b.r + b.rv * dt);
    // A completed entrance may magnify, but hover return must not shrink below
    // the resting size that keeps the whole nickname readable. New arrivals,
    // swaps and removal still use their intentional small-radius transitions.
    if (previous >= b.r0 && b.rt >= b.r0 && b.r < b.r0) { b.r = b.r0; b.rv = 0; }
    if (Math.abs(b.rt - b.r) < .0001 && Math.abs(b.rv) < .001) { b.r = b.rt; b.rv = 0; }
  }
  b.radiusSpeed = (b.r - previous) / dt;
}
function physics(dt, warm = false) {
  const live = bubbles;
  const returnStrength = 0.5;
  const t = S.t;
  let activeRecovery = false;
  for (const b of live) {
    if (b.state !== 'live' || (b.born && S.now < b.born && !warm)) continue;
    if (!warm) advanceRadius(b, dt);
    const padding = padOf(b.p);
    b.fixed = recovering(b); b.seedRecovery = b.fixed && b.recoverAge < 0;
    activeRecovery ||= b.fixed;
    b.contactRadius = b.r * (1 + padding); b.wallRadius = b.r * (1 + padding * .5);
    b.inverseMass = b.fixed ? 0 : 1 / Math.max(1, b.r * b.r * (heavy(b) ? 14 : 1));
    b.contactGrowth = warm ? 0 : Math.max(0, b.radiusSpeed) * (1 + padding);
    if (b.fixed) { b.x = b.hx; b.y = b.hy; b.vx = b.vy = 0; continue; }
    let ax = 0, ay = 0;
    if (b === S.spot) {
      const [tx, ty] = spotSlot(b);
      ax += (tx - b.x) * 34 - b.vx * 9;
      ay += (ty - b.y) * 34 - b.vy * 9;
    } else {
      // Distributed anchors keep the entire rectangular viewport populated.
      // The springs stay soft so hovering, vacancies and returning bubbles can
      // still displace neighbours instead of locking them onto a grid.
      ax += (b.anchorX - b.x) * returnStrength;
      ay += (b.anchorY - b.y) * returnStrength;
      if (S.motion && !warm) {
        ax += wave(t * 0.21 + b.ph, b.ph * 3) * 26;
        ay += wave(t * 0.19 + b.ph * 1.7, b.ph) * 26;
      }
      for (const v of vacancies) {
        const age = S.now - v.t0; if (age > 1.6) continue;
        const dx = v.x - b.x, dy = v.y - b.y, d = Math.hypot(dx, dy) || 1;
        const reach = v.R * 5.5; if (d > reach) continue;
        const f = (1 - d / reach) * (1 - age / 1.6) * 900;
        ax += (dx / d) * f; ay += (dy / d) * f;
        if (dy > 0) ay += f * 0.65; // fall down into the gap
      }
    }
    b.vx += ax * dt; b.vy += ay * dt;
    const damp = Math.exp(-(b === S.spot ? 1 : 3.4) * dt);
    b.vx *= damp; b.vy *= damp;
    b.x += b.vx * dt; b.y += b.vy * dt;
  }
  // collisions via grid
  const cell = 64 * S.scale, skin = 8 * S.scale;
  let rebuild = true;
  for (let it = 0; it < (warm ? 3 : 16); it++) {
    let penetration = 0, coreOverlap = false;
    // A conservative neighbour list is reused while positions remain inside its
    // margin. Dense contacts get extra solver passes, not repeated grid searches.
    if (rebuild || warm) collectContacts(live, cell, skin);
    rebuild = false;
    for (let pair = 0; pair < collisionPairs.length; pair += 2) {
      const a = collisionPairs[pair], c = collisionPairs[pair + 1], mass = a.inverseMass + c.inverseMass;
      if (!mass) continue;
      const dx = c.x - a.x, dy = c.y - a.y, want = a.contactRadius + c.contactRadius + 1.2 * S.scale;
      const d2 = dx * dx + dy * dy;
      if (d2 >= want * want) continue;
      const d = Math.sqrt(d2), angle = (a.p.id * 1.618 + c.p.id) % TAU;
      if (a.r + c.r - d > .15) coreOverlap = true;
      const nx = d > .00001 ? dx / d : Math.cos(angle), ny = d > .00001 ? dy / d : Math.sin(angle), ov = want - d;
      const fa = a.inverseMass / mass, fc = 1 - fa;
      // Clear an occupied origin slowly while the seed is invisible, then let
      // the expanding solid surface pass its outward velocity to its neighbours.
      const seedContact = a.seedRecovery || c.seedRecovery;
      const correction = seedContact ? (it === 0 ? Math.min(ov, 75 * S.scale * dt) : 0) : ov * .9;
      if (!seedContact) penetration = Math.max(penetration, ov);
      a.x -= nx * correction * fa; a.y -= ny * correction * fa;
      c.x += nx * correction * fc; c.y += ny * correction * fc;
      const seedSpeed = seedContact ? Math.min(75 * S.scale, ov / dt) : 0;
      const rv = (c.vx - a.vx) * nx + (c.vy - a.vy) * ny - a.contactGrowth - c.contactGrowth - seedSpeed;
      if (rv < 0) { a.vx += nx * rv * fa * .9; a.vy += ny * rv * fa * .9; c.vx -= nx * rv * fc * .9; c.vy -= ny * rv * fc * .9; }
    }
    // walls + search pill
    for (const b of live) {
      if (b.state !== 'live' || b.fixed || b.r < .5) continue;
      const beforeX = b.x, beforeY = b.y;
      const R = b.wallRadius;
      if (!b.entering) {
        if (b.x < R + 4) { b.x = R + 4; b.vx = Math.abs(b.vx) * 0.3; }
        if (b.x > S.W - R - 4) { b.x = S.W - R - 4; b.vx = -Math.abs(b.vx) * 0.3; }
        if (b.y < R + 4) { b.y = R + 4; b.vy = Math.abs(b.vy) * 0.3; }
        if (b.y > S.H - R - 4) { b.y = S.H - R - 4; b.vy = -Math.abs(b.vy) * 0.3; }
      } else if (b.x > R && b.x < S.W - R && b.y > R && b.y < S.H - R) b.entering = false;
      if (b !== S.spot) for (const O of S.obs) {
        if (b.x + R + 2 < O.x0 || b.x - R - 2 > O.x1 || b.y + R + 2 < O.y0 || b.y - R - 2 > O.y1) continue;
        const qx = clamp(b.x, O.x0 + O.r, O.x1 - O.r), qy = clamp(b.y, O.y0 + O.r, O.y1 - O.r);
        let dx = b.x - qx, dy = b.y - qy, d = Math.hypot(dx, dy);
        if (d < 0.01) { dx = 0; dy = b.y < (O.y0 + O.y1) / 2 ? -1 : 1; d = 1; }
        const want = O.r + R + 2;
        if (d < want) { b.x = qx + (dx / d) * want; b.y = qy + (dy / d) * want; const vn = (b.vx * dx + b.vy * dy) / d; if (vn < 0) { b.vx -= vn * dx / d; b.vy -= vn * dy / d; } }
      }
      const wallShift = Math.max(Math.abs(b.x - beforeX), Math.abs(b.y - beforeY));
      penetration = Math.max(penetration, wallShift);
      if (wallShift > .15) coreOverlap = true;
      if (Math.abs(b.x - b.contactX) + Math.abs(b.y - b.contactY) > skin * .45) rebuild = true;
    }
    // Idle and hover motion can finish once solid cores are separated; recovery
    // gets the extra passes needed to transmit pressure through a crowded chain.
    if (!rebuild && (penetration < .03 || !warm && !activeRecovery && it >= 2 && !coreOverlap)) break;
  }
  for (const b of live) {
    if (b.state !== 'live' || !b.seedRecovery) continue;
    const clear = !live.some(c => c !== b && c.state === 'live'
      && Math.hypot(c.x - b.x, c.y - b.y) < c.r * (1 + padOf(c.p)) + b.r + 1.2 * S.scale - .02);
    if (clear) { b.recoverAge = 0; b.recoverUntil = S.now + RECOVERY_DURATION + .1; b.heavyUntil = S.now + RECOVERY_DURATION + .25; }
  }
}
const heavy = (b) => b === S.spot || S.now < b.heavyUntil;
const recovering = (b) => b.state === 'live' && S.now < b.recoverUntil;
function spotR() { return clamp(Math.min(S.W, S.H) * 0.105, 54, 96); }
function spotSlot() {
  const R = spotR();
  let y = S.pill.y0 - R * 1.25 - 26;
  if (y - R * 1.4 < 130) y = S.pill.y1 + R * 1.25 + 46;
  return [S.cx, y];
}

/* ───────────── per-frame state ───────────── */
function hitTest(x, y) {
  if (preparingScene()) return null;
  let best = null, bd = 1e9;
  for (const b of bubbles) {
    if (b.state !== 'live' || b.r < 4) continue;
    const d = Math.hypot(b.x - x, b.y - y);
    if (d < b.r && d < bd) { bd = d; best = b; }
  }
  return best;
}
let swapTimer = 0;
function update(dt) {
  if (preparingScene()) { warmScene(); return; }
  const ptr = S.ptr;
  S.hover = ptr.inside && ptr.mouse ? hitTest(ptr.x, ptr.y) : null;
  canvas.classList.toggle('pointing', !!S.hover);

  for (const b of bubbles) {
    // respawn
    if (b.state === 'gone' && S.now >= b.respawnAt) {
      // Overlapping birth sites take turns; two fixed centres cannot both expand
      // through one another. Distant bubbles can still restore concurrently.
      if (bubbles.some(c => c !== b && recovering(c) && Math.hypot(b.hx - c.hx, b.hy - c.hy)
        < b.r0 * (1 + padOf(b.p)) + c.r0 * (1 + padOf(c.p)) + 1.2 * S.scale)) continue;
      b.state = 'live'; b.x = b.hx; b.y = b.hy; b.vx = b.vy = 0; b.r = 0.01; b.rv = 0;
      b.heavyUntil = S.now + 1.1; b.born = 0;
      b.recoverAge = -1; b.recoverUntil = Infinity;
      bursts.push({ k: 'gather', x: b.x, y: b.y, R: b.r0, rgb: (S.fx ? styleOf(b.p) : TIERS[0]).rgb, t0: S.now, life: 0.42 });
    }
    if (b.state !== 'live') continue;
    if (b.born && S.now < b.born) continue;
    // target radius: magnify near cursor, spotlight size, swap shrink
    let rt = b.r0;
    if (b === S.spot) rt = spotR();
    else if (!recovering(b) && ptr.inside && ptr.mouse) {
      const d = Math.hypot(b.x - ptr.x, b.y - ptr.y), reach = 150 * S.scale;
      if (d < reach) {
        const f = 1 - d / reach, p = b.recoverUntil ? clamp((S.now - b.recoverUntil) / .65, 0, 1) : 1;
        rt = b.r0 * (1 + .62 * f * f * p * p * (3 - 2 * p));
      }
    }
    if (b.removing) rt = 0;
    b.rt = rt;
    if (b.removing && b.r < 0.6) b.dead = true;
    // swap fade
    if (b.swap) {
      b.swap.t += dt;
      if (b.swap.phase === 'out') {
        b.vis = Math.max(0, 1 - b.swap.t / 0.55);
        if (b.vis <= 0) {
          onScreen.delete(b.p.id); b.p = b.swap.next; onScreen.add(b.p.id);
          b.sizeSeed = b.p.seed; b.r0 = baseRadius(b.p, b.sizeSeed); b.r = b.r0 * 0.55; b.dirty = true;
          b.swap = { phase: 'in', t: 0 };
        }
      } else { b.vis = Math.min(1, b.swap.t / 0.6); if (b.vis >= 1) b.swap = null; }
    }
    const bw = b === S.hover || b === S.spot ? 1 : 0;
    b.boost = lerp(b.boost, bw, 1 - Math.exp(-dt * 6));
  }
  for (let i = bubbles.length - 1; i >= 0; i--) if (bubbles[i].dead) { onScreen.delete(bubbles[i].p.id); releaseBubble(bubbles[i]); bubbles.splice(i, 1); }
  for (let i = vacancies.length - 1; i >= 0; i--) if (S.now - vacancies[i].t0 > 1.6) vacancies.splice(i, 1);

  // ambient renewal: a stranger drifts in every few seconds
  if (S.motion) {
    swapTimer += dt;
    if (swapTimer > 3.2) {
      swapTimer = 0;
      const cand = bubbles.filter((b) => b.state === 'live' && !b.swap && b !== S.spot && b !== S.hover && b.p.tier <= 1 && !b.p.dev
        && Math.hypot(b.x - S.ptr.x, b.y - S.ptr.y) > 200);
      const b = cand[(rand() * cand.length) | 0];
      const next = nextCommon();
      if (b && next) b.swap = { phase: 'out', t: 0, next };
    }
  }

  const sub = Math.max(1, Math.ceil(dt * 120));
  for (let i = 0; i < sub; i++) physics(dt / sub);
  for (const b of bubbles) {
    if (b.state === 'live' && !(b.born && S.now < b.born) && (b.r > b.sR * 1.04 || b.dirty && b.r > 2))
      buildSprite(b, Math.max(b.r, b.r0) * 1.1);
  }
  updateCard();
}

/* ───────────── rendering ───────────── */
const rgba = (rgb, a) => `rgba(${rgb},${a})`;
function halo(x, y, R, i0, i1, rgb, a) {
  if (a <= 0.002) return;
  const g = ctx.createRadialGradient(x, y, R * i0, x, y, R * i1);
  g.addColorStop(0, rgba(rgb, a)); g.addColorStop(0.45, rgba(rgb, a * 0.35)); g.addColorStop(1, rgba(rgb, 0));
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, R * i1, 0, TAU); ctx.fill();
}
function star(x, y, s, rgb, a) {
  if (s < 0.6 || a <= 0.01) return;
  ctx.fillStyle = rgba(rgb, a);
  ctx.beginPath();
  ctx.moveTo(x - s, y); ctx.quadraticCurveTo(x, y, x, y - s); ctx.quadraticCurveTo(x, y, x + s, y);
  ctx.quadraticCurveTo(x, y, x, y + s); ctx.quadraticCurveTo(x, y, x - s, y); ctx.fill();
  halo(x, y, s, 0, 0.5, rgb, a * 0.6);
}
function ringStroke(x, y, rad, w, style) {
  ctx.lineWidth = w; ctx.strokeStyle = style;
  ctx.beginPath(); ctx.arc(x, y, rad, 0, TAU); ctx.stroke();
}
function polyline(pts, x, y, R) {
  ctx.beginPath();
  pts.forEach(([px, py], i) => (i ? ctx.lineTo(x + px * R, y + py * R) : ctx.moveTo(x + px * R, y + py * R)));
}

function genBolts(b) {
  const out = [];
  const n = 2 + (b.boost > 0.4 ? 2 : 0) + (rand() < 0.4 ? 1 : 0);
  for (let i = 0; i < n; i++) {
    const s = rand() * TAU, span = 0.6 + rand() * 1.2, segs = 11, pts = [];
    for (let j = 0; j <= segs; j++) {
      const a = s + (span * j) / segs, edge = j === 0 || j === segs;
      const rr = 1.03 + (rand() - 0.5) * (edge ? 0.02 : 0.17);
      pts.push([Math.cos(a) * rr, Math.sin(a) * rr]);
    }
    out.push({ pts, w: 1 });
    if (rand() < 0.65) {
      const m = 3 + ((rand() * 5) | 0), a = s + (span * m) / segs, bp = [pts[m]], len = 0.25 + rand() * 0.4;
      for (let j = 1; j <= 4; j++) { const aa = a + (rand() - 0.5) * 0.35; const rr = 1.03 + (len * j) / 4; bp.push([Math.cos(aa) * rr, Math.sin(aa) * rr]); }
      out.push({ pts: bp, w: 0.6 });
    }
  }
  if (rand() < 0.1 + b.boost * 0.35) {
    const a = rand() * TAU, len = 0.7 + rand() * 0.6, bp = [];
    for (let j = 0; j <= 8; j++) { const aa = a + (rand() - 0.5) * 0.3 * (j ? 1 : 0); const rr = 1 + (len * j) / 8; bp.push([Math.cos(aa) * rr, Math.sin(aa) * rr]); }
    out.push({ pts: bp, w: 1.2 });
    b.flash = 1;
  }
  return out;
}

const FX = {
  1: {
    under(b, x, y, R, t, k) { halo(x, y, R, 0.9, 1.55, '220,230,255', 0.07 + 0.08 * k); },
    over(b, x, y, R, t, k) {
      const ang = t * 0.85 + b.ph;
      ringStroke(x, y, R * 0.965, R * 0.075, conic(ctx, ang, x, y, [[0, 'rgba(255,255,255,0)'], [0.045, 'rgba(255,255,255,.95)'], [0.1, 'rgba(255,255,255,0)'], [0.5, 'rgba(255,255,255,0)'], [0.54, 'rgba(225,235,255,.55)'], [0.58, 'rgba(255,255,255,0)'], [1, 'rgba(255,255,255,0)']]));
      const cyc = (t * 0.32 + b.ph) % 1, s = Math.pow(Math.max(0, Math.sin(cyc * TAU)), 8);
      const sa = ang + 0.28;
      star(x + Math.cos(sa) * R, y + Math.sin(sa) * R, R * (0.38 + 0.25 * k) * s, '255,255,255', s);
    },
  },
  2: {
    under(b, x, y, R, t, k) { halo(x, y, R, 0.85, 1.85, '255,185,80', 0.15 + 0.05 * Math.sin(t * 1.6 + b.ph) + 0.12 * k); },
    over(b, x, y, R, t, k) {
      const ang = t * 1.2 + b.ph;
      ringStroke(x, y, R * 0.957, R * 0.09, conic(ctx, ang, x, y, [[0, 'rgba(255,250,220,0)'], [0.05, 'rgba(255,248,215,.95)'], [0.13, 'rgba(255,210,120,0)'], [0.5, 'rgba(255,250,220,0)'], [0.55, 'rgba(255,240,200,.8)'], [0.62, 'rgba(255,210,120,0)'], [1, 'rgba(255,250,220,0)']]));
      for (const m of b.motes) {
        const a = m.a + t * m.s * (1 + k), d = R * (m.d + 0.05 * Math.sin(t * 0.8 + m.ph));
        const tw = 0.3 + 0.7 * Math.pow(Math.max(0, Math.sin(t * 2.4 + m.ph)), 3);
        const px = x + Math.cos(a) * d, py = y + Math.sin(a) * d;
        halo(px, py, m.sz * 3.2, 0, 1, '255,205,110', 0.5 * tw);
        ctx.fillStyle = `rgba(255,244,210,${0.9 * tw})`; ctx.beginPath(); ctx.arc(px, py, m.sz * 0.7, 0, TAU); ctx.fill();
        if (tw > 0.85) star(px, py, m.sz * 4, '255,240,200', (tw - 0.85) * 5);
      }
    },
  },
  3: {
    under(b, x, y, R, t, k) {
      halo(x, y, R, 0.9, 1.7, '190,215,255', 0.1 + 0.08 * k);
      const n = 6;
      for (let i = 0; i < n; i++) {
        const a = (i / n) * TAU + t * 0.14 + b.ph, hue = (i * 60 + t * 40) % 360;
        const len = R * (1.9 + 0.35 * Math.sin(t * 0.9 + i * 1.3) + 0.4 * k), w = R * 0.17;
        const ca = Math.cos(a), sa = Math.sin(a), px = -sa, py = ca;
        const bx = x + ca * R * 0.95, by = y + sa * R * 0.95;
        const g = ctx.createLinearGradient(bx, by, x + ca * len, y + sa * len);
        g.addColorStop(0, `hsla(${hue},100%,72%,${0.34 + 0.2 * k})`); g.addColorStop(1, `hsla(${hue},100%,70%,0)`);
        ctx.fillStyle = g; ctx.beginPath();
        ctx.moveTo(bx + px * w, by + py * w); ctx.lineTo(x + ca * len, y + sa * len); ctx.lineTo(bx - px * w, by - py * w); ctx.closePath(); ctx.fill();
      }
    },
    over(b, x, y, R, t, k) {
      const rot = t * 0.9 + b.ph;
      const stops = []; for (let i = 0; i <= 12; i++) stops.push([i / 12, `hsla(${(i * 30) % 360},100%,68%,.92)`]);
      ringStroke(x, y, R * 0.96, R * (0.08 + 0.02 * k), conic(ctx, rot, x, y, stops));
      ringStroke(x, y, R * 0.96, R * 0.05, conic(ctx, -rot * 1.3, x, y, [[0, 'rgba(255,255,255,0)'], [0.04, 'rgba(255,255,255,.9)'], [0.09, 'rgba(255,255,255,0)'], [1, 'rgba(255,255,255,0)']]));
    },
  },
  4: {
    under(b, x, y, R, t, k) {
      b.flash *= 0.86;
      halo(x, y, R, 0.85, 1.8 + b.flash * 0.6, '80,170,255', 0.14 + 0.05 * Math.sin(t * 7 + b.ph) + 0.12 * k + 0.3 * b.flash);
    },
    over(b, x, y, R, t, k) {
      if (!b.bolts || S.now - b.boltT > 0.06 + rand() * 0.06) { b.bolts = genBolts(b); b.boltT = S.now; }
      ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      for (const bolt of b.bolts) {
        polyline(bolt.pts, x, y, R);
        ctx.strokeStyle = 'rgba(70,160,255,.16)'; ctx.lineWidth = 7 * bolt.w; ctx.stroke();
        ctx.strokeStyle = 'rgba(120,210,255,.45)'; ctx.lineWidth = 3 * bolt.w; ctx.stroke();
        ctx.strokeStyle = 'rgba(240,252,255,.95)'; ctx.lineWidth = 1.1 * bolt.w; ctx.stroke();
      }
    },
  },
  5: {
    under(b, x, y, R, t, k) {
      halo(x, y, R, 0.9, 1.9, '60,240,190', 0.1 + 0.1 * k);
      // curtains: radial streaks whose length follows a slow travelling wave
      const hues = [[56, 255, 180], [54, 212, 255], [138, 107, 255], [255, 95, 210]];
      const n = 72;
      ctx.lineCap = 'round';
      for (let i = 0; i < n; i++) {
        const th = (i / n) * TAU + b.ph;
        const w1 = Math.sin(3 * th + t * 0.9) * 0.5 + 0.5, w2 = Math.sin(2 * th - t * 0.6 + 1.7) * 0.5 + 0.5;
        const e = Math.pow(w1 * 0.65 + w2 * 0.35, 2.2);
        if (e < 0.06) continue;
        const r0 = R * (1.04 + 0.05 * w2), r1 = R * (1.2 + 0.55 * e + 0.2 * k);
        const c = hues[Math.floor(((th / TAU) * 4 + t * 0.15) % 4 + 4) % 4];
        const cx0 = x + Math.cos(th) * r0, cy0 = y + Math.sin(th) * r0, cx1 = x + Math.cos(th) * r1, cy1 = y + Math.sin(th) * r1;
        const g = ctx.createLinearGradient(cx0, cy0, cx1, cy1);
        g.addColorStop(0, `rgba(${c},${0.55 * e})`); g.addColorStop(0.35, `rgba(${c},${0.28 * e})`); g.addColorStop(1, `rgba(${c},0)`);
        ctx.strokeStyle = g; ctx.lineWidth = R * 0.09;
        ctx.beginPath(); ctx.moveTo(cx0, cy0); ctx.lineTo(cx1, cy1); ctx.stroke();
      }
    },
    over(b, x, y, R, t, k) {
      const rot = t * 0.7 + b.ph;
      ringStroke(x, y, R * 0.965, R * 0.06, conic(ctx, rot, x, y, even(['rgba(56,255,180,.9)', 'rgba(54,212,255,.2)', 'rgba(138,107,255,.9)', 'rgba(255,95,210,.2)', 'rgba(56,255,180,.9)'])));
    },
  },
  6: {
    under(b, x, y, R, t, k) {
      halo(x, y, R, 0.8, 2.3 + 0.3 * k, '255,120,40', 0.28 + 0.15 * k);
      const n = 46, len0 = R * (0.98);
      ctx.beginPath();
      for (let i = 0; i < n; i++) {
        const a = (i / n) * TAU + t * 0.06 + b.ph;
        const len = R * (0.2 + 0.62 * Math.pow((wave(t * 0.9 + i * 7.3, i) + 1) / 2, 2) + 0.25 * k);
        const w = (TAU / n) * 0.42;
        ctx.moveTo(x + Math.cos(a - w) * len0, y + Math.sin(a - w) * len0);
        ctx.lineTo(x + Math.cos(a) * (R + len), y + Math.sin(a) * (R + len));
        ctx.lineTo(x + Math.cos(a + w) * len0, y + Math.sin(a + w) * len0);
      }
      const g = ctx.createRadialGradient(x, y, R * 0.95, x, y, R * 2.0);
      g.addColorStop(0, 'rgba(255,236,170,.75)'); g.addColorStop(0.35, 'rgba(255,150,50,.4)'); g.addColorStop(1, 'rgba(255,80,20,0)');
      ctx.fillStyle = g; ctx.fill();
      // prominence loop
      const pa = t * 0.25 + b.ph, pulse = 0.5 + 0.5 * Math.sin(t * 1.3 + b.ph);
      ctx.beginPath();
      ctx.moveTo(x + Math.cos(pa) * R, y + Math.sin(pa) * R);
      ctx.quadraticCurveTo(x + Math.cos(pa + 0.3) * R * (1.7 + 0.2 * pulse), y + Math.sin(pa + 0.3) * R * (1.7 + 0.2 * pulse), x + Math.cos(pa + 0.6) * R, y + Math.sin(pa + 0.6) * R);
      ctx.strokeStyle = `rgba(255,170,80,${0.35 + 0.3 * pulse})`; ctx.lineWidth = 2.2; ctx.stroke();
    },
    over(b, x, y, R, t, k) {
      ringStroke(x, y, R * 0.97, R * 0.06, conic(ctx, t * 0.5, x, y, even(['rgba(255,250,220,.95)', 'rgba(255,170,60,.5)', 'rgba(255,240,190,.95)', 'rgba(255,120,40,.5)', 'rgba(255,250,220,.95)'])));
      for (const e of b.embers) {
        const age = ((t * (1 + k) + e.o) % e.L) / e.L;
        const sx = x + Math.cos(e.a) * R, sy = y + Math.sin(e.a) * R;
        const px = sx + Math.sin(t * 2 + e.sw) * R * 0.12 * age + Math.cos(e.a) * R * 0.25 * age;
        const py = sy - age * R * 1.1;
        const a = Math.sin(age * Math.PI) * 0.9;
        halo(px, py, e.sz * 3, 0, 1, '255,140,50', a * 0.6);
        ctx.fillStyle = `rgba(255,${(230 - age * 120) | 0},${(160 - age * 140) | 0},${a})`;
        ctx.beginPath(); ctx.arc(px, py, e.sz * (1 - age * 0.5), 0, TAU); ctx.fill();
      }
    },
  },
  7: {
    under(b, x, y, R, t, k) {
      const clouds = [['130,80,255', 0.3], ['60,120,255', 0.22], ['255,80,200', 0.16]];
      clouds.forEach(([c, a], i) => {
        const ang = t * 0.18 + i * 2.1 + b.ph;
        halo(x + Math.cos(ang) * R * 0.45, y + Math.sin(ang) * R * 0.3, R, 0.2, 2.1 + 0.4 * k, c, a + 0.1 * k);
      });
      this.disk(b, x, y, R, t, k, false);
    },
    over(b, x, y, R, t, k) {
      ringStroke(x, y, R * 1.02, 1.4, conic(ctx, t * 0.6, x, y, even(['rgba(235,225,255,.95)', 'rgba(150,110,255,.3)', 'rgba(120,220,255,.9)', 'rgba(150,110,255,.3)', 'rgba(235,225,255,.95)'])));
      this.disk(b, x, y, R, t, k, true);
    },
    disk(b, x, y, R, t, k, front) {
      const tilt = -0.36 + Math.sin(t * 0.1 + b.ph) * 0.08, ct = Math.cos(tilt), st = Math.sin(tilt), flat = 0.3;
      for (const q of b.disk) {
        const a = q.a + t * q.sp * (1.6 + 1.4 * k) / Math.pow(q.rr, 1.5);
        const sa = Math.sin(a);
        if ((sa > 0) !== front) continue;
        const lx = Math.cos(a) * q.rr * R, ly = sa * q.rr * R * flat;
        const px = x + lx * ct - ly * st, py = y + lx * st + ly * ct;
        const al = q.br * (front ? 1 : 0.55) * (0.6 + 0.4 * k);
        ctx.fillStyle = q.col + al + ')';
        const s = q.sz * (front ? 1.5 : 1.0) * (R / 40);
        ctx.beginPath(); ctx.arc(px, py, s, 0, TAU); ctx.fill();
      }
      // the glowing band itself, drawn as nested elliptical strokes
      ctx.save(); ctx.translate(x, y); ctx.rotate(tilt); ctx.scale(1, flat);
      const a0 = front ? 0 : Math.PI, a1 = front ? Math.PI : TAU;
      const bands = [[1.32, 0.5, 'rgba(120,90,255,A)'], [1.5, 0.34, 'rgba(170,120,255,A)'], [1.72, 0.22, 'rgba(90,200,255,A)']];
      for (const [rr, w, col] of bands) {
        const al = (front ? 0.22 : 0.14) * (1 + 0.6 * k);
        ctx.beginPath(); ctx.arc(0, 0, R * rr, a0, a1);
        ctx.strokeStyle = col.replace('A', al); ctx.lineWidth = R * w; ctx.stroke();
      }
      ctx.beginPath(); ctx.arc(0, 0, R * 1.24, a0, a1);
      ctx.strokeStyle = `rgba(235,225,255,${front ? 0.75 : 0.4})`; ctx.lineWidth = 1.6 / flat * 0.5; ctx.stroke();
      ctx.restore();
    },
  },
};
const FX_DEV = {
  over(b, x, y, R, t, k) {
    ctx.lineWidth = 1; ctx.strokeStyle = 'rgba(120,170,255,.22)';
    ctx.beginPath(); ctx.arc(x, y, R * 1.16, 0, TAU); ctx.stroke();
    for (let i = 0; i < 3; i++) {
      const a = t * (0.7 + k) + b.ph + (i * TAU) / 3;
      const px = x + Math.cos(a) * R * 1.16, py = y + Math.sin(a) * R * 1.16;
      ctx.lineWidth = 1.6; ctx.strokeStyle = 'rgba(120,180,255,.6)';
      ctx.beginPath(); ctx.arc(x, y, R * 1.16, a - 0.45, a); ctx.stroke();
      halo(px, py, 6, 0, 1, '110,170,255', 0.8);
      ctx.fillStyle = '#e6f0ff'; ctx.beginPath(); ctx.arc(px, py, 1.6, 0, TAU); ctx.fill();
    }
  },
};

function drawBackground(t) {
  for (const L of lights) {
    const x = S.W * .06 * Math.sin(t * L.sp * 6 + L.ph), y = S.H * .06 * Math.cos(t * L.sp * 5 + L.ph);
    const transform = `translate3d(${x}px,${y}px,0)`;
    if (L.node.style.transform !== transform) L.node.style.transform = transform;
  }
  ctx.globalCompositeOperation = 'lighter';
  for (const s of stars) {
    const a = s.a * (0.55 + 0.45 * Math.sin(t * s.f + s.ph));
    ctx.fillStyle = `rgba(210,220,255,${a})`;
    ctx.fillRect(s.x, s.y, s.s, s.s);
  }
  ctx.globalCompositeOperation = 'source-over';
}

function drawBubble(b) {
  const R = b.r, s = R / b.sR, h = b.sHalf * s;
  ctx.globalAlpha = b.alpha * b.vis;
  ctx.drawImage(b.sprite, b.x - h, b.y - h, h * 2, h * 2);
  ctx.globalAlpha = 1;
}
const nameLights = [null,
  ['#c5d5ed', '#eef6ff'], ['#ffcd72', '#fff2ca'], ['#b9e9ff', '#ffc4ec'],
  ['#76cfff', '#c4f5ff'], ['#7ef4d4', '#c8b8ff'], ['#ffb46a', '#fff0b1'],
  ['#bd9dff', '#99e7ff'],
];
function nicknameLight(b, R) {
  if (!S.fx) return TIERS[0].text;
  const st = styleOf(b.p);
  if (!b.p.tier && !b.p.dev) return st.text;
  const colors = b.p.tier ? nameLights[b.p.tier] : ['#99c2ff', '#ddf0ff'];
  const phase = (S.t / (5.2 - b.p.tier * .28) + b.p.seed) % 1;
  const x = lerp(-R * 2.2, R * 2.2, phase), width = R * .64;
  const light = ctx.createLinearGradient(x - width, -R * .45, x + width, R * .45);
  light.addColorStop(0, st.text); light.addColorStop(.22, colors[0]);
  light.addColorStop(.47, '#ffffff'); light.addColorStop(.55, '#ffffff');
  light.addColorStop(.76, colors[1]); light.addColorStop(1, st.text);
  return light;
}
function drawNicknameGlints(b, L) {
  if (!S.fx || b.p.tier < 3) return;
  ctx.save(); ctx.globalCompositeOperation = 'lighter';
  const count = b.p.tier === 7 ? 2 : 1;
  for (let i = 0; i < count; i++) {
    const line = L.lines[i % L.lines.length];
    if (!line) continue;
    const phase = (S.t / (4.6 - b.p.tier * .2) + b.p.seed + i * .43) % 1;
    const a = lerp(-line.halfAngle, line.halfAngle, phase), dir = line.top ? 1 : -1;
    const x = Math.sin(a) * line.rr + Math.sin(dir * a) * L.fs * .48;
    const y = line.y + dir * (1 - Math.cos(a)) * line.rr - Math.cos(a) * L.fs * .48;
    const alpha = Math.sin(phase * Math.PI) ** 6 * .85;
    star(x, y, 1.2 + b.p.tier * .14, '235,246,255', alpha);
  }
  ctx.restore();
}
function drawNicknameScrim(g, L, R) {
  g.beginPath(); g.arc(0, 0, R - .4, 0, TAU); g.clip();
  for (const line of L.lines) {
    const end = line.top ? -R : R;
    const shade = g.createLinearGradient(0, end * .08, 0, end);
    shade.addColorStop(0, 'rgba(5,7,16,0)'); shade.addColorStop(.5, 'rgba(5,7,16,.42)'); shade.addColorStop(1, 'rgba(5,7,16,.86)');
    g.fillStyle = shade; g.fillRect(-R, Math.min(end * .08, end), R * 2, Math.abs(end * .92));
  }
}
function cacheNickname(b, L, R, key, zoom = 1) {
  const half = Math.ceil((R + 2) * DPR) / DPR;
  const paint = (density) => {
    const c = document.createElement('canvas');
    c.width = c.height = Math.ceil(half * 2 * density);
    const g = c.getContext('2d'), pixelScale = c.width / (half * 2);
    g.setTransform(pixelScale, 0, 0, pixelScale, c.width / 2, c.height / 2);
    g.save();
    drawNicknameScrim(g, L, R);
    drawArcText(g, L, TIERS[0].text, pixelScale / DPR);
    g.restore();
    return c;
  };
  // Keep an exact native-size surface for rest and a higher-resolution surface
  // for magnification. Both remain immutable throughout ordinary hover motion.
  releaseSurface(b.nameTexture); releaseSurface(b.nameZoomTexture);
  b.nameTexture = paint(DPR);
  b.nameZoomTexture = zoom > 1 ? paint(DPR * zoom) : null;
  b.nameZoomScale = zoom;
  b.nameHalf = half; b.nameTextureKey = key;
}
function drawNickname(b) {
  const minimum = minimumNameRadius(b.p.name);
  if (b.r < minimum - .05) return;
  // A search result gets the full responsive layout, including its return.
  // Ordinary hover scales a stable layout instead of rewrapping all neighbours
  // at every quarter-pixel change in their spring radius.
  if (b === S.spot) b.nameSearch = true;
  else if (b.nameSearch && Math.abs(b.r - b.rt) < .01 && Math.abs(b.rv) < .05) b.nameSearch = false;
  const R = Math.max(minimum, Math.floor((b.nameSearch ? b.r : b.r0) * 4) / 4);
  const key = b.p.name + ':' + R + ':' + !!b.nameSearch;
  if (key !== b.nameKey) { b.nameKey = key; b.nameLayout = layoutName(b.p.name, R); }
  const L = b.nameLayout;
  const scale = b.nameSearch ? 1 : Math.max(11 / L.fs, b.r / b.r0);
  const cached = !S.fx || (!b.p.tier && !b.p.dev);
  let texture;
  if (cached) {
    const zoom = b.nameSearch ? 1 : Math.max(1.8, scale);
    if (b.nameTextureKey !== key || b.nameZoomScale < zoom) cacheNickname(b, L, R, key, zoom);
    texture = Math.abs(scale - 1) < .00001 || !b.nameZoomTexture ? b.nameTexture : b.nameZoomTexture;
    // A complete cached name is already contained in its circular avatar.
    // Draw in screen coordinates without saving/restoring hundreds of canvas
    // states. Entrances still take the clipped path below.
    if (R * scale <= b.r) {
      const h = b.nameHalf * scale;
      ctx.globalAlpha = b.alpha * b.vis * clamp((b.r / b.r0 - .8) / .2, 0, 1);
      ctx.drawImage(texture, b.x - h, b.y - h, h * 2, h * 2);
      ctx.globalAlpha = 1;
      return;
    }
  }
  ctx.save(); ctx.translate(b.x, b.y);
  ctx.globalAlpha = b.alpha * b.vis * clamp((b.r / b.r0 - .8) / .2, 0, 1);
  // During the entrance, reveal full-size type through the expanding circle;
  // never shrink lettering below 11 CSS px or let it escape the avatar.
  if (R * scale > b.r) { ctx.beginPath(); ctx.arc(0, 0, b.r, 0, TAU); ctx.clip(); }
  ctx.scale(scale, scale);
  if (cached) {
    const h = b.nameHalf;
    ctx.drawImage(texture, -h, -h, h * 2, h * 2);
  } else {
    drawNicknameScrim(ctx, L, R);
    drawArcText(ctx, L, nicknameLight(b, R), scale);
    drawNicknameGlints(b, L);
  }
  ctx.restore();
}
function fxOf(b) { return b.p.dev && b.p.tier === 0 ? null : FX[b.p.tier]; }

function render() {
  const t = S.t;
  ctx.setTransform(S.pixelRatio, 0, 0, S.pixelRatio, 0, 0);
  ctx.clearRect(0, 0, S.W, S.H);
  drawBackground(t);
  if (preparingScene()) { root.dataset.visibleCount = '0'; return; }

  // spotlight glow
  if (S.spot && S.spot.state === 'live') {
    const b = S.spot;
    ctx.globalCompositeOperation = 'lighter';
    halo(b.x, b.y, b.r, 0.6, 3.0, '150,175,255', 0.2);
    const age = S.now - S.spotT;
    for (let i = 0; i < 2; i++) {
      const p = ((age * 0.55 + i * 0.5) % 1);
      ctx.lineWidth = 1.2; ctx.strokeStyle = `rgba(190,205,255,${0.35 * (1 - p)})`;
      ctx.beginPath(); ctx.arc(b.x, b.y, b.r * (1.15 + p * 1.1), 0, TAU); ctx.stroke();
    }
    ctx.globalCompositeOperation = 'source-over';
  }

  const order = bubbles.filter((b) => b.state === 'live' && b.r > 0.5 && b.sprite)
    .sort((a, c) => (a === S.spot) - (c === S.spot) || (a === S.hover) - (c === S.hover) || a.p.tier + a.p.dev * 0.5 - c.p.tier - c.p.dev * 0.5);
  const count = String(order.length);
  if (root.dataset.visibleCount !== count) root.dataset.visibleCount = count;

  for (const b of order) {
    const fx = S.fx ? fxOf(b) : null, dev = S.fx && b.p.dev;
    if (fx && fx.under || dev || !fx && b.boost > .02) {
      ctx.globalCompositeOperation = 'lighter';
      ctx.globalAlpha = b.alpha * b.vis;
      if (fx && fx.under) fx.under(b, b.x, b.y, b.r, t + b.ph * 10, b.boost);
      else if (dev) halo(b.x, b.y, b.r, 0.9, 1.6, '90,150,255', 0.12 + 0.12 * b.boost);
      else halo(b.x, b.y, b.r, 0.9, 1.5, '200,215,255', 0.14 * b.boost);
      ctx.globalCompositeOperation = 'source-over';
    }
    drawBubble(b);
    if (fx && fx.over || dev) {
      ctx.globalCompositeOperation = 'lighter';
      ctx.globalAlpha = b.alpha * b.vis;
      if (fx && fx.over) fx.over(b, b.x, b.y, b.r, t + b.ph * 10, b.boost);
      if (dev) FX_DEV.over(b, b.x, b.y, b.r, t, b.boost);
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = 'source-over';
    }
  }
  // Keep names readable above neighbouring light effects without scaling their glyphs.
  for (const b of order) drawNickname(b);
  drawBursts();
}

/* ───────────── pop & respawn ───────────── */
function pop(b, px, py) {
  if (b.state !== 'live' || b.r < b.r0 * 0.5) return;
  const st = S.fx ? styleOf(b.p) : TIERS[0], x = b.x, y = b.y, R = b.r, tier = S.fx ? b.p.tier : 0;
  bursts.push({ k: 'remnant', sprite: b.sprite, half: b.sHalf, sR: b.sR, x, y, R, t0: S.now, life: 0.14 });
  bursts.push({ k: 'ring', x, y, R, rgb: st.rgb, t0: S.now, life: 0.55 });
  bursts.push({ k: 'flash', x: px ?? x, y: py ?? y, R, t0: S.now, life: 0.2 });
  const hit = Math.atan2((py ?? y) - y, (px ?? x) - x);
  const shards = 9 + tier;
  for (let i = 0; i < shards; i++) {
    const a = hit + Math.PI + ((i + rand() * 0.6) / shards) * TAU;
    bursts.push({ k: 'shard', x, y, a, R, v: R * (1.2 + rand() * 1.4), len: 0.35 + rand() * 0.45, hue: (rand() * 360) | 0, t0: S.now, life: 0.5 + rand() * 0.25 });
  }
  const drops = 14 + tier * 4;
  for (let i = 0; i < drops; i++) {
    const a = rand() * TAU, sp = R * (3 + rand() * 6);
    bursts.push({ k: 'drop', x: x + Math.cos(a) * R * 0.85, y: y + Math.sin(a) * R * 0.85, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp - R * 2.5,
      sz: 0.8 + rand() * 1.4, rgb: tier ? st.rgb : '225,235,255', t0: S.now, life: 0.6 + rand() * 0.45 });
  }
  b.state = 'gone'; b.hx = x; b.hy = y; b.r = 0; b.rv = 0; b.recoverUntil = 0; b.respawnAt = S.now + 2.3;
  vacancies.push({ x, y, R, t0: S.now });
  if (S.spot === b) releaseSpot();
}
function drawBursts() {
  if (!bursts.length) return;
  ctx.globalCompositeOperation = 'lighter';
  for (let i = bursts.length - 1; i >= 0; i--) {
    const q = bursts[i], age = S.now - q.t0, p = age / q.life;
    if (p >= 1) { bursts.splice(i, 1); continue; }
    if (q.k === 'remnant') {
      ctx.globalCompositeOperation = 'source-over';
      const s = (q.R / q.sR) * (1 + 0.14 * easeOut(p)), h = q.half * s;
      ctx.globalAlpha = 1 - p; ctx.drawImage(q.sprite, q.x - h, q.y - h, h * 2, h * 2); ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = 'lighter';
    } else if (q.k === 'ring') {
      const e = easeOut(p);
      ctx.lineWidth = 2.6 * (1 - p) + 0.3; ctx.strokeStyle = rgba(q.rgb, 0.75 * (1 - p));
      ctx.beginPath(); ctx.arc(q.x, q.y, q.R * (1 + 0.95 * e), 0, TAU); ctx.stroke();
      halo(q.x, q.y, q.R, 0.6 + e * 0.6, 1.4 + e, q.rgb, 0.18 * (1 - p));
    } else if (q.k === 'flash') {
      halo(q.x, q.y, q.R, 0, 0.9 * (0.6 + p), '255,255,255', 0.55 * (1 - p));
    } else if (q.k === 'shard') {
      const e = easeOut(p), rr = q.R + q.v * e, half = (q.len / 2) * (1 - p * 0.8);
      const fy = 30 * age * age * 9;
      ctx.lineCap = 'round';
      ctx.lineWidth = Math.max(0.4, 1.8 * (1 - p));
      ctx.strokeStyle = `hsla(${q.hue},100%,78%,${0.85 * (1 - p)})`;
      ctx.beginPath(); ctx.arc(q.x, q.y + fy, rr, q.a - half, q.a + half); ctx.stroke();
    } else if (q.k === 'drop') {
      const g = 900 * S.scale;
      const x = q.x + q.vx * age, y = q.y + q.vy * age + 0.5 * g * age * age;
      const vx = q.vx, vy = q.vy + g * age, sp = Math.hypot(vx, vy) || 1;
      const L = Math.min(10, sp * 0.018);
      ctx.lineCap = 'round'; ctx.lineWidth = q.sz; ctx.strokeStyle = rgba(q.rgb, 0.9 * (1 - p));
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x - (vx / sp) * L, y - (vy / sp) * L); ctx.stroke();
    } else if (q.k === 'gather') {
      const e = easeOut(p);
      ctx.lineWidth = 1.4; ctx.strokeStyle = rgba(q.rgb, 0.6 * Math.sin(p * Math.PI));
      ctx.beginPath(); ctx.arc(q.x, q.y, q.R * (1.7 - 0.7 * e), 0, TAU); ctx.stroke();
      star(q.x, q.y, q.R * 0.9 * Math.sin(p * Math.PI), '255,255,255', Math.sin(p * Math.PI));
    }
  }
  ctx.globalCompositeOperation = 'source-over';
}

/* ───────────── spotlight / search ───────────── */
function setSpot(p) {
  releaseSpot();
  let b = bubbles.find((x) => x.p.id === p.id && !x.removing);
  if (!b) {
    const victim = bubbles.filter((x) => x.p.tier === 0 && !x.p.dev && x.state === 'live' && !x.removing)
      .sort((a, c) => Math.hypot(c.x - S.cx, c.y - S.cy) - Math.hypot(a.x - S.cx, a.y - S.cy))[0];
    if (victim) victim.removing = true;
    b = spawnFromEdge(p, rand() * TAU);
  }
  if (b.state === 'gone') { b.state = 'live'; b.x = b.hx; b.y = b.hy; b.r = 0.01; }
  // Search takes ownership of the current identity, including an in-flight swap.
  b.swap = null; b.vis = 1;
  b.recoverUntil = 0;
  S.spot = b; S.spotT = S.now;
  b.born = 0;
}
function releaseSpot() { S.spot = null; }

const q = $('#q'), results = $('#results'), pill = $('#pill');
const clearButton = $('#clear');
clearButton.disabled = !q.value;
let active = -1, matches = [];
function miniAvatar(p, size = 30) {
  const c = document.createElement('canvas');
  c.width = c.height = size * DPR;
  const g = c.getContext('2d'); g.setTransform(DPR, 0, 0, DPR, size / 2 * DPR, size / 2 * DPR);
  const paint = () => {
    if (disposed || !c.isConnected && c.dataset.painted) return;
    c.dataset.painted = 'true';
    g.clearRect(-size, -size, size * 2, size * 2);
    g.save(); g.beginPath(); g.arc(0, 0, size / 2, 0, TAU); g.clip();
    drawAvatar(g, p, size / 2, paint); g.restore();
    g.lineWidth = 1; g.strokeStyle = 'rgba(255,255,255,.25)'; g.beginPath(); g.arc(0, 0, size / 2 - 0.5, 0, TAU); g.stroke();
  };
  paint();
  return c;
}
function runSearch() {
  const v = q.value.trim().toLowerCase();
  clearButton.disabled = !q.value;
  pill.classList.toggle('has-text', !!q.value);
  if (!v) { clearSearch(); return; }
  matches = [];
  const exact = [], starts = [], contains = [];
  for (const p of roster) {
    const n = p.searchName || p.name.toLowerCase(), i = n.indexOf(v);
    if (n === v) exact.push(p);
    else if (i === 0) starts.push(p);
    else if (i > 0 || p.aliases?.some(name => name.toLowerCase().includes(v))) contains.push(p);
  }
  matches = exact.concat(starts, contains).slice(0, Math.max(8, exact.length));
  results.replaceChildren();
  if (!matches.length) {
    const li = document.createElement('li'); li.className = 'empty'; li.textContent = labels.noResults;
    results.appendChild(li);
  }
  matches.forEach((p, i) => {
    const li = document.createElement('li');
    li.setAttribute('role', 'option'); li.id = results.id + '-option-' + i;
    li.dataset.index = String(i);
    li.appendChild(miniAvatar(p));
    const nm = document.createElement('span'); nm.className = 'nm';
    const n = p.name, at = n.toLowerCase().indexOf(v);
    if (at < 0) nm.textContent = n;
    else {
      const mark = document.createElement('mark'); mark.textContent = n.slice(at, at + v.length);
      nm.append(document.createTextNode(n.slice(0, at)), mark, document.createTextNode(n.slice(at + v.length)));
    }
    const tg = document.createElement('span'); tg.className = 'tg';
    tg.textContent = p.source;
    li.append(nm, tg);
    results.appendChild(li);
  });
  active = matches.length ? 0 : -1;
  results.hidden = false; q.setAttribute('aria-expanded', 'true');
  markActive();
}
function markActive() {
  [...results.children].forEach((li, i) => li.setAttribute('aria-selected', String(i === active)));
  if (active >= 0) q.setAttribute('aria-activedescendant', results.id + '-option-' + active); else q.removeAttribute('aria-activedescendant');
  const option = results.children[active];
  if (option && results.clientHeight > 0) {
    const top = option.offsetTop, bottom = top + option.offsetHeight;
    if (top < results.scrollTop) results.scrollTop = top;
    else if (bottom > results.scrollTop + results.clientHeight) results.scrollTop = bottom - results.clientHeight;
  }
}
function choose(p) {
  results.hidden = true; q.setAttribute('aria-expanded', 'false');
  q.value = p.name; pill.classList.add('has-text');
  clearButton.disabled = false;
  setSpot(p);
  $('#status').textContent = labels.found.replace('{{name}}', () => p.name);
  q.blur();
}
listen(q, 'input', runSearch);
listen(results, 'pointerdown', e => {
  const li = e.target.closest('[data-index]');
  if (li && matches[Number(li.dataset.index)]) { e.preventDefault(); choose(matches[Number(li.dataset.index)]); }
});
listen(q, 'focus', () => { if (q.value) runSearch(); });
listen(q, 'blur', () => {
  clearTimeout(blurTimer);
  blurTimer = setTimeout(() => { if (!disposed) { results.hidden = true; q.setAttribute('aria-expanded', 'false'); } }, 120);
});
listen(q, 'keydown', (e) => {
  if (e.key === 'ArrowDown' && matches.length) { active = (active + 1) % matches.length; markActive(); e.preventDefault(); }
  else if (e.key === 'ArrowUp' && matches.length) { active = (active - 1 + matches.length) % matches.length; markActive(); e.preventDefault(); }
  else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); clearSearch(); q.blur(); }
});
listen(pill, 'submit', (e) => { e.preventDefault(); if (active >= 0 && matches[active]) choose(matches[active]); });
function clearSearch() {
  q.value = ''; pill.classList.remove('has-text'); results.hidden = true; releaseSpot();
  clearButton.disabled = true;
  matches = []; active = -1; q.setAttribute('aria-expanded', 'false'); q.removeAttribute('aria-activedescendant');
  $('#status').textContent = '';
}
listen($('#clear'), 'click', () => { clearSearch(); q.focus(); });
listen(root, 'keydown', (e) => {
  if (e.key === '/' && document.activeElement !== q) { e.preventDefault(); q.focus(); }
  if (e.key === 'Escape' && document.activeElement !== q) releaseSpot();
});

/* ───────────── hover card ───────────── */
const card = $('#card'), cardAv = $('#cardAv');
cardAv.width = cardAv.height = 88;
let cardFor = null, cardCandidate = null, cardSince = 0, cardSize = null;
function updateCard() {
  const spot = S.spot && S.spot.state === 'live' && S.spot.r > S.spot.r0 ? S.spot : null;
  const b = S.hover || spot;
  if (!b || b.state !== 'live') { card.classList.remove('on'); cardCandidate = null; return; }
  if (cardCandidate !== b) {
    cardCandidate = b; cardSince = S.now; card.classList.remove('on');
  }
  // Passing over a row of bubbles should not rebuild and measure a glass card
  // for each one. Search results are immediate; deliberate hover takes 120 ms.
  if (b !== spot && S.now - cardSince < .12) return;
  if (cardFor !== b.p) {
    cardFor = b.p; cardSize = null;
    const p = b.p, st = styleOf(p);
    $('#cardName').textContent = p.name;
    $('#cardMeta').textContent = labels.source.replace('{{source}}', () => p.source);
    const paint = () => {
      if (disposed || cardFor !== p) return;
      const g = cardAv.getContext('2d'); g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, 88, 88);
      g.save(); g.translate(44, 44); g.beginPath(); g.arc(0, 0, 42, 0, TAU); g.clip(); drawAvatar(g, p, 42, paint); g.restore();
      g.lineWidth = 2; g.strokeStyle = p.tier || p.dev ? st.text : 'rgba(255,255,255,.3)'; g.beginPath(); g.arc(44, 44, 42, 0, TAU); g.stroke();
    };
    paint();
  }
  if (!cardSize) cardSize = { width: card.offsetWidth, height: card.offsetHeight };
  const cw = cardSize.width, ch = cardSize.height, gap = 16 + b.r * (1 + padOf(b.p));
  let x = b.x + gap, y = b.y - ch / 2;
  if (x + cw > S.W - 12) x = b.x - gap - cw;
  y = clamp(y, 12, S.H - ch - 12); x = clamp(x, 12, S.W - cw - 12);
  card.style.transform = `translate3d(${x}px,${y}px,0)`;
  card.classList.add('on');
}

/* ───────────── input ───────────── */
let down = null;
listen(canvas, 'pointermove', e => {
  const point = localPoint(e); S.ptr.x = point.x; S.ptr.y = point.y;
  S.ptr.inside = true; S.ptr.mouse = e.pointerType === 'mouse';
});
listen(canvas, 'pointerleave', () => { S.ptr.inside = false; S.ptr.x = S.ptr.y = -1e4; down = null; });
listen(canvas, 'pointerdown', e => { down = localPoint(e); S.ptr.mouse = e.pointerType === 'mouse'; });
listen(canvas, 'pointercancel', () => { down = null; });
listen(canvas, 'pointerup', e => {
  const point = localPoint(e);
  if (!down || Math.hypot(point.x - down.x, point.y - down.y) > 8) { down = null; return; }
  down = null;
  const b = hitTest(point.x, point.y);
  if (b) pop(b, point.x, point.y);
  else if (S.spot) { releaseSpot(); clearSearch(); }
});
function setEffects(on) {
  if (disposed || S.fx === on) return;
  S.fx = on;
  bubbles.forEach((b) => { if (b.p.tier || b.p.dev) b.dirty = true; });
}
function setMotion(on) { if (!disposed) S.motion = on; }
listen(window, 'resize', resize);
const resizeObserver = new ResizeObserver(resize);
resizeObserver.observe(root);

/* Pause the loop itself when hidden; disposal owns every callback and surface. */
const frameInterval = 1000 / 60;
let last = 0, nextFrame = 0, lastSpin = -Infinity;
function frame(ts) {
  frameHandle = 0;
  if (disposed || document.hidden) return;
  if (!started) {
    started = true; S.now = ts / 1000; resize(); populate();
  }
  schedule();
  if (ts < nextFrame - 2) return;
  nextFrame = !nextFrame || ts - nextFrame > frameInterval ? ts + frameInterval : nextFrame + frameInterval;
  const now = ts / 1000;
  const dt = Math.max(1 / 1000, Math.min(1 / 30, last ? now - last : 1 / 60));
  last = now; S.now = now;
  if (S.motion) S.t += dt;
  if (S.motion && document.activeElement === q && now - lastSpin >= 1 / 30) {
    pill.style.setProperty('--spin', ((S.t * 90) % 360) + 'deg'); lastSpin = now;
  }
  update(dt); render();
}
listen(document, 'visibilitychange', () => {
  last = 0; nextFrame = 0;
  if (document.hidden) { cancelAnimationFrame(frameHandle); frameHandle = 0; }
  else schedule();
});
resize(); schedule();
return {
  setEffects,
  setMotion,
  dispose() {
    if (disposed) return;
    disposed = true;
    cancelAnimationFrame(frameHandle); frameHandle = 0;
    clearTimeout(blurTimer);
    resizeObserver.disconnect();
    removers.splice(0).forEach(remove => remove());
    avatars.dispose();
    bubbles.forEach(releaseBubble);
    bubbles.length = bursts.length = vacancies.length = stars.length = 0;
    onScreen.clear(); collisionGrid.clear(); collisionBuckets.length = collisionPairs.length = 0;
    glyphWidths.clear(); arcGeometryCache.clear(); nameRadiusCache.clear();
    lights.forEach(light => light.node.remove());
    results.replaceChildren(); card.classList.remove('on'); cardFor = cardCandidate = null;
    releaseSurface(mctx.canvas); releaseSurface(canvas); releaseSurface(cardAv);
    delete root.dataset.visibleCount; delete root.dataset.pixelRatio;
  },
};
}
