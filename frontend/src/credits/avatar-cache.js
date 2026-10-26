/* Source archives stay unchanged. Display avatars use a 384-pixel WebP cache;
   canvas and nickname density remain native. Bound decoding and storage. */
  class AvatarDiskStore {
    constructor(byteLimit) {
      this.byteLimit = byteLimit; this.entries = new Map(); this.bytes = 0;
      this.opening = null; this.writing = Promise.resolve();
    }
    open() {
      if (!this.opening) this.opening = (async () => {
        if (typeof caches === 'undefined') return null;
        try {
          const cache = await caches.open('lumina-credits-avatars-v2');
          const keys = await cache.keys();
          const metadata = await Promise.all(keys.map(async key => {
            const response = await cache.match(key);
            return [key.url, Number(response?.headers.get('X-Lumina-Bytes')) || 0,
              Number(response?.headers.get('X-Lumina-Stored')) || 0];
          }));
          metadata.sort((a, b) => a[2] - b[2]);
          for (const [url, size] of metadata) { this.entries.set(url, size); this.bytes += size; }
          return cache;
        } catch (_) { return null; }
      })();
      return this.opening;
    }
    async get(url) {
      try {
        const cache = await this.open(), response = await cache?.match(url);
        if (!response) return null;
        const blob = await response.blob();
        const width = Number(response.headers.get('X-Lumina-Width'));
        const height = Number(response.headers.get('X-Lumina-Height'));
        return { blob, stored: Number(response.headers.get('X-Lumina-Stored')) || 0,
          dimensions: width && height ? [width, height] : null };
      } catch (_) { return null; }
    }
    put(url, blob, dimensions) {
      if (!blob.size || blob.size > this.byteLimit || typeof Response === 'undefined') return Promise.resolve(false);
      this.writing = this.writing.then(async () => {
        try {
          const cache = await this.open();
          if (!cache) return false;
          await cache.put(url, new Response(blob, { headers: {
            'Content-Type': blob.type || 'application/octet-stream',
            'X-Lumina-Bytes': String(blob.size), 'X-Lumina-Stored': String(Date.now()),
            'X-Lumina-Width': String(dimensions?.[0] || 0),
            'X-Lumina-Height': String(dimensions?.[1] || 0),
          } }));
          this.bytes -= this.entries.get(url) || 0;
          this.entries.delete(url); this.entries.set(url, blob.size); this.bytes += blob.size;
          while (this.bytes > this.byteLimit || this.entries.size > 1024) {
            const [oldest, size] = this.entries.entries().next().value;
            await cache.delete(oldest); this.entries.delete(oldest); this.bytes -= size;
          }
          return true;
        } catch (_) { return false; }
      });
      return this.writing;
    }
    async drop(url) {
      try {
        const cache = await this.open();
        await cache?.delete(url);
        this.bytes -= this.entries.get(url) || 0; this.entries.delete(url);
      } catch (_) { /* A damaged disk entry must not block the network fallback. */ }
    }
  }
  export class CreditsAvatarCache {
    constructor({ concurrency = 4, byteLimit = 48 * 1024 * 1024,
      diskByteLimit = 64 * 1024 * 1024, diskMaxAge = 24 * 60 * 60 * 1000 } = {}) {
      this.concurrency = concurrency; this.byteLimit = byteLimit;
      this.disk = new AvatarDiskStore(diskByteLimit); this.diskMaxAge = diskMaxAge;
      this.diskHits = 0; this.diskWrites = 0;
      this.entries = new Map(); this.queue = []; this.active = 0;
      this.bytes = 0; this.failed = 0; this.loaded = 0;
      this.disposed = false;
    }
    get(url, dimensions, requestedPixels, fit, onReady) {
      if (this.disposed) return { ok: false, fail: true, img: null };
      const key = fit + ':' + url;
      let entry = this.entries.get(key);
      const pixels = 2 ** Math.ceil(Math.log2(Math.max(32, requestedPixels)));
      if (!entry) {
        entry = { url, dimensions, fit, requested: pixels, pixels: 0, img: null,
          ok: false, fail: false, pending: false, waiters: new Set(), bytes: 0 };
        this.entries.set(key, entry);
      }
      this.entries.delete(key); this.entries.set(key, entry);
      entry.requested = Math.max(entry.requested, pixels);
      if (!entry.fail && (!entry.ok || entry.pixels < pixels)) {
        if (onReady) entry.waiters.add(onReady);
        if (!entry.pending) {
          entry.pending = true; this.queue.push(entry); this.pump();
        }
      }
      return entry;
    }
    pump() {
      while (!this.disposed && this.active < this.concurrency && this.queue.length) {
        const entry = this.queue.shift();
        this.active++;
        this.load(entry).finally(() => { this.active--; this.pump(); });
      }
    }
    async decode(entry, pixels) {
      let source;
      const remote = /^https:\/\//.test(entry.url);
      const diskUrl = entry.url + (entry.url.includes('?') ? '&' : '?') + '__lumina_fit=' + entry.fit;
      const web = remote || typeof location !== 'undefined' && /^https?:$/.test(location.protocol);
      if (web && typeof fetch === 'function' && typeof createImageBitmap === 'function') {
        let cached = remote ? await this.disk.get(diskUrl) : null;
        if (this.disposed) throw new DOMException('Disposed', 'AbortError');
        if (cached && Date.now() - cached.stored < this.diskMaxAge) {
          try {
            const image = await this.resize(cached.blob,
              { ...entry, dimensions: cached.dimensions || entry.dimensions }, Math.max(pixels, 384));
            this.diskHits++; return image;
          } catch (_) { await this.disk.drop(diskUrl); cached = null; }
        }
        try {
          const response = await fetch(entry.url, { signal: entry.controller.signal,
            credentials: 'omit', referrerPolicy: 'no-referrer' });
          if (!response.ok) throw new Error('Avatar request failed');
          source = await response.blob();
          const image = await this.resize(source, entry, remote ? Math.max(pixels, 384) : pixels);
          if (remote && !this.disposed) {
            const stored = await this.compress(image.image, source, entry.dimensions);
            if (!this.disposed && await this.disk.put(diskUrl, stored.blob, stored.dimensions)) this.diskWrites++;
          }
          return image;
        } catch (error) {
          if (cached && !this.disposed) {
            try {
              const image = await this.resize(cached.blob,
                { ...entry, dimensions: cached.dimensions || entry.dimensions }, Math.max(pixels, 384));
              this.diskHits++; return image;
            } catch (_) { await this.disk.drop(diskUrl); }
          }
          throw error;
        }
      } else {
        source = await new Promise((resolve, reject) => {
          const image = new Image(); image.decoding = 'async';
          const stop = () => { image.onload = image.onerror = null; image.src = ''; reject(new DOMException('Disposed', 'AbortError')); };
          entry.controller.signal.addEventListener('abort', stop, { once: true });
          const finish = callback => value => {
            entry.controller.signal.removeEventListener('abort', stop);
            image.onload = image.onerror = null; callback(value);
          };
          image.onload = finish(() => resolve(image)); image.onerror = finish(reject); image.src = entry.url;
        });
      }
      return this.resize(source, entry, pixels);
    }
    async resize(source, entry, pixels) {
      if (typeof createImageBitmap !== 'function') return { image: source, pixels: Infinity };
      let dimensions = entry.dimensions || [source.naturalWidth || source.width, source.naturalHeight || source.height];
      let decodedSource = null;
      if (!dimensions.every(value => Number.isFinite(value) && value > 0)) {
        decodedSource = await createImageBitmap(source);
        source = decodedSource; dimensions = [source.width, source.height];
        entry.dimensions = dimensions;
      }
      const [width, height] = dimensions;
      try {
        pixels = Math.min(pixels, 384);
        if (entry.fit === 'contain') {
          const ratio = Math.min(1, pixels / Math.max(width, height));
          return { image: await createImageBitmap(source, {
            resizeWidth: Math.max(1, Math.round(width * ratio)),
            resizeHeight: Math.max(1, Math.round(height * ratio)), resizeQuality: 'high',
          }), pixels: ratio === Math.min(1, 384 / Math.max(width, height)) ? Infinity : pixels };
        }
        const side = Math.min(width, height), edge = Math.min(side, pixels);
        return { image: await createImageBitmap(source, (width - side) / 2, (height - side) / 2, side, side,
          { resizeWidth: edge, resizeHeight: edge, resizeQuality: 'high' }),
          pixels: edge === Math.min(side, 384) ? Infinity : pixels };
      } finally { decodedSource?.close(); }
    }
    async compress(image, original, dimensions) {
      if (typeof OffscreenCanvas !== 'undefined') {
        try {
          const canvas = new OffscreenCanvas(image.width, image.height);
          canvas.getContext('2d').drawImage(image, 0, 0);
          const blob = await canvas.convertToBlob({ type: 'image/webp', quality: .82 });
          return { blob, dimensions: [image.width, image.height] };
        } catch (_) { /* Older browsers can still cache the original source. */ }
      }
      return { blob: original, dimensions };
    }
    async load(entry) {
      const pixels = entry.requested;
      entry.controller = new AbortController();
      entry.timeout = setTimeout(() => entry.controller.abort(), 15000);
      try {
        const decoded = await this.decode(entry, pixels);
        if (this.disposed) { decoded.image.close?.(); return; }
        if (entry.img && entry.img.close) entry.img.close();
        this.bytes -= entry.bytes;
        entry.img = decoded.image; entry.pixels = decoded.pixels;
        entry.bytes = (entry.img.width || entry.img.naturalWidth || pixels)
          * (entry.img.height || entry.img.naturalHeight || pixels) * 4;
        this.bytes += entry.bytes; entry.ok = true; this.loaded++;
      } catch (_) {
        if (!this.disposed) { entry.fail = true; this.failed++; }
      } finally {
        clearTimeout(entry.timeout);
        entry.pending = false;
        if (!this.disposed) for (const ready of entry.waiters) ready();
        entry.waiters.clear();
        if (!this.disposed) this.trim(entry);
      }
    }
    trim(keep) {
      for (const [url, entry] of this.entries) {
        if (this.bytes <= this.byteLimit && this.entries.size <= 192) break;
        if (entry === keep || entry.pending) continue;
        entry.img?.close?.();
        this.bytes -= entry.bytes; this.entries.delete(url);
      }
    }
    stats() {
      return { active: this.active, queued: this.queue.length, cached: this.entries.size,
        decoded_bytes: this.bytes, loaded: this.loaded, failed: this.failed,
        disk_hits: this.diskHits, disk_writes: this.diskWrites };
    }
    dispose() {
      if (this.disposed) return;
      this.disposed = true; this.queue.length = 0;
      for (const entry of this.entries.values()) {
        clearTimeout(entry.timeout); entry.controller?.abort();
        entry.waiters.clear(); entry.img?.close?.(); entry.img = null;
      }
      this.entries.clear(); this.bytes = 0;
    }
  }
