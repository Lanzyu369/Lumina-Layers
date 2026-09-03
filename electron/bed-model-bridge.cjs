"use strict";

const BACKEND_ORIGIN = "http://127.0.0.1:8000";
const BED_MODEL_PATH = "/api/system/machine-registry/bed-model";
const DEVICE_PROFILE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/;
const MAX_NATIVE_BED_MODEL_BYTES = 32 * 1024 * 1024;

function isAllowedBedModelIpcSender(details) {
  return (
    details?.isMainFrame === true &&
    typeof details.senderFrameUrl === "string" &&
    typeof details.trustedMainFrameUrl === "string" &&
    details.senderFrameUrl === details.trustedMainFrameUrl
  );
}

function resolveNativeBedModelBackendUrl(deviceProfileId) {
  if (
    typeof deviceProfileId !== "string" ||
    !DEVICE_PROFILE_ID_PATTERN.test(deviceProfileId)
  ) {
    throw new TypeError("Invalid device profile id.");
  }
  const url = new URL(BED_MODEL_PATH, BACKEND_ORIGIN);
  url.searchParams.set("device_profile_id", deviceProfileId);
  return url.href;
}

async function cancelReader(reader) {
  try {
    await reader.cancel();
  } catch (_) {}
}

async function fetchNativeBedModel({
  deviceProfileId,
  fetchImpl,
  maxBytes = MAX_NATIVE_BED_MODEL_BYTES,
}) {
  if (typeof fetchImpl !== "function") {
    throw new TypeError("A fetch implementation is required.");
  }
  if (!Number.isSafeInteger(maxBytes) || maxBytes <= 0) {
    throw new TypeError("Invalid native bed model byte limit.");
  }

  const requestedUrl = resolveNativeBedModelBackendUrl(deviceProfileId);
  const response = await fetchImpl(requestedUrl, { redirect: "error" });
  if (response.status === 404) {
    return null;
  }
  if (response.status !== 200) {
    throw new Error("Native bed model request failed.");
  }
  if (response.redirected === true) {
    throw new Error("Native bed model redirects are forbidden.");
  }
  if (
    typeof response.url === "string" &&
    response.url.length > 0 &&
    new URL(response.url).href !== requestedUrl
  ) {
    throw new Error("Native bed model response URL changed.");
  }
  if (response.headers?.get("content-type")?.trim().toLowerCase() !== "model/stl") {
    throw new Error("Native bed model response has an invalid MIME type.");
  }
  if (!response.body || typeof response.body.getReader !== "function") {
    throw new Error("Native bed model response has no readable body.");
  }

  const reader = response.body.getReader();
  const declaredSize = Number(response.headers.get("content-length"));
  if (Number.isFinite(declaredSize) && declaredSize > maxBytes) {
    await cancelReader(reader);
    throw new Error("Native bed model is too large.");
  }

  const chunks = [];
  let totalBytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!(value instanceof Uint8Array)) {
        throw new TypeError("Native bed model stream returned invalid bytes.");
      }
      totalBytes += value.byteLength;
      if (totalBytes > maxBytes) {
        throw new Error("Native bed model is too large.");
      }
      chunks.push(value);
    }
  } catch (error) {
    await cancelReader(reader);
    throw error;
  }

  const combined = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    combined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return combined.buffer;
}

module.exports = {
  MAX_NATIVE_BED_MODEL_BYTES,
  fetchNativeBedModel,
  isAllowedBedModelIpcSender,
  resolveNativeBedModelBackendUrl,
};
