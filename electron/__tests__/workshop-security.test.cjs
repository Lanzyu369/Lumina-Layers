const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const {
  createWorkshopSessionToken,
  isAllowedWorkshopDownload,
  isAllowedWorkshopIpcSender,
  isAllowedWorkshopPermission,
  isAllowedWorkshopPopup,
  isAllowedWorkshopRequest,
  isWorkshopFrameProcessIsolated,
  resolveWorkshopRuntimeRequest,
  shouldBlockWorkshopNavigation,
  shouldBlockWorkshopRedirect,
  shouldRetryFrontendLoad,
} = require("../workshop-security.cjs");

const HOST_URL = "http://127.0.0.1:4174/";
const MODULE_URL =
  "lumina-workshop://fixture.hello/1.0.0/ui/index.html";

describe("Workshop desktop runtime security", () => {
  it("creates a unique non-empty per-launch token", () => {
    const first = createWorkshopSessionToken();
    const second = createWorkshopSessionToken();
    assert.match(first, /^[A-Za-z0-9_-]{43}$/);
    assert.notEqual(first, second);
  });

  it("resolves only a canonical module runtime URL", () => {
    assert.deepEqual(resolveWorkshopRuntimeRequest(MODULE_URL), {
      moduleId: "fixture.hello",
      version: "1.0.0",
      backendUrl:
        "http://127.0.0.1:8000/api/workshop/v1/modules/" +
        "fixture.hello/1.0.0/runtime",
    });
    for (const invalid of [
      "lumina-workshop://fixture.hello/1.0.0/ui/other.html",
      "lumina-workshop://fixture.hello/%2F/ui/index.html",
      "lumina-workshop://fixture.hello/1.0.0/ui/index.html?token=x",
      "lumina-workshop://Fixture.Hello/1.0.0/ui/index.html",
      "lumina-workshop://fixture.hello@evil/1.0.0/ui/index.html",
      "https://fixture.hello/1.0.0/ui/index.html",
    ]) {
      assert.equal(resolveWorkshopRuntimeRequest(invalid), null);
    }
  });

  it("blocks network requests initiated by an opaque module origin", () => {
    assert.equal(
      isAllowedWorkshopRequest({
        initiator: "null",
        frameUrl: MODULE_URL,
        resourceType: "fetch",
        url: "https://example.com/collect",
      }),
      false,
    );
    assert.equal(
      isAllowedWorkshopRequest({
        initiator: "null",
        frameUrl: MODULE_URL,
        resourceType: "webSocket",
        url: "wss://example.com/socket",
      }),
      false,
    );
  });

  it("allows the host to create a module frame but blocks module navigation", () => {
    assert.equal(
      isAllowedWorkshopRequest({
        initiator: HOST_URL,
        frameUrl: HOST_URL,
        resourceType: "subFrame",
        url: MODULE_URL,
      }),
      true,
    );
    assert.equal(
      isAllowedWorkshopRequest({
        initiator: HOST_URL,
        frameUrl: MODULE_URL,
        resourceType: "subFrame",
        url: MODULE_URL,
      }),
      true,
    );
    assert.equal(
      isAllowedWorkshopRequest({
        initiator: null,
        frameUrl: "about:blank",
        parentFrameUrl: HOST_URL,
        resourceType: "subFrame",
        url: MODULE_URL,
      }),
      true,
    );
    assert.equal(
      isAllowedWorkshopRequest({
        initiator: "null",
        frameUrl: MODULE_URL,
        resourceType: "subFrame",
        url: MODULE_URL,
      }),
      false,
    );
    assert.equal(
      isAllowedWorkshopRequest({
        initiator: "null",
        frameUrl: MODULE_URL,
        resourceType: "subFrame",
        url: "lumina-workshop://other.module/1.0.0/ui/index.html",
      }),
      false,
    );
  });

  it("retries only a failed top-level host frontend load", () => {
    assert.equal(
      shouldRetryFrontendLoad({
        isMainFrame: true,
        validatedUrl: HOST_URL,
      }),
      true,
    );
    assert.equal(
      shouldRetryFrontendLoad({
        isMainFrame: false,
        validatedUrl: MODULE_URL,
      }),
      false,
    );
    assert.equal(
      shouldRetryFrontendLoad({
        isMainFrame: true,
        validatedUrl: MODULE_URL,
      }),
      false,
    );
  });

  it("allows only explicit non-network worker and media resources", () => {
    for (const [resourceType, url] of [
      ["worker", "blob:null/9fcd0b53-69a4-4d35-97ca-a19d61bc9c40"],
      ["worker", "data:text/javascript,self.close()"],
      ["image", "data:image/png;base64,AA=="],
      ["media", "blob:null/media"],
      ["font", "data:font/woff2;base64,AA=="],
    ]) {
      assert.equal(
        isAllowedWorkshopRequest({
          initiator: "null",
          frameUrl: MODULE_URL,
          resourceType,
          url,
        }),
        true,
      );
    }
    assert.equal(
      isAllowedWorkshopRequest({
        initiator: "null",
        frameUrl: MODULE_URL,
        resourceType: "other",
        url: "blob:null/download",
      }),
      false,
    );
    assert.equal(
      isAllowedWorkshopRequest({
        initiator: "null",
        frameUrl: MODULE_URL,
        resourceType: "mainFrame",
        url: "data:text/html,escaped",
      }),
      false,
    );
  });

  it("fails closed when a renderer request has no frame identity", () => {
    assert.equal(
      isAllowedWorkshopRequest({
        initiator: "null",
        frameUrl: null,
        resourceType: "fetch",
        url: "https://example.com/collect",
      }),
      false,
    );
    assert.equal(
      isAllowedWorkshopRequest({
        initiator: null,
        frameUrl: null,
        resourceType: "subFrame",
        url: MODULE_URL,
      }),
      false,
    );
  });

  it("leaves ordinary host-frame requests unaffected", () => {
    assert.equal(
      isAllowedWorkshopRequest({
        initiator: HOST_URL,
        frameUrl: HOST_URL,
        resourceType: "xhr",
        url: "http://127.0.0.1:8000/api/health",
      }),
      true,
    );
    assert.equal(
      isAllowedWorkshopRequest({
        initiator: null,
        frameUrl: null,
        resourceType: "mainFrame",
        url: HOST_URL,
      }),
      true,
    );
  });

  it("allows only the exact loopback runtime for trusted main-process proxying", () => {
    assert.equal(
      isAllowedWorkshopRequest({
        initiator: null,
        frameUrl: null,
        resourceType: "other",
        trustedInternal: true,
        url:
          "http://127.0.0.1:8000/api/workshop/v1/modules/" +
          "fixture.hello/1.0.0/runtime",
      }),
      true,
    );
    assert.equal(
      isAllowedWorkshopRequest({
        initiator: null,
        frameUrl: null,
        resourceType: "other",
        trustedInternal: true,
        url: "http://127.0.0.1:8000/api/health",
      }),
      false,
    );
  });

  it("blocks module navigation and redirect escape paths", () => {
    assert.equal(
      shouldBlockWorkshopNavigation({
        frameUrl: MODULE_URL,
        initiatorUrl: "null",
        targetUrl: "https://example.com",
        isMainFrame: false,
      }),
      true,
    );
    assert.equal(
      shouldBlockWorkshopNavigation({
        frameUrl: "about:blank",
        initiatorUrl: HOST_URL,
        targetUrl: MODULE_URL,
        isMainFrame: false,
      }),
      false,
    );
    assert.equal(
      shouldBlockWorkshopRedirect({
        frameUrl: MODULE_URL,
        targetUrl: "data:text/html,redirect",
      }),
      true,
    );
  });

  it("denies module popups, permissions, and downloads", () => {
    assert.equal(
      isAllowedWorkshopPopup({
        openerUrl: MODULE_URL,
        targetUrl: "https://example.com",
      }),
      false,
    );
    assert.equal(
      isAllowedWorkshopPermission({
        frameUrl: MODULE_URL,
        requestingOrigin: "null",
      }),
      false,
    );
    assert.equal(
      isAllowedWorkshopDownload({
        frameUrl: MODULE_URL,
        url: "blob:null/download",
      }),
      false,
    );
    assert.equal(
      isAllowedWorkshopDownload({
        frameUrl: HOST_URL,
        url: "blob:null/download",
      }),
      false,
    );
  });

  it("allows Workshop IPC only from the trusted host frame", () => {
    assert.equal(isAllowedWorkshopIpcSender(HOST_URL), true);
    assert.equal(isAllowedWorkshopIpcSender(MODULE_URL), false);
    assert.equal(isAllowedWorkshopIpcSender("null"), false);
    assert.equal(
      isAllowedWorkshopIpcSender("https://example.com/"),
      false,
    );
  });

  it("requires a distinct renderer process for the module frame", () => {
    assert.equal(isWorkshopFrameProcessIsolated(41, 42), true);
    assert.equal(isWorkshopFrameProcessIsolated(41, 41), false);
    assert.equal(isWorkshopFrameProcessIsolated(41, null), false);
  });
});
