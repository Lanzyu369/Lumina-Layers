import { useCallback, useEffect, useMemo, useRef } from "react";
import { motion } from "framer-motion";

import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { useI18n } from "../i18n/context";
import { tRuntime } from "../i18n/runtime";
import MaterialCloudCatalogCard from "./materialCloud/MaterialCloudCatalogCard";
import MaterialCloudLocalRevisions from "./materialCloud/MaterialCloudLocalRevisions";
import { CATALOG_FILTERS, catalogEntryKey } from "./materialCloud/catalogModel";
import type { CatalogFilter } from "./materialCloud/catalogModel";
import {
  MATERIAL_CATALOG_PAGE_SIZE,
  useMaterialCloudCatalog,
} from "./materialCloud/useMaterialCloudCatalog";
import Button from "./ui/Button";
import Pagination from "./ui/Pagination";
import { XIcon } from "./ui/icons";
import {
  StatusBanner,
  cardPadClass,
  cx,
  resolvePanelSurfaceClass,
  wellClass,
  wellPadClass,
} from "./ui/panelPrimitives";

const SUCCESS_AUTO_DISMISS_MS = 5_000;
const SKELETON_CARD_COUNT = 6;
const CATALOG_GRID_CLASS =
  "grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,17.5rem),1fr))]";

const filterChipClass = (active: boolean) => cx(
  "inline-flex min-h-9 items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold transition focus:outline-none focus:ring-4 focus:ring-[var(--focus-ring)]",
  active
    ? "border-blue-400 bg-blue-50 text-blue-700 dark:border-blue-400/70 dark:bg-blue-500/15 dark:text-blue-200"
    : "border-slate-200/80 bg-[var(--surface-panel)] text-slate-600 hover:border-slate-300 dark:border-slate-700/80 dark:text-slate-300 dark:hover:border-slate-600",
);

function DismissButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="inline-flex h-7 w-7 items-center justify-center rounded-md text-slate-500 transition hover:bg-slate-900/5 hover:text-slate-800 focus:outline-none focus:ring-4 focus:ring-[var(--focus-ring)] dark:text-slate-400 dark:hover:bg-slate-100/10 dark:hover:text-slate-100"
    >
      <XIcon />
    </button>
  );
}

