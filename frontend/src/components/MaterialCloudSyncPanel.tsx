import TransientBanner from "./ui/TransientBanner";
import { LibraryIdentity, LibraryFields } from "./ui/LibraryDetails";
import CloudLibraryPreview from "./ui/CloudLibraryPreview";
import { resolveCatalogDisplay, resolveCatalogFitError, resolveCatalogChannel, formatBytes, toRgbCss } from "./materialCloud/catalogModel";
import { useCallback, useState } from "react";

import { useI18n } from "../i18n/context";
import MaterialCloudHistoryDialog from "./materialCloud/MaterialCloudHistoryDialog";
import { CATALOG_FILTERS, catalogEntryKey } from "./materialCloud/catalogModel";
import {
  useMaterialCloudCatalog,
} from "./materialCloud/useMaterialCloudCatalog";
import Button from "./ui/Button";
import Pagination from "./ui/Pagination";
import CloseButton from "./ui/CloseButton";
import {
  StatusBanner,
  wellClass,
} from "./ui/panelPrimitives";

const SKELETON_CARD_COUNT = 6;
const CATALOG_GRID_CLASS =
  "grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,17.5rem),1fr))]";

function CatalogSkeleton({ label }: { label: string }) {
  return (
    <div role="status" aria-live="polite" className={CATALOG_GRID_CLASS}>
      <span className="sr-only">{label}</span>
      {Array.from({ length: SKELETON_CARD_COUNT }, (_, index) => (
        <div key={index} aria-hidden="true" className={`${wellClass} flex animate-pulse flex-col gap-4 p-4`}>
          <div className="flex gap-3">
            <div className="h-14 w-14 rounded-lg bg-slate-300/50 dark:bg-slate-600/40" />
            <div className="flex-1 space-y-2 pt-1">
              <div className="h-3 w-3/4 rounded bg-slate-300/50 dark:bg-slate-600/40" />
              <div className="h-3 w-1/2 rounded bg-slate-300/40 dark:bg-slate-600/30" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {Array.from({ length: 4 }, (__, cell) => (
              <div key={cell} className="h-8 rounded bg-slate-300/40 dark:bg-slate-600/30" />
            ))}
          </div>
          <div className="h-11 rounded-[10px] bg-slate-300/40 dark:bg-slate-600/30" />
        </div>
      ))}
    </div>
  );
}

/**
 * Cloud material library page: browse the Registry catalog page by page,
 * install or update materials, and roll back local revisions.
 * 云端耗材库页面：分页浏览 Registry 目录，安装/更新耗材，回滚本地版本。
 */
