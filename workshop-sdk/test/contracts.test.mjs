import assert from "node:assert/strict";
import test from "node:test";

import {
  WORKSHOP_API_VERSION,
  WORKSHOP_MANIFEST_VERSION,
  WORKSHOP_PERMISSION_NAMES,
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
