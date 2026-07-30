export const WORKSHOP_API_VERSION = "1.0.0" as const;
export const WORKSHOP_MANIFEST_VERSION = 1 as const;
export const WORKSHOP_RPC_VERSION = 1 as const;

export const WORKSHOP_PERMISSION_NAMES = [
  "image.pick",
  "project.storage",
  "color-library.read",
  "handoff.image",
] as const;

export type WorkshopPermissionName =
  (typeof WORKSHOP_PERMISSION_NAMES)[number];

export interface LocalizedText {
  "zh-CN": string;
  "en-US": string;
}

export interface WorkshopManifestV1 {
  manifestVersion: typeof WORKSHOP_MANIFEST_VERSION;
  id: string;
  version: string;
  name: LocalizedText;
  description: LocalizedText;
  publisher: string;
  workshopApi: {
    min: string;
    maxExclusive: string;
  };
  luminaVersion: {
    min: string;
  };
  entrypoints: {
    ui: "ui/index.html";
  };
  permissions: Array<{
    name: WorkshopPermissionName;
    reason: string;
  }>;
}

export interface WorkshopRaster {
  width: number;
  height: number;
  data: Uint8ClampedArray;
}

export interface WorkshopPickedImage {
  name: string;
  mimeType: string;
  bytes: ArrayBuffer;
  raster: WorkshopRaster;
}

export interface WorkshopRecipeSource {
  manifestSchemaVersion: 1;
  moduleId: string;
  moduleVersion: string;
  projectSchemaVersion: string;
  renderSchemaVersion: string;
  payload: Record<string, unknown>;
}

export interface WorkshopSquareGridLayout {
  kind: "square-grid";
  rows: number;
  columns: number;
  pitchMm: number;
}

export interface WorkshopImageHandoff {
  moduleId: string;
  moduleVersion: string;
  projectId: string;
  pngBytes: ArrayBuffer;
  pixelWidth: number;
  pixelHeight: number;
  recommendedWidthMm: number;
  recommendedHeightMm: number;
  preserveCanvasBounds: true;
  layout?: WorkshopSquareGridLayout;
  colorLibraryId: string | null;
  recipeSource: WorkshopRecipeSource;
}

export interface WorkshopProjectRecord<T = unknown> {
  projectId: string;
  schemaVersion: string;
  createdAt: string;
  updatedAt: string;
  project: T;
}

export interface WorkshopColorEntry {
  id: string;
  label: string;
  hex: string;
  materialId: string | null;
}

export interface WorkshopColorLibrary {
  id: string;
  label: string;
  sourceKind: "lut" | "material-archive" | "native-bundle";
  colors: WorkshopColorEntry[];
}

export interface WorkshopUiState {
  locale: "zh-CN" | "en-US";
  theme: "light" | "dark";
  tokens: Record<string, string>;
}

export type WorkshopRpcMethod =
  | "image.pick"
  | "project.save"
  | "project.load"
  | "project.latest"
  | "project.remove"
  | "colorLibrary.read"
  | "handoff.image"
  | "ui.getState"
  | "status.progress"
  | "status.error"
  | "status.diagnostics"
  | "lifecycle.ready";

export interface WorkshopRpcRequest {
  protocol: "lumina-workshop-rpc";
  version: typeof WORKSHOP_RPC_VERSION;
  kind: "request";
  requestId: string;
  method: WorkshopRpcMethod;
  payload: unknown;
}

export interface WorkshopRpcResponse {
  protocol: "lumina-workshop-rpc";
  version: typeof WORKSHOP_RPC_VERSION;
  kind: "response";
  requestId: string;
  ok: boolean;
  result?: unknown;
  error?: {
    code: string;
    message: string;
    retryable: boolean;
  };
}

export function createRequestEnvelope(
  requestId: string,
  method: WorkshopRpcMethod,
  payload: unknown,
): WorkshopRpcRequest {
  return {
    protocol: "lumina-workshop-rpc",
    version: WORKSHOP_RPC_VERSION,
    kind: "request",
    requestId,
    method,
    payload,
  };
}
