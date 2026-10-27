import { afterEach, expect, it, vi } from 'vitest';
import { CreditsAvatarCache } from './avatar-cache.js';

afterEach(() => { vi.unstubAllGlobals(); });

it('bounds concurrent avatar requests and aborts active work and drops queued work on disposal', async () => {
  const signals: AbortSignal[] = [];
  const fetcher = vi.fn((_url: string, init: RequestInit) => {
    signals.push(init.signal as AbortSignal);
    return new Promise<Response>(() => {});
  });
  vi.stubGlobal('fetch', fetcher);
  vi.stubGlobal('createImageBitmap', vi.fn());
  const cache = new CreditsAvatarCache({ concurrency: 2 });
  for (let i = 0; i < 5; i++) cache.get(`https://credits.example/${i}.webp`, [384, 384], 80, 'cover');
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  expect(cache.stats().queued).toBe(3);
  cache.dispose();
  expect(signals.every(signal => signal.aborted)).toBe(true);
  expect(cache.stats().queued).toBe(0);
  expect(cache.stats().cached).toBe(0);
});

it('closes a late decoded bitmap without invoking a disposed view callback', async () => {
  const closed = vi.fn(), ready = vi.fn();
  let resolveBitmap!: (image: ImageBitmap) => void;
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, blob: async () => new Blob(['avatar']) })));
  const decode = vi.fn(() => new Promise<ImageBitmap>(resolve => { resolveBitmap = resolve; }));
  vi.stubGlobal('createImageBitmap', decode);
  const cache = new CreditsAvatarCache();
  cache.get('https://credits.example/avatar.webp', [384, 384], 80, 'cover', ready);
  await vi.waitFor(() => expect(decode).toHaveBeenCalledTimes(1));
  cache.dispose();
  resolveBitmap({ width: 384, height: 384, close: closed } as unknown as ImageBitmap);
  await vi.waitFor(() => expect(closed).toHaveBeenCalledOnce());
  expect(ready).not.toHaveBeenCalled();
  expect(cache.stats().decoded_bytes).toBe(0);
});

it('loads valid avatars whose optional manifest dimensions are absent', async () => {
  const closed = vi.fn(), ready = vi.fn();
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, blob: async () => new Blob(['avatar']) })));
  const decode = vi.fn(async (...args: unknown[]) => {
    const options = args.at(-1) as ImageBitmapOptions;
    if (args.length > 1 && (!Number.isFinite(options.resizeWidth) || !Number.isFinite(options.resizeHeight))) {
      throw new Error('Invalid bitmap dimensions');
    }
    return { width: options.resizeWidth ?? 640, height: options.resizeHeight ?? 480, close: closed } as unknown as ImageBitmap;
  });
  vi.stubGlobal('createImageBitmap', decode);
  const cache = new CreditsAvatarCache();
  const entry = cache.get('https://credits.example/avatar.webp', undefined, 80, 'cover', ready);
  await vi.waitFor(() => expect(ready).toHaveBeenCalledOnce());
  expect(entry.ok).toBe(true);
  expect(entry.fail).toBe(false);
  cache.dispose();
});
