import assert from "node:assert/strict";
import test from "node:test";

import {
  WORKSHOP_API_VERSION,
  WORKSHOP_MANIFEST_VERSION,
  WORKSHOP_PERMISSION_NAMES,
  WorkshopClientError,
  applyWorkshopUiState,
  connectWorkshop,
  createRequestEnvelope,
} from "../dist/index.js";

test("exports stable v1 identities and permission names", () => {
  assert.equal(WORKSHOP_API_VERSION, "1.0.0");
  assert.equal(WORKSHOP_MANIFEST_VERSION, 1);
  assert.deepEqual(WORKSHOP_PERMISSION_NAMES, [
    "image.pick",
    "project.storage",
    "color-library.read",
    "handoff.image",
  ]);
});

test("creates a bounded protocol request envelope", () => {
  assert.deepEqual(createRequestEnvelope("req-1", "ui.getState", {}), {
    protocol: "lumina-workshop-rpc",
    version: 1,
    kind: "request",
    requestId: "req-1",
    method: "ui.getState",
    payload: {},
  });
});

function createConnectedWindow(channel, posted) {
  const parent = {
    postMessage(message) {
      posted.push(message);
    },
  };
  return {
    parent,
    addEventListener(_name, listener) {
      queueMicrotask(() =>
        listener({
          source: parent,
          data: {
            type: "lumina.workshop.connect",
            sessionId: "session-1",
          },
          ports: [channel.port2],
        }),
      );
    },
    removeEventListener() {},
  };
}

test("connects only after the host transfers one MessagePort", async () => {
  const channel = new MessageChannel();
  const posted = [];
  const client = await connectWorkshop({
    moduleId: "fixture.hello",
    moduleVersion: "1.0.0",
    windowObject: createConnectedWindow(channel, posted),
  });

  assert.deepEqual(posted[0], {
    type: "lumina.workshop.ready",
    moduleId: "fixture.hello",
    moduleVersion: "1.0.0",
    apiVersion: "1.0.0",
  });
  assert.equal(client.sessionId, "session-1");
  client.close();
  channel.port1.close();
});

test("maps valid responses and rejects pending requests when closed", async () => {
  const channel = new MessageChannel();
  const client = await connectWorkshop({
    moduleId: "fixture.hello",
    moduleVersion: "1.0.0",
    windowObject: createConnectedWindow(channel, []),
  });

  const requestReceived = new Promise((resolve) => {
    channel.port1.onmessage = ({ data }) => {
      channel.port1.postMessage({
        protocol: "lumina-workshop-rpc",
        version: 1,
        kind: "response",
        requestId: data.requestId,
        ok: true,
        result: {
          locale: "zh-CN",
          theme: "dark",
          tokens: {},
        },
      });
      resolve();
    };
  });
  const state = await client.ui.getState();
  await requestReceived;
  assert.equal(state.theme, "dark");

  channel.port1.onmessage = null;
  const pending = client.projects.latest();
  client.close();
  await assert.rejects(
    pending,
    (error) =>
      error instanceof WorkshopClientError && error.code === "CLIENT_CLOSED",
  );
  channel.port1.close();
});

test("times out a handshake that is not transferred by the parent", async () => {
  let removed = false;
  const parent = { postMessage() {} };
  await assert.rejects(
    connectWorkshop({
      moduleId: "fixture.hello",
      moduleVersion: "1.0.0",
      handshakeTimeoutMs: 10,
      windowObject: {
        parent,
        addEventListener() {},
        removeEventListener() {
          removed = true;
        },
      },
    }),
    (error) =>
      error instanceof WorkshopClientError &&
      error.code === "HANDSHAKE_TIMEOUT",
  );
  assert.equal(removed, true);
});

test("fails closed when the host sends a duplicate response", async () => {
  const channel = new MessageChannel();
  const client = await connectWorkshop({
    moduleId: "fixture.hello",
    moduleVersion: "1.0.0",
    windowObject: createConnectedWindow(channel, []),
  });

  let firstRequestId = "";
  channel.port1.onmessage = ({ data }) => {
    firstRequestId ||= data.requestId;
    channel.port1.postMessage({
      protocol: "lumina-workshop-rpc",
      version: 1,
      kind: "response",
      requestId: data.requestId,
      ok: true,
      result: null,
    });
  };
  await client.projects.latest();

  channel.port1.onmessage = null;
  const pending = client.projects.latest();
  channel.port1.postMessage({
    protocol: "lumina-workshop-rpc",
    version: 1,
    kind: "response",
    requestId: firstRequestId,
    ok: true,
    result: null,
  });
  await assert.rejects(
    pending,
    (error) =>
      error instanceof WorkshopClientError &&
      error.code === "DUPLICATE_RESPONSE",
  );
  channel.port1.close();
});

test("applies only public Lumina theme tokens", () => {
  const values = new Map();
  const root = {
    lang: "",
    dataset: {},
    style: {
      setProperty(name, value) {
        values.set(name, value);
      },
    },
  };

  applyWorkshopUiState(
    {
      locale: "en-US",
      theme: "light",
      tokens: {
        "--lumina-surface": "#fff",
        "--private-secret": "blocked",
        color: "red",
      },
    },
    root,
  );

  assert.equal(root.lang, "en-US");
  assert.equal(root.dataset.theme, "light");
  assert.deepEqual([...values], [["--lumina-surface", "#fff"]]);
});
