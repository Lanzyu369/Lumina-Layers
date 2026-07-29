import {
  Component,
  useMemo,
  type ErrorInfo,
  type ReactNode,
} from "react";

import Button from "../components/ui/Button";
import {
  PanelIntro,
  StatusBanner,
  cx,
  resolvePanelSurfaceClass,
  resolveSectionCardClass,
} from "../components/ui/panelPrimitives";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { useI18n } from "../i18n/context";
import { translations } from "../i18n/translations";
import { useSettingsStore } from "../stores/settingsStore";
import { createBrowserWorkshopFileServices } from "./browserFiles";
import { WorkshopHostError, createWorkshopHostServices } from "./host";
import {
  OFFICIAL_WORKSHOP_MODULES,
  WORKSHOP_MODULE_WHITELIST,
} from "./modules/bead/manifest";
import {
  createWorkshopProjectStorage,
  type WorkshopProjectStorageResult,
} from "./projectStorage";
import {
  validateWorkshopModules,
  type RegisteredWorkshopModule,
} from "./registry";
import { useWorkshopStore } from "./store";
import type {
  WorkshopHostServices,
  WorkshopModuleManifest,
  WorkshopVisibleError,
} from "./types";

declare const __LUMINA_VERSION__: string | undefined;

let defaultStorageResult: WorkshopProjectStorageResult | null = null;
const defaultFileServices = createBrowserWorkshopFileServices();

function getDefaultStorage(): WorkshopProjectStorageResult {
  defaultStorageResult ??= createWorkshopProjectStorage();
  return defaultStorageResult;
}

function translateFromSettings(key: string): string {
  const language = useSettingsStore.getState().language;
  const entry = translations[key];
  return entry?.[language] ?? entry?.zh ?? key;
}

function reportHostError(error: WorkshopVisibleError | null): void {
  const current = useWorkshopStore.getState().diagnostics;
  if (!error && !current) {
    return;
  }
  useWorkshopStore.getState().setDiagnostics(
    error
      ? {
          projectSchemaVersion:
            current?.projectSchemaVersion ?? "unknown",
          inputMode: current?.inputMode ?? null,
          rows: current?.rows ?? null,
          columns: current?.columns ?? null,
          compression: current?.compression ?? null,
          errorCode: error.code,
        }
      : current
        ? { ...current, errorCode: null }
        : null,
  );
}

function createDefaultHost(
  manifest: WorkshopModuleManifest,
): WorkshopHostServices {
  const storage = getDefaultStorage();
  return createWorkshopHostServices(manifest, {
    storage: storage.storage,
    files: defaultFileServices,
    getLocale: () => useSettingsStore.getState().language,
    getTheme: () => useSettingsStore.getState().theme,
    translate: translateFromSettings,
    onProgress: () => undefined,
    onError: reportHostError,
    onDiagnostics: (_moduleId, _moduleVersion, summary) => {
      useWorkshopStore.getState().setDiagnostics(summary);
    },
    handoffImage: async () => {
      throw new WorkshopHostError(
        "handoff-unavailable",
        "Workshop handoff is not configured yet.",
      );
    },
  });
}

interface WorkshopBoundaryProps {
  children: ReactNode;
  fallback: ReactNode;
}

interface WorkshopBoundaryState {
  failed: boolean;
}

class WorkshopModuleBoundary extends Component<
  WorkshopBoundaryProps,
  WorkshopBoundaryState
