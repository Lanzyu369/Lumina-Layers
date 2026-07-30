import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { useI18n } from "../../i18n/context";
import {
  WORKSHOP_API_VERSION,
  type WorkshopPermissionName,
} from "../contracts";
import {
  canRunWorkshopInBrowser,
  desktopModuleUrl,
  injectWorkshopRuntimeCsp,
  isWorkshopApiCompatible,
  WORKSHOP_HANDSHAKE_TIMEOUT_MS,
  type WorkshopApiRange,
  type WorkshopInstallSource,
  type WorkshopRuntimeMode,
  type WorkshopStartupFailure,
  type WorkshopStartupFailureReason,
} from "./health";
import {
  createWorkshopRpcHost,
  type WorkshopMessagePort,
  type WorkshopRpcHandler,
  type WorkshopRpcHandlers,
  type WorkshopRpcHost,
} from "./rpcHost";

export interface WorkshopFrameModule {
  moduleId: string;
  moduleVersion: string;
  displayName: string;
  source: WorkshopInstallSource;
  official: boolean;
  enabled: boolean;
  runtimeUrl: string | null;
  browserRuntimeHtml?: string | null;
  workshopApi: WorkshopApiRange;
  permissions: readonly WorkshopPermissionName[];
  candidate: boolean;
  previousVersion: string | null;
  consecutiveStartFailures: number;
}

export interface WorkshopFrameChannel {
  port1: WorkshopMessagePort;
  port2: MessagePort;
}

export interface WorkshopFrameProps {
  module: WorkshopFrameModule;
  runtimeMode?: WorkshopRuntimeMode;
  handlers?: WorkshopRpcHandlers;
  syntheticHandlers?: WorkshopRpcHandlers;
  createChannel?: () => WorkshopFrameChannel;
  loadBrowserRuntime?: (url: string) => Promise<string>;
  prepareCandidate?: (
    moduleId: string,
    moduleVersion: string,
  ) => void | Promise<void>;
  activateCandidate?: (
    moduleId: string,
    moduleVersion: string,
  ) => void | Promise<void>;
  onStartSuccess?: (
    moduleId: string,
    moduleVersion: string,
  ) => void | Promise<void>;
  onStartFailure?: (
    failure: WorkshopStartupFailure,
  ) => void | Promise<void>;
  disableVersion?: (
    moduleId: string,
    moduleVersion: string,
  ) => void | Promise<void>;
}

type RuntimePhase =
  | "preparing"
  | "loading"
  | "handshaking"
  | "connected"
  | "ready"
  | "failed"
  | "desktop-required"
  | "disabled"
  | "incompatible";

interface RuntimeDocument {
  src?: string;
  srcDoc?: string;
}

interface RuntimeProgress {
  phase: string;
  completed: number;
  total: number;
}

interface RuntimeError {
  code: string;
  message: string;
  retryable: boolean;
}

const EMPTY_HANDLERS: WorkshopRpcHandlers = Object.freeze({});

function defaultCreateChannel(): WorkshopFrameChannel {
  const channel = new MessageChannel();
  return {
    port1: channel.port1,
    port2: channel.port2,
  };
}

async function defaultLoadBrowserRuntime(
  url: string,
): Promise<string> {
  const response = await fetch(url, {
    cache: "no-store",
    credentials: "same-origin",
    redirect: "error",
  });
  if (!response.ok) {
    throw new Error(
      `Workshop runtime returned HTTP ${response.status}.`,
    );
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("text/html")) {
    throw new Error("Workshop runtime did not return HTML.");
  }
  return response.text();
}

function createSessionId(): string {
  if (typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
}

function readyMessage(
  value: unknown,
  moduleId: string,
  moduleVersion: string,
): boolean {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value)
  ) {
    return false;
  }
  const message = value as Record<string, unknown>;
  return (
    message.type === "lumina.workshop.ready" &&
    message.moduleId === moduleId &&
    message.moduleVersion === moduleVersion &&
    message.apiVersion === WORKSHOP_API_VERSION
  );
}

function progressValue(value: unknown): RuntimeProgress | null {
  if (value === null) {
    return null;
  }
  return value as RuntimeProgress;
}

function errorValue(value: unknown): RuntimeError | null {
  if (value === null) {
    return null;
  }
  return value as RuntimeError;
}

