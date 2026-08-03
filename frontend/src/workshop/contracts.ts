/**
 * Host-side identities derived from the public Workshop SDK.
 * 宿主侧只在这里扩展公开 Workshop SDK 的身份类型。
 */

import {
  WORKSHOP_PERMISSION_NAMES,
  WORKSHOP_RPC_VERSION,
  type WorkshopPermissionName,
  type WorkshopRpcMethod,
  type WorkshopRpcResponse,
} from "@lumina/workshop-sdk";

export {
  WORKSHOP_API_VERSION,
  WORKSHOP_MANIFEST_VERSION,
  WORKSHOP_PERMISSION_NAMES,
  WORKSHOP_RPC_VERSION,
} from "@lumina/workshop-sdk";

export type {
  LocalizedText,
  WorkshopColorEntry,
  WorkshopColorLibrary,
  WorkshopImageHandoff,
  WorkshopManifestV1,
  WorkshopPermissionName,
  WorkshopPickedImage,
  WorkshopProjectRecord,
  WorkshopRaster,
  WorkshopRecipeSource,
  WorkshopRpcMethod,
  WorkshopRpcRequest,
  WorkshopRpcResponse,
  WorkshopSquareGridLayout,
  WorkshopUiState,
} from "@lumina/workshop-sdk";

export interface WorkshopModuleIdentity {
  readonly moduleId: string;
  readonly moduleVersion: string;
}

export interface WorkshopRpcEnvelopeShape {
  protocol: "lumina-workshop-rpc";
  version: unknown;
  kind: "request";
  requestId: string;
  method: string;
  payload: unknown;
}

export const WORKSHOP_RPC_METHODS = [
  "image.pick",
  "project.save",
  "project.load",
  "project.latest",
  "project.remove",
  "colorLibrary.read",
  "handoff.image",
  "ui.getState",
  "status.progress",
  "status.error",
  "status.diagnostics",
  "lifecycle.ready",
] as const satisfies readonly WorkshopRpcMethod[];

const RPC_METHOD_SET = new Set<string>(WORKSHOP_RPC_METHODS);
const PERMISSION_SET = new Set<string>(WORKSHOP_PERMISSION_NAMES);

export function isWorkshopRpcMethod(
  value: unknown,
): value is WorkshopRpcMethod {
  return typeof value === "string" && RPC_METHOD_SET.has(value);
}

export function isWorkshopPermissionName(
  value: unknown,
): value is WorkshopPermissionName {
  return typeof value === "string" && PERMISSION_SET.has(value);
}

export function responseEnvelope(
  requestId: string,
  result: unknown,
): WorkshopRpcResponse {
  return {
    protocol: "lumina-workshop-rpc",
    version: WORKSHOP_RPC_VERSION,
    kind: "response",
    requestId,
    ok: true,
    result,
  };
}

export function errorResponseEnvelope(
  requestId: string,
  code: string,
  message: string,
  retryable = false,
): WorkshopRpcResponse {
  return {
    protocol: "lumina-workshop-rpc",
    version: WORKSHOP_RPC_VERSION,
    kind: "response",
    requestId,
    ok: false,
    error: {
      code,
      message,
      retryable,
    },
  };
}

export function isRpcEnvelopeShape(
  value: unknown,
): value is WorkshopRpcEnvelopeShape {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value)
  ) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    candidate.protocol === "lumina-workshop-rpc" &&
    candidate.kind === "request" &&
    typeof candidate.requestId === "string" &&
    candidate.requestId.length > 0 &&
    candidate.requestId.length <= 128 &&
    typeof candidate.method === "string" &&
    "payload" in candidate
  );
}
