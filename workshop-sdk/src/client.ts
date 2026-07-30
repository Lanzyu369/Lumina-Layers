import {
  WORKSHOP_API_VERSION,
  WORKSHOP_RPC_VERSION,
  WorkshopColorLibrary,
  WorkshopImageHandoff,
  WorkshopPickedImage,
  WorkshopProjectRecord,
  WorkshopRpcMethod,
  WorkshopRpcResponse,
  WorkshopUiState,
  createRequestEnvelope,
} from "./contracts.js";

const DEFAULT_HANDSHAKE_TIMEOUT_MS = 10_000;
const DEFAULT_REQUEST_TIMEOUT_MS = 30_000;
const IMAGE_PICK_REQUEST_TIMEOUT_MS = 300_000;
const HANDOFF_REQUEST_TIMEOUT_MS = 120_000;
const MAX_LOCALLY_TIMED_OUT_REQUEST_IDS = 256;

interface WorkshopParentWindowLike {
  postMessage(
    message: unknown,
    targetOrigin?: string,
    transfer?: Transferable[],
  ): void;
}

interface WorkshopWindowLike {
  parent: WorkshopParentWindowLike;
  addEventListener(
    type: "message",
    listener: (event: MessageEvent) => void,
  ): void;
  removeEventListener(
    type: "message",
    listener: (event: MessageEvent) => void,
  ): void;
}

export interface ConnectWorkshopOptions {
  moduleId: string;
  moduleVersion: string;
  windowObject?: WorkshopWindowLike;
  handshakeTimeoutMs?: number;
}

export class WorkshopClientError extends Error {
  readonly code: string;
  readonly retryable: boolean;

  constructor(code: string, message: string, retryable = false) {
    super(message);
    this.name = "WorkshopClientError";
    this.code = code;
    this.retryable = retryable;
  }
}

export interface WorkshopClient {
  readonly sessionId: string;
  image: {
    pick(): Promise<WorkshopPickedImage | null>;
  };
  projects: {
    save<T>(record: WorkshopProjectRecord<T>): Promise<void>;
    load<T>(projectId: string): Promise<WorkshopProjectRecord<T> | null>;
    latest<T>(): Promise<WorkshopProjectRecord<T> | null>;
    remove(projectId: string): Promise<void>;
  };
  colorLibrary: {
    read(): Promise<WorkshopColorLibrary | null>;
  };
  handoff: {
    image(
      value: WorkshopImageHandoff,
    ): Promise<{ status: "needs-confirmation" | "completed" }>;
  };
  ui: {
    getState(): Promise<WorkshopUiState>;
  };
  status: {
    progress(
      value: {
        phase: string;
        completed: number;
        total: number;
      } | null,
    ): Promise<void>;
    error(
      value: {
        code: string;
        message: string;
        retryable: boolean;
      } | null,
    ): Promise<void>;
    diagnostics(
      value: Record<string, string | number | boolean | null>,
    ): Promise<void>;
  };
  lifecycle: {
    ready(): Promise<void>;
  };
  close(): void;
}

interface PendingRequest {
  resolve(value: unknown): void;
  reject(reason: WorkshopClientError): void;
  timeout: ReturnType<typeof setTimeout>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseResponse(value: unknown): WorkshopRpcResponse | null {
  if (!isRecord(value)) {
    return null;
  }
  if (
    value.protocol !== "lumina-workshop-rpc" ||
    value.version !== WORKSHOP_RPC_VERSION ||
    value.kind !== "response" ||
    typeof value.requestId !== "string" ||
    value.requestId.length === 0 ||
    typeof value.ok !== "boolean"
  ) {
    return null;
  }
  if (value.ok) {
    return value as unknown as WorkshopRpcResponse;
  }
  if (
    !isRecord(value.error) ||
    typeof value.error.code !== "string" ||
    typeof value.error.message !== "string" ||
    typeof value.error.retryable !== "boolean"
  ) {
    return null;
  }
  return value as unknown as WorkshopRpcResponse;
}

class PortWorkshopClient implements WorkshopClient {
  readonly sessionId: string;
  readonly image;
  readonly projects;
  readonly colorLibrary;
  readonly handoff;
  readonly ui;
  readonly status;
  readonly lifecycle;