export function WorkshopFrame({
  module,
  runtimeMode = "browser",
  handlers = EMPTY_HANDLERS,
  syntheticHandlers = EMPTY_HANDLERS,
  createChannel = defaultCreateChannel,
  loadBrowserRuntime = defaultLoadBrowserRuntime,
  prepareCandidate,
  activateCandidate,
  onStartSuccess,
  onStartFailure,
  disableVersion,
}: WorkshopFrameProps) {
  const { t } = useI18n();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const handshakeTimerRef = useRef<ReturnType<
    typeof setTimeout
  > | null>(null);
  const hostRef = useRef<WorkshopRpcHost | null>(null);
  const detachPortRef = useRef<(() => void) | null>(null);
  const handshakeAcceptedRef = useRef(false);
  const frameLoadedRef = useRef(false);
  const failureHandledRef = useRef(false);
  const mountedRef = useRef(true);
  const prepareCandidateRef = useRef(prepareCandidate);
  const onStartFailureRef = useRef(onStartFailure);
  const disableVersionRef = useRef(disableVersion);
  const [runtimeDocument, setRuntimeDocument] =
    useState<RuntimeDocument | null>(null);
  const [phase, setPhase] = useState<RuntimePhase>("preparing");
  const [failureReason, setFailureReason] =
    useState<WorkshopStartupFailureReason | null>(null);
  const [progress, setProgress] =
    useState<RuntimeProgress | null>(null);
  const [moduleError, setModuleError] =
    useState<RuntimeError | null>(null);
  const runtimeModuleId = module.moduleId;
  const runtimeModuleVersion = module.moduleVersion;
  const runtimeModuleCandidate = module.candidate;
  const runtimeApiMin = module.workshopApi.min;
  const runtimeApiMaxExclusive =
    module.workshopApi.maxExclusive;
  const runtimePermissionsJson = JSON.stringify(
    module.permissions,
  );

  useEffect(() => {
    prepareCandidateRef.current = prepareCandidate;
  }, [prepareCandidate]);

  useEffect(() => {
    onStartFailureRef.current = onStartFailure;
    disableVersionRef.current = disableVersion;
  }, [disableVersion, onStartFailure]);

  const clearHandshakeTimer = useCallback(() => {
    if (handshakeTimerRef.current === null) {
      return;
    }
    clearTimeout(handshakeTimerRef.current);
    handshakeTimerRef.current = null;
  }, []);

  const closeConnection = useCallback(() => {
    clearHandshakeTimer();
    const detach = detachPortRef.current;
    detachPortRef.current = null;
    detach?.();
    hostRef.current?.close();
    hostRef.current = null;
  }, [clearHandshakeTimer]);

  const failStartup = useCallback(
    (reason: WorkshopStartupFailureReason) => {
      if (failureHandledRef.current) {
        return;
      }
      failureHandledRef.current = true;
      closeConnection();
      setRuntimeDocument(null);
      setFailureReason(reason);
      setPhase("failed");
      const consecutiveFailures = Math.min(
        3,
        module.consecutiveStartFailures + 1,
      );
      const failure: WorkshopStartupFailure = {
        moduleId: module.moduleId,
        moduleVersion: module.moduleVersion,
        reason,
        consecutiveFailures,
      };
      void Promise.resolve(
        onStartFailureRef.current?.(failure),
      ).finally(() => {
        if (
          consecutiveFailures >= 3 &&
          module.previousVersion === null
        ) {
          void disableVersionRef.current?.(
            module.moduleId,
            module.moduleVersion,
          );
        }
      });
    },
    [
      closeConnection,
      module.consecutiveStartFailures,
      module.moduleId,
      module.moduleVersion,
      module.previousVersion,
    ],
  );

  useEffect(() => {
    mountedRef.current = true;
    handshakeAcceptedRef.current = false;
    frameLoadedRef.current = false;
    failureHandledRef.current = false;
    setRuntimeDocument(null);
    setFailureReason(null);
    setProgress(null);
    setModuleError(null);

    let cancelled = false;
    const prepare = async () => {
      if (!module.enabled) {
        setPhase("disabled");
        return;
      }
      if (
        !isWorkshopApiCompatible({
          min: runtimeApiMin,
          maxExclusive: runtimeApiMaxExclusive,
        })
      ) {
        setPhase("incompatible");
        return;
      }
      if (
        !canRunWorkshopInBrowser(
          module.source,
          module.official,
          runtimeMode,
        )
      ) {
        setPhase("desktop-required");
        return;
      }
      setPhase("preparing");
      if (module.candidate) {
        if (prepareCandidateRef.current === undefined) {
          failStartup("candidate-prepare-failed");
          return;
        }
        try {
          await prepareCandidateRef.current(
            module.moduleId,
            module.moduleVersion,
          );
        } catch {
          failStartup("candidate-prepare-failed");
          return;
        }
      }
      if (cancelled) {
        return;
      }
      setPhase("loading");
      if (runtimeMode === "desktop-secure") {
        setRuntimeDocument({
          src: desktopModuleUrl(
            module.moduleId,
            module.moduleVersion,
          ),
        });
        return;
      }
      try {
        const html =
          module.browserRuntimeHtml ??
          (module.runtimeUrl === null
            ? null
            : await loadBrowserRuntime(module.runtimeUrl));
        if (html === null) {
          throw new Error("Workshop runtime HTML is unavailable.");
        }
        const srcDoc = injectWorkshopRuntimeCsp(html);
        if (!cancelled) {
          setRuntimeDocument({ srcDoc });
        }
      } catch {
        if (!cancelled) {
          failStartup("runtime-load-failed");
        }
      }
    };

    void prepare();
    return () => {
      cancelled = true;
      mountedRef.current = false;
      closeConnection();
    };
  }, [
    closeConnection,
    failStartup,
    loadBrowserRuntime,
    module.browserRuntimeHtml,
    module.candidate,
    module.enabled,
    module.moduleId,
    module.moduleVersion,
    module.official,
    module.runtimeUrl,
    module.source,
    runtimeApiMaxExclusive,
    runtimeApiMin,
    runtimeMode,
  ]);

  const handleFrameLoad = useCallback(() => {
    if (
      runtimeDocument === null ||
      failureHandledRef.current ||
      handshakeAcceptedRef.current
    ) {
      return;
    }
    frameLoadedRef.current = true;
    setPhase("handshaking");
    clearHandshakeTimer();
    handshakeTimerRef.current = setTimeout(() => {
      failStartup("handshake-timeout");
    }, WORKSHOP_HANDSHAKE_TIMEOUT_MS);
  }, [
    clearHandshakeTimer,
    failStartup,
    runtimeDocument,
  ]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (
        !frameLoadedRef.current ||
        handshakeAcceptedRef.current ||
        failureHandledRef.current ||
        event.source !== iframeRef.current?.contentWindow ||
        !readyMessage(
          event.data,
          runtimeModuleId,
          runtimeModuleVersion,
        ) ||
        !isWorkshopApiCompatible({
          min: runtimeApiMin,
          maxExclusive: runtimeApiMaxExclusive,
        })
      ) {
        return;
      }
      handshakeAcceptedRef.current = true;
      clearHandshakeTimer();

      const selectedHandlers =
        runtimeMode === "browser-unsafe-development"
          ? syntheticHandlers
          : handlers;
      const upstreamProgress = selectedHandlers[
        "status.progress"
      ] as WorkshopRpcHandler | undefined;
      const upstreamError = selectedHandlers[
        "status.error"
      ] as WorkshopRpcHandler | undefined;
      const upstreamReady = selectedHandlers[
        "lifecycle.ready"
      ] as WorkshopRpcHandler | undefined;
      const runtimeHandlers: WorkshopRpcHandlers = {
        ...selectedHandlers,
        "status.progress": async (payload, context) => {
          if (mountedRef.current) {
            setProgress(progressValue(payload));
          }
          return upstreamProgress?.(payload, context);
        },
        "status.error": async (payload, context) => {
          if (mountedRef.current) {
            setModuleError(errorValue(payload));
          }
          return upstreamError?.(payload, context);
        },
        "lifecycle.ready": async (payload, context) => {
          await upstreamReady?.(payload, context);
          try {
            if (runtimeModuleCandidate) {
              if (activateCandidate === undefined) {
                throw new Error(
                  "Candidate activation is unavailable.",
                );
              }
              await activateCandidate(
                runtimeModuleId,
                runtimeModuleVersion,
              );
            }
            await onStartSuccess?.(
              runtimeModuleId,
              runtimeModuleVersion,
            );
          } catch (error) {
            failStartup("activation-failed");
            throw error;
          }
          if (mountedRef.current) {
            setPhase("ready");
          }
          return undefined;
        },
      };

      let host: WorkshopRpcHost | null = null;
      let channel: WorkshopFrameChannel | null = null;
      try {
        host = createWorkshopRpcHost({
          identity: {
            moduleId: runtimeModuleId,
            moduleVersion: runtimeModuleVersion,
          },
          permissions: new Set(
            JSON.parse(
              runtimePermissionsJson,
            ) as WorkshopPermissionName[],
          ),
          handlers: runtimeHandlers,
        });
        channel = createChannel();
        detachPortRef.current = host.attach(channel.port1);
        hostRef.current = host;
        iframeRef.current?.contentWindow?.postMessage(
          {
            type: "lumina.workshop.connect",
            sessionId: createSessionId(),
          },
          "*",
          [channel.port2],
        );
        setPhase("connected");
      } catch {
        host?.close();
        channel?.port2.close();
        failStartup("runtime-load-failed");
      }
    };

    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
    };
  }, [
    activateCandidate,
    clearHandshakeTimer,
    createChannel,
    failStartup,
    handlers,
    onStartSuccess,
    runtimeApiMaxExclusive,
    runtimeApiMin,
    runtimeModuleCandidate,
    runtimeModuleId,
    runtimeModuleVersion,
    runtimePermissionsJson,
    runtimeMode,
    syntheticHandlers,
  ]);

  const statusLabel =
    phase === "ready"
      ? t("workshop_runtime_running")
      : phase === "connected"
        ? t("workshop_runtime_waiting_ready")
        : phase === "handshaking"
          ? t("workshop_runtime_handshaking")
          : phase === "loading"
            ? t("workshop_runtime_loading")
            : t("workshop_runtime_preparing");

  if (phase === "desktop-required") {
    return (
      <div role="status" className="rounded-lg border border-[color:var(--surface-outline)] bg-[color:var(--surface-section-muted)] p-4 text-sm text-slate-600 dark:text-slate-300">
        {t("workshop_runtime_desktop_required")}
      </div>
    );
  }
  if (phase === "disabled") {
    return (
      <div role="status" className="rounded-lg border border-[color:var(--surface-outline)] bg-[color:var(--surface-section-muted)] p-4 text-sm text-slate-600 dark:text-slate-300">
        {t("workshop_runtime_disabled")}
      </div>
    );
  }
  if (phase === "incompatible") {
    return (
      <div role="alert" className="rounded-lg border border-[color:var(--surface-outline)] bg-[color:var(--surface-section-muted)] p-4 text-sm text-slate-600 dark:text-slate-300">
        {t("workshop_runtime_incompatible")}
      </div>
    );
  }
  if (phase === "failed") {
    const failureLabel =
      failureReason === "handshake-timeout"
        ? t("workshop_runtime_handshake_timeout")
        : failureReason === "candidate-prepare-failed"
          ? t("workshop_runtime_snapshot_failed")
          : failureReason === "activation-failed"
            ? t("workshop_runtime_activation_failed")
            : t("workshop_runtime_load_failed");
    return (
      <div role="alert" className="rounded-lg border border-[color:var(--surface-outline)] bg-[color:var(--surface-section-muted)] p-4 text-sm text-slate-600 dark:text-slate-300">
        {failureLabel}
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="flex min-h-7 items-center justify-between gap-3 text-xs text-slate-500 dark:text-slate-400">
        <span>{statusLabel}</span>
        {progress ? (
          <span
            role="status"
            className="flex min-w-0 items-center gap-2"
          >
            <span className="max-w-48 truncate">{progress.phase}</span>
            <span>
              {progress.completed} / {progress.total}
            </span>
          </span>
        ) : null}
      </div>
      {moduleError ? (
        <div
          role="alert"
          className="rounded-lg border border-[color:var(--surface-outline)] bg-[color:var(--surface-section-muted)] px-3 py-2 text-xs text-slate-600 dark:text-slate-300"
        >
          {moduleError.message}
        </div>
      ) : null}
      {runtimeDocument ? (
        <iframe
          ref={iframeRef}
          key={`${module.moduleId}@${module.moduleVersion}`}
          title={module.displayName}
          src={runtimeDocument.src}
          srcDoc={runtimeDocument.srcDoc}
          sandbox="allow-scripts"
          referrerPolicy="no-referrer"
          loading="eager"
          onLoad={handleFrameLoad}
          className="min-h-[560px] w-full flex-1 rounded-lg border border-[color:var(--surface-outline)] bg-[color:var(--surface-panel)]"
        />
      ) : null}
    </div>
  );
}
