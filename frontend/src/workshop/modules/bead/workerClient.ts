import type { WorkshopRaster } from "../../types";
import type { BeadProject, RecognitionRequest } from "./types";
import type {
  BeadWorkerRequest,
  BeadWorkerRequestType,
  BeadWorkerResponse,
  BeadWorkerResultMap,
} from "./workerProtocol";

export interface BeadWorkerLike {
  onmessage:
    | ((event: MessageEvent<BeadWorkerResponse>) => void)
    | null;
  onerror: ((event: ErrorEvent) => void) | null;
  postMessage(
    message: BeadWorkerRequest,
    transfer?: Transferable[],
  ): void;
  terminate(): void;
}

export interface BeadWorkerTask<T> {
  id: number;
  promise: Promise<T>;
}

interface PendingTask<T extends BeadWorkerRequestType> {
  type: T;
  resolve: (value: BeadWorkerResultMap[T]) => void;
  reject: (error: BeadWorkerClientError) => void;
}

export class BeadWorkerClientError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "BeadWorkerClientError";
    this.code = code;
  }
}

function productionWorker(): BeadWorkerLike {
  return new Worker(new URL("./beadWorker.ts", import.meta.url), {
    type: "module",
  });
}

function transferableRaster(source: WorkshopRaster): {
  raster: WorkshopRaster;
  transfer: Transferable[];
} {
  const data = new Uint8ClampedArray(source.data);
  return {
    raster: {
      width: source.width,
      height: source.height,
      data,
    },
    transfer: [data.buffer],
  };
}

function errorMessage(event: ErrorEvent): string {
  return event.message || "The bead worker stopped unexpectedly.";
}

export class BeadWorkerClient {
  private readonly worker: BeadWorkerLike;

  private readonly pending = new Map<
    number,
    PendingTask<BeadWorkerRequestType>
  >();

  private nextId = 1;

  private disposed = false;

  constructor(
    workerFactory: () => BeadWorkerLike = productionWorker,
  ) {
    this.worker = workerFactory();
    this.worker.onmessage = (event) => {
      this.handleResponse(event.data);
    };
    this.worker.onerror = (event) => {
      this.rejectAll(
        new BeadWorkerClientError(
          "worker-error",
          errorMessage(event),
        ),
      );
    };
  }

  classify(
    source: WorkshopRaster,
  ): BeadWorkerTask<BeadWorkerResultMap["classify"]> {
    const { raster, transfer } = transferableRaster(source);
    return this.post("classify", (id) => ({
      id,
      type: "classify",
      raster,
    }), transfer);
  }

  recognize(
    request: RecognitionRequest,
  ): BeadWorkerTask<BeadWorkerResultMap["recognize"]> {
    const { raster, transfer } = transferableRaster(
      request.source,
    );
    return this.post(
      "recognize",
      (id) => ({
        id,
        type: "recognize",
        request: { ...request, source: raster },
      }),
      transfer,
    );
  }

  render(
    project: BeadProject,
    compression: number,
    pixelsPerCell: number,
  ): BeadWorkerTask<BeadWorkerResultMap["render"]> {
    return this.post("render", (id) => ({
      id,
      type: "render",
      project: { ...project, source: null },
      compression,
      pixelsPerCell,
    }));
  }

  cancelBefore(requestId: number): void {
    for (const [id, task] of this.pending) {
      if (id < requestId) {
        this.pending.delete(id);
        task.reject(
          new BeadWorkerClientError(
            "request-cancelled",
            "A newer bead worker request replaced this request.",
          ),
        );
      }
    }
  }

  cancel(requestId: number): void {
    const task = this.pending.get(requestId);
    if (!task) {
      return;
    }
    this.pending.delete(requestId);
    task.reject(
      new BeadWorkerClientError(
        "request-cancelled",
        "The bead worker request was cancelled.",
      ),
    );
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.rejectAll(
      new BeadWorkerClientError(
        "worker-disposed",
        "The bead worker client was disposed.",
      ),
    );
    this.worker.onmessage = null;
    this.worker.onerror = null;
    this.worker.terminate();
  }

  private post<T extends BeadWorkerRequestType>(
    type: T,
    createRequest: (id: number) => Extract<
      BeadWorkerRequest,
      { type: T }
    >,
    transfer: Transferable[] = [],
  ): BeadWorkerTask<BeadWorkerResultMap[T]> {
    if (this.disposed) {
      throw new BeadWorkerClientError(
        "worker-disposed",
        "The bead worker client was disposed.",
      );
    }
    const id = this.nextId;
    this.nextId += 1;
    let rejectTask:
      | ((error: BeadWorkerClientError) => void)
      | null = null;
    const promise = new Promise<BeadWorkerResultMap[T]>(
      (resolve, reject) => {
        rejectTask = reject;
        this.pending.set(id, {
          type,
          resolve,
          reject,
        } as PendingTask<BeadWorkerRequestType>);
      },
    );
    try {
      this.worker.postMessage(createRequest(id), transfer);
    } catch (error) {
      this.pending.delete(id);
      rejectTask?.(
        new BeadWorkerClientError(
          "worker-post-failed",
          error instanceof Error
            ? error.message
            : "Failed to send work to the bead worker.",
        ),
      );
    }
    return { id, promise };
  }

  private handleResponse(response: BeadWorkerResponse): void {
    const task = this.pending.get(response.id);
    if (!task) {
      return;
    }
    this.pending.delete(response.id);
    if (!response.ok) {
      task.reject(
        new BeadWorkerClientError(
          response.errorCode,
          response.message,
        ),
      );
      return;
    }
    if (response.type !== task.type) {
      task.reject(
        new BeadWorkerClientError(
          "protocol-mismatch",
          "The bead worker returned a mismatched result.",
        ),
      );
      return;
    }
    task.resolve(
      response.result as BeadWorkerResultMap[BeadWorkerRequestType],
    );
  }

  private rejectAll(error: BeadWorkerClientError): void {
    const tasks = [...this.pending.values()];
    this.pending.clear();
    for (const task of tasks) {
      task.reject(
        new BeadWorkerClientError(error.code, error.message),
      );
    }
  }
}
