import type { CreditsCatalog, CreditsRecord } from "./types";

const MANIFEST_URL = "https://lumina-studio-credits.pages.dev/manifest.json";
const CACHE_DATABASE = "lumina-credits-catalog";
const CACHE_STORE = "snapshots";

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid credits object");
  return value as Record<string, unknown>;
}

function ownedUrl(value: unknown): string {
  if (typeof value !== "string") throw new Error("Invalid credits URL");
  const url = new URL(value, MANIFEST_URL);
  if (url.origin !== new URL(MANIFEST_URL).origin || url.username || url.password) {
    throw new Error("Invalid credits asset origin");
  }
  return url.href;
}

function imagePath(value: unknown, assetsBase: string): string | undefined {
  if (value == null) return undefined;
  if (typeof value !== "string" || !value) throw new Error("Invalid credits avatar");
  const url = new URL(value, assetsBase);
  if (url.protocol !== "https:" || url.username || url.password) throw new Error("Invalid credits avatar URL");
  return value;
}

function imageSize(value: unknown): [number, number] | undefined {
  if (value == null) return undefined;
  if (!Array.isArray(value) || value.length !== 2 || value.some((n) => typeof n !== "number" || !Number.isFinite(n) || n <= 0)) {
    throw new Error("Invalid credits image dimensions");
  }
  return [value[0], value[1]];
}

function records(value: unknown, assetsBase: string): CreditsRecord[] {
  if (!Array.isArray(value) || !value.length) throw new Error("Invalid credits records");
  const ids = new Set<string>();
  return value.map((entry) => {
    const row = object(entry);
    for (const key of ["id", "name", "source"]) {
      if (typeof row[key] !== "string" || !(row[key] as string).trim()) throw new Error("Invalid credits identity");
    }
    const id = row.id as string;
    if (ids.has(id)) throw new Error("Duplicate credits identity");
    ids.add(id);
    if (!Number.isInteger(row.tier) || (row.tier as number) < 0 || (row.tier as number) > 7
      || typeof row.dev !== "boolean" || typeof row.brand !== "boolean") throw new Error("Invalid credits style");
    if (row.aliases != null && (!Array.isArray(row.aliases) || row.aliases.some((alias) => typeof alias !== "string"))) {
      throw new Error("Invalid credits aliases");
    }
    return {
      id, name: row.name as string, source: row.source as string,
      avatar: imagePath(row.avatar, assetsBase), avatar_size: imageSize(row.avatar_size),
      avatar_preview: imagePath(row.avatar_preview, assetsBase), avatar_preview_size: imageSize(row.avatar_preview_size),
      tier: row.tier as number, dev: row.dev, brand: row.brand, aliases: (row.aliases ?? []) as string[],
    };
  });
}

async function openCache(): Promise<IDBDatabase | null> {
  if (!globalThis.indexedDB) return null;
  return new Promise((resolve) => {
    let abandoned = false;
    const request = indexedDB.open(CACHE_DATABASE, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(CACHE_STORE);
    request.onerror = () => resolve(null);
    request.onblocked = () => { abandoned = true; resolve(null); };
    request.onsuccess = () => {
      if (abandoned) request.result.close();
      else resolve(request.result);
    };
  });
}

async function snapshot(catalog?: CreditsCatalog): Promise<CreditsCatalog | null> {
  let db: IDBDatabase | null = null;
  try {
    db = await openCache();
    if (!db) return null;
    const value = await new Promise<unknown>((resolve) => {
      const transaction = db!.transaction(CACHE_STORE, catalog ? "readwrite" : "readonly");
      const store = transaction.objectStore(CACHE_STORE);
      const request = catalog ? store.put(catalog, "current") : store.get("current");
      let result: unknown;
      request.onsuccess = () => { result = request.result; };
      transaction.oncomplete = () => resolve(catalog ?? result);
      transaction.onerror = transaction.onabort = () => resolve(null);
    });
    if (!value) return null;
    const cached = object(value);
    const assetsBase = ownedUrl(cached.assetsBase);
    return { assetsBase, records: records(cached.records, assetsBase), stale: false };
  } catch {
    // Optional browser storage must not prevent an otherwise valid online read.
    return null;
  } finally {
    db?.close();
  }
}

/** Load verified public credits; preserve the last good snapshot if a refresh fails. */
export async function loadCreditsCatalog(signal?: AbortSignal): Promise<CreditsCatalog> {
  signal?.throwIfAborted();
  const controller = new AbortController();
  const cancel = () => controller.abort(signal?.reason);
  signal?.addEventListener("abort", cancel, { once: true });
  const timeout = setTimeout(() => controller.abort(), 12_000);
  const options: RequestInit = { signal: controller.signal, credentials: "omit", referrerPolicy: "no-referrer" };
  try {
    const manifestResponse = await fetch(MANIFEST_URL, { ...options, cache: "no-cache" });
    if (!manifestResponse.ok) throw new Error("Credits manifest unavailable");
    const manifest = object(await manifestResponse.json());
    if (manifest.schema_version !== 1 || manifest.dataset !== "lumina-credits") throw new Error("Unsupported credits manifest schema");
    const rosterInfo = object(manifest.roster);
    const rosterUrl = ownedUrl(rosterInfo.path);
    const assetsBase = ownedUrl(manifest.assets_base);
    if (typeof rosterInfo.sha256 !== "string" || !/^[a-f0-9]{64}$/i.test(rosterInfo.sha256)) throw new Error("Invalid credits checksum");
    const response = await fetch(rosterUrl, options);
    if (!response.ok) throw new Error("Credits roster unavailable");
    const bytes = await response.arrayBuffer();
    if (bytes.byteLength !== rosterInfo.bytes) throw new Error("Credits roster size mismatch");
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
    const hash = Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join("");
    if (hash !== rosterInfo.sha256.toLowerCase()) throw new Error("Credits roster checksum mismatch");
    const roster = object(JSON.parse(new TextDecoder().decode(bytes)));
    if (roster.schema_version !== 2) throw new Error("Unsupported credits roster schema");
    const result: CreditsCatalog = { records: records(roster.records, assetsBase), assetsBase, stale: false };
    if (result.records.length !== manifest.records) throw new Error("Credits roster count mismatch");
    signal?.throwIfAborted();
    await snapshot(result);
    signal?.throwIfAborted();
    return result;
  } catch (error) {
    signal?.throwIfAborted();
    const cached = await snapshot();
    signal?.throwIfAborted();
    if (cached) return { ...cached, stale: true };
    throw error;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", cancel);
  }
}