function StatTile({
  label,
  value,
  testId,
  highlight = false,
  onClick,
}: {
  label: string;
  value: string | number;
  testId?: string;
  highlight?: boolean;
  onClick?: () => void;
}) {
  const content = (
    <>
      <span className="block text-[11px] font-medium text-slate-500 dark:text-slate-400">{label}</span>
      <span
        data-testid={testId}
        className={cx(
          "mt-1 block truncate text-lg font-semibold tabular-nums",
          highlight ? "text-blue-700 dark:text-blue-300" : "text-slate-900 dark:text-slate-50",
        )}
      >
        {value}
      </span>
    </>
  );
  if (!onClick) {
    return <div className={`${wellPadClass} min-w-0`}>{content}</div>;
  }
  return (
    <button
      type="button"
      onClick={onClick}
      className={`${wellPadClass} min-w-0 text-left transition hover:brightness-95 focus:outline-none focus:ring-4 focus:ring-[var(--focus-ring)] dark:hover:brightness-125`}
    >
      {content}
    </button>
  );
}

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
  const { t, lang } = useI18n();
  const workspace = useWorkspaceMode();
  const catalog = useMaterialCloudCatalog();
  const { dismissSuccess, success, view } = catalog;
  const listTopRef = useRef<HTMLDivElement | null>(null);

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
    return Number.isNaN(parsed.getTime()) ? value : dateFormatter.format(parsed);
  }, [dateFormatter]);

  useEffect(() => {
    if (!success) {
      return undefined;
    }
    const timer = window.setTimeout(dismissSuccess, SUCCESS_AUTO_DISMISS_MS);
    return () => window.clearTimeout(timer);
  }, [dismissSuccess, success]);

  const handlePageChange = useCallback((nextPage: number) => {
    void catalog.goToPage(nextPage);
    const anchor = listTopRef.current;
    if (anchor && typeof anchor.scrollIntoView === "function" && anchor.getBoundingClientRect().top < 0) {
      anchor.scrollIntoView({ block: "start", behavior: "smooth" });
    }
  }, [catalog]);

  const syncIndexStateLabel = catalog.status
    ? t(`mat_sync_state_${catalog.status.index_state}`)
    : t("mat_sync_state_unknown");
  const isListBusy = catalog.isLoading || catalog.isPageLoading || catalog.isSearchPending;
  const paginationDisabled = isListBusy || catalog.pendingInstall !== null;

  const renderFilterChip = (filter: CatalogFilter) => {
    const count = catalog.filterCounts[filter];
    const isActive = catalog.activeFilter === filter;
    return (
      <button
        key={filter}
        type="button"
        data-testid={`material-cloud-filter-${filter}`}
        aria-pressed={isActive}
        onClick={() => catalog.selectFilter(filter)}
        className={filterChipClass(isActive)}
      >
        <span>{t(`mat_sync_filter_${filter}`)}</span>
        {count !== undefined ? (
          <span
            className={cx(
              "rounded-full px-1.5 text-[10px] leading-4 tabular-nums",
              isActive
                ? "bg-blue-100 text-blue-700 dark:bg-blue-400/20 dark:text-blue-100"
                : "bg-slate-200/70 text-slate-600 dark:bg-slate-700/60 dark:text-slate-300",
            )}
          >
            {count}
          </span>
        ) : null}
      </button>
    );
  };

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
    if (view.entries.length === 0) {
      return (
        <div
          data-testid="material-cloud-catalog-empty"
          className={`${wellPadClass} py-10 text-center text-sm text-slate-500 dark:text-slate-400`}
        >
          {t("mat_sync_catalog_empty")}
        </div>
      );
    }
    const firstIndex = (view.page - 1) * MATERIAL_CATALOG_PAGE_SIZE + 1;
    const lastIndex = firstIndex + view.entries.length - 1;
    return (
      <>
        <div
          aria-busy={isListBusy}
          className={cx(CATALOG_GRID_CLASS, "transition-opacity", isListBusy && "pointer-events-none opacity-60")}
        >
          {view.entries.map((entry) => {
            const entryKey = catalogEntryKey(entry);
            return (
              <MaterialCloudCatalogCard
                key={entryKey}
                entry={entry}
                installState={catalog.resolveEntryInstallState(entry)}
                isInstalling={catalog.pendingInstall === entryKey}
                installDisabled={catalog.pendingInstall !== null}
                onInstall={(target) => void catalog.installEntry(target)}
              />
            );
          })}
        </div>
        <div className="flex flex-col items-center gap-3 border-t panel-divider pt-4 lg:flex-row lg:justify-between">
          <p
            data-testid="material-cloud-page-range"
            className="text-xs text-slate-500 dark:text-slate-400"
          >
            {tRuntime("mat_sync_page_range_inline", {
              from: firstIndex,
              to: lastIndex,
              total: view.total,
            })}
          </p>
          {view.pageCount > 1 ? (
            <Pagination
              data-testid="material-cloud-pagination"
              page={view.page}
              pageCount={view.pageCount}
              onPageChange={handlePageChange}
              disabled={paginationDisabled}
              showJump={view.pageCount > 7}
            />
          ) : null}
        </div>
      </>
    );
  };

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      data-testid="material-cloud-sync-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-4`}
    >
      <section className={`${cardPadClass} grid gap-4`}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
              {t("mat_sync_title")}
            </h2>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              {tRuntime("mat_sync_last_sync_inline", { time: formatDate(catalog.status?.last_sync_at) })}
            </p>
          </div>
          <Button
            label={t("mat_sync_refresh_btn")}
            variant="secondary"
            onClick={() => void catalog.refreshCatalog()}
            disabled={catalog.isLoading || catalog.isRefreshing}
            loading={catalog.isRefreshing}
            className="w-full sm:w-auto"
          />
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <StatTile
            label={t("mat_sync_catalog_count_label")}
            value={catalog.catalogTotalCount}
            testId="material-cloud-catalog-count"
          />
          <StatTile
            label={t("mat_sync_installed_count_label")}
            value={catalog.status?.installed_count ?? 0}
            testId="material-cloud-sync-installed-count"
          />
          <StatTile
            label={t("mat_sync_update_count_label")}
            value={catalog.updateCount ?? "…"}
            testId="material-cloud-update-count"
            highlight={(catalog.updateCount ?? 0) > 0}
            onClick={(catalog.updateCount ?? 0) > 0 ? () => catalog.selectFilter("updates") : undefined}
          />
          <StatTile label={t("mat_sync_index_state_label")} value={syncIndexStateLabel} />
        </div>
      </section>

      {catalog.error ? (
        <StatusBanner
          data-testid="material-cloud-sync-error"
          tone="error"
          action={<DismissButton label={t("mat_sync_dismiss_btn")} onClick={catalog.dismissError} />}
        >
          {catalog.error}
        </StatusBanner>
      ) : null}
      {catalog.notice ? (
        <StatusBanner data-testid="material-cloud-sync-notice" tone="info">
          {catalog.notice}
        </StatusBanner>
      ) : null}
      {success ? (
        <StatusBanner
          data-testid="material-cloud-sync-success"
          tone="success"
          role="status"
          action={<DismissButton label={t("mat_sync_dismiss_btn")} onClick={dismissSuccess} />}
        >
          {success}
        </StatusBanner>
      ) : null}

      <MaterialCloudLocalRevisions
        entries={catalog.rollbackCandidates}
        pendingRollback={catalog.pendingRollback}
        formatDate={formatDate}
        onRollback={(entry, revisionId) => void catalog.rollbackEntry(entry, revisionId)}
      />

      <section className={`${cardPadClass} flex flex-col gap-4`}>
        <div ref={listTopRef} className="flex flex-col gap-3 lg:flex-row lg:items-center">
          <label className="min-w-0 flex-1">
            <span className="sr-only">{t("mat_sync_search_placeholder")}</span>
            <input
              data-testid="material-cloud-search-input"
              type="search"
              value={catalog.searchQuery}
              onChange={(event) => catalog.handleSearchQueryChange(event.target.value)}
              placeholder={t("mat_sync_search_placeholder")}
              className="min-h-11 w-full rounded-[10px] border border-slate-200/80 bg-[var(--surface-panel)] px-4 py-2 text-sm text-slate-800 outline-none shadow-[var(--shadow-control)] transition-all duration-200 hover:border-slate-300 focus:border-blue-400 focus:ring-4 focus:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:text-slate-100 dark:hover:border-slate-600"
            />
          </label>
          <div
            className="flex min-w-0 flex-wrap gap-2"
            role="group"
            aria-label={t("mat_sync_filter_group_label")}
          >
            {CATALOG_FILTERS.map(renderFilterChip)}
          </div>
        </div>
        {renderCatalogBody()}
      </section>
    </motion.aside>
  );
}
