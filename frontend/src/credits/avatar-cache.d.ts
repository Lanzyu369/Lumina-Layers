export interface AvatarCacheEntry {
  ok: boolean;
  fail: boolean;
  img: CanvasImageSource | null;
}

export class CreditsAvatarCache {
  constructor(options?: { concurrency?: number; byteLimit?: number; diskByteLimit?: number; diskMaxAge?: number });
  get(url: string, dimensions: [number, number] | undefined, requestedPixels: number,
    fit: 'cover' | 'contain', onReady?: () => void): AvatarCacheEntry;
  stats(): { active: number; queued: number; cached: number; decoded_bytes: number;
    loaded: number; failed: number; disk_hits: number; disk_writes: number };
  dispose(): void;
}