  private readonly port: MessagePort;
  private readonly pending = new Map<string, PendingRequest>();
  private readonly locallyTimedOutRequestIds = new Set<string>();
  private requestSequence = 0;
  private closed = false;

  constructor(sessionId: string, port: MessagePort) {
    this.sessionId = sessionId;
    this.port = port;
    this.port.onmessage = (event) => this.handleResponse(event.data);
    this.port.onmessageerror = () => {
      this.failProtocol(
        new WorkshopClientError(
          "MALFORMED_RESPONSE",
          "The Workshop host sent an unreadable response.",
        ),
      );
    };
    this.port.start();

    this.image = {
      pick: () =>
        this.request<WorkshopPickedImage | null>(
          "image.pick",
          {},
          [],
          IMAGE_PICK_REQUEST_TIMEOUT_MS,
        ),
    };
    this.projects = {
      save: <T>(record: WorkshopProjectRecord<T>) =>
        this.request<void>("project.save", { record }),
      load: <T>(projectId: string) =>
        this.request<WorkshopProjectRecord<T> | null>("project.load", {
          projectId,
        }),
      latest: <T>() =>
        this.request<WorkshopProjectRecord<T> | null>("project.latest", {}),
      remove: (projectId: string) =>
        this.request<void>("project.remove", { projectId }),
    };
    this.colorLibrary = {
      read: () =>
        this.request<WorkshopColorLibrary | null>("colorLibrary.read", {}),
    };
    this.handoff = {
      image: (value: WorkshopImageHandoff) =>
        this.request<{ status: "needs-confirmation" | "completed" }>(
          "handoff.image",
          value,
          [value.pngBytes],
          HANDOFF_REQUEST_TIMEOUT_MS,
        ),
    };
    this.ui = {
      getState: () => this.request<WorkshopUiState>("ui.getState", {}),
    };
    this.status = {
      progress: (value: {
        phase: string;
        completed: number;
        total: number;
      } | null) => this.request<void>("status.progress", value),
      error: (
        value: {
          code: string;
          message: string;
          retryable: boolean;
        } | null,
      ) => this.request<void>("status.error", value),
      diagnostics: (
        value: Record<string, string | number | boolean | null>,
      ) => this.request<void>("status.diagnostics", value),
    };
    this.lifecycle = {
      ready: () => this.request<void>("lifecycle.ready", {}),
    };
  }

  close(): void {
    if (this.closed) {
      return;
    }
    this.closed = true;
    this.port.onmessage = null;
    this.port.onmessageerror = null;
    this.port.close();
    this.rejectAll(
      new WorkshopClientError(
        "CLIENT_CLOSED",
        "The Workshop connection has been closed.",
      ),
    );
  }