export default function MaterialCloudSyncPanel() {
  const { t } = useI18n();
  const catalog = useMaterialCloudCatalog();
  const [showHistory, setShowHistory] = useState(false);
  const [historyMaterial, setHistoryMaterial] = useState<string | null>(null);
  const { dismissSuccess, success, view } = catalog;
  const handlePageChange = useCallback((nextPage: number) => {
    void catalog.goToPage(nextPage);
  }, [catalog]);

  const isListBusy = catalog.isLoading || catalog.isPageLoading || catalog.isSearchPending;
  const paginationDisabled = isListBusy || catalog.pendingInstall !== null;

  const renderCatalogBody = () => {
    if (view.kind === "loading") {
      return <CatalogSkeleton label={t("mat_gradient_library_loading")} />;
    }
    if (view.kind === "full_catalog_failed") {
      return (
        <StatusBanner
          data-testid="material-cloud-full-catalog-failed"
          tone="warning"
          action={(
            <Button
              label={t("mat_sync_full_catalog_retry_btn")}
              variant="secondary"
              size="sm"
              onClick={catalog.retryFullCatalog}
            />
          )}
        >
          {t("mat_sync_full_catalog_failed")}
        </StatusBanner>
      );
    }
    return null;
  };

  const entries = view.kind === "entries" ? view.entries : [];
  return <><CloudLibraryPreview emptyMessage={t("mat_sync_catalog_empty")} busy={isListBusy || view.kind !== "entries"} resetKey={`${catalog.searchQuery}:${catalog.activeFilter}:${view.kind === "entries" ? view.page : 0}`}
    toolbar={<>
      <input type="search" aria-label={t("mat_sync_search_placeholder")} placeholder={t("mat_sync_search_placeholder")} value={catalog.searchQuery} onChange={(event) => catalog.handleSearchQueryChange(event.target.value)} className="min-w-48 flex-1 rounded-lg bg-slate-100 px-4 py-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:bg-slate-800" />
      <div className="flex flex-wrap gap-2" role="group" aria-label={t("mat_sync_filter_group_label")}>{CATALOG_FILTERS.map((filter) => <button key={filter} type="button" aria-pressed={catalog.activeFilter === filter} onClick={() => catalog.selectFilter(filter)} className={`rounded-lg px-3 py-2 text-xs focus-visible:ring-2 focus-visible:ring-blue-500 ${catalog.activeFilter === filter ? "bg-slate-200 dark:bg-slate-700" : "bg-slate-100 dark:bg-slate-800"}`}>{t(`mat_sync_filter_${filter}`)} {catalog.filterCounts[filter] ?? "…"}</button>)}</div>
      <Button label={t("mat_sync_local_section_title")} variant="secondary" onClick={() => { setHistoryMaterial(null); setShowHistory(true); }} />
      <Button label={t("mat_sync_refresh_btn")} variant="secondary" loading={catalog.isRefreshing} disabled={catalog.isLoading} onClick={() => void catalog.refreshCatalog()} />
    </>}
    notices={<>{catalog.error && <StatusBanner data-testid="material-cloud-sync-error" tone="error" action={<CloseButton label={t("mat_sync_dismiss_btn")} onClick={catalog.dismissError} />}>{catalog.error}</StatusBanner>}<TransientBanner data-testid="material-cloud-sync-notice" tone="info" autoDismiss={false} message={catalog.notice} /><TransientBanner data-testid="material-cloud-sync-success" message={success} onDismiss={dismissSuccess} />{view.kind !== "entries" && renderCatalogBody()}</>}
    footer={view.kind === "entries" && <><span className="text-xs text-slate-500">{t("cloud_library_results")} · {view.total}</span>{view.pageCount > 1 && <Pagination page={view.page} pageCount={view.pageCount} onPageChange={handlePageChange} disabled={paginationDisabled} showJump={view.pageCount > 7} />}</>}
    items={entries.map((entry) => {
      const display = resolveCatalogDisplay(entry);
      const fit = resolveCatalogFitError(entry);
      const state = catalog.resolveEntryInstallState(entry);
      const key = catalogEntryKey(entry);
      return { key, name: display.name, subtitle: [display.brand, display.materialType].filter(Boolean).join(" · "), color: display.rgb ? toRgbCss(display.rgb) : undefined,
        metric: fit.meanDeltaE === null ? t("mat_sync_fit_error_missing") : `${t("mat_sync_fit_error_label")} ${fit.meanDeltaE.toFixed(2)}`,
        state: t(`mat_sync_catalog_state_${state}`),
        action: state === "installed" || state === "local_available" ? undefined : <Button label={t(state === "update_available" ? "cloud_library_update" : "mat_sync_install_btn")} variant="secondary" loading={catalog.pendingInstall === key} disabled={catalog.pendingInstall !== null} onClick={() => void catalog.installEntry(entry)} />,
        detail: <div className="grid gap-5">
          <LibraryIdentity name={display.name} subtitle={[display.brand, display.materialType].filter(Boolean).join(" · ")} color={display.rgb ? toRgbCss(display.rgb) : undefined} />
          <LibraryFields rows={[
            { label: t("mat_sync_fit_error_label"), value: fit.meanDeltaE?.toFixed(2) ?? "—" },
            ...(fit.layerHeightMm !== null ? [{ label: t("mat_gradient_library_layer_height_label"), value: `${fit.layerHeightMm} mm` }] : []),
            ...(fit.verificationCount !== null ? [{ label: t("mat_gradient_library_verification_count_label"), value: fit.verificationCount }] : []),
          ]} />
          <LibraryFields rows={[
            { label: t("mat_sync_catalog_state_label"), value: t(`mat_sync_catalog_state_${state}`) },
          { label: t("mat_sync_channel_label"), value: resolveCatalogChannel(entry) === "other" ? entry.channel : t(`mat_sync_channel_${resolveCatalogChannel(entry)}`) },
            { label: t("mat_sync_package_size_label"), value: formatBytes(entry.package_bytes) },
            ...(catalog.resolveLocalDirectory(entry) ? [{ label: t("mat_gradient_library_directory_label"), value: catalog.resolveLocalDirectory(entry), multiline: true }] : []),
          ]} />
            {state !== "installed" && state !== "local_available" && <Button label={t(state === "update_available" ? "cloud_library_update" : "mat_sync_install_btn")} variant="secondary" loading={catalog.pendingInstall === key} disabled={catalog.pendingInstall !== null} onClick={() => void catalog.installEntry(entry)} />}
          {catalog.rollbackCandidates.some(item => item.material_id === entry.material_id) && <Button variant="secondary" label={t("mat_sync_local_section_title")} onClick={() => { setHistoryMaterial(entry.material_id); setShowHistory(true); }} />}
        </div>
      };
    })} />
    {showHistory && <MaterialCloudHistoryDialog
      entries={catalog.rollbackCandidates.filter(item => historyMaterial === null || item.material_id === historyMaterial)}
      pendingRollback={catalog.pendingRollback} error={catalog.error} success={success} onDismissSuccess={dismissSuccess}
      onClose={() => setShowHistory(false)} onRollback={(entry, revision) => void catalog.rollbackEntry(entry, revision)} />}
  </>;
}
