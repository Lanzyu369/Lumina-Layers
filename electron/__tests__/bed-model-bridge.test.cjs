const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

let bridge = {};
try {
  bridge = require("../bed-model-bridge.cjs");
} catch (_) {}

const {
  fetchNativeBedModel,
  isAllowedBedModelIpcSender,
  resolveNativeBedModelBackendUrl,
} = bridge;

const DEV_MAIN_URL = "http://127.0.0.1:4174/";
const FILE_MAIN_URL =
  "file:///Applications/Lumina%20Studio.app/Contents/Resources/app/dist/index.html";

function fakeResponse({
  chunks = [],
  contentType = "model/stl",
  redirected = false,
  status = 200,
  url = "",
} = {}) {
  let chunkIndex = 0;
  let cancelled = false;
  const reader = {
    async read() {
      if (chunkIndex >= chunks.length) {
        return { done: true, value: undefined };
      }
      const value = chunks[chunkIndex];
      chunkIndex += 1;
      return { done: false, value };
    },
    async cancel() {
      cancelled = true;
    },
  };
  return {
    body: { getReader: () => reader },
    get cancelled() {
      return cancelled;
    },
    headers: new Headers({ "content-type": contentType }),
    redirected,
    status,
    url,
  };
}

describe("native bed model desktop bridge", () => {
  it("exports the complete guarded bridge contract", () => {
    assert.equal(typeof fetchNativeBedModel, "function");
    assert.equal(typeof isAllowedBedModelIpcSender, "function");
    assert.equal(typeof resolveNativeBedModelBackendUrl, "function");
  });

  it("allows only the exact trusted top-level Lumina frame", () => {
    assert.equal(typeof isAllowedBedModelIpcSender, "function");
    if (!isAllowedBedModelIpcSender) return;

    for (const trustedMainFrameUrl of [DEV_MAIN_URL, FILE_MAIN_URL]) {
      assert.equal(
        isAllowedBedModelIpcSender({
          isMainFrame: true,
          senderFrameUrl: trustedMainFrameUrl,
          trustedMainFrameUrl,
        }),
        true,
      );
    }
    for (const candidate of [
      {
        isMainFrame: false,
        senderFrameUrl: FILE_MAIN_URL,
        trustedMainFrameUrl: FILE_MAIN_URL,
      },
      {
        isMainFrame: true,
        senderFrameUrl:
          "lumina-workshop://fixture.hello/1.0.0/ui/index.html",
        trustedMainFrameUrl: FILE_MAIN_URL,
      },
      {
        isMainFrame: true,
        senderFrameUrl: "https://example.com/",
        trustedMainFrameUrl: DEV_MAIN_URL,
      },
      {
        isMainFrame: true,
        senderFrameUrl: "file:///tmp/index.html",
        trustedMainFrameUrl: FILE_MAIN_URL,
      },
    ]) {
      assert.equal(isAllowedBedModelIpcSender(candidate), false);
    }
  });

  it("constructs only the fixed loopback endpoint from a validated profile id", () => {
    assert.equal(typeof resolveNativeBedModelBackendUrl, "function");
    if (!resolveNativeBedModelBackendUrl) return;

    assert.equal(
      resolveNativeBedModelBackendUrl("BambuStudio:bbl:bambu-lab-h2d:0.4"),
      "http://127.0.0.1:8000/api/system/machine-registry/bed-model" +
        "?device_profile_id=BambuStudio%3Abbl%3Abambu-lab-h2d%3A0.4",
    );
    for (const invalid of [
      "",
      "../bed.stl",
      "profile?id=other",
      "profile%2Fother",
      "x".repeat(257),
      42,
    ]) {
      assert.throws(() => resolveNativeBedModelBackendUrl(invalid));
    }
  });

  it("streams a valid STL without allowing the renderer to choose the URL", async () => {
    assert.equal(typeof fetchNativeBedModel, "function");
    if (!fetchNativeBedModel) return;

    const response = fakeResponse({
      chunks: [new Uint8Array([1, 2]), new Uint8Array([3, 4])],
    });
    let requestedUrl = null;
    let requestedOptions = null;
    const bytes = await fetchNativeBedModel({
      deviceProfileId: "OrcaSlicer:bbl:bambu-lab-h2d:0.4",
      fetchImpl: async (url, options) => {
        requestedUrl = url;
        requestedOptions = options;
        return response;
      },
    });

    assert.equal(
      requestedUrl,
      "http://127.0.0.1:8000/api/system/machine-registry/bed-model" +
        "?device_profile_id=OrcaSlicer%3Abbl%3Abambu-lab-h2d%3A0.4",
    );
    assert.deepEqual(requestedOptions, { redirect: "error" });
    assert.deepEqual([...new Uint8Array(bytes)], [1, 2, 3, 4]);
  });

  it("returns no model for a backend 404", async () => {
    assert.equal(typeof fetchNativeBedModel, "function");
    if (!fetchNativeBedModel) return;

    const result = await fetchNativeBedModel({
      deviceProfileId: "OrcaSlicer:bbl:bambu-lab-h2d:0.4",
      fetchImpl: async () => fakeResponse({ status: 404 }),
    });
    assert.equal(result, null);
  });

  it("rejects an unexpected MIME type or redirected response", async () => {
    assert.equal(typeof fetchNativeBedModel, "function");
    if (!fetchNativeBedModel) return;

    const options = {
      deviceProfileId: "OrcaSlicer:bbl:bambu-lab-h2d:0.4",
    };
    await assert.rejects(
      fetchNativeBedModel({
        ...options,
        fetchImpl: async () =>
          fakeResponse({ contentType: "application/octet-stream" }),
      }),
    );
    await assert.rejects(
      fetchNativeBedModel({
        ...options,
        fetchImpl: async () =>
          fakeResponse({
            redirected: true,
            url: "http://127.0.0.1:8000/redirected.stl",
          }),
      }),
    );
    await assert.rejects(
      fetchNativeBedModel({
        ...options,
        fetchImpl: async () =>
          fakeResponse({ url: "http://127.0.0.1:8001/bed.stl" }),
      }),
    );
  });

  it("cancels the response stream when the STL exceeds the byte limit", async () => {
    assert.equal(typeof fetchNativeBedModel, "function");
    if (!fetchNativeBedModel) return;

    const response = fakeResponse({
      chunks: [new Uint8Array([1, 2, 3]), new Uint8Array([4, 5, 6])],
    });
    await assert.rejects(
      fetchNativeBedModel({
        deviceProfileId: "OrcaSlicer:bbl:bambu-lab-h2d:0.4",
        fetchImpl: async () => response,
        maxBytes: 4,
      }),
      /too large/i,
    );
    assert.equal(response.cancelled, true);
  });
});