> {
  state: WorkshopBoundaryState = { failed: false };

  static getDerivedStateFromError(): WorkshopBoundaryState {
    return { failed: true };
  }

  componentDidCatch(_error: Error, _info: ErrorInfo): void {
    reportHostError({
      code: "module-render-failed",
      message: "Workshop module render failed.",
      retryable: true,
    });
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function BeadGridIcon() {
  return (
    <svg
      aria-hidden="true"
      className="h-8 w-8"
      viewBox="0 0 32 32"
      fill="currentColor"
    >
      {[6, 16, 26].flatMap((x) =>
        [6, 16, 26].map((y) => (
          <circle key={`${x}-${y}`} cx={x} cy={y} r="3.3" />
        )),
      )}
    </svg>
  );
}

function moduleMeta(
  template: string,
  author: string,
  version: string,
): string {
  return template
    .replace("{author}", author)
    .replace("{version}", version);
}

function ModuleCard({
  record,
  onOpen,
  hasProject,
}: {
  record: RegisteredWorkshopModule;
  onOpen(): void;
  hasProject: boolean;
}) {
  const { t, lang } = useI18n();
  const { manifest } = record.definition;

  return (
    <article
      className={cx(
        resolveSectionCardClass("standard"),
        "flex min-h-64 flex-col gap-4",
        !record.enabled && "opacity-60",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex h-14 w-14 items-center justify-center rounded-[20px] bg-blue-100 text-blue-700 dark:bg-blue-950/70 dark:text-blue-300">
          <BeadGridIcon />
        </div>
        <span className="rounded-full border border-blue-200/80 bg-blue-50/80 px-2.5 py-1 text-[11px] font-semibold text-blue-700 dark:border-blue-800/80 dark:bg-blue-950/60 dark:text-blue-300">
          {t("workshop.official")}
        </span>
      </div>

      <div className="min-w-0 flex-1">
        <h3 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
          {manifest.name[lang]}
        </h3>
        <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
          {manifest.description[lang]}
        </p>
        <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
          {moduleMeta(
            t("workshop.moduleMeta"),
            manifest.author,
            manifest.version,
          )}
        </p>
      </div>

      {record.enabled ? (
        <Button
          label={t(hasProject ? "workshop.continue" : "workshop.open")}
          onClick={onOpen}
          className="w-full"
        />
      ) : (
        <StatusBanner tone="warning">
          {t(`workshop.disabled.${record.reason}`)}
        </StatusBanner>
      )}
    </article>
  );
}

export interface WorkshopPanelProps {
  createHost?: (manifest: WorkshopModuleManifest) => WorkshopHostServices;
}

export function WorkshopPanel({
  createHost = createDefaultHost,
}: WorkshopPanelProps) {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  const activeModuleId = useWorkshopStore((state) => state.activeModuleId);
  const lastProjectIds = useWorkshopStore((state) => state.lastProjectIds);
  const pendingRecipeSource = useWorkshopStore(
    (state) => state.pendingRecipeSource,
  );
  const openModule = useWorkshopStore((state) => state.openModule);
  const returnHome = useWorkshopStore((state) => state.returnHome);
  const clearPendingRecipe = useWorkshopStore(
    (state) => state.clearPendingRecipe,
  );

  const registeredModules = useMemo(
    () =>
      validateWorkshopModules(OFFICIAL_WORKSHOP_MODULES, {
        appVersion:
          typeof __LUMINA_VERSION__ === "string"
            ? __LUMINA_VERSION__
            : "0.0.0",
        whitelist: WORKSHOP_MODULE_WHITELIST,
      }),
    [],
  );
  const selected = registeredModules.find(
    (record) =>
      record.enabled && record.definition.manifest.id === activeModuleId,
  );
  const host = useMemo(
    () => (selected ? createHost(selected.definition.manifest) : null),
    [createHost, selected],
  );
  const persistent =
    createHost === createDefaultHost ? getDefaultStorage().persistent : true;

  return (
    <div
      className={cx(
        resolvePanelSurfaceClass(workspace.mode),
        "flex flex-col gap-5",
      )}
    >
      {selected && host ? (
        <div className="mx-auto flex w-full max-w-[96rem] flex-col gap-5">
          <div className="flex items-center justify-between gap-3">
            <button
              type="button"
              onClick={returnHome}
              className="inline-flex min-h-10 items-center gap-2 rounded-xl px-3 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-200/70 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--focus-ring)] dark:text-slate-300 dark:hover:bg-slate-800/70 dark:hover:text-slate-50"
            >
              <span aria-hidden="true">←</span>
              {t("workshop.back")}
            </button>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {moduleMeta(
                t("workshop.moduleMeta"),
                selected.definition.manifest.author,
                selected.definition.manifest.version,
              )}
            </span>
          </div>

          <WorkshopModuleBoundary
            fallback={
              <StatusBanner
                tone="error"
                title={t("workshop.moduleErrorTitle")}
                action={
                  <Button
                    label={t("workshop.back")}
                    variant="secondary"
                    size="sm"
                    onClick={returnHome}
                  />
                }
              >
                {t("workshop.moduleErrorDescription")}
              </StatusBanner>
            }
          >
            <selected.definition.Component
              manifest={selected.definition.manifest}
              host={host}
              pendingRecipeSource={pendingRecipeSource}
              clearPendingRecipe={clearPendingRecipe}
            />
          </WorkshopModuleBoundary>
        </div>
      ) : (
        <div className="mx-auto flex w-full max-w-[96rem] flex-col gap-5">
          <PanelIntro
            eyebrow="Lumina Studio"
            title={t("workshop.title")}
            description={t("workshop.description")}
          />
          <StatusBanner tone="info">{t("workshop.localOnly")}</StatusBanner>
          {!persistent && (
            <StatusBanner tone="warning">
              {t("workshop.persistenceUnavailable")}
            </StatusBanner>
          )}
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            {registeredModules.map((record) => (
              <ModuleCard
                key={record.definition.manifest.id}
                record={record}
                hasProject={Boolean(
                  lastProjectIds[record.definition.manifest.id],
                )}
                onOpen={() =>
                  openModule(record.definition.manifest.id)
                }
              />
            ))}
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t("workshop.capabilityManaged")}
          </p>
        </div>
      )}
    </div>
  );
}

export default WorkshopPanel;
