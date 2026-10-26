import { webcrypto } from "node:crypto";
import { IDBFactory } from "fake-indexeddb";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadCreditsCatalog } from "./catalog";

const origin = "https://lumina-studio-credits.pages.dev/";
const record = {
  id: "community-1", name: "真实昵称", source: "爱发电",
  avatar: "data/avatars/example.webp", avatar_size: [96, 96],
  avatar_preview: null, avatar_preview_size: null,
  tier: 2, dev: false, brand: false, aliases: ["旧昵称"],
};

async function serveCatalog(overrides: Record<string, unknown> = {}) {
  const payload = JSON.stringify({ schema_version: 2, records: [record] });
  const bytes = new TextEncoder().encode(payload);
  const hash = Buffer.from(await webcrypto.subtle.digest("SHA-256", bytes)).toString("hex");
  const manifest = {
    schema_version: 1, dataset: "lumina-credits", records: 1,
    assets_base: "./", roster: { path: "data/roster.json", sha256: hash, bytes: bytes.byteLength },
    ...overrides,
  };
  manifest.roster = { path: "data/roster.json", sha256: hash, bytes: bytes.byteLength, ...(overrides.roster as object ?? {}) };
  const fetcher = vi.fn(async (url: string) => url.endsWith("manifest.json")
    ? new Response(JSON.stringify(manifest), { status: 200 })
    : new Response(payload, { status: 200 }));
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

beforeEach(() => {
  vi.stubGlobal("indexedDB", new IDBFactory());
  vi.stubGlobal("crypto", webcrypto);
});
afterEach(() => vi.unstubAllGlobals());

describe("Cloudflare credits catalog", () => {
  it("verifies the roster and keeps avatar paths relative to the manifest asset base", async () => {
    const fetcher = await serveCatalog();
    const result = await loadCreditsCatalog();
    expect(result.assetsBase).toBe(origin);
    expect(result.stale).toBe(false);
    expect(result.records).toEqual([expect.objectContaining({ name: "真实昵称", avatar: record.avatar })]);
    expect(fetcher).toHaveBeenNthCalledWith(1, origin + "manifest.json", expect.objectContaining({ credentials: "omit", referrerPolicy: "no-referrer" }));
    expect(fetcher).toHaveBeenNthCalledWith(2, origin + "data/roster.json", expect.objectContaining({ credentials: "omit" }));
  });

  it("rejects a checksum mismatch on first load", async () => {
    await serveCatalog({ roster: { sha256: "0".repeat(64) } });
    await expect(loadCreditsCatalog()).rejects.toThrow(/checksum/i);
  });

  it("retains the last verified snapshot when a refresh has a wrong checksum", async () => {
    await serveCatalog();
    const good = await loadCreditsCatalog();
    await serveCatalog({ roster: { sha256: "0".repeat(64) } });
    const cached = await loadCreditsCatalog();
    expect(cached).toEqual({ ...good, stale: true });
  });

  it("loads the last verified snapshot when the network is unavailable", async () => {
    await serveCatalog();
    const good = await loadCreditsCatalog();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Offline")));
    expect(await loadCreditsCatalog()).toEqual({ ...good, stale: true });
  });

  it("does not follow a manifest to an unrelated origin", async () => {
    const fetcher = await serveCatalog({ roster: { path: "https://example.org/roster.json", sha256: "0".repeat(64), bytes: 1 } });
    await expect(loadCreditsCatalog()).rejects.toThrow(/origin/i);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("rejects unsupported manifest schemas", async () => {
    await serveCatalog({ schema_version: 7 });
    await expect(loadCreditsCatalog()).rejects.toThrow(/schema/i);
  });

  it("respects cancellation instead of reviving a closed view from the cache", async () => {
    await serveCatalog();
    await loadCreditsCatalog();
    const controller = new AbortController();
    controller.abort();
    await expect(loadCreditsCatalog(controller.signal)).rejects.toHaveProperty("name", "AbortError");
  });

  it("still loads online when browser storage is unavailable", async () => {
    vi.stubGlobal("indexedDB", undefined);
    await serveCatalog();
    expect((await loadCreditsCatalog()).records[0].name).toBe(record.name);
  });
});