  private request<T>(
    method: WorkshopRpcMethod,
    payload: unknown,
    transfer: Transferable[] = [],
    timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
  ): Promise<T> {
    if (this.closed) {
      return Promise.reject(
        new WorkshopClientError(
          "CLIENT_CLOSED",
          "The Workshop connection has been closed.",
        ),
      );
    }

    this.requestSequence += 1;
    const requestId = `req-${this.requestSequence}`;
    const envelope = createRequestEnvelope(requestId, method, payload);

    return new Promise<T>((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(requestId);
        this.rememberTimedOutRequestId(requestId);
        reject(
          new WorkshopClientError(
            "REQUEST_TIMEOUT",
            `Workshop request ${method} timed out.`,
            true,
          ),
        );
      }, timeoutMs);
      this.pending.set(requestId, {
        resolve: (value) => resolve(value as T),
        reject,
        timeout,
      });

      try {
        this.port.postMessage(envelope, transfer);
      } catch (error) {
        clearTimeout(timeout);
        this.pending.delete(requestId);
        reject(
          new WorkshopClientError(
            "REQUEST_SEND_FAILED",
            error instanceof Error
              ? error.message
              : `Workshop request ${method} could not be sent.`,
            true,
          ),
        );
      }
    });
  }

  private handleResponse(value: unknown): void {
    const response = parseResponse(value);
    if (response === null) {
      this.failProtocol(
        new WorkshopClientError(
          "MALFORMED_RESPONSE",
          "The Workshop host sent a malformed response.",
        ),
      );
      return;
    }

    const pending = this.pending.get(response.requestId);
    if (pending === undefined) {
      if (this.locallyTimedOutRequestIds.delete(response.requestId)) {
        return;
      }
      this.failProtocol(
        new WorkshopClientError(
          "DUPLICATE_RESPONSE",
          "The Workshop host sent a duplicate or unknown response.",
        ),
      );
      return;
    }

    clearTimeout(pending.timeout);
    this.pending.delete(response.requestId);
    if (response.ok) {
      pending.resolve(response.result);
      return;
    }
    const error = response.error;
    pending.reject(
      new WorkshopClientError(
        error?.code ?? "HOST_REQUEST_FAILED",
        error?.message ?? "The Workshop host rejected the request.",
        error?.retryable ?? false,
      ),
    );
  }

  private failProtocol(error: WorkshopClientError): void {
    if (this.closed) {
      return;
    }
    this.closed = true;
    this.port.onmessage = null;
    this.port.onmessageerror = null;
    this.port.close();
    this.rejectAll(error);
  }

  private rejectAll(error: WorkshopClientError): void {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timeout);
      pending.reject(error);
    }
    this.pending.clear();
    this.locallyTimedOutRequestIds.clear();
  }

  private rememberTimedOutRequestId(requestId: string): void {
    this.locallyTimedOutRequestIds.add(requestId);
    if (
      this.locallyTimedOutRequestIds.size <=
      MAX_LOCALLY_TIMED_OUT_REQUEST_IDS
    ) {
      return;
    }
    const oldestRequestId = this.locallyTimedOutRequestIds
      .values()
      .next().value;
    if (oldestRequestId !== undefined) {
      this.locallyTimedOutRequestIds.delete(oldestRequestId);
    }
  }
}

export async function connectWorkshop(
  options: ConnectWorkshopOptions,
): Promise<WorkshopClient> {
  const windowObject =
    options.windowObject ??
    (window as unknown as WorkshopWindowLike);
  const handshakeTimeoutMs =
    options.handshakeTimeoutMs ?? DEFAULT_HANDSHAKE_TIMEOUT_MS;

  return new Promise<WorkshopClient>((resolve, reject) => {
    let settled = false;
    const finishWithError = (error: WorkshopClientError) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timeout);
      windowObject.removeEventListener("message", onMessage);
      reject(error);
    };
    const onMessage = (event: MessageEvent) => {
      if (event.source !== windowObject.parent) {
        return;
      }
      if (!isRecord(event.data) || event.data.type !== "lumina.workshop.connect") {
        return;
      }
      if (
        typeof event.data.sessionId !== "string" ||
        event.data.sessionId.length === 0 ||
        event.ports.length !== 1
      ) {
        finishWithError(
          new WorkshopClientError(
            "HANDSHAKE_INVALID",
            "The Workshop host supplied an invalid connection.",
          ),
        );
        return;
      }

      settled = true;
      clearTimeout(timeout);
      windowObject.removeEventListener("message", onMessage);
      resolve(new PortWorkshopClient(event.data.sessionId, event.ports[0]));
    };
    const timeout = setTimeout(() => {
      finishWithError(
        new WorkshopClientError(
          "HANDSHAKE_TIMEOUT",
          "The Workshop host did not connect within 10 seconds.",
          true,
        ),
      );
    }, handshakeTimeoutMs);

    windowObject.addEventListener("message", onMessage);
    try {
      windowObject.parent.postMessage(
        {
          type: "lumina.workshop.ready",
          moduleId: options.moduleId,
          moduleVersion: options.moduleVersion,
          apiVersion: WORKSHOP_API_VERSION,
        },
        "*",
      );
    } catch (error) {
      finishWithError(
        new WorkshopClientError(
          "HANDSHAKE_SEND_FAILED",
          error instanceof Error
            ? error.message
            : "The Workshop ready message could not be sent.",
          true,
        ),
      );
    }
  });
}
