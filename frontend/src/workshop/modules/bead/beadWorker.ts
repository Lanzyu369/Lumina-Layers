import {
  classifyPattern,
  recognizeBeadPattern,
} from "./recognition";
import { renderBeadProject } from "./renderer";
import type {
  BeadWorkerRequest,
  BeadWorkerResponse,
} from "./workerProtocol";

interface WorkerScope {
  onmessage:
    | ((event: MessageEvent<BeadWorkerRequest>) => void)
    | null;
  postMessage(
    message: BeadWorkerResponse,
    transfer?: Transferable[],
  ): void;
}

function errorCode(error: unknown): string {
  if (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    typeof error.code === "string"
  ) {
    return error.code;
  }
  return "bead-worker-failed";
}

function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "The bead worker could not complete the request.";
}

export function processBeadWorkerRequest(
  request: BeadWorkerRequest,
): BeadWorkerResponse {
  try {
    if (request.type === "classify") {
      return {
        id: request.id,
        ok: true,
        type: "classify",
        result: classifyPattern(request.raster),
      };
    }
    if (request.type === "recognize") {
      return {
        id: request.id,
        ok: true,
        type: "recognize",
        result: recognizeBeadPattern(request.request),
      };
    }
    return {
      id: request.id,
      ok: true,
      type: "render",
      result: renderBeadProject(request.project, {
        compression: request.compression,
        pixelsPerCell: request.pixelsPerCell,
      }),
    };
  } catch (error) {
    return {
      id: request.id,
      ok: false,
      errorCode: errorCode(error),
      message: errorMessage(error),
    };
  }
}

const workerScope = self as unknown as WorkerScope;

workerScope.onmessage = (event) => {
  const response = processBeadWorkerRequest(event.data);
  if (response.ok && response.type === "render") {
    workerScope.postMessage(response, [response.result.data.buffer]);
  } else {
    workerScope.postMessage(response);
  }
};
