"use strict";

// This probe loads the native addon in a real utility process without listing or opening ports.
const { app, utilityProcess } = require("electron");
const path = require("node:path");

let child = null;
let ready = null;
let failure = null;
const deadline = setTimeout(() => {
  failure = "serial_worker_smoke_timeout";
  if (child) child.kill();
  else app.exit(1);
}, 10000);

app.whenReady().then(() => {
  child = utilityProcess.fork(path.join(__dirname, "../serial-worker.cjs"), [], {
    stdio: "ignore", serviceName: "Lumina Serial Load Probe",
  });
  child.on("message", (message) => {
    if (message.type === "ready") ready = message;
    else if (message.type === "error") failure = message.error;
    else return;
    child.kill();
  });
  child.once("error", () => { failure = "serial_worker_smoke_failed"; child.kill(); });
  child.once("exit", () => {
    clearTimeout(deadline);
    const passed = Boolean(ready && !failure);
    console.log(JSON.stringify({ passed, electron: process.versions.electron, worker: ready, error: failure,
      enumerated: false, opened: false, workerExited: true }));
    app.exit(passed ? 0 : 1);
  });
}).catch(() => { clearTimeout(deadline); app.exit(1); });
