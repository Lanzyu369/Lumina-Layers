"use strict";

const { ipcRenderer } = require("electron");

const queuedPayloads = [];
const payloadWaiters = [];

ipcRenderer.on("lumina-migration-payload", (_event, payload) => {
  const resolve = payloadWaiters.shift();
  if (resolve) resolve(payload);
  else queuedPayloads.push(payload);
});

globalThis.__luminaMigrationReceive = () => {
  if (queuedPayloads.length > 0) return Promise.resolve(queuedPayloads.shift());
  return new Promise(resolve => payloadWaiters.push(resolve));
};
