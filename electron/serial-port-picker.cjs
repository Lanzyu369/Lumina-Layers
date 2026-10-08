"use strict";

const PAGE_SIZE = 5;
const LABEL_KEYS = ["title", "message", "empty", "cancel", "next", "previous"];

function normalizeLabels(value) {
  if (!value || typeof value !== "object") return null;
  const result = {};
  for (const key of LABEL_KEYS) {
    const label = value[key];
    if (typeof label !== "string" || !label.trim() || label.length > 500 || /[\u0000-\u0008\u000B-\u001F]/u.test(label)) return null;
    result[key] = label;
  }
  return result;
}

function displayText(value) {
  return typeof value === "string"
    ? value.replace(/[\u0000-\u001F\u007F\u202A-\u202E\u2066-\u2069]/gu, "").slice(0, 100)
    : "";
}

function createSerialPortPicker({ getWindow, dialog, frontendUrl, packagedIndexUrl, getFrontendUrl }) {
  let labels = null;
  let active = null;
  let installedSession = null;

  function trustedUrl(value) {
    try {
      const url = new URL(value);
      if (url.username || url.password) return false;
      if (url.protocol === "file:") {
        const index = new URL(packagedIndexUrl);
        return url.protocol === index.protocol && url.host === index.host && url.pathname === index.pathname && url.search === index.search;
      }
      return url.protocol === "http:" && url.origin === new URL(getFrontendUrl?.() ?? frontendUrl).origin;
    } catch {
      return false;
    }
  }

  function trustedContents(contents) {
    try {
      const window = getWindow();
      return Boolean(window && !window.isDestroyed() && contents && contents === window.webContents &&
        !contents.isDestroyed() && contents.mainFrame && contents.mainFrame.parent === null &&
        trustedUrl(contents.mainFrame.url) && trustedUrl(contents.getURL()));
    } catch {
      return false;
    }
  }

  function isTrustedIpcSender(event) {
    return trustedContents(event?.sender) && event.senderFrame === event.sender.mainFrame;
  }

  function allowPermission(contents, requestingOrigin, details) {
    if (!trustedContents(contents) || details?.isMainFrame !== true ||
        details.requestingUrl !== contents.mainFrame.url) return false;
    if (contents.mainFrame.url.startsWith("file:")) {
      return requestingOrigin === "file://" || requestingOrigin === "file:///" || requestingOrigin === details.requestingUrl;
    }
    try {
      return new URL(requestingOrigin).origin === new URL(getFrontendUrl?.() ?? frontendUrl).origin;
    } catch {
      return false;
    }
  }

  function setLabels(event, value) {
    if (!isTrustedIpcSender(event)) return false;
    const normalized = normalizeLabels(value);
    if (!normalized) return false;
    labels = normalized;
    return true;
  }

  async function pickNativePort(event, ports, signal) {
    if (!isTrustedIpcSender(event) || !labels || signal?.aborted) return null;
    const window = getWindow();
    const frame = event.senderFrame;
    const url = frame.url;
    const copy = { ...labels };
    let page = 0;
    while (!signal?.aborted && isTrustedIpcSender(event) && frame.url === url) {
      const lastPage = Math.max(0, Math.ceil(ports.length / PAGE_SIZE) - 1);
      const visible = ports.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
      const actions = [null, ...visible.map((port) => ({ path: port.path }))];
      const buttons = [copy.cancel, ...visible.map((port) => displayText(port.path))];
      if (page > 0) { actions.push({ step: -1 }); buttons.push(copy.previous); }
      if (page < lastPage) { actions.push({ step: 1 }); buttons.push(copy.next); }
      let response;
      try {
        response = await dialog.showMessageBox(window, {
          type: "info", title: copy.title, message: ports.length ? copy.message : copy.empty,
          detail: visible.map((port) => [displayText(port.path), displayText(port.manufacturer)]
            .filter(Boolean).join(" — ")).join("\n"),
          buttons, defaultId: 0, cancelId: 0, noLink: true, signal,
        });
      } catch (error) {
        if (signal?.aborted) return null;
        throw error;
      }
      if (signal?.aborted || !isTrustedIpcSender(event) || event.senderFrame !== frame || frame.url !== url) return null;
      const action = actions[response.response];
      if (action?.step) { page += action.step; continue; }
      return action?.path ?? null;
    }
    return null;
  }

  async function choose(event, initialPorts, contents, callback) {
    event.preventDefault();
    if (!trustedContents(contents) || !labels) { callback(""); return; }
    active?.finish("");
    const window = getWindow();
    const frame = contents.mainFrame;
    const url = frame.url;
    const ports = new Map(initialPorts.filter((port) => typeof port.portId === "string" && port.portId)
      .map((port) => [port.portId, port]));
    const copy = { ...labels };
    let settled = false;
    let revision = 0;
    let page = 0;
    let controller = null;
    let timer = null;
    const session = installedSession;

    function validContext() {
      return trustedContents(contents) && contents.mainFrame === frame && frame.url === url;
    }
    function finish(portId) {
      if (settled) return;
      settled = true;
      controller?.abort();
      clearTimeout(timer);
      session.removeListener("serial-port-added", added);
      session.removeListener("serial-port-removed", removed);
      contents.removeListener("did-start-navigation", navigating);
      contents.removeListener("destroyed", cancel);
      contents.removeListener("render-process-gone", cancel);
      window.removeListener("close", cancel);
      window.removeListener("closed", cancel);
      if (active?.finish === finish) active = null;
      // The renderer may already have gone away; cancellation is a boundary guard.
      try { callback(portId); } catch { /* Electron invalidated the request. */ }
    }
    function cancel() { finish(""); }
    function navigating(_event, _url, _isInPlace, isMainFrame) {
      if (isMainFrame !== false) cancel();
    }
    function changed() { ++revision; controller?.abort(); }
    function added(_event, port, owner) {
      if (owner !== contents || !port?.portId) return;
      ports.set(port.portId, port);
      changed();
    }
    function removed(_event, port, owner) {
      if (owner !== contents || !ports.delete(port?.portId)) return;
      changed();
    }
    active = { finish };
    session.on("serial-port-added", added);
    session.on("serial-port-removed", removed);
    contents.on("did-start-navigation", navigating);
    contents.on("destroyed", cancel);
    contents.on("render-process-gone", cancel);
    window.on("close", cancel);
    window.on("closed", cancel);
    timer = setTimeout(cancel, 120000);
    timer.unref?.();
    try {
      while (!settled && validContext()) {
        const list = [...ports.values()];
        const lastPage = Math.max(0, Math.ceil(list.length / PAGE_SIZE) - 1);
        page = Math.min(page, lastPage);
        const visible = list.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
        const actions = [null, ...visible.map((port) => ({ portId: port.portId }))];
        const buttons = [copy.cancel, ...visible.map((port) => displayText(port.portName) || displayText(port.portId))];
        if (page > 0) { actions.push({ step: -1 }); buttons.push(copy.previous); }
        if (page < lastPage) { actions.push({ step: 1 }); buttons.push(copy.next); }
        controller = new AbortController();
        const shownRevision = revision;
        let response;
        try {
          response = await dialog.showMessageBox(window, {
            type: "info", title: copy.title,
            message: list.length ? copy.message : copy.empty,
            detail: visible.map((port) => [displayText(port.portName), displayText(port.displayName)].filter(Boolean).join(" — ")).join("\n"),
            buttons, defaultId: 0, cancelId: 0, noLink: true, signal: controller.signal,
          });
        } catch (error) {
          // Electron documents abort as cancellation; also tolerate platforms
          // rejecting the promise when a hotplug refresh closes the dialog.
          if (!settled && controller.signal.aborted && revision !== shownRevision && validContext()) continue;
          throw error;
        }
        if (settled) return;
        if (!validContext()) { finish(""); return; }
        if (revision !== shownRevision) continue;
        const action = actions[response.response];
        if (action?.step) { page += action.step; continue; }
        finish(action?.portId && ports.has(action.portId) ? action.portId : "");
      }
    } catch {
      finish("");
    } finally {
      if (!settled) finish("");
    }
  }

  function install(session) {
    if (installedSession) return;
    installedSession = session;
    session.on("select-serial-port", choose);
  }
  function dispose() {
    active?.finish("");
    installedSession?.removeListener("select-serial-port", choose);
    installedSession = null;
  }
  return { allowPermission, dispose, install, isTrustedIpcSender, pickNativePort, setLabels };
}

module.exports = { createSerialPortPicker, normalizeLabels };
