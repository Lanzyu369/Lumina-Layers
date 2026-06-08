import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { motion } from "framer-motion";

import {
  approveMaterialRegistryPackage,
  fetchMaterialSyncStatus,
  refreshMaterialSyncFromRegistry,
  rollbackMaterialSyncRevision,
  uploadMaterialRegistryPackage,
} from "../api/materialSync";
import type {
  MaterialRegistryPackageMutationResponse,
  MaterialSyncInstalledEntry,
  MaterialSyncStatusResponse,
} from "../api/types";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { useI18n } from "../i18n/context";
import { tRuntime } from "../i18n/runtime";
import Button from "./ui/Button";
import {
  StatusBanner,
  mutedSectionCardClass,
  resolvePanelSurfaceClass,
  resolveSectionCardClass,
} from "./ui/panelPrimitives";

const formatBytes = (bytes: number): string => {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
};

export default function MaterialCloudSyncPanel() {
  const { t, lang } = useI18n();
  const workspace = useWorkspaceMode();
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const [status, setStatus] = useState<MaterialSyncStatusResponse | null>(null);
  const [lastUploaded, setLastUploaded] = useState<MaterialRegistryPackageMutationResponse | null>(null);
  const [officialPassword, setOfficialPassword] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [pendingRollback, setPendingRollback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const dateFormatter = useMemo(
    () => new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
      dateStyle: "medium",
      timeStyle: "short",
    }),
    [lang],
  );

  const formatDate = useCallback((value: string | null | undefined) => {
    if (!value) {
      return "-";
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return value;
    }
    return dateFormatter.format(parsed);
  }, [dateFormatter]);

  const refreshStatus = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetchMaterialSyncStatus();
      setStatus(response);
      return response;
    } catch (err) {
      setError(err instanceof Error ? err.message : t("mat_sync_status_failed"));
      setStatus(null);
      return null;
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  const handleRefreshFromRegistry = useCallback(async () => {
    setIsRefreshing(true);
    setError(null);
    setSuccess(null);
    try {
      const response = await refreshMaterialSyncFromRegistry();
      await refreshStatus();
      setSuccess(response.message || t("mat_sync_refresh_success"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("mat_sync_refresh_failed"));
    } finally {
      setIsRefreshing(false);
    }
  }, [refreshStatus, t]);

  const handleRollback = useCallback(async (entry: MaterialSyncInstalledEntry, revisionId: string) => {
    const rollbackKey = `${entry.material_id}:${revisionId}`;
    setPendingRollback(rollbackKey);
    setError(null);
    setSuccess(null);
    try {
      const response = await rollbackMaterialSyncRevision(entry.material_id, revisionId);
      await refreshStatus();
      setSuccess(response.message || t("mat_sync_rollback_success"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("mat_sync_rollback_failed"));
    } finally {
      setPendingRollback(null);
    }
  }, [refreshStatus, t]);

  const handleUploadPackage = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    event.target.value = "";
    if (!file) {
      return;
    }
    setIsUploading(true);
    setError(null);
    setSuccess(null);
    try {
      const response = await uploadMaterialRegistryPackage(file);
      setLastUploaded(response);
      setSuccess(response.message || t("mat_sync_upload_success"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("mat_sync_upload_failed"));
    } finally {
      setIsUploading(false);
    }
  }, [t]);

  const handleApproveOfficial = useCallback(async () => {
    if (!lastUploaded || !officialPassword.trim()) {
      return;
    }
    setIsApproving(true);
    setError(null);
    setSuccess(null);
    try {
      const response = await approveMaterialRegistryPackage(
        lastUploaded.package_path,
        officialPassword.trim(),
      );
      setLastUploaded(response);
      setOfficialPassword("");
      setSuccess(response.message || t("mat_sync_approve_success"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("mat_sync_approve_failed"));
    } finally {
      setIsApproving(false);
    }
  }, [lastUploaded, officialPassword, t]);

  const syncIndexStateLabel = status
    ? t(`mat_sync_state_${status.index_state}`)
    : t("mat_sync_state_unknown");

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      data-testid="material-cloud-sync-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-5`}
    >
      <input
        ref={uploadInputRef}
        type="file"
        accept=".zip,application/zip"
        className="hidden"
        data-testid="material-cloud-upload-input"
        onChange={(event) => void handleUploadPackage(event)}
      />

      <section className={`${mutedSectionCardClass} grid gap-4 px-4 py-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center`}>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-900 dark:text-slate-50">
            {t("mat_sync_title")}
          </p>
          <dl className="mt-3 grid gap-3 sm:grid-cols-3">
            <div className="min-w-0">
              <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                {t("mat_sync_index_state_label")}
              </dt>
              <dd className="mt-1 truncate text-sm font-semibold text-slate-900 dark:text-slate-50">
                {syncIndexStateLabel}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                {t("mat_sync_installed_count_label")}
              </dt>
              <dd
                data-testid="material-cloud-sync-installed-count"
                className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-50"
              >
                {status?.installed_count ?? 0}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                {t("mat_sync_last_sync_label")}
              </dt>
              <dd className="mt-1 truncate text-sm font-semibold text-slate-900 dark:text-slate-50">
                {formatDate(status?.last_sync_at)}
              </dd>
            </div>
          </dl>
        </div>
        <Button
          label={t("mat_sync_refresh_btn")}
          variant="secondary"
          onClick={() => void handleRefreshFromRegistry()}
          disabled={isLoading || isRefreshing}
          loading={isRefreshing}
          className="w-full lg:w-auto"
        />
      </section>

      <section className={`${resolveSectionCardClass(workspace.mode)} grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end`}>
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">
            {t("mat_sync_upload_title")}
          </h3>
          {lastUploaded ? (
            <dl className="mt-3 grid gap-2 text-sm text-slate-600 dark:text-slate-300">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <dt className="font-semibold">{t("mat_sync_package_path_label")}</dt>
                <dd className="break-all font-mono text-xs">{lastUploaded.package_path}</dd>
              </div>
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <dt className="font-semibold">{t("mat_sync_package_size_label")}</dt>
                <dd>{formatBytes(lastUploaded.package_bytes)}</dd>
              </div>
            </dl>
          ) : (
            <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
              {t("mat_sync_upload_empty")}
            </p>
          )}
        </div>
        <div className="grid gap-3 sm:grid-cols-[minmax(0,14rem)_auto_auto]">
          <input
            data-testid="material-cloud-official-password-input"
            type="password"
            value={officialPassword}
            onChange={(event) => setOfficialPassword(event.target.value)}
            placeholder={t("mat_sync_official_password_placeholder")}
            className="min-h-10 rounded-2xl border border-slate-200/80 bg-[var(--surface-panel)] px-3 py-2 text-sm text-slate-800 outline-none shadow-[var(--shadow-control)] focus:border-blue-400 focus:ring-4 focus:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:text-slate-100"
          />
          <Button
            label={t("mat_sync_upload_btn")}
            variant="secondary"
            onClick={() => uploadInputRef.current?.click()}
            disabled={isUploading || isApproving}
            loading={isUploading}
            className="w-full"
          />
          <Button
            label={t("mat_sync_approve_official_btn")}
            onClick={() => void handleApproveOfficial()}
            disabled={!lastUploaded || !officialPassword.trim() || isApproving || isUploading}
            loading={isApproving}
            className="w-full"
          />
        </div>
      </section>

      {error ? (
        <StatusBanner data-testid="material-cloud-sync-error" tone="error">
          {error}
        </StatusBanner>
      ) : null}
      {success ? (
        <StatusBanner data-testid="material-cloud-sync-success" tone="success">
          {success}
        </StatusBanner>
      ) : null}

      {isLoading ? (
        <section className={`${mutedSectionCardClass} flex min-h-40 items-center justify-center`}>
          <p className="text-sm text-slate-500 dark:text-slate-400">{t("mat_gradient_library_loading")}</p>
        </section>
      ) : (
        <div className="grid gap-4">
          {(status?.installed ?? []).map((entry) => {
            const rollbackRevisions = entry.available_revisions.filter(
              (revisionId) => revisionId && revisionId !== entry.revision_id,
            );
            return (
              <section
                key={entry.material_id}
                className={`${resolveSectionCardClass(workspace.mode)} grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center`}
              >
                <div className="min-w-0">
                  <h3 className="flex min-w-0 flex-wrap items-center gap-2 text-base font-semibold text-slate-900 dark:text-slate-50">
                    {entry.channel === "official" ? (
                      <span
                        data-testid="material-cloud-official-badge"
                        className="rounded-full border border-amber-300 bg-amber-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-amber-800 dark:border-amber-400/60 dark:bg-amber-500/15 dark:text-amber-200"
                      >
                        {t("mat_sync_official_badge")}
                      </span>
                    ) : null}
                    <span className="truncate">{entry.display_name || entry.local_directory}</span>
                  </h3>
                  <dl className="mt-3 grid gap-3 sm:grid-cols-3">
                    <div className="min-w-0">
                      <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                        {t("mat_sync_material_id_label")}
                      </dt>
                      <dd className="mt-1 break-all font-mono text-xs text-slate-700 dark:text-slate-200">
                        {entry.material_id}
                      </dd>
                    </div>
                    <div className="min-w-0">
                      <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                        {t("mat_sync_revision_label")}
                      </dt>
                      <dd className="mt-1 break-all font-mono text-xs text-slate-700 dark:text-slate-200">
                        {entry.revision_id}
                      </dd>
                    </div>
                    <div className="min-w-0">
                      <dt className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                        {t("mat_gradient_library_directory_label")}
                      </dt>
                      <dd className="mt-1 break-all text-xs font-semibold text-slate-700 dark:text-slate-200">
                        {entry.local_directory}
                      </dd>
                    </div>
                  </dl>
                </div>
                <div className="grid gap-2">
                  {rollbackRevisions.length > 0 ? rollbackRevisions.map((revisionId) => (
                    <Button
                      key={revisionId}
                      label={tRuntime("mat_sync_rollback_btn", { revisionId })}
                      variant="secondary"
                      onClick={() => void handleRollback(entry, revisionId)}
                      disabled={pendingRollback !== null}
                      loading={pendingRollback === `${entry.material_id}:${revisionId}`}
                      className="w-full"
                    />
                  )) : (
                    <span className="text-sm text-slate-500 dark:text-slate-400">
                      {t("mat_sync_no_rollback")}
                    </span>
                  )}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </motion.aside>
  );
}
